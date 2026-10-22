import copy
import dataclasses
import datetime as dt
import json
import math
import os
import pathlib
import pickle
import threading
import time
import unicodedata
from collections.abc import Callable

import pandas as pd
import pytest

import yus
from tests.data.gruindoor_20250114T2030 import build_game
from yus.processing.event_extraction import extract_events
from yus.processing.event_unification import GameDescriptions, PlayerResolver
from yus.processing.stats import compute_stats
from yus.session import GameSession, GameSnapshot, replay
from yus.sports import ultimate

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


def team_named(events: list[yus.Event], game: yus.Game) -> list[yus.Event]:
    """The events with teams named by their first names, as official streams name them."""
    first = {name: team.names[0] for team in game.teams for name in team.names}
    return [event.model_copy(update={"team": first[event.team]}) if isinstance(event, ultimate.UltimateEvent) and event.team in first else event for event in events]


def feed_in_turn(session: GameSession, streams: dict[str, list[yus.TranscriptGroup]], lag: dict[str, float] | None = None) -> list[GameSnapshot]:
    """Feed each commentator's groups in the order they arrive, each `lag` seconds late, advancing them to the group's end; a
    snapshot after each."""
    late = {name: dt.timedelta(seconds=(lag or {}).get(name, 0.0)) for name in streams}
    feed = sorted(((arrival(g) + late[name], k, name, g) for k, (name, groups) in enumerate(streams.items()) for g in groups), key=lambda item: item[:2])
    snapshots = []
    for _, _, name, group in feed:
        session.add_groups(name, [group])
        session.advance(arrival(group), name)
        snapshots.append(session.snapshot())
    return snapshots


def assert_settled_never_change(snapshots: list[GameSnapshot], final: GameSnapshot) -> None:
    settled = 0
    for snap in snapshots:
        assert snap.settled_count >= settled
        settled = snap.settled_count
        assert snap.official.events[:settled] == final.official.events[:settled], f"version {snap.version}"


def assert_same_snapshot(a: GameSnapshot, b: GameSnapshot, version: bool = True) -> None:
    assert (a.settled_count, a.finished) == (b.settled_count, b.finished) and (a.version == b.version or not version)
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
    assert final.resolved["Gavin Kistner"].events == batch.events and final.settled_count == len(batch.events) == 200
    assert final.official.events == team_named(batch.events, game)  # teams by first name, as with several commentators
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
    assert snap.resolved["Gavin Kistner"].events[0].team == "white" and {event.team for event in snap.official.events} == {WHITE, BLACK}
    assert [group.words for group in snap.transcripts["Gavin Kistner"]] == [group.words for group in transcript.groups[:60]]
    session.add_groups("Gavin Kistner", transcript.groups[60:61])
    assert len(snap.transcripts["Gavin Kistner"]) == 60 and len(session.snapshot().transcripts["Gavin Kistner"]) == 61


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
    snapshots = feed_in_turn(session, {"A": transcript.groups, "B": other.groups})
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
    assert_same_snapshot(loaded.snapshot(), original.snapshot(), version=False)  # versions after load() leap past any given out before
    loaded.save()
    assert_same_snapshot(GameSession.load(tmp_path / "game").snapshot(), loaded.snapshot())


