"""Compute game stats as pandas tables from a resolved event stream.

`compute_stats()` walks the stream once, in order, to number points and possessions, then counts in plain Python and builds the
DataFrames at the end, so that a live UI can recompute everything whenever an event arrives (a few milliseconds per game).

Indoor rules assumed: the first point starts with a pull; after a goal the team scored on picks up the disc, so a "hold" is a
point won by the team that started it on offense, and a "break" is one won by the other team.

Times with a UTC offset are turned into naive wall-clock times (pandas can't mix the two); a team the events leave empty ("") is
inferred from who had the disc.
"""

from __future__ import annotations

import datetime
import math
from collections.abc import Callable
from typing import Any, ClassVar

import pandas as pd
import pydantic

import yus
from yus.processing.event_unification.players import normalize
from yus.sports import ultimate

UNKNOWN = "unknown"
"""Row label for a throw type or direction the commentator didn't say."""

SCORE_PREFIX = "score_"
"""`score_timeline` names each team's running-score column `SCORE_PREFIX + team`, so that no team name can clash with a fixed column."""

THROW_TYPES = [str(kind) for kind in ultimate.ThrowType] + [UNKNOWN]
DIRECTIONS = [str(direction) for direction in ultimate.ThrowDirection] + [UNKNOWN]

Row = dict[str, Any]

# Column name -> dtype of every table, in output order. Flags that may be unknown use pandas' nullable dtypes ("boolean", "Int64").
_EVENT_COLUMNS = {"event": "int64", "when": "datetime64[ns]", "elapsed": "float64", "team": "object", "player": "object"}
THROW_COLUMNS = _EVENT_COLUMNS | {
    "receiver": "object",
    "type": "object",
    "direction": "object",
    "completed": "bool",
    "scored": "bool",
    "hit_wall": "bool",
    "hit_net": "bool",
    "point": "int64",
    "possession": "int64",
    "provisional": "bool",
}
DEFENSE_COLUMNS = _EVENT_COLUMNS | {"intercepted": "bool", "point": "int64", "possession": "Int64", "provisional": "bool"}
SUBSTITUTION_COLUMNS = _EVENT_COLUMNS | {"sub_type": "object", "point": "int64", "provisional": "bool"}
INFRACTION_COLUMNS = _EVENT_COLUMNS | {"point": "int64", "provisional": "bool"}
POSSESSION_COLUMNS = {
    "possession": "int64",
    "point": "int64",
    "team": "object",
    "start": "datetime64[ns]",
    "end": "datetime64[ns]",
    "duration_s": "float64",
    "throws": "int64",
    "completions": "int64",
    "outcome": "object",
    "provisional": "bool",
}
POINT_COLUMNS = {
    "point": "int64",
    "o_team": "object",
    "start": "datetime64[ns]",
    "end": "datetime64[ns]",
    "duration_s": "float64",
    "possessions": "int64",
    "throws": "int64",
    "turnovers": "int64",
    "scored_by": "object",
    "assist": "object",
    "scorer": "object",
    "hold": "boolean",
    "suspect": "bool",
    "provisional": "bool",
}
_TEAM_COUNTS = [
    "goals",
    "possessions",
    "o_points",
    "holds",
    "d_points",
    "breaks",
    "throws",
    "completions",
    "turnovers",
    "ds",
    "interceptions",
    "hucks",
    "huck_completions",
    "wall_throws",
    "net_throws",
]
TEAM_COLUMNS = (
    {"team": "object"}
    | dict.fromkeys(_TEAM_COUNTS, "int64")
    | {
        "goals_per_possession": "float64",
        "completion_pct": "float64",
        "huck_completion_pct": "float64",
        "provisional": "bool",
    }
)
_PLAYER_COUNTS = [
    "throws",
    "completions",
    "assists",
    "hockey_assists",
    "goals",
    "targets",
    "catches",
    "drops_or_misses",
    "turnovers",
    "ds",
    "interceptions",
    "hucks",
    "huck_completions",
]
PLAYER_COLUMNS = {"team": "object", "player": "object"} | dict.fromkeys(_PLAYER_COUNTS, "int64") | {"completion_pct": "float64", "provisional": "bool"}
_BREAKDOWN_COUNTS = {"throws": "int64", "completions": "int64", "goals": "int64", "turnovers": "int64", "completion_pct": "float64", "provisional": "bool"}
THROW_TYPE_COLUMNS = {"team": "object", "type": "object"} | _BREAKDOWN_COUNTS
DIRECTION_COLUMNS = {"team": "object", "direction": "object"} | _BREAKDOWN_COUNTS
CONNECTION_COLUMNS = {"team": "object", "thrower": "object", "receiver": "object"} | _BREAKDOWN_COUNTS
_TIMELINE_COLUMNS = {
    "goal": "int64",
    "event": "int64",
    "when": "datetime64[ns]",
    "elapsed": "float64",
    "point": "int64",
    "team": "object",
    "assist": "object",
    "scorer": "object",
    "hockey_assist": "object",
    "hold": "boolean",
}


