"""Live transcription: audio arriving in real time becomes committed words, grouped into TranscriptGroups.

Every `period_s` seconds of new audio, Whisper re-decodes the last `window_s` seconds. A word is committed once two
consecutive decodes agree on it (LocalAgreement-2) and it ended `hold_s` ago, or once it ended `force_s` ago.
See docs/live_transcription.md.

Exposed as the yus-live-transcribe command-line tool, which plays an audio file as if it arrived live.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import pathlib
import statistics
import sys
import threading
import time
from collections import Counter
from typing import Any, Callable, NamedTuple, Protocol, Sequence

import numpy as np
import pydantic

import yus
from yus.processing.transcription import transcribe as tr

SAMPLE_RATE = 16000  # Whisper's

# A decode returns Whisper segments as dicts: "words" (each with "word", "start", "end", "probability"; seconds from the start of the decoded
# audio), plus "text" and, optionally, the decode's "avg_logprob" and "compression_ratio".
Segment = dict[str, Any]
Transcribe = Callable[[np.ndarray, str | None], list[Segment]]

# Greedy decoding only: Whisper's fallback to higher temperatures took up to 7 s per window and mostly produced loops. A decode that fails
# Whisper's confidence check (logprob) or a compression check is dropped instead; repetitive play-by-play compresses up to about 3.
DECODE_OPTIONS: dict[str, Any] = {"temperature": 0.0, "condition_on_previous_text": False, "word_timestamps": True}
LOW_LOGPROB = -1.0
HIGH_COMPRESSION = 3.5
# Whisper invents these on noise (its training data has many subtitles); a segment saying only one of them is dropped.
HALLUCINATIONS = frozenset({"thank you", "thanks for watching", "thank you for watching", "please subscribe", "you", "bye"})
# A segment repeating the prompt back ("Players: Kaia Mann, ...") is dropped.
PROMPT_ECHOES = ("players:", "terms:")

# Committed words a new decode is aligned against, to skip words it re-transcribes with drifted times.
ALIGN_WORDS = 8


class TimedWord(NamedTuple):
    """A decoded word, with times in seconds from the start of the stream."""

    text: str
    start: float
    end: float
    probability: float = 0.0
    logprob: float = 0.0  # avg_logprob of its Whisper segment


class DecodePass(pydantic.BaseModel):
    """One decode of the trailing window."""

    end: float = pydantic.Field(..., description="Seconds of the stream decoded (the end of the window).")
    compute: float = pydantic.Field(..., description="Seconds the decode took.")
    words: int = pydantic.Field(0, description="Words hypothesized after the commit point.")
    committed: int = pydantic.Field(0, description="Words committed by this pass.")


def _key(word: TimedWord) -> str:
    return tr.normalize_token(word.text)


def is_hallucination(segment: Segment) -> bool:
    """True for a segment Whisper probably invented: from a decode that failed Whisper's confidence or compression check, with most words
    squeezed into no time (Whisper could not place them in the audio), a stock subtitle phrase, or the prompt echoed back."""
    # mlx-whisper reports a NaN avg_logprob for about 1 decode in 6, most of them good; like Whisper's own check, NaN passes.
    if float(segment.get("avg_logprob") or 0.0) < LOW_LOGPROB or float(segment.get("compression_ratio") or 0.0) > HIGH_COMPRESSION:
        return True
    words = segment.get("words") or []
    if 2 * sum(float(w["end"]) - float(w["start"]) < 0.005 for w in words) > len(words):
        return True
    text = " ".join(str(w["word"]) for w in words) or str(segment.get("text", ""))
    return " ".join(tr.phrase_key(text)) in HALLUCINATIONS or any(echo in text.lower() for echo in PROMPT_ECHOES)


def word_probability(word: dict[str, Any]) -> float:
    """A decoded word's probability; 0 when missing or NaN (a NaN would make the transcript's JSON invalid)."""
    probability = float(word.get("probability") or 0.0)
    return 0.0 if math.isnan(probability) else probability


def segment_logprob(segment: Segment) -> float:
    """The segment's avg_logprob or, when mlx-whisper reports NaN, the mean log probability of its words."""
    logprob = float(segment.get("avg_logprob") or 0.0)
    if math.isnan(logprob):
        probs = [word_probability(w) for w in segment.get("words") or []]
        return statistics.fmean(math.log(max(p, 1e-6)) for p in probs) if probs else LOW_LOGPROB
    return logprob


