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

import copy
import dataclasses
import datetime as dt
import json
import os
import pathlib
import re
import threading
import time
from collections.abc import Callable
from typing import Any

import pydantic

import yus
from yus.processing.event_extraction import EventExtractor
from yus.processing.event_unification import GameDescriptions, LiveMerger, MergeResult, PlayerDescription, PlayerResolver
from yus.processing.stats import GameStats, compute_stats

TIMEOUT = 6.0  # seconds without words after which an open throw becomes final (EventExtractor's timeout)


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

    def __init__(self, official: yus.EventStream, teams: list[yus.Team], settled: int, resolver: PlayerResolver, commentator: str | None):
        self.official, self.teams, self.settled, self.resolver, self.commentator = official, teams, settled, resolver, commentator
        self._lock = threading.Lock()
        self._values: dict[str, Any] = {}

    def get(self, key: str, compute: Callable[[], Any]) -> Any:
        with self._lock:
            if key not in self._values:
                self._values[key] = compute()
            return self._values[key]


@dataclasses.dataclass(eq=False)
class GameSnapshot:
    """The game as its session had it at one `version`. Read-only: its objects are shared with the session and later snapshots.

    `official.events[:settled_count]` are final as far as the commentary goes; later ones are provisional and may change or go.
    A description (`describe()`, or one a commentator speaks) re-resolves names in every event, settled or not.
    `stats`, `score`, `summary`, `unresolved` and `unmentioned` are computed when first read, then kept.
    """

    version: int
    game: yus.Game
    commentators: list[CommentatorState]
    raw: dict[str, yus.EventStream]  # per commentator: events as extracted, names as spoken; final ones first
    resolved: dict[str, yus.EventStream]  # per commentator: the raw events with names resolved by PlayerResolver
    official: yus.EventStream  # one commentator: its resolved stream; several: the merged stream
    settled_count: int
    associations: list[HeardAssociation]
    descriptions: GameDescriptions  # every description in effect: given, described, and heard
    merge: MergeResult | None  # with several commentators: offsets, pairs, conflicts, name links
    finished: bool
    _views: _Views = dataclasses.field(repr=False)

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
        """(team, name, mentions) for each name in the official stream that still needs a person to identify it (PlayerResolver.unresolved)."""
        views = self._views
        return views.get("unresolved", lambda: views.resolver.unresolved(views.official, views.commentator))

    @property
    def unmentioned(self) -> dict[str, list[str]]:
        """Roster players no official event names, per team: likely identities for the unresolved names."""
        views = self._views
        return views.get("unmentioned", lambda: views.resolver.unmentioned_players(views.official, views.commentator))

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
    extractor: EventExtractor
    pending_text: str = ""
    advanced: dt.datetime | None = None  # the latest time passed to advance()
    heard: int = 0  # associations of the extractor already recorded
    resolver: PlayerResolver | None = None  # what `resolved` was resolved with
    resolved: list[yus.Event] = dataclasses.field(default_factory=list)  # the final raw events, resolved


@dataclasses.dataclass(eq=False)
class _Computed:
    data_version: int
    raw: dict[str, yus.EventStream]
    resolved: dict[str, yus.EventStream]
    official: yus.EventStream
    settled: int
    merge: MergeResult | None
    associations: list[HeardAssociation]
    descriptions: GameDescriptions
    views: _Views


class _SavedCommentator(pydantic.BaseModel):
    name: str
    file: str
    focus_team: str | None = None
    pending_text: str = ""
    advanced: dt.datetime | None = None


