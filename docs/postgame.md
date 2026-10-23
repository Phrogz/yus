# Processing a Game Afterwards

`yus-game` (`yus/game_cli.py`) turns the recordings of one game, from one or more commentators, into one official event
stream and its stats, after the game. It writes a game directory that the dashboard shows, an HTML report, and CSV tables,
and lists what a person should fix.

## Where it fits

```text
per commentator:  recording --yus-transcribe--> transcript (or a transcript JSON as it is)
                  --> GameSession: EventExtractor --> PlayerResolver (+ descriptions) --> merge (2+ commentators) --> compute_stats
```

The session is the one `yus-serve` runs live ([session.md](session.md)), fed every group at once and finished. So the
results are those of `yus-events` → `PlayerResolver` → `merge_streams` → `compute_stats`, and spoken identifications
("red shorts is kaia") apply as they do live.

## Usage

```bash
yus-game --team white.json --team dark.json --descriptions game-descriptions.json \
    --commentator "Gavin Kistner=20250114T2030-0700.ogg" \
    --commentator "Sam=sam.ogg@-42:dark"
```

`--commentator NAME=PATH[@OFFSET][:FOCUS]`, once per commentator; the first is the clock reference.

- `PATH`: a recording, which `yus-transcribe` transcribes in its own process, or a yus `Transcript` JSON (`.json`), used as it is.
  A JSON without `groups` (an event stream, a team file) or without words is refused.
- `@OFFSET`: seconds added to this commentator's times, e.g. `@-42` for a recording whose clock is 42 s ahead. Merging
  estimates offsets up to 20 s by itself, so give one only for clocks further apart.
- `:FOCUS`: the team this commentator follows (any of its names). In a merge conflict on that team's events, they win.
- A `PATH` that exists is taken whole, even with `@` or `:` in its name.