def _loop_at(keys: Sequence[str], i: int) -> int:
    """The length of the phrase a loop starting at `i` repeats, or 0."""
    for n in range(1, 21):
        reps = 3 if n < 6 else 2
        if i + n * reps <= len(keys) and all(keys[i + k * n : i + (k + 1) * n] == keys[i : i + n] for k in range(1, reps)):
            return n
    return 0


def strip_loops(words: list[TimedWord]) -> list[TimedWord]:
    """Drop the repeats of decoding loops from a hypothesis, keeping the first copy and every other word. Play-by-play repeats a short
    phrase at most twice in a row ("backhand to george, backhand to hat"), so a loop is a 1-5 word phrase said 3+ times in a row, or
    a 6-20 word phrase twice. A partial repeat right after the loop goes too (2+ words, or any at the end of the decode): Whisper often
    leaves a loop mid-phrase. Words after a loop are kept: they are usually real speech, and a phrase that was really said twice loses
    only its second copy."""
    keys = [_key(w) for w in words]
    kept: list[TimedWord] = []
    i = 0
    while i < len(keys):
        if not (n := _loop_at(keys, i)):
            kept.append(words[i])
            i += 1
            continue
        kept += words[i : i + n]
        i += n
        while keys[i : i + n] == keys[i - n : i]:
            i += n
        partial = 0
        while partial < n - 1 and i + partial < len(keys) and keys[i + partial] == keys[i - n + partial]:
            partial += 1
        if partial >= 2 or i + partial == len(keys):
            i += partial
    return kept


def hypothesis_words(segments: Sequence[Segment], offset: float) -> list[TimedWord]:
    """The words of one decode, in stream seconds (`offset` is where the decoded audio starts), without hallucinated segments or loops."""
    words: list[TimedWord] = []
    for seg in segments:
        if is_hallucination(seg):
            continue
        logprob = segment_logprob(seg)
        for w in seg.get("words") or []:
            if tr.normalize_token(text := str(w["word"]).strip()):  # not just punctuation
                words.append(TimedWord(text, offset + float(w["start"]), offset + float(w["end"]), word_probability(w), logprob))
    return strip_loops(words)


def _ended_prefix(words: Sequence[TimedWord], before: float) -> int:
    """How many leading words ended by `before`."""
    n = 0
    while n < len(words) and words[n].end <= before:
        n += 1
    return n


def _agreed_prefix(a: Sequence[TimedWord], b: Sequence[TimedWord]) -> int:
    n = 0
    while n < min(len(a), len(b)) and _key(a[n]) == _key(b[n]):
        n += 1
    return n


def after_commit_point(hypothesis: list[TimedWord], committed: Sequence[TimedWord]) -> list[TimedWord]:
    """The words of a decode that follow the last committed word. Word times drift between decodes, so the decode is first aligned on the
    text of the committed words it repeats (the match ending nearest the commit point); without such a match, words whose middle is past the
    commit point are new."""
    if not committed:
        return hypothesis
    commit_point = committed[-1].end
    keys = [_key(w) for w in hypothesis]
    tail = [_key(w) for w in committed[-ALIGN_WORDS:]]
    for k in range(len(tail), 0, -1):
        tolerance = 1.0 if k == 1 else 2.0  # seconds a repeated word's end may drift
        ends = [(abs(hypothesis[j + k - 1].end - commit_point), j + k) for j in range(len(keys) - k + 1) if keys[j : j + k] == tail[-k:]]
        if matches := [m for m in ends if m[0] <= tolerance]:
            return hypothesis[min(matches)[1] :]
    return [w for w in hypothesis if (w.start + w.end) / 2 > commit_point]


def unheard(previous: Sequence[TimedWord], final: Sequence[TimedWord]) -> list[TimedWord]:
    """The leading words of the previous decode's uncommitted hypothesis that the final decode did not hear again: those before the
    final decode's first word, found by its text (within 1 s, for drift) or else by time; all of them if the final decode heard nothing."""
    if not final:
        return list(previous)
    first = final[0]
    for j, word in enumerate(previous):
        if _key(word) == _key(first) and abs(word.start - first.start) <= 1.0:
            return list(previous[:j])
    return [w for w in previous if w.end <= first.start]