class GameStats(pydantic.BaseModel):
    """Stats for one game (or the part of it played so far), as pandas DataFrames.

    Raw tables have one row per event of one type, indexed by the event's position in the stream: `throws`, `defenses`,
    `substitutions`, `infractions`. Each row carries its `point` and `possession` numbers and a `provisional` flag. Derived tables
    aggregate them: `possessions`, `points`, `team_box`, `player_box`, `throw_types` and `directions` (outcomes per team and throw
    type or direction), `connections` (thrower -> receiver), and `score_timeline` (one row per goal with the running score).
    Unknown players (None) are left out of the player tables (`player_box`, `connections`) but counted in the team tables.
    Events whose team is unknown (None in a table) and can't be inferred are left out of every per-team table.
    A derived row is flagged `provisional` when a provisional event changes it (or makes it).
    """

    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)

    teams: list[str] = pydantic.Field(..., description="Team labels in table order: the given teams' first names, then any other team named by an event.")
    score: dict[str, int] = pydantic.Field(..., description="Goals per team, in team order.")
    start: datetime.datetime | None = pydantic.Field(..., description="Time that `elapsed` counts from (naive): the stream's game start, else its first event.")
    provisional_from: int | None = pydantic.Field(None, description="Events from this index on are flagged provisional.")

    throws: pd.DataFrame
    defenses: pd.DataFrame
    substitutions: pd.DataFrame
    infractions: pd.DataFrame
    possessions: pd.DataFrame
    points: pd.DataFrame
    team_box: pd.DataFrame
    player_box: pd.DataFrame
    throw_types: pd.DataFrame
    directions: pd.DataFrame
    connections: pd.DataFrame
    score_timeline: pd.DataFrame

    RAW_TABLES: ClassVar[tuple[str, ...]] = ("throws", "defenses", "substitutions", "infractions")
    DERIVED_TABLES: ClassVar[tuple[str, ...]] = ("team_box", "player_box", "points", "possessions", "score_timeline", "throw_types", "directions", "connections")

    def tables(self, names: list[str] | tuple[str, ...] | None = None) -> dict[str, pd.DataFrame]:
        """The named tables (default: all derived ones, then the raw ones), by name."""
        return {name: getattr(self, name) for name in names or self.DERIVED_TABLES + self.RAW_TABLES}

    def summary(self) -> str:
        """One line, e.g. "white 14, black 9 (point 24 in play)"."""
        text = ", ".join(f"{team} {goals}" for team, goals in self.score.items())
        text = text or ("no team known yet" if any(len(getattr(self, name)) for name in self.RAW_TABLES) else "no events yet")
        notes = []
        points, goals = self.points, self.score_timeline
        if len(points) and points["throws"].iloc[-1] and not (len(goals) and goals["point"].iloc[-1] == points.index[-1]):
            notes.append(f"point {points.index[-1]} in play")
        if self.provisional_from is not None and (count := sum(int(getattr(self, name)["provisional"].sum()) for name in self.RAW_TABLES)):
            notes.append(f"{count} provisional event{'s' * (count != 1)}")
        return text + (f" ({'; '.join(notes)})" if notes else "")

    def connection_matrix(self, team: str, value: str = "throws") -> pd.DataFrame:
        """`connections` of one team as a thrower x receiver matrix of `value` ("throws", "completions", "goals", "completion_pct")."""
        rows = self.connections.xs(team, level="team") if team in self.connections.index.get_level_values("team") else self.connections.iloc[:0].droplevel("team")
        matrix = rows[value].unstack("receiver")
        return matrix if value == "completion_pct" else matrix.fillna(0).astype("int64")


