import dataclasses
import datetime
import random
import statistics
import time

import pytest

import yus
from tests.data.gruindoor_20250114T2030 import build_game
from yus.processing.event_unification import LiveMerger, MergeResult, merge_streams
from yus.processing.event_unification.players import normalize
from yus.sports import ultimate
from yus.sports.ultimate import indoor

SPLIT = datetime.datetime(2025, 1, 14, 20, 30, 47, 600000) + datetime.timedelta(seconds=463.3)  # dev before, test after
B_TEAMS = {"white": "light", "black": "dark"}  # the second commentator calls the teams differently...
B_LABELS = {"glasses": "specs", "blondie": "blond hair", "bluey": "blue shirt", "yellow sleeve": "yellow shirt", "leg stripe": "purple leg stripe"}  # ...and unknown players


@dataclasses.dataclass
class Commentary:
    """Two synthetic commentators' resolved streams of the ground-truth game, and which true event each event reports."""

    streams: list[yus.EventStream]
    sources: list[list[int]]
    offset: float  # seconds the second commentator's clock is ahead of the first's
    focus: list[str | None]


def commentate(truth: list[yus.Event], mode: str, seed: int, offset: float, jitter: float = 0.6) -> Commentary:
    """Two commentators report the true events. "dual": both cover the whole game and miss ~10% of events. "split": the first
    covers white and the second black, each missing ~5% of their team's events and reporting ~25% of the other team's without
    names or throw types. Each report is jittered in time and may drop a name, throw type, direction or wall hit, or flip its
    outcome; the second commentator's clock is `offset` seconds ahead, and it names teams and unknown players differently."""
    rng = random.Random(seed)
    said: list[list[tuple[int, yus.Event]]] = [[], []]
    for i, event in enumerate(truth):
        for c in (0, 1):
            own = mode == "dual" or (c == 0) == (getattr(event, "team") == "white")
            if rng.random() < (0.9 if mode == "dual" else 0.95 if own else 0.25):
                said[c].append((i, report(event, c, own, rng, offset if c else 0.0, jitter)))
    for c in (0, 1):  # a commentator reports events in the order they happen
        times = sorted(event.when for _, event in said[c])
        said[c] = [(i, event.model_copy(update={"when": when})) for (i, event), when in zip(said[c], times)]
    focus: list[str | None] = [None, None] if mode == "dual" else ["white", "dark"]
    return Commentary([yus.EventStream(events=[e for _, e in s]) for s in said], [[i for i, _ in s] for s in said], offset, focus)


def report(event: yus.Event, commentator: int, own: bool, rng: random.Random, offset: float, jitter: float) -> yus.Event:
    update: dict[str, object] = {"when": event.when + datetime.timedelta(seconds=offset + rng.gauss(0, jitter))}
    fields = type(event).model_fields
    for field, unsaid in (("player", 0.05), ("receiver", 0.1), ("type", 0.25), ("direction", 0.4), ("hit_wall", 0.3)):
        if field in fields and (rng.random() < unsaid or (not own and field in ("player", "receiver", "type", "direction"))):
            update[field] = fields[field].default
    for field, flipped in (("completed", 0.03), ("scored", 0.02)):
        if field in fields and rng.random() < flipped:
            update[field] = not getattr(event, field)
    if commentator:
        update["team"] = B_TEAMS[getattr(event, "team")]
        for field in ("player", "receiver"):
            name = update.get(field, getattr(event, field, None))
            update[field] = B_LABELS.get(name, name) if isinstance(name, str) else name
    return event.model_copy(update={k: v for k, v in update.items() if k in fields})


