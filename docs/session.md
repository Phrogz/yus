# Game Session

`yus.session.GameSession` ties the pipeline together for one game, live or replayed. Commentators' transcript groups go in;
`snapshot()` returns everything a dashboard shows at one `version`. A server feeds it from worker threads, and `replay()`
feeds a saved transcript at its own pace for tests and demos.

## Where it fits

```text
LiveTranscriber / replay ──groups──> GameSession
    per commentator:  EventExtractor (incremental) ──raw events──> PlayerResolver ──resolved events
    whole game:       one commentator: its resolved stream; several: LiveMerger ──official stream──> compute_stats
```

- **Extraction** runs in `add_groups()`. Each commentator has an `EventExtractor` fed only the new groups (about 20 µs a group).
- **Resolution and merging** run in `snapshot()`, only when something changed since the last one.
  - Final raw events are resolved once and cached until a description changes; only the open throw is resolved again.
  - A `LiveMerger` merges the streams when there are two or more commentators.
- **Stats, unresolved names and unmentioned players** are computed when a snapshot's are first read, then kept. A snapshot
  whose official stream and settled count are the same as the last one's shares its stats. `compute_stats` takes 7–10 ms,
  more than the rest of a snapshot put together.

## API

```python
from yus.session import GameSession, replay

session = GameSession(game, descriptions, directory)   # descriptions and directory optional; timeout=6.0, llm=None keywords
session.add_commentator("Gavin", focus_team=None)      # focus_team: any team name, for merge conflicts
session.add_groups("Gavin", groups)                    # TranscriptGroups, in order; copies are kept
session.set_pending_text("Gavin", transcriber.pending_text)
session.advance(transcriber.horizon, "Gavin")          # transcript complete up to horizon (None: all commentators)
session.describe("white", ["red shorts"], player="Kaia Mann", commentator=None)   # -> PlayerDescription
session.finish()                                       # end of game: everything final
session.version                                        # increases on every change
snap = session.snapshot()                              # the same object until the next change
session.save(); session = GameSession.load(directory)
replay(session, transcript_or_json_path, "Gavin", speed=0, on_update=None)   # -> groups fed
```

`GameSnapshot` is a read-only dataclass. Its objects are shared with the session and with later snapshots. It can be
deep-copied and pickled. `dataclasses.asdict` gives the fields below, but not the computed ones (`stats` to `provisional`).

| field | |
|---|---|
| `version`, `game`, `finished` | |
| `commentators` | `CommentatorState`: `name`, `focus_team`, `groups` (count), `final_count` (raw events final), `pending_text` |
| `transcripts` | per commentator name: the `TranscriptGroup`s received |
| `raw`, `resolved` | per commentator name: `EventStream`, final events first. `raw` keeps names as spoken; both keep teams as spoken |
| `official` | one commentator: its resolved stream; several: the merged stream. Teams by their first names either way |
| `settled_count`, `provisional` | `official.events[:settled_count]` are final; `provisional` lists the rest |
| `merge` | the `MergeResult` with two or more commentators (offsets, pairs, conflicts, name links); else `None` |
| `associations` | `HeardAssociation`s: `commentator`, `team`, `description`, `name` (as spoken), `player` (as recorded) |
| `descriptions` | every description in effect, in the order recorded: given, described and heard |
| `stats` | `compute_stats(official, game.teams, provisional_from=settled_count)` |
| `score`, `summary` | from `stats` |
| `unresolved`, `unmentioned` | as `PlayerResolver.unresolved` / `unmentioned_players`, over `official`'s names as resolved (not resolved again) |

### Behaviour

- **Settled events.**
  - One commentator: `settled_count` is the extractor's `final_count`. At most the one open throw is provisional.
  - Several: it is the merge's `settled`, cut before the first merged event that contains a provisional raw event.
    Merged events settle only up to the slowest commentator's progress: the start of their last group, or their last
    `advance()` once more than `timeout` seconds without words followed that group. The session sets the merge's `settle`
    to how far that progress lags the newest event, plus 2 s (`SETTLE_MARGIN`, for a refined offset or a word committed
    just before its horizon). Once every commentator's progress has passed the newest event (a pause in play, the end of the
    game), everything settles but the last throw and what follows it. While a commentator has neither groups nor an
    `advance()`, nothing settles.
  - A merged event that settled stays settled while the commentators and descriptions stay the same, even when a refined
    offset makes a later merge more cautious (`session.json` keeps the count).
  - After `finish()`: every event is settled.
  - Settled events never change as commentary arrives, and `settled_count` never decreases. A description does change them:
    `describe()` and spoken identifications re-resolve the names of every event, settled or not (and, with several
    commentators, may change how events pair).
- **Spoken identifications.** The extractor finds identifications like "oh, red shorts is kaia". Each one is recorded at once
  as a description for that commentator's stream: `PlayerDescription(team, [description], player, commentator=...)`.
  - A commentator's own record beats shared ones. To correct a heard identification, `describe()` the same description
    with that `commentator`.
  - A heard name that can't be recorded is kept with `player=None` (for example, one that resolves to a label).