class _SavedSession(pydantic.BaseModel):
    """session.json: what the other files don't say."""

    version: int
    timeout: float | None
    finished: bool = False
    commentators: list[_SavedCommentator] = []
    associations: list[HeardAssociation] = []
    merger_segments: list[list[tuple[int, float]] | None] | None = pydantic.Field(None, description="LiveMerger.segments as the last merge started.")


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
    being the clock reference. Add every commentator before feeding groups: one added later can unsettle settled events.
    """

    def __init__(self, game: yus.Game, descriptions: GameDescriptions | None = None, directory: pathlib.Path | str | None = None, *, timeout: float | None = TIMEOUT):
        self.game = yus.Game(sport=game.sport, when=game.when, teams=list(game.teams))
        self.directory = pathlib.Path(directory) if directory is not None else None
        self.timeout = timeout
        self._resolver = PlayerResolver(self.game.teams, descriptions)  # replaced, never changed, so that snapshots can keep it
        self._lock = threading.RLock()
        self._commentators: dict[str, _Commentator] = {}
        self._associations: list[HeardAssociation] = []
        self._merger: LiveMerger | None = None
        self._merger_before: list[list[tuple[int, float]] | None] | None = None  # its segments as the last merge started
        self._finished = False
        self._version = 0
        self._data_version = 0
        self._computed: _Computed | None = None
        self._snapshot: GameSnapshot | None = None

    # ------------------------------------------------------------------ state

    @property
    def version(self) -> int:
        """Increases on every change."""
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
            if not name or name in self._commentators:
                raise ValueError(f"Commentator {name!r} is {'already added' if name else 'not named'}")
            if focus_team is not None and self._resolver.team_index(focus_team) is None:
                raise ValueError(f"No team is called {focus_team!r}; teams: {[team.names for team in self.game.teams]}")
            files = {c.file for c in self._commentators.values()}
            stem = re.sub(r"[^\w.-]+", "_", name).strip("._") or "commentator"
            file = next(f for f in (stem if i == 1 else f"{stem}-{i}" for i in range(1, len(files) + 2)) if f not in files)
            transcript = yus.Transcript(game=self.game, commentator=name)
            self._commentators[name] = _Commentator(name, focus_team, file, transcript, EventExtractor(self.game.teams, timeout=self.timeout))
            focus = [c.focus_team for c in self._commentators.values()]
            if self._merger is not None:
                self._merger.options["focus"] = focus
            elif len(self._commentators) > 1:
                self._merger = LiveMerger(focus=focus, teams=self.game.teams)
            self._changed(data=True)

    def add_groups(self, commentator: str, groups: list[yus.TranscriptGroup]) -> None:
        """Add a commentator's next transcript groups, in order (copies are kept; the groups are left as they are)."""
        with self._lock:
            c = self._get(commentator)
            if self._finished:
                raise RuntimeError("The session is finished")
            for group in groups:
                kept = yus.TranscriptGroup.model_validate(group.model_dump())
                kept.transcript = c.transcript
                c.transcript.groups.append(kept)
                c.extractor.feed(kept)
            self._hear(c)
            if groups:
                self._changed(data=True)

    def advance(self, now: dt.datetime, commentator: str | None = None) -> None:
        """Note that a commentator's transcript (None: every commentator's) is complete up to `now`, transcript time: a throw left
        open for more than `timeout` seconds without words becomes final."""
        with self._lock:
            changed = False
            for c in [self._get(commentator)] if commentator is not None else self._commentators.values():
                before = c.extractor.final_count
                c.extractor.advance(now)
                c.advanced = now if c.advanced is None else max(c.advanced, now)
                changed |= c.extractor.final_count != before
            if changed:
                self._changed(data=True)

    def describe(self, team: str, descriptions: list[str] | str, player: str | None = None, label: str | None = None, commentator: str | None = None) -> PlayerDescription:
        """Record that `descriptions` all mean one player of `team`: `player`, or an unknown person called `label` (PlayerResolver.describe).
        It applies to every event, earlier ones too. A commentator's own record beats shared ones (commentator=None) for their stream,
        so to correct what a commentator was heard to say, pass that commentator. Raises ValueError (unknown team or player)."""
        with self._lock:
            descriptions = [descriptions] if isinstance(descriptions, str) else list(descriptions)
            record = self._record(PlayerDescription(team=team, descriptions=descriptions, player=player, label=label, commentator=commentator))
            self._changed(data=True)
            return record

    def set_pending_text(self, commentator: str, text: str) -> None:
        """Show what live transcription guesses a commentator is saying (not used for events)."""
        with self._lock:
            c = self._get(commentator)
            if c.pending_text != text:
                c.pending_text = text
                self._changed(data=False)

    def finish(self) -> None:
        """End of the game: every event becomes final, and no more groups are taken."""
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
                raw=done.raw,
                resolved=done.resolved,
                official=done.official,
                settled_count=done.settled,
                associations=done.associations,
                descriptions=done.descriptions,
                merge=done.merge,
                finished=self._finished,
                _views=done.views,
            )
            return self._snapshot

    def _compute(self) -> _Computed:
        raw: dict[str, yus.EventStream] = {}
        resolved: dict[str, yus.EventStream] = {}
        finals = []
        for c in self._commentators.values():
            events = c.extractor.events
            final = c.extractor.final_count
            if c.resolver is not self._resolver:
                c.resolver, c.resolved = self._resolver, []
            c.resolved += [self._resolver.resolve_event(event, c.name) for event in events[len(c.resolved) : final]]
            resolved_events = c.resolved[:final] + [self._resolver.resolve_event(event, c.name) for event in events[final:]]
            raw[c.name] = yus.EventStream(game=self.game, transcript=c.transcript, events=events)
            resolved[c.name] = yus.EventStream(game=self.game, transcript=c.transcript, events=resolved_events)
            finals.append(final)
        merge = None
        if not self._commentators:
            official, settled = yus.EventStream(game=self.game), 0
        elif self._merger is None:
            official, settled = next(iter(resolved.values())), finals[0]
        else:
            self._merger_before = copy.deepcopy(self._merger.segments)
            merge = self._merger.merge(list(resolved.values()))
            official, settled = merge.stream, _settled(merge, finals)
        if self._finished:
            settled = len(official.events)
        single = next(iter(self._commentators)) if len(self._commentators) == 1 else None
        views = _Views(official, self.game.teams, settled, self._resolver, single)
        return _Computed(self._data_version, raw, resolved, official, settled, merge, list(self._associations), self._resolver.descriptions, views)

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
                    _SavedCommentator(name=c.name, file=c.file, focus_team=c.focus_team, pending_text=c.pending_text, advanced=c.advanced) for c in self._commentators.values()
                ],
                associations=self._associations,
                merger_segments=self._merger_before,
            )
            _write_json(self.directory / "session.json", saved.model_dump(mode="json"))

    @classmethod
    def load(cls, directory: pathlib.Path | str) -> GameSession:
        """The session saved in `directory`, as it was: transcripts are fed again (events/ and official.json are not read back)."""
        directory = pathlib.Path(directory)
        game = yus.Game.model_validate_json((directory / "game.json").read_text())
        path = directory / "descriptions.json"
        descriptions = GameDescriptions.model_validate_json(path.read_text()) if path.exists() else None
        saved = _SavedSession.model_validate_json((directory / "session.json").read_text())
        session = cls(game, descriptions, directory, timeout=saved.timeout)
        session._associations = list(saved.associations)
        for entry in saved.commentators:
            session.add_commentator(entry.name, entry.focus_team)
            c = session._commentators[entry.name]
            c.file, c.pending_text, c.heard = entry.file, entry.pending_text, sum(a.commentator == entry.name for a in saved.associations)
            c.transcript = yus.Transcript.model_validate_json((directory / "transcripts" / f"{entry.file}.json").read_text())
            c.transcript.game, c.transcript.commentator = session.game, entry.name
            for group in c.transcript.groups:
                c.extractor.feed(group)
            session._hear(c)  # only identifications not heard before
            if entry.advanced is not None:
                c.extractor.advance(entry.advanced)
                c.advanced = entry.advanced
        if saved.finished:
            for c in session._commentators.values():
                c.extractor.finish()
            session._finished = True
        if session._merger is not None and saved.merger_segments is not None:
            session._merger.segments = [list(segments) if segments is not None else None for segments in saved.merger_segments]
        session._version = saved.version
        session.snapshot()  # merge now, so that the merger goes on from where it was
        return session

    # ------------------------------------------------------------------ internals

    def _get(self, name: str) -> _Commentator:
        if name not in self._commentators:
            raise ValueError(f"Unknown commentator {name!r}; add_commentator() first. Commentators: {list(self._commentators)}")
        return self._commentators[name]

    def _changed(self, data: bool) -> None:
        self._version += 1
        if data:
            self._data_version += 1

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


def _settled(merge: MergeResult, finals: list[int]) -> int:
    """The merge's settled count, cut before the first merged event made from a provisional raw event (one the extractor may revise)."""
    for m, pair in enumerate(merge.pairs[: merge.settled]):
        if any(index is not None and index >= final for index, final in zip(pair, finals)):
            return m
    return merge.settled


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


__all__ = ["CommentatorState", "GameSession", "GameSnapshot", "HeardAssociation", "replay"]
