"""The game session: the one object that ties the pipeline together for one game, live or replayed.

    groups per commentator --EventExtractor--> raw events --PlayerResolver--> resolved events
        --LiveMerger (2+ commentators)--> official stream --compute_stats--> stats

A server feeds it each commentator's transcript groups as they arrive (from a LiveTranscriber, or `replay` for a saved
transcript); a dashboard reads `snapshot()`, everything shown for the game at one `version`. Extraction runs when groups arrive
(microseconds per group). Resolution and merging are recomputed by `snapshot()` when something changed; stats, unresolved names
and unmentioned players when a snapshot's are first read. `save()` and `load()` keep a session as files in a directory.
See docs/session.md.
"""

from __future__ import annotations

import collections
import copy
import dataclasses
import datetime as dt
import functools
import inspect
import itertools
import json
import logging
import math
import os
import pathlib
import re
import threading
import time
import unicodedata
from collections.abc import Callable
from typing import Any

import pydantic

import yus
from yus.processing.event_extraction import AssistedExtractor, EventExtractor, LLMAssistant
from yus.processing.event_unification import GameDescriptions, LiveMerger, MergeResult, PlayerDescription, PlayerResolver, TeamConflict, merge_streams
from yus.processing.event_unification.merge import NAME_FIELDS
from yus.processing.event_unification.players import mentions, normalize
from yus.processing.stats import GameStats, compute_stats
from yus.sports import ultimate

log = logging.getLogger("yus.session")

TIMEOUT = 6.0  # seconds without words after which an open throw becomes final (EventExtractor's timeout)
SETTLE = 20.0  # merge_streams's default `settle`, used before any commentator has an event
SETTLE_MARGIN = 2.0  # seconds of slack in settling merged events: an offset LiveMerger refines, a word committed just before its horizon
TOLERANCE = inspect.signature(merge_streams).parameters["tolerance"].default  # how far apart merging pairs events, unless set
ABSENT_S = 30.0  # a commentator whose transcript has had no words for this long does not hold settling back


class CommentatorState(pydantic.BaseModel):
    """One commentator, as a snapshot shows them."""

    name: str
    focus_team: str | None = pydantic.Field(None, description="The team this commentator follows (any of its names); None for the whole game.")
    groups: int = pydantic.Field(0, description="Transcript groups received.")
    final_count: int = pydantic.Field(0, description="How many of this commentator's raw events are final.")
    pending_text: str = pydantic.Field("", description="Live transcription's guess at what is being said, not committed yet (display only).")


class HeardAssociation(pydantic.BaseModel):
    """A spoken identification ("oh, red shorts is kaia") that event extraction found, and the player it was recorded as."""

    commentator: str
    team: str | None
    description: str = pydantic.Field(..., description='What the commentator called the player, e.g. "red shorts".')
    name: str = pydantic.Field(..., description='Who they said it is, as spoken, e.g. "kaia".')
    player: str | None = pydantic.Field(None, description="The roster player the description was recorded as; None if it could not be recorded.")


class _Views:
    """What a snapshot computes when first read, shared by the snapshots of one computation (stats take about 10 ms)."""

    def __init__(self, official: yus.EventStream, teams: list[yus.Team], settled: int, resolver: PlayerResolver):
        self.official, self.teams, self.settled, self.resolver = official, teams, settled, resolver
        self._lock = threading.Lock()
        self._values: dict[str, Any] = {}

    def get(self, key: str, compute: Callable[[], Any]) -> Any:
        with self._lock:
            if key not in self._values:
                self._values[key] = compute()
            return self._values[key]

    def __getstate__(self) -> dict[str, Any]:  # copy.deepcopy and pickle: a lock can't be copied
        with self._lock:
            return {key: value for key, value in self.__dict__.items() if key != "_lock"} | {"_values": dict(self._values)}

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__dict__.update(state)
        self._lock = threading.Lock()


@dataclasses.dataclass(eq=False)
class GameSnapshot:
    """The game as its session had it at one `version`. Read-only: its objects are shared with the session and later snapshots.

    `official.events[:settled_count]` are final as far as the commentary goes; later ones are provisional and may change or go.
    A description (`describe()`, or one a commentator speaks) re-resolves names in every event, settled or not. `late` lists the
    merged events left out because a commentator reported them after the play they describe had settled without them.
    `stats`, `score`, `summary`, `unresolved`, `unmentioned` and `team_conflicts` are computed when first read, then kept. A
    snapshot can be deep-copied and pickled; `dataclasses.asdict` gives its fields (not the computed ones).
    """

    version: int
    game: yus.Game
    commentators: list[CommentatorState]
    transcripts: dict[str, list[yus.TranscriptGroup]]  # per commentator: the groups received
    raw: dict[str, yus.EventStream]  # per commentator: events as extracted, names as spoken; final ones first
    resolved: dict[str, yus.EventStream]  # per commentator: the raw events with names resolved by PlayerResolver
    official: yus.EventStream  # one commentator: its resolved stream; several: the merged stream. Teams by their first names
    settled_count: int
    associations: list[HeardAssociation]
    descriptions: GameDescriptions  # every description in effect: given, described, and heard
    merge: MergeResult | None  # with several commentators: offsets, pairs, conflicts, name links
    finished: bool
    views: dataclasses.InitVar[_Views]
    late: list[yus.Event] = dataclasses.field(default_factory=list, kw_only=True)  # merged events left out of `official`: reported after their play had settled

    def __post_init__(self, views: _Views) -> None:
        self._views = views

    @property
    def stats(self) -> GameStats:
        """compute_stats of the official stream, with events from `settled_count` on flagged provisional."""
        views = self._views
        return views.get("stats", lambda: compute_stats(views.official, views.teams, provisional_from=views.settled))

    @property
    def score(self) -> dict[str, int]:
        """Goals per team (first team names), as the stats count them."""
        return self.stats.score

    @property
    def summary(self) -> str:
        """One line, e.g. "Dump & Drizzle 14, Category 5 9 (point 24 in play)"."""
        return self.stats.summary()

    @property
    def unresolved(self) -> list[tuple[str, str, int]]:
        """(team, name, mentions) for each name in the official stream that still needs a person to identify it: names that are
        not roster players (labels of unknown players, and names nobody described), most mentioned first, as PlayerResolver.unresolved.
        Names resolved to another team's player are in `team_conflicts` instead."""
        views = self._views
        return views.get("unresolved", lambda: _unresolved(views.official, views.resolver))

    @property
    def unmentioned(self) -> dict[str, list[str]]:
        """Roster players no official event names, per team: likely identities for the unresolved names."""
        views = self._views
        return views.get("unmentioned", lambda: _unmentioned(views.official, views.resolver))

    @functools.cached_property
    def team_conflicts(self) -> dict[str, list[TeamConflict]]:
        """Per commentator, the raw events with a name that resolved to another team's player (PlayerResolver.team_conflicts):
        the event's team is likely wrong, or the name needs a description for its own team."""
        resolver = PlayerResolver(self.game.teams, self.descriptions)
        return {name: resolver.team_conflicts(stream, name) for name, stream in self.raw.items()}

    @property
    def provisional(self) -> list[yus.Event]:
        """The official events that may still change."""
        return self.official.events[self.settled_count :]