def test_load_does_not_hear_identifications_again(game: yus.Game, tmp_path: pathlib.Path):
    session = GameSession(game, directory=tmp_path)
    session.add_commentator("A")
    session.add_groups("A", spoken((0, "picked up by red shorts for white"), (3, "flick to pikachu"), (6, "oh, red shorts is kaia")).groups)
    session.describe("white", ["red shorts"], player="Emily Kraus", commentator="A")  # corrects what was heard
    session.save()
    loaded = GameSession.load(tmp_path)
    assert_same_snapshot(loaded.snapshot(), session.snapshot())
    assert loaded.snapshot().official.events[0].player == "Emily Kraus" and len(loaded.descriptions.players) == 2


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
    with pytest.raises(ValueError):
        session.add_commentator("A")
    with pytest.raises(ValueError):
        session.set_pending_text("nobody", "")
    with pytest.raises(ValueError):
        session.describe("white", ["glasses"], label="glasses", commentator="a typo")
    with pytest.raises(ValueError):
        GameSession(game).add_commentator("C", focus_team="purple")
    with pytest.raises(TypeError):
        session.set_pending_text("A", None)  # type: ignore[arg-type]
    changed(False)
    assert session.snapshot().commentators[0].pending_text == "flick"
    session.finish()
    changed()
    session.finish()
    changed(False)
    session.advance(arrival(transcript.groups[4]) + dt.timedelta(seconds=60))
    changed(False)
    for refused in (lambda: session.add_groups("A", transcript.groups[5:6]), lambda: session.add_commentator("B"), lambda: session.set_pending_text("A", "x")):
        with pytest.raises(RuntimeError):
            refused()
    session.describe("white", ["specs"], label="glasses")  # names can still be fixed
    changed()


def test_snapshot_speed(game: yus.Game, transcript: yus.Transcript, descriptions: GameDescriptions):
    session = GameSession(game, descriptions)
    started = time.perf_counter()
    replay(session, transcript, "Gavin Kistner", on_update=lambda snap: snap.official)
    snapshots = time.perf_counter() - started
    assert snapshots < 2.0, f"{snapshots:.2f} s for {len(transcript.groups)} snapshots"

    session = GameSession(game, descriptions)
    started = time.perf_counter()
    replay(session, transcript, "Gavin Kistner", on_update=lambda snap: (snap.stats, snap.unresolved, snap.unmentioned))
    with_stats = time.perf_counter() - started
    assert with_stats < 3.0, f"{with_stats:.2f} s for {len(transcript.groups)} snapshots with their stats"  # about 1.7 s: compute_stats' DataFrames


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
    assert snap.official.events == team_named(batch.events, game) and sum(snap.score.values()) >= 23


def guarded(errors: list[BaseException], work: Callable[[], None]) -> threading.Thread:
    """A thread that runs `work`, adding any exception to `errors`."""

    def run() -> None:
        try:
            work()
        except BaseException as error:  # pragma: no cover - reported by the test
            errors.append(error)

    return threading.Thread(target=run)


def test_threads_feed_and_read_concurrently(game: yus.Game, transcript: yus.Transcript, tmp_path: pathlib.Path):
    other = other_commentator(transcript, 3.0, drop=5)
    session = GameSession(game, directory=tmp_path)
    session.add_commentator("A")
    session.add_commentator("B")
    done = threading.Event()
    errors: list[BaseException] = []

    def feed(name: str, groups: list[yus.TranscriptGroup]) -> None:
        for group in groups:
            session.add_groups(name, [group])

    def read() -> None:
        while not done.is_set():
            snap = session.snapshot()
            assert snap.settled_count <= len(snap.official.events)

    def describe_and_save() -> None:
        for i in range(10):
            session.describe("white", ["glasses"], label=f"glasses {i}")
            session.save()

    threads = [guarded(errors, lambda: feed("A", transcript.groups)), guarded(errors, lambda: feed("B", other.groups)), guarded(errors, describe_and_save)]
    reader = guarded(errors, read)
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
    session.save()
    assert_same_snapshot(GameSession.load(tmp_path).snapshot(), snap)


def test_a_lagging_commentator_never_unsettles_events(game: yus.Game, transcript: yus.Transcript, descriptions: GameDescriptions):
    """B's transcript arrives 90 s late (a busy GPU, say). LiveMerger alone allows 20 s."""
    other = other_commentator(transcript, 5.0, drop=8)
    session = GameSession(game, descriptions)
    session.add_commentator("A")
    session.add_commentator("B", focus_team="light")
    snapshots = feed_in_turn(session, {"A": transcript.groups, "B": other.groups}, lag={"B": 90.0})
    session.finish()
    final = session.snapshot()
    assert_settled_never_change(snapshots, final)
    assert len(final.official.events) == 200 and max(len(s.official.events) - s.settled_count for s in snapshots) < 45


