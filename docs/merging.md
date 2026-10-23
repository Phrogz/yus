# Merging Commentators' Event Streams

`yus.processing.event_unification.merge` turns several commentators' event streams of one game into one official stream.

## Where it fits

transcript → events (`yus-events`, names as spoken) → **player resolution** (`PlayerResolver`, per stream) → **merging** → stats.

Its input is each commentator's *resolved* stream. Each commentator's clock may be off. Each misses some events, and they
disagree on details such as who caught the disc, the throw type, or whether it was a score.

## How it works

1. **Clock offsets.** Each stream's offset from the first stream (the reference) starts from a peak of a histogram of time
   differences between events of the same type and team within `max_offset`. Scores and same-named players count more. When
   other peaks at least 1.8 s away are at least half as high (up to 3 in all), the one whose alignment scores best wins. The
   offset is then refined twice from the median difference of the events it paired.
2. **Pairing.** A monotone alignment (each stream keeps its own order) finds the highest-scoring chain of pairs: a Fenwick tree
   over the candidate pairs. A pair must have the same kind of event and team and be within `tolerance` seconds. An
   `indoor.Throw` and an `ultimate.Throw` are the same kind (a class and its same-named ancestors); the merged event takes the
   more specific class. A pair's score falls quadratically with the time apart, so events far apart pair only when their
   details agree. Matching names add to it and different roster names subtract from it; so do throw type, outcome, and above
   all a score both reported. Streams after the second are aligned to the events merged so far.
3. **Fields.** A known value beats an unknown one (`None`, or `False` for flags like `hit_wall`). If known values disagree:
   a roster player beats a description label, a score beats silence (a catch nobody else called a score; saying it was not
   caught is no silence), then the commentator whose `focus` is the event's team wins, then the majority, then, on a tie, the
   earliest stream among the tied values. A merged event's time is the mean of its aligned times.
