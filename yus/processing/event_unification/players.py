"""Resolve the names commentators used for players ("pikachu", "the kid", "yellow border") to the players themselves.

Where this fits: event extraction writes each event's player and receiver as the commentator said them. Before streams are
merged or stats computed, this step rewrites them, per stream and per team, as:
  1. a roster player, when this game's descriptions say so ("the kid" is Serayan Knappe-Butler), or when the team file knows
     the name (full name, nickname, or mondegreen; else a first or last name unique on the team);
  2. one label per unknown player, when this game's descriptions group several descriptions of the same unknown person
     ("yellow border", "yellow fringe" -> "yellow sleeve"); describing the label later identifies the whole group;
  3. otherwise the name as spoken.
`unresolved()` lists 2 and 3, so that a person can identify them.

Team files hold only what is true of a player in every game. What one commentator called someone in one game belongs in that
game's `GameDescriptions`, which can grow during the game. Resolution is a pure function of the raw events, the rosters, and the
descriptions, and costs microseconds per event; live use re-resolves the raw stream whenever an event or a description arrives,
so a description added mid-game also fixes the events before it.
"""

from __future__ import annotations

import collections
import re
import unicodedata
from typing import TypeVar

import pydantic

import yus
from yus.sports import ultimate

E = TypeVar("E", bound=yus.Event)


def normalize(name: str) -> str:
    """Comparable form of a name: case-folded, no possessive or punctuation, hyphens as spaces, "&" as "and", no leading "the"
    ("The Kid's," -> "kid")."""
    text = unicodedata.normalize("NFKC", name).casefold().replace("&", " and ").replace("-", " ").replace("_", " ")
    text = re.sub(r"['’‘ʼ]s\b", "", text)
    words = re.sub(r"[^\w\s]", " ", text).split()
    if len(words) > 1 and words[0] == "the":
        words = words[1:]
    return " ".join(words)


class PlayerDescription(pydantic.BaseModel):
    """One player as commentators described them during one game, e.g. "the kid" is Serayan Knappe-Butler."""

    model_config = pydantic.ConfigDict(extra="forbid")

    team: str = pydantic.Field(..., description='Any name of the player\'s team, e.g. "white" or "Dump & Drizzle".')
    descriptions: list[str] = pydantic.Field(..., min_length=1, description='What commentators called this player, e.g. ["the kid"].')
    player: str | None = pydantic.Field(None, description="The roster player described, or None while nobody knows who it is.")
    label: str | None = pydantic.Field(None, description="Name to use for an unknown player; defaults to the first description.")
    commentator: str | None = pydantic.Field(None, description="Apply only to this commentator's event streams; None applies to all.")

    @property
    def name(self) -> str:
        """The name resolved events get for this player."""
        return self.player or self.label or self.descriptions[0]


class GameDescriptions(pydantic.BaseModel):
    """Who commentators meant by their descriptions, for one game. Kept per game (e.g. alongside its transcripts)."""

    model_config = pydantic.ConfigDict(extra="forbid")

    players: list[PlayerDescription] = []


