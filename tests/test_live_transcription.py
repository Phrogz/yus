"""Tests for live transcription (yus-live-transcribe). A scripted fake decoder stands in for Whisper; the slow test at the end runs the real model."""

import datetime as dt
import inspect
import os
import pathlib
import random
import re
from collections import Counter
from types import SimpleNamespace
from typing import Callable

import numpy as np
import pytest

import yus
from yus.processing.transcription import live
from yus.processing.transcription import transcribe as tr

DATA = pathlib.Path(__file__).parent / "data"
SR = live.SAMPLE_RATE
T0 = dt.datetime(2025, 1, 14, 20, 30, 33)

Script = list[tuple[str, float, float]]  # (text, start, end) in seconds of the stream
Edit = Callable[[int, Script, float, float], Script]


def speak(text: str, at: float, word_s: float = 0.3) -> Script:
    """Words said back to back from `at`."""
    return [(word, at + i * word_s, at + (i + 1) * word_s) for i, word in enumerate(text.split())]


def ramp(seconds: float) -> np.ndarray:
    """Test audio whose samples hold their own index, so the fake decoder knows where each window starts."""
    return np.arange(int(round(seconds * SR)), dtype=np.float32)


class FakeWhisper:
    """Decodes a window to the scripted words that lie wholly inside it, optionally edited per call: edit(call, words, window start, window end)."""

    def __init__(self, script: Script, edit: Edit | None = None) -> None:
        self.script = script
        self.edit = edit
        self.windows: list[tuple[float, float, str | None]] = []

    def __call__(self, audio: np.ndarray, prompt: str | None) -> list[live.Segment]:
        start = float(audio[0]) / SR
        end = start + len(audio) / SR
        words = [(t, s, e) for t, s, e in self.script if s >= start - 1e-9 and e <= end + 1e-9]
        if self.edit:
            words = self.edit(len(self.windows), words, start, end)
        self.windows.append((start, end, prompt))
        return [segment(words, start)] if words else []


def segment(words: Script, offset: float = 0.0, no_speech_prob: float = 0.01, avg_logprob: float = -0.3) -> live.Segment:
    return {
        "text": "".join(f" {t}" for t, _, _ in words),
        "avg_logprob": avg_logprob,
        "no_speech_prob": no_speech_prob,
        "words": [{"word": f" {t}", "start": s - offset, "end": e - offset, "probability": 0.9} for t, s, e in words],
    }


def transcriber(fake: Callable[..., list[live.Segment]], replacements: tr.Replacements | None = None, **kwargs: float) -> live.LiveTranscriber:
    return live.LiveTranscriber(T0, "Players: Kaia Mann.", replacements, transcribe=fake, **kwargs)  # type: ignore[arg-type]


def run(lt: live.LiveTranscriber, seconds: float, blocks: list[float] | float = 0.1) -> tuple[list[yus.TranscriptGroup], list[yus.TranscriptGroup]]:
    """Feed `seconds` of ramp audio in blocks; return the groups feed() returned and those flush() returned."""
    audio = ramp(seconds)
    sizes = iter(blocks) if isinstance(blocks, list) else None
    fed: list[yus.TranscriptGroup] = []
    pos = 0
    while pos < len(audio):
        size = int((next(sizes, 1.0) if sizes else blocks) * SR)  # type: ignore[arg-type]
        fed += lt.feed(audio[pos : pos + size])
        pos += size
    return fed, lt.flush()


def group_texts(groups: list[yus.TranscriptGroup]) -> list[str]:
    return [g.interpretations[0].transcript for g in groups]


def word_times(groups: list[yus.TranscriptGroup]) -> list[tuple[str, float, float]]:
    return [(w.text, (w.start - T0).total_seconds(), (w.start + w.duration - T0).total_seconds()) for g in groups for w in g.words]