def measure(result: MergeResult, commentary: Commentary, truth: list[yus.Event], teams: list[yus.Team], part: str = "all") -> dict[str, float]:
    """Against the truth: pairing precision and recall, extra merged events, and per team the error in goals and completion %.
    `part` limits it to the true events of the "dev" or "test" part of the game."""
    keep = {i for i, event in enumerate(truth) if part == "all" or (event.when < SPLIT) == (part == "dev")}
    sources = [[{commentary.sources[k][j]} if j is not None else set() for k, j in enumerate(pair)] for pair in result.pairs]
    groups = [(set().union(*s), sum(bool(x) for x in s)) for s in sources]
    paired = [srcs for srcs, members in groups if members > 1 and srcs & keep]
    shared = set(commentary.sources[0]) & set(commentary.sources[1]) & keep
    together = {next(iter(srcs)) for srcs in paired if len(srcs) == 1}
    official = {normalize(name): team.names[0] for team in teams for name in team.names}
    merged = [e for e, (srcs, _) in zip(result.stream.events, groups) if srcs & keep]
    real = [truth[i] for i in sorted(keep)]
    found = {"precision": sum(len(s) == 1 for s in paired) / max(1, len(paired)), "recall": len(together & shared) / max(1, len(shared))}
    found["events"] = len(merged) - len(real)
    for team in teams:
        name = team.names[0]
        mine = [e for e in merged if isinstance(e, ultimate.Throw) and official[normalize(e.team)] == name]
        true = [e for e in real if isinstance(e, ultimate.Throw) and official[normalize(e.team)] == name]
        found[f"goals {name}"] = sum(e.scored for e in mine) - sum(e.scored for e in true)
        found[f"comp% {name}"] = 100 * (sum(e.completed for e in mine) / max(1, len(mine)) - sum(e.completed for e in true) / max(1, len(true)))
    return found


def arriving(commentary: Commentary, until: float, lags: list[float]) -> list[yus.EventStream]:
    """The events each commentator has reported `until` seconds into the game, with each stream `lags` seconds behind."""
    start = commentary.streams[0].events[0].when
    offsets = [0.0, commentary.offset]
    return [yus.EventStream(events=[e for e in stream.events if (e.when - start).total_seconds() - offsets[k] <= until - lags[k]]) for k, stream in enumerate(commentary.streams)]


T0 = datetime.datetime(2025, 1, 14, 20, 31)


def throw(t: float, team: str, player: str | None, receiver: str | None, completed: bool = True, scored: bool = False, **fields) -> indoor.Throw:
    return indoor.Throw(when=T0 + datetime.timedelta(seconds=t), team=team, player=player, receiver=receiver, completed=completed, scored=scored, **fields)


def defense(t: float, team: str, player: str | None) -> ultimate.Defense:
    return ultimate.Defense(when=T0 + datetime.timedelta(seconds=t), team=team, player=player)


def stream(*events: yus.Event) -> yus.EventStream:
    return yus.EventStream(events=list(events))


@pytest.fixture(scope="module")
def game() -> yus.Game:
    return build_game()


@pytest.fixture(scope="module")
def truth(game: yus.Game) -> list[yus.Event]:
    assert game.official_stream is not None
    return game.official_stream.events


def test_one_stream_is_unchanged(game: yus.Game, truth: list[yus.Event]):
    official = yus.EventStream(events=truth)
    result = merge_streams([official])
    assert result.stream.events == truth
    assert result.offsets == [0.0] and result.pairs == [[i] for i in range(len(truth))] and result.conflicts == [] and result.links == []
    named = merge_streams([official], teams=game.teams).stream.events  # teams known: merged events use official team names
    assert [e.model_copy(update={"team": t.team}) for e, t in zip(named, truth)] == truth
    assert {e.team for e in named} == {"Dump & Drizzle", "Category 5"}


def test_a_shifted_copy_merges_into_the_original(truth: list[yus.Event]):
    official = yus.EventStream(events=truth)
    shifted = yus.EventStream(events=[e.model_copy(update={"when": e.when + datetime.timedelta(seconds=7.3)}) for e in truth])
    result = merge_streams([official, shifted])
    assert result.offsets[1] == pytest.approx(-7.3, abs=0.01)
    assert result.pairs == [[i, i] for i in range(len(truth))]
    assert [e.model_copy(update={"when": t.when}) for e, t in zip(result.stream.events, truth)] == truth
    assert max(abs((e.when - t.when).total_seconds()) for e, t in zip(result.stream.events, truth)) < 0.01
    assert result.conflicts == []


def test_nothing_to_merge():
    assert merge_streams([]).stream.events == []
    result = merge_streams([stream(), stream()])
    assert result.stream.events == [] and result.offsets == [0.0, 0.0] and result.settled == 0


# Measured on 40 seeds (whole game): dual P 0.997 (min 0.981), R 0.993 (min 0.974), offset error 0.06 s (max 0.19); split P 0.94
# (min 0.81), R 0.94 (min 0.83), offset error 0.14 s (max 0.55). These 8 seeds are tested with some margin.
EXPECT = {
    "dual": {"precision": (0.98, 0.99), "recall": (0.97, 0.985), "offset": 0.25, "goals": 2, "comp%": 2.5, "exact scores": 4},
    "split": {"precision": (0.85, 0.92), "recall": (0.85, 0.92), "offset": 0.6, "goals": 3, "comp%": 3.5, "exact scores": 1},
}