class LiveTranscriber:
    """Turn audio arriving in real time into a Transcript, a group at a time.

    Feed audio as it arrives; each call returns the TranscriptGroups completed by then. Every `period_s` seconds of new audio, the last
    `window_s` seconds are decoded with the static `prompt` (see `live_prompt`). Words after the commit point are committed when two
    consecutive decodes agree on them and they ended `hold_s` ago, or when they ended `force_s` ago. A group closes once a pause of more
    than `gap_s` follows its last committed word. Known mishearings (`replacements`, see transcribe.load_replacements) are replaced when
    a group closes. Word times are `start` plus their offset in the stream, as naive local times like yus-transcribe's.

    `transcribe(audio, prompt)` decodes 16 kHz mono float32 audio into Whisper segments (see `Segment`); the default loads a Whisper
    `model` with `backend` ("auto", "mlx" or "faster-whisper"; see `load_whisper`).
    """

    def __init__(
        self,
        start: dt.datetime,
        prompt: str | None = None,
        replacements: tr.Replacements | None = None,
        model: str = "large-v3-turbo",
        backend: str = "auto",
        sample_rate: int = SAMPLE_RATE,
        period_s: float = 3.0,
        window_s: float = 20.0,
        hold_s: float = 1.0,
        force_s: float = 4.0,
        transcribe: Transcribe | None = None,
        gap_s: float = 0.6,
    ) -> None:
        self._step = int((window_s - force_s - period_s) * SAMPLE_RATE)  # samples per decode when a backlog is decoded in steps
        if not (0 < period_s and self._step >= 1):
            raise ValueError(f"need 0 < period_s and force_s + period_s < window_s, got period_s={period_s}, force_s={force_s}, window_s={window_s}")
        self.start = tr.local_naive(start)
        self.prompt = prompt or None
        self.replacements = replacements or {}
        self.sample_rate = sample_rate
        self.period_s, self.window_s, self.hold_s, self.force_s, self.gap_s = period_s, window_s, hold_s, force_s, gap_s
        self.transcript = yus.Transcript()
        self.committed: list[TimedWord] = []  # every committed word, before mondegreen replacement
        self.passes: list[DecodePass] = []
        self.fired: Counter[tuple[str, str]] = Counter()  # mondegreens replaced: (mishearing, replacement) -> count
        self._transcribe = transcribe or load_whisper(backend, model)
        self._resampler = _Resampler(sample_rate) if sample_rate != SAMPLE_RATE else None
        self._buffer = np.zeros(0, dtype=np.float32)  # the last window_s seconds, at 16 kHz
        self._received = 0  # 16 kHz samples received
        self._decoded = 0  # ...when the last decode ran
        self._open: list[TimedWord] = []  # committed words of the group not yet closed
        self._pending: list[TimedWord] = []  # the last decode's uncommitted words
        self._horizon = 0.0
        self._flushed = False

    @property
    def pending_text(self) -> str:
        """The latest decode's words after the commit point, not committed yet: a guess at what is being said, for display."""
        return " ".join(w.text for w in self._pending)

    @property
    def open_text(self) -> str:
        """Committed words of the group still open, with mondegreens replaced."""
        texts = [w.text for w in self._open]
        for a, b, text in reversed(tr.find_replacements(texts, self.replacements)):
            texts[a:b] = [text]
        return " ".join(texts)

    @property
    def audio_s(self) -> float:
        """Seconds of audio received."""
        return self._received / SAMPLE_RATE

    @property
    def horizon(self) -> dt.datetime:
        """The time up to which every word has been returned in a group, for EventExtractor.advance(): the start of the first word of the
        open group or of the pending hypothesis or, with neither, the end of the last committed word or the start of the next decode's
        window (`window_s - period_s` before the end of the latest decode: no later decode hears earlier audio), whichever is later. A word
        can still start a little before it when a decode moves its time (about 1% of words, by under 1 s, in replays of the measured game).
        It never decreases; after flush() it is the end of the audio."""
        return self.start + dt.timedelta(seconds=round(self.audio_s if self._flushed else self._horizon, 3))

    def feed(self, samples: np.ndarray) -> list[yus.TranscriptGroup]:
        """Add mono audio at `sample_rate` that just arrived; return the groups completed by it. Decodes when `period_s` of new audio has
        arrived, once per call however much arrived (a decoder that fell behind skips ahead), except that a backlog too long for one window
        is decoded in steps so that no audio goes undecoded."""
        if self._flushed:
            raise RuntimeError("feed() after flush(): the stream has ended")
        audio = np.asarray(samples, dtype=np.float32)
        if audio.size != max(audio.shape, default=0):
            raise ValueError(f"feed() takes mono audio, got samples of shape {audio.shape}")
        audio = audio.reshape(-1)
        if self._resampler:
            audio = self._resampler.resample(audio)
        groups: list[yus.TranscriptGroup] = []
        for i in range(0, len(audio), self._step):
            self._append(audio[i : i + self._step])
            if self._received - self._decoded >= self.period_s * SAMPLE_RATE:
                groups += self._decode(final=False)
        return groups

    def flush(self) -> list[yus.TranscriptGroup]:
        """End the stream: decode what is left, commit every word (the final decode's, and the previous decode's words before them that
        it did not hear again), and return the remaining groups."""
        if self._flushed:
            return []
        if self._resampler:
            self._append(self._resampler.resample(None))
        if self._received > self._decoded:
            groups = self._decode(final=True)
        else:
            groups = self._commit(self._pending)
            self._pending = []
        if self._open:
            groups.append(self._close())
        self._flushed = True
        return groups

    def _append(self, audio: np.ndarray) -> None:
        keep = int(self.window_s * SAMPLE_RATE)
        self._buffer = np.concatenate([self._buffer, audio])[-keep:]
        self._received += len(audio)

    def _decode(self, final: bool) -> list[yus.TranscriptGroup]:
        now = self._received / SAMPLE_RATE
        self._decoded = self._received
        began = time.perf_counter()
        segments = self._transcribe(self._buffer, self.prompt) if len(self._buffer) else []
        compute = time.perf_counter() - began
        new = after_commit_point(hypothesis_words(segments, now - len(self._buffer) / SAMPLE_RATE), self.committed)
        if final:  # commit everything, keeping what the previous decode heard and this one did not
            new = unheard(self._pending, new) + new
            n = len(new)
        else:
            held = _ended_prefix(new[: _agreed_prefix(new, self._pending)], now - self.hold_s)
            n = max(held, _ended_prefix(new, now - self.force_s))
        groups = self._commit(new[:n])
        self._pending = new[n:]
        if self._open and self._paused(now):
            groups.append(self._close())
        delivered = max(self.committed[-1].end if self.committed else 0.0, now + self.period_s - self.window_s)
        self._horizon = max(self._horizon, min([delivered] + [words[0].start for words in (self._open, self._pending) if words]))
        self.passes.append(DecodePass(end=now, compute=compute, words=len(new), committed=n))
        return groups

    def _paused(self, now: float) -> bool:
        """Whether the latest decode heard a pause of more than gap_s after the last committed word."""
        last = self._open[-1].end
        if self._pending:
            return self._pending[0].start - last > self.gap_s
        return now - last > self.gap_s + self.hold_s

    def _commit(self, words: Sequence[TimedWord]) -> list[yus.TranscriptGroup]:
        groups: list[yus.TranscriptGroup] = []
        for word in words:
            if self._open and word.start - self._open[-1].end > self.gap_s:
                groups.append(self._close())
            self._open.append(word)
            self.committed.append(word)
        return groups

    def _close(self) -> yus.TranscriptGroup:
        words = [
            yus.Word(
                text=w.text,
                confidence=w.probability,
                start=self.start + dt.timedelta(seconds=round(w.start, 3)),
                duration=dt.timedelta(seconds=round(max(0.0, w.end - w.start), 3)),
            )
            for w in self._open
        ]
        group = self.transcript.add_group()
        group.add_interpretation(confidence=statistics.fmean(w.logprob for w in self._open)).words.extend(tr.replace_mondegreens(words, self.replacements, self.fired))
        self._open = []
        return group


