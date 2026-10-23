"""Who is on the field: each player's stints, points played, playing time and plus-minus, and each team's line combinations.

Only substitutions (and line-ups, which are substitutions on) say who is on the field, so only a team with at least one
substitution is tracked, from its first one on, and only the players substituted for it. (A throw's team follows possession, which
misses turnovers nobody said, so a throw alone does not make its thrower a player of that team.) Each player's state between two things said about them follows from both: "kaia
on" then "kaia off" means on in between; "kaia on" then a throw by kaia, on in between; "kaia off" then "kaia off" again, or
"kaia off" then a throw by kaia, means a substitution was missed in between, so unknown. Before the first thing said about a player
their state is unknown. After the last, the state of their last substitution stays (unless something said since disagrees); a
throw, catch or D only says they were on then. Substitutions of one team said within `BURST` seconds of each other, with no goal
between, count as made together, at the first one's time ("26 off. glasses on." is one swap). When `line_size` of a team's players
are known to be on, everyone else on it is off and the line is known; when more than `line_size` would be on, a substitution was
missed, and the on-field state of all of the team's players is unknown until that clears up. Nothing is guessed: unknown time and
goals are counted as unknown.
"""

from __future__ import annotations

import bisect
import collections
import dataclasses
import datetime
from typing import Any

ON, OFF, UNKNOWN = "on", "off", "unknown"
BURST = 5.0
"""Seconds between substitutions of one team said as one swap."""
UNKNOWN_LINE = "unknown"
"""`lines` row label for the time a team's line is not known exactly."""

Row = dict[str, Any]


@dataclasses.dataclass(slots=True)
class _Seen:
    when: datetime.datetime
    before: str  # the player's state just before
    after: str  # and just after
    provisional: bool
    point: int | None = None  # for a play (a throw, catch or D): the point it was made in; None for a substitution


class _Player:
    """One player's states over time, from what was said about them."""

    def __init__(self, seen: list[_Seen], start: datetime.datetime, end: datetime.datetime):
        seen = sorted(seen, key=lambda s: s.when)
        self.starts = [start]
        self.states = [UNKNOWN]
        self.said: dict[datetime.datetime, str] = {}  # the state at each moment something was said: a throw by kaia, kaia was on
        subbed = False  # the things said that agree up to this one include a substitution
        for k, item in enumerate(seen):
            subbed = item.point is None or (subbed and seen[k - 1].after == item.before)
            following = seen[k + 1] if k + 1 < len(seen) else None
            if following is None:
                state = item.after if subbed else UNKNOWN
            else:
                state = item.after if following.before == item.after else UNKNOWN
            when = min(max(item.when, start), end)
            self.said[when] = item.after
            if when == self.starts[-1]:
                self.states[-1] = state
            else:
                self.starts.append(when)
                self.states.append(state)

    def at(self, when: datetime.datetime, moment: bool = False) -> str:
        """The state from `when` on (until the next change); with `moment`, at `when` itself, as said then if anything was."""
        found = self.said.get(when) if moment else None
        return found if found is not None else self.states[bisect.bisect_right(self.starts, when) - 1]


def on_field(
    throws: list[Row], defenses: list[Row], substitutions: list[Row], points: list[Row], start: datetime.datetime | None, line_size: int | None
) -> tuple[list[Row], list[Row], list[Row]]:
    """(on_field, lines, shifts) rows for the teams with substitutions; see the module docstring and docs/stats.md."""
    if start is None or not substitutions:
        return [], [], []
    rows = throws + defenses + substitutions
    end = max(row["when"] for row in rows)
    provisional = any(row["provisional"] for row in rows)
    seen = _observations(throws, defenses, substitutions, sorted(throw["when"] for throw in throws if throw["scored"]))
    point_ends = [point["end"] for point in points]
    goals = [(throw["when"], throw["team"]) for throw in throws if throw["scored"] and throw["team"] is not None]
    on_rows: list[Row] = []
    line_rows: list[Row] = []
    shift_rows: list[Row] = []
    for team, players in seen.items():
        moved = any(s.provisional for found in players.values() for s in found)
        tracker = _Team(team, {name: _Player(found, start, end) for name, found in players.items()}, line_size)
        on, lines, shifts = tracker.tally(start, end, goals, point_ends, players)
        for row in on:
            row["provisional"] = moved or (provisional and tracker.state(row["player"], end) != OFF)
        current = tracker.line(end)
        for row in lines:
            row["provisional"] = moved or (provisional and row["line"] == current)
        for row in shifts:
            row["provisional"] = moved or (provisional and row["end"] == end)
        on_rows += on
        line_rows += lines
        shift_rows += sorted(shifts, key=lambda row: (row["player"], row["start"]))
    for k, row in enumerate(shift_rows, start=1):
        row["shift"] = k
    return on_rows, line_rows, shift_rows