class _TeamLabels:
    """Maps the team names events use ("dark", "black") to one label per team: the first of the team's names. An empty name
    (the event extractor's "don't know") maps to None."""

    def __init__(self, teams: list[yus.Team] | None):
        self.order: list[str] = []
        self._labels: dict[str, str] = {}
        self._seen: dict[str, str | None] = {}
        for i, team in enumerate(teams or []):
            label = team.names[0] if team.names else f"team {i + 1}"
            self.order.append(label)
            for name in team.names:
                if key := normalize(name):
                    self._labels.setdefault(key, label)

    def __call__(self, name: str | None) -> str | None:
        if name is None:
            return None
        if name not in self._seen:
            key = normalize(name)
            label = self._seen[name] = self._labels.get(key, name) if key else None
            if label is not None and label not in self.order:
                self.order.append(label)
        return self._seen[name]

    def other(self) -> dict[str, str]:
        """Each team's opponent, when there are exactly two teams."""
        return dict(zip(self.order, reversed(self.order))) if len(self.order) == 2 else {}


def compute_stats(stream: yus.EventStream, teams: list[yus.Team] | None = None, provisional_from: int | None = None) -> GameStats:
    """Stats for a resolved event stream (players already mapped by PlayerResolver), in stream order.

    `teams` (optional) merges the names events use for one team ("dark", "black") under the team's first name, and orders the
    teams (teams without events still get a row). With `provisional_from`, events from that index on are included but flagged
    `provisional`, as are the derived rows they count toward, so that a UI can style them.
    """
    labels = _TeamLabels(teams)
    events = stream.events
    game_start = [stream.game.when] if stream.game is not None else []
    clock = _naive_clock(game_start + [event.when for event in events])
    start = clock(game_start[0]) if game_start else (clock(events[0].when) if events else None)
    firm = len(events) if provisional_from is None else max(provisional_from, 0)

    throws, defenses, substitutions, infractions = _number_events(events, labels, clock, start, firm)
    possessions = _possessions(throws, defenses)
    points = _points(sorted(throws + defenses + substitutions + infractions, key=lambda row: row["event"]), start)
    team_box = _team_box(labels.order, throws, defenses, possessions, points)
    player_box = _player_box(labels.order, throws, defenses)
    timeline_columns = _TIMELINE_COLUMNS | {SCORE_PREFIX + team: "int64" for team in labels.order} | {"provisional": "bool"}

    return GameStats(
        teams=list(labels.order),
        score={team: row["goals"] for team, row in zip(labels.order, team_box)},
        start=start,
        provisional_from=provisional_from,
        throws=_frame(throws, THROW_COLUMNS, "event"),
        defenses=_frame(defenses, DEFENSE_COLUMNS, "event"),
        substitutions=_frame(substitutions, SUBSTITUTION_COLUMNS, "event"),
        infractions=_frame(infractions, INFRACTION_COLUMNS, "event"),
        possessions=_frame(possessions, POSSESSION_COLUMNS, "possession"),
        points=_frame(points, POINT_COLUMNS, "point"),
        team_box=_frame(team_box, TEAM_COLUMNS, "team"),
        player_box=_frame(player_box, PLAYER_COLUMNS, ["team", "player"]),
        throw_types=_frame(_breakdown(labels.order, throws, "type", THROW_TYPES), THROW_TYPE_COLUMNS, ["team", "type"]),
        directions=_frame(_breakdown(labels.order, throws, "direction", DIRECTIONS), DIRECTION_COLUMNS, ["team", "direction"]),
        connections=_frame(_connections(labels.order, throws), CONNECTION_COLUMNS, ["team", "thrower", "receiver"]),
        score_timeline=_frame(_score_timeline(labels.order, throws, points), timeline_columns, "goal"),
    )


