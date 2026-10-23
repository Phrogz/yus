# Live Stats Dashboard

`yus.web.dashboard` is a [Dash](https://dash.plotly.com/) app that shows one game's stats as they happen. It polls a
`GameSession`'s snapshots (see [session.md](session.md)) and draws everything from one snapshot at a time, so every panel
shows the same version of the game. It is readable on a phone.

## Where it fits

```text
GameSession.snapshot() ──GameSnapshot──> dashboard (polls every second) ──> browsers
                       <──describe()──── "Unresolved names" form
```

`yus-serve` mounts it at `/dashboard/` (see `yus/web/server.py`); `run_dashboard()` serves it alone for local viewing.

## What it shows

| Panel | Content | Source |
|---|---|---|
| Scoreboard | team names and scores, game clock, live/final, point in play, provisional count; each commentator's phrase count and pending text | `score`, `settled_count`, `commentators` |
| Score | running score as step lines, goals as dots (hover: thrower → scorer, score, hold/break); each point shaded: holds gray, breaks in the breaking team's color | `score_timeline`, `points` |
| Game flow | every possession as a bar on its team's row, colored by how it ended; lines at goals | `possessions`, `points` |
| Teams | goals, holds/O points, breaks/D points, possessions, goals per possession, throws, completions, turnovers, Ds, hucks, wall/net throws | `team_box` |
| Recent events | the newest 40 official events, newest first, with game time and running score after goals | `official` |
| Unresolved names | names that are not roster players yet, with mention counts, and per team the players nobody has named (likely identities) | `unresolved`, `unmentioned` |
| Players | box score, sortable by any column | `player_box` |
| Throw types, Directions | per team: throws by type (or direction), stacked completed / goal / turnover, labelled with count and completion rate | `throw_types`, `directions` |
| Connections | per team: thrower × receiver heatmap of throws (hover: completions, goals) | `connections` |

**Provisional events** (from `settled_count` on) may still change. They are shown in italics with a hatched background
and a "provisional" tag in Recent events. Rows, columns, bars and dots they count toward are italic, faded, hatched or hollow.

The **game clock** is the time from the stats' start to the latest commentary: the last word heard from the first
commentator (the clock reference), or the last event if that is later. The start is the game's `when`, else the first event.

## API

```python
from yus.web.dashboard import create_dashboard, run_dashboard

app = create_dashboard(session.snapshot, session.describe)     # dash.Dash; app.server is its Flask (WSGI) app
run_dashboard(session, "127.0.0.1", 8050)                      # http://127.0.0.1:8050/dashboard/ until Ctrl-C
```

`create_dashboard(get_snapshot, describe=None, requests_pathname_prefix="/dashboard/", refresh_ms=1000) -> dash.Dash`

- `get_snapshot()` returns a `GameSnapshot`. It is called on every poll, so it must be cheap (`GameSession.snapshot` is).
- `describe(team, descriptions, player=None, label=None)`, e.g. `GameSession.describe`, adds a form under Unresolved names. Pick a
  name, then a roster player (players nobody has named are listed first) or type a label for someone not identified yet. The
  form calls `describe(team, [name], player=...)` or `describe(team, [name], label=...)` and shows the `ValueError` it raises,
  if any. Without `describe`, the panel only lists names and candidates.
- `requests_pathname_prefix`: the URL the browser uses. The app answers there whether it is mounted under the prefix (Starlette
  `Mount("/dashboard", WSGIMiddleware(app.server))`, werkzeug `DispatcherMiddleware`) or given the whole path.
- `refresh_ms`: how often each browser polls.

`run_dashboard(snapshot_source, host="127.0.0.1", port=8050, *, describe=None, refresh_ms=1000, stop=None)` serves a
`GameSession` (with its `describe`), a function returning snapshots, or one fixed snapshot, until interrupted or until the
`stop` event is set. It prints the URL.

### Updates

One callback renders every panel from one snapshot.

- A browser that already shows a snapshot's version gets nothing back (`PreventUpdate`, HTTP 204).
- A new version with the same stats object (only pending text changed, say) gets only the scoreboard and commentators.
  `GameSession` shares stats between snapshots whose events and settled count are unchanged.
- Each snapshot is rendered once per server, however many browsers watch, and its stats are read once.
- Figures are plain dicts (plotly.js draws them as they are); the tests run each one through `plotly.graph_objects.Figure` to
  validate it.

## Measured

On an Apple Silicon Mac (Python 3.13, Dash 2.18), refreshing one browser after every group of a replayed game:

| | hand-made transcript | Whisper transcript |
|---|---|---|
| groups / refreshes with new stats | 246 / 197 | 201 / 166 |
| refresh with new stats, median (max) | 19 ms (55) | 19 ms (54) |
| of which dashboard rendering, median (max) | 10 ms (43) | 10 ms (43) |
| response, median (max) | 70 KB (88) | 71 KB (96) |

- The rest of a refresh with new stats is mostly `compute_stats` (7–10 ms). Rendering took 53 ms when the figures were
  `plotly.graph_objects`, and responses were 130–157 KB with plotly's default template in every figure.
- A new version with the same stats: 1 ms, 2.2 KB. An unchanged version: 0.2 ms, no body. A second browser joining at the end
  of the game: 2 ms (the cached render), 87 KB.
- The tests check the ground-truth game (14–9, last 5 events provisional) against its numbers:
  - Score: 23 shaded points (12 holds, white broke 8 times and black 3).
  - Game flow: 44 possessions (23 goals, 21 turnovers), one hatched.
  - Teams: holds 6/10 and 6/14, breaks 8/14 and 3/10.
  - Throw types: white's 52 flicks are 38 completed, 8 goals and 6 turnovers.
  - Connections: glasses → Tristan Weber, 7 throws.
- Headless Chrome screenshots at 1280 px and in a 390 px frame: no sideways page scrolling. The player table scrolls sideways
  inside its card.

## Limitations

- **Clock.** The clock moves only when a new snapshot arrives (new words, events or pending text), not every second. It counts
  from the game's `when`, which is the pull only if the session's `Game` says so.
- **Bandwidth.** Every stats change sends about 70–90 KB to each browser, whole figures and tables (no partial updates). Live,
  that is about one phrase every 4 s, so roughly 1 MB a minute per viewer.
- **Theme.** Light only: figure colors are fixed when they are built, so they can't follow the system's dark mode.
- **Describing.** Descriptions are shared, for every commentator. A commentator's own heard identification can only be
  corrected through `GameSession.describe(..., commentator=...)`. The form describes one name at a time.
- **Recent events** lists only the newest 40 events.
- **Testing.** Tested with Flask's test client, a Starlette mount and headless Chrome, not on a real phone.
- **Teams.** Teams past the eighth are gray.
