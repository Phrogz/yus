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
- **Stats, unresolved names and unmentioned players** are computed when a snapshot's are first read, then kept.
  `compute_stats` takes 7–10 ms, more than the rest of a snapshot put together.

## API

```python
from yus.session import GameSession, replay

session = GameSession(game, descriptions, directory)   # descriptions and directory optional; timeout=6.0 keyword
session.add_commentator("Gavin", focus_team=None)      # focus_team: any team name, for merge conflicts
session.add_groups("Gavin", groups)                    # TranscriptGroups, in order; copies are kept
session.set_pending_text("Gavin", transcriber.pending_text)
session.advance(horizon, "Gavin")                      # transcript complete up to horizon (None: all commentators)
session.describe("white", ["red shorts"], player="Kaia Mann", commentator=None)   # -> PlayerDescription
session.finish()                                       # end of game: everything final; add_groups now raises
session.version                                        # increases on every change
snap = session.snapshot()                              # the same object until the next change
session.save(); session = GameSession.load(directory)
replay(session, transcript_or_json_path, "Gavin", speed=0, on_update=None)   # -> groups fed
```

`GameSnapshot` is a read-only dataclass. Its objects are shared with the session and with later snapshots.

| field | |
|---|---|
| `version`, `game`, `finished` | |
| `commentators` | `CommentatorState`: `name`, `focus_team`, `groups` (count), `final_count` (raw events final), `pending_text` |
| `transcripts` | per commentator name: the `TranscriptGroup`s received |
| `raw`, `resolved` | per commentator name: `EventStream`, final events first. `raw` keeps names as spoken |
| `official` | one commentator: its resolved stream; several: the merged stream (teams by first name) |
| `settled_count`, `provisional` | `official.events[:settled_count]` are final; `provisional` lists the rest |
| `merge` | the `MergeResult` with two or more commentators (offsets, pairs, conflicts, name links); else `None` |
| `associations` | `HeardAssociation`s: `commentator`, `team`, `description`, `name` (as spoken), `player` (as recorded) |
| `descriptions` | every description in effect, in the order recorded: given, described and heard |
| `stats` | `compute_stats(official, game.teams, provisional_from=settled_count)` |
| `score`, `summary` | from `stats` |
| `unresolved`, `unmentioned` | `PlayerResolver.unresolved` / `unmentioned_players` over `official` |

### Behaviour

- **Settled events.**
  - One commentator: `settled_count` is the extractor's `final_count`. At most the one open throw is provisional.
  - Several: it is the merge's `settled`, cut before the first merged event that contains a provisional raw event.
  - After `finish()`: every event is settled.
  - Settled events never change as commentary arrives. A description does change them: `describe()` and spoken
    identifications re-resolve the names of every event, settled or not (and, with several commentators, may change how events pair).
- **Spoken identifications.** The extractor finds identifications like "oh, red shorts is kaia". Each one is recorded at once
  as a description for that commentator's stream: `PlayerDescription(team, [description], player, commentator=...)`.
  - A commentator's own record beats shared ones. To correct a heard identification, `describe()` the same description
    with that `commentator`.
  - A heard name that can't be recorded is kept with `player=None` (for example, one that resolves to a label).
- **advance(now, commentator=None)** takes transcript time: the time up to which that commentator's ASR has delivered every
  word (`None` means every commentator). After `timeout` seconds without words, an open throw becomes final. Feeding a group
  applies the same rule, so how often you call it changes only how soon the throw becomes final. Pass a commentator when the
  commentators' transcribers lag by different amounts.
- **Versions.** Every change bumps `version`, but only effective ones:
  - `add_commentator`;
  - `add_groups` with at least one group;
  - `describe`;
  - `finish`, the first time;
  - `set_pending_text` with new text (the events are not recomputed);
  - `advance` when an event became final.
- **Threads.** Every method takes one lock. `snapshot()` holds it for 0.1–2 ms. Stats are computed outside it, on first
  read, under the snapshot's own lock.
- **Commentators** are merged in the order they were added; the first is the clock reference. Add every commentator before
  feeding groups. A commentator added later starts a new merge (when they are the second) or joins it (later ones). Either way
  `settled_count` can drop and settled events can change.
- **Errors.** These raise `ValueError`: an unknown commentator, a duplicate name, an unknown focus team, or a description
  naming an unknown team or a player who is not on that team. `add_groups` after `finish()` raises `RuntimeError`.

### Files

`save()` writes these files to the session's `directory`. Each is written to a temporary file first, then renamed into place.

