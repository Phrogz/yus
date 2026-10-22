# Event Extraction

Event extraction turns a play-by-play transcript into game events: throws, defenses, and (not yet produced) substitutions and
infractions. `yus.processing.event_extraction` does it with rules, live: it takes transcript groups as they arrive and
keeps an up-to-date event list. `yus.processing.evaluation` scores any event stream against ground truth.

```txt
audio -> yus-transcribe / yus-live-transcribe -> Transcript -> yus-events -> EventStream (names as spoken)
      -> PlayerResolver (event unification) -> merging -> stats
```

Player names stay as the commentator said them, in lower case ("pikachu", "close crop", "the kid", "adam federbusch").
`PlayerResolver` maps them to roster players later; see [Game Description Files](usage.md#game-description-files).
Each event's `team` is one of that team's names. This is the team's first color name (`"white"` for
`["Dump & Drizzle", "white", "light"]`, `"dark"` for `["Category 5", "Cat 5", "dark", "black"]`), or its first name if it has
no color name. `PlayerResolver.team_index` and the scorer accept any of a team's names.

## Command line

```bash
yus-events game.transcript.json --team white.json --team dark.json [-o game.events.json] [--timeout 6]
yus-score game.events.json [--gt truth.json] [--team T.json ...] [--resolve | --descriptions D.json] [--start T] [--stop T] [-v] [--json]
```

- `yus-events` writes `<transcript stem>.events.json` and prints a summary: counts, goals per team, and spoken identifications.
  Give one `--team` per team, or none: without them it assumes two teams called `white`/`light` and `black`/`dark` (a single
  `--team` is an error). `--timeout` finalizes a throw after that many seconds of silence, as live use would (see below).
- `yus-score` compares a predicted stream with a ground-truth stream. The default ground truth is the bundled game,
  `tests/data/gruindoor_20250114T2030-eventstream.json`, together with its team files.
  - `--start`/`--stop` keep only the events in a time window, on both sides. A value is an ISO time, a clock time, or seconds
    after t0, the first word of the transcript next to the ground truth. For the bundled game, `--stop 463.3` is the dev
    split and `--start 463.3` is the test split.
  - `--resolve` maps names to players with `PlayerResolver` on both sides. `--descriptions` does the same and also uses a
    per-game descriptions file.
  - `-v` lists misses, false positives and field mismatches.
  - Unreadable or invalid files print an error and exit with status 1.

## Python API

```python
from yus.processing.event_extraction import EventExtractor, extract_events

stream = extract_events(transcript, game.teams)            # batch: EventStream

extractor = EventExtractor(game.teams, timeout=6.0)        # live
for group in groups:                                       # as each TranscriptGroup arrives
    extractor.feed(group)
    final, provisional = extractor.events[: extractor.final_count], extractor.events[extractor.final_count :]
extractor.advance(asr_horizon)  # no words up to this transcript time: a throw open for > timeout s becomes final
extractor.finish()              # end of game: everything final
for team, description, name in extractor.associations:   # "oh, red shorts is kaia" -> ("white", "red shorts", "kaia")
    resolver.describe(team, [description], player=resolver.resolve(name, team))
```

- `associations` only holds identifications of a roster player whose team is known, so the loop above never raises. "kaia is
  wide open", "this game is intense" and "red shorts is kaia on dark" (kaia plays for white) record nothing. Without rosters
  there are no associations.

- `events` lists events in time order, with the final ones first. `events[:final_count]` never changes. The events after
  that are provisional: in practice the one throw whose outcome is still open, shown as completed until the commentary says
  otherwise. The next group may revise it.
- `advance(now)` takes transcript time, not wall-clock time: the time up to which the ASR has delivered every word. Because
  `feed()` applies the same rule at the start of each group, results do not depend on how often `advance` is called.
- Streaming and batch give identical events for the same timeout, and final events never change. Tests check this on both
  transcripts and on 40 random commentaries (with score lines, bare team names, identifications, possessives and accented
  names). 3,000 random commentaries, with random `advance()` calls and with and without teams, were also checked once, outside
  the test suite.

```python
from yus.processing.evaluation import score
result = score(predicted, truth, teams=game.teams, resolve=resolver, start=split)  # streams, event lists, or JSON paths
result.overall.f1, result.exact.f1, result.fields["receiver"].accuracy, result.report(verbose=True)
```