class _Resampler:
    """Stream audio at another sample rate to 16 kHz (PyAV, installed with faster-whisper)."""

    def __init__(self, sample_rate: int) -> None:
        import av  # type: ignore[import-not-found]

        self.sample_rate = sample_rate
        self._av = av
        self._resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)

    def resample(self, audio: np.ndarray | None) -> np.ndarray:
        """Resample the next samples; None drains what the resampler holds back."""
        frame = None
        if audio is not None:
            if not len(audio):
                return audio
            frame = self._av.AudioFrame.from_ndarray(np.ascontiguousarray(audio).reshape(1, -1), format="flt", layout="mono")
            frame.sample_rate = self.sample_rate
        out = [f.to_ndarray().reshape(-1) for f in self._resampler.resample(frame)]
        return np.concatenate(out).astype(np.float32) if out else np.zeros(0, dtype=np.float32)


# Whisper backends ------------------------------------------------------------------------------------------------------------------------


class Whisper(Protocol):
    """A Transcribe callable that can also count prompt tokens with its model's tokenizer."""

    def __call__(self, audio: np.ndarray, prompt: str | None) -> list[Segment]: ...

    def count_tokens(self, text: str) -> int: ...


_MLX_LOCK = threading.Lock()


class MlxWhisper:
    """Decode with mlx-whisper on an Apple Silicon GPU. mlx-whisper caches one model per repo, shared by every instance, so decodes
    run one at a time (several commentators' transcribers in threads take turns on the GPU)."""

    def __init__(self, model: str = "large-v3-turbo", language: str = "en", **options: Any) -> None:
        import mlx.core as mx  # type: ignore[import-not-found]
        import mlx_whisper  # type: ignore[import-not-found]
        from mlx_whisper.transcribe import ModelHolder  # type: ignore[import-not-found]

        self.repo = tr.resolve_hf_repo_id(model, "mlx") or model
        self._transcribe = mlx_whisper.transcribe
        self._model = ModelHolder.get_model(self.repo, mx.float16)  # mlx_whisper.transcribe reuses this cached model
        self._count = tr.mlx_token_counter(self._model, language)
        self.options = {**DECODE_OPTIONS, "language": language, **options}

    def __call__(self, audio: np.ndarray, prompt: str | None) -> list[Segment]:
        with _MLX_LOCK:  # the patched model is shared by every MlxWhisper of the same model, in any thread
            self._model.decode = OneWindow(self._model.decode)
            try:
                return list(self._transcribe(audio, path_or_hf_repo=self.repo, initial_prompt=prompt, verbose=None, **self.options)["segments"])
            finally:
                del self._model.decode  # back to the class's decode

    def count_tokens(self, text: str) -> int:
        return self._count(text)