@pytest.mark.parametrize("mode", ["dual", "split"])
def test_two_synthetic_commentators(game: yus.Game, truth: list[yus.Event], mode: str):
    expect = EXPECT[mode]
    found = []
    for seed in range(8):
        commentary = commentate(truth, mode, seed, offset=4 + seed)
        result = merge_streams(commentary.streams, focus=commentary.focus, teams=game.teams)
        measured = measure(result, commentary, truth, game.teams)
        alone = measure(merge_streams(commentary.streams[:1], teams=game.teams), commentary, truth, game.teams)
        goals = [abs(measured[f"goals {team.names[0]}"]) for team in game.teams]
        assert measured["precision"] >= expect["precision"][0] and measured["recall"] >= expect["recall"][0], (seed, measured)
        assert abs(result.offsets[1] + commentary.offset) <= expect["offset"], (seed, result.offsets)
        assert max(goals) <= expect["goals"], (seed, measured)
        assert sum(goals) <= sum(abs(alone[f"goals {team.names[0]}"]) for team in game.teams), (seed, measured, alone)  # better than one commentator
        assert max(abs(measured[f"comp% {team.names[0]}"]) for team in game.teams) <= expect["comp%"], (seed, measured)
        found.append((measured["precision"], measured["recall"], sum(goals) == 0))
    assert statistics.fmean(p for p, _, _ in found) >= expect["precision"][1]
    assert statistics.fmean(r for _, r, _ in found) >= expect["recall"][1]
    assert sum(exact for _, _, exact in found) >= expect["exact scores"]


def test_three_commentators(game: yus.Game, truth: list[yus.Event]):
    first, second = commentate(truth, "dual", 11, offset=5.0), commentate(truth, "dual", 12, offset=-8.0)
    result = merge_streams([*first.streams, second.streams[1]], teams=game.teams)
    assert result.offsets == pytest.approx([0.0, -5.0, 8.0], abs=0.25)
    sources = [first.sources[0], first.sources[1], second.sources[1]]
    groups = [{sources[k][j] for k, j in enumerate(pair) if j is not None} for pair in result.pairs]
    members = [sum(j is not None for j in pair) for pair in result.pairs]
    assert sum(len(g) == 1 for g, n in zip(groups, members) if n > 1) / sum(n > 1 for n in members) >= 0.98
    assert abs(len(result.stream.events) - len(truth)) <= 4
    assert sum(n == 3 for n in members) >= 0.6 * len(truth)  # 0.9^3 of events are reported by all three


def test_known_values_and_roster_names_win(game: yus.Game):
    a = stream(throw(0, "white", "Tristan Weber", "glasses", type=ultimate.ThrowType.FLICK), throw(3, "black", "Adam Federbusch", "George Abuhamad"))
    b = stream(throw(0.4, "light", "Tristan Weber", "Ari Weissman", hit_wall=True), throw(3.3, "dark", "Adam Federbusch", "Zach Ehler"))
    result = merge_streams([a, b], teams=game.teams, offsets=[0.0, 0.0])
    assert result.pairs == [[0, 0], [1, 1]]
    first, second = result.stream.events
    assert isinstance(first, indoor.Throw) and isinstance(second, indoor.Throw)
    assert (first.team, first.receiver, first.type, first.hit_wall) == ("Dump & Drizzle", "Ari Weissman", "flick", True)  # roster beats label
    assert second.receiver == "George Abuhamad"  # two roster players: the earliest stream wins
    assert [(c.event, c.field, c.values, c.chosen, c.rule) for c in result.conflicts] == [
        (0, "receiver", ["glasses", "Ari Weissman"], "Ari Weissman", "roster"),
        (1, "receiver", ["George Abuhamad", "Zach Ehler"], "George Abuhamad", "earliest"),
    ]
    focused = merge_streams([a, b], teams=game.teams, offsets=[0.0, 0.0], focus=[None, "black"])  # any name of the team
    assert focused.stream.events[1].receiver == "Zach Ehler" and focused.conflicts[1].rule == "focus"


