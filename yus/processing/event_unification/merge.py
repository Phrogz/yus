"""Merge several commentators' resolved event streams of one game into one official event stream.

Where this fits: after player resolution (each stream names roster players, or this game's labels for unknown players) and
before stats. Each commentator's clock may be off, each misses some events, and they disagree on details. Merging:
  1. estimates each stream's clock offset from the first stream, from the time differences of events of the same type and team,
     then refines it from the events it pairs;
  2. pairs events that describe the same action with a monotone alignment (every stream keeps its order): events of the same
     type and team within `tolerance` seconds, scored by closeness in time and agreement of names, throw type and outcome;
  3. merges the fields of paired events: a known value beats an unknown one, a roster player beats a description label, then
     the commentator focusing on the event's team wins, then the majority, then the earliest stream;
  4. repairs contradictions with the game's grammar: possession continues iff a throw was completed and not scored, and a
     Defense follows an incomplete throw by the other team.

It is a pure function of its inputs and takes a few milliseconds for a whole game, so live use re-merges the streams so far
whenever an event arrives. Merged events well before the latest input event (`settle` seconds, plus what pairing, reordering
and the next throw look at) are settled: they come out the same however many events follow, provided events arrive in order
and no stream lags another by more than `settle`. A stream whose offset is estimated, not given, can still move, so the events
within its reach are not settled (`LiveMerger` keeps each offset once it is well supported). Newer events are provisional.
"""

from __future__ import annotations

import bisect
import collections
import dataclasses
import datetime
import functools
import itertools
import math
import statistics
from collections.abc import Callable, Sequence
from typing import Literal

import pydantic

import yus
from yus.processing.event_unification import players
from yus.sports import ultimate

Value = str | bool | None
Rule = Literal["roster", "focus", "majority", "earliest", "grammar"]

NAME_FIELDS = ("player", "receiver")
normalize = functools.lru_cache(maxsize=4096)(players.normalize)
OFFSET_BIN = 0.25  # seconds per bin of the offset histogram
TIME_WEIGHT, TIME_ZERO = 2.0, 0.6  # pair score for events at the same time; fraction of tolerance at which time alone scores 0


class Conflict(pydantic.BaseModel):
    """A field of a merged event that its inputs disagreed on (or that contradicted the game), and how it was settled."""

    event: int = pydantic.Field(..., description="Index of the merged event in MergeResult.stream.events.")
    field: str = pydantic.Field(..., description='The field, e.g. "receiver" or "completed".')
    values: list[Value] = pydantic.Field(..., description="Each input stream's value (None where the stream has no event here).")
    chosen: Value = pydantic.Field(..., description="The merged value.")
    rule: Rule = pydantic.Field(..., description="What settled it: roster name over description, team focus, majority, earliest stream, or game grammar.")


class NameLink(pydantic.BaseModel):
    """A suggestion that a name in one stream means the same player as a name the merged stream uses, e.g. B's "specs" is
    "glasses": both name the same player in paired events. Add it to the game's descriptions to apply it."""

    stream: int
    team: str
    name: str
    same_as: str
    support: int = pydantic.Field(..., description="How many paired events agree.")


class MergeResult(pydantic.BaseModel):
    """The official stream merged from several streams, and how it was made."""

    stream: yus.EventStream
    offsets: list[float] = pydantic.Field(..., description="Seconds added to each input stream's times to align it to the first stream.")
    pairs: list[list[int | None]] = pydantic.Field(..., description="For each merged event, the index of the event it came from in each input stream, or None.")
    conflicts: list[Conflict] = []
    links: list[NameLink] = []
    settled: int = pydantic.Field(0, description="The first `settled` merged events are final; later ones may change as events arrive.")

    @property
    def provisional(self) -> list[bool]:
        """For each merged event, whether it may still change."""
        return [i >= self.settled for i in range(len(self.stream.events))]


@dataclasses.dataclass(eq=False)
class _Item:
    """One input event, with its stream, position, comparable type and team, and its time in seconds on the aligned clock."""

    stream: int
    index: int
    event: yus.Event
    kind: str
    team: str | None
    raw: float
    t: float = 0.0