def _naive_clock(times: list[datetime.datetime]) -> Callable[[datetime.datetime], datetime.datetime]:
    """A function giving the naive wall-clock time of each of a stream's `times`, so that pandas can hold and subtract them. Naive
    times stay as they are. Times with a UTC offset go to the zone of the first time whose offset isn't UTC (the commentator's
    local time, which naive times are taken to be in), else to this system's local time (like `transcribe.local_naive`)."""
    if all(when.utcoffset() is None for when in times):
        return _same
    zone = next((when.tzinfo for when in times if when.utcoffset() not in (None, datetime.timedelta(0))), None)
    return lambda when: when.astimezone(zone).replace(tzinfo=None) if when.utcoffset() is not None else when.replace(tzinfo=None)


def _same(when: datetime.datetime) -> datetime.datetime:
    return when


def _number_events(
    events: list[yus.Event], labels: _TeamLabels, clock: Callable[[datetime.datetime], datetime.datetime], start: datetime.datetime | None, firm: int
) -> tuple[list[Row], list[Row], list[Row], list[Row]]:
    """One row per Ultimate event, split by type, each with its point and possession number. A possession ends with a goal, an
    incomplete throw, or a throw by the other team; a point ends with a goal. A non-throw event belongs to the possession it
    happened in (a D to the possession it ended); after a goal, to the next point and to no possession. An event without a team
    gets the one that had the disc (a throw, see `_throw_teams`) or the one defending (a D), when that can be told."""
    found = [(i, event, labels(event.team)) for i, event in enumerate(events) if isinstance(event, ultimate.UltimateEvent)]
    other = labels.other()
    throw_teams = iter(_throw_teams([(event, team) for _, event, team in found if isinstance(event, ultimate.Throw)], other))
    throws: list[Row] = []
    defenses: list[Row] = []
    substitutions: list[Row] = []
    infractions: list[Row] = []
    point, possession, last = 1, 0, None
    for i, event, team in found:
        when = clock(event.when)
        row: Row = {
            "event": i,
            "when": when,
            "elapsed": (when - start).total_seconds() if start is not None else 0.0,
            "team": team,
            "player": event.player,
            "provisional": i >= firm,
        }
        after_goal = last is not None and last["scored"]
        if isinstance(event, ultimate.Throw):
            row["team"] = next(throw_teams)
            point += after_goal
            new_possession = last is None or after_goal or not last["completed"] or last["team"] != row["team"]
            possession += new_possession
            row |= {
                "receiver": event.receiver,
                "type": str(event.type) if event.type is not None else None,
                "direction": str(event.direction) if event.direction is not None else None,
                "completed": event.completed,
                "scored": event.scored,
                "hit_wall": getattr(event, "hit_wall", False),
                "hit_net": getattr(event, "hit_net", False),
                "point": point,
                "possession": possession,
                "hockey_assist": last["player"] if last is not None and event.scored and not new_possession else None,  # for the box and timeline only
            }
            throws.append(row)
            last = row
            continue
        row["point"] = point + after_goal
        if isinstance(event, ultimate.Defense):
            if team is None and last is not None:  # the defending team: the scorers after a goal, else the other team
                row["team"] = last["team"] if after_goal else other.get(last["team"])
            row |= {"intercepted": event.intercepted, "possession": None if last is None or after_goal else possession}
            defenses.append(row)
        elif isinstance(event, ultimate.Substitution):
            row["sub_type"] = str(event.sub_type)
            substitutions.append(row)
        elif isinstance(event, ultimate.Infraction):
            infractions.append(row)
    return throws, defenses, substitutions, infractions