| file | content |
|---|---|
| `game.json` | `sport`, `when`, `teams` |
| `descriptions.json` | `GameDescriptions`: everything given, described and heard; `PlayerResolver` and `yus-stats --descriptions` read it |
| `transcripts/<commentator>.json` | that commentator's `Transcript` (the name made file-safe: `B / Other` → `B_Other`) |
| `events/<commentator>.json` | raw `EventStream`, as `yus-events` writes it (`yus-score`, `yus-stats` read it) |
| `official.json` | the official `EventStream` |
| `session.json` | version, timeout, finished, commentators (file, focus, pending text, last `advance`), associations heard, the merger's state |

`load()` rebuilds a session by feeding the transcripts to new extractors. It replays the last `advance`, records only
identifications not heard before, and restores the `LiveMerger`'s segments as they were when its last merge started. It then
merges once. The snapshot after `load()` equals the one saved, and both sessions go on identically (tested with two
commentators, mid-game). `events/` and `official.json` are outputs: they are not read back, so an improved extractor applies
on reload.

### replay

`replay()` feeds each group when its last word ends:

- `speed=1` is real time and `speed=2` is twice as fast. `speed=0` feeds every group at once.
- While it waits, it calls `advance()` every `tick` (1 s) of transcript time, up to the next group's first word.
- `on_update(snapshot)` is called after each group, and after each advance that changed something.
- `stop` (a `threading.Event`) ends the replay early; `clock` and `sleep` can be replaced, e.g. in tests.
- It adds the commentator if they are new. It does not finish the session.

## Measured

These numbers come from an Apple Silicon Mac, Python 3.13, the hand-made transcript of the 2025-01-14 20:30 game (246 groups)
and its descriptions file.

- **Correctness.**
  - After `replay()` and `finish()`, the official stream equals the batch pipeline's (`extract_events` → `resolve_stream`).
    So do all stats tables, and the Whisper transcript gives the same result.
  - The score is 14–10. The ground truth is 14–9: the extractor counts "blade in the end zone nope not in the end zone" as a
    goal (a known extraction limitation).
  - In snapshots taken after every group, settled events never changed and `settled_count` never decreased.
- **Two commentators.** The second commentator is synthetic: the same commentary with a clock 5 s ahead, every 8th group
  missed, and "light"/"dark" in place of "white"/"black". Groups were fed in arrival order, 462 in all.
  - The merged stream has the same 200 events and the same score as one commentator alone. The estimated offset was −5.0 s.
  - Settled events never changed.
  - Provisional events: a median of 8, at most 12. The first event settled 80 s in, once `LiveMerger` had locked the
    offset. The newest settled event is a median of 38 s old.
- **Speed.**

  | | snapshot | snapshot + stats |
  |---|---|---|
  | one commentator, median (max) | 0.10 ms (0.3) | 7.1 ms (10) |
  | one commentator, whole game, after every group | 0.03 s | 1.75 s |
  | two commentators, median (max) | 2.0 ms (22) | 9.2 ms (30) |

  - `describe()` followed by a snapshot takes 1.9 ms.
  - `save()` of the two-commentator game takes 14 ms and writes 636 KB. `load()` takes 66 ms.

## Limitations

- **Stats dominate.** About 97% of the cost of reading `stats` after every group is `compute_stats` building its DataFrames.
  A dashboard should read stats once per version, not once per widget.
- **Timeouts.** Silence finalizes an open throw only if the server calls `advance()` (or `replay()` does). Without it, a
  throw stays provisional until the commentator speaks again.
- **Unscoped `advance()`.** Without a commentator, it tells every extractor that the transcript is complete up to `now`. Use
  it only when all transcribers have caught up.
- **Merging.** The merge inherits `LiveMerger`'s limits:
  - settling waits about 20–40 s, and until offsets are locked;
  - its results depend on how often `snapshot()` is called, since each call merges once;
  - it is tested only on synthetic second commentators.
- **Name scope.** A heard identification applies only to the commentator who said it. Another commentator's matching
  description stays unresolved unless the merge pairs their events (a roster name beats a label) or someone describes it.
- **Persistence.**
  - `save()` rewrites every file, about 14 ms for a whole game.
  - A crash during `save()` can leave files from two versions, though no file is ever half-written.
  - `pending_text` is saved, so it can be stale after a restart until the transcriber sets it again.
- **Live end-to-end.** `test_live_transcription_of_the_real_audio_feeds_a_session` runs LiveTranscriber on the real audio into
  a session (`YUS_SLOW_TESTS=1`). It has not been run yet: the GPU was busy with the live-transcription measurements.