def test_the_majority_wins(game: yus.Game):
    streams = [stream(throw(t, "white", "Tristan Weber", receiver)) for t, receiver in ((0, "Kaia Mann"), (0.3, "Emily Kraus"), (-0.2, "Emily Kraus"))]
    result = merge_streams(streams, teams=game.teams, offsets=[0.0, 0.0, 0.0])
    assert result.pairs == [[0, 0, 0]]
    assert result.stream.events[0].receiver == "Emily Kraus" and result.conflicts[0].rule == "majority"


def test_grammar_repairs_what_one_commentator_got_wrong(game: yus.Game):
    a = stream(
        throw(0, "white", "Kaia Mann", "Joe Oaks"),  # completed, but black's Defense follows
        defense(1.5, "black", "Adam Federbusch"),
        throw(10, "black", "Adam Federbusch", "George Abuhamad", scored=True),  # scored, but black throws on
        throw(12, "black", "George Abuhamad", "Zach Ehler", scored=True),
    )
    result = merge_streams([a], teams=game.teams)
    events = result.stream.events
    assert (events[0].completed, events[2].scored, events[3].scored) == (False, False, True)
    assert [(c.event, c.field, c.values, c.chosen, c.rule) for c in result.conflicts] == [(0, "completed", [True], False, "grammar"), (2, "scored", [True], False, "grammar")]
    assert merge_streams([a], repair=False).stream.events == a.events
    agreed = merge_streams([a, stream(a.events[2].model_copy())], teams=game.teams)  # two commentators saw the score: an event between was missed
    assert agreed.stream.events[2].scored and not [c for c in agreed.conflicts if c.event == 2]


def heard_as_two(truth: list[yus.Event], gap: float, completed: bool = True) -> tuple[yus.EventStream, yus.EventStream, int]:
    """Two commentators of the ground-truth game, as in the end-to-end runs: white's goal at 154 s ("flick huck to kaia in the
    end zone for a score") was "Flick hot to Kaia Mann" for the white-focus commentator, a catch by "hot" and hot's throw to
    Kaia `gap` seconds later, which the extractor took as dropped since black picked up next; the dark-focus commentator's
    "Flick hock Kaia Mann. And the end's on first score" was the score. The second clock is 5 s ahead."""
    goal = next(i for i, e in enumerate(truth) if isinstance(e, ultimate.Throw) and e.scored and e.when.time() == datetime.time(20, 33, 7))
    a, b = list(truth), [e.model_copy(update={"when": e.when + datetime.timedelta(seconds=5), "team": B_TEAMS[getattr(e, "team")]}) for e in truth]
    split = {"when": truth[goal].when + datetime.timedelta(seconds=gap), "player": "hot", "receiver": "Kaia Mann", "completed": False, "scored": False}
    a[goal : goal + 1] = [truth[goal].model_copy(update={"receiver": "hot", "completed": completed, "scored": False}), truth[goal].model_copy(update=split)]
    b[goal] = b[goal].model_copy(update={"receiver": "hock"})
    return stream(*a), stream(*b), goal


def goals(events: list[yus.Event]) -> list[int]:
    return [sum(getattr(e, "scored", False) and normalize(getattr(e, "team")) in names for e in events) for names in ({"white", "dump and drizzle"}, {"black", "category 5"})]


def test_a_score_one_commentator_heard_stands(game: yus.Game, truth: list[yus.Event]):
    def merged(a: yus.EventStream, b: yus.EventStream) -> MergeResult:
        return merge_streams([a, b], focus=["white", "dark"], teams=game.teams, offsets=[0.0, -5.0])

    a, b, goal = heard_as_two(truth, 0.56)
    result = merged(a, b)
    assert goals(result.stream.events) == goals(truth) == [14, 9]
    assert [(c.field, c.values, c.chosen, c.rule) for c in result.conflicts if c.event == goal][-1] == ("scored", [False, True], True, "score")
    assert result.stream.events[goal + 1].player == "hot"  # the throw heard twice stays, as heard
    assert merged(a, stream(*b.events[: goal + 1])).stream.events[goal].scored is False  # the dark-focus commentator's next event isn't in yet
    later = merged(*heard_as_two(truth, 2.0)[:2])  # 2 s later, hot's throw is likelier real, and the dark-focus commentator missed it
    assert goals(later.stream.events) == [13, 9]
    dropped = merged(*heard_as_two(truth, 0.56, completed=False)[:2])  # the white-focus commentator said it was dropped
    assert goals(dropped.stream.events) == [13, 9] and ("scored", "focus") in [(c.field, c.rule) for c in dropped.conflicts if c.event == goal]