@dataclasses.dataclass(eq=False)
class _Group:
    """Input events that describe one action, and their merged event (`rep`) so far."""

    items: list[_Item]
    rep: yus.Event
    disputes: dict[str, Rule]
    t: float


class _Context:
    """What merging needs to know about the game: team names, rosters, each stream's team focus, and how to compare times."""

    def __init__(self, teams: Sequence[yus.Team] | None, focus: Sequence[str | None] | None, tolerance: float):
        self.teams = list(teams or [])
        self.tolerance = tolerance
        self.team_index = {normalize(name): i for i, team in enumerate(self.teams) for name in team.names}
        self.rosters = [{normalize(player) for player in team.players} for team in self.teams]
        self.focus = [self.team_key(team) for team in focus or []]
        if self.teams and (unknown := [team for team, key in zip(focus or [], self.focus) if key is not None and not key.startswith("#")]):
            raise ValueError(f"focus names no team of the game: {unknown}; teams are {[team.names for team in self.teams]}")
        self.clock: Callable[[datetime.datetime], datetime.datetime] = _same_time

    def team_key(self, team: str | None) -> str | None:
        """Comparable team: "#<index>" for a known team, else the normalized name."""
        if team is None:
            return None
        index = self.team_index.get(normalize(team))
        return normalize(team) if index is None else f"#{index}"

    def team_name(self, key: str | None, spoken: str) -> str:
        """The name merged events use for a team: its official (first) name when known, else as spoken."""
        return self.teams[int(key[1:])].names[0] if key and key.startswith("#") else spoken

    def is_roster(self, team: str | None, name: str) -> bool:
        return bool(team and team.startswith("#")) and normalize(name) in self.rosters[int(team[1:])]

    def focuses(self, stream: int, team: str | None) -> bool:
        return stream < len(self.focus) and team is not None and self.focus[stream] == team


def merge_streams(
    streams: list[yus.EventStream],
    tolerance: float = 3.0,
    max_offset: float = 20.0,
    focus: list[str | None] | None = None,
    *,
    teams: list[yus.Team] | None = None,
    offsets: list[float | None] | None = None,
    settle: float = 20.0,
    repair: bool = True,
) -> MergeResult:
    """Merge several commentators' resolved event streams of one game into one official, time-ordered stream.

    Args:
        streams: Each commentator's events, players resolved (see PlayerResolver). The first stream is the clock reference.
        tolerance: Most seconds apart (after alignment) two events can be and still describe the same action.
        max_offset: Largest clock offset, in seconds, to look for between a stream and the first.
        focus: Each stream's commentator's team focus (any name of the team), or None for one who covers the whole game.
            In a conflict, the commentator focusing on the event's team wins.
        teams: The game's teams. They identify teams named differently ("white", "light") and roster players (which beat
            description labels); merged events then name teams by their official (first) names. Without them, team names must match.
        offsets: Known clock offsets, per stream (the first is ignored: it is the reference); None, or a None entry, estimates it.
        settle: Seconds before the latest input event that every event still to come is assumed to follow: the most any stream
            lags another. Merged events before that (and before what pairing, reordering and repair look at) are final.
        repair: Repair outcomes that contradict the game's grammar.

    Times may be naive or carry a UTC offset; when streams mix them, merged times are naive (see `_clock`).
    """
    ctx = _Context(teams, focus, tolerance)
    items = _items(streams, ctx)
    groups = [_group([item], ctx) for item in items[0]] if streams else []
    found = [0.0] * len(streams)
    estimated = [False] * len(streams)
    for k in range(1, len(streams)):
        known = offsets[k] if offsets and k < len(offsets) else None
        found[k], matches = _place(groups, items[k], known, max_offset, ctx)
        groups = _interleave(groups, items[k], matches, ctx)
        estimated[k] = known is None
    return _finish(streams, groups, found, items, _stable_until(items, estimated, settle, max_offset, tolerance), repair, ctx)


