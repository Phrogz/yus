import datetime as dt
import json
import os
import pathlib
import threading
import time

import pandas as pd
import pytest

import yus
from tests.data.gruindoor_20250114T2030 import build_game
from yus.processing.event_extraction import extract_events
from yus.processing.event_unification import GameDescriptions, PlayerResolver
from yus.processing.stats import compute_stats
from yus.session import GameSession, GameSnapshot, replay

DATA = pathlib.Path(__file__).parent / "data"
TRANSCRIPT = DATA / "gruindoor_20250114T2030-transcript.json"  # the hand-made transcript
WHISPER = DATA / "gruindoor_20250114T2030-whisper-turbo.json"
DESCRIPTIONS = DATA / "gruindoor_20250114T2030-descriptions.json"
WHITE, BLACK = "Dump & Drizzle", "Category 5"
T0 = dt.datetime(2025, 1, 14, 20, 40)


@pytest.fixture(scope="module")
def game() -> yus.Game:
    return build_game()


@pytest.fixture(scope="module")
def transcript() -> yus.Transcript:
    return yus.Transcript.model_validate_json(TRANSCRIPT.read_text())


@pytest.fixture(scope="module")
def descriptions() -> GameDescriptions:
    return GameDescriptions.model_validate_json(DESCRIPTIONS.read_text())


def spoken(*lines: tuple[float, str]) -> yus.Transcript:
    """A transcript with one group per (seconds after T0, text), 0.3 s per word."""
    transcript = yus.Transcript()
    for seconds, text in lines:
        interpretation = transcript.add_group().add_interpretation(confidence=0.9)
        for i, word in enumerate(text.split()):
            interpretation.add_word(word, start=T0 + dt.timedelta(seconds=seconds + 0.3 * i), duration=dt.timedelta(seconds=0.3))
    return transcript


def other_commentator(transcript: yus.Transcript, seconds: float, drop: int) -> yus.Transcript:
    """The same commentary from someone whose clock is `seconds` ahead, who misses every `drop`th group and says light/dark."""
    swap = {"white": "light", "black": "dark"}
    other = yus.Transcript()
    for i, group in enumerate(transcript.groups):
        if i % drop != drop - 1:
            interpretation = other.add_group().add_interpretation(confidence=group.interpretations[0].confidence)
            for word in group.words:
                interpretation.add_word(swap.get(word.text, word.text), start=word.start + dt.timedelta(seconds=seconds), duration=word.duration)
    return other


def arrival(group: yus.TranscriptGroup) -> dt.datetime:
    return max(word.start + word.duration for word in group.words)


def assert_settled_never_change(snapshots: list[GameSnapshot], final: GameSnapshot) -> None:
    settled = 0
    for snap in snapshots:
        assert snap.settled_count >= settled
        settled = snap.settled_count
        assert snap.official.events[:settled] == final.official.events[:settled], f"version {snap.version}"


def assert_same_snapshot(a: GameSnapshot, b: GameSnapshot) -> None:
    assert (a.version, a.settled_count, a.finished) == (b.version, b.settled_count, b.finished)
    assert a.commentators == b.commentators and a.associations == b.associations and a.descriptions == b.descriptions
    assert a.official.events == b.official.events
    assert {name: s.events for name, s in a.raw.items()} == {name: s.events for name, s in b.raw.items()}
    assert {name: s.events for name, s in a.resolved.items()} == {name: s.events for name, s in b.resolved.items()}
    assert a.unresolved == b.unresolved and a.unmentioned == b.unmentioned
    for name, table in a.stats.tables().items():
        pd.testing.assert_frame_equal(table, b.stats.tables([name])[name])


