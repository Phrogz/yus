"""Score a predicted event stream against a ground-truth stream: which events were found, and which of their fields are right.

Exposed as the yus-score command-line tool:

    yus-score PRED.json [--gt GT.json] [--team T.json ...] [--resolve] [--descriptions D.json] [--start T] [--stop T] [--shift FROM TO] [-v] [--json]

How events are paired: both streams are sorted by time, then a monotone (order-keeping, never crossing) alignment pairs predicted
events with true ones of the same type at most `tolerance` seconds apart. It maximizes the number of pairs first, then minimizes
the summed cost |dt| / tolerance + (fields that differ / fields compared). Unpaired predictions are false positives; unpaired true
events are misses. A paired event is "exact" when all of its fields agree.

How fields are compared:
  * names (player, receiver) as PlayerResolver compares them: case, punctuation, possessives and a leading "the" are ignored
    ("The Kid" == "kid"); "somebody", "someone", "unknown" and "" mean the same as None;
  * teams by any of their names when teams are given ("dark" == "Category 5"), else as normalized text;
  * a field the event's class lacks takes the default it has where it is defined (an ultimate.Throw's hit_wall is False, as an
    indoor.Throw's is by default).

Times are compared as naive local wall-clock times, like the ground truth's: times with a UTC offset are converted (see naive_clock).

Names can be mapped before comparing, on both streams alike, with `resolve`: a PlayerResolver, or any function from event to event.
"""

from __future__ import annotations

import argparse
import bisect
import datetime as dt
import json
import pathlib
import statistics
import sys
from collections.abc import Callable, Iterable
from typing import Any

import pydantic

import yus
from yus.processing.event_unification.players import PlayerResolver, normalize
from yus.sports import ultimate
from yus.sports.ultimate import indoor  # noqa: F401  (registers indoor.Throw for loading)

DATA = pathlib.Path(__file__).resolve().parents[2] / "tests" / "data"
DEFAULT_TRUTH = DATA / "gruindoor_20250114T2030-eventstream.json"
DEFAULT_TEAMS = [DATA / "team_dump_and_drizzle.json", DATA / "team_category_5.json"]
DEFAULT_TOLERANCE = 3.0

FIELDS_BY_KIND: dict[str, tuple[str, ...]] = {
    "throw": ("team", "player", "receiver", "type", "direction", "completed", "scored", "hit_wall", "hit_net"),
    "defense": ("team", "player", "intercepted"),
    "substitution": ("team", "player", "sub_type"),
    "infraction": ("team", "player"),
}
FIELDS = ("team", "player", "receiver", "type", "direction", "completed", "scored", "hit_wall", "hit_net", "intercepted", "sub_type")
NAME_FIELDS = {"player", "receiver"}
UNKNOWN_NAMES = {"", "somebody", "someone", "some one", "unknown", "none", "null", "n a", "nobody"}

Resolve = Callable[[yus.Event], yus.Event]
Clock = Callable[[dt.datetime], dt.datetime]
TimeSpec = dt.datetime | float | str


def _defaults() -> dict[str, Any]:
    found: dict[str, Any] = {}
    for model in (indoor.Throw, ultimate.Defense, ultimate.Substitution, ultimate.Infraction):
        for name, info in model.model_fields.items():
            if not info.is_required():
                found.setdefault(name, info.default)
    return found


DEFAULTS = _defaults()  # optional fields' defaults, for events whose class lacks the field


class Counts(pydantic.BaseModel):
    """True positives, false positives and misses, with precision, recall and F1 (None when neither side has anything)."""

    tp: int = 0
    fp: int = 0
    fn: int = 0
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None

    @classmethod
    def of(cls, tp: int, fp: int, fn: int) -> Counts:
        if tp + fp + fn == 0:
            return cls()
        return cls(tp=tp, fp=fp, fn=fn, precision=tp / (tp + fp) if tp + fp else 0.0, recall=tp / (tp + fn) if tp + fn else None, f1=2 * tp / (2 * tp + fp + fn))


class TypeScore(Counts):
    """Counts for one event type, plus how many of its paired events were exact."""

    truth: int = 0
    predicted: int = 0
    exact: int = 0

    @property
    def exact_rate(self) -> float | None:
        return self.exact / self.tp if self.tp else None