def test_merged_events_settle_only_as_far_as_the_slowest_commentator(game: yus.Game, transcript: yus.Transcript, descriptions: GameDescriptions):
    other = other_commentator(transcript, 5.0, drop=8)  # B's clock is 5 s ahead
    session = GameSession(game, descriptions)
    session.add_commentator("A")
    session.add_commentator("B", focus_team="light")
    session.add_groups("A", transcript.groups[:30])
    session.advance(arrival(transcript.groups[29]), "A")
    assert session.snapshot().settled_count == 0  # nothing is known of B, who may yet report the start of the game

    a = transcript.groups[30:160]
    b = [group for group in other.groups if group.start < transcript.groups[120].start + dt.timedelta(seconds=5)]
    feed_in_turn(session, {"A": a, "B": b})  # then B is silent, and not advanced
    stalled = session.snapshot()
    assert 0 < stalled.settled_count and stalled.official.events[stalled.settled_count - 1].when < b[-1].start - dt.timedelta(seconds=5)
    session.advance(arrival(a[-1]) + dt.timedelta(seconds=5), "B")  # B's transcript is complete up to A's last word: B said nothing
    resumed = session.snapshot()
    assert resumed.settled_count > stalled.settled_count + 20
    assert resumed.official.events[: stalled.settled_count] == stalled.official.events[: stalled.settled_count]


def test_commentators_named_alike_but_for_case_get_their_own_files(game: yus.Game, transcript: yus.Transcript, tmp_path: pathlib.Path):
    session = GameSession(game, directory=tmp_path)
    names = ["Gavin", "gavin", "G\u00e1vin", "Ga\u0301vin"]  # the last two differ only in Unicode normalization
    for i, name in enumerate(names, 1):
        session.add_commentator(name)
        session.add_groups(name, transcript.groups[: 10 * i])
    session.save()
    files = [unicodedata.normalize("NFC", path.name).casefold() for path in (tmp_path / "transcripts").iterdir()]
    assert len(set(files)) == len(files) == 4
    loaded = GameSession.load(tmp_path)
    assert loaded.commentators == names and [c.groups for c in loaded.snapshot().commentators] == [10, 20, 30, 40]


def utc_minus_7(transcript: yus.Transcript) -> yus.Transcript:
    """The transcript with its (naive, local) times given their UTC offset."""
    for word in transcript.words:
        word.start = word.start.replace(tzinfo=dt.timezone(dt.timedelta(hours=-7)))
    return transcript


def test_advance_takes_any_time_for_commentators_with_and_without_utc_offsets(game: yus.Game, monkeypatch: pytest.MonkeyPatch):
    def session_of_two() -> GameSession:
        session = GameSession(game)
        for name, commentary in (("A", spoken((0, "picked up by pikachu for white"), (2, "flick to kaia"))), ("B", utc_minus_7(spoken((0, "kaia to tristan"))))):
            session.add_commentator(name)
            session.add_groups(name, commentary.groups)
        return session

    later = T0 + dt.timedelta(seconds=20)
    for now in (later, later.replace(tzinfo=dt.timezone(dt.timedelta(hours=-7))), later.replace(tzinfo=dt.timezone(dt.timedelta(hours=-7))).astimezone(dt.UTC)):
        session = session_of_two()
        assert [len(session.snapshot().raw[name].events) for name in "AB"] == [1, 1] and [c.final_count for c in session.snapshot().commentators] == [0, 0]
        session.advance(now)  # 17 s after the last word: both throws become final
        assert [c.final_count for c in session.snapshot().commentators] == [1, 1]

    session = session_of_two()
    version = session.version

    def broken(now: dt.datetime) -> None:
        raise RuntimeError("broken")

    monkeypatch.setattr(session._commentators["B"].extractor, "advance", broken)
    with pytest.raises(RuntimeError):
        session.advance(later)
    assert session.version > version and [c.final_count for c in session.snapshot().commentators] == [1, 0]  # A's throw became final before B failed