class OneWindow:
    """Wrap mlx-whisper's model.decode for one transcribe() call so that only the first 30-second window is decoded.

    When a decode ends with two timestamps, as it often does at the end of a live window, transcribe() decodes the audio after the last
    timestamp again: a full encoder pass, usually over a fraction of a second of audio. On the measured game that was 1 decode in 9,
    9% of decoding time, and replaying the decodes without those second passes gave the same transcript: the next decode hears that audio.
    Later windows are reported as silence (transcribe() then skips them); temperature fallback still re-decodes the first window."""

    def __init__(self, decode: Callable[[Any, Any], Any]) -> None:
        self.decode = decode
        self.first: Any = None

    def __call__(self, mel: Any, options: Any) -> Any:
        if self.first is None:
            self.first = mel
        if mel is self.first:
            return self.decode(mel, options)
        from mlx_whisper.decoding import DecodingResult  # type: ignore[import-not-found]

        return DecodingResult(audio_features=None, language=options.language, avg_logprob=-math.inf, no_speech_prob=1.0, temperature=options.temperature, compression_ratio=0.0)


class FasterWhisper:
    """Decode with faster-whisper (CTranslate2) on an NVIDIA GPU or the CPU."""

    def __init__(self, model: str = "large-v3-turbo", language: str = "en", device: str = "auto", compute_type: str = "default", **options: Any) -> None:
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]

        self._model = WhisperModel(model, device=tr.resolve_device(device), compute_type=compute_type)
        self._count = tr.faster_whisper_token_counter(self._model, language)
        self.options = {**DECODE_OPTIONS, "language": language, "vad_filter": False, **options}

    def __call__(self, audio: np.ndarray, prompt: str | None) -> list[Segment]:
        segments, _ = self._model.transcribe(audio, initial_prompt=prompt, **self.options)
        return [segment_dict(seg) for seg in segments]

    def count_tokens(self, text: str) -> int:
        return self._count(text)