class LiveMerger:
    """Merges the streams so far, again whenever an event arrives, so that settled events stay as they are.

    Each stream's clock offset is estimated until `lock_after` of its events have been paired, then kept for the events so
    far. When the events paired since put the offset `OFFSET_BIN` or more away, the new estimate applies to the stream's
    events still to come (`segments`); events already merged keep theirs. Events within reach of a stream whose offset is
    still estimated (including one that hasn't reported yet) are not settled.

    merger = LiveMerger(teams=game.teams, focus=["white", "black"])
    result = merger.merge(streams_so_far)   # again as events arrive; result.provisional marks events that may still change

    Pass every commentator's stream from the first call on, empty until it reports: a stream added later can unsettle events.
    """

    def __init__(self, *, lock_after: int = 10, **options):
        """`options` are merge_streams's: tolerance, max_offset, focus, teams, settle, repair."""
        self.options = options
        self.lock_after = lock_after
        self.segments: list[list[tuple[int, float]] | None] = [[(0, 0.0)]]  # per stream: (first event, offset from there on)

    @property
    def offsets(self) -> list[float | None]:
        """Each stream's offset for the events still to come; None while it is being estimated."""
        return [segments[-1][1] if segments else None for segments in self.segments]

    def merge(self, streams: list[yus.EventStream]) -> MergeResult:
        """Merge the streams so far (each a prefix of the stream it will be: events are only ever added at the end). The
        result's offsets are those of each stream's first events."""
        self.segments += [None] * (len(streams) - len(self.segments))
        shifted = [stream if not segments or len(segments) == 1 else _resegment(stream, segments) for stream, segments in zip(streams, self.segments)]
        result = merge_streams(shifted, offsets=[segments[0][1] if segments else None for segments in self.segments], **self.options)
        clock = _clock([event.when for stream in streams for event in stream.events])
        for k, segments in enumerate(self.segments[1 : len(streams)], 1):
            paired = [pair for pair in result.pairs if pair[k] is not None and sum(index is not None for index in pair) > 1]
            if segments is None:
                if len(paired) >= self.lock_after:
                    self.segments[k] = [(0, result.offsets[k])]
                continue
            estimate = statistics.median(self._gap(streams, result, pair, k, clock) for pair in paired)
            if abs(estimate - segments[-1][1]) >= OFFSET_BIN:
                segments.append((len(streams[k].events), estimate))
        return result

    def _gap(self, streams: list[yus.EventStream], result: MergeResult, pair: list[int | None], k: int, clock: Callable[[datetime.datetime], datetime.datetime]) -> float:
        """Seconds from stream k's event in a pair, as reported, to the mean aligned time of the other events in the pair."""
        times = {j: clock(streams[j].events[i].when) for j, i in enumerate(pair) if i is not None}
        offsets = {j: self._offset(j, i, result) for j, i in enumerate(pair) if i is not None and j != k}
        return statistics.fmean((times[j] - times[k]).total_seconds() + offset for j, offset in offsets.items())

    def _offset(self, stream: int, index: int, result: MergeResult) -> float:
        segments = self.segments[stream]
        return result.offsets[stream] if segments is None else next(offset for start, offset in reversed(segments) if start <= index)


def _resegment(stream: yus.EventStream, segments: list[tuple[int, float]]) -> yus.EventStream:
    """The stream with each event's time moved by its segment's offset less the first segment's, so that the first's applies to all."""
    base, found = segments[0][1], list(stream.events)
    for (start, offset), (end, _) in zip(segments[1:], [*segments[2:], (len(found), 0.0)]):
        shift = datetime.timedelta(seconds=offset - base)
        found[start:end] = [event.model_copy(update={"when": event.when + shift}) for event in found[start:end]]
    return yus.EventStream(game=stream.game, events=found)


def _items(streams: list[yus.EventStream], ctx: _Context) -> list[list[_Item]]:
    """Each stream's events in time order, timed in seconds since the earliest event."""
    times = [event.when for stream in streams for event in stream.events]
    if not times:
        return [[] for _ in streams]
    ctx.clock = _clock(times)
    epoch = min(map(ctx.clock, times))
    found = []
    for k, stream in enumerate(streams):
        order = sorted(range(len(stream.events)), key=lambda i: ctx.clock(stream.events[i].when))
        found.append([_item(k, i, stream.events[i], epoch, ctx) for i in order])
    return found