def _throw_teams(throws: list[tuple[ultimate.Throw, str | None]], other: dict[str, str]) -> list[str | None]:
    """The team of each (throw, team named) pair: the one named, else the team that had the disc after the previous throw (the
    same team after a completion; after a turnover or a goal, the other team), else before the next throw; None if unknown."""
    teams = [team for _, team in throws]
    if None not in teams:
        return teams
    for k in range(1, len(teams)):
        if teams[k] is None and (previous := teams[k - 1]) is not None:
            teams[k] = previous if _keeps_disc(throws[k - 1][0]) else other.get(previous)
    for k in range(len(teams) - 2, -1, -1):
        if teams[k] is None and (following := teams[k + 1]) is not None:
            teams[k] = following if _keeps_disc(throws[k][0]) else other.get(following)
    return teams


def _keeps_disc(throw: ultimate.Throw) -> bool:
    return throw.completed and not throw.scored


def _possessions(throws: list[Row], defenses: list[Row]) -> list[Row]:
    """One row per possession. Outcome: "goal", "turnover", "in play" (the last possession, still going), or "unknown" (the other
    team threw next without a recorded turnover; provisional if that throw is)."""
    found: dict[int, Row] = {}
    for throw in throws:
        row = found.get(throw["possession"])
        if row is None:
            row = found[throw["possession"]] = {
                "possession": throw["possession"],
                "point": throw["point"],
                "team": throw["team"],
                "start": throw["when"],
                "throws": 0,
                "completions": 0,
                "provisional": False,
                "first_provisional": throw["provisional"],
            }
        row["end"] = throw["when"]
        row["throws"] += 1
        row["completions"] += throw["completed"]
        row["outcome"] = "goal" if throw["scored"] else "turnover" if not throw["completed"] else None
        row["provisional"] |= throw["provisional"]
    for defense in defenses:
        if (row := found.get(defense["possession"])) is not None:
            row["end"] = max(row["end"], defense["when"])
            row["provisional"] |= defense["provisional"]
    rows = list(found.values())
    for row, following in zip(rows, rows[1:] + [None]):
        if row["outcome"] is None:
            row["outcome"] = "in play" if following is None else "unknown"
            row["provisional"] |= following is not None and following["first_provisional"]
        row["duration_s"] = (row["end"] - row["start"]).total_seconds()
    return rows


def _points(rows: list[Row], start: datetime.datetime | None) -> list[Row]:
    """One row per point, from all event rows in stream order. A point starts when the one before it ended (the first point, at
    `start`) and ends with its goal (or its latest event, while in play). Its `o_team` is the team of its first throw; it is
    `suspect` when that team scored the point before, which indoor rules forbid (the team scored on picks up)."""
    found: dict[int, Row] = {}
    possessions: dict[int, set[int]] = {}
    for event in rows:
        row = found.get(event["point"])
        if row is None:
            row = found[event["point"]] = {
                "point": event["point"],
                "o_team": None,
                "throws": 0,
                "turnovers": 0,
                "scored_by": None,
                "assist": None,
                "scorer": None,
                "hold": None,
                "provisional": False,
                "o_provisional": False,  # whether the throw that set o_team is provisional
            }
            possessions[event["point"]] = set()
        row["end"] = event["when"]
        row["provisional"] |= event["provisional"]
        if "completed" not in event:
            continue
        if not row["throws"]:
            row["o_team"], row["o_provisional"] = event["team"], event["provisional"]
        row["throws"] += 1
        row["turnovers"] += not event["completed"]
        possessions[event["point"]].add(event["possession"])
        if event["scored"]:
            hold = event["team"] == row["o_team"] if event["team"] is not None and row["o_team"] is not None else None
            row |= {"scored_by": event["team"], "assist": event["player"], "scorer": event["receiver"], "hold": hold}
    previous_end, previous_scorer = start, None
    for row in found.values():
        row["start"] = previous_end if previous_end is not None else row["end"]
        row["duration_s"] = (row["end"] - row["start"]).total_seconds()
        row["possessions"] = len(possessions[row["point"]])
        row["suspect"] = row["o_team"] is not None and row["o_team"] == previous_scorer
        previous_end, previous_scorer = row["end"], row["scored_by"]
    return list(found.values())


