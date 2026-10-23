# End-to-End Results

The whole live pipeline on the real audio of the 2025-01-14 20:30 game (960.6 s, one commentator), scored against the
hand-made ground truth (`tests/data/gruindoor_20250114T2030-*`).

- **Setup.** An M3 Pro Mac. `yus-serve` on localhost with mlx-whisper large-v3-turbo, both team files and the game's
  descriptions file. `yus-replay` streamed the audio in real time (`--speed 1`).
- **Measuring.** A script read `/api/state?events=-1` every 0.5 s, and fetched `/`, `/admin`, `/commentate`, `/dashboard/`
  and the dashboard's refresh callback every 10 s. It also timed every Whisper decode.
- **Times.** `yus-replay` prints when it stamped the file's second 0, and `yus-score --shift` moves the events from that
  moment back onto the recording's (20:30:33). After the shift, matched events were 0.16 s early on average (median error
  0.25 s), and words 0.13 s early.
- **Scoring.** Event F1 pairs events within 3 s; exact F1 also needs every field right. Names on both sides are resolved
  with `PlayerResolver` and the descriptions file. Latency runs from an event's own time (its first words) to the first
  poll that showed it, or that counted it settled. From the true events' times it is within 0.5 s of that.

| | one commentator | two commentators | two, after the settling fix |
|---|---|---|---|
| event F1 / exact F1 | 0.975 / 0.792 | merged 0.968 / 0.796 | merged 0.975 / 0.793 |
| ... dev / test | 0.964 / 0.821, 0.986 / 0.766 | 0.954 / 0.853, 0.981 / 0.743 | 0.964 / 0.802, 0.986 / 0.785 |
| ... each commentator's own stream | | 0.975 / 0.787, 0.975 / 0.802 | 0.973 / 0.769, 0.985 / 0.796 |
| events (truth: 200) | 204 | 207 | 206 |
| final score (truth: 14–9) | 14–11 | 13–10 | 13–10 |
| word error rate, lenient | 0.117 (dev 0.142, test 0.092) | 0.111, 0.128 | 0.130, 0.121 |
| speech to first shown: median / p90 / max | 8.1 / 11.9 / 23.4 s | 8.9 / 12.3 / 29.7 s | 10.0 / 15.0 / 24.4 s |
| speech to settled: median / p90 / max | 11.1 / 15.0 / 27.8 s | 44.2 / 53.3 / 65.3 s | 31.4 / 40.9 / 51.8 s |
| provisional events: median while live; 15 s after the end | 1; 0 | 8; 9 | 5; 2 |
| GPU busy decoding (decode median / max) | 49% (1.44 / 2.28 s) | 97% (1.44 / 2.33 s) | 99% (1.51 / 2.62 s) |
| audio waiting for its transcriber: median / max | 0 / 2.1 s | 0.7 / 6.9 s | 3.2 / 8.2 s |
| pages while live: answered; slowest | 96 of 96 each; 104 ms | 97 of 97 each; 75 ms | 97 of 97 each; 71 ms |
| save, then `GameSession.load` | same events, settled count and score | the same; offsets 0, −5.33 s | the same; offsets 0, −5.06 s |

In the two-commentator runs, both streams were the same audio. The second started about 5 s after the first. One
commentator's focus team was white and the other's was dark. The slowest page was always the dashboard's refresh callback.
Results vary from run to run, as Whisper's windows start at different times (see
[live_transcription.md](live_transcription.md#limitations)).

## What Went Wrong

- **Score.**
  - In every run, "blade in the end zone? Nope, not in the end zone" (650 s) counts as a white goal: the extractor never
    retracts a fact (see [extraction.md](extraction.md#limitations)). Possession then flips, so white's real goal at 668 s
    goes to black.
  - With one commentator, Whisper also heard "picked up by naked for black" (310 s) as "Picked Huck by Naked for a score",
    a black goal that never happened.
  - With two, white lost its goal at 154 s in both runs. Only the dark-focus commentator's transcript said "for a score",
    and on a white event the white-focus commentator's outcome wins.
- **Settling with two commentators (fixed).** Merged events settled only 20 s, plus `tolerance`, before the newest event.
  That gave a median 44 s from speech to settled. In a pause, or at the end of the game, the last 9 or 10 events stayed
  provisional until "Finish game". The session now settles from how far the slowest commentator lags, plus 2 s (see
  [session.md](session.md#behaviour)). Live, that gave a median of 31 s, and 2 events left waiting at the end;
  `settled_count` never went down. The rest of the 31 s is the transcription lag (about 8 s), the second commentator's 5 s
  offset, the merge's 3 s `tolerance`, and waiting for the next throw.
- **Capacity.** Two commentators kept the M3 Pro's GPU 97–99% busy: two decodes of about 1.5 s per 3 s period. It kept up,
  without headroom. Audio waited up to 8 s for its transcriber, and events showed 1–2 s later at the median than with one
  commentator. A third commentator would need about 4.5 s of decoding per 3 s, so each transcriber would decode less often
  and fall further behind (not tried).
- **Errors.** No transcription errors and no failed requests. The dashboard and the admin page answered throughout.

## Reproducing

```bash
DATA=tests/data
yus-serve --team $DATA/team_dump_and_drizzle.json --team $DATA/team_category_5.json --asr mlx --host 127.0.0.1 \
    --descriptions $DATA/gruindoor_20250114T2030-descriptions.json --game-dir /tmp/e2e
yus-replay 20250114T2030-0700.ogg --commentator "Gavin Kistner" --speed 1    # ends: "Audio second 0 was stamped T"
# two commentators: also start the second about 5 s after the first, and give each --focus
yus-replay 20250114T2030-0700.ogg --commentator "Second Voice" --focus dark --speed 1
curl -X POST http://127.0.0.1:8000/api/finish
yus-score /tmp/e2e/official.json --descriptions $DATA/gruindoor_20250114T2030-descriptions.json \
    --shift T 2025-01-14T20:30:33 [--stop 463.3 | --start 463.3]
```

The word error rate is computed as in [live_transcription.md](live_transcription.md#accuracy-and-latency), on
`/tmp/e2e/transcripts/<commentator>.json` moved by the same shift. The polling, page probes and decode timing came from
a script outside the repository.