def _item(stream: int, index: int, event: yus.Event, epoch: datetime.datetime, ctx: _Context) -> _Item:
    raw = (ctx.clock(event.when) - epoch).total_seconds()
    return _Item(stream, index, event, _kind(type(event)), ctx.team_key(getattr(event, "team", None)), raw, raw)


def _clock(times: list[datetime.datetime]) -> Callable[[datetime.datetime], datetime.datetime]:
    """A function that makes the times comparable. Naive times stay as they are, and so do times with a UTC offset when all
    have one. When they are mixed, those with an offset become naive wall-clock times in the zone of the first one whose
    offset isn't UTC (the commentator's local time, which naive times are taken to be in), else in this system's local zone,
    as the stats do."""
    aware = [when.utcoffset() is not None for when in times]
    if all(aware) or not any(aware):
        return _same_time
    zone = next((when.tzinfo for when in times if when.utcoffset() not in (None, datetime.timedelta(0))), None)
    return lambda when: when if when.utcoffset() is None else when.astimezone(zone).replace(tzinfo=None)


def _same_time(when: datetime.datetime) -> datetime.datetime:
    return when


def _stable_until(items: list[list[_Item]], estimated: list[bool], settle: float, max_offset: float, tolerance: float) -> float:
    """The aligned time before which nothing still to come can change how events are paired. Events still to come are taken
    to be later than `settle` seconds before the latest event; an event within `tolerance` of them may still gain or lose a
    partner. An estimated offset may yet move its stream's events by up to `reach` either way, so they (and, for a stream
    that hasn't reported, any it reports next) limit it too, and count only as early as they may turn out to be."""
    reach = max_offset + 2 * tolerance + OFFSET_BIN  # the estimate is within max_offset, then refined twice by up to tolerance
    latest = max((stream[-1].raw - reach if guessed else stream[-1].t for stream, guessed in zip(items, estimated) if stream), default=None)
    if latest is None:
        return -math.inf
    until = latest - settle
    for stream, guessed in zip(items, estimated):
        if guessed:
            until = min(until, stream[0].raw - reach if stream else latest - settle - max_offset - reach)
    return until - tolerance


def _place(groups: list[_Group], items: list[_Item], known: float | None, max_offset: float, ctx: _Context) -> tuple[float, list[tuple[int, int]]]:
    """The offset of a stream from the groups so far, and the pairs of (group, item) that describe the same action. An
    estimated offset starts from the candidate (a peak of time differences) that pairs best, then is refined twice from
    the events it pairs."""
    if known is not None:
        _shift(items, known)
        return known, _align(groups, items, ctx)[0]
    scored = []
    for candidate in _offset_candidates(groups, items, max_offset, TIME_ZERO * ctx.tolerance):
        _shift(items, candidate)
        scored.append((_align(groups, items, ctx), candidate))
    (matches, _), offset = max(scored, key=lambda found: found[0][1])  # the first, the histogram's peak, on a tie
    _shift(items, offset)
    for _ in range(2):
        if not matches:
            break
        offset += statistics.median(groups[i].t - items[j].t for i, j in matches)  # refine from the paired events
        _shift(items, offset)
        matches = _align(groups, items, ctx)[0]
    return offset, matches


def _shift(items: list[_Item], offset: float) -> None:
    for item in items:
        item.t = item.raw + offset


def _offset_candidates(groups: list[_Group], items: list[_Item], max_offset: float, apart: float, count: int = 3, share: float = 0.5) -> list[float]:
    """The most common time differences between groups and items of the same type and team, within ±max_offset: the peak,
    and up to `count` - 1 other peaks at least `apart` seconds away (nearer ones refine to the same offset) and at least
    `share` as common. Scores and named players count more. [0.0] when nothing compares."""
    order = sorted(range(len(groups)), key=lambda i: groups[i].t)
    times = [groups[i].t for i in order]
    bins: collections.Counter[int] = collections.Counter()
    for item in items:
        lo, hi = bisect.bisect_left(times, item.raw - max_offset), bisect.bisect_right(times, item.raw + max_offset)
        for i in order[lo:hi]:
            group = groups[i]
            if group.items[0].kind == item.kind and group.items[0].team == item.team:
                bins[round((group.t - item.raw) / OFFSET_BIN)] += _offset_weight(group.rep, item.event)
    smoothed = {b: bins[b - 1] + 2 * bins[b] + bins[b + 1] for b in bins}
    peaks: list[int] = []
    for b in sorted(smoothed, key=lambda b: (-smoothed[b], abs(b), b)):
        if len(peaks) == count:
            break
        if peaks and smoothed[b] < share * smoothed[peaks[0]]:
            break
        if all(abs(b - peak) * OFFSET_BIN >= apart for peak in peaks):
            peaks.append(b)
    return [peak * OFFSET_BIN for peak in peaks] or [0.0]