PLAY = speak("picked up by pikachu", 1.0) + speak("backhand to glasses", 3.0) + speak("scoober to tristan", 9.5) + speak("off the wall for the score", 16.0)
UTTERANCES = ["picked up by pikachu", "backhand to glasses", "scoober to tristan", "off the wall for the score"]


# Committing words ------------------------------------------------------------------------------------------------------------------------


def test_streaming_commits_each_word_once_with_its_time() -> None:
    lt = transcriber(FakeWhisper(PLAY))
    fed, flushed = run(lt, 25.0)
    assert group_texts(fed + flushed) == UTTERANCES
    assert word_times(fed + flushed) == pytest.approx(PLAY)
    assert lt.transcript.groups == fed + flushed
    assert all(w.start.tzinfo is None for w in lt.transcript.words)
    assert [w.text for w in lt.committed] == [t for t, _, _ in PLAY]


@pytest.mark.parametrize("seed", range(8))
def test_streaming_equals_batch_for_any_block_sizes(seed: int) -> None:
    """However the audio is split into feeds, the result equals decoding it all at once."""
    rng = random.Random(seed)
    blocks = [rng.choice([0.01, 0.1, 0.5, 1.3, 2.9, 3.0, 7.7, 30.0]) for _ in range(200)]
    batch = transcriber(FakeWhisper(PLAY))
    batch.feed(ramp(25.0))
    batch.flush()
    lt = transcriber(FakeWhisper(PLAY))
    fed, flushed = run(lt, 25.0, blocks)
    assert group_texts(fed + flushed) == group_texts(batch.transcript.groups) == UTTERANCES
    assert word_times(fed + flushed) == pytest.approx(word_times(batch.transcript.groups))


def test_a_backlog_longer_than_the_window_is_decoded_in_steps() -> None:
    fake = FakeWhisper(PLAY)
    lt = transcriber(fake, window_s=8.0, force_s=2.0, period_s=1.0)
    groups = lt.feed(ramp(25.0)) + lt.flush()
    assert group_texts(groups) == UTTERANCES
    assert max(b[0] - a[1] for a, b in zip(fake.windows, fake.windows[1:])) <= 0  # every window overlaps the previous one


def commit_times(lt: live.LiveTranscriber, seconds: float, block_s: float = 0.5) -> dict[str, float]:
    """Feed in blocks and note how much audio had arrived when each word was committed."""
    audio = ramp(seconds)
    times: dict[str, float] = {}
    for pos in range(0, len(audio), int(block_s * SR)):
        lt.feed(audio[pos : pos + int(block_s * SR)])
        for w in lt.committed:
            times.setdefault(w.text, lt.audio_s)
    return times


def test_words_commit_when_two_decodes_agree() -> None:
    lt = transcriber(FakeWhisper(speak("pull", 1.0)))
    assert commit_times(lt, 10.0) == {"pull": 6.0}  # heard at 3.0 s, confirmed at 6.0 s
    assert [p.end for p in lt.passes] == [3.0, 6.0, 9.0]


def test_agreed_words_wait_for_hold() -> None:
    """A word two decodes agree on still waits until it ended hold_s ago, so that later audio can revise it."""
    lt = transcriber(FakeWhisper(speak("pull", 2.5)), period_s=1.0, hold_s=1.5)
    assert commit_times(lt, 10.0) == {"pull": 5.0}  # heard at 3.0, agreed at 4.0 (ended only 1.2 s before), committed at 5.0


def test_unstable_words_are_forced_after_force_s() -> None:
    def flip(call: int, words: Script, start: float, end: float) -> Script:
        return [("kaia" if call % 2 else "kaya", s, e) for _, s, e in words]

    lt = transcriber(FakeWhisper(speak("kaia", 1.7), flip), period_s=1.0)
    assert commit_times(lt, 10.0) == {"kaia": 6.0}  # decodes at 3, 4, 5 never agree; at 6 it ended 4 s ago
    assert lt.committed[0].text == "kaia"  # as the forcing decode heard it


