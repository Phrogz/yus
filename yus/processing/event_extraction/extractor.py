"""Rule-based, streaming event extraction: transcript groups in, indoor Ultimate events out.

Each group is tagged (see `lexicon`) and parsed left to right by a small state machine that remembers which team has the disc,
who holds it, and at most one throw whose outcome is not yet known. That throw stays provisional until the commentary settles it:
an explicit outcome ("dropped", "deed by", "for a score", "caught by"), the next throw, a pickup, or `timeout` seconds of silence.
Everything else is final once its group has been parsed, except that a group in which a throw scored stays provisional until the
next group (or the timeout): a correction there ("nope, not in the end zone") can still take the score back. A correction that
reaches an event already finished parses again from before it, so possession follows the corrected event. Player names are kept
as spoken, in lower case; event unification's PlayerResolver maps them to players later. Teams are written as one of the team's
names (see `team_label`).

Substitutions ("pikachu subs off", "close crop, emily off", "fulmer on for cynic") change nothing about the disc. One said while a
throw is open waits behind that throw, so that events stay in time order; a group with substitutions waits for the next group, where
"nope" or "sorry, tristan on" can take the last one back.
"""

from __future__ import annotations

import copy
import dataclasses
import datetime as dt
from collections.abc import Callable
from typing import TYPE_CHECKING, NamedTuple

import yus
from yus.processing.event_extraction.lexicon import Item, Tag, Tagger, Token, pieces, tokenize
from yus.processing.event_unification.players import normalize, roster_aliases
from yus.sports import ultimate
from yus.sports.ultimate import SubType, ThrowDirection, ThrowType, indoor

if TYPE_CHECKING:
    from yus.processing.event_extraction.llm import AssistedExtractor, LLMAssistant

COLORS = frozenset("white black dark light red blue green yellow orange purple pink grey gray navy maroon gold silver teal brown".split())
DEFAULT_TEAMS = (yus.Team(names=["white", "light"]), yus.Team(names=["black", "dark"]))
EVENT_TAGS = frozenset({Tag.TYPE, Tag.DIR, Tag.TO, Tag.THROWV, Tag.CAUGHT, Tag.DEFENSE, Tag.INTERCEPT, Tag.PICKUP, Tag.SCORE, Tag.DROP, Tag.THROWAWAY})
THROW_STARTS = (Tag.TYPE, Tag.DIR, Tag.TO, Tag.THROWV, Tag.THROWAWAY)
CHATTER = frozenset({Tag.FILLER, Tag.NAME, Tag.UNK, Tag.NUM})  # what an identification takes with it when alone: "pikachu is killing it tonight"
TIES = frozenset({Tag.NAME, Tag.UNK, Tag.PICKUP, Tag.CHECKIN, Tag.TO, Tag.DEFENSE, Tag.INTERCEPT})  # what a bare team name may follow
RESTATED = frozenset({None, Tag.BOUNDARY, Tag.TO, Tag.CORRECT, Tag.NAME, Tag.TEAM, Tag.TEAMREF})  # what may follow a name that replaces another
RETRACTS = frozenset({"nope", "no", "sorry", "wait", "actually", "no wait", "wait no", "my bad", "my mistake", "scratch that", "correction", "i mean", "oops", "whoops"})
NEGATIONS = frozenset({"not", "wasn't", "isn't", "wasnt", "isnt"})  # "not joe", "that wasn't joe"
NEGATED = frozenset({"it", "that", "it's", "that's", "he", "she"})  # what may stand between "nope" and "not in": "sorry, it wasn't in"
NAMED_BY = frozenset({Tag.TO, Tag.THROWV, Tag.CAUGHT, Tag.PICKUP, Tag.DEFENSE, Tag.INTERCEPT, Tag.TYPE, Tag.DIR})  # "to X", "backhand swing X": that event's
TIED_TO = frozenset({Tag.PICKUP, Tag.CHECKIN, Tag.DEFENSE, Tag.INTERCEPT})  # what "on dark" may follow ("picked up by blue on dark")
PAIRED_WITHIN = 10.0  # seconds: "X off" then "Y on" this soon after, with no other event between, is one team's swap


class Association(NamedTuple):
    """A spoken identification such as "red shorts is kaia": pass to PlayerResolver.describe(team, [description], player=...).
    `name` is as spoken and resolves to a player on the roster of `team`."""

    team: str | None
    description: str
    name: str


@dataclasses.dataclass(slots=True)
class _Throw:
    when: dt.datetime
    team: int | None
    player: str | None
    type: ThrowType | None = None
    direction: ThrowDirection | None = None
    receiver: str | None = None
    receiver_set: bool = False
    completed: bool | None = None  # None: not known yet
    scored: bool = False
    hit_wall: bool = False
    hit_net: bool = False
    ez_in: bool = False
    ez_to: bool = False
    decisive: bool = False  # outcome stated: final at the end of this group
    stated: bool = False  # its team was said ("for dark", "white picks it up"), not inferred
    backed: bool = False  # its thrower caught the team's last pass, which backs the team in possession

    def open_for_receiver(self) -> bool:
        return not self.receiver_set and self.completed is not False

    def open_for_style(self, attr: str) -> bool:
        """Can a throw type or direction said next still describe this throw ("flick" | "swing, to close crop")?"""
        settled = self.receiver_set or self.completed is not None or self.ez_in or self.ez_to or self.hit_wall or self.hit_net
        return getattr(self, attr) is None and not settled


@dataclasses.dataclass(slots=True)
class _Defense:
    when: dt.datetime
    team: int | None
    player: str | None
    intercepted: bool


@dataclasses.dataclass(slots=True)
class _Sub:
    when: dt.datetime
    team: int | None
    player: str
    sub_type: SubType


class _Spec(NamedTuple):
    """One substitution as said, before its team is known: a SUBST item's value is a list of these, all said together."""

    name: str
    sub_type: SubType
    start: dt.datetime
    team: int | None  # said: "kaia off for white", "on white we have ..."


@dataclasses.dataclass(slots=True)
class _Group:
    items: list[Item]
    subject: _Throw | _Defense | str | None = None  # what a following "for dark" refers to ("pickup", or "lineup" for "d-line ...")
    correcting: bool = False  # after "sorry": the next receiver or name replaces the last one
    wrong: str | None = None  # a name said not to be right: "that wasn't joe"


class _Replay(Exception):  # noqa: N818 (not an error)
    """A correction took back a fact of an event already finished: parse `groups` and the current group again from `base`."""

    def __init__(self, base: EventExtractor, groups: list[yus.TranscriptGroup]):
        super().__init__()
        self.base, self.groups = base, groups


def team_label(team: yus.Team) -> str:
    """The name events use for a team: its first color name ("white" for ["Dump & Drizzle", "white", "light"]), else its first name."""
    return next((name for name in team.names if normalize(name) in COLORS), team.names[0] if team.names else "")