@dataclasses.dataclass(eq=False)
class _Commentator:
    name: str
    focus_team: str | None
    file: str  # file name stem under transcripts/ and events/
    transcript: yus.Transcript
    extractor: EventExtractor | AssistedExtractor
    pending_text: str = ""
    advanced: dt.datetime | None = None  # the latest time passed to advance()
    aware: bool | None = None  # whether the transcript's times carry a UTC offset; None until the first word
    spoke: tuple[dt.datetime, dt.datetime] | None = None  # start and end of the last group with words
    heard: int = 0  # associations of the extractor already recorded
    resolver: PlayerResolver | None = None  # what `resolved` was resolved with
    resolved: list[yus.Event] = dataclasses.field(default_factory=list)  # the final raw events, resolved
    named: list[yus.Event] = dataclasses.field(default_factory=list)  # the same with teams by first name: a lone commentator's official events

    def awareness(self) -> bool | None:
        """Whether this commentator's times carry a UTC offset: as their words, else as their last advance(); None if unknown."""
        return self.aware if self.aware is not None or self.advanced is None else self.advanced.utcoffset() is not None

    def progress(self, timeout: float | None) -> dt.datetime | None:
        """The earliest time (theirs) at which an event still to come from this commentator can be; None while unknown (no words,
        no advance). An event can start in the last group (a name ending it may be the subject of the next group), unless more
        than `timeout` seconds without words followed it."""
        if self.spoke is None:
            return self.advanced
        start, end = self.spoke
        if self.advanced is not None and timeout is not None and (self.advanced - end).total_seconds() > timeout:
            return self.advanced
        return start

    def absent(self) -> bool:
        """Whether their transcript is complete for more than ABSENT_S past their last words (or they never spoke): they then do
        not hold settling back. What they say later about play that settled meanwhile does not change it."""
        if self.advanced is None:
            return False
        return self.spoke is None or (self.advanced - self.spoke[1]).total_seconds() > ABSENT_S


@dataclasses.dataclass(eq=False)
class _Settled:
    """The merged events settled so far, kept as they were but for names (resolved by `resolver`), and the raw events they were
    made from: (commentator index, raw index). `late`: raw events of late reports left out so far."""

    resolver: PlayerResolver
    merger: LiveMerger
    events: list[yus.Event] = dataclasses.field(default_factory=list)
    pairs: list[list[int | None]] = dataclasses.field(default_factory=list)
    items: set[tuple[int, int]] = dataclasses.field(default_factory=set)
    late: set[tuple[int, int]] = dataclasses.field(default_factory=set)

    def add(self, events: list[yus.Event], pairs: list[list[int | None]]) -> None:
        self.events += events
        self.pairs += pairs
        self.items |= {(k, i) for pair in pairs for k, i in enumerate(pair) if i is not None}

    def holds(self, pair: list[int | None]) -> bool:
        return any((k, i) in self.items for k, i in enumerate(pair) if i is not None)


@dataclasses.dataclass(eq=False)
class _Bounds:
    settle: float  # LiveMerger's `settle` for the next merge
    quiet: dt.datetime | None  # merged events before this (the reference clock) settle; None: only as the merge settles them
    absent: list[bool]  # per commentator: whether they hold settling back


@dataclasses.dataclass(eq=False)
class _Computed:
    data_version: int
    transcripts: dict[str, list[yus.TranscriptGroup]]
    raw: dict[str, yus.EventStream]
    resolved: dict[str, yus.EventStream]
    official: yus.EventStream
    settled: int
    merge: MergeResult | None
    late: list[yus.Event]
    associations: list[HeardAssociation]
    descriptions: GameDescriptions
    views: _Views


class _SavedCommentator(pydantic.BaseModel):
    name: str
    file: str
    focus_team: str | None = None
    pending_text: str = ""
    advanced: dt.datetime | None = None
    llm_answers: dict[int, yus.EventStream | None] = pydantic.Field({}, description="AssistedExtractor.answers: per group sent, the LLM's events, or null.")


