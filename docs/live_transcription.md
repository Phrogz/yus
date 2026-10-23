# Live Transcription

`yus.processing.transcription.live` turns commentary audio that arrives in real time into a `yus.Transcript`, one
`TranscriptGroup` at a time, a few seconds behind the speaker. `yus-transcribe` needs the whole recording; this does not.

```text
microphone / file ──audio──> LiveTranscriber.feed() ──TranscriptGroups──> EventExtractor.feed() ──raw events──> PlayerResolver ──> stats
                                               └──horizon──> EventExtractor.advance()
```

Each group is a burst of speech ("picked up by Pikachu", "backhand to glasses"), closed after a pause, with word times as
naive local datetimes like `yus-transcribe`'s. Names stay as Whisper heard them, apart from known mondegreens
(`"Takaya"` becomes `Kaia Mann`); mapping names and descriptions to players is `PlayerResolver`'s job, later.

## How It Works

Whisper decodes 30-second windows and is unreliable on a few seconds of gym noise, so the live transcriber keeps re-decoding
a sliding window of recent audio and only commits words it has heard consistently:

1. **Decode.** Once `period_s` (3 s) of new audio has arrived, Whisper decodes the last `window_s` (20 s) of audio, with the
   same static prompt every time (the roster; see [The Prompt](#the-prompt)). Already committed audio stays in the window
   as context. Decoding is greedy (temperature 0), one 30-second window per decode (see [Decoding Time](#decoding-time)).
2. **Clean the decode.** Drop segments that are probably invented: a decode that fails Whisper's own confidence check
   (average log probability below -1) or compression check (above 3.5, a loop), segments with most words squeezed into no
   time (Whisper could not place them in the audio), stock subtitle phrases ("Thanks for watching!"), and the prompt read
   back ("Players: ..."). Drop the repeats of a decoding loop (a 1-5 word phrase three times in a row, or a 6-20 word phrase
   twice; play-by-play repeats a short phrase at most twice: "backhand to George, backhand to Hat"), and a partial repeat right
   after it, but keep its first copy and the words after it, which are usually real speech.
3. **Find the new words.** Word times drift between decodes, so the decode is aligned on the text of the last committed
   words it repeats (the match ending nearest the commit point). Without such a match, words whose middle is past the end of
   the last committed word are new. This keeps re-heard words from being committed twice, and keeps words from being lost
   when their times move earlier.
4. **Commit.** New words are committed when two consecutive decodes agree on them (LocalAgreement-2, comparing the leading
   words) and they ended `hold_s` (1 s) ago, or, agreed or not, once they ended `force_s` (4 s) ago.
5. **Group.** A pause of more than `gap_s` (0.6 s) after the last committed word closes its group, as soon as a decode hears
   the pause (or the next committed word starts after it). Mondegreens are replaced when a group closes, so a phrase
   committed by two decodes ("feather" + "brush") still becomes `Adam Federbusch`.
6. **Flush.** At the end of the stream, a final decode commits every word it hears, plus the previous decode's uncommitted
   words before them that it did not hear again (all of them if the final decode heard nothing).

Audio arriving while a decode runs waits for it; the next decode then sees all of it at once. A decoder slower than
`period_s` therefore decodes less often instead of falling behind.

## Python API

```python
import datetime as dt
import pathlib
from yus.processing.transcription import live, transcribe as tr

teams = tr.load_teams_from_files([pathlib.Path("team_dump_and_drizzle.json"), pathlib.Path("team_category_5.json")])
whisper = live.load_whisper()                                    # mlx on Apple Silicon, else faster-whisper
transcriber = live.LiveTranscriber(
    start=dt.datetime(2025, 1, 14, 20, 30, 33),                  # wall-clock time of the first sample
    prompt=live.live_prompt(teams, whisper),
    replacements=tr.load_replacements("ultimate/indoor", teams),
    transcribe=whisper,                                          # omit to load model/backend here
)
for samples in microphone():                                     # mono float32 in [-1, 1] at sample_rate (default 16000)
    for group in transcriber.feed(samples):                      # groups completed by this audio
        extractor.feed(group)
    extractor.advance(transcriber.horizon)                       # transcript complete up to here
    show(transcriber.open_text, transcriber.pending_text)        # committed words of the open group; the latest guess
for group in transcriber.flush():                                # end of stream: commit and close everything
    extractor.feed(group)
transcriber.transcript                                           # every closed group
```

- `LiveTranscriber(start, prompt=None, replacements=None, model="large-v3-turbo", backend="auto", sample_rate=16000,
  period_s=3.0, window_s=20.0, hold_s=1.0, force_s=4.0, transcribe=None, gap_s=0.6)`. Other sample rates are resampled
  (PyAV). Needs `force_s + period_s < window_s`. A `start` with a UTC offset becomes a naive local time
  (`transcribe.local_naive`), so word times are always naive.
- `feed(samples) -> list[TranscriptGroup]` takes mono audio (a 1-D array, or 2-D with one channel; more channels raise
  `ValueError`); `flush() -> list[TranscriptGroup]`; `transcript`, `open_text`, `pending_text`,
  `committed` (every committed word as heard, with times in stream seconds), `passes` (each decode's time and compute),
  `fired` (mondegreens replaced).
- `horizon`: the time up to which every word has been returned in a group, for `EventExtractor.advance()` (see
  [extraction.md](extraction.md)). It is the start of the open group or of the pending hypothesis; with neither, the end of
  the last committed word or the start of the next decode's window (`window_s - period_s` before the latest decode's end: no
  later decode hears earlier audio), whichever is later. It never decreases. See [Accuracy and Latency](#accuracy-and-latency)
  for how often a word still starts before it.
- `transcribe(audio, prompt) -> list[dict]`: any callable that decodes 16 kHz audio into Whisper segment dicts (`words` with
  `word`/`start`/`end`/`probability`, plus `text`, `avg_logprob`, `compression_ratio`). `MlxWhisper` and `FasterWhisper` are
  the built-in adapters; tests pass a fake. mlx-whisper shares one cached model between all `MlxWhisper`s of a model, so
  their decodes take turns (a lock), which lets several commentators' transcribers run in threads.
- `live_prompt(teams, whisper, prefix="", extra_terms=(), sport_terms=False)`: the static prompt.
- `simulate(transcriber, audio, speed=0.0)` plays audio as if it arrived live and returns `LiveTimings` (each word's and
  group's latency, GPU busy fraction of the playing time, which at `speed` 2 is half the audio's length). With a fake
  `clock` that the decoder advances by a fixed time per decode (`FixedCost` in the slow test), the windows decoded, and so
  the transcript, are the same on every run.

## Command Line

```bash
yus-live-transcribe 20250114T2030-0700.ogg --team team_dump_and_drizzle.json --team team_category_5.json -o game.live.json
```

It prints each group as it closes, with how long after its last word it closed, then the mondegreens replaced and the
latency summary (the setup and summary lines go to stderr):

```text
Recording start: 2025-01-14T20:30:33 (from com.apple.quicktime.creationdate in the file's metadata)
Decoding with mlx using mlx-community/whisper-large-v3-turbo
Prompt (121 of 223 tokens): Players: Matt Whitlock (Pikachu), Kaia Mann, Emily Kraus, ...
20:30:47.0 (+ 5.2 s)  We have Kaia Mann, Pikachu, Tristan, glasses.
20:30:53.9 (+ 8.0 s)  and short crown.
20:31:11.4 (+ 7.0 s)  Black pulls picked up by Pikachu, backhand glasses,
20:31:17.0 (+ 4.8 s)  scoober to Tristan.
...
Replaced 'bush' with 'Adam Federbusch' (14x)
...
Word latency (end of word -> committed): median 6.5 s, p90 8.4 s, p95 9.8 s, max 14.4 s over 1124 words
Group latency (end of group -> closed): median 6.7 s, p90 8.9 s, p95 10.0 s, max 13.9 s over 222 groups
GPU busy decoding 49% of the time (467 s for 961 s of audio)
```

- `--speed X` - 1 plays the file in real time, 2 twice as fast. 0 (default) runs as fast as the decoder allows on a simulated
  clock that still accounts for decoding time, so latencies are the same as live.
- `--period`, `--window`, `--hold`, `--force` - see [How It Works](#how-it-works).
- `--team`, `--sport`, `--recording-start`, `--backend`, `--model`, `--language`, `--prompt`, `--terms-file`,
  `--no-mondegreens` - as for `yus-transcribe`. `--sport-terms` also puts the sport's terms in the prompt.
- `--start`/`--stop` - seconds into the file; `-o` - transcript JSON (default `<audio>.live.json`); `--timings` - each word's
  end and commit time and each decode, as JSON; `--quiet` - do not print groups.

## The Prompt

Every decode is primed with the same prompt: the roster, `Players: Matt Whitlock (Pikachu), Kaia Mann, ...`, plus any
`--prompt` text and `--terms-file` phrases. The sport's term list is left out by default. `yus-transcribe` primes only the first
30-second window; priming every window with the 62-term list (`swing, swing to, swings to, dump, dump to, ..., to, ...`) made
Whisper repeat it ("swing to, swing to, swing to", "turn, turn, turn"), and the loops cost up to 3.5 s of decoding each.

## Decoding Time

A decode of a 20-second window takes about 1.4 s with mlx-whisper large-v3-turbo on an M3 Pro, nearly all of it the encoder,
which always encodes 30 seconds. Two things made some decodes much slower, and are handled:

- **Second passes.** When a decode ends with two timestamps, as it often does at the very end of a live window,
  `mlx_whisper.transcribe` decodes the audio after the last timestamp again: a second full encoder pass, usually over less than
  half a second of audio. That was 1 decode in 8 to 14 and 6-9% of decoding time; replaying the recorded decodes without those
  passes gave exactly the same transcript (the next decode hears that audio anyway). `MlxWhisper` decodes only the first window
  of each call (`OneWindow`).
- **Loops.** A decode that loops ("He's a big fan of the game." 20 times) runs to Whisper's 224-token limit, about 2.2 s.
  Dropping the term list from the prompt made loops rare; the compression check drops them.

mlx-whisper reports a NaN average log probability for about 1 decode in 6, almost all of them good. Like Whisper's own check,
the live transcriber lets NaN pass (dropping those decodes raised dev WER by 0.002-0.023 in replays) and gives their groups the
mean log probability of their words as confidence.

## Accuracy and Latency

The 2025-01-14 20:30 game (960 s, one commentator, M3 Pro, mlx-whisper large-v3-turbo), against the hand-made transcript
(`tests/data/gruindoor_20250114T2030-transcript.json`). Word error rate is lenient (`back hand` = `backhand`) and counts a
replaced mondegreen like `bush` → `Adam Federbusch` as an error (about 0.025 of it). Dev is audio up to 477.9 s (the first
463.3 s after the first labeled word); everything was tuned on dev only. Latency is from the end of a spoken word to its
commit, on the simulated live clock (`--speed 0`).

The whole game, `yus-live-transcribe --speed 0` (the "earlier prototype" is the baseline this module started from):

| | WER dev | WER test | WER all | latency median / p90 / p95 / max | GPU busy |
|---|---|---|---|---|---|
| `yus-transcribe` (whole file at once, not live) | 0.116 | 0.082 | 0.099 | - | 7% |
| Earlier prototype (full term prompt, temperature fallback, no segment filter) | 0.178 | 0.123 | 0.150 | 7.7 / 13.4 / 17.2 / 27.7 s | 63% |
| **Live, defaults** (period 3 s, force 4 s; 3 runs) | 0.148-0.167 | 0.089-0.108 | 0.118-0.137 | 6.5 / 8.4 / 9.8 / 14.4 s | 49% |
| Live, defaults, after the loop and `horizon` fixes below (1 run) | 0.139 | 0.103 | 0.121 | 6.4 / 8.4 / 9.6 / 15.4 s | 49% |
| Live, `--period 2` (2 runs) | 0.137-0.144 | 0.101-0.110 | 0.119-0.127 | 5.1 / 7.2 / 7.7 / 14.1 s | 73% |

Latency and GPU busy are from one clean run each (`yus-live-transcribe` for the defaults). Events extracted from those
transcripts (`yus-events --timeout 6`, scored by `yus-score` with the game's descriptions): F1 0.965 (exact 0.777) at the
defaults, 0.975 (0.792) at `--period 2`, against 0.990 (0.870) from `yus-transcribe`'s whole-file transcript. The run after
the fixes had name recall 0.904 and, with the prototype's extractor on the test half, event F1 0.981 (exact 0.610 with names as
heard, 0.752 resolved).

What was tried on dev. Dev WER differs by up to 0.023 between runs of the same settings (see [Limitations](#limitations)), so
settings were compared over several runs, or by replaying recorded decodes, which holds the decodes fixed and isolates
the change (marked "replay").

| Change | Dev result |
|---|---|
| Full roster + term prompt, temperature fallback 0 / 0.2 / 0.4 (the prompt `yus-transcribe` uses) | WER 0.176, latency 7.6 / 15.3 s (median / p95), busy 67% |
| ... + dropping failed, collapsed and stock-phrase segments | 0.146, 7.4 / 15.0 s |
| Roster-only prompt (+ segment filter) | 0.146, 6.7 / 12.4 s, busy 53% |
| Roster + the term list without variants (`swing` but not `swing to`) | 0.199 (unfiltered; roster-only was 0.162) |
| Greedy decoding only (roster prompt, filtered): **default** | 0.146-0.169 over 6 runs (mean 0.157), 6.4-6.7 / 9.1-10.5 s, busy 47-50% |
| One window per decode (no second passes) | replay: same transcript; decode time p95 2.9 → 1.5 s, max 3.4 → 2.2 s; 6% less GPU time on dev |
| Dropping decodes with a NaN log probability | replay: WER +0.002 to +0.023 |
| Period 2 s | 0.137-0.155 over 5 runs (mean 0.145), 5.3 / 7.8-9.0 s, busy 71-75%; on test, though, 0.101-0.110 against 0.089-0.108: kept 3 s, which leaves the GPU half free |
| Force 3 s (replay of 6 runs) | WER -0.011 to +0.005 (mean -0.004); latency 0.3-0.8 s lower. On test +0.003 / +0.009: kept 4 s |
| Force 5 s / 6 s (replay) | WER within noise of force 4, latency 0.1-1.2 s higher |
| Hold 0.5-2 s | no effect at period 2-3 s: a word is at least one period old when its second decode can agree |
| Window 15 s / 28 s (period 3) | 0.186 / 0.169 (one run each) |
| Alignment by time only (no text alignment) | replay: within 0.01 WER |
| Loops only at 3+ repeats, or a 10+ word phrase twice | replay: WER +0.000 to +0.011 (Whisper's duplicated 6-9 word phrases got in) |
| Loops: drop only the repeats, keep the words after them (it used to cut the decode where the loop began, for as long as the loop stayed in the window): **default** | replay of 9 recordings: WER -0.002 to +0.002 (mean +0.001); p90 / p95 latency 0.1-0.3 s lower. At 190-205 s, where "to Tristan, backhand to glasses, flick" was really said twice, the words after it now commit at most 7.5-7.8 s after they were said, not 10-11 s. On test, 2 of 3 recordings are unchanged; the third gained 14 words of chatter after a "No, no, no" loop at 857 s (0.108 → 0.132) |
| Keeping a repeat that starts before the commit point (it was accepted before) | replay: WER mean -0.0004 against dropping all repeats; more insertions on some recordings: not adopted |
| `horizon` in silence: the start of the next decode's window (`window_s - period_s` back) instead of `force_s` back: **default** | replay of 9 recordings: words that start before the horizon reported when they arrived, 8-14% (up to 13 s before it) → 0.4-1.1% (under 1 s); 10 s or 13 s back left about as many, but up to 7 s or 4 s before it. Cost: after a throw and then silence, `EventExtractor.advance()` makes it final about 13 s later |
| Skipping decodes in silence | not built: Silero VAD hears speech in 291-297 of the game's 321 3-second chunks (gym chatter), so at most 9% of decodes could be skipped |

## Limitations

- Accuracy is that of Whisper on 20-second windows: worse than decoding the whole file (WER 0.10), mostly on fast,
  overlapping phrases, where consecutive decodes disagree and words are forced in as the latest decode heard them.
- Results vary from run to run: a decode's output depends on exactly where its window starts (3.00 s and 3.05 s of the same
  audio decode to entirely different text), and window starts depend on decoding time. Two runs of the same settings differed
  by up to 0.023 in dev WER, so smaller differences were not taken as real.
- Measured on one game, one commentator, one gym and one machine. Latency and the GPU busy fraction scale with the GPU:
  a decoder slower than `period_s` decodes back to back and latency grows by the excess.
- Committed words are final: a later, better decode cannot revise them. The transcript can contain a phrase twice when one
  decode hears it twice at different times ("backhand swing to Blondie" at 448 s and 452 s), or miss a word when Whisper
  re-hears it with a different spelling and a time far from the first.
- Mondegreens are replaced only within a group, as in `yus-transcribe`.
- A phrase that was really said twice in a row and is 6+ words long ("to Tristan, backhand to glasses, flick" at 192 s) is
  taken for a loop and loses its second copy; so does a 1-5 word phrase said three times.
- Speech after a loop is kept, including chatter: with the old cut, one recording's test half had 14 fewer inserted words.
- `horizon` can still be passed by a word whose time a later decode moved earlier: about 1% of words, by under 1 s.
- Default decoding is for mlx-whisper; the faster-whisper adapter is untested against a real model here (no cached CTranslate2
  model), still decodes second passes, and on a CPU is far too slow for live use.
- The CLI simulates live arrival from a file; capturing from a microphone is up to the caller (`feed()` takes any audio).