class EventExtractor:
    """Extracts events from a transcript as its groups arrive.

    extractor = EventExtractor(game.teams, timeout=6.0)
    for group in groups:                       # live: as each group arrives
        extractor.feed(group)
        show(extractor.events[: extractor.final_count], extractor.events[extractor.final_count :])   # final, provisional
    extractor.finish()                         # end of game: everything is final

    `events` are in time order, final ones first; `events[:final_count]` never change, later ones are provisional and may be
    revised or removed by the next group. `advance(now)` finalizes a provisional throw once `timeout` seconds pass with no speech.
    `associations` lists spoken identifications ("red shorts is kaia") for PlayerResolver.describe: only those that name a roster
    player of a known team, so without rosters there are none. Without teams, two teams named "white"/"light" and "black"/"dark"
    are assumed.
    """

    def __init__(self, teams: list[yus.Team] | None = None, timeout: float | None = None, lineups: bool = False):
        self.teams = list(teams) if teams else [team.model_copy() for team in DEFAULT_TEAMS]
        self.timeout = timeout
        self.lineups = lineups  # a line-up said for one team ("on white we have kaia, pikachu ...") subs its players on
        self.labels = [team_label(team) for team in self.teams]
        self.associations: list[Association] = []
        self.possession: int | None = None  # index of the team on offense
        self.holder: str | None = None  # who has the disc, as spoken
        self._rosters = [roster_aliases(team) for team in self.teams]
        self._roster_team: dict[str, int | None] = {}
        for index, aliases in enumerate(self._rosters):
            for alias in [name for names in aliases for name in names]:
                self._roster_team[alias] = index if self._roster_team.get(alias, index) == index else None
        self._tagger = Tagger([team.names for team in self.teams], self._roster_team)
        self._name_team: dict[str, int] = {}  # what the commentator said about names: line-ups, "for dark"
        self._final: list[yus.Event] = []
        self._done: list[_Throw | _Defense] = []  # finished while parsing the current group
        self._pending: _Throw | None = None
        self._carry: Item | None = None  # a name ending the last group, maybe the subject of the next ("Tristan" | "picks up")
        self._held: list[Token] = []  # a team reference cut by the end of the last group ("picks it up for" | "White.")
        self._held_subject: str | None = None
        self._last_end: dt.datetime | None = None
        self._stated = False  # possession was said, not inferred, since the last throw ended
        self._passed = False  # the holder caught the last throw
        self._said: str | None = None  # the last name said, for "sorry, that was connor"
        self._seen: set[str] = set()  # names events used (normalized)
        self._sub_teams: dict[str, int] = {}  # the team of each name's latest substitution whose team is known (normalized name)
        self._subs_after: list[_Sub] = []  # substitutions said while the open throw was open: they follow it in `events`
        self._unsettled: list[_Throw | _Defense] = []  # the last group's events, while a correction in the next one may change them
        self._window: tuple[EventExtractor, list[yus.TranscriptGroup]] | None = None  # the state before the unsettled group, and it
        self._start: EventExtractor | None = None  # the state before the group being parsed
        self._late: dict[tuple[dt.datetime, int], dict[str, object]] = {}  # corrections of finished events: (when, index in events) -> changes
        self._cues: set[tuple[dt.datetime, str]] = set()  # the words that made them
        self.last_items: list[Item] = []  # the last group's items, as parsed (line-ups and identifications removed)
        self._handlers = self._bind_handlers()

    def _bind_handlers(self) -> dict[Tag, Callable[[_Group, int], int]]:
        return {
            Tag.TEAM: self._on_team,
            Tag.TEAMREF: self._on_team_ref,
            Tag.NAME: self._on_name,
            Tag.UNK: self._on_name,
            Tag.PICKUP: self._on_pickup,
            Tag.TYPE: self._on_style,
            Tag.DIR: self._on_style,
            Tag.TO: self._on_to,
            Tag.THROWV: self._on_throw_verb,
            Tag.CAUGHT: self._on_caught,
            Tag.DEFENSE: self._on_defense,
            Tag.INTERCEPT: self._on_defense,
            Tag.DROP: self._on_drop,
            Tag.NOSCORE: self._on_drop,
            Tag.NOT_IN: self._on_not_in,
            Tag.THROWAWAY: self._on_throwaway,
            Tag.SCORE: self._on_score,
            Tag.EZ_IN: self._on_end_zone,
            Tag.EZ_TO: self._on_end_zone,
            Tag.WALL: self._on_wall,
            Tag.NET: self._on_wall,
            Tag.CORRECT: self._on_correct,
            Tag.LINEUP: self._on_lineup,
            Tag.BOUNDARY: self._on_boundary,
            Tag.SUBST: self._on_sub,
        }

    @property
    def events(self) -> list[yus.Event]:
        """Final events, then provisional ones."""
        provisional = [*self._unsettled, *([self._pending] if self._pending is not None else []), *self._subs_after]
        return self._final + [self._render(record) for record in provisional]

    @property
    def final_count(self) -> int:
        """How many of `events` are final."""
        return len(self._final)

    @property
    def open_from(self) -> int:
        """Where the throw still open is in `events` (`len(events)` if none). The next group's own events start here: those between
        `final_count` and here are the last group's, waiting for a correction in the next one ("nope, not in the end zone")."""
        return len(self._final) + len(self._unsettled)

    def feed(self, group: yus.TranscriptGroup) -> None:
        """Parse the next transcript group (its first interpretation)."""
        if not group.words:
            return
        todo = [group]
        while todo:
            current = todo.pop(0)
            try:
                self._feed(current)
            except _Replay as replay:
                self._restore(replay.base)
                todo = [*replay.groups, current, *todo]

    def _feed(self, group: yus.TranscriptGroup) -> None:
        words = group.words
        self.advance(words[0].start)
        self._start = self._snapshot()
        items = self._tagger.tag(self._held + tokenize(words))
        subject = self._held_subject if self._held and items and items[0].tag is Tag.TEAMREF else None  # "... picks it up for" | "white"
        self._held, self._held_subject = [], None
        held = _dangling_team_prefix(items)
        if held:
            self._held = [Token(item.text, item.start, item.end) for item in items[-held:]]
            items = items[:-held]
        if self._carry is not None:
            carry, self._carry = self._carry, None
            items = [carry, Item(Tag.BOUNDARY, False, ",", carry.end, carry.end), *items]
        parsed = _Group(self._preprocess(items), subject=subject)
        self.last_items = parsed.items
        self._parse(parsed)
        if self._held and parsed.subject == "pickup":
            self._held_subject = "pickup"
        pending = self._pending
        if pending is not None and (pending.decisive or (pending.completed is True and not pending.ez_to)):
            self._finish_throw(pending)  # a catch toward the end zone waits: a pickup by the other team next means it scored
        self._last_end = max(word.start + word.duration for word in words)
        self._final.extend(self._render(record) for record in self._unsettled)  # the group before's: no longer correctable
        if any((isinstance(record, _Throw) and record.scored) or isinstance(record, _Sub) for record in self._done):
            self._unsettled, self._window = self._done, (self._start, [group])  # a score or a substitution waits for the next group
        else:
            self._final.extend(self._render(record) for record in self._done)
            self._unsettled, self._window = [], None
        self._done, self._start = [], None

    def advance(self, now: dt.datetime) -> None:
        """Note that the transcript is complete up to `now` (transcript time, not wall-clock time): after more than `timeout`
        seconds without words, the provisional events become final as they stand."""
        if self.timeout is None or self._last_end is None or (now - self._last_end).total_seconds() <= self.timeout:
            return
        self._carry, self._held, self._held_subject = None, [], None
        if self._pending is not None:
            self._finish_throw(self._pending)
        self._commit()

    def finish(self) -> None:
        """End of the transcript: make every event final."""
        self._carry, self._held, self._held_subject = None, [], None
        if self._pending is not None:
            self._finish_throw(self._pending)
        self._commit()

    def team_of(self, name: str | None) -> int | None:
        """Index of the team `name` plays for, from what the commentator said, else the rosters, else the team it was last
        substituted for; None if unknown or ambiguous."""
        found = self._said_team(name)
        return found if found is not None or not name else self._sub_teams.get(normalize(name))

    def _said_team(self, name: str | None) -> int | None:
        """The team of `name` from what the commentator said, else the rosters."""
        if not name:
            return None
        key = normalize(name)
        return self._name_team[key] if key in self._name_team else self._roster_team.get(key)

    def knows(self, name: str) -> bool:
        """Is `name` a roster name, nickname or mondegreen, or a name announced in a line-up?"""
        return pieces(name) in self._tagger.names or normalize(name) in self._roster_team

    def copy(self) -> EventExtractor:
        """An independent copy of this extractor, to parse ahead and come back to (as `llm.AssistedExtractor` does)."""
        new = copy.copy(self)
        new.associations = list(self.associations)
        new._tagger = self._tagger.copy()
        new._name_team = dict(self._name_team)
        new._final = list(self._final)
        new._done = [dataclasses.replace(record) for record in self._done]
        new._unsettled = [dataclasses.replace(record) for record in self._unsettled]
        new._pending = dataclasses.replace(self._pending) if self._pending is not None else None
        new._held = list(self._held)
        new._late = dict(self._late)
        new._cues = set(self._cues)
        new._seen = set(self._seen)
        new._sub_teams = dict(self._sub_teams)
        new._subs_after = [dataclasses.replace(record) for record in self._subs_after]
        new._handlers = new._bind_handlers()
        return new

    def _snapshot(self) -> EventExtractor:
        new = self.copy()
        new._window = new._start = None  # no chains of snapshots: a replay never reaches back further than its own window
        return new

    def _restore(self, base: EventExtractor) -> None:
        """Go back to the state `base` (which stays as it is); corrections already decided are kept."""
        late, cues = self._late, self._cues
        self.__dict__.update(base.copy().__dict__)
        self._late, self._cues = late, cues
        self._handlers = self._bind_handlers()

    def revise(self, start: int, events: list[yus.Event]) -> None:
        """Replace `events[start:]` with `events`: another reading of the groups that made them, such as an LLM's (see `llm`).
        Callers must not have shown `events[start:]` as final. Teams must be `labels`. When the last old event was the open throw
        and the last new one is a throw, that throw stays open, so the next group can still settle it. Possession and who holds
        the disc follow the new last event when its team, receiver or outcome differs from the old last event's."""
        old = self.events[start:]
        if list(events) == old:
            return
        if self._unsettled:  # the new reading replaces them; the next group can no longer take a score back
            self._final.extend(self._render(record) for record in self._unsettled)
            self._unsettled, self._window = [], None
        body, subs = _trailing_subs(list(events))  # substitutions after the open throw stay behind it
        old = _trailing_subs(old)[0]
        was_open = self._pending is not None
        self._final = self._final[:start] + body
        self._subs_after = []
        last, previous = (body[-1] if body else None), (old[-1] if old else None)
        if was_open and isinstance(last, ultimate.Throw):
            self._final.pop()
            if last != previous:
                self._pending = self._record(last)
        else:
            self._pending = None
        if self._pending is not None:
            self._subs_after = [_Sub(event.when, self._index(event.team), event.player or "", event.sub_type) for event in subs]
        else:
            self._final += subs
        if last is not None and _outcome(last) != _outcome(previous):
            self._follow(last)

    def _follow(self, last: yus.Event) -> None:
        """Possession and who holds the disc after a revision whose last event is `last`."""
        self._passed = isinstance(last, ultimate.Throw) and self._pending is None and bool(last.completed) and not last.scored and last.receiver is not None
        if self._pending is not None:
            self.possession, self.holder = self._pending.team, self._pending.player
        elif isinstance(last, ultimate.Throw) and last.completed and not last.scored:
            self.possession, self.holder = self._index(last.team), last.receiver
        elif isinstance(last, ultimate.Throw):
            self.possession, self.holder = self._other(self._index(last.team)), None
        elif isinstance(last, ultimate.Defense):
            self.possession, self.holder = self._index(last.team), last.player if last.intercepted else None

    def _index(self, label: str | None) -> int | None:
        return self.labels.index(label) if label in self.labels else None

    def _record(self, throw: ultimate.Throw) -> _Throw:
        """An open throw from a throw event: a catch that did not score stays unsettled, as the rules leave one."""
        settled = throw.scored or not throw.completed
        return _Throw(
            when=throw.when,
            team=self._index(throw.team),
            player=throw.player,
            type=throw.type,
            direction=throw.direction,
            receiver=throw.receiver,
            receiver_set=throw.receiver is not None,
            completed=throw.completed if settled else None,
            scored=throw.scored,
            hit_wall=getattr(throw, "hit_wall", False),
            hit_net=getattr(throw, "hit_net", False),
            decisive=settled,
        )

    # ------------------------------------------------------------------ events and state

    def _label(self, team: int | None) -> str:
        return self.labels[team] if team is not None else ""

    def _other(self, team: int | None) -> int | None:
        return 1 - team if team is not None and len(self.teams) == 2 else None

    def _learn(self, name: str | None, team: int | None) -> None:
        if name and team is not None:
            self._name_team[normalize(name)] = team

    def _render(self, record: _Throw | _Defense | _Sub) -> yus.Event:
        if isinstance(record, _Sub):
            return ultimate.Substitution(when=record.when, team=self._label(record.team), player=record.player, sub_type=record.sub_type)
        if isinstance(record, _Defense):
            return ultimate.Defense(when=record.when, team=self._label(record.team), player=record.player, intercepted=record.intercepted)
        completed = record.completed is not False
        team = record.team
        if record is self._pending:  # finished throws keep the team they finished with
            team = team if record.stated else self._evidence(record, team)
            team = team if team is not None else self.possession
        return indoor.Throw(
            when=record.when,
            team=self._label(team),
            player=record.player,
            type=record.type,
            direction=record.direction,
            receiver=record.receiver,
            completed=completed,
            scored=completed and (record.scored or record.ez_in),
            hit_wall=record.hit_wall,
            hit_net=record.hit_net,
        )

    def _commit(self) -> None:
        self._final.extend(self._render(record) for record in [*self._unsettled, *self._done])
        self._unsettled, self._done, self._window = [], [], None

    def _evidence(self, throw: _Throw, team: int | None) -> int | None:
        """The throw's team as its thrower's and receiver's teams say (from the commentary, else the rosters), else `team`. A name
        known only on the other team's roster means the team in possession was wrong ("power dump to tristan" after a false goal);
        names that disagree, or names on both rosters or none, say nothing."""
        known = {t for t in (self.team_of(throw.player), self.team_of(throw.receiver), team if throw.backed else None) if t is not None}
        return known.pop() if len(known) == 1 else team

    def _finish_throw(self, throw: _Throw) -> None:
        changes = self._late.get((throw.when, self._position()))
        if changes:
            _change(throw, changes)
        if throw.team is None:
            for team in (self.possession, self.team_of(throw.player), self.team_of(throw.receiver)):
                if team is not None:
                    throw.team = team
                    break
        if not throw.stated:
            throw.team = self._evidence(throw, throw.team)
        self._stated = False
        self._seen.update(normalize(name) for name in (throw.player, throw.receiver) if name)
        throw.completed = throw.completed is not False
        throw.scored = throw.completed and (throw.scored or throw.ez_in)
        if throw.completed and not throw.scored:
            self.possession, self.holder, self._passed = throw.team, throw.receiver, throw.receiver is not None
        else:
            self.possession, self.holder, self._passed = self._other(throw.team), None, False
        self._done.append(throw)
        if self._pending is throw:
            self._pending = None
            self._done += self._subs_after  # said while it was open: they follow it
            self._subs_after = []

    def _start_throw(self, when: dt.datetime, thrower: str | None = None, named: bool = False) -> _Throw:
        previous = self._pending
        if previous is not None:
            if named and previous.open_for_receiver():
                previous.receiver, previous.receiver_set = thrower, True  # "flick huck" | "joe backhand to ...": joe caught it
            self._finish_throw(previous)
        player = thrower if named else self.holder
        team = self.possession if self.possession is not None else self.team_of(player)
        backed = self._passed and player is not None and normalize(player) == normalize(self.holder or "")
        self._pending = _Throw(when, team, player, stated=self._stated and self.possession is not None, backed=backed)
        return self._pending

    def _recent(self) -> list[_Throw | _Defense | _Sub]:
        """The events a correction can still change, newest first: substitutions said after the open throw started, the open throw,
        this group's, and the group before's while they wait for this one."""
        found: list[_Throw | _Defense | _Sub] = [*reversed(self._subs_after), *([self._pending] if self._pending is not None else [])]
        found += reversed(self._done)
        if self._window is not None:
            found += reversed(self._unsettled)
        return found

    def _last_throw(self) -> _Throw | None:
        return next((record for record in self._recent() if isinstance(record, _Throw)), None)

    def _position(self, record: _Throw | _Defense | _Sub | None = None) -> int:
        """Index in `events` of the finished `record`, else of the next event to finish. With its time, it tells apart events that
        Whisper gave the same time ("flick to joe flick to tristan")."""
        position = len(self._final)
        for records in (self._unsettled, self._done):
            for k, other in enumerate(records):
                if other is record:
                    return position + k
            position += len(records)
        return position

    def _retract(self, record: _Throw | _Defense | _Sub, changes: dict[str, object], cue: Item) -> None:
        """Change facts of `record` that `cue` took back: at once if it is the open throw (or waits behind it), else by parsing
        again from before the groups that made it, with the change made when it finishes (so later events follow it). Final events
        never change."""
        if record is self._pending or any(record is other for other in self._subs_after):
            _change(record, changes)
            return
        self._cues.add((cue.start, cue.text))
        target = (record.when, self._position(record))
        self._late[target] = {**self._late.get(target, {}), **changes}
        if self._window is not None:
            raise _Replay(*self._window)
        assert self._start is not None
        raise _Replay(self._start, [])

    def _decided(self, cue: Item) -> bool:
        """Is `cue` a correction of a finished event, already made (the groups are being parsed again)?"""
        return (cue.start, cue.text) in self._cues

    def _mentions(self, name: str) -> bool:
        key = normalize(name)
        return normalize(self.holder or "") == key or any(normalize(getattr(record, attr, None) or "") == key for record in self._recent() for attr in ("player", "receiver"))

    def _pickup(self, name: str | None, checkin: bool = False) -> None:
        throw = self._pending
        if throw is not None and not checkin:
            if throw.completed is True and (throw.ez_in or throw.ez_to):
                throw.scored = True  # caught in or toward the end zone, then the disc is picked up: a score
            elif not throw.scored and throw.completed is not True:
                throw.completed = False  # someone picks it up: the throw hit the ground
            self._finish_throw(throw)
        self.holder, self._passed = name, False
        team = self.team_of(name)
        if team is not None and not checkin:
            self.possession = team

    # ------------------------------------------------------------------ parsing

    def _preprocess(self, items: list[Item]) -> list[Item]:
        """Drop line-up clauses (learning their names) and spoken identifications (recording them as associations)."""
        result: list[Item] = []
        clause: list[Item] = []
        for item in items:
            clause.append(item)
            if item.tag is Tag.BOUNDARY and item.value:
                result += self._clause(clause)
                clause = []
        return result + self._clause(clause)

    def _clause(self, clause: list[Item]) -> list[Item]:
        tags = {item.tag for item in clause}
        if Tag.LINEUP in tags and Tag.NAME in tags and not tags & EVENT_TAGS:
            said = next((item.value for item in clause if item.tag in (Tag.TEAM, Tag.TEAMREF)), None)
            team = said if isinstance(said, int) else None
            names = [item for item in clause if item.tag is Tag.NAME]
            for item in names:
                self._learn(str(item.value), team)
                self._tagger.add_name(str(item.value))
            return self._lineup(names, team) if self.lineups else []
        if Tag.SUB in tags:
            clause = self._substitutions(clause)
            tags = {item.tag for item in clause}
        return self._associate(clause) if Tag.IS in tags else clause

    def _lineup(self, names: list[Item], team: int | None) -> list[Item]:
        """A line-up as substitutions on, when it is one team's: the team said, else the one team all its names are known on."""
        known = {self.team_of(str(item.value)) for item in names}
        team = team if team is not None else known.pop() if len(known) == 1 else None
        if team is None:
            return []
        specs = [_Spec(str(item.value), SubType.SUB_ON, item.start, team) for item in names]
        return [Item(Tag.SUBST, specs, " ".join(item.text for item in names), names[0].start, names[-1].end)]

    def _substitutions(self, clause: list[Item]) -> list[Item]:
        """The clause with each substitution word and the names it goes with made one SUBST item: "pikachu subs off, blondie on",
        "close crop, emily off", "tanner off purple off", "fulmer on for cynic", "kaia off for white", "subbing on: ari and ben".
        A name right after "to", "caught by" or "picked up by" is that event's ("to 50, tristan off"). Substitution words that go
        with no name, or are followed by more of the sentence ("blue yellow on the end zone"), are filler."""
        result: list[Item] = []
        k = 0
        while k < len(clause):
            item = clause[k]
            if item.tag is not Tag.SUB:
                result.append(item)
                k += 1
                continue
            found = self._postfix_sub(result, clause, k) or self._prefix_sub(result, clause, k)
            if found is None:
                result.append(Item(Tag.FILLER, None, item.text, item.start, item.end))
                k += 1
                continue
            first, specs, k = found
            last = clause[k - 1]
            del result[first:]
            result.append(Item(Tag.SUBST, specs, " ".join(spec.name for spec in specs) + " " + item.text, specs[0].start, last.end))
        return result

    def _postfix_sub(self, result: list[Item], clause: list[Item], k: int) -> tuple[int, list[_Spec], int] | None:
        """Names before the substitution word at clause[k] ("close crop, emily off"): (where they start in `result`, the
        substitutions, the index in `clause` after the phrase), or None."""
        word = clause[k]
        kind = word.value
        assert isinstance(kind, SubType)
        n, team, replaced = k + 1, None, None
        if n < len(clause) and clause[n].tag is Tag.TEAMREF:  # "kaia off for white"
            team, n = clause[n].value, n + 1
        elif kind is SubType.SUB_ON and n + 1 < len(clause) and clause[n].text == "for" and _player(clause[n + 1]):  # "fulmer on for cynic"
            replaced, n = clause[n + 1], n + 2
        if not _sub_ends(clause, n):
            return None
        end = len(result) - (1 if result and result[-1].tag is Tag.IS and result[-1].text == "is" else 0)  # "kaia is on"
        first = _names_before(result, end)
        names = [item for item in result[first:end] if _player(item)]
        if not names:
            return None
        said = team if isinstance(team, int) else None
        specs = [_Spec(_name_of(item), kind, item.start, said) for item in names]
        if replaced is not None:
            specs.append(_Spec(_name_of(replaced), SubType.SUB_OFF, replaced.start, said))
        return first, specs, n

    def _prefix_sub(self, result: list[Item], clause: list[Item], k: int) -> tuple[int, list[_Spec], int] | None:
        """A substitution phrase starting its clause, then the names that end it: "subbing on: ari and ben" (not a bare "on")."""
        word = clause[k]
        kind = word.value
        assert isinstance(kind, SubType)
        start = next((j + 1 for j in range(len(result) - 1, -1, -1) if result[j].tag is Tag.SUBST), 0)
        if word.text in ("on", "off") or any(item.tag not in (Tag.FILLER, Tag.BOUNDARY, Tag.TEAM, Tag.TEAMREF) for item in result[start:]):
            return None
        said = next((item.value for item in [*result[start:], *clause[k + 1 : k + 2]] if item.tag in (Tag.TEAM, Tag.TEAMREF)), None)
        n = k + 1
        names: list[Item] = []
        while n < len(clause) and (_player(clause[n]) or _separator(clause[n]) or clause[n].tag is Tag.TEAMREF or (clause[n].tag is Tag.BOUNDARY and clause[n].value)):
            if _player(clause[n]):
                names.append(clause[n])
            n += 1
        if not names or n < len(clause):
            return None
        team = said if isinstance(said, int) else None
        return len(result), [_Spec(_name_of(item), kind, item.start, team) for item in names], n

    def _associate(self, clause: list[Item]) -> list[Item]:
        """Remove each "red shorts is kaia [on white]" from the clause, recording it if it identifies a roster player (`_identify`).
        The description stays if it is part of an event ("backhand to red shorts is kaia"). An identification alone in its part of
        the clause (after a comma or another identification) also takes the rest of that part if nothing there is an event."""
        result: list[Item] = []
        part = 0  # where the current part of the clause starts in `result`
        k = 0
        while k < len(clause):
            item = clause[k]
            if item.tag is not Tag.IS or not result or result[-1].tag is not Tag.NAME or k + 1 >= len(clause) or clause[k + 1].tag is not Tag.NAME:
                result.append(item)
                part = len(result) if item.tag is Tag.BOUNDARY else part
                k += 1
                continue
            after = clause[k + 2] if k + 2 < len(clause) else None
            explicit = after.value if after is not None and after.tag is Tag.TEAMREF and isinstance(after.value, int) else None
            if not clause[k + 1].text.endswith("'s"):  # not "the kid is kaia's brother"
                self._identify(str(result[-1].value), str(clause[k + 1].value), explicit)
            end = k + (3 if explicit is not None else 2)
            if all(x.tag in (Tag.FILLER, Tag.BOUNDARY, Tag.CORRECT) for x in result[part:-1]):  # alone: "oh, red shorts is kaia"
                del result[-1]
                rest = end
                while rest < len(clause) and clause[rest].tag in CHATTER:
                    rest += 1
                end = rest if rest == len(clause) or clause[rest].tag is Tag.BOUNDARY else end
            part = len(result)
            k = end
        return result

    def _identify(self, description: str, name: str, explicit: int | None) -> None:
        """Record "description is name" when `name` is a roster player of one known team (the one named, if any) and `description`
        is not itself a roster name: "kaia is wide open" and "this game is intense" identify nobody."""
        if any(self._roster_player(description, team) for team in range(len(self.teams))):
            return
        candidates = [team for team in range(len(self.teams)) if self._roster_player(name, team)]
        subbed = self._sub_teams.get(normalize(description)) if self._said_team(description) is None else None
        if explicit is None and subbed is not None and subbed not in candidates:
            self._learn(name, subbed)  # "small gloves is joe", and small gloves subs for dark: this joe is not white's
            return
        if explicit is not None:
            team = explicit if explicit in candidates else None
        elif len(candidates) == 1:
            team = candidates[0]
        else:
            team = next((t for t in (self.team_of(name), self.team_of(description)) if t is not None and t in candidates), None)
        if team is not None:
            self.associations.append(Association(self._label(team) or None, description, name))
            self._learn(description, team)

    def _roster_player(self, name: str, team: int) -> str | None:
        """The one player on the team's roster that `name` means (as PlayerResolver finds roster players), else None."""
        exact, partial = self._rosters[team]
        players = exact.get(normalize(name)) or partial.get(normalize(name), set())
        return next(iter(players)) if len(players) == 1 else None

    def _parse(self, group: _Group) -> None:
        i = 0
        while i < len(group.items):
            handler = self._handlers.get(group.items[i].tag)
            i = handler(group, i) if handler else i + 1

    @staticmethod
    def _next(items: list[Item], j: int) -> int:
        """Index of the next item that is not a filler or a comma."""
        while j < len(items) and (items[j].tag is Tag.FILLER or (items[j].tag is Tag.BOUNDARY and not items[j].value)):
            j += 1
        return j

    def _take_name(self, group: _Group, j: int) -> tuple[str | None, int, bool]:
        """(name, index after it, found) for a NAME or unknown-player phrase at the next item."""
        j = self._next(group.items, j)
        if j < len(group.items) and group.items[j].tag in (Tag.NAME, Tag.UNK):
            item = group.items[j]
            if item.tag is Tag.NAME:
                self._said = str(item.value)
            return (str(item.value) if item.tag is Tag.NAME else None), j + 1, True
        return None, j, False

    @staticmethod
    def _previous_tag(group: _Group, i: int) -> Tag | None:
        return next((group.items[k].tag for k in range(i - 1, -1, -1) if group.items[k].tag not in (Tag.FILLER, Tag.BOUNDARY)), None)

    def _on_team(self, group: _Group, i: int) -> int:
        """A bare team name: "black pulls", "white picks it up", or after a pickup or defense ("picked up by red shorts, dark").
        Anywhere else ("that's 5-4 white", "the dark corner") it says nothing about possession."""
        j = self._next(group.items, i + 1)
        team = group.items[i].value
        assert isinstance(team, int)
        following = group.items[j].tag if j < len(group.items) else None
        if following is Tag.PULL:  # "black pulls"
            if self._pending is not None:
                self._finish_throw(self._pending)
            self.possession, self.holder, self._stated = self._other(team), None, True
            return j + 1
        if following is Tag.PICKUP:  # "white picks it up"
            self._pickup(None)
            self.possession, self._stated = team, True
            group.subject = "pickup"
            return j + 1
        if following is Tag.CHECKIN:  # "dark checks it in"
            if self._pending is None:
                self.possession, self._stated = team, True
            return j + 1
        if self._tied(group, i):
            return self._on_team_ref(group, i)
        return i + 1

    def _tied(self, group: _Group, i: int) -> bool:
        """Does the bare team name at item i follow the pickup or defense just described, in the same sentence?"""
        if group.subject != "pickup" and not isinstance(group.subject, _Defense):
            return False
        k = i - 1
        while k >= 0 and (
            (group.items[k].tag is Tag.FILLER and group.items[k].text not in ("the", "a", "an")) or (group.items[k].tag is Tag.BOUNDARY and not group.items[k].value)
        ):
            k -= 1
        return k >= 0 and group.items[k].tag in TIES

    def _on_team_ref(self, group: _Group, i: int) -> int:
        team = group.items[i].value
        assert isinstance(team, int)
        subject = group.subject
        if subject == "lineup" or self._previous_tag(group, i) is Tag.NUM:
            return i + 1  # "d-line comes on for dark", "five four for white"
        self.possession, self._stated = team, True
        if isinstance(subject, _Defense):
            subject.team = team
        elif isinstance(subject, _Throw) and subject is self._pending:
            subject.team, subject.stated = team, True
            self._learn(subject.player, team)
        elif subject == "pickup":
            self._learn(self.holder, team)
        return i + 1

    def _on_name(self, group: _Group, i: int) -> int:
        item = group.items[i]
        name = str(item.value) if item.tag is Tag.NAME else None
        j = self._next(group.items, i + 1)
        following = group.items[j].tag if j < len(group.items) else None
        if name is not None and following in RESTATED and self._restates(group, i, name):
            return i + 1
        if name is not None:
            self._said = name
        for rule in (self._name_pickup, self._name_thrower, self._name_has, self._name_outcome, self._name_scorer, self._name_defender):
            k = rule(group, i, j, following, name)
            if k is not None:
                return k
        throw = self._pending
        if throw is not None and throw.open_for_receiver():
            throw.receiver, throw.receiver_set = name, True  # "backhand hat": "to" left out
        elif j >= len(group.items) and name is not None:
            self._carry = item
        return i + 1

    def _restates(self, group: _Group, i: int, name: str) -> bool:
        """Handle a name that corrects another: "not joe" (remembered), then any name when joe was said; or, right after "sorry"
        and ending its clause, "that was connor" or a name no open throw takes ("to joe, sorry, tristan"). Those must be known
        names (a roster, a line-up, or an earlier event), so that "wait, he stepped out" and "sorry, kaia, that was a great throw"
        replace nobody. True if it did."""
        before = tuple(item.text if item.tag is Tag.FILLER else "" for item in group.items[max(i - 2, 0) : i])
        if before[-1:] and before[-1] in NEGATIONS:  # "not joe", "that wasn't joe"
            group.correcting, group.wrong = True, name
            return True
        if not group.correcting:
            return False
        throw = self._pending
        restating = before[-2:] in (("that", "was"), ("it", "was")) or before[-1:] in (("that's",), ("it's",))
        if group.wrong is not None and normalize(group.wrong) != normalize(name) and self._mentions(group.wrong):
            old = group.wrong
        elif (
            (restating or throw is None or not throw.open_for_receiver())
            and self._said
            and normalize(self._said) != normalize(name)
            and (self.knows(name) or normalize(name) in self._seen)
            and _cued(group, i)
            and _ends_clause(group.items, i)
        ):
            old = self._said
        else:
            return False
        return self._rename(group, group.items[i], old, name)

    def _rename(self, group: _Group, cue: Item, old: str, new: str) -> bool:
        """Say `new` wherever the open throw, the most recent finished event that names `old`, or who holds the disc said `old`.
        False, changing nothing, if that would make a throw's thrower its receiver ("to joe for the score" | "sorry, kaia")."""
        key = normalize(old)
        record = None
        if not self._decided(cue):
            record = next((r for r in self._recent() if r is not self._pending and key in (normalize(r.player or ""), normalize(getattr(r, "receiver", None) or ""))), None)
        if any(_to_self(r, old, new) for r in (self._pending, record) if isinstance(r, _Throw)):
            return False
        group.correcting, group.wrong = False, None
        self._said = new
        if self.holder is not None and normalize(self.holder) == key:
            self.holder = new
        changes: dict[str, object] = {"rename": (old, new)}
        if self._pending is not None:
            _change(self._pending, changes)
        if record is not None:
            self._retract(record, changes, cue)
        return True

    def _name_pickup(self, group: _Group, i: int, j: int, following: Tag | None, name: str | None) -> int | None:
        if following not in (Tag.PICKUP, Tag.CHECKIN):  # "stephen picks it up", "gloves taps it in"
            return None
        self._pickup(name, checkin=following is Tag.CHECKIN)
        group.subject = "pickup"
        return j + 1

    def _name_thrower(self, group: _Group, i: int, j: int, following: Tag | None, name: str | None) -> int | None:
        if following not in THROW_STARTS:  # "joe big flick huck", "bush backhand to george"
            return None
        throw = self._pending
        if throw is not None and not (throw.receiver_set or throw.type or throw.direction or throw.completed is not None):
            return None  # "to ... X flick": X more likely finishes the open throw
        self._check_thrower_team(name)
        nxt = group.items[i + 1] if i + 1 < len(group.items) else group.items[i]
        group.subject = self._start_throw(nxt.start, thrower=name, named=True)
        return i + 1

    def _name_has(self, group: _Group, i: int, j: int, following: Tag | None, name: str | None) -> int | None:
        if following is not Tag.HAS:  # "close crop gets it": completes an open throw, else just says who has the disc
            return None
        throw = self._pending
        if throw is not None and throw.open_for_receiver():
            throw.receiver, throw.receiver_set, throw.completed = name, True, True
        elif throw is None:
            self.holder, self._passed = name, False
            team = self.team_of(name)
            self.possession = team if team is not None else self.possession
        return j + 1

    def _name_outcome(self, group: _Group, i: int, j: int, following: Tag | None, name: str | None) -> int | None:
        throw = self._pending
        if following not in (Tag.CAUGHT, Tag.DROP, Tag.SCORE) or throw is None or not throw.open_for_receiver():
            return None
        throw.receiver, throw.receiver_set = name, True  # "kaia catches it", "kaia drops it", "joe scores"
        return i + 1

    def _name_scorer(self, group: _Group, i: int, j: int, following: Tag | None, name: str | None) -> int | None:
        throw = self._pending
        if following is not Tag.EZ_IN or name is None or throw is None or not throw.receiver_set or throw.completed is False:
            return None
        if normalize(throw.receiver or "") == normalize(name):
            return None  # "... to kaia" | "kaia in the end zone": the same throw
        new = self._start_throw(group.items[i].start)  # "backhand to glasses. tristan in the end zone": glasses threw to tristan
        new.receiver, new.receiver_set = name, True
        group.subject = new
        return i + 1

    def _name_defender(self, group: _Group, i: int, j: int, following: Tag | None, name: str | None) -> int | None:
        if following not in (Tag.DEFENSE, Tag.INTERCEPT) or group.items[j].text.endswith(" by"):
            return None
        return self._defense(group, j, name, j + 1)  # "glasses with the d"

    def _check_thrower_team(self, name: str | None) -> None:
        """A thrower known to play for the other team means a turnover was missed: the open throw was not completed."""
        team = self.team_of(name)
        if team is None or self.possession is None or team == self.possession:
            return
        throw = self._pending
        if throw is not None and throw.team != team and throw.completed is not True and not throw.scored:
            throw.completed = False
            self._finish_throw(throw)
        self.possession, self._stated = team, False

    def _on_pickup(self, group: _Group, i: int) -> int:
        name, j, found = self._take_name(group, i + 1)  # "picked up by pikachu"
        self._pickup(name if found else None)
        group.subject = "pickup"
        return j

    def _on_style(self, group: _Group, i: int) -> int:
        item = group.items[i]
        attr = "type" if item.tag is Tag.TYPE else "direction"
        throw = self._pending
        if throw is None or not throw.open_for_style(attr):
            throw = self._start_throw(item.start)
        setattr(throw, attr, item.value)
        group.subject = throw
        return i + 1

    def _on_to(self, group: _Group, i: int) -> int:
        name, j, found = self._take_name(group, i + 1)
        before = self._previous_tag(group, i)
        k = self._next(group.items, i + 1)
        after = group.items[k].tag if k < len(group.items) else None
        if Tag.NUM in (before, after):
            return k + 1  # a score line: "five to three"
        if not found and before is not None and after not in (Tag.EZ_IN, Tag.EZ_TO, Tag.SCORE, Tag.WALL, Tag.NET):
            return i + 1  # a "to" with nothing throw-like after it
        throw = self._pending
        correction = group.correcting and throw is not None and throw.receiver_set and throw.completed is not False
        if group.correcting and found and throw is None:  # "... in the end zone. | Sorry, to tristan": the last receiver
            group.correcting = False
            if self._decided(group.items[i]):
                return j
            target = self._last_throw()
            if target is not None and target.receiver_set:
                self._retract(target, {"receiver": name}, group.items[i])
        group.correcting = False
        if throw is None or not (throw.open_for_receiver() or correction):
            throw = self._start_throw(group.items[i].start)
        if found:
            throw.receiver, throw.receiver_set = name, True
        group.subject = throw
        return j

    def _on_correct(self, group: _Group, i: int) -> int:
        """A correction word. Right after a substitution, "nope" alone, or "sorry, tristan on" (the same kind, or the same player),
        takes that substitution back."""
        group.correcting = True
        latest = self._latest()
        if isinstance(latest, _Sub) and group.items[i].text in RETRACTS:
            k = i + 1
            while k < len(group.items) and group.items[k].tag is Tag.BOUNDARY and not group.items[k].value:
                k += 1
            following = group.items[k] if k < len(group.items) else None
            if following is None or (following.tag is Tag.BOUNDARY and following.value):
                self._drop(latest)
            elif following.tag is Tag.SUBST and isinstance(following.value, list) and following.value:
                spec = following.value[0]
                if spec.sub_type is latest.sub_type or normalize(spec.name) == normalize(latest.player):
                    self._drop(latest)
        return i + 1

    def _on_sub(self, group: _Group, i: int) -> int:
        """Substitutions said together (a SUBST item). The team: the one said, else `team_of` the name (said, rosters, earlier
        substitutions), another name said with it, or the team of the player subbed off just before it ("dylan off. small gloves
        on."). The teams of the name's throws are not used: they follow possession, which misses turnovers nobody said."""
        specs = group.items[i].value
        assert isinstance(specs, list)
        known = [team for team in (spec.team if spec.team is not None else self.team_of(spec.name) for spec in specs) if team is not None]
        common = known[0] if known and all(team == known[0] for team in known) else None
        for spec in specs:
            team = spec.team if spec.team is not None else self.team_of(spec.name)
            team = team if team is not None else common
            previous = self._latest()
            if isinstance(previous, _Sub) and previous.sub_type is SubType.SUB_OFF and spec.sub_type is SubType.SUB_ON:
                if (spec.start - previous.when).total_seconds() <= PAIRED_WITHIN:
                    if team is None:
                        team = previous.team
                    elif previous.team is None:
                        previous.team = team
                        self._note_teams(team, previous.player)
            record = _Sub(spec.start, team, spec.name, spec.sub_type)
            if self._pending is not None:
                self._subs_after.append(record)
            else:
                changes = self._late.get((record.when, self._position()))
                if changes:
                    _change(record, changes)
                self._done.append(record)
            self._learn(spec.name, spec.team)
            self._note_teams(team, record.player)
            self._seen.add(normalize(record.player))
            self._said = record.player
        group.correcting = False
        return i + 1

    def _note_teams(self, team: int | None, *names: str | None) -> None:
        if team is not None:
            for name in names:
                if name:
                    self._sub_teams[normalize(name)] = team

    def _latest(self) -> _Throw | _Defense | _Sub | None:
        """The event said last, while it can still change."""
        if self._subs_after:
            return self._subs_after[-1]
        if self._pending is not None:
            return self._pending
        if self._done:
            return self._done[-1]
        return self._unsettled[-1] if self._unsettled and self._window is not None else None

    def _drop(self, record: _Sub) -> None:
        for records in (self._subs_after, self._done, self._unsettled):
            for k, other in enumerate(records):
                if other is record:
                    del records[k]
                    return

    def _on_lineup(self, group: _Group, i: int) -> int:
        group.subject = "lineup"  # a team named next is the line's, not the team with the disc
        return i + 1

    def _on_boundary(self, group: _Group, i: int) -> int:
        if group.items[i].value:
            group.subject = None  # a sentence ends: "for dark" in the next one is about something new
        return i + 1

    def _on_throw_verb(self, group: _Group, i: int) -> int:
        throw = self._pending
        if throw is None or throw.receiver_set or throw.completed is not None:
            throw = self._start_throw(group.items[i].start)  # "kaia hits pikachu", "throws it to tristan"
        name, j, found = self._take_name(group, i + 1)
        if found:
            throw.receiver, throw.receiver_set = name, True
        group.subject = throw
        return j if found else i + 1

    def _on_caught(self, group: _Group, i: int) -> int:
        name, j, found = self._take_name(group, i + 1)
        throw = self._pending
        if throw is None or throw.completed is False:
            throw = self._start_throw(group.items[i].start)
        if found:
            throw.receiver, throw.receiver_set = name, True
        throw.completed = True
        group.subject = throw
        return j

    def _on_defense(self, group: _Group, i: int) -> int:
        name, j, found = self._take_name(group, i + 1)  # "deed by stephen butler", "stolen by gloves"
        return self._defense(group, i, name if found else None, j)

    def _defense(self, group: _Group, i: int, name: str | None, j: int) -> int:
        """A block or interception (item i) by `name`; the open throw was not completed. Returns the index to parse next."""
        item = group.items[i]
        k = self._next(group.items, j)
        explicit = group.items[k].value if k < len(group.items) and group.items[k].tag is Tag.TEAMREF else None
        j = k + 1 if explicit is not None else j
        thrower_team, stated = self.possession, self._stated
        throw = self._pending
        if throw is not None:
            if throw.completed is not False:
                throw.completed, throw.scored = False, False
            stated = throw.stated
            self._finish_throw(throw)
            thrower_team = throw.team if throw.team is not None else thrower_team
        defender = self.team_of(name)
        if explicit is None and defender is not None and defender == thrower_team and not stated and (throw is None or not throw.backed and self._evidence(throw, None) is None):
            thrower_team = self._other(defender)  # "deed by joe" and joe plays for the team that was thought to have the disc
            if throw is not None:
                throw.team = thrower_team
        team = next((t for t in (explicit, self._other(thrower_team), defender) if isinstance(t, int)), None)
        defense = _Defense(item.start, team, name, item.tag is Tag.INTERCEPT)
        changes = self._late.get((defense.when, self._position()))
        if changes:
            _change(defense, changes)
        self._done.append(defense)
        if defense.player:
            self._seen.add(normalize(defense.player))
        self.possession, self.holder, self._stated, self._passed = team, defense.player if defense.intercepted else None, isinstance(explicit, int), False
        self._learn(defense.player, explicit if isinstance(explicit, int) else None)
        group.subject = defense
        return j

    def _on_drop(self, group: _Group, i: int) -> int:
        throw = self._pending
        item = group.items[i]
        if throw is None and (item.tag is Tag.NOSCORE or group.correcting):  # "... for a score. | No score."
            target = self._last_throw()
            if target is not None and target.scored and not self._decided(item):
                self._retract(target, {"completed": False}, item)
        elif throw is not None:
            throw.completed, throw.scored, throw.decisive = False, False, True
        return i + 1

    def _on_not_in(self, group: _Group, i: int) -> int:
        """ "not in the end zone", "not a score", "nope, not in": the most recent throw, if said to score, did not (it may still have
        been caught). A bare "not in" counts only right after a correction word: "george not in position" takes nothing back."""
        item = group.items[i]
        if item.value == "cued" and not _cued(group, i, NEGATED):
            return i + 1
        target = self._last_throw()
        if target is not None and (target.scored or target.ez_in or target.ez_to) and not self._decided(item):
            self._retract(target, {"scored": False}, item)
        return i + 1

    def _on_throwaway(self, group: _Group, i: int) -> int:
        throw = self._pending
        if throw is None or throw.completed is not None or throw.receiver_set:
            throw = self._start_throw(group.items[i].start)  # "kaia throws it away"
        throw.completed, throw.scored, throw.decisive = False, False, True
        group.subject = throw
        return i + 1

    def _on_score(self, group: _Group, i: int) -> int:
        ahead = [item.tag for item in group.items[i + 1 : i + 5] if item.tag not in (Tag.FILLER, Tag.BOUNDARY)]
        if Tag.NUM in ahead[:2] or Tag.IS in ahead[:1]:
            return i + 1  # a score line: "score is five four", "score's five four"
        if i and group.items[i - 1].text in ("the", "what's", "whats", "what") and group.items[i].text.startswith("score"):
            return i + 1  # "what's the score?"
        throw = self._pending
        if throw is not None and throw.completed is not False:
            throw.scored = throw.completed = throw.decisive = True
        return i + 1

    def _on_end_zone(self, group: _Group, i: int) -> int:
        throw = self._pending
        if throw is None:
            return i + 1
        if group.items[i].tag is Tag.EZ_TO:
            throw.ez_to = True
        elif throw.completed is not False:
            throw.ez_in = True
            throw.decisive = throw.decisive or throw.receiver_set or bool(throw.completed)
        return i + 1

    def _on_wall(self, group: _Group, i: int) -> int:
        throw = self._pending
        if throw is not None:
            if group.items[i].tag is Tag.WALL:
                throw.hit_wall = True
            else:
                throw.hit_net = True
        return i + 1