def _team_box(teams: list[str], throws: list[Row], defenses: list[Row], possessions: list[Row], points: list[Row]) -> list[Row]:
    box: dict[str, Row] = {team: {"team": team, "provisional": False} | dict.fromkeys(_TEAM_COUNTS, 0) for team in teams}
    for throw in throws:
        if (row := box.get(throw["team"])) is None:
            continue
        huck = throw["direction"] == ultimate.ThrowDirection.HUCK
        row["throws"] += 1
        row["completions"] += throw["completed"]
        row["turnovers"] += not throw["completed"]
        row["goals"] += throw["scored"]
        row["hucks"] += huck
        row["huck_completions"] += huck and throw["completed"]
        row["wall_throws"] += throw["hit_wall"]
        row["net_throws"] += throw["hit_net"]
        row["provisional"] |= throw["provisional"]
    for defense in defenses:
        if (row := box.get(defense["team"])) is None:
            continue
        row["ds"] += 1
        row["interceptions"] += defense["intercepted"]
        row["provisional"] |= defense["provisional"]
    for possession in possessions:
        if (row := box.get(possession["team"])) is not None:
            row["possessions"] += 1
    _count_points(box, points)
    for row in box.values():
        row["goals_per_possession"] = _ratio(row["goals"], row["possessions"], 2)
        row["completion_pct"] = _ratio(row["completions"], row["throws"])
        row["huck_completion_pct"] = _ratio(row["huck_completions"], row["hucks"])
    return list(box.values())


def _count_points(box: dict[str, Row], points: list[Row]) -> None:
    """Add o_points, d_points, holds and breaks to the team box."""
    for point in points:
        if point["o_team"] is None:
            continue
        for team, row in box.items():  # every team's o_points or d_points count depends on the point's first throw
            row["o_points" if team == point["o_team"] else "d_points"] += 1
            row["provisional"] |= point["o_provisional"]
        if point["hold"] is not None:
            box[point["scored_by"]]["holds" if point["hold"] else "breaks"] += 1


def _player_box(teams: list[str], throws: list[Row], defenses: list[Row]) -> list[Row]:
    box: dict[tuple[str, str], Row] = {}

    def credit(team: str | None, player: str | None, provisional: bool, *counts: str) -> None:
        if player is None or team is None:
            return
        row = box.get((team, player))
        if row is None:
            row = box[(team, player)] = {"team": team, "player": player, "provisional": False} | dict.fromkeys(_PLAYER_COUNTS, 0)
        for count in counts:
            row[count] += 1
        row["provisional"] |= provisional

    for throw in throws:
        team, provisional, completed = throw["team"], throw["provisional"], throw["completed"]
        huck = ["hucks", *(["huck_completions"] if completed else [])] if throw["direction"] == ultimate.ThrowDirection.HUCK else []
        credit(team, throw["player"], provisional, "throws", "completions" if completed else "turnovers", *(["assists"] if throw["scored"] else []), *huck)
        credit(team, throw["receiver"], provisional, "targets", "catches" if completed else "drops_or_misses", *(["goals"] if throw["scored"] else []))
        credit(team, throw["hockey_assist"], provisional, "hockey_assists")
    for defense in defenses:
        credit(defense["team"], defense["player"], defense["provisional"], "ds", *(["interceptions"] if defense["intercepted"] else []))
    order = {team: i for i, team in enumerate(teams)}
    rows = sorted(box.values(), key=lambda row: (order[row["team"]], -(row["throws"] + row["targets"] + row["ds"]), row["player"]))
    for row in rows:
        row["completion_pct"] = _ratio(row["completions"], row["throws"])
    return rows