def test_no_agreement_on_a_changing_prefix() -> None:
    """Agreement is on a prefix: a later word both decodes heard waits while an earlier one changes."""

    def flip(call: int, words: Script, start: float, end: float) -> Script:
        return [(("kaia" if call % 2 else "kaya") if t == "kaia" else t, s, e) for t, s, e in words]

    lt = transcriber(FakeWhisper(speak("kaia pull", 1.4), flip), period_s=1.0)
    times = commit_times(lt, 10.0)
    assert times == {"kaia": 6.0, "pull": 6.0}


@pytest.mark.parametrize("drift", [0.4, -0.4, 0.15, 1.2, -1.2])
def test_words_re_decoded_with_drifted_times_are_not_duplicated_or_lost(drift: float) -> None:
    def shift(call: int, words: Script, start: float, end: float) -> Script:
        return [(t, s + drift * (call % 2), e + drift * (call % 2)) for t, s, e in words]

    lt = transcriber(FakeWhisper(PLAY, shift))
    run(lt, 25.0)
    assert [w.text for w in lt.committed] == [t for t, _, _ in PLAY]


def test_a_re_decoded_word_with_different_spelling_is_not_committed_again() -> None:
    """Once "crown" is committed, a later decode hearing "crowns" at the same place does not add it."""

    def respell(call: int, words: Script, start: float, end: float) -> Script:
        return [("crowns" if t == "crown" and call >= 2 else t, s + 0.1 * (call >= 2), e + 0.1 * (call >= 2)) for t, s, e in words]

    lt = transcriber(FakeWhisper(speak("and short crown", 1.0) + speak("black pulls", 3.0), respell))
    run(lt, 12.0)
    assert [w.text for w in lt.committed] == ["and", "short", "crown", "black", "pulls"]


@pytest.mark.parametrize(
    ("committed", "hypothesis", "expected"),
    [
        (speak("to kaia", 1.0), speak("to kaia to pikachu", 1.0), ["to", "pikachu"]),  # aligned on text: the repeated "to" is new
        (speak("to kaia", 1.0), speak("to kaia to pikachu", 1.6), ["to", "pikachu"]),  # ...even after drift
        (speak("dump to kaia", 1.0), [("kaya", 1.6, 1.9), ("flick", 2.0, 2.3)], ["flick"]),  # respelled: by time
        ([], speak("flick", 1.0), ["flick"]),
    ],
)
def test_after_commit_point(committed: Script, hypothesis: Script, expected: list[str]) -> None:
    words = [live.TimedWord(*w) for w in committed], [live.TimedWord(*w) for w in hypothesis]
    assert [w.text for w in live.after_commit_point(words[1], words[0])] == expected


# Filtering decodes -----------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("to kaia to kaia to kaia to kaia to kaia", "to kaia"),
        ("flick flick flick flick", "flick"),
        ("backhand to george backhand to hat backhand to george", "backhand to george backhand to hat backhand to george"),  # play-by-play, not a loop
        ("dump to kaia dump to kaia swing to joe", "dump to kaia dump to kaia swing to joe"),  # one repeat is fine
        ("picked up by pikachu, a flick to the end zone. picked up by pikachu, a flick to the end zone.", "picked up by pikachu, a flick to the end zone."),
    ],
)
def test_strip_loops(text: str, expected: str) -> None:
    words = [live.TimedWord(t, i, i + 1) for i, t in enumerate(text.split())]
    assert " ".join(w.text for w in live.strip_loops(words)) == expected


def test_hypothesis_words_are_in_stream_time_without_punctuation_only_words() -> None:
    words = live.hypothesis_words([segment([("Black", 1.0, 1.3), ("!", 1.3, 1.4), ("pulls.", 1.4, 1.8)])], 100.0)
    assert words == [live.TimedWord("Black", 101.0, 101.3, 0.9, -0.3), live.TimedWord("pulls.", 101.4, 101.8, 0.9, -0.3)]