def test_add_groups_refuses_times_unlike_the_commentators(game: yus.Game, tmp_path: pathlib.Path):
    session = GameSession(game, directory=tmp_path)
    session.add_commentator("A")
    session.add_groups("A", spoken((0, "picked up by pikachu for white")).groups)
    version = session.version
    with pytest.raises(ValueError, match="naive"):
        session.add_groups("A", [spoken((2, "flick to kaia")).groups[0], utc_minus_7(spoken((4, "backhand to tristan"))).groups[0]])
    assert session.version == version and session.snapshot().commentators[0].groups == 1  # neither group was added
    mixed = spoken((2, "flick to kaia"))
    mixed.words[-1].start = mixed.words[-1].start.astimezone()
    session.add_commentator("B")
    with pytest.raises(ValueError):
        session.add_groups("B", mixed.groups)
    session.add_groups("B", utc_minus_7(spoken((0, "flick to kaia"))).groups)
    session.save()
    assert_same_snapshot(GameSession.load(tmp_path).snapshot(), session.snapshot())


def test_load_without_session_json(game: yus.Game, transcript: yus.Transcript, descriptions: GameDescriptions, tmp_path: pathlib.Path):
    other = other_commentator(transcript, 4.0, drop=6)
    session = GameSession(game, descriptions, tmp_path)
    session.add_commentator("Gavin Kistner")
    session.add_commentator("B / Other")
    session.add_groups("Gavin Kistner", transcript.groups[:50])
    session.add_groups("B / Other", other.groups[:40])
    session.save()
    (tmp_path / "session.json").unlink()
    loaded = GameSession.load(tmp_path)
    assert loaded.commentators == ["B / Other", "Gavin Kistner"]  # file name order: B_Other.json, Gavin_Kistner.json
    snap, saved = loaded.snapshot(), session.snapshot()
    assert snap.transcripts.keys() == saved.transcripts.keys() and snap.descriptions == saved.descriptions
    assert {name: s.events for name, s in snap.raw.items()} == {name: s.events for name, s in saved.raw.items()}


def test_load_refuses_file_names_that_leave_the_directory(game: yus.Game, tmp_path: pathlib.Path):
    session = GameSession(game, directory=tmp_path / "game")
    session.add_commentator("A")
    session.save()
    path = tmp_path / "game" / "session.json"
    data = json.loads(path.read_text())
    data["commentators"][0]["file"] = "../../x"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="file name"):
        GameSession.load(tmp_path / "game")


def test_versions_after_load_are_new(game: yus.Game, transcript: yus.Transcript, tmp_path: pathlib.Path):
    session = GameSession(game, directory=tmp_path)
    session.add_commentator("A")
    session.add_groups("A", transcript.groups[:10])
    session.save()
    saved = session.version
    for group in transcript.groups[10:20]:  # changes that were never saved: then the server crashed
        session.add_groups("A", [group])
    loaded = GameSession.load(tmp_path)
    assert loaded.version == saved
    loaded.add_groups("A", transcript.groups[10:11])
    assert loaded.version > session.version


def test_unresolved_names_are_not_resolved_again(game: yus.Game):
    lines = ((0, "picked up by red shorts for {}"), (3, "flick to pikachu"), (6, "backhand to red shorts"))
    one, two = GameSession(game), GameSession(game)
    for session, names in ((one, ["A"]), (two, ["A", "B"])):
        for name, team in zip(names, ["white", "light"]):
            session.add_commentator(name)
            session.add_groups(name, spoken(*((seconds, text.format(team)) for seconds, text in lines)).groups)
        session.describe("white", ["red shorts"], label="Kaia")  # an unknown player called Kaia: not Kaia Mann
        snap = session.snapshot()
        assert [event.player for event in snap.official.events] == ["Kaia", "Matt Whitlock"] and snap.official.events[1].receiver == "Kaia"
        assert snap.unresolved == [(WHITE, "Kaia", 2)] and "Kaia Mann" in snap.unmentioned[WHITE]