def test_a_score_heard_as_two_settles_when_its_reporter_goes_on(game: yus.Game, truth: list[yus.Event]):
    """Whether the score stands depends on the reporter's next event: here the dark-focus commentator, 15 s behind, says
    nothing more until black scores 15 s later. Meanwhile, the score is not settled, though `settle` alone would settle it."""
    a, b, goal = heard_as_two(truth, 0.56)
    b = stream(*(e for k, e in enumerate(b.events) if k <= goal or getattr(e, "scored", False) or e.when > b.events[goal].when + datetime.timedelta(seconds=20)))
    final = merge_streams([a, b], focus=["white", "dark"], teams=game.teams, offsets=[0.0, -5.0])
    assert final.stream.events[goal].scored and final.settled > goal
    held = 0
    for until in range(150, 260):
        prefix = [stream(*(e for e in s.events if (e.when - truth[0].when).total_seconds() <= until - late)) for s, late in ((a, 0), (b, 5 + 15))]
        result = merge_streams(prefix, focus=["white", "dark"], teams=game.teams, offsets=[0.0, -5.0])
        assert result.stream.events[: result.settled] == final.stream.events[: result.settled], until
        held += result.settled == goal and not result.stream.events[goal].scored
    assert held >= 2  # measured 2: settled stops before it until the reporter goes on


def test_a_defense_goes_after_the_throw_it_stopped(game: yus.Game):
    a = stream(throw(0, "white", "Kaia Mann", "Joe Oaks", completed=False), throw(8, "black", "Adam Federbusch", "George Abuhamad"))
    b = stream(defense(-0.4, "dark", "Zach Ehler"))  # said a little early
    result = merge_streams([a, b], teams=game.teams, offsets=[0.0, 0.0])
    assert [type(e).__name__ for e in result.stream.events] == ["Throw", "Defense", "Throw"]
    assert result.pairs == [[0, None], [None, 0], [1, None]]
    assert [e.when for e in result.stream.events] == sorted(e.when for e in result.stream.events)


def test_links_suggest_descriptions(game: yus.Game, truth: list[yus.Event]):
    commentary = commentate(truth, "dual", 0, offset=6.0)
    links = {(link.stream, link.team, link.name): link.same_as for link in merge_streams(commentary.streams, teams=game.teams).links}
    assert links[(1, "light", "specs")] == "glasses" and links[(1, "dark", "yellow shirt")] == "yellow sleeve"
    assert all(name in B_LABELS.values() for _, _, name in links)


def test_result_round_trips_through_json(game: yus.Game, truth: list[yus.Event]):
    commentary = commentate(truth, "split", 1, offset=5.0)
    result = merge_streams(commentary.streams, focus=commentary.focus, teams=game.teams)
    loaded = MergeResult.model_validate_json(result.model_dump_json())
    assert loaded.model_dump(mode="json") == result.model_dump(mode="json")
    assert type(loaded.stream.events[0]) is indoor.Throw


@pytest.mark.parametrize("mode", ["dual", "split"])
def test_settled_events_stay_as_events_arrive(game: yus.Game, truth: list[yus.Event], mode: str):
    """Re-merging the streams so far, with the same offsets, gives the final result for every event it says is settled, even
    when one commentator's events arrive seconds after the other's (either way round)."""
    took, settled, merged = [], 0, 0
    for seed, lags in ((3, [0.0, 6.0]), (4, [10.0, 0.0]), (5, [0.0, 16.0])):
        commentary = commentate(truth, mode, seed, offset=4.0 + seed)
        final = merge_streams(commentary.streams, focus=commentary.focus, teams=game.teams)
        before = 0
        for until in range(0, 990, 4):
            prefix = arriving(commentary, until, lags)
            start = time.perf_counter()
            result = merge_streams(prefix, focus=commentary.focus, teams=game.teams, offsets=final.offsets)
            took.append(time.perf_counter() - start)
            n = result.settled
            assert result.stream.events[:n] == final.stream.events[:n] and result.pairs[:n] == final.pairs[:n], (seed, until)
            assert [c for c in result.conflicts if c.event < n] == [c for c in final.conflicts if c.event < n], (seed, until)
            assert result.provisional == [i >= n for i in range(len(result.stream.events))]
            assert n >= before, (seed, until)  # settled events stay settled
            before, settled, merged = n, settled + n, merged + len(result.stream.events)
    assert settled >= 0.9 * merged  # measured 0.93: all but the last ~30 s
    assert statistics.median(took) < 0.02  # measured: 2 ms median, 5 ms for the whole game