def test_decoding_loops_are_not_committed() -> None:
    def loop(call: int, words: Script, start: float, end: float) -> Script:
        return words + [w for w in speak("to kaia " * 6, 3.0, 0.2) if w[2] <= end]  # a loop decoded at 3-5.4 s

    lt = transcriber(FakeWhisper(speak("picked up by pikachu", 1.0), loop))
    run(lt, 12.0)
    assert lt.transcript.words and " ".join(w.text for w in lt.transcript.words) == "picked up by pikachu to kaia"


@pytest.mark.parametrize(
    ("seg", "expected"),
    [
        (segment(speak("flick to kaia", 0.0)), False),
        (segment(speak("Thanks for watching!", 0.0)), True),
        (segment(speak("Thank you.", 0.0)), True),
        (segment(speak("Thank you, Kaia.", 0.0)), False),  # more than the stock phrase
        (segment(speak("Players: Matt Whitlock (Pikachu), Kaia Mann", 0.0)), True),
        (segment(speak("flick to kaia", 0.0), avg_logprob=-1.4), True),  # failed Whisper's confidence check
        (segment(speak("flick to kaia", 0.0), avg_logprob=float("nan")), True),
        (segment(speak("flick to kaia", 0.0), no_speech_prob=0.9, avg_logprob=-0.4), False),  # confident speech in noise
        ({**segment(speak("to kaia to kaia", 0.0)), "compression_ratio": 4.1}, True),  # failed Whisper's compression check
        ({**segment(speak("to kaia to kaia", 0.0)), "compression_ratio": 3.0}, False),
        (segment([("flick", 1.0, 1.4), ("to", 1.4, 1.4), ("kaia", 1.4, 1.4)]), True),  # most words squeezed into no time
        (segment([("flick", 1.0, 1.4), ("to", 1.4, 1.4), ("kaia", 1.4, 1.8)]), False),
    ],
)
def test_is_hallucination(seg: live.Segment, expected: bool) -> None:
    assert live.is_hallucination(seg) is expected


def test_hallucinated_segments_are_dropped() -> None:
    def noise(call: int, words: Script, start: float, end: float) -> Script:
        return words

    class Noisy(FakeWhisper):
        def __call__(self, audio: np.ndarray, prompt: str | None) -> list[live.Segment]:
            start = float(audio[0]) / SR
            return [*super().__call__(audio, prompt), segment(speak("thanks for watching", start + 6.0), start), segment(speak("go go", start + 1.0), start, 0.95, -1.3)]

    lt = transcriber(Noisy(speak("black pulls", 8.0), noise))
    run(lt, 15.0)
    assert [w.text for w in lt.transcript.words] == ["black", "pulls"]


# Groups ----------------------------------------------------------------------------------------------------------------------------------