class _SavedSession(pydantic.BaseModel):
    """session.json: what the other files don't say."""

    version: int
    timeout: float | None
    finished: bool = False
    commentators: list[_SavedCommentator] = []
    associations: list[HeardAssociation] = []
    merger_segments: list[list[tuple[int, float]] | None] | None = pydantic.Field(None, description="LiveMerger.segments as the last merge started.")
    settled: int = pydantic.Field(0, description="Merged events kept settled (see GameSession._official).")
    settled_events: yus.EventStream | None = pydantic.Field(None, description="Those events, as they settled.")
    settled_pairs: list[list[int | None]] | None = pydantic.Field(None, description="Per settled event, its raw event's index in each commentator's stream.")


class GameSession:
    """One game's pipeline, fed by any number of commentators, live or replayed. Thread-safe: every method takes one lock.

    session = GameSession(game, descriptions, directory)
    session.add_commentator("Gavin", focus_team=None)
    session.add_groups("Gavin", groups)          # as LiveTranscriber completes them
    session.set_pending_text("Gavin", text)      # its latest uncommitted guess, for display
    session.advance(horizon, "Gavin")            # transcript complete up to horizon: a throw open > timeout s becomes final
    snap = session.snapshot()                    # cached per `version`
    snap.official.events[: snap.settled_count]   # final; the rest provisional
    snap.stats.team_box, snap.summary, snap.unresolved
    session.describe("white", ["red shorts"], player="Kaia Mann")   # fixes earlier events too
    session.finish(); session.save()             # GameSession.load(directory) picks it up again

    Each commentator's groups go to their own EventExtractor (`timeout` seconds of silence finalize an open throw). Spoken
    identifications it finds ("red shorts is kaia") are recorded at once as descriptions for that commentator's stream.
    One commentator's resolved stream is the official stream; with more, a LiveMerger merges them, the first commentator added
    being the clock reference. Merged events settle only up to the slowest commentator's progress (their last group, or their
    last advance() after a silence), so advance every commentator as their transcriber reports progress. Add every commentator
    before feeding groups: one added later can unsettle settled events.

    With `llm`, groups the rules may have misread also go to that model (an AssistedExtractor per commentator). Its answers are
    applied by add_groups(), advance() and snapshot(); a group's events stay provisional until its answer comes or the budget
    runs out. save() keeps what was decided, so load() does not ask again.
    """

    def __init__(
        self,
        game: yus.Game,
        descriptions: GameDescriptions | None = None,
        directory: pathlib.Path | str | None = None,
        *,
        timeout: float | None = TIMEOUT,
        llm: LLMAssistant | None = None,
    ):
        self.game = yus.Game(sport=game.sport, when=game.when, teams=list(game.teams))
        self.directory = pathlib.Path(directory) if directory is not None else None
        self.timeout = timeout
        self.llm = llm
        self._resolver = PlayerResolver(self.game.teams, descriptions)  # replaced, never changed, so that snapshots can keep it
        self._lock = threading.RLock()
        self._commentators: dict[str, _Commentator] = {}
        self._associations: list[HeardAssociation] = []
        self._merger: LiveMerger | None = None
        self._merger_before: list[list[tuple[int, float]] | None] | None = None  # its segments as the last merge started
        self._settled: _Settled | None = None  # merged events settled so far, with that resolver and merger
        self._restore = 0  # merged events settled when a session.json without them was saved
        self._finished = False
        self._version = 0
        self._floor = 0  # the least version the next change may take (load() sets it past any version given out before)
        self._data_version = 0
        self._computed: _Computed | None = None
        self._snapshot: GameSnapshot | None = None

    # ------------------------------------------------------------------ state

    @property
    def version(self) -> int:
        """Increases on every change, also across save() and load()."""
        return self._version

    @property
    def commentators(self) -> list[str]:
        with self._lock:
            return list(self._commentators)

    @property
    def descriptions(self) -> GameDescriptions:
        """Every description in effect (given, described, heard), in the order recorded. Read-only."""
        return self._resolver.descriptions

    @property
    def finished(self) -> bool:
        return self._finished

    # ------------------------------------------------------------------ input

    def add_commentator(self, name: str, focus_team: str | None = None) -> None:
        """Add a commentator; `focus_team` (any name of a team) if they follow one team, which then wins their merge conflicts."""
        with self._lock:
            self._check_open()
            if not name or name in self._commentators:
                raise ValueError(f"Commentator {name!r} is {'already added' if name else 'not named'}")
            if focus_team is not None and self._resolver.team_index(focus_team) is None:
                raise ValueError(f"No team is called {focus_team!r}; teams: {[team.names for team in self.game.teams]}")
            taken = {_file_key(c.file) for c in self._commentators.values()}
            stem = _stem(name) or "commentator"
            file = next(f for f in (stem if i == 1 else f"{stem}-{i}" for i in itertools.count(1)) if _file_key(f) not in taken)
            transcript = yus.Transcript(game=self.game, commentator=name)
            self._commentators[name] = _Commentator(name, focus_team, file, transcript, self._extractor())
            focus = [c.focus_team for c in self._commentators.values()]
            if self._merger is not None:
                self._merger.options["focus"] = focus
            elif len(self._commentators) > 1:
                self._merger = LiveMerger(focus=focus, teams=self.game.teams)
            self._changed(data=True)

    def add_groups(self, commentator: str, groups: list[yus.TranscriptGroup]) -> None:
        """Add a commentator's next transcript groups, in order (copies are kept; the groups are left as they are). Raises
        ValueError, adding none, if their word times carry a UTC offset and the commentator's earlier ones don't, or the reverse."""
        with self._lock:
            c = self._get(commentator)
            self._check_open()
            _awareness(groups, c.aware, commentator)
            polled = self._poll()
            fed = 0
            try:
                for group in groups:
                    kept = yus.TranscriptGroup.model_validate(group.model_dump())
                    self._feed(c, kept)
                    fed += 1
            finally:
                if fed:
                    self._hear(c)
                if fed or polled:
                    self._changed(data=True)

    def advance(self, now: dt.datetime, commentator: str | None = None) -> None:
        """Note that a commentator's transcript (None: every commentator's) is complete up to `now`, transcript time: a throw left
        open for more than `timeout` seconds without words becomes final. With several commentators, it also lets merged events
        settle up to there. `now` may be naive or carry a UTC offset whatever the transcripts' times are (naive times are local)."""
        with self._lock:
            targets = [self._get(commentator)] if commentator is not None else list(self._commentators.values())
            if self._finished:
                return
            zone = self._zone()
            changed = self._poll()
            try:
                for c in targets:
                    when = _as(now, c.awareness(), zone)
                    before = self._state(c)
                    c.extractor.advance(when)
                    c.advanced = when if c.advanced is None else max(c.advanced, when)
                    changed |= self._state(c) != before
            finally:
                if changed:
                    self._changed(data=True)

    def describe(self, team: str, descriptions: list[str] | str, player: str | None = None, label: str | None = None, commentator: str | None = None) -> PlayerDescription:
        """Record that `descriptions` all mean one player of `team`: `player`, or an unknown person called `label` (PlayerResolver.describe).
        It applies to every event, earlier ones too. A commentator's own record beats shared ones (commentator=None) for their stream,
        so to correct what a commentator was heard to say, pass that commentator. Raises ValueError (unknown team, player or commentator)."""
        with self._lock:
            if commentator is not None:
                self._get(commentator)
            descriptions = [descriptions] if isinstance(descriptions, str) else list(descriptions)
            record = self._record(PlayerDescription(team=team, descriptions=descriptions, player=player, label=label, commentator=commentator))
            self._changed(data=True)
            return record

    def set_pending_text(self, commentator: str, text: str) -> None:
        """Show what live transcription guesses a commentator is saying (not used for events)."""
        if not isinstance(text, str):
            raise TypeError(f"Pending text must be a str, not {type(text).__name__}")
        with self._lock:
            c = self._get(commentator)
            self._check_open()
            if c.pending_text != text:
                c.pending_text = text
                self._changed(data=False)

    def finish(self) -> None:
        """End of the game: every event becomes final, and no more commentators, groups or pending text are taken. With `llm`,
        it first waits for the answers still due, each at most until its budget runs out."""
        with self._lock:
            if self._finished:
                return
            for c in self._commentators.values():
                c.extractor.finish()
                c.pending_text = ""
            self._finished = True
            self._changed(data=True)

    # ------------------------------------------------------------------ output

    def snapshot(self) -> GameSnapshot:
        """The game now. The same object until the next change."""
        with self._lock:
            if self._poll():
                self._changed(data=True)
            if self._snapshot is not None and self._snapshot.version == self._version:
                return self._snapshot
            if self._computed is None or self._computed.data_version != self._data_version:
                self._computed = self._compute()
            done = self._computed
            commentators = [
                CommentatorState(name=c.name, focus_team=c.focus_team, groups=len(c.transcript.groups), final_count=c.extractor.final_count, pending_text=c.pending_text)
                for c in self._commentators.values()
            ]
            self._snapshot = GameSnapshot(
                version=self._version,
                game=self.game,
                commentators=commentators,
                transcripts=done.transcripts,
                raw=done.raw,
                resolved=done.resolved,
                official=done.official,
                settled_count=done.settled,
                associations=done.associations,
                descriptions=done.descriptions,
                merge=done.merge,
                finished=self._finished,
                views=done.views,
                late=done.late,
            )
            return self._snapshot

    def _compute(self) -> _Computed:
        transcripts: dict[str, list[yus.TranscriptGroup]] = {}
        raw: dict[str, yus.EventStream] = {}
        resolved: dict[str, yus.EventStream] = {}
        finals = []
        for c in self._commentators.values():
            events, final = c.extractor.events, c.extractor.final_count
            transcripts[c.name] = list(c.transcript.groups)
            raw[c.name] = yus.EventStream(game=self.game, events=events)
            resolved[c.name] = yus.EventStream(game=self.game, events=self._resolve(c, events, final))
            finals.append(final)
        official, settled, merge, late = self._official(list(resolved.values()), finals)
        if self._finished:
            settled = len(official.events)
        before = self._computed
        if before is not None and before.settled == settled and before.official.events == official.events:
            official, views = before.official, before.views  # nothing shown changed: keep the stats
        else:
            views = _Views(official, self.game.teams, settled, self._resolver)
        return _Computed(self._data_version, transcripts, raw, resolved, official, settled, merge, late, list(self._associations), self._resolver.descriptions, views)

    def _resolve(self, c: _Commentator, events: list[yus.Event], final: int) -> list[yus.Event]:
        """The commentator's raw events resolved: final ones once (until a description changes), provisional ones every time."""
        if c.resolver is not self._resolver:
            c.resolver, c.resolved, c.named = self._resolver, [], []
        c.resolved += [self._resolver.resolve_event(event, c.name) for event in events[len(c.resolved) : final]]
        return c.resolved + [self._resolver.resolve_event(event, c.name) for event in events[final:]]

    def _official(self, streams: list[yus.EventStream], finals: list[int]) -> tuple[yus.EventStream, int, MergeResult | None, list[yus.Event]]:
        """The official stream, how many of its events are settled, the merge (with several commentators), and the merged
        events left out as late reports."""
        if not streams:
            return yus.EventStream(game=self.game), 0, None, []
        if self._merger is None:
            (c,), final = self._commentators.values(), finals[0]
            c.named += [self._team_named(event) for event in c.resolved[len(c.named) :]]
            return yus.EventStream(game=self.game, events=c.named + [self._team_named(event) for event in streams[0].events[final:]]), final, None, []
        self._merger_before = copy.deepcopy(self._merger.segments)
        bounds = self._bounds(streams, finals)
        self._merger.options["settle"] = bounds.settle
        merge = self._merger.merge(streams)
        held = [len(stream.events) if gone else final for stream, final, gone in zip(streams, finals, bounds.absent)]  # final, or absent
        done = self._settled
        if done is None or done.merger is not self._merger:
            done = self._settled = _Settled(self._resolver, self._merger)
            if self._restore:  # loaded from a session.json that kept only their number
                count, self._restore = self._restore, 0
                if count <= len(merge.stream.events) and _settled(merge, held, count) == count:
                    done.add(merge.stream.events[:count], merge.pairs[:count])
        elif done.resolver is not self._resolver:
            self._rename(done, merge)
        # Settled events stay as they settled. The merge's other events follow them, but for those after the last merged event
        # holding a settled raw event that come before it: late reports of play that settled without them.
        last = max((m for m, pair in enumerate(merge.pairs) if done.holds(pair)), default=-1)
        rest = [m for m in range(last + 1, len(merge.pairs)) if not done.holds(merge.pairs[m])]
        late = [m for m in range(last) if not done.holds(merge.pairs[m])]
        self._note_late(done, merge, late)
        limit, zone = _settled(merge, held), self._zone()
        n = 0
        while n < len(rest) and (rest[n] < limit or self._quiet(merge, rest[n], held, bounds.quiet, zone)):
            n += 1
        floor = done.events[-1].when if done.events else None
        tail = [_not_before(merge.stream.events[m], floor, zone) for m in rest]
        done.add(tail[:n], [merge.pairs[m] for m in rest[:n]])
        return yus.EventStream(game=self.game, events=done.events + tail[n:]), len(done.events), merge, [merge.stream.events[m] for m in late]

    def _rename(self, done: _Settled, merge: MergeResult) -> None:
        """A description changed: the settled events keep their place and everything else, but their names are resolved again.
        Each takes the names of the merged event made from the same raw events, else each name is resolved again from the raw
        event it came from (a late report, left out, may now pair with it)."""
        merged = {tuple(pair): event for pair, event in zip(merge.pairs, merge.stream.events)}
        commentators = [(c.name, c.extractor.events) for c in self._commentators.values()]
        for j, (event, pair) in enumerate(zip(done.events, done.pairs)):
            names = {field: name for field in NAME_FIELDS if (name := getattr(event, field, None)) is not None}
            same = merged.get(tuple(pair))
            if same is not None:
                update = {field: getattr(same, field, name) for field, name in names.items()}
            else:
                update = {}
                for field, name in names.items():
                    for (commentator, raw), i in zip(commentators, pair):
                        if i is not None and getattr(done.resolver.resolve_event(raw[i], commentator), field, None) == name:
                            update[field] = getattr(self._resolver.resolve_event(raw[i], commentator), field, name)
                            break
            if update := {field: name for field, name in update.items() if name != names[field]}:
                done.events[j] = event.model_copy(update=update)
        done.resolver = self._resolver

    def _note_late(self, done: _Settled, merge: MergeResult, late: list[int]) -> None:
        """Log the late reports left out for the first time."""
        names = list(self._commentators)
        new = []
        for m in late:
            items = {(k, i) for k, i in enumerate(merge.pairs[m]) if i is not None}
            if items - done.late:
                event = merge.stream.events[m]
                new.append(f"{type(event).__name__} at {event.when:%H:%M:%S} from {', '.join(names[k] for k, _ in sorted(items))}")
            done.late |= items
        if new:
            log.warning("Left out %d event(s) reported after their play had settled: %s", len(new), "; ".join(new))

    @staticmethod
    def _quiet(merge: MergeResult, m: int, held: list[int], bound: dt.datetime | None, zone: dt.tzinfo | None) -> bool:
        """Whether merged event m settles whatever follows it: it is before `bound`, and made of final raw events."""
        if bound is None or not _before(merge.stream.events[m].when, bound, zone):
            return False
        return all(index is None or index < final for index, final in zip(merge.pairs[m], held))

    def _team_named(self, event: yus.Event) -> yus.Event:
        """The event with its team named by the team's first name, as merged events are."""
        index = self._resolver.team_index(event.team) if isinstance(event, ultimate.UltimateEvent) else None
        if index is None or (name := self.game.teams[index].names[0]) == event.team:
            return event
        return event.model_copy(update={"team": name})

    def _bounds(self, streams: list[yus.EventStream], finals: list[int]) -> _Bounds:
        """How far merged events can settle. A commentator's events still to come are no earlier than their progress, and their
        provisional raw events may still change; the earliest of these, over the commentators, is the bottom.

        `settle`, LiveMerger's for the next merge: how many seconds before its latest event the bottom is, plus SETTLE_MARGIN.
        Negative once every commentator's progress has passed the latest event. Infinite while a commentator's progress is
        unknown. `quiet`: the merge's tolerance plus SETTLE_MARGIN before the bottom (no event still to come pairs with an
        event before it), once every offset is kept: merged events before it settle without waiting for the events after them
        (the next throw, which can repair an outcome; a neighbour they may swap with). Absent commentators (no words for
        ABSENT_S) are left out, unless all are."""
        assert self._merger is not None
        commentators = list(self._commentators.values())
        absent = [c.absent() for c in commentators]
        absent = [False] * len(absent) if all(absent) else absent
        segments = self._merger.segments + [None] * (len(streams) - len(self._merger.segments))
        latest: list[tuple[dt.datetime, float]] = []
        earliest: list[tuple[dt.datetime, float]] = []
        for c, stream, final, segs, gone in zip(commentators, streams, finals, segments, absent):
            offsets = [offset for _, offset in segs] if segs else [0.0]  # an estimated offset: merging allows for it
            if stream.events:
                latest.append((max(event.when for event in stream.events), max(offsets)))
            if gone:
                continue
            progress = c.progress(self.timeout)
            if progress is None:
                return _Bounds(math.inf, None, absent)
            earliest.append((min([progress, *(event.when for event in stream.events[final:])]), offsets[-1]))
        if not latest:
            return _Bounds(SETTLE, None, absent)
        clock = _clock([when for when, _ in latest + earliest], self._zone())
        top = max(clock(when) + dt.timedelta(seconds=offset) for when, offset in latest)
        bottom = min(clock(when) + dt.timedelta(seconds=offset) for when, offset in earliest)
        settle = (top - bottom).total_seconds() + SETTLE_MARGIN + 0.001  # an event exactly at the bound is not settled, whatever the rounding
        kept = all(segs is not None for segs, gone in zip(segments[1:], absent[1:]) if not gone)
        margin = self._merger.options.get("tolerance", TOLERANCE) + SETTLE_MARGIN
        return _Bounds(settle, bottom - dt.timedelta(seconds=margin) if kept else None, absent)

    # ------------------------------------------------------------------ persistence

    def save(self) -> None:
        """Write the session to its directory: game.json (sport, when, teams), descriptions.json, transcripts/<commentator>.json,
        events/<commentator>.json (raw), official.json (merged), and session.json (the rest)."""
        with self._lock:
            if self.directory is None:
                raise ValueError("No directory to save to: pass one to GameSession()")
            snap = self.snapshot()
            _write_json(self.directory / "game.json", self.game.model_dump(mode="json", include={"sport", "when", "teams"}))
            _write_json(self.directory / "descriptions.json", snap.descriptions.model_dump(mode="json", exclude_none=True))
            for c in self._commentators.values():
                _write_json(self.directory / "transcripts" / f"{c.file}.json", c.transcript.model_dump(mode="json"))
                _write_json(self.directory / "events" / f"{c.file}.json", snap.raw[c.name].model_dump(mode="json"))
            _write_json(self.directory / "official.json", snap.official.model_dump(mode="json"))
            saved = _SavedSession(
                version=self._version,
                timeout=self.timeout,
                finished=self._finished,
                commentators=[
                    _SavedCommentator(name=c.name, file=c.file, focus_team=c.focus_team, pending_text=c.pending_text, advanced=c.advanced, llm_answers=_answers(c.extractor))
                    for c in self._commentators.values()
                ],
                associations=self._associations,
                merger_segments=self._merger_before,
                settled=len(self._settled.events) if self._settled is not None else 0,
                settled_events=yus.EventStream(events=self._settled.events) if self._settled is not None else None,
                settled_pairs=self._settled.pairs if self._settled is not None else None,
            )
            _write_json(self.directory / "session.json", saved.model_dump(mode="json"))

    @classmethod
    def load(cls, directory: pathlib.Path | str, *, llm: LLMAssistant | None = None) -> GameSession:
        """The session saved in `directory`, as it was: transcripts are fed again (events/ and official.json are not read back), with
        the LLM's saved answers. `llm` answers the groups to come (and any whose answer was still due when it was saved).
        Without session.json, each transcripts/*.json is a commentator (its `commentator`, else the file name), in file name order."""
        directory = pathlib.Path(directory)
        game = yus.Game.model_validate_json((directory / "game.json").read_text())
        path = directory / "descriptions.json"
        descriptions = GameDescriptions.model_validate_json(path.read_text()) if path.exists() else None
        saved, transcripts = _read_saved(directory)
        session = cls(game, descriptions, directory, timeout=saved.timeout, llm=llm)
        session._associations = list(saved.associations)
        for entry in saved.commentators:
            if _stem(entry.file) != entry.file or not entry.file:
                raise ValueError(f"Not a file name made by save(): {entry.file!r} ({directory / 'session.json'})")
            session.add_commentator(entry.name, entry.focus_team)
            c = session._commentators[entry.name]
            c.file, c.pending_text, c.heard = entry.file, entry.pending_text, sum(a.commentator == entry.name for a in saved.associations)
            if entry.llm_answers:
                c.extractor = session._extractor({k: stream.events if stream is not None else None for k, stream in entry.llm_answers.items()})
            path = directory / "transcripts" / f"{entry.file}.json"
            transcript = transcripts[entry.file] if entry.file in transcripts else yus.Transcript.model_validate_json(path.read_text())
            _awareness(transcript.groups, None, entry.name)
            for group in transcript.groups:
                session._feed(c, group)
            session._hear(c)  # only identifications not heard before
            if entry.advanced is not None:
                c.advanced = _as(entry.advanced, c.awareness(), session._zone())
                c.extractor.advance(c.advanced)
        if saved.finished:
            for c in session._commentators.values():
                c.extractor.finish()
            session._finished = True
        session._restore_merger(saved)
        session._version, session._floor = saved.version, time.time_ns() // 1000  # past any version given out before, saved or not
        if len(session._associations) > len(saved.associations):
            session._changed(data=True)  # heard more: an extractor changed
        session.snapshot()  # merge now, so that the merger goes on from where it was
        return session

    def _restore_merger(self, saved: _SavedSession) -> None:
        """Put the merger back as its last merge started, with the merged events settled then."""
        if self._merger is None or saved.merger_segments is None:
            return
        self._merger.segments = [list(segments) if segments is not None else None for segments in saved.merger_segments]
        if saved.settled_events is not None and saved.settled_pairs is not None:
            self._settled = _Settled(self._resolver, self._merger)
            self._settled.add(saved.settled_events.events, saved.settled_pairs)
        else:
            self._restore = saved.settled

    # ------------------------------------------------------------------ internals

    def _extractor(self, answers: dict[int, list[yus.Event] | None] | None = None) -> EventExtractor | AssistedExtractor:
        """A new commentator's extractor: assisted by the LLM when there is one, or when saved answers are to be replayed."""
        extractor = EventExtractor(self.game.teams, timeout=self.timeout)
        return AssistedExtractor(extractor, self.llm, answers=answers) if self.llm is not None or answers else extractor

    def _poll(self) -> bool:
        """Apply the LLM answers that came in; True if any commentator's events changed."""
        changed = False
        for c in self._commentators.values():
            if isinstance(c.extractor, AssistedExtractor):
                changed |= c.extractor.poll()
        return changed

    def _get(self, name: str) -> _Commentator:
        if name not in self._commentators:
            raise ValueError(f"Unknown commentator {name!r}; add_commentator() first. Commentators: {list(self._commentators)}")
        return self._commentators[name]

    def _check_open(self) -> None:
        if self._finished:
            raise RuntimeError("The session is finished")

    def _changed(self, data: bool) -> None:
        self._version, self._floor = max(self._version + 1, self._floor), 0
        if data:
            self._data_version += 1

    def _feed(self, c: _Commentator, group: yus.TranscriptGroup) -> None:
        """Give a group (kept as it is) to the commentator's extractor and transcript."""
        group.transcript = c.transcript
        c.extractor.feed(group)
        c.transcript.groups.append(group)
        if group.words:
            if c.aware is None:
                c.aware = group.words[0].start.utcoffset() is not None
                c.advanced = _as(c.advanced, c.aware, self._zone()) if c.advanced is not None else None
            c.spoke = (group.words[0].start, max(word.start + word.duration for word in group.words))

    def _state(self, c: _Commentator) -> tuple[int, dt.datetime | None]:
        """What advance() can change that a snapshot shows: final events and, when merging, how far merged events can settle."""
        return c.extractor.final_count, c.progress(self.timeout) if self._merger is not None else None

    def _zone(self) -> dt.tzinfo | None:
        """The zone naive times are taken to be in when compared with times that carry a UTC offset, as merging does: that of the
        first commentator whose times have an offset other than UTC, else None (this system's zone)."""
        for c in self._commentators.values():
            if c.spoke is not None and c.spoke[0].utcoffset() not in (None, dt.timedelta(0)):
                return c.spoke[0].tzinfo
        return None

    def _record(self, description: PlayerDescription) -> PlayerDescription:
        """Add a description to a new resolver (snapshots keep the old one) and use it from now on."""
        resolver = PlayerResolver(self.game.teams, self._resolver.descriptions)
        record = resolver.add(description)
        self._resolver = resolver
        return record

    def _hear(self, c: _Commentator) -> None:
        """Record the commentator's new spoken identifications as descriptions for their stream."""
        for found in c.extractor.associations[c.heard :]:
            player = None
            try:
                name = self._resolver.resolve(found.name, found.team, c.name)
                if found.team and name:
                    player = self._record(PlayerDescription(team=found.team, descriptions=[found.description], player=name, commentator=c.name)).player
            except ValueError:  # the name means a label, not a roster player
                pass
            self._associations.append(HeardAssociation(commentator=c.name, team=found.team, description=found.description, name=found.name, player=player))
        c.heard = len(c.extractor.associations)