def test_a_slower_stream_cannot_change_settled_events(game: yus.Game):
    """A throw's outcome depends on the next throw, which a slower commentator may report later: a goal followed by the same
    team's throw looks like a catch until the other team's throw between them arrives."""
    a = stream(throw(0, "white", "Kaia Mann", "Joe Oaks", scored=True), *(throw(21 + 3 * n, "white", "Joe Oaks", "Kaia Mann") for n in range(20)))
    b = stream(throw(18, "black", "Adam Federbusch", "Zach Ehler", completed=False))
    final = merge_streams([a, b], teams=game.teams, offsets=[0.0, 0.0])
    assert final.stream.events[0].scored and final.settled > 0
    for n in range(1, len(a.events) + 1):  # b's event arrives once a has reported up to `settle` seconds past it
        late = a.events[n - 1].when - b.events[0].when <= datetime.timedelta(seconds=20)
        result = merge_streams([stream(*a.events[:n]), stream() if late else b], teams=game.teams, offsets=[0.0, 0.0])
        assert result.stream.events[: result.settled] == final.stream.events[: result.settled], n


def test_estimated_offsets_settle_nothing_they_could_move(truth: list[yus.Event]):
    official = yus.EventStream(events=truth)
    assert merge_streams([official]).settled > 0.8 * len(truth)
    shifted = yus.EventStream(events=[e.model_copy(update={"when": e.when + datetime.timedelta(seconds=7.3)}) for e in truth])
    assert merge_streams([official, shifted]).settled == 0  # more events could move the estimated offset, and every pair with it
    assert merge_streams([official, shifted], offsets=[0.0, -7.3]).settled > 0.8 * len(truth)


def live(commentary: Commentary, game: yus.Game, lags: list[float], step: int = 5) -> tuple[LiveMerger, list[MergeResult]]:
    """A LiveMerger's results as the commentators' events arrive, every `step` seconds; each result's settled events must be the
    final result's, and settled events stay settled."""
    merger = LiveMerger(focus=commentary.focus, teams=game.teams)
    results = [merger.merge(arriving(commentary, until, lags)) for until in range(0, 960 + int(max(lags)) + step, step)]
    final = results[-1]
    for until, result in enumerate(results):
        n = result.settled
        assert result.stream.events[:n] == final.stream.events[:n] and result.pairs[:n] == final.pairs[:n], until * step
        assert until == 0 or n >= results[until - 1].settled, until * step
    return merger, results


def test_live_merger_keeps_offsets_and_settled_events(game: yus.Game, truth: list[yus.Event]):
    commentary = commentate(truth, "dual", 5, offset=9.0)
    merger, results = live(commentary, game, [0.0, 1.0])
    assert results[0].settled == 0 and abs(merger.offsets[1] + 9.0) < 0.3
    assert next(i for i, r in enumerate(results) if r.settled) * 5 <= 120  # the offset is kept after 10 pairs (measured 55 s median)
    measured = measure(results[-1], commentary, truth, game.teams)
    assert measured["precision"] >= 0.98 and measured["recall"] >= 0.97


# Over 24 seeds of split coverage, the offset kept after 10 pairs was up to 0.98 s off (2.3 s before offset candidates were
# compared by how well they pair), costing up to 0.08 pairing recall against a batch merge; re-estimating it for later events
# brings the final offset within 0.47 s and the cost to 0.05 at worst (0.003 on average). Seeds 10 and 14 were the worst.
@pytest.mark.parametrize("seed", [10, 14])
def test_live_merger_corrects_the_offset_for_later_events(game: yus.Game, truth: list[yus.Event], seed: int):
    commentary = commentate(truth, "split", seed, offset=4 + seed % 8)
    merger, results = live(commentary, game, [0.0, 1.0])
    segments = merger.segments[1]
    assert segments is not None and len(segments) > 1 and abs(segments[0][1] + commentary.offset) < 1.0
    assert abs(merger.offsets[1] + commentary.offset) < 0.3  # measured 0.23, 0.13
    batch = measure(merge_streams(commentary.streams, focus=commentary.focus, teams=game.teams), commentary, truth, game.teams)
    measured = measure(results[-1], commentary, truth, game.teams)
    assert measured["precision"] >= batch["precision"] - 0.05 and measured["recall"] >= batch["recall"] - 0.05  # measured -0.043, +0.044