class PlayerResolver:
    """Resolves spoken player names for one game, from its team rosters and its descriptions.

    resolver = PlayerResolver(game.teams, descriptions)
    resolved = resolver.resolve_stream(raw_stream)   # raw_stream is left unchanged
    resolver.describe("white", ["red shorts"], player="Kaia Mann")   # learned mid-game
    resolved = resolver.resolve_stream(raw_stream)   # earlier "red shorts" events now say Kaia Mann
    path.write_text(resolver.descriptions.model_dump_json(indent=2))   # keep what was learned with the game
    """

    def __init__(self, teams: list[yus.Team], descriptions: GameDescriptions | None = None):
        self.teams = teams
        self.descriptions = GameDescriptions()
        self._team_index: dict[str, int] = {}
        for i, team in enumerate(teams):
            for name in team.names:
                if self._team_index.setdefault(normalize(name), i) != i:
                    raise ValueError(f"Two teams are called {name!r}")
        self._roster = [roster_aliases(team) for team in teams]
        self._described: dict[tuple[int, str], list[PlayerDescription]] = collections.defaultdict(list)
        for description in (descriptions or GameDescriptions()).players:
            self.add(description)

    def describe(self, team: str, descriptions: list[str], player: str | None = None, label: str | None = None, commentator: str | None = None) -> PlayerDescription:
        """Record that `descriptions` all mean one player: `player`, or an unknown person called `label`. To identify an unknown
        player later, describe its label: describe("black", ["yellow sleeve"], player="Jerry Swider")."""
        return self.add(PlayerDescription(team=team, descriptions=descriptions, player=player, label=label, commentator=commentator))

    def add(self, description: PlayerDescription) -> PlayerDescription:
        """Record a description (stored in `self.descriptions`) and return it. Raises ValueError for an unknown team, a player not on
        that team's roster, or an empty description. For one name, a commentator's own record beats shared ones; later records win."""
        team = self.team_index(description.team)
        if team is None:
            raise ValueError(f"No team is called {description.team!r}; teams: {[t.names for t in self.teams]}")
        if description.player is not None:
            roster = {normalize(player): player for player in self.teams[team].players}
            if normalize(description.player) not in roster:
                raise ValueError(f"{description.player!r} is not on the roster of {self.teams[team].names[0]!r}")
            description = description.model_copy(update={"player": roster[normalize(description.player)]})
        if not all(normalize(text) for text in description.descriptions):
            raise ValueError(f"Empty description in {description.descriptions!r}")
        self.descriptions.players.append(description)
        for text in description.descriptions:
            self._described[(team, normalize(text))].append(description)
        return description

    def team_index(self, team: str | None) -> int | None:
        """Position in `teams` of the team with this name (any of its names, ignoring case), or None."""
        return self._team_index.get(normalize(team)) if team else None

    def resolve(self, name: str | None, team: str | None, commentator: str | None = None) -> str | None:
        """The player (or unknown player's label) that `name` means on `team`, or `name` itself when it can't be resolved."""
        found = self._lookup(name, team, commentator)
        return name if found is None else found

    def resolve_event(self, event: E, commentator: str | None = None) -> E:
        """A copy of `event` with its player (and receiver, for throws) resolved."""
        if not isinstance(event, ultimate.UltimateEvent):
            return event.model_copy()
        update = {"player": self.resolve(event.player, event.team, commentator)}
        if isinstance(event, ultimate.Throw):
            update["receiver"] = self.resolve(event.receiver, event.team, commentator)
        return event.model_copy(update={field: value for field, value in update.items() if value != getattr(event, field)})

    def resolve_stream(self, stream: yus.EventStream, commentator: str | None = None) -> yus.EventStream:
        """A copy of `stream` with every event resolved. Commentator-specific descriptions use `commentator`, else the stream's
        transcript's commentator (a stream loaded from JSON has no transcript, so pass it)."""
        commentator = self._commentator(stream, commentator)
        events = [self.resolve_event(event, commentator) for event in stream.events]
        return yus.EventStream(game=stream.game, transcript=stream.transcript, events=events)

    def unresolved(self, stream: yus.EventStream, commentator: str | None = None) -> list[tuple[str, str, int]]:
        """(team, name, mentions) for each name that still needs a person to identify it, most mentioned first: names neither a
        roster player nor described, and labels of described but unknown players. Teams are given by their first name; names that
        normalize alike ("kid", "the kid") are counted together under their most common form."""
        commentator = self._commentator(stream, commentator)
        forms: dict[tuple[int, str], collections.Counter[str]] = collections.defaultdict(collections.Counter)
        for team, name in mentions(stream):
            index = self.team_index(team)
            resolved = self.resolve(name, team, commentator)
            if index is not None and resolved is not None and resolved not in self.teams[index].players:
                forms[(index, normalize(resolved))][resolved] += 1
        found = [(self._team_name(index), counts.most_common(1)[0][0], counts.total()) for (index, _), counts in forms.items()]
        return sorted(found, key=lambda item: -item[2])

    def unmentioned_players(self, stream: yus.EventStream, commentator: str | None = None) -> dict[str, list[str]]:
        """Roster players no event resolves to, per team (first team name): likely identities for the unresolved names."""
        commentator = self._commentator(stream, commentator)
        mentioned = {(self.team_index(team), self.resolve(name, team, commentator)) for team, name in mentions(stream)}
        return {self._team_name(i): [p for p in team.players if (i, p) not in mentioned] for i, team in enumerate(self.teams)}

    def _lookup(self, name: str | None, team: str | None, commentator: str | None) -> str | None:
        index = self.team_index(team)
        if name is None or index is None:
            return None
        found = self._described_as(index, normalize(name), commentator)
        if found is not None:
            if found.player is None and (named := self._described_as(index, normalize(found.name), commentator)) and named.player:
                return named.player  # the unknown player's label has since been identified
            return found.name
        exact, partial = self._roster[index]
        players = exact.get(normalize(name)) or partial.get(normalize(name), set())
        return next(iter(players)) if len(players) == 1 else None

    def _described_as(self, team: int, key: str, commentator: str | None) -> PlayerDescription | None:
        records = self._described.get((team, key), [])
        own = [d for d in records if commentator and d.commentator and normalize(d.commentator) == normalize(commentator)]
        shared = [d for d in records if d.commentator is None]
        return (own or shared or [None])[-1]

    def _team_name(self, index: int) -> str:
        team = self.teams[index]
        return team.names[0] if team.names else f"team {index + 1}"

    @staticmethod
    def _commentator(stream: yus.EventStream, commentator: str | None) -> str | None:
        return commentator or (stream.transcript.commentator if stream.transcript else None)


def roster_aliases(team: yus.Team) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Normalized names -> the roster players they may mean, in two tiers: (full names, nicknames, and mondegreens) and (first
    name, last name, and other parts of full names, e.g. "knappe butler", "knappe", "butler"). The first tier is tried first."""
    exact: dict[str, set[str]] = collections.defaultdict(set)
    partial: dict[str, set[str]] = collections.defaultdict(set)
    for player, info in team.players.items():
        for name in [player, *(info if isinstance(info, list) else [*info.nicknames, *info.mondegreens])]:
            if normalize(name):
                exact[normalize(name)].add(player)
        words = normalize(player).split()
        for part in [*words, *(" ".join(words[i:]) for i in range(1, len(words) - 1))]:
            if len(part) > 1:
                partial[part].add(player)
    return exact, partial


def mentions(stream: yus.EventStream) -> list[tuple[str, str]]:
    """(team, name) for every player and receiver named in the stream's events."""
    found = []
    for event in stream.events:
        if isinstance(event, ultimate.UltimateEvent):
            found += [(event.team, name) for name in (event.player, getattr(event, "receiver", None)) if name]
    return found