4. **Game grammar** (`repair=True`):
   - Two neighbouring events from different streams are swapped when the game says the other order fits better, such as a
     Defense said just before the throw it stopped, or a pass placed after the score that ended the possession.
   - Then each throw's outcome is made to agree with what follows: a Defense by the other team means incomplete; the same team
     throwing next means completed and not scored; a score is a catch.
   - An outcome that several commentators agreed on is never overridden, because an event they all missed is likelier.
   - A score that one commentator reported and another was silent on stands against that other commentator's next throw by
     the same team when it came less than 1 s (`SAME_BREATH`) after their report of the scoring throw, and the reporter's next
     throw or Defense has the other team with the disc. Such a throw is one throw heard as two: in the end-to-end runs, "flick
     huck to kaia in the end zone for a score" became "Flick hot to Kaia Mann", a catch by "hot" and hot's dropped throw.
     Until a commentator reports more play after it, the score stands, provisional: a session that settles events in a pause
     (see [session.md](session.md#behaviour)) then keeps it.

## API

```python
from yus.processing.event_unification import LiveMerger, merge_streams

result = merge_streams(resolved_streams, focus=["white", None], teams=game.teams)
result.stream      # yus.EventStream, time-ordered; teams named by their official (first) name when `teams` is given
result.offsets     # seconds added to each stream to align it to the first, e.g. [0.0, -6.42]
result.pairs       # per merged event, the index of its source event in each input stream (or None)
result.conflicts   # Conflict(event, field, values per stream, chosen, rule: roster|score|focus|majority|earliest|grammar)
result.links       # NameLink suggestions, e.g. stream 1's "specs" (team "light") is "glasses"
result.settled     # the first `settled` events are final; result.provisional marks the rest
```

`merge_streams(streams, tolerance=3.0, max_offset=20.0, focus=None, *, teams=None, offsets=None, settle=20.0, repair=True)`

- `teams` identifies teams that commentators name differently ("white"/"light") and tells roster players from labels.
  Without `teams`, team names must match. A `focus` that names none of the `teams` raises `ValueError`.
- `offsets` fixes known clock offsets (`None` entries are estimated).
- `settle`: the most one stream may lag another, in seconds. Events still to come are assumed to be later than `settle`
  seconds before the latest input event.
- Times may be naive or carry a UTC offset. If the streams mix the two, merged times are naive local wall-clock times, as in
  the stats.

Merging is a pure function of its inputs, and merged events are copies, never the input events. It does not apply `links`: to
use one, add it to the game's descriptions with that stream's commentator, then re-resolve.

**Settled events.** `result.settled` counts the leading merged events that no event still to come can change. The count stops
before the first event that:

- is later than `settle` + `tolerance` seconds before the latest input event (a new event could pair with it);
- may still be reordered, because the group after it is not settled yet;
- is a throw whose next throw is not settled yet, since the grammar repair reads it;
- is a score heard as two (above) that waits for the reporter's next event, while only the other team has the disc.

An estimated offset can move with more events, so a stream whose offset is estimated holds settling back: before its first
event less 26.25 s (`max_offset` + 2 × `tolerance` + 0.25 s), or, while it has no events, a further `max_offset` back. A
batch merge of several streams with estimated offsets therefore has `settled == 0`. Pass `offsets`, or use `LiveMerger`.

**Live.** Re-merge the streams so far whenever an event arrives:

```python
merger = LiveMerger(focus=["white", "black"], teams=game.teams)   # takes merge_streams's keyword options
result = merger.merge(streams_so_far)
```

`LiveMerger` estimates each stream's offset until 10 of its events have paired, then keeps it for the events so far. After
that, whenever the paired events give an offset at least 0.25 s away from the current one, the new offset applies to that
stream's later events only (`merger.segments`: (first event index, offset) per stream; `merger.offsets`: the current ones).
Events already merged keep their offset, so settled events never change and `settled` never decreases.

Pass every commentator's stream from the first call, empty until it reports. A stream added to the list later can unsettle
events. There is no CLI; `yus-stats` and live UIs call it from Python. The stats module's `provisional_from` takes
`result.settled`.

## Measured

There is only one real commentator. So `tests/test_merge.py` generates two commentators from the ground-truth game
(`build_game().official_stream`, 200 events) and scores the merge against it:

- **Coverage.** In *dual*, both cover the whole game and each misses 10% of events. In *split*, one covers white and the other
  black; each misses 5% of its own team's events and reports 25% of the other team's, without names or throw types.
- **Noise.** The second clock is 4–11 s ahead. Event times have 0.6 s jitter. Names, types and directions are sometimes dropped,
  and 3%/2% of outcomes (completed/scored) are flipped. The second commentator uses other team names and labels for unknown players.

Scoring constants were tuned on the dev part (before 463.3 s) only, and barely mattered.

Results over 40 seeds; test part shown where it differs:

| | dual | split |
|---|---|---|
| pairing precision / recall (test part) | 0.996 / 0.992 | 0.943 / 0.942 |
| pairing precision / recall (whole game; worst seed) | 0.997 / 0.993 (0.981 / 0.974) | 0.937 / 0.936 (0.81 / 0.83) |
| offset error, mean (max) | 0.06 s (0.19 s) | 0.14 s (0.55 s) |
| final score exactly right | 60% of seeds | 22% of seeds |
| worst team's goal error, mean: merged vs one commentator | 0.42 vs 2.2 | 1.1 vs 6.6 |
| worst team's completion % error, mean: merged vs one commentator | 0.5 vs 1.1 pts | 0.9 vs 7.2 pts |

Speed: merging a whole game with estimated offsets takes about 6.5 ms (dual, about 360 input events) or 3 ms (split), on an
M-series Mac; with the offsets known, 4 ms or 2 ms. A `LiveMerger` re-merge takes 2.3 ms (dual) or 1.2 ms (split) at the median,
14 ms at most.

**Settling.** Re-merging the streams so far, with offsets held fixed, after every second of 240 games: no settled event ever
differed from the final result, and `settled` never decreased. The games cover both modes, 12 seeds, 0.6 s and 1.0 s jitter,
and one stream lagging the other by 0, 5, 9 or 16 s. About 7–8 events (a median of 29 s) stay provisional, against 5 before
reordering and the next throw were taken into account.

**`LiveMerger`**, over 24 seeds per mode, second stream 1 s behind:

| | dual | split |
|---|---|---|
| first settled event, median (max) | 55 s (95 s) | 162 s (330 s) |
| offset error at the end, mean (max) | 0.10 s (0.35 s) | 0.18 s (0.47 s) |
| pairing precision / recall lost vs a batch merge, mean | 0.000 / 0.001 | 0.003 / 0.003 |
| same, worst seed | 0.006 / 0.013 | 0.043 / 0.051 |

The offset first kept is up to 0.98 s off in split mode, where only a quarter of the other team's events are reported, and
without names. Before later events got a refined offset, that cost up to 0.06 / 0.08 (0.009 / 0.012 on average). Before
other histogram peaks were weighed, one seed kept an offset 2.3 s off and lost 0.75 precision.

Another 128 games added unequal lags (0/6, 10/0 and 0/16 s) and a second commentator who starts at 200 s. No settled event
changed and `settled` never decreased. With the late starter, the first stream's events settle from about 85 s.

Most split-mode score errors are goals that neither commentator reported in full. The rest come from cross-reports without names,
which can pair with the neighbouring throw.

**A score heard as two.** Both real two-commentator runs ([results.md](results.md)) lost white's goal at 154 s, as above.
Re-merged with the session's offsets, both now score it (white 14, was 13; truth 14–9), with the same event F1 and exact F1
(0.968 / 0.796 and 0.975 / 0.793), and live re-merges as events arrive changed no settled event. The synthetic results above are
unchanged: their commentators never hear one throw as two. Without the 1 s limit, against any later throws of the team, a
mistaken score stood 10 times in the 80 synthetic games, and exact final scores fell from 60% to 52% (dual) and 22% to 18%
(split). In the ground truth, one commentator's consecutive throws are at least 0.8 s apart. Re-merging every 0.5 s, with
most goals of the game heard as two (gaps of 0.4–1.5 s, either commentator silent) and the reporter lagging 0, 6 or 15 s, no
settled event changed and `settled` never decreased (4 seeds). In 20 such games, every goal heard as two under 1 s apart was
kept, and every one 1.5 s apart lost. A `GameSession` whose reporter said nothing for 18 s after such a goal used to settle it,
in the pause, as no score; the score now shows while undecided, so it settles as a score. Re-feeding the two real runs to a
session at the times their groups arrived gave the same result as before (14–9; no settled event changed).

## Limitations

- **Synthetic evaluation only.** The noise model (Gaussian jitter, independent misses and flips) is an assumption, and no
  real two-commentator recording exists yet.
- **Overlap is needed for offsets.** Offsets come from shared events. Streams with nothing in common get offset 0, and a
  `LiveMerger` stream whose offset is never kept holds settling back from its first event on. Within a stream, clock drift is
  followed only as `LiveMerger`'s offsets for later events; batch offsets are constant.
- **Missed events.** An event that every commentator missed stays missing. The grammar assumes nothing was missed between two
  throws, except that it never overrides an outcome several commentators agree on, or a score against a throw heard as two.
  A single report saying both "scored" and "incomplete" is taken as a catch.
- **Extra events stay.** The second half of a throw heard as two stays in the merged stream, after the goal, as heard.
  Events can't say "no score", so silence and "no score" are told apart only by whether the catch was reported.
- **Labels for unknown players** that differ between commentators are not unified automatically; `links` only suggests them.
- **Timing.**
  - Merged times are means, nudged where needed to keep the order.
  - Settling assumes events are only appended, in time order, and that no stream lags another by more than `settle` (20 s).
