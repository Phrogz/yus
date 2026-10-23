# Stats

`yus.processing.stats` turns an event stream into pandas tables: box scores for teams and players, points, possessions, the
running score, throw types and directions, and who throws to whom. From substitutions it also tracks who is on the field: points
played, playing time and plus-minus per player, and each team's line combinations.

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
stats.on_field.loc[("Dump & Drizzle", "Matt Whitlock")]          # points played, seconds on, plus-minus (teams with substitutions)
stats.lines.loc["Dump & Drizzle"]                                # one row per line of five, and "unknown"
```

`compute_stats(stream, teams=None, provisional_from=None, line_size=5) -> GameStats`

- `teams`: merges the names events use for one team (`"dark"`, `"black"`) under the team's first name (`"Category 5"`) and fixes
  the team order; teams without events still get a row. Without it, teams are labelled as the events name them.
- `provisional_from`: events from this index on are counted, but flagged `provisional`, as is every derived row they change
  (a new row, or one that differs from the stats of the events before the index), so a UI can style them (e.g. words live
  transcription has not confirmed yet). For example, a provisional throw that starts a point flags both teams' `team_box` rows
  (their `o_points` / `d_points`).
- `line_size`: players per team on the field (indoor: 5). `None` if not known: then no line is ever known.

`GameStats` holds `teams`, `score`, `start` (what `elapsed` counts from: the stream's `game.when`, else its first event),
`line_size`, `summary()`, `connection_matrix(team, value)`, `tables(names)`, and these DataFrames. Every table has a `provisional`
column. `derived()` names the derived tables, with `ON_FIELD_TABLES` (`on_field`, `lines`, `shifts`) when some team has
substitutions; `tables()` without names gives those and the raw ones.

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
| `on_field` | team, player | points_played, time_on_s, time_unknown_s, goals_for, goals_against, plus_minus, goals_unknown |
| `lines` | team, line | points, time_s, goals_for, goals_against, plus_minus |
| `shifts` | shift | team, player, state (`on`, `off`, `unknown`), start, end, duration_s |

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
- **On the field** (`on_field.py`). Only substitutions (and line-ups, said as substitutions on: see
  [extraction.md](extraction.md#substitutions)) say who is on the field, so only teams with a substitution have rows, from their
  first one on, and only the players substituted for them.
  - A player's state between two things said about them follows from both: "a on" then "a off", or "a on" then a throw by a,
    means on in between. "a off" then "a off" again, or "a off" then a throw by a, means a substitution was missed: unknown. Before
    the first thing said, unknown. After the last, the state of the last substitution stays, unless something said since
    disagrees; a throw, catch or D alone says only that they were on then.
  - Substitutions of one team said within 5 s (`BURST`), with no goal between, are one swap, made at the first one's time.
  - A swap said within 10 s of a goal (`AFTER_GOAL`), with no throw or D since, was made between points: at the goal's time, so
    that a player subbed off just after a goal gets neither the next point nor its seconds. The goal itself still counts the
    players on before the swap. A later swap, or one after the next point's first throw or D, was made when said (subs here are
    made on the fly: in the subbing commentary, substitutions are said all through points of 20-60 s).
  - When `line_size` players of a team are known to be on, the rest are off, and the line is known. When more would be on, a
    substitution was missed, and every player of that team is unknown until it clears up.
  - `points_played`: points in which the player was on at some time, or threw, caught or made a D. `time_on_s` and
    `time_unknown_s` count seconds from `start` to the last event. `goals_for` and `goals_against` count goals while the player
    was on (at the goal's moment: subs said after it count for the next point), `plus_minus` is their difference, and
    `goals_unknown` counts goals while their state was unknown. Nothing unknown is guessed or counted as on or off.
  - The dashboard leaves the completion percentage of a player who never threw blank (also one only subbed on).
  - `lines`: the team's five as one label (names sorted, joined by ", "), with `unknown` for the time the line is not known. A
    line's `points` are the points it was on the field for at some time.
  - A substitution with no team gets its player's: the one team of their other substitutions, else of their throws, catches and Ds.
  - The dashboard's Players table shows `points_played`, `time_on_s` (in minutes) and `plus_minus` as Pts, Min and +/-, blank for
    a team with no substitutions.
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
- `--format text|csv|html` (default text); `--tables a,b` (default: all derived tables, with `on_field`, `lines` and `shifts` when
  a team has substitutions; the raw ones are `throws`, `defenses`, `substitutions`, `infractions`); `-o` a file (text, html; default
  stdout) or a directory (csv; default `EVENTS-stats/`).

## Measured

On the ground-truth game (`build_game().official_stream`, 200 events), checked in `tests/test_stats.py` against the transcript
words rather than the events: white 14, black 9 (23 goals = 22 "for a score" + 1 "in the end zone caught by"); 9 Ds = "deed"/
"stolen", 2 interceptions = "stolen"; 21 turnovers = groups saying deed/stolen/dropped/turf/"no score"; all 32 pickups said for
a team ("picks it up for white") start a possession of that team; 44 possessions alternate teams; white holds 6 and breaks 8,
black holds 6 and breaks 3.

Recompute time (Apple Silicon, best of 15 runs): 9 ms for the 200-event game (11 ms including `PlayerResolver`), 14 ms for
1,000 events, 38 ms for 5,000. Most of it is building the 15 DataFrames, so it barely grows with the game. Every prefix of the
game (all 201 tested) gives the same rows as the full game for the events so far, except the point and possession still in
play, whose end and outcome change as the game goes on. With the last 1 or 3 events of a prefix provisional, every row that
differs from the stats of the final events alone is flagged. Live on the event extractor's output for the real Whisper
transcript, recomputed after each of its groups, the slowest recompute is about 13 ms.

The stats are exact for the events they are given; their accuracy is that of event extraction and player resolution.

**On the field**, on the 2025-01-28 subbing commentary (`tests/data/subbing_20250128T2050-*`; the ground truth is a draft, see
[extraction.md](extraction.md#substitutions)), names resolved with the team file and the game's descriptions file:

- From the draft truth (177 substitutions, 19 goals), each player's state is known for 87% of player-seconds. White's line of five
  is known for 516 s of 1,015, dark's for 650 s. The commentator missed some substitutions; each one leaves a player unknown
  until they are mentioned again.
- Points played: 37 of the truth's 262 player-point credits came from under 10 s on the field after a goal, with no play (a
  player subbed off 3 s after a goal got the next point). With swaps said just after a goal made at the goal, 1 of 228 does.
- From the extractor's events (`timeout=6`), wherever both know a player's state, they agree for 98.5% of player-seconds, but the
  extractor's stream knows it for only 54% (truth: 87%). Whisper's mishearings split players ("Sarayan", "Sorayan" and "Ryan" are
  Serayan), and white's line is known for 3 s. With those mishearings resolved too (as team-file mondegreens would), the states
  are known for 78% and agree for 99.6% (99.9% before swaps were moved to goals: the extractor misses goals, so it moves fewer);
  playing time is off by a median of 5 s (white) and 4 s (dark); white's line is known for 503 s (truth 516), dark's for 280 s
  (truth 650: its first substitutions have no team). Plus-minus differs for most players, because the extractor finds 14 of the
  19 goals (goals said as "Glasses for a score" with no throw) and gives one to the wrong team.
- Recomputing takes 10 ms for this game (best of 15). The bundled game, which has no substitutions, takes 7 ms: the three new
  tables are empty, and empty tables now come from a cache.

## Limitations

- Events are taken in stream order; a merged stream must be sorted by time.
- On-field tracking trusts that substitutions are said; it assumes no unsaid off-and-on between two things said that agree. A
  throw's team follows possession, so a throw alone never adds a player to a team.
- A line-up said again later does not take the others off: with more than five then on, the line is unknown.
- A turnover is charged to the thrower and also counted as a drop-or-miss for the receiver; the stream does not say whose fault
  it was. Stalls, fouls and callahans are not modelled.
- Possessions are split by throws only: a D logged after a throw marked complete does not end the possession.
- Without `teams`, `"dark"` and `"black"` are two teams (and, with three labels, an empty team can't be inferred as "the other
  team").
- `o_team` is what the events say; a `suspect` point is flagged, not corrected.
- `elapsed` counts from the game's start only when the stream carries its `Game`; a stream loaded from JSON counts from its first
  event (so the CLI's first point is 4.2 s shorter than the API's on the ground truth game).