def _cued(group: _Group, i: int, between: frozenset[str] | None = None) -> bool:
    """Does a correction word come right before item i, with only commas and fillers (those in `between`, if given) between
    ("sorry, that was tristan")?"""
    for item in reversed(group.items[:i]):
        if item.tag is Tag.CORRECT:
            return True
        if not (item.tag is Tag.BOUNDARY and not item.value) and not (item.tag is Tag.FILLER and (between is None or item.text in between)):
            return False
    return False


def _ends_clause(items: list[Item], i: int) -> bool:
    """Does the name at item i end its clause ("to joe, sorry, tristan", "that was connor to james"), rather than start a remark
    ("sorry, kaia, that was a great throw", "actually, tristan has been great tonight")?"""
    k = i + 1
    while k < len(items) and items[k].tag is Tag.BOUNDARY and not items[k].value:
        k += 1
    return k == len(items) or items[k].tag in (Tag.BOUNDARY, Tag.TO, Tag.TEAM, Tag.TEAMREF, Tag.CORRECT)


def _player(item: Item, alone: bool = True) -> bool:
    """Can the item be a player substituted: a name, or a number said as digits ("26 off"; a small one only right before the
    substitution word: "5 off")?"""
    return item.tag is Tag.NAME or (alone and item.tag is Tag.NUM and item.text.isdigit())