def test_replay_of_the_game_matches_the_batch_pipeline(game: yus.Game, transcript: yus.Transcript, descriptions: GameDescriptions):
    session = GameSession(game, descriptions)
    snapshots: list[GameSnapshot] = []
    assert replay(session, transcript, "Gavin Kistner", on_update=snapshots.append) == len(transcript.groups)
    session.finish()
    final = session.snapshot()

    resolver = PlayerResolver(game.teams, descriptions)
    raw = extract_events(transcript, game.teams, timeout=6.0)
    batch = resolver.resolve_stream(raw, "Gavin Kistner")
    expected = compute_stats(yus.EventStream(game=game, events=batch.events), game.teams, provisional_from=len(batch.events))
    assert final.official.events == batch.events and final.settled_count == len(batch.events) == 200
    for name, table in expected.tables().items():
        pd.testing.assert_frame_equal(final.stats.tables([name])[name], table)

    truth = compute_stats(resolver.resolve_stream(game.official_stream), game.teams)
    assert truth.score == {WHITE: 14, BLACK: 9}
    # The extractor counts one more black goal: "blade in the end zone nope not in the end zone" (docs/extraction.md, Limitations).
    assert final.score[WHITE] == 14 and final.score[BLACK] in (9, 10)
    assert final.summary.startswith(f"{WHITE} 14, {BLACK} ")

    assert_settled_never_change(snapshots, final)
    for snap in snapshots[::25]:
        assert snap.stats.provisional_from == snap.settled_count
        assert snap.raw["Gavin Kistner"].events[: snap.settled_count] == raw.events[: snap.settled_count]
        assert len(snap.official.events) - snap.settled_count <= 1  # one commentator: only the open throw is provisional


def test_snapshot_reports_commentators_and_names(game: yus.Game, transcript: yus.Transcript, descriptions: GameDescriptions):
    session = GameSession(game, descriptions)
    session.add_commentator("Gavin Kistner", focus_team="white")
    session.add_groups("Gavin Kistner", transcript.groups[:60])
    session.set_pending_text("Gavin Kistner", "flick to")
    snap = session.snapshot()
    (state,) = snap.commentators
    assert (state.name, state.focus_team, state.groups, state.pending_text) == ("Gavin Kistner", "white", 60, "flick to")
    assert state.final_count == snap.settled_count and snap.merge is None and not snap.finished
    assert snap.unresolved[0][:2] == (WHITE, "glasses")  # nobody knows who "glasses" is
    assert "Ben Kishter" not in snap.unmentioned[WHITE] and "Molly Lanning" in snap.unmentioned[BLACK]
    assert snap.provisional == snap.official.events[snap.settled_count :]
    assert snap.raw["Gavin Kistner"].events[0].player == "pikachu" and snap.resolved["Gavin Kistner"].events[0].player == "Matt Whitlock"


def test_describe_mid_game_fixes_earlier_events(game: yus.Game, transcript: yus.Transcript):
    session = GameSession(game)
    session.add_commentator("Gavin Kistner")
    session.add_groups("Gavin Kistner", transcript.groups[:120])
    before = session.snapshot()
    crop = [i for i, event in enumerate(before.official.events) if "close crop" in (event.player, getattr(event, "receiver", None))]
    assert crop and any(name == "close crop" for _, name, _ in before.unresolved)

    record = session.describe("white", ["close crop", "short crop"], player="ben kishter")
    assert record.player == "Ben Kishter" and session.version > before.version
    after = session.snapshot()
    for i in crop:
        assert "close crop" not in (after.official.events[i].player, getattr(after.official.events[i], "receiver", None))
        assert "Ben Kishter" in (after.official.events[i].player, getattr(after.official.events[i], "receiver", None))
    assert not any(name == "close crop" for _, name, _ in after.unresolved)
    assert after.raw["Gavin Kistner"].events == before.raw["Gavin Kistner"].events  # raw events keep names as spoken
    assert before.official.events[crop[0]].player in ("close crop", None) or before.official.events[crop[0]].receiver == "close crop"  # old snapshot kept
    assert session.descriptions.players[-1] == record and after.descriptions.players[-1] == record

    with pytest.raises(ValueError):
        session.describe("white", ["glasses"], player="Jerry Swider")  # not on white
    assert session.snapshot() is after