class FieldScore(pydantic.BaseModel):
    """Agreement on one field over the paired events that have it; `known_*` only counts pairs whose true value is not None."""

    total: int = 0
    correct: int = 0
    known_total: int = 0
    known_correct: int = 0

    @property
    def accuracy(self) -> float | None:
        return self.correct / self.total if self.total else None

    @property
    def known_accuracy(self) -> float | None:
        return self.known_correct / self.known_total if self.known_total else None


class Timing(pydantic.BaseModel):
    """Time differences (predicted - true, seconds) over paired events."""

    n: int = 0
    mean_abs: float | None = None
    median_abs: float | None = None
    max_abs: float | None = None
    mean_signed: float | None = None


class Match(pydantic.BaseModel):
    """A predicted event paired with a true one, and the fields where they differ (true value, predicted value)."""

    type: str
    truth_index: int
    predicted_index: int
    when: dt.datetime
    dt: float
    mismatches: dict[str, tuple[Any, Any]] = {}


class Unpaired(pydantic.BaseModel):
    """A miss (true event with no prediction) or a false positive (prediction with no true event)."""

    type: str
    index: int
    when: dt.datetime
    fields: dict[str, Any]


class Score(pydantic.BaseModel):
    """Result of `score()`. `overall` counts paired events; `exact` counts paired events whose fields all agree."""

    tolerance: float
    t0: dt.datetime
    start: dt.datetime | None = None
    stop: dt.datetime | None = None
    overall: Counts
    exact: Counts
    per_type: dict[str, TypeScore]
    fields: dict[str, FieldScore]
    timing: Timing
    matches: list[Match] = []
    misses: list[Unpaired] = []
    false_positives: list[Unpaired] = []
    warnings: list[str] = []

    @property
    def exact_rate(self) -> float | None:
        """Share of paired events that are exact."""
        return self.exact.tp / self.overall.tp if self.overall.tp else None

    def report(self, verbose: bool = False) -> str:
        """A text table of the scores; `verbose` also lists misses, false positives and field mismatches."""
        lines = _report_header(self) + _report_types(self) + _report_fields(self) + _report_timing(self)
        return "\n".join(lines + (_report_details(self) if verbose else []))


class _Prepared(pydantic.BaseModel):
    index: int
    when: dt.datetime
    t: float
    kind: str
    fields: tuple[str, ...]
    raw: dict[str, Any]
    norm: dict[str, Any]


def score(
    predicted: Any,
    truth: Any,
    *,
    tolerance: float = DEFAULT_TOLERANCE,
    start: TimeSpec | None = None,
    stop: TimeSpec | None = None,
    t0: dt.datetime | None = None,
    teams: list[yus.Team] | None = None,
    resolve: PlayerResolver | Resolve | None = None,
    strict_type: bool = False,
    shift: dt.timedelta | None = None,
) -> Score:
    """Score `predicted` events against `truth` (each an EventStream, a list of events or event dicts, or a JSON path; see load_events).

    start / stop keep only events (on both sides) with start <= when < stop; each is a datetime, an ISO or clock-time string, or
    seconds after `t0`. t0 defaults to the earliest true event. Any time may be naive or carry a UTC offset (see naive_clock).
    teams make team names synonyms ("dark" == "Category 5"); a PlayerResolver given as `resolve` supplies its teams when `teams` is
    None. `resolve` maps names on both sides before comparing. strict_type requires identical "__type__" tags (indoor.Throw !=
    ultimate.Throw); by default only the class name counts. `shift` is added to every predicted time first, e.g. to score a live
    replay of a recording, timed on the day it was replayed, against the recording's truth.
    """
    warnings: list[str] = []
    truth_events = load_events(truth, warnings, "truth")
    predicted_events = load_events(predicted, warnings, "predicted")
    if shift:
        predicted_events = [event.model_copy(update={"when": event.when + shift}) for event in predicted_events]
    if isinstance(resolve, PlayerResolver):
        teams = resolve.teams if teams is None else teams
        resolve = resolve.resolve_event
    if resolve is not None:
        truth_events = [resolve(event) for event in truth_events]
        predicted_events = [resolve(event) for event in predicted_events]
    clock = naive_clock([event.when for event in truth_events + predicted_events] + _datetimes(t0, start, stop))
    if t0 is None:
        t0 = min((clock(event.when) for event in truth_events or predicted_events), default=dt.datetime(2000, 1, 1))
    t0 = clock(t0)
    window = (parse_time(start, t0, clock) if start is not None else None, parse_time(stop, t0, clock) if stop is not None else None)
    synonyms = _team_synonyms(teams)
    truth_prepared = _prepare(truth_events, t0, window, synonyms, strict_type, clock)
    predicted_prepared = _prepare(predicted_events, t0, window, synonyms, strict_type, clock)
    pairs = align(predicted_prepared, truth_prepared, tolerance)
    result = _tally(predicted_prepared, truth_prepared, pairs)
    return Score(tolerance=tolerance, t0=t0, start=window[0], stop=window[1], warnings=warnings, **result)


