import datetime as dt
import json
import os
import pathlib
import re

import pandas as pd
import pytest

import yus
from tests.data.gruindoor_20250114T2030 import build_game
from yus import game_cli
from yus.game_cli import clock, main, parse_source
from yus.processing.evaluation import score
from yus.processing.event_unification import GameDescriptions, PlayerDescription, PlayerResolver
from yus.session import GameSession, replay

DATA = pathlib.Path(__file__).parent / "data"
TRANSCRIPT = DATA / "gruindoor_20250114T2030-transcript.json"  # the hand-made transcript
WHISPER = DATA / "gruindoor_20250114T2030-whisper-turbo.json"
DESCRIPTIONS = DATA / "gruindoor_20250114T2030-descriptions.json"
TEAM_FILES = [DATA / "team_dump_and_drizzle.json", DATA / "team_category_5.json"]
TEAMS = ["--team", str(TEAM_FILES[0]), "--team", str(TEAM_FILES[1]), "--descriptions", str(DESCRIPTIONS)]
WHITE, BLACK = "Dump & Drizzle", "Category 5"


@pytest.fixture(scope="module")
def teams() -> list[yus.Team]:
    return [yus.Team.model_validate_json(path.read_text()) for path in TEAM_FILES]


@pytest.fixture(scope="module")
def transcript() -> yus.Transcript:
    return yus.Transcript.model_validate_json(TRANSCRIPT.read_text())


def run(tmp_path: pathlib.Path, *commentators: str, extra: tuple[str, ...] = ()) -> GameSession:
    """yus-game on these --commentator values into tmp_path/game; the saved game, loaded."""
    assert main([*TEAMS, "--game-dir", str(tmp_path / "game"), *extra, *(arg for c in commentators for arg in ("--commentator", c))]) == 0
    return GameSession.load(tmp_path / "game")


def other_commentator(transcript: yus.Transcript, seconds: float, drop: int, swap: dict[str, str] | None = None) -> yus.Transcript:
    """The same commentary from someone whose clock is `seconds` ahead, who misses every `drop`th group and says `swap`'s words."""
    other = yus.Transcript()
    for i, group in enumerate(transcript.groups):
        if i % drop != drop - 1:
            interpretation = other.add_group().add_interpretation(confidence=group.interpretations[0].confidence)
            for word in group.words:
                interpretation.add_word((swap or {}).get(word.text, word.text), start=word.start + dt.timedelta(seconds=seconds), duration=word.duration)
    return other


def save(path: pathlib.Path, transcript: yus.Transcript) -> str:
    path.write_text(transcript.model_dump_json())
    return str(path)


@pytest.mark.parametrize("path", [TRANSCRIPT, WHISPER], ids=["hand-made", "whisper"])
def test_one_commentator(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str], teams: list[yus.Team], path: pathlib.Path):
    loaded = run(tmp_path, f"Gavin Kistner={path}")
    out = capsys.readouterr().out
    snap = loaded.snapshot()
    assert snap.finished and snap.settled_count == len(snap.official.events) and [c.name for c in snap.commentators] == ["Gavin Kistner"]
    assert out.startswith(snap.summary)
    assert snap.official.events == yus.EventStream.model_validate_json((tmp_path / "game" / "official.json").read_text()).events

    descriptions = GameDescriptions.model_validate_json(DESCRIPTIONS.read_text())
    live = GameSession(yus.Game(sport="ultimate/indoor", when=dt.datetime(2025, 1, 14, 20, 30), teams=teams), descriptions)
    replay(live, path, "Gavin Kistner")
    live.finish()
    assert snap.official.events == live.snapshot().official.events and snap.score == live.snapshot().score  # as yus-serve would have it
    truth = build_game()
    assert score(snap.official, truth.official_stream, resolve=PlayerResolver(truth.teams, descriptions)).overall.f1 > 0.95
    assert sum(snap.score.values()) >= 22

    assert "Unresolved names" in out and "glasses" in out  # what a person should fix
    report = (tmp_path / "game" / "report.html").read_text()
    assert f"{WHITE.replace('&', '&amp;')} <b>{snap.score[WHITE]}</b>" in report and "Tristan Weber" in report and "<details>" in report
    team_box = pd.read_csv(tmp_path / "game" / "stats" / "team_box.csv", index_col="team")
    assert team_box["goals"].to_dict() == snap.score
    assert len(list((tmp_path / "game" / "stats").glob("*.csv"))) == 12