def _names_before(items: list[Item], end: int) -> int:
    """Where the list of names ending at items[end] starts ("close crop, emily", "ari and ben"); `end` if there is none. A name
    right after "to", "caught by", "picked up by" or a throw word is that event's, not the list's ("to 50, tristan", "backhand swing
    close crop, pikachu")."""
    first = end
    while first > 0 and _player(items[first - 1], alone=first == end):
        first -= 1
        gap = first
        while gap > 0 and _separator(items[gap - 1]):
            gap -= 1
        if gap == first or gap == 0 or not _player(items[gap - 1]):
            break
        first = gap
    if first < end and first > 0 and items[first - 1].tag in NAMED_BY:
        first += 1
        while first < end and not _player(items[first]):
            first += 1
    return first


def _name_of(item: Item) -> str:
    return str(item.value) if item.tag is Tag.NAME else item.text


def _separator(item: Item) -> bool:
    return (item.tag is Tag.BOUNDARY and not item.value) or (item.tag is Tag.FILLER and item.text == "and")


def _sub_ends(clause: list[Item], n: int) -> bool:
    """Does a substitution word followed by clause[n:] end its phrase: the clause ends, a boundary, a correction, "and", or the
    next substitution ("tanner off purple off")?"""
    if n >= len(clause) or clause[n].tag in (Tag.BOUNDARY, Tag.CORRECT) or (clause[n].tag is Tag.FILLER and clause[n].text == "and"):
        return True
    k = n
    while k < len(clause) and (_player(clause[k]) or _separator(clause[k])):
        k += 1
    if k < len(clause) and clause[k].tag is Tag.IS and clause[k].text == "is":
        k += 1
    return k > n and k < len(clause) and clause[k].tag is Tag.SUB


