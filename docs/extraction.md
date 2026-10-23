# Event Extraction

Event extraction turns a play-by-play transcript into game events: throws, defenses and substitutions (infractions are not
produced yet). `yus.processing.event_extraction` does it with rules, live: it takes transcript groups as they arrive and
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
yus-events game.transcript.json --team white.json --team dark.json [-o game.events.json] [--timeout 6] [--llm MODEL [--llm-url URL] [--llm-budget S]]
yus-score game.events.json [--gt truth.json] [--team T.json ...] [--resolve | --descriptions D.json] [--start T] [--stop T] [--shift FROM TO] [-v] [--json]
```

- `yus-events` writes `game.events.json` for `game.transcript.json` (else `<transcript stem>.events.json`) and prints a
  summary: counts, goals per team, and spoken identifications.
  Give one `--team` per team, or none: without them it assumes two teams called `white`/`light` and `black`/`dark` (a single
  `--team` is an error). `--timeout` finalizes a throw after that many seconds of silence, as live use would (see below).
- `yus-score` compares a predicted stream with a ground-truth stream. The default ground truth is the bundled game,
  `tests/data/gruindoor_20250114T2030-eventstream.json`, together with its team files.
  - `--start`/`--stop` keep only the events in a time window, on both sides. A value is an ISO time, a clock time, or seconds
    after t0, the first word of the transcript next to the ground truth. For the bundled game, `--stop 463.3` is the dev
    split and `--start 463.3` is the test split.
  - `--resolve` maps names to players with `PlayerResolver` on both sides. `--descriptions` does the same and also uses a
    per-game descriptions file.
  - `--shift FROM TO` moves the predicted times by `TO - FROM` first. A game replayed through `yus-serve` is timed on the day
    of the replay: give the time `yus-replay` says it stamped the start of the file, and the recording's start.
  - `-v` lists misses, false positives and field mismatches.
  - Unreadable or invalid files print an error and exit with status 1.

## Python API

```python
from yus.processing.event_extraction import EventExtractor, extract_events

stream = extract_events(transcript, game.teams)            # batch: EventStream

extractor = EventExtractor(game.teams, timeout=6.0)        # live; lineups=True: "on white we have ..." subs those players on
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
  that are provisional, and the next group may revise them:
  - the one throw whose outcome is still open, shown as completed until the commentary says otherwise;
  - when a throw scored, all of that group's events, until the next group ends or `timeout` seconds pass without words. A
    correction in the next group ("Blade in the end zone?" | "Nope, not in the end zone") can still take the score back.
- `advance(now)` takes transcript time, not wall-clock time: the time up to which the ASR has delivered every word. Because
  `feed()` applies the same rule at the start of each group, results do not depend on how often `advance` is called.