def spoken(*lines: tuple[float, str]) -> yus.Transcript:
    """A transcript of these (seconds after 20:40, words) groups."""
    transcript = yus.Transcript()
    for seconds, text in lines:
        interpretation = transcript.add_group().add_interpretation(confidence=0.9)
        for i, word in enumerate(text.split()):
            interpretation.add_word(word, start=dt.datetime(2025, 1, 14, 20, 40) + dt.timedelta(seconds=seconds + 0.3 * i), duration=dt.timedelta(seconds=0.3))
    return transcript


KID_FOR_BLACK = spoken((0, "white pulls"), (5, "picked up by bluey for black"), (8, "bluey backhand to the kid"), (11, "the kid hammer to george for a score"))


def test_names_of_another_teams_player_are_reported(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]):
    """The descriptions say "the kid" is white's Serayan Knappe-Butler; here he is said to play for black."""
    run(tmp_path, f"A={save(tmp_path / 'a.json', KID_FOR_BLACK)}")
    assert 'Team conflicts:\n  "the kid" (2x for Category 5) is Dump & Drizzle\'s Serayan Knappe-Butler' in capsys.readouterr().out


@pytest.mark.parametrize("label", ["the kid", "black kid"])
def test_a_name_described_on_its_own_team_is_no_conflict(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str], label: str):
    """Describing black's "the kid" as an unknown player, as the conflict asks, clears it, even with the name as the label."""
    descriptions = GameDescriptions.model_validate_json(DESCRIPTIONS.read_text())
    descriptions.players.append(PlayerDescription(team="black", descriptions=["the kid"], label=label))
    (path := tmp_path / "descriptions.json").write_text(descriptions.model_dump_json())
    run(tmp_path, f"A={save(tmp_path / 'a.json', KID_FOR_BLACK)}", extra=("--descriptions", str(path)))
    out = capsys.readouterr().out
    assert "Team conflicts" not in out and f"Category 5: {label} 2x" in out


def test_two_commentators_are_merged(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str], transcript: yus.Transcript):
    """Two synthetic commentators: each misses some groups; the second's clock is 5 s ahead and they say light/dark."""
    a = save(tmp_path / "a.json", other_commentator(transcript, 0.0, drop=7))
    b = save(tmp_path / "b.json", other_commentator(transcript, 5.0, drop=5, swap={"white": "light", "black": "dark"}))
    loaded = run(tmp_path, f"A={a}:white", f"B={b}:dark", extra=("--html", str(tmp_path / "report.html"), "--csv-dir", str(tmp_path / "csv")))
    out = capsys.readouterr().out
    snap = loaded.snapshot()
    alone = run(tmp_path / "alone", f"A={TRANSCRIPT}").snapshot()

    assert snap.merge is not None and snap.merge.offsets[1] == pytest.approx(-5.0, abs=0.3)
    assert [c.focus_team for c in snap.commentators] == ["white", "dark"]
    assert snap.official.events == yus.EventStream.model_validate_json((tmp_path / "game" / "official.json").read_text()).events
    assert snap.score == alone.score and abs(len(snap.official.events) - len(alone.official.events)) <= 5
    assert "  B: " in out and "focus dark" in out and "Merged:" in out
    assert "reported by" in (tmp_path / "report.html").read_text() and (tmp_path / "csv" / "player_box.csv").exists()
    assert not (tmp_path / "game" / "report.html").exists()


def test_an_offset_moves_a_commentator_further_than_merging_looks(tmp_path: pathlib.Path, transcript: yus.Transcript):
    """Merging estimates offsets up to 20 s; a recording that started 90 s off needs @OFFSET."""
    a = save(tmp_path / "a.json", other_commentator(transcript, 0.0, drop=7))
    b = save(tmp_path / "b.json", other_commentator(transcript, 90.0, drop=5))
    unaligned = run(tmp_path / "unaligned", f"A={a}", f"B={b}").snapshot()
    aligned = run(tmp_path / "aligned", f"A={a}", f"B={b}@-90").snapshot()
    assert aligned.merge is not None and aligned.merge.offsets[1] == pytest.approx(0.0, abs=0.3)
    assert len(aligned.official.events) < 210 < 250 < len(unaligned.official.events)
    assert yus.Transcript.model_validate_json((tmp_path / "aligned" / "game" / "transcripts" / "B.json").read_text()).groups[0].words[0].start == transcript.groups[0].start