def _trailing_subs(events: list[yus.Event]) -> tuple[list[yus.Event], list[ultimate.Substitution]]:
    """`events` without the substitutions at their end, and those substitutions."""
    k = len(events)
    while k > 0 and isinstance(events[k - 1], ultimate.Substitution):
        k -= 1
    return events[:k], [event for event in events[k:] if isinstance(event, ultimate.Substitution)]


def _to_self(throw: _Throw, old: str, new: str) -> bool:
    """Would saying `new` for `old` make the throw's thrower its receiver?"""
    player, receiver = (new if name and normalize(name) == normalize(old) else name for name in (throw.player, throw.receiver))
    return bool(player and receiver and normalize(player) == normalize(receiver))


def _change(record: _Throw | _Defense, changes: dict[str, object]) -> None:
    """Apply a correction to an event being parsed."""
    for field, value in changes.items():
        if field == "rename":
            assert isinstance(value, tuple)
            old, new = value
            for attr in ("player", "receiver"):
                if normalize(getattr(record, attr, None) or "") == normalize(old):
                    setattr(record, attr, new)
        elif isinstance(record, _Throw) and field == "scored":  # not in the end zone
            record.scored = record.ez_in = record.ez_to = record.decisive = False
        elif isinstance(record, _Throw) and field == "completed":  # no score: a turnover
            record.completed, record.scored, record.decisive = False, False, True
        elif isinstance(record, _Throw) and field == "receiver":
            record.receiver, record.receiver_set = value if isinstance(value, str) else None, True