| option | |
|---|---|
| `--team` | team JSON files, one per team (two or more) |
| `--descriptions` | the game's descriptions file ([usage.md](usage.md#game-description-files)) |
| `--game-dir DIR` | the game directory (default `games/<start>`, see [Times](#times)); refused if it holds a game, unless `--force` |
| `--html FILE` | the report (default `DIR/report.html`) |
| `--csv-dir DIR2` | the stats tables (default `DIR/stats/`) |
| `--asr`, `--model` | Whisper backend and model for recordings (default: `yus-transcribe`'s) |
| `--stop S` | transcribe only the first S seconds of each recording (a quick try) |
| `--retranscribe` | transcribe recordings again, though their transcripts are kept |

Before anything is transcribed, these are checked: the commentators, the descriptions file against the rosters, the
transcript JSONs, and the game directory (if its default name is known by then: see [Limitations](#limitations)).

### Transcripts of recordings

Each recording's transcript is kept beside it, as `yus-transcribe` writes it: `game.ogg` → `game.transcript.json`
(`game.stop120.transcript.json` with `--stop 120`). Running again uses it instead of transcribing, and says so; a transcript
`yus-transcribe` wrote before is used too. If the recording's folder can't be written, a warning says so and the transcript is
only in the game directory.

### Times

A recording is timed from its start: the creation time in its metadata, else a time in its name like
`20250114T2030-0700.ogg` (as `yus-transcribe` finds it). A recording that says neither is taken to start with the first
commentator's recording (or their transcript's first word), and a note says so: give `@OFFSET` if it started more than
20 s apart.

The game starts with the first commentator's recording (its start, `@OFFSET` added), else their first word. That names the
default game directory and is 0:00 for the report's times. Word times with a UTC offset are taken in their own zone, as
`compute_stats` takes them.

## Outputs

- **Game directory**, as `GameSession.save()` writes it ([session.md](session.md#files)): `game.json`, `descriptions.json`,
  `transcripts/`, `events/`, `official.json`, `session.json`. Show it on the dashboard with
  `yus-serve --load DIR --asr none` (`--asr none` skips loading Whisper). The transcripts there are on the game's clock,
  `@OFFSET` applied: to run from them, pass them without `@OFFSET`. `--force` also deletes the replaced game's
  `transcripts/` and `events/` files of commentators it no longer has.
- **HTML report**, one page: the score; the commentators (follows, file, groups, events, clock offset); what to check;
  the team box score; each team's players (names that are not roster players in italics); the points (offense, scorer, hold
  or break, assist → goal, running score); and every event, with who reported it and what the commentators disagreed on.
- **CSV**: the 12 stats tables, as `yus-stats --format csv` writes them ([stats.md](stats.md#api)).
- **Terminal**: the score, each commentator (groups, events, estimated offset, focus), the merge's settled conflicts by rule,
  then what to fix.

### What to fix

- **Unresolved names**, per team, most mentioned first, and the roster players no event names (likely identities). Add the
  names to the descriptions file and run the same command again with `--force` (recordings' transcripts are reused).
- **Team conflicts:**
  - a name said for one team that only another team's player answers to (in the team files or the descriptions):
    `"the kid" (2x for Category 5) is Dump & Drizzle's Serayan Knappe-Butler`. The event's team is wrong, or the name needs
    a description: one for the team said, a player or an unknown player's label, clears it. Read from each commentator's
    events as extracted (`PlayerResolver.team_conflicts`).
  - stretches of play that two commentators put on different teams, e.g.
    `2:48–3:04: 7 throws A put on Dump & Drizzle, B on Category 5`. Merging pairs only events of one team, so both reports
    stay in the official stream. Found from events reported by one commentator each, of one kind and different teams,
    within 3 s; matches less than 15 s apart form one stretch.
- The report also lists every field the commentators disagreed on, with what each said and the rule that settled it.

## Measured

On an M3 Pro at commit af27691, against the hand-made ground truth (`tests/data/gruindoor_20250114T2030*`); event F1 /
exact F1 as `yus-score` computes them, with names resolved by the descriptions file. Dev is before 463.3 s (20:38:30.9),
test after.

| input | events | score (truth 14–9) | F1 / exact: all | dev | test |
|---|---|---|---|---|---|
| hand-made transcript | 200 | 14–10 | 0.995 / 0.950 | 1.000 / 1.000 | 0.990 / 0.904 |
| Whisper transcript (`-whisper-turbo.json`) | 200 | 14–10 | 0.990 / 0.870 | 0.990 / 0.948 | 0.990 / 0.798 |
| synthetic A (hand-made, every 7th group missed) | 170 | 13–8 | 0.908 / 0.703 | 0.910 / 0.742 | 0.906 / 0.667 |
| synthetic B (every 5th missed, 5 s ahead, light/dark) | 159 | 9–9 | 0.880 / 0.663 | 0.872 / 0.628 | 0.888 / 0.695 |
| A (white) + B (dark), merged; offset −5.00 s | 203 | 14–10 | 0.958 / 0.789 | 0.964 / 0.829 | 0.952 / 0.752 |
| A + B with B 90 s ahead, no `@OFFSET` (offset −13.5 s, wrong) | 311 | 14–11 | 0.751 / 0.446 | 0.788 / 0.519 | 0.721 / 0.386 |
| ... with `@-90` | 203 | 14–10 | 0.958 / 0.774 | 0.964 / 0.829 | 0.952 / 0.724 |
| two live transcripts of the real audio, merged afterwards | 207 | 14–10 | 0.968 / 0.791 | 0.954 / 0.843 | 0.981 / 0.743 |
| ... the run after the settling fix | 206 | 14–10 | 0.975 / 0.793 | 0.964 / 0.802 | 0.986 / 0.785 |

- **Today.** Since the extractor takes back corrected scores (commit fc4448d), the hand-made transcript gives 14–9 and
  0.995 / 0.970 (dev 1.000 / 1.000, test 0.990 / 0.942), and Whisper's 14–9 and 0.990 / 0.890 (0.990 / 0.948,
  0.990 / 0.837). The other rows were not run again.
- **Live vs afterwards.** The last two rows are the transcripts of two earlier two-commentator runs (the same audio
  streamed twice, about 5 s apart, focus white and dark), scored after moving them back onto the recording.
  Merged afterwards, they give the live runs' event F1 (0.968 / 0.796 and 0.975 / 0.793 live) and offsets of −5.34 s
  and −5.06 s (−5.33 s and −5.06 s live). The score is 14–10 against 13–10 live: merging now keeps a score that one
  commentator heard and the other heard as two throws (white's goal at 154 s). With the merge before that change,
  afterwards also gave 13–10.
  The two-commentator runs now in [results.md](results.md), merged afterwards at commit c11b795, give their live event F1
  (0.975 / 0.828 and 0.966 / 0.809) and score (14–9), with offsets of −5.10 s and −5.12 s (−5.10 s and −5.09 s live).
- **Speed.** Processing a whole game from transcripts takes 0.05–0.13 s (one or two commentators), about 0.6 s with the
  command's start-up. The slow test transcribes the first 120 s of the real recording with mlx-whisper large-v3-turbo
  (17.5 s in all, model loading included): 17 events, event F1 0.968, exact 0.839 up to 115 s.
- **Reload.** `GameSession.load` of the game directory gives the same official events and score (tested with one and two
  commentators).

## Limitations

- **No real second commentator.** Merging was measured on synthetic commentators and on one recording streamed twice.
- **Offsets.** Clocks more than 20 s apart need `@OFFSET`; a wrong estimate (as in the 90 s row) is not detected, though
  the team conflicts and a high event count hint at it. A clock that drifts within a recording is not followed: the batch
  merge keeps one offset per commentator.
- **Recordings without a start time** are assumed to start with the first commentator's.
- **Transcribing** runs one recording after another: about 1.5 minutes for the 16-minute game on an M3 Pro (from the slow
  test's decoding rate, not timed). A kept transcript is reused even if `--model`, `--asr` or the team files changed: pass
  `--retranscribe`.
- **A recording without a start time**, first and not transcribed yet, names the game directory only once transcribed, so a
  game already there is found only then (its transcript is kept).
- **Extraction and merging** keep their own limits ([extraction.md](extraction.md#limitations), [merging.md](merging.md#limitations)),
  e.g. a score taken back two groups later still counts.
- **Team conflicts** between commentators are found only for events nobody else reported; a whole possession put on the
  wrong team by the only commentator who saw it is not.