def test_commentators_putting_play_on_different_teams_are_reported(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str], transcript: yus.Transcript):
    b = other_commentator(transcript, 4.0, drop=1000)
    for word in b.groups[36].words:  # "pikachu picks it up for white", then seven white throws
        word.text = "dark" if word.text == "white" else word.text
    run(tmp_path, f"A={TRANSCRIPT}", f"B={save(tmp_path / 'b.json', b)}")
    out = capsys.readouterr().out
    assert "Team conflicts:" in out and "throws A put on Dump & Drizzle, B on Category 5" in out


def test_a_saved_game_is_replaced_only_with_force(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]):
    run(tmp_path, f"A={TRANSCRIPT}", f"B={WHISPER}")
    with pytest.raises(SystemExit, match="already holds a game"):
        run(tmp_path, f"A={WHISPER}")
    assert run(tmp_path, f"Whisper={WHISPER}", extra=("--force",)).commentators == ["Whisper"]
    assert [p.name for p in sorted((tmp_path / "game").glob("*/*.json"))] == ["Whisper.json", "Whisper.json"]  # events/, transcripts/


def test_times_with_a_utc_offset_are_game_times(tmp_path: pathlib.Path, transcript: yus.Transcript):
    aware = yus.Transcript.model_validate(transcript.model_dump())
    for word in aware.words:
        word.start = word.start.replace(tzinfo=dt.timezone(dt.timedelta(hours=-7)))
    run(tmp_path, f"A={save(tmp_path / 'a.json', aware)}")
    assert not re.search(r"\b\d\d:\d\d:\d\d\b", (tmp_path / "game" / "report.html").read_text())  # no time of day
    assert clock(dt.datetime(2025, 1, 14, 20, 31, 5, tzinfo=dt.timezone(dt.timedelta(hours=-7))), dt.datetime(2025, 1, 14, 20, 30)) == "1:05"


