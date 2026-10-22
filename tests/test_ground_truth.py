"""Spot checks of hand-verified labels and timings in the gruindoor_20250114T2030 ground truth."""

import datetime

import pytest

import yus
from tests.data.gruindoor_20250114T2030 import TEAM_FILES, build_game
from yus.sports import ultimate
from yus.sports.ultimate import indoor

T0 = datetime.datetime(2025, 1, 14, 20, 30, 33)  # audio t=0


@pytest.fixture(scope="module")
def game() -> yus.Game:
    return build_game()


def offset(when: datetime.datetime) -> float:
    return round((when - T0).total_seconds(), 2)


def test_rosters_come_from_team_files(game: yus.Game):
    assert game.teams == [yus.Team.model_validate_json(path.read_text()) for path in TEAM_FILES]
    assert [team.names[0] for team in game.teams] == ["Dump & Drizzle", "Category 5"]


@pytest.mark.parametrize(
    "index, field, value",
    [
        (35, "direction", ultimate.ThrowDirection.HUCK),  # "hammer put to the end zone" / "caught by george for a score"
        (53, "receiver", "hat"),  # "backhand in the end zone caught by hat"
        (94, "type", ultimate.ThrowType.BACKHAND),  # "backhand to bluey"
        (94, "direction", None),
        (111, "direction", None),  # "backhand to kaia swing": the trailing "swing" belongs to the next throw...
        (112, "direction", ultimate.ThrowDirection.SWING),  # ..."flick to close crop swing"
        (113, "direction", ultimate.ThrowDirection.SWING),  # ..."backhand to pikachu"
        (134, "player", "kid"),  # "kid picks it up for white"
        (165, "receiver", "stephen"),  # "flick to stephen"
        (166, "player", "stephen"),
    ],
)
def test_raw_labels(game: yus.Game, index: int, field: str, value: object):
    assert getattr(game.event_streams[0].events[index], field) == value


def test_raw_names_are_spelled_as_transcribed(game: yus.Game):
    raw, unified = game.event_streams[0], game.official_stream
    assert unified is not None
    names = {getattr(evt, field, None) for evt in raw.events for field in ("player", "receiver") if isinstance(evt, (indoor.Throw, ultimate.Defense))}
    assert "federbusch" in names and "federbush" not in names
    spoken = {word.text for word in game.transcripts[0].words}
    assert all(word in spoken for name in names - {None} for word in name.split())
    assert {unified.events[i].player for i, evt in enumerate(raw.events) if evt.player in ("federbusch", "bush")} == {"Adam Federbusch"}


@pytest.mark.parametrize(
    "group, text, starts",
    [
        (5, "backhand to close crop", [51.8, 52.4, 52.7, 53.0]),
        (7, "backhand swing to glasses", [58.8, 59.4, 59.7, 60.0]),
        (8, "flick to kaia deed by somebody on dark", [63.5, 63.8, 64.1, 64.85, 65.85, 66.15, 67.05, 67.35]),
        (11, "backhand to yellow border", [75.45, 78.5, 78.8, 79.4]),
        (12, "backhand federbusch to naked for a score", [83.1, 85.45, 87.9, 88.2, 88.8, 89.1, 89.4]),
        (15, "backhand to joe", [93.9, 94.5, 94.8]),
        (16, "joe big flick huck off the wall no score", [96.9, 97.2, 97.5, 97.8, 101.1, 101.4, 101.7, 102.0, 102.3]),
        (71, "backhand in the end zone caught by hat", [289.8, 290.4, 290.7, 291.0, 291.3, 293.1, 293.4, 293.7]),
        (198, "backhand bobbled and dropped by hat no score", [763.4, 765.75, 766.35, 766.65, 767.19, 767.49, 767.79, 768.09]),
        (225, "flick huck deed by gloves no score", [885.5, 885.8, 888.2, 888.5, 888.8, 889.1, 889.4]),
    ],
)
def test_retimed_groups(game: yus.Game, group: int, text: str, starts: list[float]):
    interp = game.transcripts[0].groups[group].interpretations[0]
    assert interp.transcript == text
    assert [offset(word.start) for word in interp.words] == starts


@pytest.mark.parametrize(
    "index, when",
    [(2, 51.8), (4, 58.8), (5, 63.5), (6, 64.85), (8, 75.45), (9, 83.1), (10, 87.9), (11, 91.4), (12, 93.9), (13, 97.2), (53, 289.8), (183, 888.2)],
)
def test_retimed_events(game: yus.Game, index: int, when: float):
    assert offset(game.event_streams[0].events[index].when) == when


def test_retimed_groups_do_not_overlap_neighbors(game: yus.Game):
    groups = game.transcripts[0].groups
    words = game.transcripts[0].words
    assert [word.start for word in words] == sorted(word.start for word in words)
    for i in [4, 5, 6, 7, 8, 10, 11, 12, 14, 15, 16, 70, 71, 197, 198, 199, 224, 225]:
        assert groups[i].start + groups[i].duration <= groups[i + 1].start, f"group {i} overlaps group {i + 1}"