def test_snapshots_can_be_copied_and_pickled(game: yus.Game, transcript: yus.Transcript):
    session = GameSession(game)
    replay(session, transcript.model_copy(update={"groups": transcript.groups[:40]}), "A")
    snap = session.snapshot()
    snap.stats
    for copied in (copy.deepcopy(snap), pickle.loads(pickle.dumps(snap))):
        assert copied.official.events == snap.official.events and copied.score == snap.score and copied.unresolved == snap.unresolved
    fields = dataclasses.asdict(snap)
    assert fields["settled_count"] == snap.settled_count and fields["official"].events == snap.official.events and "views" not in fields


@pytest.mark.parametrize("speed, tick", [(-1.0, 1.0), (math.nan, 1.0), (1.0, 0.0)])
def test_replay_refuses_a_bad_speed_or_tick(game: yus.Game, speed: float, tick: float):
    with pytest.raises(ValueError):
        replay(GameSession(game), spoken((0, "flick to kaia")), "A", speed=speed, tick=tick, clock=lambda: 0.0, sleep=lambda seconds: None)


AUDIO = pathlib.Path(os.environ.get("YUS_DATA", pathlib.Path.home() / "Documents/Personal/yus-data")) / "drive/20250114T2030-0700.ogg"


@pytest.mark.skipif(os.environ.get("YUS_SLOW_TESTS") != "1", reason="needs the Whisper model, a GPU and the game's audio: set YUS_SLOW_TESTS=1")
def test_live_transcription_of_the_real_audio_feeds_a_session(game: yus.Game, descriptions: GameDescriptions):
    """The first 180 s of the game's audio (t=0 is 20:30:33), transcribed live into a session, against the ground truth."""
    pytest.importorskip("mlx_whisper", reason="mlx-whisper is only installed on Apple Silicon (uv sync --extra mlx)")
    if not AUDIO.exists():
        pytest.skip(f"no audio at {AUDIO}")
    from yus.processing.evaluation import score
    from yus.processing.transcription import live
    from yus.processing.transcription import transcribe as tr

    whisper = live.MlxWhisper("large-v3-turbo")
    start = dt.datetime(2025, 1, 14, 20, 30, 33)
    transcriber = live.LiveTranscriber(start, live.live_prompt(game.teams, whisper), tr.load_replacements("ultimate/indoor", game.teams), transcribe=whisper)
    session = GameSession(game, descriptions)
    session.add_commentator("Gavin Kistner")
    slowest = 0.0

    def on_groups(groups: list[yus.TranscriptGroup], now: float) -> None:
        nonlocal slowest
        session.add_groups("Gavin Kistner", groups)
        session.advance(transcriber.horizon, "Gavin Kistner")
        session.set_pending_text("Gavin Kistner", transcriber.pending_text)
        started = time.perf_counter()
        session.snapshot().stats
        slowest = max(slowest, time.perf_counter() - started)

    live.simulate(transcriber, live.load_audio(AUDIO)[: 180 * live.SAMPLE_RATE], on_groups=on_groups)
    session.finish()
    snap = session.snapshot()
    cut = start + dt.timedelta(seconds=175)  # an event under way at 180 s may be cut off
    result = score(snap.official, game.official_stream, resolve=PlayerResolver(game.teams, descriptions), stop=cut)
    print(f"\n{snap.summary}; event F1 {result.overall.f1:.3f}, exact {result.exact.f1:.3f}; slowest snapshot with stats {slowest * 1000:.0f} ms")
    assert result.overall.f1 > 0.8 and slowest < 0.1
