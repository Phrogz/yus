# End-to-End Results

The whole live pipeline on the real audio of the 2025-01-14 20:30 game (960.6 s, one commentator), scored against the
hand-made ground truth (`tests/data/gruindoor_20250114T2030-*`). The commentary has no substitutions: those, and who is on
the field, were measured offline on another game ([extraction.md](extraction.md#substitutions), [stats.md](stats.md#measured)).

- **Setup.** An M3 Pro Mac. `yus-serve` on localhost with mlx-whisper large-v3-turbo, both team files and the game's
  descriptions file. `yus-replay` streamed the audio in real time (`--speed 1`). Other work loaded the CPU at times; the
  GPU ran only these runs.
- **Measuring.** A script read `/api/state?events=-1` every 0.5 s, and fetched `/`, `/admin`, `/commentate`, `/dashboard/`
  and the dashboard's refresh callback every 10 s. It also timed every Whisper decode.
- **Times.** `yus-replay` prints when it stamped the file's second 0, and `yus-score --shift` moves the events from that
  moment back onto the recording's (20:30:33). After the shift, matched events were 0.16 s early on average (median error
  0.25 s), and words 0.13 s early.
- **Scoring.** Event F1 pairs events within 3 s; exact F1 also needs every field right. Names on both sides are resolved
  with `PlayerResolver` and the descriptions file. Latency runs from an event's own time (its first words) to the first
  poll that showed it, or that counted it settled. From the true events' times it is within 0.5 s of that.
- **Before and after.** "Before" is commit 9946b0d, where each commentator decodes every 3 s and merged events settle
  only as the merge settles them. "After" runs commit b80d4c3's transcriber, session and server, which add the shared
  decode scheduler (each of two commentators decodes every 4.5 s) and settling once every commentator has gone quiet past
  an event ([server.md](server.md), [session.md](session.md)). All four runs used 9946b0d's extraction and merging code.
  The extractor at commit a6ff6c5 (substitutions and later fixes) gives the same raw events from all six transcripts.

| | one: before | one: after | two: before | two: after |
|---|---|---|---|---|
| event F1 / exact F1 | 0.975 / 0.817 | 0.975 / 0.817 | merged 0.975 / 0.828 | merged 0.966 / 0.809 |
| ... dev / test | 0.964 / 0.831, 0.986 / 0.804 | the same | 0.969 / 0.816, 0.981 / 0.838 | 0.949 / 0.788, 0.981 / 0.829 |
| ... each commentator's own stream | | | 0.978 / 0.799, 0.975 / 0.816 | 0.970 / 0.782, 0.970 / 0.832 |
| events (truth: 200) | 204 | 204 | 206 | 208 |
| final score (truth: 14–9) | 14–10 | 14–10 | 14–9 | 14–9 |
| word error rate, lenient (dev, test) | 0.115 (0.139, 0.092) | the same | 0.123 (0.134, 0.113), 0.122 (0.148, 0.098) | 0.148 (0.170, 0.127), 0.138 (0.151, 0.125) |
| speech to first shown: median / p90 / max | 8.3 / 12.0 / 23.5 s | 8.3 / 12.0 / 23.3 s | 10.2 / 15.8 / 24.9 s | 10.4 / 14.0 / 21.8 s |
| speech to settled: median / p90 / max | 11.5 / 17.4 / 27.9 s | 11.6 / 17.7 / 27.7 s | 34.1 / 42.0 / 50.9 s | 23.3 / 30.2 / 50.6 s |
| provisional events: median while live; 15 s after the end | 1; 0 | 1; 0 | 5; 2 | 3; 0 |
| settled events that changed later; late reports left out | 0; - | 0; 0 | 0; - | 0; 0 |
| GPU busy decoding (decode median / max) | 49% (1.43 / 2.38 s) | 50% (1.44 / 2.40 s) | 98% (1.47 / 5.81 s) | 65% (1.44 / 2.42 s) |
| decodes per commentator-minute | 20.0 | 20.0 | 17.6 | 13.4 |
| audio not decoded yet: median / max | | 2.9 / 5.3 s | | 3.7 / 6.7 s |
| pages while live: answered; slowest | 672 of 672; 95 ms | 672 of 672; 83 ms | 679 of 679; 86 ms | 672 of 672; 93 ms |
| saved, then `GameSession.load` | same events, settled count and score | the same | the same; offsets 0, −5.10 s | the same; offsets 0, −5.09 s |

In the two-commentator runs, both streams were the same audio. The second started about 5 s after the first. One
commentator's focus team was white and the other's was dark. With one commentator, the run after decoded the same windows
as the run before (one decode per 3 s, no contention), so its transcript and events are identical. With two, decode times
decide where windows start, so results vary from run to run (see [live_transcription.md](live_transcription.md#limitations)).
Before, `backlog_s` counted audio waiting for the worker (median 1.4–1.6 s, max 12.6–12.7 s with two); after, it counts
audio not decoded yet, which includes the wait for the next decode period.

## What Went Wrong

- **Score.** With one commentator, Whisper heard "picked up by naked for black" (310 s) as "Picked Huck by Naked for a
  score", a black goal that never happened. Both two-commentator runs got 14–9.
- **Accuracy at 4.5 s.** The merged stream scored event F1 0.966 (0.975 before), and the transcripts' word error rates
  were 0.148 and 0.138 (0.123 and 0.122). Three offline runs at each period (`yus-live-transcribe --speed 0`) put that
  within run-to-run variation: word error rate 0.114–0.136 at 3 s and 0.128–0.131 at 4.5 s, event F1 0.965–0.975 and
  0.955–0.973 ([live_transcription.md](live_transcription.md#accuracy-and-latency)). Words commit about 1.6 s later.
- **Settling with two commentators (fixed).** Merged events used to settle only as the merge settled them: a throw waited
  for the next throw, and the slowest commentator's lag held everything back. In a pause, or at the end of the game, the
  last events stayed provisional until play resumed or "Finish game". They now also settle once every commentator's
  progress is 5 s past them (the merge's 3 s `tolerance` plus 2 s), and a commentator without words for 30 s no longer
  holds settling back ([session.md](session.md#behaviour)). Re-feeding each two-commentator run's groups at the times they
  arrived, with the old and the new session, gave a median 32.8 → 24.3 s (before run) and 31.9 → 23.1 s (after run) from
  speech to settled, with the same final stream. The rest of the 23 s is the transcription lag (8–10 s), the second
  commentator's 5 s offset and the 5 s margin.
- **Capacity (fixed).** Two commentators decoding every 3 s kept the GPU 98% busy, with decodes of up to 5.8 s and audio
  waiting up to 12.7 s. A shared scheduler now gives turns in order and stretches the period to 2.25 s per live
  commentator. With two, the GPU was 65% busy, the longest decode took 2.4 s, and audio waited at most 6.7 s to be
  decoded. Events showed as soon as before (median 10.4 s, p90 14.0 s, against 10.2 and 15.8 s): words commit later, but
  no longer queue behind the other commentator's decodes. A third commentator would decode every 6.75 s, at about the
  same load (not tried). Skipping silent decodes (`--skip-silence`) saved 2% of decodes on this game and is off.
- **Errors.** No transcription errors and no failed requests. The dashboard and the admin page answered throughout.

## Reproducing

```bash
DATA=tests/data
yus-serve --team $DATA/team_dump_and_drizzle.json --team $DATA/team_category_5.json --asr mlx --host 127.0.0.1 \
    --descriptions $DATA/gruindoor_20250114T2030-descriptions.json --game-dir /tmp/e2e
yus-replay 20250114T2030-0700.ogg --commentator "Gavin Kistner" --focus white --speed 1    # ends: "Audio second 0 was stamped T"
# two commentators: also start the second about 5 s after the first
yus-replay 20250114T2030-0700.ogg --commentator "Second Voice" --focus dark --speed 1
curl -X POST http://127.0.0.1:8000/api/finish
yus-score /tmp/e2e/official.json --descriptions $DATA/gruindoor_20250114T2030-descriptions.json \
    --shift T 2025-01-14T20:30:33 [--stop 463.3 | --start 463.3]
```

Both "before" runs are commit 9946b0d. The word error rate is computed as in
[live_transcription.md](live_transcription.md#accuracy-and-latency), on `/tmp/e2e/transcripts/<commentator>.json` moved by
the same shift. The polling, page probes and decode timing came from a script outside the repository.