def segment_dict(segment: Any) -> Segment:
    """A faster-whisper Segment as the dict mlx-whisper returns."""
    words = [{"word": w.word, "start": w.start, "end": w.end, "probability": w.probability} for w in segment.words or []]
    fields = ("text", "start", "end", "avg_logprob", "compression_ratio", "no_speech_prob")
    return {**{name: getattr(segment, name) for name in fields}, "words": words}


def load_whisper(backend: str = "auto", model: str = "large-v3-turbo", language: str = "en") -> Whisper:
    """Load a Whisper model for live decoding: mlx on Apple Silicon (backend "auto" prefers it, see transcribe.resolve_backend), else faster-whisper."""
    return MlxWhisper(model, language) if tr.resolve_backend(backend) == "mlx" else FasterWhisper(model, language)


def live_prompt(
    teams: list[yus.Team], whisper: Whisper | None = None, *, sport: str = "ultimate/indoor", prefix: str = "", extra_terms: Sequence[str] = (), sport_terms: bool = False
) -> str:
    """The static prompt for every decode: `prefix`, the roster, then `extra_terms` (and, with `sport_terms`, the sport's terms), within
    Whisper's 223-token prompt budget. The sport's terms are left out by default: priming every decode with that list made Whisper repeat
    it ("swing to, swing to, ..."), adding loops, errors and compute."""
    count = whisper.count_tokens if whisper else tr.estimate_tokens
    terms = tr.load_terms(sport if sport_terms else "", extra_terms)
    return tr.build_prompt(tr.load_roster(teams), terms, prefix=prefix, count_tokens=count)


# Simulated live arrival ------------------------------------------------------------------------------------------------------------------


class LiveTimings(pydantic.BaseModel):
    """When words and groups were committed during a (simulated) live run, in seconds of stream time."""

    audio: float = 0.0
    speed: float = pydantic.Field(0.0, description="How fast the audio was played: 1 in real time, 2 twice as fast; 0 on a simulated real-time clock.")
    compute: float = pydantic.Field(0.0, description="Seconds spent in feed() and flush(), nearly all of it decoding.")
    word_latency: list[float] = pydantic.Field(default_factory=list, description="For each committed word: from the end of the word to its commit.")
    group_latency: list[float] = pydantic.Field(default_factory=list, description="For each group: from the end of its last word to the group's close.")
    commits: list[tuple[float, float]] = pydantic.Field(default_factory=list, description="For each committed word: (end of the word, commit time).")

    @property
    def busy(self) -> float:
        """Fraction of the playing time the decoder was busy (GPU busy fraction): the audio plays in audio / speed seconds."""
        return self.compute * (self.speed or 1.0) / self.audio if self.audio else 0.0

    def summary(self) -> str:
        def stats(values: list[float]) -> str:
            return ", ".join(f"{name} {quantile(values, q):.1f} s" for name, q in (("median", 0.5), ("p90", 0.9), ("p95", 0.95), ("max", 1.0))) if values else "none"

        return (
            f"Word latency (end of word -> committed): {stats(self.word_latency)} over {len(self.word_latency)} words\n"
            f"Group latency (end of group -> closed): {stats(self.group_latency)} over {len(self.group_latency)} groups\n"
            f"GPU busy decoding {self.busy:.0%} of the time ({self.compute:.0f} s for {self.audio:.0f} s of audio{f' at {self.speed:g}x' if self.speed else ''})"
        )


def quantile(values: Sequence[float], q: float) -> float:
    """The value at fraction q of the sorted values (lower nearest rank)."""
    ordered = sorted(values)
    return ordered[int(q * (len(ordered) - 1))]