def test_spoken_association_is_applied(game: yus.Game):
    session = GameSession(game)
    session.add_commentator("A")
    commentary = spoken(
        (0, "picked up by red shorts for white"), (3, "flick to pikachu"), (6, "backhand to red shorts"), (10, "oh, red shorts is kaia"), (13, "flick to red shorts")
    )
    session.add_groups("A", commentary.groups[:3])
    assert session.snapshot().official.events[0].player == "red shorts" and not session.snapshot().associations

    session.add_groups("A", commentary.groups[3:])
    snap = session.snapshot()
    (heard,) = snap.associations
    assert (heard.commentator, heard.team, heard.description, heard.name, heard.player) == ("A", "white", "red shorts", "kaia", "Kaia Mann")
    assert [event.player for event in snap.official.events] == ["Kaia Mann", "Matt Whitlock", "Kaia Mann"]
    assert snap.official.events[1].receiver == "Kaia Mann" and snap.raw["A"].events[0].player == "red shorts"
    assert snap.descriptions.players[-1].commentator == "A"

    session.describe("white", ["red shorts"], player="Emily Kraus", commentator="A")  # a person corrects what was heard
    assert session.snapshot().official.events[0].player == "Emily Kraus"


def test_two_commentators_are_merged(game: yus.Game, transcript: yus.Transcript, descriptions: GameDescriptions):
    other = other_commentator(transcript, 5.0, drop=8)
    session = GameSession(game, descriptions)
    session.add_commentator("A")
    session.add_commentator("B", focus_team="light")
    feed = sorted([(arrival(g), 0, g) for g in transcript.groups] + [(arrival(g), 1, g) for g in other.groups], key=lambda item: item[:2])
    snapshots = []
    for when, k, group in feed:
        session.add_groups("AB"[k], [group])
        session.advance(when, "AB"[k])
        snapshots.append(session.snapshot())
    session.finish()
    final = session.snapshot()

    alone = GameSession(game, descriptions)
    replay(alone, transcript, "A")
    alone.finish()
    assert final.merge is not None and final.merge.offsets[1] == pytest.approx(-5.0, abs=0.3)
    assert final.official.events[0].team == WHITE  # merged events name teams by their first name
    assert len(final.official.events) == len(alone.snapshot().official.events) and final.score == alone.snapshot().score
    assert final.settled_count == len(final.official.events)
    assert [c.groups for c in final.commentators] == [len(transcript.groups), len(other.groups)]
    assert_settled_never_change(snapshots, final)
    assert max(len(s.official.events) - s.settled_count for s in snapshots) < 25


def test_save_and_load_reproduce_the_session(game: yus.Game, transcript: yus.Transcript, descriptions: GameDescriptions, tmp_path: pathlib.Path):
    other = other_commentator(transcript, 4.0, drop=6)
    sessions = [GameSession(game, descriptions, tmp_path / "game")]
    original = sessions[0]
    original.add_commentator("Gavin Kistner")
    original.add_commentator("B / Other", focus_team="dark")
    half = len(transcript.groups) // 2
    original.add_groups("Gavin Kistner", transcript.groups[:half])
    original.add_groups("B / Other", other.groups[: half - 20])
    original.describe("black", ["gloves"], label="gloves guy")
    original.advance(arrival(transcript.groups[half - 1]) + dt.timedelta(seconds=10), "Gavin Kistner")
    original.set_pending_text("B / Other", "flick to")
    saved = original.snapshot()
    original.save()

    files = sorted(str(path.relative_to(tmp_path / "game")) for path in (tmp_path / "game").rglob("*.json"))
    assert files == [
        "descriptions.json",
        "events/B_Other.json",
        "events/Gavin_Kistner.json",
        "game.json",
        "official.json",
        "session.json",
        "transcripts/B_Other.json",
        "transcripts/Gavin_Kistner.json",
    ]
    assert set(json.loads((tmp_path / "game" / "game.json").read_text())) == {"sport", "when", "teams"}
    assert yus.EventStream.model_validate_json((tmp_path / "game" / "official.json").read_text()).events == saved.official.events
    assert yus.EventStream.model_validate_json((tmp_path / "game" / "events" / "B_Other.json").read_text()).events == saved.raw["B / Other"].events

    loaded = GameSession.load(tmp_path / "game")
    assert_same_snapshot(loaded.snapshot(), saved)

    sessions.append(loaded)
    for session in sessions:  # both go on the same way
        session.add_groups("Gavin Kistner", transcript.groups[half:])
        session.add_groups("B / Other", other.groups[half - 20 :])
        session.snapshot()
        session.finish()
    assert_same_snapshot(loaded.snapshot(), original.snapshot())
    loaded.save()
    assert_same_snapshot(GameSession.load(tmp_path / "game").snapshot(), original.snapshot())


