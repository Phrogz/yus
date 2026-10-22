"""Rule-based, streaming event extraction: transcript groups in, indoor Ultimate events out.

Each group is tagged (see `lexicon`) and parsed left to right by a small state machine that remembers which team has the disc,
who holds it, and at most one throw whose outcome is not yet known. That throw stays provisional until the commentary settles it:
an explicit outcome ("dropped", "deed by", "for a score", "caught by"), the next throw, a pickup, or `timeout` seconds of silence.
Everything else is final once its group has been parsed. Player names are kept as spoken, in lower case; event unification's
PlayerResolver maps them to players later. Teams are written as one of the team's names (see `team_label`).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Callable
from typing import NamedTuple

import yus
from yus.processing.event_extraction.lexicon import Item, Tag, Tagger, Token, tokenize
from yus.processing.event_unification.players import normalize, roster_aliases
from yus.sports import ultimate
from yus.sports.ultimate import ThrowDirection, ThrowType, indoor

COLORS = frozenset("white black dark light red blue green yellow orange purple pink grey gray navy maroon gold silver teal brown".split())
DEFAULT_TEAMS = (yus.Team(names=["white", "light"]), yus.Team(names=["black", "dark"]))
EVENT_TAGS = frozenset({Tag.TYPE, Tag.DIR, Tag.TO, Tag.THROWV, Tag.CAUGHT, Tag.DEFENSE, Tag.INTERCEPT, Tag.PICKUP, Tag.SCORE, Tag.DROP, Tag.THROWAWAY})
THROW_STARTS = (Tag.TYPE, Tag.DIR, Tag.TO, Tag.THROWV, Tag.THROWAWAY)
CHATTER = frozenset({Tag.FILLER, Tag.NAME, Tag.UNK, Tag.NUM})  # what an identification takes with it when alone: "pikachu is killing it tonight"
TIES = frozenset({Tag.NAME, Tag.UNK, Tag.PICKUP, Tag.CHECKIN, Tag.TO, Tag.DEFENSE, Tag.INTERCEPT})  # what a bare team name may follow


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
class _Group:
    items: list[Item]
    subject: _Throw | _Defense | str | None = None  # what a following "for dark" refers to ("pickup", or "lineup" for "d-line ...")
    correcting: bool = False  # after "sorry": the next receiver replaces the last one


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

    def __init__(self, teams: list[yus.Team] | None = None, timeout: float | None = None):
        self.teams = list(teams) if teams else [team.model_copy() for team in DEFAULT_TEAMS]
        self.timeout = timeout
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
        self._handlers: dict[Tag, Callable[[_Group, int], int]] = {
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
            Tag.THROWAWAY: self._on_throwaway,
            Tag.SCORE: self._on_score,
            Tag.EZ_IN: self._on_end_zone,
            Tag.EZ_TO: self._on_end_zone,
            Tag.WALL: self._on_wall,
            Tag.NET: self._on_wall,
            Tag.CORRECT: self._on_correct,
            Tag.LINEUP: self._on_lineup,
            Tag.BOUNDARY: self._on_boundary,
        }

    @property
    def events(self) -> list[yus.Event]:
        """Final events, then provisional ones."""
        return self._final + ([self._render(self._pending)] if self._pending is not None else [])

    @property
    def final_count(self) -> int:
        """How many of `events` are final."""
        return len(self._final)

    def feed(self, group: yus.TranscriptGroup) -> None:
        """Parse the next transcript group (its first interpretation)."""
        words = group.words
        if not words:
            return
        self.advance(words[0].start)
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
        self._parse(parsed)
        if self._held and parsed.subject == "pickup":
            self._held_subject = "pickup"
        pending = self._pending
        if pending is not None and (pending.decisive or (pending.completed is True and not pending.ez_to)):
            self._finish_throw(pending)  # a catch toward the end zone waits: a pickup by the other team next means it scored
        self._last_end = max(word.start + word.duration for word in words)
        self._commit()

    def advance(self, now: dt.datetime) -> None:
        """Note that the transcript is complete up to `now` (transcript time, not wall-clock time): after more than `timeout`
        seconds without words, the provisional throw becomes final as it stands."""
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
        """Index of the team `name` plays for, from what the commentator said, else the rosters; None if unknown or ambiguous."""
        if not name:
            return None
        key = normalize(name)
        return self._name_team[key] if key in self._name_team else self._roster_team.get(key)

    # ------------------------------------------------------------------ events and state

    def _label(self, team: int | None) -> str:
        return self.labels[team] if team is not None else ""

    def _other(self, team: int | None) -> int | None:
        return 1 - team if team is not None and len(self.teams) == 2 else None

    def _learn(self, name: str | None, team: int | None) -> None:
        if name and team is not None:
            self._name_team[normalize(name)] = team

    def _render(self, record: _Throw | _Defense) -> yus.Event:
        if isinstance(record, _Defense):
            return ultimate.Defense(when=record.when, team=self._label(record.team), player=record.player, intercepted=record.intercepted)
        completed = record.completed is not False
        team = record.team if record.team is not None else self.possession
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
        self._final.extend(self._render(record) for record in self._done)
        self._done.clear()

    def _finish_throw(self, throw: _Throw) -> None:
        if throw.team is None:
            for team in (self.possession, self.team_of(throw.player), self.team_of(throw.receiver)):
                if team is not None:
                    throw.team = team
                    break
        throw.completed = throw.completed is not False
        throw.scored = throw.completed and (throw.scored or throw.ez_in)
        if throw.completed and not throw.scored:
            self.possession, self.holder = throw.team, throw.receiver
        else:
            self.possession, self.holder = self._other(throw.team), None
        self._done.append(throw)
        if self._pending is throw:
            self._pending = None

    def _start_throw(self, when: dt.datetime, thrower: str | None = None, named: bool = False) -> _Throw:
        previous = self._pending
        if previous is not None:
            if named and previous.open_for_receiver():
                previous.receiver, previous.receiver_set = thrower, True  # "flick huck" | "joe backhand to ...": joe caught it
            self._finish_throw(previous)
        player = thrower if named else self.holder
        team = self.possession if self.possession is not None else self.team_of(player)
        self._pending = _Throw(when, team, player)
        return self._pending

    def _pickup(self, name: str | None, checkin: bool = False) -> None:
        throw = self._pending
        if throw is not None and not checkin:
            if throw.completed is True and (throw.ez_in or throw.ez_to):
                throw.scored = True  # caught in or toward the end zone, then the disc is picked up: a score
            elif not throw.scored and throw.completed is not True:
                throw.completed = False  # someone picks it up: the throw hit the ground
            self._finish_throw(throw)
        self.holder = name
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
            team = next((item.value for item in clause if item.tag in (Tag.TEAM, Tag.TEAMREF)), None)
            for item in clause:
                if item.tag is Tag.NAME:
                    self._learn(str(item.value), team if isinstance(team, int) else None)
                    self._tagger.add_name(str(item.value))
            return []
        return self._associate(clause) if Tag.IS in tags else clause

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
            if all(x.tag in (Tag.FILLER, Tag.BOUNDARY) for x in result[part:-1]):  # alone: "oh, red shorts is kaia"
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
            self.possession, self.holder = self._other(team), None
            return j + 1
        if following is Tag.PICKUP:  # "white picks it up"
            self._pickup(None)
            self.possession = team
            group.subject = "pickup"
            return j + 1
        if following is Tag.CHECKIN:  # "dark checks it in"
            self.possession = team if self._pending is None else self.possession
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
        self.possession = team
        if isinstance(subject, _Defense):
            subject.team = team
        elif isinstance(subject, _Throw) and subject is self._pending:
            subject.team = team
            self._learn(subject.player, team)
        elif subject == "pickup":
            self._learn(self.holder, team)
        return i + 1

    def _on_name(self, group: _Group, i: int) -> int:
        item = group.items[i]
        name = str(item.value) if item.tag is Tag.NAME else None
        j = self._next(group.items, i + 1)
        following = group.items[j].tag if j < len(group.items) else None
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
            self.holder = name
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
        self.possession = team

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
        group.correcting = False
        if throw is None or not (throw.open_for_receiver() or correction):
            throw = self._start_throw(group.items[i].start)
        if found:
            throw.receiver, throw.receiver_set = name, True
        group.subject = throw
        return j

    def _on_correct(self, group: _Group, i: int) -> int:
        group.correcting = True
        return i + 1

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
        thrower_team = self.possession
        throw = self._pending
        if throw is not None:
            if throw.completed is not False:
                throw.completed, throw.scored = False, False
            thrower_team = throw.team if throw.team is not None else thrower_team
            self._finish_throw(throw)
        team = next((t for t in (explicit, self._other(thrower_team), self.team_of(name)) if isinstance(t, int)), None)
        defense = _Defense(item.start, team, name, item.tag is Tag.INTERCEPT)
        self._done.append(defense)
        self.possession, self.holder = team, name if defense.intercepted else None
        self._learn(name, explicit if isinstance(explicit, int) else None)
        group.subject = defense
        return j

    def _on_drop(self, group: _Group, i: int) -> int:
        throw = self._pending
        if throw is not None:
            throw.completed, throw.scored, throw.decisive = False, False, True
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


def _dangling_team_prefix(items: list[Item]) -> int:
    """How many items at the end are the start of a team reference that the next group may finish: "for", "on the"."""
    texts = tuple(item.text if item.tag is Tag.FILLER else "" for item in items[-2:])
    if texts[-1:] in (("for",), ("on",)):
        return 1
    return 2 if texts in (("for", "the"), ("on", "the")) else 0


def extract_events(transcript: yus.Transcript, teams: list[yus.Team] | None = None, timeout: float | None = None) -> yus.EventStream:
    """All events of a transcript: feed every group to an EventExtractor, then finish."""
    extractor = EventExtractor(teams, timeout=timeout)
    for group in transcript.groups:
        extractor.feed(group)
    extractor.finish()
    return yus.EventStream(game=transcript.game, transcript=transcript, events=extractor.events)