def load_events(source: Any, warnings: list[str] | None = None, label: str = "events") -> list[yus.Event]:
    """Events from a path or "-" (stdin) holding {"events": [...]}, a JSON list or JSON lines; from an EventStream; or from a list of
    events or event dicts. Dicts without "__type__" get one inferred from their fields; events that fail to load are skipped and
    reported in `warnings`."""
    if isinstance(source, (str, pathlib.Path)):
        text = sys.stdin.read() if str(source) == "-" else pathlib.Path(source).read_text()
        try:
            source = json.loads(text)
        except json.JSONDecodeError:
            try:
                source = [json.loads(line) for line in text.splitlines() if line.strip()]
            except json.JSONDecodeError as error:
                raise ValueError(f"{source}: neither JSON nor JSON lines ({error})") from None
    if isinstance(source, dict):
        source = source.get("events", [source] if "when" in source else [])
    if isinstance(source, yus.EventStream):
        source = source.events
    events: list[yus.Event] = []
    for index, item in enumerate(source):
        try:
            events.append(item if isinstance(item, yus.Event) else yus.Event.from_tagged(_with_type(item)))
        except (ValueError, TypeError) as error:
            if warnings is not None:
                warnings.append(f"{label} event #{index} skipped: {str(error).splitlines()[0]}")
    return events


def parse_time(value: TimeSpec, t0: dt.datetime, clock: Clock | None = None) -> dt.datetime:
    """A datetime from a datetime, seconds after t0 (float or numeric string), an ISO datetime, or a clock time on t0's date. A time
    with a UTC offset keeps it, unless `clock` (see naive_clock) is given to make it naive."""
    clock = clock or _same
    if isinstance(value, dt.datetime):
        return clock(value)
    if isinstance(value, (int, float)):
        return clock(t0 + dt.timedelta(seconds=float(value)))
    text = value.strip()
    try:
        return clock(t0 + dt.timedelta(seconds=float(text)))
    except ValueError:
        pass
    try:
        return clock(dt.datetime.fromisoformat(text))
    except ValueError:
        pass
    try:
        return clock(dt.datetime.combine(t0.date(), dt.time.fromisoformat(text), tzinfo=t0.tzinfo))
    except ValueError:
        raise ValueError(f"Cannot parse time {value!r}: want an ISO datetime, HH:MM:SS[.f], or seconds after t0") from None


def naive_clock(times: Iterable[dt.datetime]) -> Clock:
    """A function giving times as naive local wall-clock times, so that naive times and times with a UTC offset compare. Naive
    times stay as they are. Times with an offset go to the zone of the first of `times` whose offset isn't UTC (the commentator's
    local time, which naive times are taken to be in), else to this system's local time."""
    zone = next((when.tzinfo for when in times if when.utcoffset() not in (None, dt.timedelta(0))), None)
    return lambda when: when.replace(tzinfo=None) if when.utcoffset() is None else when.astimezone(zone).replace(tzinfo=None)


def _same(when: dt.datetime) -> dt.datetime:
    return when


