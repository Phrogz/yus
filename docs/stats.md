# Stats

`yus.processing.stats` turns an event stream into pandas tables: box scores for teams and players, points, possessions, the
running score, throw types and directions, and who throws to whom.

## Where it fits

```txt
transcript --yus-events--> raw events (names as spoken) --PlayerResolver--> resolved events --compute_stats--> DataFrames --> UI
```

Stats run last, on a stream whose names `PlayerResolver` has already mapped to players (see
[Game Description Files](usage.md#game-description-files)); with several commentators, on the merged stream. They are a pure
function of the stream: live, recompute them whenever an event arrives (about 9 ms for a whole game).

## API

```python
from yus.processing.stats import compute_stats

stats = compute_stats(resolved_stream, teams=game.teams)        # teams optional
stats.summary()                    # "Dump & Drizzle 14, Category 5 9 (point 24 in play)"
stats.score                        # {"Dump & Drizzle": 14, "Category 5": 9}
stats.player_box.loc[("Dump & Drizzle", "Tristan Weber")]
stats.connection_matrix("Dump & Drizzle", "throws")             # thrower x receiver
live = compute_stats(stream, game.teams, provisional_from=180)  # events 180+ flagged "provisional"
```

`compute_stats(stream, teams=None, provisional_from=None) -> GameStats`

- `teams`: merges the names events use for one team (`"dark"`, `"black"`) under the team's first name (`"Category 5"`) and fixes
  the team order; teams without events still get a row. Without it, teams are labelled as the events name them.
- `provisional_from`: events from this index on are counted, but flagged `provisional`, as is every derived row they change
  (a new row, or one that differs from the stats of the events before the index), so a UI can style them (e.g. words live
  transcription has not confirmed yet). For example, a provisional throw that starts a point flags both teams' `team_box` rows
  (their `o_points` / `d_points`).

`GameStats` holds `teams`, `score`, `start` (what `elapsed` counts from: the stream's `game.when`, else its first event),
`summary()`, `connection_matrix(team, value)`, `tables(names)`, and these DataFrames. Every table has a `provisional` column.

| Table | Index | Columns |
| ----- | ----- | ------- |
| `throws` | event | when, elapsed, team, player, receiver, type, direction, completed, scored, hit_wall, hit_net, point, possession |
| `defenses` | event | when, elapsed, team (the defender's), player, intercepted, point, possession (the one the D ended) |
| `substitutions`, `infractions` | event | when, elapsed, team, player, (sub_type), point |
| `possessions` | possession | point, team, start, end, duration_s, throws, completions, outcome |
| `points` | point | o_team, start, end, duration_s, possessions, throws, turnovers, scored_by, assist, scorer, hold, suspect |
| `team_box` | team | goals, possessions, o_points, holds, d_points, breaks, throws, completions, turnovers, ds, interceptions, hucks, huck_completions, wall_throws, net_throws, goals_per_possession, completion_pct, huck_completion_pct |
| `player_box` | team, player | throws, completions, assists, hockey_assists, goals, targets, catches, drops_or_misses, turnovers, ds, interceptions, hucks, huck_completions, completion_pct |
| `throw_types` | team, type | throws, completions, goals, turnovers, completion_pct |
| `directions` | team, direction | same as `throw_types` |
| `connections` | team, thrower, receiver | same as `throw_types` |
| `score_timeline` | goal | event, when, elapsed, point, team, assist, scorer, hockey_assist, hold, `score_<team>` (running score) per team |

Raw tables hold one event type each, so their bool columns stay `bool`. Flags that may not be known yet use nullable dtypes
(`hold` is `boolean`, NA while the point is in play; a D before any throw has possession `<NA>`). Percentages are 0-100,
rounded to 0.1, and NaN when nothing was thrown. A throw type or direction nobody said is `"unknown"`. Running-score columns
carry the `score_` prefix (`SCORE_PREFIX`) so that no team name can clash with a fixed column.

Times are naive. Times with a UTC offset are converted to the zone of the first one whose offset isn't UTC (the commentator's
local time; naive times in the same stream are taken to be in it), else, when all are UTC, to this machine's local time, as
transcription does. So a stream written with `-07:00` offsets gives the same tables as one without.

### Definitions

- **Possession**: starts with a throw after a goal, after an incomplete throw, or by the other team (the first throw of a
  possession is the pickup). Outcome: `goal`, `turnover`, `in play` (the last one), or `unknown` (the other team threw next
  without a recorded turnover: an extraction gap).
- **Point**: ends with a goal. Indoor rules: the first point starts with the pull, and after a goal the team scored on picks
  up, so `o_team` is the team that threw first in the point. **Hold**: `o_team` scored; **break**: the other team did. A point
  starts when the previous one ended (the first at `start`), so durations add up to the game time. **suspect**: `o_team` scored
  the point before, which indoor rules forbid; the events have a wrong goal or team there (none in the ground truth; 1 of 25
  points in the event extractor's output on both transcripts).
- **Turnover** (team and player): an incomplete throw, charged to the thrower. So for every team, completions + turnovers =
  throws. **drops_or_misses**: incomplete throws to a receiver, whatever the cause (drop, D, bad throw).
- **Assist** / **goal**: thrower / receiver of a scoring throw. **Hockey assist**: thrower of the previous throw in the same
  possession.
- **Unknown players** (`None`) are left out of `player_box` and `connections` but counted in the team tables.
- **Unknown teams**: the event extractor writes team `""` when it can't tell (e.g. before any team is named). Such a throw gets
  the team that had the disc: after the previous throw (the same team after a completion, the other one after a turnover or a
  goal), else before the next throw; a D gets the defending team. The "other team" needs exactly two teams. A team that still
  can't be told is `None`: the event stays in the raw tables, points and possessions, but out of `teams`, `score`, the summary
  and every per-team table.

## CLI

```bash
yus-stats game.events.json --team team_dump_and_drizzle.json --team team_category_5.json \
  --descriptions game-descriptions.json                       # text tables to stdout
yus-stats game.events.json --team ... --format csv -o stats/    # one CSV per table
yus-stats game.events.json --team ... --format html -o stats.html --tables team_box,player_box,points
```

- `EVENTS` - EventStream JSON with `"__type__"` tags, as `yus-events` writes it (names as spoken).
- `--team` - team JSON files; resolves names with `PlayerResolver` and labels teams by their first name. Players nobody has
  identified yet are listed on stderr.
- `--descriptions` - the game's descriptions file (needs `--team`); `--commentator` - whose stream it is, for commentator-specific
  descriptions.
- `--format text|csv|html` (default text); `--tables a,b` (default: all derived tables; the raw ones are `throws`, `defenses`,
  `substitutions`, `infractions`); `-o` a file (text, html; default stdout) or a directory (csv; default `EVENTS-stats/`).

## Measured

On the ground-truth game (`build_game().official_stream`, 200 events), checked in `tests/test_stats.py` against the transcript
words rather than the events: white 14, black 9 (23 goals = 22 "for a score" + 1 "in the end zone caught by"); 9 Ds = "deed"/
"stolen", 2 interceptions = "stolen"; 21 turnovers = groups saying deed/stolen/dropped/turf/"no score"; all 32 pickups said for
a team ("picks it up for white") start a possession of that team; 44 possessions alternate teams; white holds 6 and breaks 8,
black holds 6 and breaks 3.

Recompute time (Apple Silicon, best of 15 runs): 9 ms for the 200-event game (11 ms including `PlayerResolver`), 14 ms for
1,000 events, 38 ms for 5,000. Most of it is building the 12 DataFrames, so it barely grows with the game. Every prefix of the
game (all 201 tested) gives the same rows as the full game for the events so far, except the point and possession still in
play, whose end and outcome change as the game goes on. With the last 1 or 3 events of a prefix provisional, every row that
differs from the stats of the final events alone is flagged. Live on the event extractor's output for the real Whisper
transcript, recomputed after each of its groups, the slowest recompute is about 13 ms.

The stats are exact for the events they are given; their accuracy is that of event extraction and player resolution.

## Limitations

- Events are taken in stream order; a merged stream must be sorted by time.
- No line tracking: no points played or plus-minus (substitutions are tabled but not used).
- A turnover is charged to the thrower and also counted as a drop-or-miss for the receiver; the stream does not say whose fault
  it was. Stalls, fouls and callahans are not modelled.
- Possessions are split by throws only: a D logged after a throw marked complete does not end the possession.
- Without `teams`, `"dark"` and `"black"` are two teams (and, with three labels, an empty team can't be inferred as "the other
  team").
- `o_team` is what the events say; a `suspect` point is flagged, not corrected.
- `elapsed` counts from the game's start only when the stream carries its `Game`; a stream loaded from JSON counts from its first
  event (so the CLI's first point is 4.2 s shorter than the API's on the ground truth game).