def _breakdown(teams: list[str], throws: list[Row], field: str, order: list[str]) -> list[Row]:
    """Throws, completions, goals and turnovers per team and value of `field` (throw type or direction)."""
    found: dict[tuple[str, str], Row] = {}
    for throw in throws:
        if throw["team"] is None:
            continue
        key = (throw["team"], throw[field] or UNKNOWN)
        _count_throw(found.setdefault(key, {"team": key[0], field: key[1]}), throw)
    team_rank = {team: i for i, team in enumerate(teams)}
    value_rank = {value: i for i, value in enumerate(order)}
    return _with_pct(sorted(found.values(), key=lambda row: (team_rank[row["team"]], value_rank.get(row[field], len(order)), row[field])))


def _connections(teams: list[str], throws: list[Row]) -> list[Row]:
    """Throws from each known thrower to each known receiver, per team."""
    found: dict[tuple[str, str, str], Row] = {}
    for throw in throws:
        if throw["team"] is not None and throw["player"] is not None and throw["receiver"] is not None:
            key = (throw["team"], throw["player"], throw["receiver"])
            _count_throw(found.setdefault(key, {"team": key[0], "thrower": key[1], "receiver": key[2]}), throw)
    rank = {team: i for i, team in enumerate(teams)}
    return _with_pct(sorted(found.values(), key=lambda row: (rank[row["team"]], -row["throws"], row["thrower"], row["receiver"])))


def _score_timeline(teams: list[str], throws: list[Row], points: list[Row]) -> list[Row]:
    """One row per goal, with each team's running score in its `SCORE_PREFIX + team` column. A goal by an unknown team (None)
    gets a row but no score."""
    score = {SCORE_PREFIX + team: 0 for team in teams}
    holds = {point["point"]: point["hold"] for point in points}
    rows: list[Row] = []
    for throw in throws:
        if throw["scored"]:
            if throw["team"] is not None:
                score[SCORE_PREFIX + throw["team"]] += 1
            rows.append(
                {
                    "goal": len(rows) + 1,
                    "event": throw["event"],
                    "when": throw["when"],
                    "elapsed": throw["elapsed"],
                    "point": throw["point"],
                    "team": throw["team"],
                    "assist": throw["player"],
                    "scorer": throw["receiver"],
                    "hockey_assist": throw["hockey_assist"],
                    "hold": holds[throw["point"]],
                    "provisional": throw["provisional"],
                }
                | score
            )
    return rows


def _count_throw(row: Row, throw: Row) -> None:
    for count in ("throws", "completions", "goals", "turnovers"):
        row.setdefault(count, 0)
    row["provisional"] = row.get("provisional", False) or throw["provisional"]
    row["throws"] += 1
    row["completions"] += throw["completed"]
    row["goals"] += throw["scored"]
    row["turnovers"] += not throw["completed"]


def _with_pct(rows: list[Row]) -> list[Row]:
    for row in rows:
        row["completion_pct"] = _ratio(row["completions"], row["throws"])
    return rows


def _ratio(part: int, whole: int, digits: int | None = None) -> float:
    """100 * part / whole rounded to 0.1 (or part / whole rounded to `digits`), NaN when whole is 0."""
    if not whole:
        return math.nan
    return round(part / whole, digits) if digits is not None else round(100 * part / whole, 1)


def _frame(rows: list[Row], columns: dict[str, str], index: str | list[str]) -> pd.DataFrame:
    """A DataFrame of `rows` with exactly `columns` (name -> dtype), indexed by `index`; typed columns even with no rows."""
    data = {name: pd.Series([row[name] for row in rows], dtype=dtype) for name, dtype in columns.items()}
    return pd.DataFrame(data).set_index(index)