def _answers(extractor: EventExtractor | AssistedExtractor) -> dict[int, yus.EventStream | None]:
    """What to save of an extractor's LLM answers."""
    if not isinstance(extractor, AssistedExtractor):
        return {}
    return {k: yus.EventStream(events=events) if events is not None else None for k, events in extractor.answers.items()}


def _settled(merge: MergeResult, finals: list[int], count: int | None = None) -> int:
    """The merge's settled count (or `count`), cut before the first merged event made from a provisional raw event (one the
    extractor may revise)."""
    for m, pair in enumerate(merge.pairs[: merge.settled if count is None else count]):
        if any(index is not None and index >= final for index, final in zip(pair, finals)):
            return m
    return merge.settled if count is None else count


def _before(when: dt.datetime, bound: dt.datetime, zone: dt.tzinfo | None) -> bool:
    """when < bound, as naive local times in `zone` if only one of them carries a UTC offset."""
    if (when.utcoffset() is None) != (bound.utcoffset() is None):
        when, bound = _as(when, False, zone), _as(bound, False, zone)
    return when < bound


def _not_before(event: yus.Event, floor: dt.datetime | None, zone: dt.tzinfo | None) -> yus.Event:
    """The event, moved to `floor` if it is earlier (merged events keep their order)."""
    return event.model_copy(update={"when": floor}) if floor is not None and _before(event.when, floor, zone) else event