def test_live_merger_with_a_commentator_who_starts_late(game: yus.Game, truth: list[yus.Event]):
    """The second commentator reports from 200 s on, and the first lags 10 s behind: the first's events settle meanwhile, and
    none of them changes when the second starts."""
    commentary = commentate(truth, "dual", 6, offset=10.0)
    start = commentary.streams[0].events[0].when + datetime.timedelta(seconds=200 + commentary.offset)
    keep = [i for i, e in enumerate(commentary.streams[1].events) if e.when >= start]
    late = Commentary(
        [commentary.streams[0], stream(*(commentary.streams[1].events[i] for i in keep))], [commentary.sources[0], [commentary.sources[1][i] for i in keep]], 10.0, commentary.focus
    )
    merger, results = live(late, game, [10.0, 0.0])
    assert results[30].settled > 0  # by 150 s, before the second commentator starts
    assert abs(merger.offsets[1] + 10.0) < 0.3
    assert measure(results[-1], late, truth, game.teams)["precision"] >= 0.98


def test_mixed_naive_and_utc_offset_times(game: yus.Game):
    a = stream(throw(0, "white", "Kaia Mann", "Joe Oaks"), throw(3, "white", "Joe Oaks", "Kaia Mann"))
    zone = datetime.timezone(datetime.timedelta(hours=-7))
    b = yus.EventStream(events=[e.model_copy(update={"when": e.when.replace(tzinfo=zone) + datetime.timedelta(seconds=0.4)}) for e in a.events])
    result = merge_streams([a, b], teams=game.teams, offsets=[0.0, 0.0])
    assert result.pairs == [[0, 0], [1, 1]]
    assert [e.when for e in result.stream.events] == [e.when + datetime.timedelta(seconds=0.2) for e in a.events]  # naive, local time
    assert merge_streams([b, b]).stream.events[0].when == b.events[0].when  # all with offsets: kept


def test_a_tie_goes_to_the_earliest_stream_among_the_tied(game: yus.Game):
    receivers = ["Kaia Mann", "Emily Kraus", "Emily Kraus", "Joe Oaks", "Joe Oaks"]
    streams = [stream(throw(0.1 * k, "white", "Tristan Weber", receiver)) for k, receiver in enumerate(receivers)]
    result = merge_streams(streams, teams=game.teams, offsets=[0.0] * 5)
    assert result.pairs == [[0] * 5]
    assert result.stream.events[0].receiver == "Emily Kraus" and result.conflicts[0].rule == "earliest"


def test_merged_events_are_copies(game: yus.Game):
    a = stream(throw(0, "white", "Kaia Mann", "Joe Oaks"))
    result = merge_streams([a])
    assert result.stream.events == a.events and result.stream.events[0] is not a.events[0]
    result.stream.events[0].receiver = "Emily Kraus"
    assert a.events[0].receiver == "Joe Oaks"


def test_a_throw_pairs_with_its_indoor_variant(game: yus.Game):
    a = stream(ultimate.Throw(when=T0, team="white", player="Kaia Mann", receiver=None, completed=True, scored=False))
    b = stream(throw(0.3, "light", "Kaia Mann", "Joe Oaks", hit_wall=True))
    result = merge_streams([a, b], teams=game.teams, offsets=[0.0, 0.0])
    assert result.pairs == [[0, 0]]
    merged = result.stream.events[0]
    assert type(merged) is indoor.Throw and (merged.receiver, merged.hit_wall) == ("Joe Oaks", True)
    assert len(merge_streams([a, stream(defense(0.3, "white", "Kaia Mann"))], offsets=[0.0, 0.0]).pairs) == 2  # a Throw never pairs with a Defense


def test_focus_must_name_a_team(game: yus.Game):
    a = stream(throw(0, "white", "Kaia Mann", "Joe Oaks"))
    with pytest.raises(ValueError, match="purple"):
        merge_streams([a, a], teams=game.teams, focus=["purple", None])
    assert merge_streams([a, a], focus=["purple", None]).pairs == [[0, 0]]  # without teams, focus can't be checked