- **Pairing.** The scorer sorts both streams by time. It then pairs events with a monotone alignment: pairs never cross,
  each pair has the same event type, and the two times are at most `tolerance` (3 s) apart. The alignment maximizes the
  number of pairs first. Among those, it prefers the smallest time differences and the fewest differing fields.
- **Event F1** counts paired events. **Exact F1** counts only paired events whose fields all agree.
- **Names** are compared the way `PlayerResolver` compares them: case, punctuation, possessives and a leading "the" are
  ignored. "somebody", "unknown" and `None` are the same.
- **Teams** are compared by any of their names when `teams` is given.
- **Times** may be naive or carry a UTC offset, on events and in `t0`/`start`/`stop`. They are compared as naive local times,
  like the ground truth's: offset times go to the zone of the first time with a non-UTC offset, else to this system's zone.
- **A field the event's class lacks** takes its default: an `ultimate.Throw` has `hit_wall=False`, like an `indoor.Throw`.
- **`resolve`** is optional. It is a `PlayerResolver` or any function from event to event, applied to both sides.

## How it works

1. **Tagging** (`lexicon.py`). Words are lower-cased and split on punctuation ("Kaia Mann," "D'd", "-huck", "endzone").
   - Each position takes the longest match from a phrase table of about 350 entries ("picked up by", "deed by",
     "in the end zone", "for dark") or from the known player names: roster names, nicknames, mondegreens, and names announced
     in a line-up. A possessive does not break a match ("Adam Federbusch's huck").
   - Runs of other words between stopwords become NAMEs. About 240 stopwords ("the disc", "alright", "team", "huh") keep common
     words from becoming players. Accented letters are kept ("josé").
   - "." "?" "!" and ";" end a clause; "," and ":" are weak boundaries that only split names.