def simulate(
    transcriber: LiveTranscriber,
    audio: np.ndarray,
    *,
    speed: float = 0.0,
    block_s: float = 0.1,
    on_groups: Callable[[list[yus.TranscriptGroup], float], None] | None = None,
    clock: Callable[[], float] = time.perf_counter,
    sleep: Callable[[float], None] = time.sleep,
) -> LiveTimings:
    """Feed `audio` (at the transcriber's sample rate) as if it arrived live, in blocks of `block_s`, and time each commit.

    speed 1 plays it in real time and `speed` times faster above that; speed 0 runs as fast as possible on a simulated clock that still
    accounts for compute: audio arriving while a decode runs waits for it, so the next decode sees all of it at once.
    `on_groups(groups, now)` is called with each batch of completed groups."""
    sample_rate = transcriber.sample_rate
    block = max(1, int(block_s * sample_rate))
    timings = LiveTimings(audio=len(audio) / sample_rate, speed=speed)
    began = clock()
    pos, now = 0, 0.0
    while pos < len(audio):
        if speed > 0:
            arrived = min(len(audio), int((clock() - began) * speed * sample_rate))
            if arrived - pos < min(block, len(audio) - pos):
                sleep(max(0.0, (pos + block) / sample_rate / speed - (clock() - began)))
                continue
        else:
            arrived = min(len(audio), max(pos + block, int(now * sample_rate)))
        tick = clock()
        groups = transcriber.feed(audio[pos:arrived])
        timings.compute += clock() - tick
        pos = arrived
        now = (clock() - began) * speed if speed > 0 else max(now, pos / sample_rate) + clock() - tick
        _record(transcriber, timings, groups, now, on_groups)
    tick = clock()
    groups = transcriber.flush()
    timings.compute += clock() - tick
    now = (clock() - began) * speed if speed > 0 else max(now, pos / sample_rate) + clock() - tick
    _record(transcriber, timings, groups, now, on_groups)
    return timings


def _record(transcriber: LiveTranscriber, timings: LiveTimings, groups: list[yus.TranscriptGroup], now: float, on_groups: Callable[..., None] | None) -> None:
    for word in transcriber.committed[len(timings.commits) :]:
        timings.commits.append((word.end, now))
        timings.word_latency.append(now - word.end)
    for group in groups:
        timings.group_latency.append(now - (group.start + group.duration - transcriber.start).total_seconds())
    if groups and on_groups:
        on_groups(groups, now)


# Command line ----------------------------------------------------------------------------------------------------------------------------


def load_audio(path: pathlib.Path) -> np.ndarray:
    """Decode an audio file to 16 kHz mono float32 (PyAV, installed with faster-whisper; no ffmpeg needed)."""
    from faster_whisper.audio import decode_audio  # type: ignore[import-not-found]

    return np.asarray(decode_audio(str(path), sampling_rate=SAMPLE_RATE), dtype=np.float32)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Transcribe an audio file as if it arrived live, printing each group of words as it is committed.")
    parser.add_argument("audio", type=pathlib.Path, help="Path to an audio file (wav/mp3/m4a/ogg/etc).")
    parser.add_argument("--team", dest="teams", action="append", type=pathlib.Path, default=[], help="Team JSON file (can be specified multiple times).")
    parser.add_argument("--sport", default="ultimate/indoor", help="Sport term set to bias toward (default: ultimate/indoor).")
    parser.add_argument("--recording-start", default="auto", help="Recording start as an ISO timestamp, 'now', or 'auto' (default), as for yus-transcribe.")
    parser.add_argument("--speed", type=float, default=0.0, help="1 plays the audio in real time, 2 twice as fast; 0 (default) as fast as possible on a simulated clock.")
    parser.add_argument("--backend", choices=tr.BACKENDS, default="auto", help="Whisper implementation: mlx (Apple Silicon GPU) or faster-whisper (CPU/CUDA). Default auto.")
    parser.add_argument("--model", default="large-v3-turbo", help="Whisper model size, Hugging Face repo id, or local path (default: large-v3-turbo).")
    parser.add_argument("--language", default="en", help="Language code (default: en).")
    parser.add_argument("--prompt", default="", help="Text to put before the roster and terms in the prompt.")
    parser.add_argument("--terms-file", type=pathlib.Path, help="File with one custom phrase per line to bias toward.")
    parser.add_argument("--sport-terms", action="store_true", help="Also list the sport's terms in the prompt (off by default: it made Whisper repeat the list).")
    parser.add_argument("--no-mondegreens", action="store_false", dest="mondegreens", default=True, help="Do not replace known mishearings (mondegreens).")
    parser.add_argument("--period", type=float, default=3.0, help="Decode every this many seconds of new audio (default: 3).")
    parser.add_argument("--window", type=float, default=20.0, help="Decode the last this many seconds (default: 20).")
    parser.add_argument("--hold", type=float, default=1.0, help="Commit words two decodes agree on once they ended this many seconds ago (default: 1).")
    parser.add_argument("--force", type=float, default=4.0, help="Commit words that ended this many seconds ago even without agreement (default: 4).")
    parser.add_argument("--start", type=float, help="Start this many seconds into the audio.")
    parser.add_argument("--stop", type=float, help="Stop this many seconds into the audio.")
    parser.add_argument("-o", "--output", type=pathlib.Path, help="Write the transcript JSON here (default: <audio>.live.json).")
    parser.add_argument("--timings", type=pathlib.Path, help="Also write each word's end and commit time, and each decode, as JSON here.")
    parser.add_argument("--quiet", action="store_true", help="Do not print groups as they are committed.")
    return parser