def _offset_weight(a: yus.Event, b: yus.Event) -> float:
    weight = 1.0
    if getattr(a, "scored", False) and getattr(b, "scored", False):
        weight += 2.0  # scores are rare, so they pin the offset
    if getattr(a, "player", None) and _same(getattr(a, "player"), getattr(b, "player", None)):
        weight += 1.0
    return weight


def _align(groups: list[_Group], items: list[_Item], ctx: _Context) -> tuple[list[tuple[int, int]], float]:
    """Monotone alignment: the pairs (group index, item index), increasing in both, with the highest total score; and that score."""
    order = sorted(range(len(groups)), key=lambda i: groups[i].t)
    times = [groups[i].t for i in order]
    edges: list[tuple[int, int, float]] = []
    for j, item in enumerate(items):
        lo, hi = bisect.bisect_left(times, item.t - ctx.tolerance), bisect.bisect_right(times, item.t + ctx.tolerance)
        for i in sorted(order[lo:hi]):
            score = _score(groups[i], item, ctx)
            if score > 0:
                edges.append((i, j, score))
    edges.sort()
    return _best_chain(edges, len(items))


def _best_chain(edges: list[tuple[int, int, float]], width: int) -> tuple[list[tuple[int, int]], float]:
    """Highest-scoring chain of edges (i, j, score) strictly increasing in i and j: a Fenwick tree of prefix maxima over j,
    filled one row i at a time. `edges` is sorted by i."""
    tree = [(0.0, -1)] * (width + 1)
    best: list[tuple[float, int]] = []
    start = 0
    while start < len(edges):
        end = start
        while end < len(edges) and edges[end][0] == edges[start][0]:
            end += 1
        for e in range(start, end):
            prior, j = (0.0, -1), edges[e][1]
            while j > 0:
                prior, j = max(prior, tree[j]), j - (j & -j)
            best.append((prior[0] + edges[e][2], prior[1]))
        for e in range(start, end):
            j = edges[e][1] + 1
            while j <= width:
                tree[j], j = max(tree[j], (best[e][0], e)), j + (j & -j)
        start = end
    chain, e = [], max(range(len(best)), key=lambda e: (best[e][0], e), default=-1)
    total = best[e][0] if e >= 0 else 0.0
    while e >= 0:
        chain.append(edges[e][:2])
        e = best[e][1]
    return chain[::-1], total


def _score(group: _Group, item: _Item, ctx: _Context) -> float:
    """How likely a group and an item describe the same action; 0 when they can't (another type or team, or too far apart)."""
    dt = abs(group.t - item.t)
    if group.items[0].kind != item.kind or group.items[0].team != item.team or dt > ctx.tolerance:
        return 0.0
    score = TIME_WEIGHT * (1 - (dt / (TIME_ZERO * ctx.tolerance)) ** 2)  # events far apart pair only when their details agree
    for field in _fields(type(item.event)):
        u, v = _known(group.rep, field), _known(item.event, field)
        if u is not None and v is not None:
            score += _agreement(field, u, v, item.team, ctx)
    return score


def _agreement(field: str, u: Value, v: Value, team: str | None, ctx: _Context) -> float:
    if field in NAME_FIELDS:
        if _same(u, v):
            return 1.5
        return -2.5 if ctx.is_roster(team, str(u)) and ctx.is_roster(team, str(v)) else -0.5  # a label may name a roster player
    if u == v:
        return 3.0 if field == "scored" and u else 0.5  # a team scores at most once in a few seconds
    return -1.0