def test_version_increases_on_every_change(game: yus.Game, transcript: yus.Transcript):
    session = GameSession(game)
    versions = [session.version]

    def changed(expected: bool = True) -> None:
        versions.append(session.version)
        assert (versions[-1] > versions[-2]) == expected

    session.add_commentator("A")
    changed()
    first = session.snapshot()
    assert session.snapshot() is first and first.version == session.version
    session.add_groups("A", transcript.groups[:5])
    changed()
    session.add_groups("A", [])
    changed(False)
    session.set_pending_text("A", "flick")
    changed()
    session.set_pending_text("A", "flick")
    changed(False)
    snap = session.snapshot()
    assert snap is not first and snap.official is session.snapshot().official
    pending = session.snapshot().official.events[session.snapshot().settled_count :]
    assert pending, "the open throw"
    session.advance(arrival(transcript.groups[4]) + dt.timedelta(seconds=1))
    changed(False)  # not silent long enough to time out
    session.advance(arrival(transcript.groups[4]) + dt.timedelta(seconds=7))
    changed()
    assert session.snapshot().settled_count == len(session.snapshot().official.events)
    session.describe("white", ["glasses"], label="glasses")
    changed()
    session.finish()
    changed()
    session.finish()
    changed(False)
    with pytest.raises(RuntimeError):
        session.add_groups("A", transcript.groups[5:6])
    with pytest.raises(ValueError):
        session.add_commentator("A")
    with pytest.raises(ValueError):
        session.set_pending_text("nobody", "")
    with pytest.raises(ValueError):
        GameSession(game).add_commentator("C", focus_team="purple")


def test_snapshot_speed(game: yus.Game, transcript: yus.Transcript, descriptions: GameDescriptions):
    session = GameSession(game, descriptions)
    started = time.perf_counter()
    replay(session, transcript, "Gavin Kistner", on_update=lambda snap: snap.official)
    snapshots = time.perf_counter() - started
    assert snapshots < 2.0, f"{snapshots:.2f} s for {len(transcript.groups)} snapshots"

    session = GameSession(game, descriptions)
    started = time.perf_counter()
    replay(session, transcript, "Gavin Kistner", on_update=lambda snap: snap.stats)
    with_stats = time.perf_counter() - started
    assert with_stats < 6.0, f"{with_stats:.2f} s for {len(transcript.groups)} snapshots with their stats"  # about 1.8 s: compute_stats' DataFrames


def test_replay_in_time_advances_through_silence(game: yus.Game):
    commentary = spoken((0, "picked up by pikachu for white"), (2, "flick to kaia"), (25, "backhand to tristan"))
    clock = [0.0]
    session = GameSession(game)
    seen: list[tuple[float, int, int]] = []
    fed = replay(
        session,
        commentary,
        "A",
        speed=10,
        on_update=lambda snap: seen.append((clock[0] * 10, snap.commentators[0].groups, snap.settled_count)),
        clock=lambda: clock[0],
        sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )
    assert fed == 3
    timed_out = next(when for when, groups, settled in seen if groups == 2 and settled == 1)
    assert 8.6 < timed_out < 10.6  # "flick to kaia" ends at 2.9 s; 6 s of silence later it is final, before the next group
    assert seen[-1][1] == 3 and seen[-1][0] == pytest.approx(25.9, abs=0.01)  # its last word ends

    stop = threading.Event()
    stop.set()
    assert replay(GameSession(game), commentary, "A", speed=1, stop=stop, clock=lambda: 0.0, sleep=lambda s: None) == 0