def _outcome(event: yus.Event | None) -> tuple:
    """What an event says about who has the disc next."""
    if isinstance(event, ultimate.Throw):
        return ("throw", event.team, event.receiver, event.completed, event.scored)
    if isinstance(event, ultimate.Defense):
        return ("defense", event.team, event.player, event.intercepted)
    return (type(event).__name__,)


def _dangling_team_prefix(items: list[Item]) -> int:
    """How many items at the end are the start of a team reference that the next group may finish: "for", "on the". An "on" only
    right after a pickup or a defense ("picked up by blue on" | "dark"): "fulmer on" is a substitution."""
    texts = tuple(item.text if item.tag in (Tag.FILLER, Tag.SUB) else "" for item in items[-2:])
    held = 1 if texts[-1:] in (("for",), ("on",)) else 2 if texts in (("for", "the"), ("on", "the")) else 0
    if held and items[-held].tag is Tag.SUB:
        before = [item.tag for item in items[: len(items) - held] if item.tag is not Tag.FILLER][-2:]
        if not (before[-1:] and before[-1] in TIED_TO) and not (before[-1:] == [Tag.NAME] and before[:1] and before[0] in TIED_TO):
            return 0
    return held


def extract_events(
    transcript: yus.Transcript, teams: list[yus.Team] | None = None, timeout: float | None = None, llm: LLMAssistant | None = None, lineups: bool = False
) -> yus.EventStream:
    """All events of a transcript: feed every group to an EventExtractor, then finish. With `llm`, uncertain groups also go to that
    model, each waiting for its answer up to the assistant's budget (see `llm.AssistedExtractor`). `lineups`: see EventExtractor."""
    extractor: EventExtractor | AssistedExtractor = EventExtractor(teams, timeout=timeout, lineups=lineups)
    if llm is not None:
        from yus.processing.event_extraction.llm import AssistedExtractor

        extractor = AssistedExtractor(extractor, llm, wait=True)
    for group in transcript.groups:
        extractor.feed(group)
    extractor.finish()
    return yus.EventStream(game=transcript.game, transcript=transcript, events=extractor.events)