def _datetimes(*values: TimeSpec | None) -> list[dt.datetime]:
    """The values that are datetimes or ISO datetime strings, as datetimes (so that their UTC offsets can choose the clock)."""
    found = []
    for value in values:
        try:
            found.append(dt.datetime.fromisoformat(value.strip()) if isinstance(value, str) else value)
        except ValueError:
            pass
    return [value for value in found if isinstance(value, dt.datetime)]


def transcript_start(truth_path: pathlib.Path) -> dt.datetime | None:
    """Start of the first word of the transcript stored next to a "<stem>-eventstream.json" file as "<stem>-transcript.json"."""
    name = truth_path.name
    if not name.endswith("-eventstream.json"):
        return None
    path = truth_path.with_name(name.removesuffix("-eventstream.json") + "-transcript.json")
    if not path.exists():
        return None
    transcript = yus.Transcript.model_validate_json(path.read_text())
    return transcript.words[0].start if transcript.words else None


def align(predicted: list[_Prepared], truth: list[_Prepared], tolerance: float) -> list[tuple[int, int]]:
    """Monotone alignment as (predicted index, true index) pairs: most pairs first, then least summed cost."""
    n, m = len(predicted), len(truth)
    if not n or not m:
        return []
    times = [event.t for event in truth]
    bonus = 2.0 * min(n, m) + 4.0  # more than any summed cost, so one more pair always wins
    width = m + 1
    back = bytearray((n + 1) * width)  # 0: pair, 1: skip predicted, 2: skip true
    back[1:width] = b"\x02" * m
    previous = [0.0] * width
    for i in range(1, n + 1):
        gains = _pair_gains(predicted[i - 1], truth, times, tolerance, bonus)
        current = [0.0] * width
        back[i * width] = 1
        for j in range(1, width):
            best, choice = (previous[j], 1) if previous[j] >= current[j - 1] else (current[j - 1], 2)
            gain = gains.get(j - 1)
            if gain is not None and previous[j - 1] + gain >= best:
                best, choice = previous[j - 1] + gain, 0
            current[j] = best
            back[i * width + j] = choice
        previous = current
    return _trace(back, n, m, width)


def _pair_gains(event: _Prepared, truth: list[_Prepared], times: list[float], tolerance: float, bonus: float) -> dict[int, float]:
    eps = 1e-6
    gains: dict[int, float] = {}
    for j in range(bisect.bisect_left(times, event.t - tolerance - eps), bisect.bisect_right(times, event.t + tolerance + eps)):
        other = truth[j]
        if other.kind == event.kind:
            cost = abs(event.t - other.t) / tolerance if tolerance > 0 else 0.0
            gains[j] = bonus - cost - len(_mismatches(event, other)) / (len(other.fields) or 1)
    return gains


def _trace(back: bytearray, n: int, m: int, width: int) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    i, j = n, m
    while i > 0 and j > 0:
        choice = back[i * width + j]
        if choice == 0:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif choice == 1:
            i -= 1
        else:
            j -= 1
    return pairs[::-1]