def _interleave(groups: list[_Group], items: list[_Item], matches: list[tuple[int, int]], ctx: _Context) -> list[_Group]:
    """The groups with each matched item added, and the other items inserted as groups of their own, in time order between
    matches (keeping both orders)."""
    target_of = dict(matches)
    matched = set(target_of.values())
    found, j = [], 0
    for i, group in enumerate(groups):
        target = target_of.get(i)
        while j < len(items) and j not in matched and (target is not None or items[j].t < group.t):
            found.append(_group([items[j]], ctx))
            j += 1
        if target is not None:
            group, j = _group([*group.items, items[target]], ctx), target + 1
        found.append(group)
    found += [_group([item], ctx) for item in items[j:]]
    return found


def _group(items: list[_Item], ctx: _Context) -> _Group:
    rep, disputes = _merge_fields(items, ctx)
    return _Group(items, rep, disputes, statistics.fmean(item.t for item in items))


def _merge_fields(items: list[_Item], ctx: _Context) -> tuple[yus.Event, dict[str, Rule]]:
    """The merged event for items that describe one action, and the rule that settled each field they disagreed on. It has
    the most specific class among them (an indoor.Throw, not an ultimate.Throw, when both are reported)."""
    base, team = items[0].event, items[0].team
    cls = functools.reduce(lambda cls, item: type(item.event) if issubclass(type(item.event), cls) else cls, items, type(base))
    if cls is not type(base):
        base = cls(**dict(base))
    update: dict[str, Value] = {}
    disputes: dict[str, Rule] = {}
    for field in _fields(cls) if len(items) > 1 else ():
        known = [(item.stream, value) for item in items if (value := _known(item.event, field)) is not None]
        if not known:
            continue
        chosen, rule = known[0][1], None
        if len({_key(value) for _, value in known}) > 1:
            chosen, rule = _settle(field, known, team, ctx)
            disputes[field] = rule
        if chosen != getattr(base, field):
            update[field] = chosen
    return (base.model_copy(update=update) if update else base), disputes


def _settle(field: str, known: list[tuple[int, Value]], team: str | None, ctx: _Context) -> tuple[Value, Rule]:
    """Choose among disagreeing known values, (stream, value) in stream order."""
    rules: list[tuple[Rule, Callable[[int, Value], bool]]] = [
        ("roster", lambda k, v: field in NAME_FIELDS and ctx.is_roster(team, str(v))),
        ("focus", lambda k, v: ctx.focuses(k, team)),
    ]
    for rule, keep in rules:
        kept = [(k, v) for k, v in known if keep(k, v)]
        if kept and len(kept) < len(known):
            known = kept
            if len({_key(v) for _, v in known}) == 1:
                return known[0][1], rule
    counts = collections.Counter(_key(v) for _, v in known)
    most = max(counts.values())
    tied = {value for value, n in counts.items() if n == most}
    return next(v for _, v in known if _key(v) in tied), "majority" if len(tied) == 1 else "earliest"


def _finish(streams: list[yus.EventStream], groups: list[_Group], offsets: list[float], items: list[list[_Item]], stable: float, repair: bool, ctx: _Context) -> MergeResult:
    """The merged stream from the final groups: grammar repaired, times non-decreasing, provisional events marked. Groups
    before `stable` (aligned time) keep their events whatever follows."""
    fixed = bisect.bisect_right(list(itertools.accumulate((group.t for group in groups), max)), stable)
    if repair:
        groups, fixed = _reorder(groups, fixed, ctx)
    events = [_finish_event(group, ctx) for group in groups]
    disputes = [dict(group.disputes) for group in groups]
    if repair:
        _repair_outcomes(events, groups, disputes, ctx)
        fixed = next((p for p in range(fixed - 1, -1, -1) if isinstance(events[p], ultimate.Throw)), fixed)  # a throw depends on what follows, up to the next throw
    for i in range(1, len(events)):
        if events[i].when < events[i - 1].when:
            events[i] = events[i].model_copy(update={"when": events[i - 1].when})
    pairs = [[next((item.index for item in group.items if item.stream == k), None) for k in range(len(streams))] for group in groups]
    conflicts = [_conflict(m, field, rule, group, event, len(streams)) for m, (group, event) in enumerate(zip(groups, events)) for field, rule in disputes[m].items()]
    game = streams[0].game if streams else None
    return MergeResult(
        stream=yus.EventStream(game=game, events=events),
        offsets=offsets,
        pairs=pairs,
        conflicts=conflicts,
        links=_links(groups, ctx),
        settled=fixed,
    )


