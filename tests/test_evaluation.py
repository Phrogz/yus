"""Tests for the event scorer (yus.processing.evaluation, the yus-score tool)."""

import datetime as dt
import json
import pathlib

import pytest

import yus
from tests.data.gruindoor_20250114T2030 import build_game
from yus.processing import evaluation
from yus.processing.evaluation import load_events, naive_clock, parse_time, score
from yus.processing.event_unification import GameDescriptions, PlayerResolver
from yus.sports import ultimate
from yus.sports.ultimate import indoor

DATA = pathlib.Path(__file__).parent / "data"
TRUTH = DATA / "gruindoor_20250114T2030-eventstream.json"
T0 = dt.datetime(2025, 1, 14, 20, 30, 47, 600000)  # first word of the transcript
SPLIT = dt.datetime(2025, 1, 14, 20, 38, 30, 900000)  # dev: before, test: after (463.3 s after T0)
NOW = dt.datetime(2025, 1, 1, 12)
MST = dt.timezone(dt.timedelta(hours=-7))


@pytest.fixture(scope="module")
def game() -> yus.Game:
    return build_game()


@pytest.fixture(scope="module")
def truth(game: yus.Game) -> list[yus.Event]:
    return game.event_streams[0].events


def throw(seconds: float, player: str | None = "kaia", receiver: str | None = "tristan", team: str = "white", **fields: object) -> indoor.Throw:
    values: dict = {"type": None, "completed": True, "scored": False} | fields
    return indoor.Throw(when=NOW + dt.timedelta(seconds=seconds), team=team, player=player, receiver=receiver, **values)


def defense(seconds: float, player: str | None = "george", team: str = "black", intercepted: bool = False) -> ultimate.Defense:
    return ultimate.Defense(when=NOW + dt.timedelta(seconds=seconds), team=team, player=player, intercepted=intercepted)


def test_truth_against_itself_is_perfect(truth: list[yus.Event]):
    result = score(truth, TRUTH)  # objects and a JSON file load alike
    assert (result.overall.f1, result.exact.f1, result.exact_rate) == (1.0, 1.0, 1.0)
    assert result.overall.tp == len(truth) == 200
    assert {kind: s.f1 for kind, s in result.per_type.items()} == {"Throw": 1.0, "Defense": 1.0}
    assert all(s.accuracy == 1.0 for s in result.fields.values() if s.total)
    assert result.timing.max_abs == 0.0 and not result.misses and not result.false_positives and not result.warnings


def test_split_windows(truth: list[yus.Event]):
    dev = score(truth, truth, stop=SPLIT)
    test = score(truth, truth, start=SPLIT)
    assert (dev.overall.tp, test.overall.tp) == (96, 104)
    assert score(truth, truth, start=463.3, t0=T0).overall.tp == 104  # seconds after t0
    assert score(truth, truth, stop="20:38:30.9", t0=T0).overall.tp == 96  # a clock time on t0's date
    inside = sum(SPLIT <= event.when < dt.datetime(2025, 1, 14, 20, 40) for event in truth)
    assert score(truth, truth, start="2025-01-14T20:38:30.9", stop="2025-01-14T20:40:00").overall.tp == inside == 20
    assert test.start == SPLIT and test.stop is None


def test_parse_time():
    assert parse_time(1.5, NOW) == NOW + dt.timedelta(seconds=1.5)
    assert parse_time("1.5", NOW) == NOW + dt.timedelta(seconds=1.5)
    assert parse_time("12:00:03", NOW) == NOW + dt.timedelta(seconds=3)
    assert parse_time("2025-01-01T12:00:03-07:00", NOW) == dt.datetime(2025, 1, 1, 12, 0, 3, tzinfo=MST)  # the offset is kept
    clock = naive_clock([dt.datetime(2025, 1, 1, tzinfo=MST)])
    assert parse_time("2025-01-01T19:00:03Z", NOW, clock) == NOW + dt.timedelta(seconds=3)  # ... or converted by a clock
    assert parse_time(dt.datetime(2025, 1, 1, 12, tzinfo=MST), NOW, clock) == NOW
    with pytest.raises(ValueError, match="Cannot parse time"):
        parse_time("soon", NOW)


def test_a_missing_event_is_a_miss_and_an_extra_one_a_false_positive(truth: list[yus.Event]):
    dropped = score(truth[:10] + truth[11:], truth)
    assert (dropped.overall.tp, dropped.overall.fn, dropped.overall.fp) == (199, 1, 0)
    assert dropped.overall.recall == pytest.approx(199 / 200) and dropped.overall.precision == 1.0
    assert [m.index for m in dropped.misses] == [10]
    extra = score([*truth, throw(0)], truth)
    assert (extra.overall.fp, extra.overall.fn) == (1, 0) and extra.false_positives[0].fields["player"] == "kaia"