def test_groups_close_after_a_pause_without_waiting_for_more_words() -> None:
    lt = transcriber(FakeWhisper(speak("picked up by pikachu", 1.0) + speak("backhand to glasses", 30.0)))
    audio = ramp(40.0)
    closed_at: list[float] = []
    for pos in range(0, len(audio), SR // 10):
        if lt.feed(audio[pos : pos + SR // 10]):
            closed_at.append(lt.audio_s)
    assert closed_at == [6.0, 36.0]  # committed at 6 s, when nothing followed for over gap_s; not when the next words came
    assert lt.flush() == []
    assert group_texts(lt.transcript.groups) == ["picked up by pikachu", "backhand to glasses"]


def test_groups_split_at_pauses_longer_than_gap() -> None:
    script = speak("dump to", 1.0) + speak("kaia", 1.6 + 0.55) + speak("swing to", 2.45 + 0.65) + speak("joe", 3.7 + 0.7)
    lt = transcriber(FakeWhisper(script))
    fed, flushed = run(lt, 12.0)
    assert group_texts(fed + flushed) == ["dump to kaia", "swing to", "joe"]


def test_flush_commits_what_is_pending() -> None:
    lt = transcriber(FakeWhisper(speak("picked up by pikachu", 1.0) + speak("for the score", 7.0)))
    fed, flushed = run(lt, 8.0)
    assert group_texts(fed) == ["picked up by pikachu"]
    assert group_texts(flushed) == ["for the score"]
    assert lt.flush() == []
    with pytest.raises(RuntimeError, match="after flush"):
        lt.feed(ramp(1.0))


def test_flush_without_new_audio_commits_the_last_hypothesis() -> None:
    fake = FakeWhisper(speak("for the score", 1.0))
    lt = transcriber(fake)
    lt.feed(ramp(3.0))
    assert lt.pending_text == "for the score" and lt.open_text == ""
    assert group_texts(lt.flush()) == ["for the score"]
    assert len(fake.windows) == 1


def test_pending_and_open_text() -> None:
    lt = transcriber(FakeWhisper(speak("dump to feather brush and then a long", 1.0)), tr.load_replacements("ultimate/indoor", teams()), period_s=1.0)
    lt.feed(ramp(2.0))
    assert (lt.open_text, lt.pending_text) == ("", "dump to feather")
    lt.feed(ramp(3.0)[2 * SR :])
    assert (lt.open_text, lt.pending_text) == ("dump to feather", "brush and then")
    lt.feed(ramp(4.0)[3 * SR :])
    assert (lt.open_text, lt.pending_text) == ("dump to Adam Federbusch and then", "a long")


def teams() -> list[yus.Team]:
    return tr.load_teams_from_files([DATA / "team_dump_and_drizzle.json", DATA / "team_category_5.json"])


def test_mondegreens_are_replaced_when_a_group_closes_even_across_commits() -> None:
    """ "feather" and "brush" are committed by different decodes; the closed group still says Adam Federbusch."""
    script = speak("huck to feather", 1.0) + [("brush.", 2.0, 2.6)] + speak("steven picks", 8.0)
    lt = transcriber(FakeWhisper(script), tr.load_replacements("ultimate/indoor", teams()), period_s=1.0, hold_s=0.5)
    fed, flushed = run(lt, 14.0)
    assert group_texts(fed + flushed) == ["huck to Adam Federbusch.", "Stephen Butler picks"]
    merged = (fed + flushed)[0].words[2]
    assert (merged.start - T0, merged.duration) == (dt.timedelta(seconds=1.6), dt.timedelta(seconds=1.0))
    assert lt.fired == Counter({("feather brush", "Adam Federbusch"): 1, ("steven", "Stephen Butler"): 1})
    assert [w.text for w in lt.committed] == ["huck", "to", "feather", "brush.", "steven", "picks"]  # committed words keep what was heard


def test_prompt_is_passed_to_every_decode() -> None:
    fake = FakeWhisper(PLAY)
    run(transcriber(fake), 10.0)
    assert {prompt for _, _, prompt in fake.windows} == {"Players: Kaia Mann."}
    assert [round(end - start, 3) for start, end, _ in fake.windows] == [3.0, 6.0, 9.0, 10.0]


def test_windows_slide() -> None:
    fake = FakeWhisper(PLAY)
    run(transcriber(fake, window_s=8.0, force_s=3.0), 25.0)
    assert [(round(a, 3), round(b, 3)) for a, b, _ in fake.windows][:4] == [(0.0, 3.0), (0.0, 6.0), (1.0, 9.0), (4.0, 12.0)]


def test_other_sample_rates_are_resampled() -> None:
    heard: list[int] = []

    def fake(audio: np.ndarray, prompt: str | None) -> list[live.Segment]:
        heard.append(len(audio))
        return [segment([("pull", 1.0, 1.5)])] if len(audio) >= 3 * SR else []

    lt = live.LiveTranscriber(T0, None, sample_rate=48000, transcribe=fake)
    tone = np.sin(np.arange(48000 * 10) / 48000 * 2 * np.pi * 440).astype(np.float32)
    groups = [g for pos in range(0, len(tone), 4800) for g in lt.feed(tone[pos : pos + 4800])] + lt.flush()
    assert abs(lt.audio_s - 10.0) < 0.05
    assert 3 * SR <= heard[0] <= 3.2 * SR
    assert group_texts(groups) == ["pull"]
    assert groups[0].start == T0 + dt.timedelta(seconds=1.0)


def test_invalid_settings() -> None:
    with pytest.raises(ValueError, match="force_s"):
        live.LiveTranscriber(T0, transcribe=FakeWhisper([]), window_s=6.0, force_s=4.0, period_s=3.0)


# Simulated live arrival ------------------------------------------------------------------------------------------------------------------


class SlowFake(FakeWhisper):
    """A fake decoder that takes `compute` seconds on a fake clock."""

    def __init__(self, script: Script, compute: float) -> None:
        super().__init__(script)
        self.compute = compute
        self.now = 0.0

    def __call__(self, audio: np.ndarray, prompt: str | None) -> list[live.Segment]:
        self.now += self.compute
        return super().__call__(audio, prompt)

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.mark.parametrize(("compute", "ends"), [(1.0, [3.0, 6.0, 9.0, 12.0, 15.0]), (4.0, [3.0, 7.0, 11.0, 15.0])])
def test_simulation_accounts_for_compute(compute: float, ends: list[float]) -> None:
    """Audio that arrives during a decode waits for it: a decoder slower than the period decodes less often, each time all that arrived."""
    fake = SlowFake(speak("pull", 1.0) + speak("flick to kaia", 8.0), compute)
    lt = transcriber(fake)
    timings = live.simulate(lt, ramp(16.0), clock=fake.clock, sleep=fake.sleep)
    assert [p.end for p in lt.passes][:-1] == pytest.approx(ends)
    assert [round(e, 3) for e, _ in timings.commits] == [1.3, 8.3, 8.6, 8.9]
    committed_at = [c for _, c in timings.commits]
    if compute == 1.0:
        assert committed_at == pytest.approx([6.0 + 1.0, 12.0 + 1.0, 12.0 + 1.0, 12.0 + 1.0])  # heard at 3 and 9, agreed at 6 and 12
    else:
        assert committed_at == pytest.approx([7.0 + 4.0, 15.0 + 4.0, 15.0 + 4.0, 15.0 + 4.0])
    assert timings.word_latency == pytest.approx([c - e for e, c in timings.commits])
    assert timings.busy == pytest.approx(compute * len(lt.passes) / 16.0)
    assert "Word latency (end of word -> committed): median" in timings.summary()


def test_real_time_simulation_gives_the_same_transcript() -> None:
    fake = SlowFake(PLAY, 0.5)
    lt = transcriber(fake)
    timings = live.simulate(lt, ramp(25.0), speed=1.0, clock=fake.clock, sleep=fake.sleep)
    assert group_texts(lt.transcript.groups) == UTTERANCES
    assert len(timings.word_latency) == len(PLAY) and min(timings.word_latency) >= 1.0


def test_live_prompt() -> None:
    roster = ", ".join(tr.load_roster(teams()))
    assert live.live_prompt(teams()) == f"Players: {roster}."  # the sport's terms made Whisper repeat them
    assert live.live_prompt(teams(), prefix="Indoor ultimate.", extra_terms=["pikachu special"]) == f"Indoor ultimate. Players: {roster}. Terms: pikachu special."
    full = live.live_prompt(teams(), sport_terms=True)
    assert full.startswith(f"Players: {roster}. Terms: flick, backhand,") and tr.estimate_tokens(" " + full) <= tr.PROMPT_TOKEN_BUDGET


def test_faster_whisper_segments_become_dicts() -> None:
    word = SimpleNamespace(word=" Kaia", start=1.0, end=1.4, probability=0.8)
    seg = SimpleNamespace(text=" Kaia", start=1.0, end=1.4, avg_logprob=-0.2, compression_ratio=0.8, no_speech_prob=0.1, words=[word], tokens=[1, 2])
    assert live.segment_dict(seg) == {
        "text": " Kaia",
        "start": 1.0,
        "end": 1.4,
        "avg_logprob": -0.2,
        "compression_ratio": 0.8,
        "no_speech_prob": 0.1,
        "words": [{"word": " Kaia", "start": 1.0, "end": 1.4, "probability": 0.8}],
    }


def test_decode_options_match_backend_signatures() -> None:
    from faster_whisper import WhisperModel

    assert {*live.DECODE_OPTIONS, "language", "vad_filter", "initial_prompt"} <= set(inspect.signature(WhisperModel.transcribe).parameters)
    mlx_whisper = pytest.importorskip("mlx_whisper", reason="mlx-whisper is only installed on Apple Silicon (uv sync --extra mlx)")
    from mlx_whisper.decoding import DecodingOptions

    accepted = set(inspect.signature(mlx_whisper.transcribe).parameters) | set(inspect.signature(DecodingOptions).parameters)
    assert {*live.DECODE_OPTIONS, "language", "initial_prompt", "verbose", "path_or_hf_repo"} <= accepted


def test_cli_defaults() -> None:
    args = live.build_arg_parser().parse_args(["game.ogg", "--team", "a.json", "--team", "b.json"])
    assert (args.speed, args.period, args.window, args.hold, args.force, args.model, args.mondegreens) == (0.0, 3.0, 20.0, 1.0, 4.0, "large-v3-turbo", True)
    assert args.teams == [pathlib.Path("a.json"), pathlib.Path("b.json")]


# Real audio ------------------------------------------------------------------------------------------------------------------------------

AUDIO = pathlib.Path(os.environ.get("YUS_DATA", pathlib.Path.home() / "Documents/Personal/yus-data")) / "drive/20250114T2030-0700.ogg"


def tokens(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]+", " ", text.lower().replace("-", " ")).split()


def wer(reference: list[str], hypothesis: list[str]) -> float:
    row = list(range(len(hypothesis) + 1))
    for i, ref in enumerate(reference, 1):
        prev, row[0] = row[0], i
        for j, hyp in enumerate(hypothesis, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ref != hyp))
    return row[-1] / len(reference)


def test_wer_helper() -> None:
    assert wer(["a", "b", "c", "d"], ["a", "x", "c"]) == 0.5


@pytest.mark.skipif(os.environ.get("YUS_SLOW_TESTS") != "1", reason="needs the Whisper model, a GPU and the game's audio: set YUS_SLOW_TESTS=1")
def test_live_wer_on_real_audio() -> None:
    """The first 120 s of the 2025-01-14 20:30 game (audio t=0 is 20:30:33), live, against the hand-made transcript."""
    pytest.importorskip("mlx_whisper", reason="mlx-whisper is only installed on Apple Silicon (uv sync --extra mlx)")
    if not AUDIO.exists():
        pytest.skip(f"no audio at {AUDIO}")
    whisper = live.MlxWhisper("large-v3-turbo")
    lt = live.LiveTranscriber(T0, live.live_prompt(teams(), whisper), tr.load_replacements("ultimate/indoor", teams()), transcribe=whisper)
    timings = live.simulate(lt, live.load_audio(AUDIO)[: 120 * SR])
    cut = T0 + dt.timedelta(seconds=118)  # a word under way at 120 s may be cut off
    reference = yus.Transcript.model_validate_json((DATA / "gruindoor_20250114T2030-transcript.json").read_text())
    expected = [t for w in reference.words if w.start < cut for t in tokens(w.text)]
    heard = [t for w in lt.transcript.words if w.start < cut for t in tokens(w.text)]
    assert wer(expected, heard) < 0.25
    assert live.quantile(timings.word_latency, 0.5) < 12.0