def _finish_event(group: _Group, ctx: _Context) -> yus.Event:
    """The group's merged event (a copy: never an input event), timed at the mean of its aligned times, with its team named
    consistently."""
    first = group.items[0]
    when = ctx.clock(first.event.when) + datetime.timedelta(seconds=statistics.fmean(item.t for item in group.items) - first.raw)
    update: dict[str, object] = {"when": when} if when != group.rep.when else {}
    if isinstance(group.rep, ultimate.UltimateEvent) and (name := ctx.team_name(first.team, group.rep.team)) != group.rep.team:
        update["team"] = name
    return group.rep.model_copy(update=update)


def _reorder(groups: list[_Group], stable: int, ctx: _Context) -> tuple[list[_Group], int]:
    """Swap neighbours that came out in an order the game can't have (a Defense before the throw it stopped, a pass after the
    score that ended the possession) when the other order fits better. Only events within tolerance of each other and from
    different streams are swapped: each stream's own order is kept. Also returns how many of the reordered groups are final
    given that the first `stable` groups are: deciding a pair looks at the pair, and at the group after it when it may swap."""
    groups = list(groups)
    p, fixed = 0, None
    while p + 1 < len(groups):
        start, a, b = p, groups[p], groups[p + 1]
        seen = p + 1  # the last group the decision depends on (groups from p on are still in their original places)
        if b.t - a.t <= ctx.tolerance and not {item.stream for item in a.items} & {item.stream for item in b.items}:
            seen = p + 2  # past the end, it is whatever comes next
            before = groups[p - 1].rep if p else None
            after = groups[p + 2].rep if p + 2 < len(groups) else None
            kept = _fit(before, a.rep, ctx) + _fit(a.rep, b.rep, ctx) + _fit(b.rep, after, ctx)
            if _fit(before, b.rep, ctx) + _fit(b.rep, a.rep, ctx) + _fit(a.rep, after, ctx) > kept:
                groups[p], groups[p + 1] = b, a
                p += 1
        if fixed is None and seen >= stable:
            fixed = start
        p += 1
    return groups, p if fixed is None else fixed


def _fit(a: yus.Event | None, b: yus.Event | None, ctx: _Context) -> float:
    """How well event b fits right after event a: negative when the game says it can't follow, positive when a throw's
    receiver throws next."""
    same = a is not None and b is not None and _same_team(a, b, ctx)
    if isinstance(a, ultimate.Throw) and isinstance(b, ultimate.Throw):
        link = 0.0
        if a.receiver and b.player:
            link = 1.0 if _same(a.receiver, b.player) else -1.0
        ends = a.scored or not a.completed
        return link - (2.0 if same and ends else 1.0 if not same and not ends else 0.0)
    if isinstance(a, ultimate.Throw) and isinstance(b, ultimate.Defense):
        return -2.0 if same else 0.0
    if isinstance(a, ultimate.Defense) and isinstance(b, ultimate.Throw):
        return 0.0 if same else -1.0
    return 0.0