def _with_type(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("__type__"):
        return data
    if "sub_type" in data:
        key = ultimate.Substitution.type_key()
    elif "intercepted" in data:
        key = ultimate.Defense.type_key()
    elif any(field in data for field in ("completed", "scored", "receiver", "direction", "hit_wall", "hit_net")):
        key = indoor.Throw.type_key()
    else:
        key = ultimate.Infraction.type_key()
    return {**data, "__type__": key}


def _team_synonyms(teams: list[yus.Team] | None) -> dict[str, str]:
    synonyms: dict[str, str] = {}
    for team in teams or []:
        for name in team.names:
            synonyms[normalize(name)] = normalize(team.names[0])
    return synonyms


def _normalize(field: str, value: Any, synonyms: dict[str, str]) -> Any:
    if value is None or isinstance(value, bool):
        return value
    text = normalize(str(getattr(value, "value", value)))
    if field in NAME_FIELDS:
        return None if text in UNKNOWN_NAMES else text
    if field == "team":
        return synonyms.get(text, text) or None
    return text or None


def _kind(event: yus.Event, strict: bool) -> str:
    return event.type_key() if strict else type(event).__name__.lower()


def _prepare(
    events: list[yus.Event], t0: dt.datetime, window: tuple[dt.datetime | None, dt.datetime | None], synonyms: dict[str, str], strict: bool, clock: Clock
) -> list[_Prepared]:
    start, stop = window
    prepared = []
    for index, event in enumerate(events):
        when = clock(event.when)
        if (start is not None and when < start) or (stop is not None and when >= stop):
            continue
        kind = _kind(event, strict)
        fields = FIELDS_BY_KIND.get(type(event).__name__.lower(), ("team", "player"))
        raw = {field: _plain(getattr(event, field, DEFAULTS.get(field))) for field in fields}
        norm = {field: _normalize(field, raw[field], synonyms) for field in fields}
        prepared.append(_Prepared(index=index, when=when, t=(when - t0).total_seconds(), kind=kind, fields=fields, raw=raw, norm=norm))
    return sorted(prepared, key=lambda event: (event.t, event.index))


def _plain(value: Any) -> Any:
    return getattr(value, "value", value)


def _mismatches(predicted: _Prepared, truth: _Prepared) -> list[str]:
    return [field for field in truth.fields if predicted.norm.get(field) != truth.norm.get(field)]


def _display(kind: str) -> str:
    return kind if "." in kind else kind.capitalize()


def _tally(predicted: list[_Prepared], truth: list[_Prepared], pairs: list[tuple[int, int]]) -> dict[str, Any]:
    order = list(FIELDS_BY_KIND)
    kinds = sorted({e.kind for e in truth} | {e.kind for e in predicted}, key=lambda k: (order.index(_base(k)) if _base(k) in order else len(order), k))
    per = {kind: {"truth": 0, "predicted": 0, "tp": 0, "exact": 0} for kind in kinds}
    for event in truth:
        per[event.kind]["truth"] += 1
    for event in predicted:
        per[event.kind]["predicted"] += 1
    fields = {field: FieldScore() for field in FIELDS}
    matches = []
    for p, t in pairs:
        match = _pair(predicted[p], truth[t], fields)
        per[truth[t].kind]["tp"] += 1
        per[truth[t].kind]["exact"] += not match.mismatches
        matches.append(match)
    exact = sum(not match.mismatches for match in matches)
    paired_p, paired_t = {p for p, _ in pairs}, {t for _, t in pairs}
    return {
        "overall": Counts.of(len(pairs), len(predicted) - len(pairs), len(truth) - len(pairs)),
        "exact": Counts.of(exact, len(predicted) - exact, len(truth) - exact),
        "per_type": {_display(kind): _type_score(**counts) for kind, counts in per.items()},
        "fields": fields,
        "timing": _timing([match.dt for match in matches]),
        "matches": matches,
        "misses": [_unpaired(event) for k, event in enumerate(truth) if k not in paired_t],
        "false_positives": [_unpaired(event) for k, event in enumerate(predicted) if k not in paired_p],
    }


def _base(kind: str) -> str:
    return kind.rsplit(".", 1)[-1].lower()


def _type_score(truth: int, predicted: int, tp: int, exact: int) -> TypeScore:
    counts = Counts.of(tp, predicted - tp, truth - tp)
    return TypeScore(**counts.model_dump(), truth=truth, predicted=predicted, exact=exact)


def _pair(predicted: _Prepared, truth: _Prepared, fields: dict[str, FieldScore]) -> Match:
    mismatched = _mismatches(predicted, truth)
    for field in truth.fields:
        ok = field not in mismatched
        tally = fields[field]
        tally.total += 1
        tally.correct += ok
        if truth.norm.get(field) is not None:
            tally.known_total += 1
            tally.known_correct += ok
    return Match(
        type=_display(truth.kind),
        truth_index=truth.index,
        predicted_index=predicted.index,
        when=truth.when,
        dt=round(predicted.t - truth.t, 6),
        mismatches={field: (truth.raw.get(field), predicted.raw.get(field)) for field in mismatched},
    )


def _unpaired(event: _Prepared) -> Unpaired:
    return Unpaired(type=_display(event.kind), index=event.index, when=event.when, fields=event.raw)


def _timing(dts: list[float]) -> Timing:
    if not dts:
        return Timing()
    absolute = [abs(x) for x in dts]
    return Timing(n=len(dts), mean_abs=statistics.fmean(absolute), median_abs=statistics.median(absolute), max_abs=max(absolute), mean_signed=statistics.fmean(dts))


def _pct(x: float | None) -> str:
    return "   n/a" if x is None else f"{100 * x:5.1f}%"


def _offset(result: Score, when: dt.datetime | None) -> str:
    return f"{(when - result.t0).total_seconds():.1f}s" if when else ""


def _report_header(result: Score) -> list[str]:
    window = f"[{_offset(result, result.start) or '-inf'}, {_offset(result, result.stop) or '+inf'})"
    lines = [f"Event score  t0={result.t0.isoformat()}  window={window}  tolerance={result.tolerance:g}s"]
    lines += [f"  warning: {warning}" for warning in result.warnings[:5]]
    if len(result.warnings) > 5:
        lines.append(f"  ... {len(result.warnings) - 5} more warnings")
    return lines + ["", f"  {'Events':<14}{'True':>5}{'Pred':>6}{'TP':>6}{'FP':>5}{'FN':>5}   {'Prec':>6} {'Recall':>6} {'F1':>6}  {'Exact':>6}"]


def _report_types(result: Score) -> list[str]:
    lines = [
        f"  {kind:<14}{d.truth:>5}{d.predicted:>6}{d.tp:>6}{d.fp:>5}{d.fn:>5}   {_pct(d.precision)} {_pct(d.recall)} {_pct(d.f1)}  {_pct(d.exact_rate)}"
        for kind, d in result.per_type.items()
    ]
    o, e = result.overall, result.exact
    lines.append(f"  {'OVERALL':<14}{o.tp + o.fn:>5}{o.tp + o.fp:>6}{o.tp:>6}{o.fp:>5}{o.fn:>5}   {_pct(o.precision)} {_pct(o.recall)} {_pct(o.f1)}  {_pct(result.exact_rate)}")
    lines.append(f"  Exact (all fields agree): {e.tp}/{o.tp} paired; exact precision / recall / F1 = {_pct(e.precision).strip()} / {_pct(e.recall).strip()} / {_pct(e.f1).strip()}")
    return lines


def _report_fields(result: Score) -> list[str]:
    lines = ["", f"  {'Field':<12}{'Accuracy':>9}  {'(n)':>11}   {'True known':>10}  {'(n)':>11}"]
    for field, s in result.fields.items():
        if s.total:
            lines.append(f"  {field:<12}{_pct(s.accuracy):>9}  {f'({s.correct}/{s.total})':>11}   {_pct(s.known_accuracy):>10}  {f'({s.known_correct}/{s.known_total})':>11}")
    return lines


def _report_timing(result: Score) -> list[str]:
    t = result.timing
    if not t.n:
        return []
    return ["", f"  |dt| over {t.n} pairs (s): mean {t.mean_abs:.2f}  median {t.median_abs:.2f}  max {t.max_abs:.2f}  mean signed (pred - true) {t.mean_signed:+.2f}"]


def _describe(fields: dict[str, Any]) -> str:
    return " ".join(f"{k}={v}" for k, v in fields.items() if v not in (None, False))


def _report_details(result: Score) -> list[str]:
    lines = ["", f"MISSES (true events with no prediction): {len(result.misses)}"]
    lines += [f"  {_offset(result, u.when):>8}  true#{u.index:<4} {u.type:<9} {_describe(u.fields)}" for u in result.misses]
    lines += ["", f"FALSE POSITIVES (predictions with no true event): {len(result.false_positives)}"]
    lines += [f"  {_offset(result, u.when):>8}  pred#{u.index:<4} {u.type:<9} {_describe(u.fields)}" for u in result.false_positives]
    wrong = [m for m in result.matches if m.mismatches]
    lines += ["", f"FIELD MISMATCHES (paired events with a differing field): {len(wrong)}"]
    for m in wrong:
        diffs = ", ".join(f"{field}: true={a!r} pred={b!r}" for field, (a, b) in m.mismatches.items())
        lines.append(f"  {_offset(result, m.when):>8}  true#{m.truth_index:<4} pred#{m.predicted_index:<4} dt={m.dt:+.2f}  {m.type:<9} {diffs}")
    return lines


def _load_teams(paths: Iterable[pathlib.Path]) -> list[yus.Team]:
    return [yus.Team.model_validate_json(pathlib.Path(path).read_text()) for path in paths]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Score a predicted event stream against a ground-truth stream.",
        epilog="T for --start/--stop: an ISO datetime, a clock time (20:38:30.9) or seconds after t0 (463.3). "
        "For the bundled game: dev split --stop 463.3, test split --start 463.3.",
    )
    parser.add_argument("predicted", help='predicted stream: {"events": [...]}, a JSON list, or JSON lines ("-" reads stdin)')
    parser.add_argument("--gt", type=pathlib.Path, default=DEFAULT_TRUTH if DEFAULT_TRUTH.exists() else None, help="ground-truth stream (default: %(default)s)")
    parser.add_argument("--team", type=pathlib.Path, action="append", help="team JSON; makes team names synonyms (default for the bundled ground truth: its teams)")
    parser.add_argument("--resolve", action="store_true", help="map player names to roster players with PlayerResolver on both sides before comparing")
    parser.add_argument("--descriptions", type=pathlib.Path, help="per-game descriptions JSON for PlayerResolver (implies --resolve)")
    parser.add_argument("--commentator", help="commentator whose descriptions apply (default: shared descriptions only)")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE, help="largest time difference of a pair, seconds (default: %(default)s)")
    parser.add_argument("--start", help="keep events with when >= T (both sides)")
    parser.add_argument("--stop", help="keep events with when < T (both sides)")
    parser.add_argument(
        "--t0", help="time that seconds in --start/--stop count from (default: first word of the <stem>-transcript.json beside the truth, else the first true event)"
    )
    parser.add_argument(
        "--shift",
        nargs=2,
        metavar=("FROM", "TO"),
        help="move predicted times by TO - FROM (ISO datetimes), e.g. the time yus-replay says it stamped a recording's start, and the recording's start",
    )
    parser.add_argument("--strict-type", action="store_true", help='require identical "__type__" tags')
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="list misses, false positives and field mismatches")
    args = parser.parse_args(argv)
    if args.gt is None:
        parser.error("--gt is required (no bundled ground truth found)")

    team_paths = args.team or (DEFAULT_TEAMS if args.gt.resolve() == DEFAULT_TRUTH.resolve() else [])
    if (args.resolve or args.descriptions) and not team_paths:
        parser.error("--resolve and --descriptions need the teams' rosters: pass --team for each team")
    try:
        teams = _load_teams(team_paths)
        resolve: PlayerResolver | Resolve | None = None
        if args.resolve or args.descriptions:
            from yus.processing.event_unification import GameDescriptions

            descriptions = GameDescriptions.model_validate_json(args.descriptions.read_text()) if args.descriptions else None
            resolver = PlayerResolver(teams, descriptions)
            resolve = lambda event: resolver.resolve_event(event, args.commentator)  # noqa: E731
        first = transcript_start(args.gt)
        t0 = parse_time(args.t0, first or dt.datetime(2000, 1, 1)) if args.t0 else first
        shift = dt.datetime.fromisoformat(args.shift[1]) - dt.datetime.fromisoformat(args.shift[0]) if args.shift else None
        result = score(
            args.predicted,
            args.gt,
            tolerance=args.tolerance,
            start=args.start,
            stop=args.stop,
            t0=t0,
            teams=teams or None,
            resolve=resolve,
            strict_type=args.strict_type,
            shift=shift,
        )
    except (OSError, ValueError) as error:  # unreadable or invalid files and times (pydantic's and json's errors are ValueErrors)
        print(f"Error: {error}", file=sys.stderr)
        return 1
    if args.json:
        exclude = None if args.verbose else {"matches", "misses", "false_positives"}
        print(result.model_dump_json(indent=2, exclude=exclude))
    else:
        print(f"Truth: {args.gt}\nPredicted: {args.predicted}")
        print(result.report(verbose=args.verbose))
    return 0


if __name__ == "__main__":
    sys.exit(main())