- **advance(now, commentator=None)** takes transcript time: the time up to which that commentator's ASR has delivered every
  word (`None` means every commentator). After `timeout` seconds without words, an open throw becomes final. Feeding a group
  applies the same rule, so how often you call it changes only how soon the throw becomes final. With several commentators,
  call it for each one as their transcriber reports progress (`LiveTranscriber.horizon`), or settling waits for their next group.
- **Times.** Each commentator's word times must be all naive or all with a UTC offset; `add_groups` refuses a group that
  differs, adding none of the groups. Commentators may differ, as `LiveMerger` allows. `advance()` takes either kind for any
  commentator. Naive times are local: in the zone of the first commentator whose times have an offset other than UTC, else
  this system's zone.
- **Versions.** Every effective change bumps `version`:
  - `add_commentator`;
  - `add_groups` with at least one group;
  - `describe`;
  - `finish`, the first time;
  - `set_pending_text` with new text (the events are not recomputed);
  - `advance` when an event became final or, with several commentators, a commentator's progress moved.

  After `load()`, `version` is the saved one; the first change then takes a version from the clock (microseconds since 1970),
  past any version given out before a crash, saved or not. A version is a cache key for one session's snapshots.
- **Threads.** Every method takes one lock. `snapshot()` holds it for a median of 0.1 ms with one commentator and 2 ms with
  two (up to 24 ms when the merge re-estimates an offset). Stats are computed outside it, on first read, under the
  snapshot's own lock.