- Streaming and batch give identical events for the same timeout, and final events never change. Tests check this on both
  transcripts and on 40 random commentaries (with score lines, bare team names, identifications, possessives, accented names,
  corrections and remarks, and groups whose words share one start time). 3,000 random commentaries with more cue words, with
  random `advance()` calls and with and without teams, were also checked once, outside the test suite (96 parsed groups again
  after a correction).

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
   - A thrower, receiver or defender known only on the other team's roster (or said to play for it) means the team in
     possession was wrong, and the event and possession are corrected: "power dump to tristan" after a false goal is white's.
     Not when the team was just said ("picked up by gloves for dark, flick to joe"), when the names disagree (dark's turtle
     to white's joe), or when the thrower caught the team's last pass. Names on both rosters, descriptions and numbers are on
     no roster and say nothing.
   - "black pulls" gives possession to white.
   - "for dark" and "on dark" set possession, but not after a score line ("5-4 for white") or a line change ("D-line comes on
     for dark"). A bare team name counts only in "white picks it up" or right after a pickup or defense ("picked up by red
     shorts, dark"); "that's 5-4 white" and "the dark corner" say nothing about possession.
   - "for" or "on" ending a group joins a team name starting the next one (Whisper's "picks it up for" | "White.").
   - "score" in "what's the score?" or before a score line ("score's five four") is no goal.
4. **Corrections.** A correction takes back what it contradicts, in the most recent throw. Only provisional events can change.
   - "not in the end zone", "not a score": that throw did not score. It stays caught if it was ("caught by somebody"). A bare
     "not in" counts only right after a cue word ("nope, not in", "sorry, it wasn't in"), so "george not in position" and
     "turtle is not in this point" take nothing back. "Out of the end zone" says nothing (it is where a pickup is taken from).
   - "no score" after a throw that scored: it was a turnover (this commentator says "no score" for every turnover).
   - "sorry, to tristan", "no, wait, to tristan": the receiver. "sorry", "nope", "no", "actually", "wait", "er", "i mean",
     "scratch that" and "my bad" are cue words.
   - "that wasn't joe, that was connor", "not joe, tristan", "sorry, that was connor", "to joe, sorry, tristan": the name, in
     the open throw, the most recent finished event that has it, and who holds the disc. Without "not joe", the new name must
     be a known one (a roster, a line-up, or an earlier event) right after the cue word, and must end its clause, so "wait,
     he stepped out", "sorry, kaia, that was a great throw" and "actually, tristan has been great tonight" replace nobody.
     A rename that would make a thrower his own receiver is no correction ("to joe for the score" | "sorry, kaia").
   - When the throw is already finished, the groups since the state before it are parsed again with the change made when it
     finishes, so possession and the following events follow it. The change is kept by the event's time and its place in the
     list, so of two throws Whisper gave one start time, only the one meant changes.
5. **Substitutions** ([below](#substitutions)). "pikachu subs off, blondie on", "close crop, emily off", "fulmer on for cynic":
   names before a substitution word that ends its phrase.
6. **Associations.** "X is Y" clauses ("oh, red shorts is kaia [on white]", several per sentence) are kept out of the event
   stream and recorded when they identify a roster player (see above). One that stands alone also takes the rest of its
   phrase with it when that holds no event, so "pikachu is killing it tonight" adds no player "tonight".

## Measured accuracy

Ground truth is one game with one commentator: 200 events, of which 191 are throws and 9 are defenses. The dev split is
everything before 463.3 s after the first word (2025-01-14T20:38:30.9) and has 96 events. The test split is everything after
and has 104 events. The rules were tuned on dev only. Cells show event F1 / exact F1.

| transcript | dev | test |
|---|---|---|
| hand-made, names as spoken | 1.000 / 1.000 | 0.990 / 0.942 |
| real Whisper large-v3-turbo, one pass (WER 0.10), names as spoken | 0.990 / 0.760 | 0.990 / 0.663 |
| same Whisper transcript, both sides resolved with PlayerResolver + descriptions | 0.990 / 0.948 | 0.990 / 0.837 |
| live transcript of the one-commentator end-to-end run ([results.md](results.md)), resolved, `--timeout 6` | 0.964 / 0.821 | 0.986 / 0.804 |
| live sliding-window transcript (WER 0.15; spike output, not in repo, before corrections), resolved, `--timeout 6` | 0.954 / 0.761 | 0.961 / 0.755 |

- **Corrections and roster teams** (October 2026). Before them: hand-made test 0.990 / 0.904, Whisper test 0.990 / 0.625 raw
  and 0.990 / 0.798 resolved, the live run 0.964 / 0.810 and 0.986 / 0.766. Dev did not change on either bundled transcript.
  - Both bundled transcripts now give the true final score, 14–9 (before: 14–10). "Blade in the end zone, nope, not in the end
    zone, caught by somebody" is a catch, and the next four throws, white's goal among them, stay white's.
  - Live, Whisper split that sentence across two groups ("Blade in the end zone?" | "Nope, ..."); it is right there too. The
    live run's transcript gives 14–10 (before 14–11). The other false goal is Whisper's "Picked Huck by Naked for a score".
  - The roster rule alone fixes 3 of those 4 throws' team. It also fixes "Deed by Joe" after that false goal on the live
    transcript: joe plays for white, so the block is white's and the throw it stopped dark's (dev exact +0.011).
- **Hand-made transcript, without team files:** 1.000 / 1.000 on dev and 0.990 / 0.942 on test.
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

## Substitutions

Substitutions are `ultimate.Substitution` events: team, player as spoken, `sub_type` `sub_on` or `sub_off`.

- **Phrases.** One or more names, then a substitution word: "subs on", "subbing off", "comes on", "subs out", or a bare "on" or
  "off" ("Tanner off purple off mock on Dylan on", "Close crop, Emily off", "kaia is on"). Also "fulmer on for cynic" (cynic off),
  "kaia off for white" (the team said), and "subbing on: ari and ben".
  - The word must end the phrase: a boundary, the clause's end, "and", a correction, or the next substitution. "blue yellow on the
    end zone for a score", "D-line comes on for dark" and "off the wall" substitute nobody.
  - Words that also describe play ("comes in", "coming in", "comes on", "comes off", "goes off", "heads off": `lexicon.LOOSE_SUBS`)
    need more: "for X", the end of the sentence, or another substitution in it. "Kaia comes in, Tristan goes off" and "Joe comes in
    for Kaia" substitute; "Kaia coming in, flick to Kaia" and "Joe comes in, catches it" do not.
  - A name right after "to", "caught by", "picked up by" or a throw word is that event's: "backhand swing to 50, Tristan off" and
    "Backhand swing close crop, Pikachu off" sub off only Tristan and Pikachu.
  - Jersey numbers: digits above 20 are names ("flick to 26", "26 off"), except in a score line whose other side is a score ("21 to
    19", "21-19", "19 to 21", "21 to nothing"; "26 to 50" is a throw); a smaller number is a name only right before the
    substitution word ("5 off"). "Five to three" is still a score line.
  - A name ending a group can start the next group's list ("Kyle" | "Fulmer on").
  - "intended for cynic" is "to cynic" (a throw).
  - An "on" ending a group is kept for the next group's team name ("picked up by blue on" | "dark") right after a pickup or a
    defense, when no name right before it could be substituted ("dropped... on" | "dark we have ..."), or after an identification.
    An identification standing alone ("red shorts is joe on", "red shorts is on") is kept whole, so "Red shorts is Joe on" |
    "dark." reads as "Red shorts is Joe on dark." (an identification, not a substitution). When the next group does not start with
    a team, or a timeout or the end comes first, the kept words are read as said, ending at the group's end ("Kaia is on" |
    "Flick to Joe": Kaia subs on). A substitution parsed that way a group late is no longer paired with a substitution off in the
    group before ("Dylan off." | "Kaia is on" | ...: Dylan keeps no team).
- **Team.** The team said ("for white"), else `team_of` the name, else another name of the same list, else the team of a player
  subbed off just before (within 10 s, nothing between: "Dylan off." | "Small gloves on."), which is also given to that player when
  only the later one's team is known. `team_of` is what the commentary said ("picks up for dark"), the rosters, and then the team of
  the name's last substitution. Throws' teams are not used: they follow possession, which misses turnovers nobody said. Otherwise
  the team is `""`; the stats fill it in from the player's other events.
  - `team_of` now also answers from substitutions, so a throw by someone subbed on for dark is evidence for dark. Without
    substitutions nothing changes.
  - "small gloves is joe", when small gloves was subbed on for dark and Joe is on white's roster, records no association: this Joe
    plays for dark.
- **Order and corrections.** A substitution said while a throw is still open waits behind it, so `events` stay in time order. A
  group with substitutions waits for the next group, like a score. "Nope" right after a substitution (alone, or followed by one of
  the same kind or player: "Dylan on." | "Nope." | "Dylan off, mock on.", "Kaia on. Sorry, Tristan on.") takes it back. "er" does
  not. When a correction parses the group before again, the swap pairing and "nope" are made again too, and a renamed substitution
  that waited behind a throw keeps its correction ("Flick huck, caught by Joe, Tristan off." | "Sorry, Emily.": Emily off).
- **Line-ups.** With `lineups=True`, a line-up said for one team ("on white we have kaia, pikachu, tristan, glasses and short
  crop") makes a substitution on for each name, at the time it was said. The team is the one said, or the one team all its names
  are known on; "so we have Michelle's brother" makes none. "starts with" and "on the field" are line-up words too. It is off by
  default because the bundled ground truth has no substitutions: on, its line-up adds 5 events there, and dev event F1 drops from
  1.000 to 0.975 on the hand-made transcript and from 0.990 to 0.964 on Whisper's. Throws and defenses do not change either way. To
  turn it on in `yus-serve` and `yus-game`, the bundled ground truth needs its 5 subs on at 20:30:47.6, and the session must pass
  `lineups=True`.

### Measured

`tests/data/subbing_20250128T2050-*`: a 17-minute recording of another game (2025-01-28) whose commentator mostly narrates
substitutions, with some play. Its Whisper transcript (`yus-transcribe`, no team files) has 191 groups. White is Dump & Drizzle; dark
has no team file. The ground truth is a **draft** (`-draft-eventstream.json`, 177 substitutions, 77 throws, 7 defenses), labeled by
Claude from the transcript and from short clips transcribed again with names in Whisper's prompt. Nobody has listened to it yet.

| subbing transcript, names as spoken, no timeout | before | now |
|---|---|---|
| substitutions: precision / recall | — / 0.000 | 1.000 / 0.994 |
| substitutions: team right / unknown / wrong | | 0.795 / 0.205 / 0 |
| substitutions: player as spoken | | 0.824 (0.864 resolved with the game's descriptions) |
| throws: event F1 / exact F1 | 0.920 / 0.333 | 0.940 / 0.403 |
| throws: team right | 0.725 | 0.771 |

- The one missed substitution is Whisper's "Cinecon" for "Cynic on". Every wrong player is a Whisper mishearing: "Sarayan",
  "Sorayan" and "Ryan" (Serayan), "Steven" (resolves to Stephen Butler), "Mach" (mock), "Simic" (cynic), "Panner" (tanner),
  "Kristen" (Tristan), "Wandi" (blondie), "Larson shoes" (fluorescent shoes), "25" (26?). Those of white's roster belong in its team
  file as mondegreens; dark has no team file.
- Unknown teams are dark's first substitutions, before the commentary says any dark name's team ("Dylan picks up for dark" at
  20:53:52), and pairs of names nobody has placed yet.
- The bundled game is unchanged: both of its transcripts give byte-identical events, with and without a timeout. The review's
  fixes (below) change no event of either game's transcripts.
- Streaming gives the same events as batch (timeouts none and 6 s), final events never change, and events stay in time order.
  Random commentary with substitution phrases (`test_random_commentary_with_substitutions_streams_like_batch`; 8,000 seeds
  checked once) streams like batch with final events unchanged; before the review's fixes 2 of 6,500 seeds broke that, both by a
  correction that parsed the group before again and lost a swap's team or a "nope".
- Random play commentary without substitution phrases (1,500 seeds, the extraction tests' phrases): 14 give other throws and Ds
  than before substitutions were added (26 before the review's fixes). 7 now read a split "X is Y on" | "dark" as the same words
  in one group would, which the old code did not; 7 are "Fulmer on" | "dark", now a substitution, where the old code kept "on dark".

### The draft ground truth

Players are written as said, spelled correctly (Whisper's mishearings are extraction errors). Events marked `_unsure` in the file
are guesses (times are the clock's minutes and seconds, 20:51:03 to 21:08:03):

- 51:29.6 "tristan" subs on: Whisper's full decode heard "Kristen", two decodes of the clip "Tristan" (who subs off at 53:39).
- 51:43.6 "kyle" on: said "Kyle, Fulmer on"; maybe a slip corrected to Fulmer.
- 52:52.0 "butler" on is taken as Stephen Butler, who comes on again at 55:09 without going off.
- 53:25.1 "26" on: Whisper heard "25" three times; 26 fits (white needs a player after "Emily off", and 26 catches at 53:36).
- 53:35.8 and 54:06.9 "serayan": heard as "Ryan" and "So Ryan".
- 53:37.1 receiver "50", heard once: a jersey number?
- 00:48.2 "fluorescent shoes" on: heard as "Larson shoes".
- 02:06.6 "Close crop, Emily off" with only "Pikachu on" after it: white would be one short.
- 03:28.9 said "Dylan on. Nope. Dylan off, mock on.": there is no "dylan on".
- Throws: outcomes not said (51:19.7 "intended for cynic", 53:56.9 Cody's huck: both labeled incomplete), 52:30.4 receiver "taylor"
  (or "Turner"), 52:33.7 "Tanner in the end zone" taken as a goal, 57:26.1 "Steven Butler D's it. No deed. Caught by Tanner for a
  score" (no D), 59:48.6 and 03:03.0 goals Whisper garbled, 00:05.6 "Backhand swing, dump, Steven" (swing or dump).

The commentator also missed substitutions: players play while labeled off (Tristan at 02:15, Sebastian and Fulmer at 04:12, 26 at
06:24, glasses at 07:01) or come on twice. Those are what was said, not labeling errors.

## Latency and cost

Latency below runs from an event's first word to the end of the group that made it final. ASR delay comes on top of it:
about 7.7 s median for the live sliding window. The "first shown" columns are for the event's first, provisional appearance.

| transcript, timeout | final: median / p95 / max | groups waited (0 / 1 / 2) | first shown: median / max | later revised |
|---|---|---|---|---|
| hand-made, 6 s | 4.9 / 11.3 / 16.1 s | | 1.5 / 6.6 s | 9 of 200 |
| hand-made, 3 s | 4.7 / 9.9 / 14.2 s | | | |
| Whisper, 6 s | 5.4 / 15.6 / 28.1 s | | 1.6 / 14.0 s | 31 of 200 |

- **Scores wait for the next group.** That costs 0.4–0.6 s at the median and 3–4 s at p95; before, the rows were
  4.3 / 8.2 / 14.2 s (52 / 146 / 2 groups waited), 4.2 / 7.0 / 9.9 s (68 / 133 / 1) and 5.0 / 12.2 / 15.0 s (79 / 117 / 4).
  Whisper's long groups make its worst case 28 s: a score early in a 15 s group waits for the end of the next one. The new
  rows were measured with `advance()` every 0.25 s between groups; groups waited was not measured again.

- **Timeout trade-off:** a 6 s timeout costs nothing on either transcript; with no timeout the worst case is 14.2 s (hand-made)
  and 17.4 s (Whisper). A 3 s timeout costs 0.03–0.04 dev exact F1, and
  0 s costs 0.07–0.2.
- **CPU** (M3 Pro, Python 3.13): `feed()` plus `events` takes a median of 33–37 µs per group (18–22 µs before corrections:
  each group now starts with a copy of the state, to parse again from). That is about 10 ms for the whole 16-minute game.
  Building an extractor takes 0.35 ms.

## LLM assistance

`llm.AssistedExtractor` gives the groups the rules may have misread a second reading by a local model served by Ollama. It is
**off by default** (see [the decision](#decision-off-by-default)); `--llm MODEL` turns it on in `yus-events` and `yus-serve`.

```python
stream = extract_events(transcript, teams, llm=LLMAssistant("qwen2.5-coder:14b"))   # waits for each answer, up to the budget
extractor = AssistedExtractor(EventExtractor(teams, timeout=6.0), LLMAssistant("qwen2.5-coder:14b"))   # live: never waits
session = GameSession(game, descriptions, directory, llm=LLMAssistant("qwen2.5-coder:14b", url="http://localhost:11434", budget=10))
```

- **What is sent.** The rules parse every group first. A group also goes to the model when it has:
  - a correction word ("nope", "sorry", "actually", "no", "not", "wait");
  - a name in an event that no team file or line-up knows, said for the first time;
  - a throw without a receiver, then one without a thrower in the same sentence ("flick put huck close crop");
  - a name that no event used ("dropped by hat");
  - throw words that changed nothing.

  That is 9% of the hand-made transcript's groups, 19–22% of Whisper's, and 17% (32 of 191) of the subbing transcript's.
  Substitutions do not count: a name only they use is no new name, and a correction in a group with no throw, defense or
  throw word ("kaia on. sorry, tristan.") sends nothing.
- **What the model sees.** The teams, who had the disc, the two groups before, the group, and the rules' events for it,
  numbered: only throws and defenses. The group's substitutions are not shown, and keep their places in a revision. The
  throw still open from the group before comes first. A scoring group's events, waiting for this group, are
  not among them: the model could drop them, and the score with them. A fixed system prompt and five made-up examples come
  first too, and Ollama keeps them cached. The answer is held to a JSON schema: `{"correct":true}`, or the corrected list,
  where `{"same":N}` keeps event N.
- **Checks.** The rules' events stand when an answer:
  - breaks the schema, names a team that does not play, or uses a name nobody said;
  - adds a defense without a defense word;
  - changes more than its reason allows. A new name allows changing the events that name it, and merging the throw it
    split. A restated throw allows merging the pair. A correction allows anything. An unused name allows changing events.
    Only throw words that made no event allow adding one.
- **Live.** The rules' events show at once. The group's events, and everything after them, stay provisional until the
  answer comes or the budget runs out (10 s from the group's arrival). One question is asked at a time.
  - A revision replaces the group's events, and the later groups are parsed again, so a retracted score gives the disc back.
    A revised scoring group no longer waits: the next group cannot take its score back.
  - Final events never change. With answers released at random moments, the events end as if every answer had been waited
    for (tested on both transcripts).
  - A timeout or an error (Ollama not running) keeps the rules' events. `yus-serve` logs each question and its outcome.
  - A hung Ollama makes each group sent wait out its budget. The installed Ollama app's server once stopped answering
    while this was built; a separately started `ollama serve` worked.
  - It needs the 9 GB model loaded; the assistant asks Ollama to keep it for 30 minutes after each question.
- **Saved.** `answers` records each decision. `GameSession.save()` keeps them in `session.json`, and `load()` replays them
  without asking again.

### Measured

These runs used an M3 Pro, Ollama 0.5.4, and only the models already installed. They came before the rules learned
[corrections](#how-it-works), which now fix the retracted score themselves (rules: hand-made test 0.990 / 0.942, Whisper
test 0.990 / 0.837). Cells show event F1 / exact F1; Whisper names
are resolved with the descriptions file.

| transcript | rules | + qwen2.5-coder:14b | + llama3.2 (3B) |
|---|---|---|---|
| hand-made, dev | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| hand-made, test | 0.990 / 0.904 | 0.995 / 0.966 | 0.995 / 0.899 |
| Whisper one pass, dev | 0.990 / 0.948 | 0.990 / 0.938 | 0.990 / 0.896 |
| Whisper one pass, test | 0.990 / 0.798 | 0.990 / 0.846 | 0.971 / 0.767 |
| 18 rephrased snippets, all events right | 5 | 12 | 7 |

- **Hand-made test.** qwen fixed the retracted score, and with it the next four events' team. It also dropped "power" as a
  thrower and merged the restated throw. The checks rejected its answers for "across" and "bobbled", which merged away a catch.
- **Whisper dev.** It turned "Flick the yellow line" into receiver "yellow line", where the rules' "the yellow" was right.
- **Snippets.** The 18 snippets are passives, reversed order, corrections, restatements and words taken for names, none
  from this game. qwen still misses "wobbles" and "sails" as names, "nice grab by joe off a backhand from kaia", and
  retracted scores, which it reads as incomplete throws.
- **Time per question** (alone on the GPU): a median of 1.8 s, mostly confirmations. A revision takes 5–6 s and the longest
  10 s. llama3.2 takes 0.4–0.5 s, but its answers are worse.
- **Determinism.** Answers vary a little from run to run even at temperature 0: one Whisper correction came back
  "incomplete" in earlier runs and "caught" in the last.

**Live, end to end.** `yus-serve` with mlx Whisper, and `yus-replay` of the real audio in real time, one commentator, with
and without `--llm qwen2.5-coder:14b`. Both runs were made the same evening (compare [results.md](results.md)).

| | without | with |
|---|---|---|
| event F1 / exact F1 | 0.975 / 0.792 | 0.975 / 0.786 |
| ... dev; test | 0.964 / 0.821; 0.986 / 0.766 | 0.969 / 0.812; 0.981 / 0.762 |
| ... the same live transcript, rules only | | 0.980 / 0.800 |
| final score (truth 14–9) | 14–11 | 13–10 (rules only: 14–10) |
| groups sent | | 47 of 218: 41 confirmed, 3 revised, 3 timed out |
| question time: median / p90 / max | | 3.0 / 9.0 / 10.0 s |
| speech to settled: median / p90 / max | 11.0 / 15.2 / 27.7 s | 12.4 / 19.5 / 31.8 s |
| Whisper decode: median / p90 / max | 1.44 / 1.55 / 2.33 s | 1.46 / 1.94 / 3.59 s |
| GPU busy: Whisper; LLM | 50% | 52%; 18% |

- **Waiting for every answer on both live transcripts** (no timeouts, current checks): one went from 0.980 / 0.800 to
  0.975 / 0.795, the other stayed at 0.975 / 0.792, and white lost a goal in both.
- **Live groups are short and noisy.** "Gloves taps a dad." became a throw to "dad" before the checks stopped new events for
  unused names.
- **The retracted score.** Live, "Blade in the end zone? Nope, not in the end zone. Caught by somebody." came back as an
  incomplete throw on both transcripts. That removes the false goal but still gives the disc away, so white's next real goal
  still goes to black.

### Decision: off by default

On the bundled transcripts it improves held-out exact F1 (+0.06 hand-made, +0.05 Whisper) without hurting event F1. It still
stays off, because:

- **It does not help live.** On the same live transcripts it is neutral or slightly worse (event and exact F1 −0.005).
- **It costs time.** Settling takes 1.4 s longer at the median and 4.3 s longer at p90. 3 of 47 answers missed the 10 s
  budget, among them two useful fixes, and Whisper's decodes slow by 0.4 s at p90.
- **There is no GPU to spare with two commentators.** Whisper alone keeps the GPU 97–99% busy ([results.md](results.md)).
- **The test halves were not blind.** The triggers target the error kinds listed under [Limitations](#limitations), which
  came from the test half. The prompt avoids this game's phrases, but the test gains are optimistic.

It is worth trying again with a faster model of the 14b's quality, on a machine with GPU to spare. The rules now read the
retracted score as a catch; the model's other gains have not been measured against them.

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
- **Corrections reach only provisional events.** A score can be taken back in the next group, other events only in their own
  group, or while the throw is still open. Only the most recent throw is corrected: "no score" after a defense says nothing
  about the goal before it. A correction made after `timeout` seconds of silence comes too late.
- **Corrections not understood:** "for a score, wait, he stepped out" (no phrase for "out"), a correction of the throw type
  ("dump to killian; a flick dump"), a bare name after the cue's sentence ("to joe. Sorry. Tristan."), and "not joe, tristan,
  backhand to emily" (a name that starts a throw replaces nobody).
- **Cue words are also chatter.** "Oh no, tristan!" after "to joe for the score" makes tristan the scorer, and "oh no, he's
  not in" is no correction only because of "he's".
- **Roster teams need roster names.** After a false goal, throws among players described only in the descriptions file ("the
  kid", "blondie") keep the wrong team until someone on a roster is named. A Whisper mishearing of a roster name can move a
  throw to the wrong team; the rule never overrides a team just said or a thrower who caught the team's last pass.
- **Restatements.** "flick put huck close crop" starts a second throw.
- **The defender is lost when Whisper splits "deed" from "by X" across groups.**
- **Unsure outcomes.** A throw to the end zone with no "caught" or "score", followed by a pickup by the other team, counts as
  incomplete.
- **Jersey numbers.** Numbers up to 20 need "number twelve" outside a substitution: a bare "to 12" reads as a score line. No
  infraction events are produced.
- **Substitutions.** Only this commentator's phrasings were seen, all of the form "X off, Y on". Whisper's mishearings of names
  split one player into several ("Sarayan", "Sorayan"), which breaks on-field tracking until the team file lists them. The LLM
  assistant (`--llm`) neither sees nor corrects substitutions.
- **Old transcripts.** Whisper's "the ends of" for "to the end zone" (twice in dev) is now a mondegreen of the sport
  (`yus/sports/ultimate`), replaced when the transcript is made. A transcript made before that still says "the ends of", and
  the extractor no longer reads it as the end zone.
- **The test split is not fully blind.** An earlier spike's report described test-split errors before these rules were
  written. No rule targets them, but one dev-motivated rule happens to fix the trailing-"swing" case: a throw type or
  direction may describe the open throw across groups. Test numbers may therefore be slightly optimistic.