def _repair_outcomes(events: list[yus.Event], groups: list[_Group], disputes: list[dict[str, Rule]], ctx: _Context) -> None:
    """Make each throw's outcome agree with what follows it: a Defense by the other team next means incomplete; the same team
    throwing next (with no Defense between) means completed and not scored; a score is a catch. An outcome that several
    commentators agreed on is kept (an event they all missed is likelier). Repairs are recorded as "grammar" disputes."""
    throws = [i for i, event in enumerate(events) if isinstance(event, ultimate.Throw)]
    for n, p in enumerate(throws):
        throw = events[p]
        assert isinstance(throw, ultimate.Throw)
        following = throws[n + 1] if n + 1 < len(throws) else len(events)
        defenses = [event for event in events[p + 1 : following] if isinstance(event, ultimate.Defense)]
        if any(not _same_team(event, throw, ctx) for event in defenses):
            want = {"completed": False, "scored": False}
        elif following < len(events) and _same_team(events[following], throw, ctx) and not defenses:
            want = {"completed": True, "scored": False}
        else:  # the other team throws next, or had the disc between (a Defense by this team), or the stream ends
            want = _turnover_or_score(throw, disputes[p], following < len(events) or bool(defenses))
        agreed = len(groups[p].items) > 1
        want = {field: value for field, value in want.items() if getattr(throw, field) != value and not (agreed and field not in disputes[p])}
        if want:
            events[p] = throw.model_copy(update=want)
            disputes[p].update(dict.fromkeys(want, "grammar"))


def _turnover_or_score(throw: ultimate.Throw, disputes: dict[str, Rule], possession_changes: bool) -> dict[str, bool]:
    """What a throw that ends a possession (or the stream) must have been, when its inputs disagreed on how it ended."""
    if possession_changes and throw.completed and not throw.scored:
        if "completed" in disputes:
            return {"completed": False}
        if "scored" in disputes:
            return {"scored": True}
    if throw.scored and not throw.completed:
        return {"scored": False} if "scored" in disputes else {"completed": True}
    return {}


def _conflict(m: int, field: str, rule: Rule, group: _Group, event: yus.Event, width: int) -> Conflict:
    values: list[Value] = [None] * width
    for item in group.items:
        values[item.stream] = getattr(item.event, field, None)
    return Conflict(event=m, field=field, values=values, chosen=getattr(event, field), rule=rule)


def _links(groups: list[_Group], ctx: _Context, least: int = 2, share: float = 0.6) -> list[NameLink]:
    """Names in later streams that, in paired events, consistently stand where the merged stream has another name for an
    unknown player."""
    seen: dict[tuple[int, str, str], collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for group in groups:
        for item in group.items if len(group.items) > 1 else ():
            for field in NAME_FIELDS:
                name, merged = getattr(item.event, field, None), getattr(group.rep, field, None)
                if name and merged and not _same(name, merged) and not ctx.is_roster(item.team, name):
                    seen[(item.stream, getattr(item.event, "team", ""), name)][merged] += 1
    found = []
    for (stream, team, name), counts in seen.items():
        merged, support = counts.most_common(1)[0]
        if support >= least and support >= share * counts.total():
            found.append(NameLink(stream=stream, team=team, name=name, same_as=merged, support=support))
    return found


@functools.cache
def _kind(cls: type[yus.Event]) -> str:
    """Events of one kind can describe the same action: a class and its ancestors of the same name (indoor.Throw is an
    ultimate.Throw, but not an ultimate.Defense)."""
    while issubclass(parent := cls.__base__, yus.Event) and parent.__name__ == cls.__name__:
        cls = parent
    return cls.type_key()


@functools.cache
def _fields(cls: type[yus.Event]) -> tuple[str, ...]:
    """The fields of an event class that merging compares and settles."""
    return tuple(field for field in cls.model_fields if field not in ("when", "team"))


@functools.cache
def _flags(cls: type[yus.Event]) -> frozenset[str]:
    """Fields of an event class that default to False (hit_wall): False there means nobody said so."""
    return frozenset(field for field, info in cls.model_fields.items() if info.default is False)


def _known(event: yus.Event, field: str) -> Value:
    """The field's value, or None when the commentator didn't say: None, or False for a flag that defaults to False."""
    value = getattr(event, field, None)
    if value is None or (value is False and field in _flags(type(event))):
        return None
    return value


def _key(value: Value) -> Value:
    return normalize(value) if isinstance(value, str) else value


def _same(u: Value, v: Value) -> bool:
    return u is not None and v is not None and _key(u) == _key(v)


def _same_team(a: yus.Event, b: yus.Event, ctx: _Context) -> bool:
    return ctx.team_key(getattr(a, "team", None)) == ctx.team_key(getattr(b, "team", None))