def _observations(throws: list[Row], defenses: list[Row], substitutions: list[Row], goals: list[datetime.datetime]) -> dict[str, dict[str, list[_Seen]]]:
    """What was said about each player of each team with substitutions, from its first substitution on: team -> player -> seen."""
    first: dict[str, datetime.datetime] = {}
    found: dict[str, dict[str, list[_Seen]]] = {}
    last: dict[str, datetime.datetime] = {}
    for row in sorted((row for row in substitutions if row["team"] is not None and row["player"] is not None), key=lambda row: row["when"]):
        team, when = row["team"], row["when"]
        if team not in first:
            first[team], found[team] = when, collections.defaultdict(list)
        elif (when - last[team]).total_seconds() <= BURST and bisect.bisect_right(goals, last[team]) == bisect.bisect_right(goals, when):
            when = found[team]["\0burst"][0].when  # one swap: made when its first substitution was said
        if when == row["when"]:
            found[team]["\0burst"] = [_Seen(when, OFF, OFF, False)]
        last[team] = row["when"]
        on = row["sub_type"] == "sub_on"
        found[team][row["player"]].append(_Seen(when, OFF if on else ON, ON if on else OFF, row["provisional"]))
    for players in found.values():
        players.pop("\0burst", None)
    plays = [(throw, name) for throw in throws for name in (throw["player"], throw["receiver"])] + [(defense, defense["player"]) for defense in defenses]
    for row, name in plays:
        if name in found.get(row["team"], {}) and row["when"] >= first[row["team"]]:  # someone substituted for the team: on then
            found[row["team"]][name].append(_Seen(row["when"], ON, ON, row["provisional"], row["point"]))
    return {team: dict(players) for team, players in found.items()}


class _Team:
    def __init__(self, name: str, players: dict[str, _Player], line_size: int | None):
        self.name, self.players, self.line_size = name, players, line_size

    def states(self, when: datetime.datetime, moment: bool = False) -> dict[str, str]:
        """Each player's state from `when` on (with `moment`: at `when`, for a goal), with what the line size tells: the rest are
        off once enough are on, and nobody's state is known when too many would be on."""
        states = {name: player.at(when, moment) for name, player in self.players.items()}
        if self.line_size is not None:
            count = sum(state == ON for state in states.values())
            if count > self.line_size:
                states = {name: OFF if state == OFF else UNKNOWN for name, state in states.items()}
            elif count == self.line_size:
                states = {name: OFF if state == UNKNOWN else state for name, state in states.items()}
        return states

    def state(self, player: str, when: datetime.datetime) -> str:
        return self.states(when)[player]

    def line(self, when: datetime.datetime) -> str:
        return _line(self.states(when), self.line_size)

    def tally(
        self, start: datetime.datetime, end: datetime.datetime, goals: list[tuple[datetime.datetime, str]], point_ends: list[datetime.datetime], seen: dict[str, list[_Seen]]
    ) -> tuple[list[Row], list[Row], list[Row]]:
        cuts = sorted({start, end, *(when for player in self.players.values() for when in player.starts), *(when for when, _ in goals if start <= when <= end)})
        totals = {name: {"points": set(), ON: 0.0, UNKNOWN: 0.0, "for": 0, "against": 0, "goals_unknown": 0} for name in self.players}
        lines: dict[str, Row] = {}
        shifts: list[Row] = []
        open_shift: dict[str, Row] = {}
        for a, b in zip(cuts, cuts[1:] + [None]):
            states = self.states(a)
            seconds = (b - a).total_seconds() if b is not None else 0.0
            point = bisect.bisect_right(point_ends, a) + 1 if point_ends else 1
            point = min(point, len(point_ends)) if point_ends else 1
            label = _line(states, self.line_size)
            line = lines.setdefault(label, _line_row(self.name, label))
            line["time_s"] += seconds
            if seconds:
                line["points"].add(point)
            for name, state in states.items():
                totals[name][state] = totals[name].get(state, 0.0) + seconds
                if state == ON and seconds:
                    totals[name]["points"].add(point)
                shift = open_shift.get(name)
                if shift is None or shift["state"] != state:
                    shift = open_shift[name] = {"team": self.name, "player": name, "state": state, "start": a, "end": a}
                    shifts.append(shift)
                shift["end"] = b if b is not None else a
        for when, scorer in goals:
            if not start <= when <= end:
                continue
            states = self.states(when, moment=True)
            label = _line(states, self.line_size)
            line = lines.setdefault(label, _line_row(self.name, label))
            line["goals_for" if scorer == self.name else "goals_against"] += 1
            for name, state in states.items():
                key = "goals_unknown" if state == UNKNOWN else ("for" if scorer == self.name else "against") if state == ON else None
                if key is not None:
                    totals[name][key] += 1
        return self._players(totals, seen), self._lines(lines), [s | {"duration_s": (s["end"] - s["start"]).total_seconds()} for s in shifts if s["end"] > s["start"]]

    def _players(self, totals: dict[str, dict[str, Any]], seen: dict[str, list[_Seen]]) -> list[Row]:
        rows = []
        for name, total in totals.items():
            played = total["points"] | {s.point for s in seen[name] if s.point is not None}  # a throw, catch or D: on in that point
            rows.append(
                {
                    "team": self.name,
                    "player": name,
                    "points_played": len(played),
                    "time_on_s": round(total[ON], 1),
                    "time_unknown_s": round(total[UNKNOWN], 1),
                    "goals_for": total["for"],
                    "goals_against": total["against"],
                    "plus_minus": total["for"] - total["against"],
                    "goals_unknown": total["goals_unknown"],
                }
            )
        return rows

    def _lines(self, lines: dict[str, Row]) -> list[Row]:
        rows = []
        for row in lines.values():
            if not row["time_s"] and not row["goals_for"] + row["goals_against"]:
                continue
            rows.append(row | {"points": len(row["points"]), "time_s": round(row["time_s"], 1), "plus_minus": row["goals_for"] - row["goals_against"]})
        return rows


def _line(states: dict[str, str], line_size: int | None) -> str:
    """The team's line as one label (its players, sorted), or UNKNOWN_LINE."""
    on = sorted(name for name, state in states.items() if state == ON)
    return ", ".join(on) if line_size is not None and len(on) == line_size else UNKNOWN_LINE


def _line_row(team: str, line: str) -> Row:
    return {"team": team, "line": line, "points": set(), "time_s": 0.0, "goals_for": 0, "goals_against": 0}