def test_a_wrong_field_breaks_exactness_but_not_the_pairing(truth: list[yus.Event]):
    changed = [event.model_copy(update={"receiver": "somebody else"}) if i == 0 else event for i, event in enumerate(truth)]
    result = score(changed, truth)
    assert result.overall.f1 == 1.0
    assert result.exact.tp == 199 and result.exact.f1 == pytest.approx(199 / 200)
    assert result.fields["receiver"].correct == result.fields["receiver"].total - 1
    assert result.matches[0].mismatches == {"receiver": ("glasses", "somebody else")}


def test_tolerance_decides_whether_shifted_events_pair():
    truth = [throw(0), throw(10)]
    near = score([throw(2.5), throw(10)], truth)
    assert near.overall.tp == 2 and near.timing.max_abs == pytest.approx(2.5)
    far = score([throw(3.5), throw(10)], truth)
    assert (far.overall.tp, far.overall.fp, far.overall.fn) == (1, 1, 1)
    assert score([throw(3.5), throw(10)], truth, tolerance=4).overall.tp == 2


def test_types_must_match_and_alignment_keeps_order():
    assert score([defense(0)], [throw(0)]).overall.tp == 0
    # Pairing crosswise would match both receivers, but pairs may not cross in time: the earlier events pair, the later ones pair.
    result = score([throw(0, receiver="a"), throw(1, receiver="b")], [throw(0.9, receiver="b"), throw(1.8, receiver="a")])
    assert result.overall.tp == 2 and result.exact.tp == 0
    # Among pairings with the most pairs, the one with the fewest field mismatches wins.
    best = score([throw(1, receiver="b")], [throw(0, receiver="a"), throw(2, receiver="b")])
    assert best.exact.tp == 1 and best.misses[0].fields["receiver"] == "a"


def test_strict_type_compares_the_full_tag():
    plain = ultimate.Throw(when=NOW, team="white", player="kaia", receiver="tristan", completed=True, scored=False)
    assert score([plain], [throw(0)]).overall.tp == 1
    assert score([plain], [throw(0)], strict_type=True).overall.tp == 0


def test_names_compare_as_the_resolver_does():
    truth = [throw(0, player="kid", receiver=None)]
    assert score([throw(0, player="The Kid", receiver="somebody")], truth).exact.tp == 1
    assert score([throw(0, player="Kid's", receiver="unknown")], truth).exact.tp == 1
    assert score([throw(0, player="kidd", receiver=None)], truth).exact.tp == 0


def test_team_names_are_synonyms_when_teams_are_given(game: yus.Game):
    truth = [throw(0, team="black")]
    assert score([throw(0, team="dark")], truth).exact.tp == 0
    assert score([throw(0, team="dark")], truth, teams=game.teams).exact.tp == 1
    assert score([throw(0, team="Category 5")], truth, teams=game.teams).exact.tp == 1
    assert score([throw(0, team="white")], truth, teams=game.teams).exact.tp == 0


def test_resolve_maps_names_on_both_sides(game: yus.Game, truth: list[yus.Event]):
    spoken = [throw(0, player="bush", receiver="naked", team="black"), throw(5, player="the kid", receiver="kaia", team="white")]
    official = [throw(0, player="Adam Federbusch", receiver="Collin Ruprecht", team="black"), throw(5, player="Serayan Knappe-Butler", receiver="Kaia Mann")]
    assert score(spoken, official).exact.tp == 0
    rosters = score(spoken, official, resolve=PlayerResolver(game.teams))
    assert rosters.exact.tp == 0 and rosters.fields["player"].correct == 1  # "bush" is a roster mondegreen; "the kid" is a description
    descriptions = GameDescriptions.model_validate_json((DATA / "gruindoor_20250114T2030-descriptions.json").read_text())
    resolver = PlayerResolver(game.teams, descriptions)
    assert score(spoken, official, resolve=resolver).exact.tp == 2
    anonymous = score(spoken, official, resolve=lambda event: event.model_copy(update={"player": "x", "receiver": "y"}))
    assert anonymous.exact.tp == 2  # any event -> event function works
    unified = game.official_stream
    assert unified is not None
    assert score(truth, unified, resolve=resolver).exact.f1 == 1.0  # resolving the raw ground truth gives the unified one


def test_load_events_accepts_files_lists_and_json_lines(tmp_path: pathlib.Path, truth: list[yus.Event]):
    stream = yus.EventStream(events=truth[:3]).model_dump(mode="json")
    (tmp_path / "stream.json").write_text(json.dumps(stream))
    (tmp_path / "list.json").write_text(json.dumps(stream["events"]))
    (tmp_path / "lines.jsonl").write_text("\n".join(json.dumps(e) for e in stream["events"]))
    for name in ("stream.json", "list.json", "lines.jsonl"):
        assert load_events(tmp_path / name) == truth[:3]
    assert load_events(yus.EventStream(events=truth[:3])) == truth[:3]
    untagged = [{k: v for k, v in e.items() if k != "__type__"} for e in stream["events"]]
    assert load_events(untagged) == truth[:3]  # the type is inferred from the fields
    warnings: list[str] = []
    assert load_events([{"when": "2025-01-14T20:31:00", "__type__": "nope.Thing"}, stream["events"][0]], warnings) == truth[:1]
    assert "Unknown event type 'nope.Thing'" in warnings[0]