- **LLM assistance** (`llm=LLMAssistant(...)`, off by default; see [extraction.md](extraction.md#llm-assistance)). Each
  commentator's extractor is an `AssistedExtractor`. Answers arrive on a worker thread and are applied by `add_groups()`,
  `advance()` and `snapshot()`, which then bump `version`. A group awaiting its answer holds back `final_count` (at most the
  budget, 10 s). `finish()` waits for the answers still due, up to their budgets. `GameSession.load(directory, llm=...)`
  replays the saved answers without asking again; `llm` answers the groups to come.
- **Commentators** are merged in the order they were added; the first is the clock reference. Add every commentator before
  feeding groups. A commentator added later starts a new merge (when they are the second) or joins it (later ones). Either way
  `settled_count` can drop and settled events can change.
- **Errors.**
  - `ValueError`: an unknown commentator (also in `describe`), a duplicate name, an unknown focus team, a description naming
    an unknown team or a player not on that team, or word times unlike the commentator's.
  - `TypeError`: pending text that is not a `str`.
  - `RuntimeError`: `add_commentator`, `add_groups` or `set_pending_text` after `finish()`. `advance()` then does nothing,
    and `describe()` still works.

### Files

`save()` writes these files to the session's `directory`. Each is written to a temporary file first, then renamed into place.

| file | content |
|---|---|
| `game.json` | `sport`, `when`, `teams` |
| `descriptions.json` | `GameDescriptions`: everything given, described and heard; `PlayerResolver` and `yus-stats --descriptions` read it |
| `transcripts/<commentator>.json` | that commentator's `Transcript` (the name made file-safe: `B / Other` → `B_Other`) |
| `events/<commentator>.json` | raw `EventStream`, as `yus-events` writes it (`yus-score`, `yus-stats` read it) |
| `official.json` | the official `EventStream` |
| `session.json` | version, timeout, finished, commentators (file, focus, pending text, last `advance`, LLM answers), associations heard, the merger's state |

File names differ even on a disk that ignores case and Unicode normalization (macOS): `Gavin` and `gavin` get `Gavin.json`
and `gavin-2.json`.

`load()` rebuilds a session by feeding the transcripts to new extractors. It replays the last `advance`, records only
identifications not heard before, and restores the `LiveMerger`'s segments as they were when its last merge started. It then
merges once. The snapshot after `load()` equals the one saved, and both sessions go on identically (tested with two
commentators, mid-game). `events/` and `official.json` are outputs: they are not read back, so an improved extractor applies
on reload. A file name in `session.json` that `save()` could not have written (`../x`) raises `ValueError`.

Without `session.json`, `load()` takes each `transcripts/*.json` as a commentator, in file name order (so the first is the
clock reference), named by the transcript's `commentator` (else the file name). Focus teams, `advance` times, the merger's
state and `finished` are then unknown.

### replay

`replay()` feeds each group when its last word ends:

- `speed=1` is real time and `speed=2` is twice as fast. `speed=0` feeds every group at once. A negative speed, or a `tick`
  of 0 or less with a positive speed, raises `ValueError`.
- While it waits, it calls `advance()` every `tick` (1 s) of transcript time, up to the next group's first word.
- `on_update(snapshot)` is called after each group, and after each advance that changed something.
- `stop` (a `threading.Event`) ends the replay early; `clock` and `sleep` can be replaced, e.g. in tests.
- It adds the commentator if they are new. It does not finish the session.

## Measured

These numbers come from an Apple Silicon Mac, Python 3.13, the hand-made transcript of the 2025-01-14 20:30 game (246 groups)
and its descriptions file.

- **Correctness.**
  - After `replay()` and `finish()`, the official stream equals the batch pipeline's (`extract_events` → `resolve_stream`,
    teams then named by their first names). So do all stats tables, and the Whisper transcript gives the same result.
  - The score is 14–10. The ground truth is 14–9: the extractor counts "blade in the end zone nope not in the end zone" as a
    goal (a known extraction limitation).
  - In snapshots taken after every group, settled events never changed and `settled_count` never decreased.
- **Two commentators.** The second commentator is synthetic: the same commentary with a clock 5 s ahead, every 8th group
  missed, and "light"/"dark" in place of "white"/"black". Groups were fed in arrival order, 462 in all, each commentator
  advanced to the end of each of their groups.
  - The merged stream has the same 200 events and the same score as one commentator alone. The estimated offset was −5.0 s.
  - With the second commentator's groups arriving late, settled events never changed and `settled_count` never decreased.
    Before the session bounded settling by progress, a lag of 30 s changed 7 snapshots' settled events and 120 s changed 147.

    | second commentator's lag | 0 s | 15 s | 30 s | 60 s | 120 s |
    |---|---|---|---|---|---|
    | provisional events, median (max) | 5 (12) | 8 (14) | 11.5 (17) | 18 (24) | 30 (40) |
    | ... with a fixed 20 s allowance (before) | 8 (12) | 8 (14) | 11 (17) | 17 (24) | 30 (39) |

    The first event settled 80 s in without lag (once `LiveMerger` had locked the offset) and 142 s in with 60 s of lag.
    The same holds when the first commentator lags instead (30 and 90 s). After both fell silent, 2 events stayed
    provisional (10 with the fixed allowance, until the next event or `finish()`).
  - In the real-audio runs with two commentators ([results.md](results.md)), events settled a median 31 s after they were
    said (p90 41 s), against 44 s (53 s) with the fixed allowance. Replaying the earlier run's transcripts at their
    recorded arrival times gave the same 31 s, with no settled event changing.
  - 108 synthetic games (offsets of −7 to +12 s, lags, a 90 s pause, clocks drifting by up to 6 ms/s) never changed a
    settled event or lowered `settled_count`. Without keeping the count, a drifting clock lowered it up to 12 times a game.
- **Speed.**

  | | snapshot | snapshot + stats |
  |---|---|---|
  | one commentator, median (max) | 0.09 ms (0.2) | 7.1 ms (9) |
  | one commentator, whole game, after every group | 0.03 s | 1.4 s (1.5 s with `unresolved` and `unmentioned`) |
  | two commentators, median (max) | 2.1 ms (24) | 7.2 ms (22) when the official stream changed |

  - New stats were needed by 197 of the 246 snapshots with one commentator, and by 210 of 462 with two (324 with 60 s of lag);
    the others shared the previous snapshot's.
  - `describe()` followed by a snapshot takes 2.1 ms.
  - `save()` of the two-commentator game takes 17–22 ms and writes 619 KB. `load()` takes about 50 ms.

## Limitations

- **Stats dominate.** About 97% of the cost of reading `stats` after every group is `compute_stats` building its DataFrames.
  A dashboard should read stats once per version, not once per widget.
- **Timeouts.** Silence finalizes an open throw only if the server calls `advance()` (or `replay()` does). Without it, a
  throw stays provisional until the commentator speaks again, and with several commentators a silent one holds settling back.
- **Unscoped `advance()`.** Without a commentator, it tells every extractor that the transcript is complete up to `now`. Use
  it only when all transcribers have caught up.
- **Progress is trusted.** Settling assumes no commentator's words arrive earlier than their last `advance()` (or, after a
  group, earlier than that group's start). A transcriber that commits a word before its own horizon can still unsettle events.
- **Merging.** The merge inherits `LiveMerger`'s limits:
  - settling waits about 30 s (the slower commentator's transcription lag, their clock offset, `tolerance` and the next
    throw), and until offsets are locked; a lagging commentator adds their lag;
  - its results depend on how often `snapshot()` is called, since each call merges once;
  - it is tested only on synthetic second commentators.
- **Name scope.** A heard identification applies only to the commentator who said it. Another commentator's matching
  description stays unresolved unless the merge pairs their events (a roster name beats a label) or someone describes it.
- **Persistence.**
  - `save()` rewrites every file, about 20 ms for a whole game.
  - A crash during `save()` can leave files from two versions, though no file is ever half-written.
  - `pending_text` is saved, so it can be stale after a restart until the transcriber sets it again.
- **Live end-to-end.** `test_live_transcription_of_the_real_audio_feeds_a_session` runs LiveTranscriber on the real audio into
  a session, advancing it to `LiveTranscriber.horizon` (`YUS_SLOW_TESTS=1`). It has not been run yet: the GPU was busy with
  another agent's live-transcription measurements.
