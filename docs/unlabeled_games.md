# Games Without Ground Truth

`yus-game` was run on the ten recordings in the Drive folder that have no ground truth (October 2026, commit 94bac68,
mlx-whisper large-v3-turbo). Each run had one commentator, no descriptions file (except the subbing game's, in
`tests/data`), and team files without players (`white`/`light`, `dark`/`black`). In seven games the commentary names
Category 5 or Dump & Drizzle players (18:50 on 21 Jan only "Bush", twice), and those games used the real team file for
that side, in that game's colour. The outputs (game directories, `report.html`, CSV files, transcripts) were kept outside
the repository.

Times are wall-clock Mountain time from each file's metadata, so they can be checked against video. Teams are named by
their shirts, with players as heard, so the owner can identify them.

## How it was checked

- **Spoken score.** The commentator never says the running score. The one exception is 18:57:59 on 21 Jan ("score is
  currently dark five, white six"), at the start of a recording that began mid-game. So there was nothing to compare
  during play.
- **Pickup check.** After a goal, the team that was scored on picks up. For each YUS goal, the next pickup said with a
  team ("X picks it up for white", or a name said with a team elsewhere in that game) should be the other team's. Pickups
  said without a team are skipped.
- **Read from the words.** I read every "score" in the transcript, worked out who scored from the pickup that followed,
  and re-transcribed garbled stretches (15 short clips, cached model). This is an estimate, not ground truth.
- **Second ASR.** Two recordings also have older Amazon Transcribe transcripts. Each was converted to a yus transcript
  (one group per audio segment) and run through `yus-game` with the same team files.

## Results

Scores are written white–dark, with each side named as in the teams column.

| recording | date, time | teams as inferred (white – dark) | YUS final | spoken score | read from the words | confidence | real final (owner) |
|---|---|---|---|---|---|---|---|
| 20250114T2010-0700 | Tue 14 Jan 2025, 20:11–20:28 | white (josh, stash, tracy, 41, pink-and-purple) – dark (freilich, topknot, chief, stetson, anders, matt) | 11–13 | none said | 12–14 | good: pickup check 14/15; 2 garbled goals missed | |
| 20250114T2050-0700 | 14 Jan, 20:52–21:09 | white (seb, tracy, josh, pink shorts, 41, ethan, tattoo) – dark (kyle, blue, joe, red, curly, grant) | 13–7 | none said | about 10–10 | low: lots of chatter; no "end of game", so it may be cut off | |
| 20250114T2110-0700 | 14 Jan, 21:11–21:29 | white (parm, frank, tank, james, abby, liz, max) – Category 5 (turtle, Busch; hat, naked, bluey, yellow fringe, gloves) | 7–3 | none ("the 9-10 game" is the time slot) | about 6–5 | low: mostly substitutions and chatter; goals said without throws | |
| 20250114T2130-0700 | 14 Jan, 21:32–21:49 | white (tanner, kyle, cody, red, joe, dave, grant) – Category 5 | 12–16 | none said | 12–17 | medium: pickup check 15/15; 4 goal errors | |
| 20250121T1850 | Tue 21 Jan, 18:58–19:09 | white (red shoes, johnny, max, colton, parm, beard, liz, frank, abby) – Category 5? ("Bush scores for dark", twice) | 8–0 | start only: "dark five, white six" | 13–15 (6–5 before the recording) | poor: the commentator follows white, and his ten "dark scores" make no goal | |
| 20250121T1910 | 21 Jan, 19:11–19:29 | white (jared, steve, hoodie, jt, stetson, rally, chief, faded) – Dump & Drizzle | 14–14 | none said | 14–14 | high: pickup check 26/26 | |
| 20250121T1930 | 21 Jan, 19:31–19:49 | the same white – Category 5 (Busch, turtle; naked, red, sweatpants) | 17–14 (Amazon: 17–14) | none said | 16–14 | high: one retracted goal counted | |
| 20250121T2150 | 21 Jan, 21:51–22:09 | white (benji, bob, 98, tracy, sloth, 24, 25) – dark (orange, josh, pantstripe, leaf, olive) | 15–14 | none said | 16–15 | high: pickup check 28/28; 2 goals said "in the score" missed | |
| 20250128T1930 | Tue 28 Jan, 19:31–19:49 | Category 5 as white (Busch, turtle; gloves, naked, pink shorts) – dark (joel, max, red shoes, johnny, christian, parm, abby) | 15–17 (Amazon: 15–17) | none said | 15–17 | high: two errors cancel | |
| 20250128T2050-subbing | 28 Jan, 20:51–21:08 | Dump & Drizzle – dark (cody, sebastian, dylan, tanner, fulmer, mock) | 11–5 (Amazon: 10–8) | none said | 10–9 (draft truth) | poor for goals; substitutions good | |

Every recording except 20:50 on 14 Jan ends with "end of game" said, so no other game is cut off mid-point. 18:50 on
21 Jan starts mid-game, and YUS has no way to be told a starting score.

Some teams recur. 19:10 and 19:30 on 21 Jan have the same white team. Parm, abby and max play in 21:10 on 14 Jan, 18:50 on
21 Jan and 19:30 on 28 Jan. Tanner, kyle and cody play in 21:30 on 14 Jan and in the subbing game.

| recording | points | throws | turnovers | Ds | subs | goals per minute | throws per point | goals in order (W/D) |
|---|---|---|---|---|---|---|---|---|
| 20250114T2010 | 25 | 226 | 36 | 12 | 0 | 1.36 | 9.0 | DDWDW DDDWD DDDWD WWDWW WWWD |
| 20250114T2050 | 21 | 167 | 24 | 14 | 1 | 1.14 | 8.0 | DWDDW WWWDW WWDWW DWDWW |
| 20250114T2110 | 11 | 54 | 4 | 4 | 108 | 0.55 | 4.9 | WWWDW DWWWD |
| 20250114T2130 | 29 | 228 | 24 | 11 | 0 | 1.61 | 7.9 | WDDWD DDWWW DWDWW DDDWW DDWDD DWD |
| 20250121T1850 | 9 | 82 | 8 | 4 | 0 | 0.71 | 9.1 | WWWWW WWW |
| 20250121T1910 | 29 | 250 | 25 | 14 | 0 | 1.55 | 8.6 | WWWDW DDWDD WWDDD DWDWW DWWDD WDW |
| 20250121T1930 | 32 | 221 | 21 | 9 | 0 | 1.71 | 6.9 | WDDWW DWDWD WDWDW DWDWD WDWDW WDWDW W |
| 20250121T2150 | 30 | 236 | 28 | 15 | 0 | 1.63 | 7.9 | DWDDW WWDWD WDDWD WDWDW DDWDD WWWW |
| 20250128T1930 | 33 | 208 | 31 | 11 | 0 | 1.80 | 6.3 | DWDWD WDDWW DWDDW DDWWD WDWDW WDWDD WD |
| 20250128T2050-subbing | 17 | 74 | 7 | 7 | 171 | 0.94 | 4.4 | DWWWD WWWWD WDWWW D |

- Points count the one in play at the end. W is the white side, D the dark side, as in the first table.
- The well-narrated games have 1.4–1.8 goals per minute and 6–9 throws per point, and no team scores more than 5 in a
  row.
- The commonest unresolved names are the descriptions a descriptions file would map: close crop, glasses, leaf and blue
  for Dump & Drizzle; hat, naked, gloves and yellow fringe for Category 5. Sides without a roster are unresolved by
  design.

## Per game

- **14 Jan 20:10.** Two goals were lost to Whisper. At 20:20:41, "backhand to the end zone, somebody first four" was
  followed by a white pickup, so it was likely a dark goal. At 20:26:17, "41 in the end of the score" was a white goal.
  "Pink and purple" splits into two players.
- **14 Jan 20:50.** The commentator talks about YUS with someone between 20:56:48 and 20:57:48.
  - "That's the goal" in that chat became a white goal at 20:57:13.
  - "I can't" became a thrower, and possession was lost. So dark's goals at 20:58:38 (clip: "Dave, flick the blue. Flick
    huck, go for the score. 41 picks up for white") and 21:00:17 ("to rally for the score. Josh picks it up for white")
    went to white.
  - "Blue and the end zone for score" (21:06:01) made no goal.
  - Whisper repeats lines here ("Backhand to blue" six times at 21:05:36).
- **14 Jan 21:10.** This game is mostly substitutions, with long stretches of chatter. Whisper invents "I'm sorry" six
  times at 21:16:22.
  - Dark goals missed or misassigned: "gloves in the end zone for a score" (21:14:39) had no throw word. "Yellow fringe
    flick, naked, and end up. Score" (21:18:49) went to white.
  - White goal missed: "Max in the end zone for a score" (21:27:57), also without a throw word.
  - Unclear: "a little French hammer to close... for score" (21:21:57).
- **14 Jan 21:30.**
  - The first goal (21:32:13, "off the wall to Bush for a score. Picked up by Joe for white") went to white.
    "Dave, pull for white" did not give dark the disc, and the roster did not correct a chain of passes.
  - "Hammer to Joe in the end zone. I mean flick to Joe in the end zone" (21:40:03) counted twice.
  - White goals missed: "to red in the end zone for speed" (21:36:22) and "Rally for score" (21:40:46).
  - "Pantstripe" is heard in 10 spellings.
- **21 Jan 18:50.** "Dark scores" (ten times, e.g. 18:59:20, 19:00:16, 19:03:45) has no throw, so it makes no goal. YUS
  also counts "cross field to Abby in the end zone. Drops it. No score." (19:00:40) as a white goal.
- **21 Jan 19:10.** The words and YUS agree on every goal. The Dump & Drizzle roster corrected one goal's team that the
  run without rosters had wrong (19:18:52; 15–13 without rosters).
- **21 Jan 19:30.** "Busch for score. Wasn't a score. Backhand to 16 for a score." (19:48:15) gave dark a goal and white a
  goal. Only dark's (to 16) was real. "To 16" loses its receiver, because a number up to 20 reads as a score.
- **21 Jan 21:50.** Two goals were said "in the score" and missed: dark at 21:54:50 ("orange in the score for an end
  zone") and white at 22:00:22 ("blade to Tracy in the score").
- **28 Jan 19:30.** "Sit down, he scores!" (19:36:21) became an extra Category 5 goal. Whisper heard "Rally Cat for a
  squoo" (19:46:12), and that goal was missed; Amazon heard "for score".
- **28 Jan 20:50 (subbing).** See below.

## Two ASRs

| recording | events (Whisper / Amazon) | event F1 / exact F1 | team / player / receiver agree | goals at the same time and team | final |
|---|---|---|---|---|---|
| 21 Jan 19:30 | 230 / 228 | 0.974 / 0.690 | 0.991 / 0.839 / 0.850 | 31 of 31 | 17–14 both |
| 28 Jan 19:30 | 219 / 212 | 0.956 / 0.668 | 0.990 / 0.845 / 0.853 | 31 of 32 each | 15–17 both |

The two ASRs give the same score. They agree on who did what about 85% of the time, and on teams 99%. On 21 Jan both
make the same extraction error (the retracted goal), so agreeing scores do not prove a right score.

## The subbing game

These numbers are against the draft truth in `tests/data/subbing_20250128T2050-*` (177 substitutions, 19 goals).

- **Substitutions.** 171 extracted: precision 0.988, recall 0.955. sub_type is always right; the player as spoken
  matches 80% of the time.
  - Team: right 72%, none 27% (mostly dark's), wrong 3. Two are dark's small gloves, whom the commentator calls "Joe"
    ("small gloves is Joe", 20:59:45): YUS makes them Dump & Drizzle's Joe Oaks. The third is "larson shoes" (dark's
    fluorescent shoes), swapped with one of them.
  - The tests' transcript, made without team files, gives 1.000 / 0.994. Priming Whisper with Dump & Drizzle's roster
    changed some words. Amazon's transcript gives 0.988 / 0.898.
- **Score: 11–5 against the draft's 10–9** (Amazon: 10–8).
  - Missed, said without a throw: "Close crop off, Butler on, glasses for a score" (20:52:50), "26 in the end zone for
    score" (20:54:26), "Cody in the end zone for a score" (21:06:08).
  - Dark goals given to Dump & Drizzle: 20:59:10 and 20:59:48, after turnovers nobody said during substitutions, and
    21:03:03, "to Joe in the end zone".
- **Points played and plus-minus are not usable.**
  - Dump & Drizzle has 16 player rows for 9 players: Serayan is heard four ways, 26 as "25", and two dark players land
    on its side.
  - Points played add up to 58 for Dump & Drizzle and 64 for dark, against at least 85 (5 per point); the truth has 114
    and 112. Most Dump & Drizzle player-time is unknown.
  - Plus-minus adds up to −15 for dark, against −5 in the truth.

## Failure patterns

1. **A goal said without a throw word makes no goal.** Examples: "dark scores", "Max in the end zone for a score",
   "Rally for score". This lost 10 goals in the white-only commentary, 3 in the subbing game and 1–2 in three others.
2. **Whisper garbles the score phrase**: "somebody first four", "in the end of the score", "in the score", "for speed",
   "for a squoo". About one goal per game is lost this way.
3. **Lost possession puts goals on the wrong team.**
   - It is lost after chatter, at the pull ("Dave, pull for white"), and after turnovers nobody said during
     substitutions.
   - Rosters fix it only when a roster name is on the throw, and not when that thrower caught the previous pass. Most
     players here are descriptions.
   - A roster can also pull another team's player across: the subbing game's "Joe" is dark's small gloves, not Joe Oaks.
4. **Corrections and restatements.** Three cases:
   - "I mean flick to Joe in the end zone" restates a goal, and both count.
   - "Wasn't a score" does not take a goal back.
   - "In the end zone. Drops it. No score." still counts: the "no score" comes two groups later.
5. **Conversation becomes play.** The commentator talks with others in two games: "that's the goal" became a goal, and
   "I can't" a thrower. Whisper also loops in those stretches ("I'm sorry" ×6).
6. **Names.**
   - A description or name is heard in many spellings (pantstripe ×10, Serayan ×4).
   - Numbers up to 20 are lost as receivers ("to 16 for a score").
   - "Pink and purple" splits into two players.
   - Sides without a roster leave every name unresolved.
7. **Nothing in the commentary checks the score.** It never states the running score, so only the pickups after goals
   can catch a wrong goal. A recording that starts mid-game has no way to give YUS its starting score.

## Reproducing

```bash
yus-game --team white.json --team cat5_dark.json --commentator "Gavin=20250114T2130-0700.ogg" --game-dir games/x
```

The commands above were run with `HF_HUB_OFFLINE=1`.

- `white.json` is `{"names": ["white", "light"], "players": {}}`, and `dark.json` is the same with `dark`, `black`.
- The real team files keep their players, with that game's colour as their names, e.g. Dump & Drizzle as
  `["Dump & Drizzle", "dark", "black"]` at 19:10 on 21 Jan.
- The subbing game also used `--descriptions tests/data/subbing_20250128T2050-descriptions.json`.
- Amazon's JSON became a yus transcript with one group per `audio_segments` entry. Its words were timed from the
  recording's start, and each punctuation item was joined to the word before it.