def _unresolved(stream: yus.EventStream, resolver: PlayerResolver) -> list[tuple[str, str, int]]:
    """PlayerResolver.unresolved of a stream whose names are resolved already. Resolving them again could take a label for a
    roster player (an unknown player labelled "Kaia" for Kaia Mann)."""
    forms: dict[tuple[int, str], collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for team, name in mentions(stream):
        index = resolver.team_index(team)
        if index is not None and name not in resolver.teams[index].players and _moved(index, name, resolver) is None:
            forms[(index, normalize(name))][name] += 1
    found = [(resolver.teams[index].names[0], counts.most_common(1)[0][0], counts.total()) for (index, _), counts in forms.items()]
    return sorted(found, key=lambda item: -item[2])


def _unmentioned(stream: yus.EventStream, resolver: PlayerResolver) -> dict[str, list[str]]:
    """PlayerResolver.unmentioned_players of a stream whose names are resolved already."""
    mentioned = set()
    for team, name in mentions(stream):
        index = resolver.team_index(team)
        moved = None if index is None else _moved(index, name, resolver)
        mentioned.add((index if moved is None else moved, name))
    teams = resolver.teams
    return {team.names[0] if team.names else f"team {i + 1}": [player for player in team.players if (i, player) not in mentioned] for i, team in enumerate(teams)}


def _moved(index: int, name: str, resolver: PlayerResolver) -> int | None:
    """The other team whose player a resolved name in an event of team `index` is: resolution moved it there (a team conflict).
    A team without a roster keeps its names."""
    teams = resolver.teams
    if not teams[index].players or name in teams[index].players:
        return None
    found = [i for i, team in enumerate(teams) if i != index and name in team.players]
    return found[0] if len(found) == 1 else None


def _stem(name: str) -> str:
    """A file name stem for a commentator's name: "B / Other" -> "B_Other"."""
    return re.sub(r"[^\w.-]+", "_", unicodedata.normalize("NFC", name)).strip("._")


def _file_key(stem: str) -> str:
    """Stems that name the same file on a case-insensitive disk (macOS, Windows) have the same key."""
    return unicodedata.normalize("NFC", stem).casefold()


def _awareness(groups: list[yus.TranscriptGroup], aware: bool | None, commentator: str) -> bool | None:
    """Whether the groups' word times carry a UTC offset, given whether the commentator's do (None: unknown). ValueError for a mix."""
    for group in groups:
        for word in group.words:
            has = word.start.utcoffset() is not None
            if aware is None:
                aware = has
            elif has != aware:
                kinds = ("naive", "with a UTC offset")
                raise ValueError(f"{commentator!r}'s word times are {kinds[aware]}, but {word.text!r} at {word.start} is {kinds[has]}")
    return aware


def _as(when: dt.datetime, aware: bool | None, zone: dt.tzinfo | None) -> dt.datetime:
    """`when`, naive or with a UTC offset as `aware` says (None: as it is). Naive times are wall-clock times in `zone` (None: this system's)."""
    if aware is None or (when.utcoffset() is not None) == aware:
        return when
    if aware:
        return when.replace(tzinfo=zone) if zone is not None else when.astimezone()
    return when.astimezone(zone).replace(tzinfo=None)


def _clock(times: list[dt.datetime], zone: dt.tzinfo | None) -> Callable[[dt.datetime], dt.datetime]:
    """A function that makes these times comparable: as they are, unless some carry a UTC offset and some don't (then all naive)."""
    aware = {when.utcoffset() is not None for when in times}
    return (lambda when: when) if len(aware) < 2 else (lambda when: _as(when, False, zone))


def _read_saved(directory: pathlib.Path) -> tuple[_SavedSession, dict[str, yus.Transcript]]:
    """session.json, or what the transcripts say without it, and the transcripts read for that (by file name stem)."""
    path = directory / "session.json"
    if path.exists():
        return _SavedSession.model_validate_json(path.read_text()), {}
    transcripts = {file.stem: yus.Transcript.model_validate_json(file.read_text()) for file in sorted((directory / "transcripts").glob("*.json"))}
    commentators = [_SavedCommentator(name=transcript.commentator or stem, file=stem) for stem, transcript in transcripts.items()]
    return _SavedSession(version=0, timeout=TIMEOUT, commentators=commentators), transcripts


def _write_json(path: pathlib.Path, data: object) -> None:
    """Write JSON so that a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(temporary, path)


def replay(
    session: GameSession,
    transcript: yus.Transcript | pathlib.Path | str,
    commentator: str,
    speed: float = 0.0,
    on_update: Callable[[GameSnapshot], None] | None = None,
    *,
    tick: float = 1.0,
    stop: threading.Event | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Feed a saved transcript (or its JSON file) to the session as `commentator` (added if new), each group when its last word
    ends: speed 1 in real time, 2 twice as fast, 0 all at once. While waiting, the session is advanced every `tick` seconds of
    transcript time, so open throws time out as they would live. `on_update(snapshot)` is called after each group and after an
    advance that changed something. Returns the number of groups fed (fewer if `stop` is set). The session is not finished."""
    _check_pace(speed, tick)
    if not isinstance(transcript, yus.Transcript):
        transcript = yus.Transcript.model_validate_json(pathlib.Path(transcript).read_text())
    if commentator not in session.commentators:
        session.add_commentator(commentator)
    groups = [group for group in transcript.groups if group.words]
    if not groups:
        return 0
    origin, began = groups[0].start, clock()
    fed = 0
    for group in groups:
        arrival = max(word.start + word.duration for word in group.words)
        while speed > 0 and (now := origin + dt.timedelta(seconds=(clock() - began) * speed)) < arrival:
            if stop is not None and stop.is_set():
                return fed
            version = session.version
            session.advance(min(now, group.start), commentator)  # no words until the group starts
            if on_update is not None and session.version != version:
                on_update(session.snapshot())
            sleep(min(tick, (arrival - now).total_seconds()) / speed)
        if stop is not None and stop.is_set():
            return fed
        session.add_groups(commentator, [group])
        fed += 1
        if on_update is not None:
            on_update(session.snapshot())
    return fed


def _check_pace(speed: float, tick: float) -> None:
    if not speed >= 0:
        raise ValueError(f"speed must be 0 (all at once) or more, not {speed}")
    if speed > 0 and not tick > 0:
        raise ValueError(f"tick must be more than 0 seconds, not {tick}")


__all__ = ["CommentatorState", "GameSession", "GameSnapshot", "HeardAssociation", "replay"]