def test_replay_of_a_saved_whisper_transcript(game: yus.Game, descriptions: GameDescriptions):
    session = GameSession(game, descriptions)
    replay(session, WHISPER, "whisper")
    session.finish()
    snap = session.snapshot()
    transcript = yus.Transcript.model_validate_json(WHISPER.read_text())
    batch = PlayerResolver(game.teams, descriptions).resolve_stream(extract_events(transcript, game.teams, timeout=6.0), "whisper")
    assert snap.official.events == batch.events and sum(snap.score.values()) >= 23


def test_threads_feed_and_read_concurrently(game: yus.Game, transcript: yus.Transcript):
    other = other_commentator(transcript, 3.0, drop=5)
    session = GameSession(game)
    session.add_commentator("A")
    session.add_commentator("B")
    done = threading.Event()
    errors: list[BaseException] = []

    def feed(name: str, groups: list[yus.TranscriptGroup]) -> None:
        try:
            for group in groups:
                session.add_groups(name, [group])
        except BaseException as error:  # pragma: no cover - reported below
            errors.append(error)

    def read() -> None:
        while not done.is_set():
            snap = session.snapshot()
            assert snap.settled_count <= len(snap.official.events)

    threads = [threading.Thread(target=feed, args=("A", transcript.groups)), threading.Thread(target=feed, args=("B", other.groups))]
    reader = threading.Thread(target=read)
    for thread in [*threads, reader]:
        thread.start()
    for thread in threads:
        thread.join()
    done.set()
    reader.join()
    session.finish()
    assert not errors
    snap = session.snapshot()
    assert snap.raw["A"].events == extract_events(transcript, game.teams, timeout=6.0).events
    assert snap.raw["B"].events == extract_events(other, game.teams, timeout=6.0).events


@pytest.mark.skipif(os.environ.get("YUS_SLOW_TESTS") != "1", reason="needs the Whisper model, a GPU and the game's audio: set YUS_SLOW_TESTS=1")
def test_live_transcription_of_the_real_audio_feeds_a_session(game: yus.Game, descriptions: GameDescriptions):
    from yus.processing.transcription import live
    from yus.processing.transcription import transcribe as tr

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    audio_path = pathlib.Path.home() / "Documents/Personal/yus-data/drive/20250114T2030-0700.ogg"
    whisper = live.load_whisper("mlx", "mlx-community/whisper-large-v3-turbo")
    transcriber = live.LiveTranscriber(
        start=dt.datetime(2025, 1, 14, 20, 30, 33),
        prompt=live.live_prompt(game.teams, whisper),
        replacements=tr.load_replacements("ultimate/indoor", game.teams),
        transcribe=whisper,
    )
    session = GameSession(game, descriptions)
    session.add_commentator("Gavin Kistner")
    slowest = [0.0]

    def on_groups(groups: list[yus.TranscriptGroup], now: float) -> None:
        session.add_groups("Gavin Kistner", groups)
        session.set_pending_text("Gavin Kistner", transcriber.pending_text)
        started = time.perf_counter()
        session.snapshot().stats
        slowest[0] = max(slowest[0], time.perf_counter() - started)

    live.simulate(transcriber, live.load_audio(audio_path), on_groups=on_groups)
    session.finish()
    snap = session.snapshot()
    print(f"\n{snap.summary}; {len(snap.official.events)} events; slowest snapshot with stats {slowest[0] * 1000:.0f} ms")
    assert sum(snap.score.values()) >= 20 and slowest[0] < 0.1
