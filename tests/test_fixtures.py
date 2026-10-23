import json
import pathlib

import pydantic
import pytest

import yus
from tests.data.gruindoor_20250114T2030 import build_game
from tests.data.regenerate_fixtures import fixture_texts
from yus.sports import ultimate
from yus.sports.ultimate import indoor

DATA = pathlib.Path(__file__).parent / "data"


def test_json_fixtures_match_python_ground_truth():
    for path, text in fixture_texts().items():
        assert path.read_text() == text, f"{path.name} is stale; run: python -m tests.data.regenerate_fixtures"


def test_event_stream_round_trips_subclasses():
    raw = build_game().event_streams[0]
    loaded = yus.EventStream.model_validate(json.loads(json.dumps(raw.model_dump(mode="json"))))
    assert loaded.events == raw.events
    assert {type(evt) for evt in loaded.events} == {indoor.Throw, ultimate.Defense}


def test_event_stream_json_keeps_subclass_fields():
    stream = yus.EventStream(events=[ultimate.Defense(when="2025-01-14T20:31:34.35", team="black", player="hat", intercepted=True)])
    assert stream.model_dump(mode="json")["events"] == [
        {"when": "2025-01-14T20:31:34.350000", "team": "black", "player": "hat", "intercepted": True, "__type__": "ultimate.Defense"}
    ]


def test_unknown_event_type_is_rejected():
    with pytest.raises(pydantic.ValidationError, match="Unknown event type 'nope.Thing'"):
        yus.EventStream.model_validate({"events": [{"when": "2025-01-14T20:31:00", "__type__": "nope.Thing"}]})


def test_events_are_in_time_order():
    events = build_game().event_streams[0].events
    assert [evt.when for evt in events] == sorted(evt.when for evt in events)


def test_event_times_are_word_start_times():
    game = build_game()
    starts = {word.start for word in game.transcripts[0].words}
    assert all(evt.when in starts for evt in game.event_streams[0].events)


@pytest.mark.parametrize("path", sorted(DATA.glob("team_*.json")), ids=lambda p: p.name)
def test_team_files_validate(path: pathlib.Path):
    yus.Team.model_validate_json(path.read_text())


def test_team_files_reject_unknown_keys():
    with pytest.raises(pydantic.ValidationError):
        yus.Team.model_validate({"names": ["white"], "players": {"Kaia Mann": {"mondegreen": ["takaya"]}}})