@pytest.fixture
def whisper(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """yus-transcribe replaced by one that writes the hand-made transcript; the commands it was run with."""
    commands = []

    def run(command: list[str], check: bool) -> None:
        commands.append(command)
        pathlib.Path(command[command.index("--output") + 1]).write_text(TRANSCRIPT.read_text())

    monkeypatch.setattr(game_cli.subprocess, "run", run)
    return commands


@pytest.fixture
def recording(tmp_path: pathlib.Path) -> pathlib.Path:
    (path := tmp_path / "recordings" / "20250114T2030-0700.ogg").parent.mkdir()
    path.write_bytes(b"")
    return path


def test_a_recording_is_transcribed_once(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, whisper: list[list[str]], recording: pathlib.Path):
    """Its transcript is kept beside it; running again, refused or forced, does not transcribe it again."""
    monkeypatch.chdir(tmp_path)
    argv = [*TEAMS, "--commentator", f"A={recording}"]
    assert main(argv) == 0 and len(whisper) == 1 and "2025-01-14T20:30:00" in whisper[0]
    assert (tmp_path / "games" / "20250114T203000" / "session.json").exists()  # named by the recording's start
    assert (recording.parent / "20250114T2030-0700.transcript.json").read_text() == TRANSCRIPT.read_text()
    with pytest.raises(SystemExit, match="already holds a game"):
        main(argv)
    assert main([*argv, "--force"]) == 0 and len(whisper) == 1
    assert main([*argv, "--force", "--retranscribe"]) == 0 and len(whisper) == 2
    assert main([*argv, "--force", "--stop", "60"]) == 0 and len(whisper) == 3 and (recording.parent / "20250114T2030-0700.stop60.transcript.json").exists()


def test_bad_inputs_are_refused_before_transcribing(tmp_path: pathlib.Path, whisper: list[list[str]], recording: pathlib.Path, transcript: yus.Transcript):
    descriptions = json.loads(DESCRIPTIONS.read_text())
    descriptions["players"].append({"team": "white", "descriptions": ["red shorts"], "player": "Nobody"})
    (bad_descriptions := tmp_path / "descriptions.json").write_text(json.dumps(descriptions))
    (taken := tmp_path / "taken").mkdir()
    (taken / "session.json").write_text("{}")
    cases = [
        (["--commentator", f"B={DATA / 'gruindoor_20250114T2030-eventstream.json'}"], "is not a yus transcript"),
        (["--commentator", f"B={TEAM_FILES[0]}"], "is not a yus transcript"),
        (["--commentator", f"B={save(tmp_path / 'empty.json', yus.Transcript())}"], "has no words"),
        (["--descriptions", str(bad_descriptions)], "'Nobody' is not on the roster"),
        (["--game-dir", str(taken)], "already holds a game"),
    ]
    for extra, message in cases:
        with pytest.raises(SystemExit, match=message):
            main([*TEAMS, "--commentator", f"A={recording}", *extra])
    assert not whisper


def test_parse_source(tmp_path: pathlib.Path, teams: list[yus.Team]):
    audio = tmp_path / "game.ogg"
    audio.write_bytes(b"")
    odd = tmp_path / "x@1:dark.json"  # a file whose name looks like an offset and a focus
    odd.write_text("{}")
    assert parse_source(f"Gavin={audio}", teams).model_dump() == {"name": "Gavin", "path": audio, "offset": None, "focus": None}
    source = parse_source(f" Sam ={audio}@-12.5:Cat 5", teams)
    assert (source.name, source.path, source.offset, source.focus, source.audio) == ("Sam", audio, -12.5, "Cat 5", True)
    assert parse_source(f"Sam={audio}:white", teams).focus == "white" and parse_source(f"Sam={audio}@+3", teams).offset == 3.0
    assert parse_source(f"Sam={odd}", teams).path == odd and not parse_source(f"Sam={odd}", teams).audio
    for bad, message in [
        (str(audio), "NAME=PATH"),
        (f"={audio}", "NAME=PATH"),
        (f"Sam={audio}:purple", "no team is called 'purple'"),
        (f"Sam={audio}@soon", "not a number of seconds"),
        (f"Sam={audio}@nan", "not a number of seconds"),
        (f"Sam={tmp_path / 'missing.ogg'}", "no file"),
        (f"Sam={tmp_path / 'missing.ogg'}@-12:dark", re.escape(f"no file {tmp_path / 'missing.ogg'}") + "$"),
        (f"Sam={tmp_path / 'no'}:file.json", re.escape(f"no file {tmp_path / 'no'}:file.json") + "$"),
        (f"Sam={tmp_path / 'missing.ogg'}@soon", re.escape(f"no file {tmp_path / 'missing.ogg'}@soon") + "$"),
    ]:
        with pytest.raises(ValueError, match=message):
            parse_source(bad, teams)


@pytest.mark.parametrize(
    "argv, message",
    [
        (["--team", str(TEAM_FILES[0]), "--commentator", f"A={TRANSCRIPT}"], "two or more"),
        (["--team", str(TEAM_FILES[0]), "--team", str(TEAM_FILES[1])], "at least one"),
        (["--team", str(TEAM_FILES[0]), "--team", str(TEAM_FILES[1]), "--commentator", f"A={TRANSCRIPT}", "--commentator", f"A={WHISPER}"], "one name"),
    ],
)
def test_bad_arguments(argv: list[str], message: str, capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit):
        main(argv)
    assert message in capsys.readouterr().err


AUDIO = pathlib.Path(os.environ.get("YUS_DATA", pathlib.Path.home() / "Documents/Personal/yus-data")) / "drive/20250114T2030-0700.ogg"


@pytest.mark.skipif(os.environ.get("YUS_SLOW_TESTS") != "1", reason="needs the Whisper model, a GPU and the game's audio: set YUS_SLOW_TESTS=1")
def test_a_recording_is_transcribed(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]):
    """The first 120 s of the game's audio (its metadata says it started at 20:30:33), against the ground truth."""
    if not AUDIO.exists():
        pytest.skip(f"no audio at {AUDIO}")
    (audio := tmp_path / AUDIO.name).symlink_to(AUDIO)  # its transcript is kept beside it
    loaded = run(tmp_path, f"Gavin Kistner={audio}", extra=("--stop", "120"))
    snap = loaded.snapshot()
    truth = build_game()
    resolver = PlayerResolver(truth.teams, GameDescriptions.model_validate_json(DESCRIPTIONS.read_text()))
    cut = dt.datetime(2025, 1, 14, 20, 30, 33) + dt.timedelta(seconds=115)  # an event under way at 120 s may be cut off
    result = score(snap.official, truth.official_stream, resolve=resolver, stop=cut)
    print(f"\n{snap.summary}; event F1 {result.overall.f1:.3f}, exact {result.exact.f1:.3f}")
    assert snap.official.events and snap.official.events[0].when < cut and result.overall.f1 > 0.8