2. **Parsing** (`extractor.py`). A state machine walks each group, tracking:
   - the team in possession;
   - who holds the disc;
   - name→team evidence, from rosters, line-ups and "for dark";
   - at most one open throw.

   The open throw becomes final when something settles it: an explicit outcome ("dropped", "deed by", "for a score",
   "caught by"), the next throw, a pickup, or the timeout. It may continue across groups ("flick" | "swing, to close crop";
   "hammer put" | "off the wall to turtle..."). A name that ends a group may start the next one ("Tristan" | "picks up for
   white").
3. **Inference.**
   - "picked up by X" after an unresolved throw means that throw hit the ground.
   - A catch toward the end zone followed by a pickup counts as a score.
   - A thrower known to be on the other team means a turnover was missed.
   - "black pulls" gives possession to white.
   - "for dark" and "on dark" set possession, but not after a score line ("5-4 for white") or a line change ("D-line comes on
     for dark"). A bare team name counts only in "white picks it up" or right after a pickup or defense ("picked up by red
     shorts, dark"); "that's 5-4 white" and "the dark corner" say nothing about possession.
   - "for" or "on" ending a group joins a team name starting the next one (Whisper's "picks it up for" | "White.").
   - "score" in "what's the score?" or before a score line ("score's five four") is no goal.
4. **Associations.** "X is Y" clauses ("oh, red shorts is kaia [on white]", several per sentence) are kept out of the event
   stream and recorded when they identify a roster player (see above). One that stands alone also takes the rest of its
   phrase with it when that holds no event, so "pikachu is killing it tonight" adds no player "tonight".

## Measured accuracy

Ground truth is one game with one commentator: 200 events, of which 191 are throws and 9 are defenses. The dev split is
everything before 463.3 s after the first word (2025-01-14T20:38:30.9) and has 96 events. The test split is everything after
and has 104 events. The rules were tuned on dev only. Cells show event F1 / exact F1.

| transcript | dev | test |
|---|---|---|
| hand-made, names as spoken | 1.000 / 1.000 | 0.990 / 0.904 |
| real Whisper large-v3-turbo, one pass (WER 0.10), names as spoken | 0.990 / 0.760 | 0.990 / 0.625 |
| same Whisper transcript, both sides resolved with PlayerResolver + descriptions | 0.990 / 0.948 | 0.990 / 0.798 |
| live sliding-window transcript (WER 0.15; spike output, not in repo), resolved, `--timeout 6` | 0.954 / 0.761 | 0.961 / 0.755 |

- **Hand-made transcript, without team files:** 1.000 / 1.000 on dev and 0.990 / 0.894 on test.
- **Why raw names score lower on the Whisper transcript:** Whisper's text differs from the hand transcript's names. Its
  mondegreens write "Adam Federbusch" where the ground truth has "federbusch", and it writes "kidd" for "kid". Comparing
  resolved names removes that difference.
- **Every remaining dev error on Whisper traces to an ASR error:**
  - lost words, such as "dump", "hat" and one whole throw;
  - "to make it" for "to naked";
  - "Lied to somebody on dark" for "deed by somebody on dark", which adds one false throw.
- **Chatty paraphrase of the dev commentary:** 0.969 / 0.969. This proxy for a chattier commentator comes from the spike;
  its only misses are timing shifts.
- **Held-out phrasing probe:** 35 of 40 snippets of other commentators' phrasing pass. The probe comes from the spike and
  was not tuned on.

## Latency and cost

Latency below runs from an event's first word to the end of the group that made it final. ASR delay comes on top of it:
about 7.7 s median for the live sliding window. The "first shown" columns are for the event's first, provisional appearance.

| transcript, timeout | final: median / p95 / max | groups waited (0 / 1 / 2) | first shown: median / max | later revised |
|---|---|---|---|---|
| hand-made, 6 s | 4.3 / 8.2 / 14.2 s | 52 / 146 / 2 | 1.5 / 6.6 s | 9 of 200 |
| hand-made, 3 s | 4.2 / 7.0 / 9.9 s | 68 / 133 / 1 | | |
| Whisper, 6 s | 5.0 / 12.2 / 15.0 s | 79 / 117 / 4 | 1.6 / 14.0 s | 31 of 200 |

- **Timeout trade-off:** a 6 s timeout costs nothing on either transcript; with no timeout the worst case is 14.2 s (hand-made)
  and 17.4 s (Whisper). A 3 s timeout costs 0.03–0.04 dev exact F1, and
  0 s costs 0.07–0.2.
- **CPU** (M3 Pro, Python 3.13): `feed()` plus `events` takes a median of 18–22 µs per group. That is about 5–5.5 ms for the
  whole 16-minute game. Building an extractor takes 0.35 ms.

## Limitations

- **One commentator, one game.** The rules were written for this commentator's terse style. The probe's other phrasings
  still fail on:
  - passives ("kaia's throw is dropped by tristan");
  - reversed order ("tristan scores on a flick from kaia");
  - "for joe" as a receiver;
  - descriptions with "in" ("the guy in the red shirt").
- **Unknown words become names.** Stopwords cover common ones, but not every word.
  - On the test split: "backhand across in the end zone" gives receiver "across", "power dump" gives player "power", and
    "bobbled and dropped" gives receiver "bobbled". "kaia's huck sails out of bounds" gives receiver "sails".
  - Whisper's mishearings of descriptions become names too: "leg strength", "clothes crop", "invert arc".
  - A description that starts with a team name ("white headband") splits into the team and "headband".
- **Facts are applied as they arrive and never retracted.** "in the end zone, nope, not in the end zone" still scores. A
  wrong score or turnover then flips possession, and every following event gets the wrong team until a team is named again:
  4 test events.
- **Restatements.** "flick put huck close crop" starts a second throw.
- **The defender is lost when Whisper splits "deed" from "by X" across groups.**
- **Unsure outcomes.** A throw to the end zone with no "caught" or "score", followed by a pickup by the other team, counts as
  incomplete.
- **Jersey numbers.** These need "number twelve"; a bare "to 12" reads as a score line. No substitution or infraction
  events are produced, and the ground truth has none.
- **Where the "ends of" mishearing lives.** The extraction lexicon handles Whisper's "the ends of" for "end zone" (twice in
  dev). The sport's mondegreen list (`yus/sports/ultimate`) may be a better home for it.
- **The test split is not fully blind.** An earlier spike's report described test-split errors before these rules were
  written. No rule targets them, but one dev-motivated rule happens to fix the trailing-"swing" case: a throw type or
  direction may describe the open throw across groups. Test numbers may therefore be slightly optimistic.