def test_report_lists_details_when_verbose(truth: list[yus.Event]):
    result = score(truth[1:], truth, t0=T0)
    assert "OVERALL" in result.report() and "MISSES" not in result.report()
    verbose = result.report(verbose=True)
    assert "MISSES (true events with no prediction): 1" in verbose and "player=pikachu" in verbose


def test_cli(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str], truth: list[yus.Event]):
    predicted = tmp_path / "pred.json"
    changed = [e.model_copy(update={"team": "dark"}) if getattr(e, "team", None) == "black" else e for e in truth]
    predicted.write_text(yus.EventStream(events=changed).model_dump_json())
    assert evaluation.main([str(predicted), "--json", "--start", "463.3"]) == 0  # bundled truth, its teams and t0 by default
    result = json.loads(capsys.readouterr().out)
    assert result["overall"]["tp"] == 104 and result["exact"]["f1"] == 1.0 and "matches" not in result
    assert evaluation.main([str(predicted), "--gt", str(TRUTH), "--team", str(DATA / "team_dump_and_drizzle.json"), "--stop", "463.3"]) == 0
    assert "OVERALL" in capsys.readouterr().out  # with only white's team file, "dark" and "black" differ
    assert evaluation.main([str(predicted), "--descriptions", str(DATA / "gruindoor_20250114T2030-descriptions.json"), "-v"]) == 0
    assert "FIELD MISMATCHES (paired events with a differing field): 0" in capsys.readouterr().out
    replayed = tmp_path / "replayed.json"  # a live replay of the recording, timed on the day it was replayed
    replayed.write_text(yus.EventStream(events=[e.model_copy(update={"when": e.when + dt.timedelta(days=640, seconds=3.5)}) for e in truth]).model_dump_json())
    assert evaluation.main([str(replayed), "--json", "--shift", "2026-10-16T20:31:00.5", "2025-01-14T20:30:57"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["exact"]["f1"] == 1.0 and result["timing"]["max_abs"] == 0.0
    assert evaluation.main([str(replayed), "--json"]) == 0 and json.loads(capsys.readouterr().out)["overall"]["tp"] == 0


def test_times_with_and_without_utc_offsets_compare():
    local = throw(0)
    offset = local.model_copy(update={"when": local.when.replace(tzinfo=MST)})
    utc = local.model_copy(update={"when": offset.when.astimezone(dt.timezone.utc)})
    for predicted, truth in [([offset], [offset]), ([local], [offset]), ([offset], [local]), ([utc], [offset])]:
        result = score(predicted, truth)
        assert result.overall.tp == 1 and result.t0 == NOW and result.t0.tzinfo is None  # naive times are the offset times' local time
    assert score([offset], [offset], start=NOW.replace(tzinfo=MST)).overall.tp == 1
    assert score([offset], [offset], start="2025-01-01T19:00:01Z").overall.tp == 0  # 12:00:01 local
    assert score([local], [local], stop="2025-01-01T12:00:01-07:00").overall.tp == 1
    assert score([local], [local], start=dt.datetime(2025, 1, 1, 12, 0, 1, tzinfo=MST)).overall.tp == 0


def test_a_field_missing_from_the_class_takes_its_default():
    plain = ultimate.Throw(when=NOW, team="white", player="kaia", receiver="tristan", completed=True, scored=False)
    assert score([plain], [throw(0)]).exact.tp == 1 and score([throw(0)], [plain]).exact.tp == 1  # hit_wall/hit_net: False
    assert score([plain], [throw(0, hit_wall=True)]).exact.tp == 0


def test_cli_errors(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]):
    (tmp_path / "pred.txt").write_text("not json\n")
    assert evaluation.main([str(tmp_path / "pred.txt")]) == 1
    assert "neither JSON nor JSON lines" in capsys.readouterr().err
    assert evaluation.main([str(tmp_path / "missing.json")]) == 1
    with pytest.raises(SystemExit):  # resolving needs rosters, and only the bundled ground truth brings its own
        evaluation.main([str(TRUTH), "--gt", str(tmp_path / "pred.txt"), "--descriptions", str(DATA / "gruindoor_20250114T2030-descriptions.json")])
    assert "need the teams' rosters" in capsys.readouterr().err
    (tmp_path / "bad-descriptions.json").write_text('{"players": [{"team": "nobody", "descriptions": ["x"]}]}')
    assert evaluation.main([str(TRUTH), "--descriptions", str(tmp_path / "bad-descriptions.json")]) == 1
    assert "No team is called 'nobody'" in capsys.readouterr().err