def print_groups(groups: list[yus.TranscriptGroup], now: float, transcriber: LiveTranscriber) -> None:
    for group in groups:
        lag = now - (group.start + group.duration - transcriber.start).total_seconds()
        print(f"{group.start:%H:%M:%S.%f}"[:-5] + f" (+{lag:4.1f} s)  {group.interpretations[0].transcript}", flush=True)


def main() -> int:
    args = build_arg_parser().parse_args()
    backend = tr.resolve_backend(args.backend)
    recording_start, source = tr.parse_recording_start(args.recording_start, args.audio)
    teams = tr.load_teams_from_files(args.teams)
    if repo_id := tr.resolve_hf_repo_id(args.model, backend):
        tr.ensure_model_downloaded(repo_id, ("weights.safetensors", "weights.npz") if backend == "mlx" else ("model.bin",))
    print(f"Recording start: {recording_start.isoformat()} (from {source})", file=sys.stderr, flush=True)
    print(f"Decoding with {backend} using {repo_id or args.model}", file=sys.stderr, flush=True)
    whisper = load_whisper(backend, args.model, args.language)
    prompt = live_prompt(teams, whisper, sport=args.sport, prefix=args.prompt, extra_terms=tr.phrases_from_file(args.terms_file), sport_terms=args.sport_terms)
    print(f"Prompt ({whisper.count_tokens(' ' + prompt)} of {tr.PROMPT_TOKEN_BUDGET} tokens): {prompt}", file=sys.stderr, flush=True)

    audio = load_audio(args.audio)
    first = int((args.start or 0.0) * SAMPLE_RATE)
    audio = audio[first : int(args.stop * SAMPLE_RATE) if args.stop is not None else None]
    whisper(np.zeros(SAMPLE_RATE, dtype=np.float32), prompt)  # compile the model's kernels before the clock starts
    transcriber = LiveTranscriber(
        recording_start + dt.timedelta(seconds=first / SAMPLE_RATE),
        prompt,
        tr.load_replacements(args.sport, teams) if args.mondegreens else {},
        period_s=args.period,
        window_s=args.window,
        hold_s=args.hold,
        force_s=args.force,
        transcribe=whisper,
    )
    timings = simulate(transcriber, audio, speed=args.speed, on_groups=None if args.quiet else lambda groups, now: print_groups(groups, now, transcriber))

    output = args.output or args.audio.with_suffix(".live.json")
    tr.write_transcript_json(transcriber.transcript, output)
    if args.timings:
        args.timings.write_text(json.dumps({**timings.model_dump(), "passes": [p.model_dump() for p in transcriber.passes]}) + "\n")
    for (heard, replacement), count in transcriber.fired.most_common():
        print(f"Replaced {heard!r} with {replacement!r} ({count}x)", file=sys.stderr)
    print(timings.summary(), file=sys.stderr)
    print(f"Transcript written to: {output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
