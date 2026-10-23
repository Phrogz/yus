"""Live stats dashboard for one game: a Dash app that polls a game session's snapshot.

    app = create_dashboard(session.snapshot, session.describe)   # serve app.server (WSGI) at, or mounted under, /dashboard/
    run_dashboard(session)                                       # or view it locally: http://127.0.0.1:8050/dashboard/

A dcc.Interval polls `get_snapshot()`. A browser that already shows a snapshot's version gets nothing (PreventUpdate); a new
version whose stats are unchanged (e.g. only a commentator's pending text changed) gets only the scoreboard. Each snapshot is
rendered once per server, however many browsers watch. See docs/dashboard.md.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import math
import threading
import uuid
from collections.abc import Callable
from typing import Any

import dash
import pandas as pd
from dash import Input, Output, State, dash_table, dcc, html
from dash.exceptions import PreventUpdate
from werkzeug.serving import make_server

import yus
from yus.processing.stats import GameStats
from yus.processing.stats.compute import SCORE_PREFIX
from yus.session import GameSession, GameSnapshot
from yus.sports import ultimate

RECENT_EVENTS = 40  # events listed, newest first

# Colors: a validated categorical palette (teams take slots 1 and 2), its ink and surfaces, and a one-hue sequential ramp.
SURFACE, PLANE, INK, INK_2, MUTED, GRID, AXIS = "#fcfcfb", "#f4f4f1", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
TEAM_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
OUTCOME_COLORS = {"completed": "#1baf7a", "goal": "#6250d6", "turnover": "#e34948"}  # stacked in this order
POSSESSION_COLORS = {"goal": "#6250d6", "turnover": "#e34948", "in play": AXIS, "unknown": GRID}
HEAT = [[0.0, "#cde2fb"], [0.5, "#3987e5"], [1.0, "#0d366b"]]
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# Outputs of the refresh callback: (component id, property). LIGHT ones change with every version, HEAVY ones with the stats.
LIGHT = [("scoreboard", "children"), ("commentators", "children")]
HEAVY = [
    ("score-timeline", "figure"),
    ("flow", "figure"),
    ("events", "children"),
    ("unresolved", "children"),
    ("team-box", "children"),
    ("player-box", "data"),
    ("throw-types", "children"),
    ("directions", "children"),
    ("connections", "children"),
]
DESCRIBE_HEAVY = [("roster", "data"), ("describe-name", "options")]

PLAYER_COLUMNS = {
    "team": "Team",
    "player": "Player",
    "goals": "G",
    "assists": "A",
    "hockey_assists": "HA",
    "ds": "D",
    "throws": "Thr",
    "completions": "Cmp",
    "completion_pct": "Cmp %",
    "turnovers": "TO",
    "targets": "Tgt",
    "catches": "Ctch",
    "drops_or_misses": "Drop",
    "interceptions": "Int",
    "hucks": "Huck",
    "huck_completions": "Huck cmp",
}
PLAYER_KEY = (
    "G goals · A assists · HA hockey assists · D blocks · Thr throws · Cmp completions · TO turnovers · Tgt targets · Ctch catches · Drop drops or misses · Int interceptions"
)


def create_dashboard(
    get_snapshot: Callable[[], GameSnapshot],
    describe: Callable[..., object] | None = None,
    requests_pathname_prefix: str = "/dashboard/",
    refresh_ms: int = 1000,
) -> dash.Dash:
    """A Dash app showing the game that `get_snapshot()` returns, polled every `refresh_ms` milliseconds.

    `describe(team, descriptions, player=None, label=None)` (e.g. `GameSession.describe`), when given, adds a form that assigns
    an unresolved name to a roster player or to a label for someone not identified yet; a ValueError it raises is shown.
    The app's Flask server (`app.server`) answers under `requests_pathname_prefix` whether it is mounted there (Starlette
    Mount, DispatcherMiddleware) or serves the whole site."""
    prefix = "/" + requests_pathname_prefix.strip("/") + "/" if requests_pathname_prefix.strip("/") else "/"
    app = dash.Dash(
        __name__,
        requests_pathname_prefix=prefix,
        routes_pathname_prefix="/",
        title="YUS live stats",
        update_title=None,
        meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
    )
    app.index_string = _INDEX
    app.server.wsgi_app = _StripPrefix(app.server.wsgi_app, prefix)
    app.layout = _layout(refresh_ms, describe is not None)
    renderer = _Renderer(describe is not None)
    heavy = HEAVY + (DESCRIBE_HEAVY if describe is not None else [])

    outputs = [Output(id, prop) for id, prop in LIGHT + heavy] + [Output("seen", "data")]
    inputs = [Input("tick", "n_intervals")] + ([Input("describe-status", "children")] if describe is not None else [])

    @app.callback(outputs, inputs, State("seen", "data"))
    def refresh(*args: Any) -> list[Any]:
        seen = args[-1] or {}
        view = renderer.view(get_snapshot())
        if seen.get("key") == view.key:
            raise PreventUpdate
        stale = seen.get("data") != view.data
        return [view.light[id] for id, _ in LIGHT] + [view.heavy[id] if stale else dash.no_update for id, _ in heavy] + [{"key": view.key, "data": view.data}]

    if describe is not None:

        @app.callback(Output("describe-player", "options"), Input("describe-name", "value"), Input("roster", "data"))
        def player_options(choice: str | None, roster: dict[str, Any] | None) -> list[dict[str, str]]:
            if not choice or not roster:
                return []
            team = json.loads(choice)[0]
            candidates, players = roster.get(team, {}).get("candidates", []), roster.get(team, {}).get("players", [])
            return [{"label": f"{player} (not named yet)", "value": player} for player in candidates] + [
                {"label": player, "value": player} for player in players if player not in candidates
            ]

        @app.callback(
            Output("describe-status", "children"),
            Output("describe-name", "value"),
            Output("describe-player", "value"),
            Output("describe-label", "value"),
            Input("describe-submit", "n_clicks"),
            State("describe-name", "value"),
            State("describe-player", "value"),
            State("describe-label", "value"),
            prevent_initial_call=True,
        )
        def submit(_clicks: int | None, choice: str | None, player: str | None, label: str | None) -> tuple[Any, ...]:
            keep = (dash.no_update,) * 3
            if not choice:
                return ("Pick a name first.", *keep)
            team, name = json.loads(choice)
            label = (label or "").strip() or None
            if not player and not label:
                return ("Pick a player, or type a label for someone nobody has identified yet.", *keep)
            try:
                describe(team, [name], player=player or None, label=None if player else label)
            except ValueError as error:
                return (f"Not recorded: {error}", *keep)
            return (f"Recorded: {name} ({team}) is {player or repr(label)}.", None, None, "")

    return app


def run_dashboard(
    snapshot_source: GameSession | GameSnapshot | Callable[[], GameSnapshot],
    host: str = "127.0.0.1",
    port: int = 8050,
    *,
    describe: Callable[..., object] | None = None,
    refresh_ms: int = 1000,
    stop: threading.Event | None = None,
) -> None:
    """Serve the dashboard locally until interrupted (or until `stop` is set): a GameSession (its snapshots, and its `describe`
    for the form), a function returning snapshots, or one fixed snapshot."""
    if isinstance(snapshot_source, GameSession):
        get_snapshot, describe = snapshot_source.snapshot, describe or snapshot_source.describe
    elif isinstance(snapshot_source, GameSnapshot):
        get_snapshot = (lambda snapshot: lambda: snapshot)(snapshot_source)
    else:
        get_snapshot = snapshot_source
    app = create_dashboard(get_snapshot, describe, refresh_ms=refresh_ms)
    server = make_server(host, port, app.server, threaded=True)
    print(f"YUS dashboard: http://{host}:{server.server_port}{app.config.requests_pathname_prefix}", flush=True)
    if stop is None:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        return
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    stop.wait()
    server.shutdown()
    thread.join()


class _StripPrefix:
    """WSGI middleware: a request for PREFIX/path is served as /path (with SCRIPT_NAME PREFIX), so that Dash's routes ("/") answer
    both when the app is mounted under the prefix and when it gets the whole path."""

    def __init__(self, app: Callable[..., Any], prefix: str):
        self.app, self.prefix = app, prefix.rstrip("/")

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Any:
        path = environ.get("PATH_INFO", "")
        if self.prefix and (path == self.prefix or path.startswith(self.prefix + "/")):
            environ = dict(environ, SCRIPT_NAME=environ.get("SCRIPT_NAME", "") + self.prefix, PATH_INFO=path[len(self.prefix) :] or "/")
        return self.app(environ, start_response)


# ---------------------------------------------------------------------------------------------------------------- rendering


@dataclasses.dataclass
class _View:
    key: str  # this snapshot: a browser showing it needs nothing
    data: str  # its stats: a browser showing them needs only the LIGHT outputs
    light: dict[str, Any]
    heavy: dict[str, Any]


class _Renderer:
    """Renders each snapshot once, and its stats-derived outputs once per stats object (shared by snapshots whose events and
    settled count did not change). Keys carry a per-app token, so a browser left open across a server restart re-renders."""

    def __init__(self, describing: bool):
        self.describing = describing
        self._lock = threading.Lock()
        self._token = uuid.uuid4().hex[:8]
        self._serial = 0
        self._snapshot: GameSnapshot | None = None
        self._stats: GameStats | None = None
        self._view: _View | None = None

    def view(self, snapshot: GameSnapshot) -> _View:
        with self._lock:
            last = self._snapshot
            if self._view is not None and last is not None and (snapshot is last or (snapshot.version == last.version and snapshot.game is last.game)):
                return self._view
            stats = snapshot.stats
            self._serial += 1
            if self._view is not None and stats is self._stats:
                data, heavy = self._view.data, self._view.heavy
            else:
                data, heavy = f"{self._token}:{self._serial}", _heavy(snapshot, stats, self.describing)
            self._view = _View(key=f"{self._token}:{self._serial}", data=data, light=_light(snapshot, stats), heavy=heavy)
            self._snapshot, self._stats = snapshot, stats
            return self._view


def _light(snapshot: GameSnapshot, stats: GameStats) -> dict[str, Any]:
    return {"scoreboard": _scoreboard(snapshot, stats), "commentators": _commentators(snapshot)}


def _heavy(snapshot: GameSnapshot, stats: GameStats, describing: bool) -> dict[str, Any]:
    end = _last_elapsed(stats)
    out = {
        "score-timeline": _score_figure(stats, end),
        "flow": _flow_figure(stats, end),
        "events": _events(snapshot, stats),
        "unresolved": _unresolved(snapshot, stats),
        "team-box": _team_box(stats),
        "player-box": _player_rows(stats),
        "throw-types": _per_team(stats, lambda team: _outcome_figure(stats.throw_types, team, "type")),
        "directions": _per_team(stats, lambda team: _outcome_figure(stats.directions, team, "direction")),
        "connections": _per_team(stats, lambda team: _connections_figure(stats, team)),
    }
    if describing:
        out["roster"] = _roster(snapshot, stats)
        out["describe-name"] = [{"label": f"{name} ({team}, {count}×)", "value": json.dumps([team, name])} for team, name, count in snapshot.unresolved]
    return out


# --- scoreboard


def _scoreboard(snapshot: GameSnapshot, stats: GameStats) -> list[Any]:
    teams = [
        html.Div(
            [html.Span(className="swatch", style={"background": _team_color(stats, team)}), html.Span(team, className="team-name"), html.Span(str(goals), className="score")],
            className="team",
        )
        for team, goals in stats.score.items()
    ]
    clock = _game_clock(snapshot, stats)
    notes = ["final" if snapshot.finished else "live"]
    points = stats.points
    if len(points) and pd.isna(points["hold"].iloc[-1]) and points["throws"].iloc[-1]:
        notes.append(f"point {points.index[-1]} in play")
    if provisional := len(snapshot.official.events) - snapshot.settled_count:
        notes.append(f"{provisional} provisional event{'s' * (provisional != 1)}")
    shown = _mmss(clock) if clock is not None and clock >= 0 else "0:00"
    meta = [html.Span(shown, className="clock", title="game clock: time since the game's start, as of the latest commentary")]
    if clock is not None and clock < 0:
        notes.insert(1, "before the start")
    return [html.Div(teams, className="teams-score"), html.Div(meta + [html.Span(" · ".join(notes), className="notes")], className="meta")]


def _commentators(snapshot: GameSnapshot) -> list[Any]:
    if not snapshot.commentators:
        return [html.Span("No commentators yet.", className="muted")]
    items = []
    for c in snapshot.commentators:
        parts: list[Any] = [html.B(c.name), html.Span(f" · {c.groups} phrase{'s' * (c.groups != 1)}", className="muted")]
        if c.pending_text:
            parts += [html.Span(" hearing: ", className="muted"), html.Span(c.pending_text, className="pending")]
        items.append(html.Div(parts, className="commentator"))
    return items


def _game_clock(snapshot: GameSnapshot, stats: GameStats) -> float | None:
    """Seconds from the stats' start to the latest commentary: the clock-reference commentator's last word, or the last event."""
    if stats.start is None:
        return None
    times = [_last_elapsed(stats)] if _has_events(stats) else []
    if snapshot.commentators and (groups := snapshot.transcripts.get(snapshot.commentators[0].name)):
        words = [word for group in groups[-1:] for word in group.words]
        if words:
            heard = _naive(words[-1].start + words[-1].duration, snapshot)
            times.append((heard - stats.start).total_seconds())
    return max(times) if times else None


def _naive(when: dt.datetime, snapshot: GameSnapshot) -> dt.datetime:
    """A time as the stats count it: naive, in the zone of the first time with a non-UTC offset (as compute_stats does)."""
    if when.utcoffset() is None:
        return when
    candidates = [snapshot.game.when] + [event.when for event in snapshot.official.events] + [when]
    zone = next((t.tzinfo for t in candidates if t.utcoffset() not in (None, dt.timedelta(0))), None)
    return when.astimezone(zone).replace(tzinfo=None)


# --- figures: plain dicts, which plotly.js draws as they are (building plotly.graph_objects figures took 10 times as long)

Figure = dict[str, Any]
AXIS_STYLE = {"gridcolor": GRID, "linecolor": AXIS, "ticks": "", "zeroline": False, "automargin": True, "fixedrange": True}
LEGEND = {"orientation": "h", "y": 1.02, "yanchor": "bottom", "x": 0}


def _figure(data: list[dict[str, Any]], height: int | None = None, xaxis: dict[str, Any] | None = None, yaxis: dict[str, Any] | None = None, **layout: Any) -> Figure:
    style = {
        "paper_bgcolor": SURFACE,
        "plot_bgcolor": SURFACE,
        "font": {"family": FONT, "size": 12, "color": INK_2},
        "margin": {"l": 8, "r": 8, "t": 8, "b": 8},
        "hoverlabel": {"bgcolor": "white", "font": {"size": 12, "color": INK}},
        "uirevision": "keep",  # keep legend clicks across updates
        "xaxis": AXIS_STYLE | (xaxis or {}),
        "yaxis": AXIS_STYLE | (yaxis or {}),
    }
    return {"data": data, "layout": style | ({"height": height} if height else {}) | layout}


def _score_figure(stats: GameStats, end: float) -> Figure:
    timeline, points = stats.score_timeline, stats.points
    if not len(timeline) and not len(points):
        return _empty_figure("No points yet")
    shapes = []
    for start, stop, hold, scored_by in zip(points["start"], points["end"], points["hold"], points["scored_by"]):
        if not pd.isna(hold):
            span = {"x0": _minutes(start, stats), "x1": _minutes(stop, stats), "fillcolor": GRID if hold else _team_color(stats, scored_by), "opacity": 0.45 if hold else 0.16}
            shapes.append({"type": "rect", "xref": "x", "yref": "paper", "y0": 0, "y1": 1, "line": {"width": 0}, "layer": "below"} | span)
    minutes = [float(m) for m in timeline["elapsed"] / 60]
    last = max(end / 60, minutes[-1] if minutes else 0.0)
    data = []
    for team in stats.teams:
        column, color = SCORE_PREFIX + team, _team_color(stats, team)
        scores = [int(score) for score in timeline[column]] if column in timeline else []
        total = scores[-1] if scores else 0
        line = {"shape": "hv", "width": 2, "color": color}
        data.append({"type": "scatter", "mode": "lines", "x": [0.0] + minutes + [last], "y": [0] + scores + [total], "line": line, "name": f"{team} {total}", "hoverinfo": "skip"})
        goals = timeline[timeline["team"] == team]
        if len(goals):
            marker = {"size": 9, "color": [SURFACE if p else color for p in goals["provisional"]], "line": {"color": color, "width": 2}}
            data.append(
                {
                    "type": "scatter",
                    "mode": "markers",
                    "x": [float(m) for m in goals["elapsed"] / 60],
                    "y": [int(score) for score in goals[column]],
                    "marker": marker,
                    "showlegend": False,
                    "customdata": [_goal_hover(stats, goal, row) for goal, row in goals.iterrows()],
                    "hovertemplate": "%{customdata}<extra></extra>",
                }
            )
    xaxis = {"title": {"text": "minutes"}, "rangemode": "tozero"}
    return _figure(data, shapes=shapes, legend=LEGEND, xaxis=xaxis, yaxis={"rangemode": "tozero", "tickformat": "d", "dtick": _score_dtick(stats)})


def _goal_hover(stats: GameStats, goal: int, row: pd.Series) -> str:
    score = "–".join(str(int(row[SCORE_PREFIX + team])) for team in stats.teams)
    kind = "" if pd.isna(row["hold"]) else (" · hold" if row["hold"] else " · break")
    return f"Goal {goal}: {row['assist'] or '?'} → {row['scorer'] or '?'}<br>{score}{kind} · {_mmss(row['elapsed'])}{' · provisional' if row['provisional'] else ''}"


def _flow_figure(stats: GameStats, end: float) -> Figure:
    possessions = stats.possessions
    possessions = possessions[possessions["team"].notna()]
    if not len(possessions):
        return _empty_figure("No possessions yet")
    data = []
    for outcome, color in POSSESSION_COLORS.items():
        rows = possessions[possessions["outcome"] == outcome]
        if not len(rows):
            continue
        hatch = ["/" if provisional else "" for provisional in rows["provisional"]]
        hover = [
            f"Possession {n} · point {row['point']} · {row['team']}<br>{row['throws']} throws, {row['completions']} completed · {outcome}"
            f"<br>{_mmss(_minutes(row['start'], stats) * 60)}–{_mmss(_minutes(row['end'], stats) * 60)}{' · provisional' if row['provisional'] else ''}"
            for n, row in rows.iterrows()
        ]
        data.append(
            {
                "type": "bar",
                "orientation": "h",
                "name": outcome,
                "y": list(rows["team"]),
                "x": [max(seconds, 2.0) / 60 for seconds in rows["duration_s"]],  # at least 2 s, to stay visible
                "base": [_minutes(start, stats) for start in rows["start"]],
                "marker": {"color": color, "line": {"color": SURFACE, "width": 1}, "pattern": {"shape": hatch, "fgcolor": SURFACE, "fillmode": "overlay"}},
                "customdata": hover,
                "hovertemplate": "%{customdata}<extra></extra>",
            }
        )
    goals = [_minutes(stop, stats) for stop, hold in zip(stats.points["end"], stats.points["hold"]) if not pd.isna(hold)]
    shapes = [{"type": "line", "xref": "x", "yref": "paper", "x0": x, "x1": x, "y0": 0, "y1": 1, "line": {"color": AXIS, "width": 1}} for x in goals]
    yaxis = {"type": "category", "categoryorder": "array", "categoryarray": list(reversed(stats.teams)), "showgrid": False}
    xaxis = {"title": {"text": "minutes"}, "range": [0, max(end / 60, 0.1) * 1.01]}
    return _figure(data, barmode="overlay", bargap=0.35, legend=LEGEND, shapes=shapes, xaxis=xaxis, yaxis=yaxis)


def _outcome_figure(table: pd.DataFrame, team: str, level: str) -> Figure:
    rows = table.xs(team, level="team") if team in table.index.get_level_values("team") else table.iloc[:0]
    rows = rows[rows["throws"] > 0]
    if not len(rows):
        return _empty_figure("No throws yet")
    labels = [str(key).replace("_", " ") for key in rows.index]
    opacity = [0.5 if p else 1.0 for p in rows["provisional"]]
    parts = {"completed": rows["completions"] - rows["goals"], "goal": rows["goals"], "turnover": rows["turnovers"]}
    hover = [
        f"{label}: {r['throws']} throws, {r['completions']} completed ({_pct(r['completion_pct'])}), {r['goals']} goals, {r['turnovers']} turnovers"
        f"{' · provisional' if r['provisional'] else ''}"
        for label, (_, r) in zip(labels, rows.iterrows())
    ]
    data = [
        {
            "type": "bar",
            "orientation": "h",
            "name": name,
            "y": labels,
            "x": [int(value) for value in values],
            "marker": {"color": OUTCOME_COLORS[name], "opacity": opacity, "line": {"color": SURFACE, "width": 1}},
            "customdata": hover,
            "hovertemplate": "%{customdata}<extra></extra>",
        }
        for name, values in parts.items()
    ]
    totals = [f" {r['throws']} · {_pct(r['completion_pct'])}" for _, r in rows.iterrows()]
    data.append({"type": "scatter", "mode": "text", "y": labels, "x": [int(n) for n in rows["throws"]], "text": totals, "textposition": "middle right", "showlegend": False})
    data[-1] |= {"textfont": {"color": INK_2, "size": 11}, "hoverinfo": "skip"}
    xaxis = {"range": [0, float(rows["throws"].max()) * 1.35]}
    yaxis = {"type": "category", "autorange": "reversed", "showgrid": False}
    return _figure(data, height=70 + 26 * len(rows), barmode="stack", bargap=0.3, legend=LEGEND | {"traceorder": "normal"}, xaxis=xaxis, yaxis=yaxis)


def _connections_figure(stats: GameStats, team: str) -> Figure:
    throws = stats.connection_matrix(team, "throws")
    if throws.empty:
        return _empty_figure("No connections yet")
    throwers = list(throws.sum(axis=1).sort_values(ascending=False, kind="stable").index)
    receivers = list(throws.sum(axis=0).sort_values(ascending=False, kind="stable").index)
    throws = throws.reindex(index=throwers, columns=receivers, fill_value=0)
    completions = stats.connection_matrix(team, "completions").reindex(index=throwers, columns=receivers, fill_value=0)
    goals = stats.connection_matrix(team, "goals").reindex(index=throwers, columns=receivers, fill_value=0)
    heatmap = {
        "type": "heatmap",
        "z": [[int(n) if n else None for n in row] for row in throws.to_numpy()],
        "x": receivers,
        "y": throwers,
        "colorscale": HEAT,
        "zmin": 0,
        "showscale": False,
        "xgap": 2,
        "ygap": 2,
        "texttemplate": "%{z}",
        "customdata": [[[int(c), int(g)] for c, g in zip(crow, grow)] for crow, grow in zip(completions.to_numpy(), goals.to_numpy())],
        "hovertemplate": "%{y} → %{x}<br>%{z} throws, %{customdata[0]} completed, %{customdata[1]} goals<extra></extra>",
        "hoverongaps": False,
    }
    xaxis = {"type": "category", "side": "top", "tickangle": -40, "showgrid": False, "title": {"text": "receiver"}}
    yaxis = {"type": "category", "autorange": "reversed", "showgrid": False, "title": {"text": "thrower"}}
    return _figure([heatmap], height=110 + 24 * len(throwers), showlegend=False, xaxis=xaxis, yaxis=yaxis)


def _per_team(stats: GameStats, figure: Callable[[str], Figure]) -> list[Any]:
    graphs = []
    for team in stats.teams:
        fig = figure(team)
        title = html.H3([html.Span(className="swatch", style={"background": _team_color(stats, team)}), team])
        graphs.append(html.Div([title, _graph(fig, fig["layout"].get("height", 160))], className="team-figure"))
    return graphs


def _graph(fig: Figure, height: int, **props: Any) -> dcc.Graph:
    return dcc.Graph(figure=fig, style={"height": f"{height}px"}, responsive=True, config={"displayModeBar": False, "scrollZoom": False}, **props)


def _empty_figure(text: str) -> Figure:
    note = {"text": text, "showarrow": False, "font": {"color": MUTED, "size": 13}, "xref": "paper", "yref": "paper", "x": 0.5, "y": 0.5}
    return _figure([], height=90, showlegend=False, annotations=[note], xaxis={"visible": False}, yaxis={"visible": False})


# --- tables and lists


TEAM_ROWS: list[tuple[str, Callable[[pd.Series], str]]] = [
    ("Goals", lambda r: f"{r['goals']}"),
    ("Holds / O points", lambda r: f"{r['holds']}/{r['o_points']}"),
    ("Breaks / D points", lambda r: f"{r['breaks']}/{r['d_points']}"),
    ("Possessions", lambda r: f"{r['possessions']}"),
    ("Goals per possession", lambda r: "–" if pd.isna(r["goals_per_possession"]) else f"{r['goals_per_possession']:.2f}"),
    ("Throws", lambda r: f"{r['throws']}"),
    ("Completions", lambda r: f"{r['completions']} ({_pct(r['completion_pct'])})"),
    ("Turnovers", lambda r: f"{r['turnovers']}"),
    ("Ds (interceptions)", lambda r: f"{r['ds']} ({r['interceptions']})"),
    ("Hucks completed", lambda r: f"{r['huck_completions']}/{r['hucks']}"),
    ("Off the wall / net", lambda r: f"{r['wall_throws']}/{r['net_throws']}"),
]


def _team_box(stats: GameStats) -> html.Table:
    box = stats.team_box
    teams = [team for team in stats.teams if team in box.index]
    head = html.Tr(
        [html.Th("")]
        + [
            html.Th(
                [html.Span(className="swatch", style={"background": _team_color(stats, team)}), team],
                className="provisional" if box.loc[team, "provisional"] else None,
                title="includes provisional events" if box.loc[team, "provisional"] else None,
            )
            for team in teams
        ]
    )
    flags = {team: "provisional" if box.loc[team, "provisional"] else None for team in teams}
    body = [html.Tr([html.Th(label, scope="row")] + [html.Td(value(box.loc[team]), className=flags[team]) for team in teams]) for label, value in TEAM_ROWS]
    return html.Table([html.Thead(head), html.Tbody(body)], className="box")


def _player_rows(stats: GameStats) -> list[dict[str, Any]]:
    rows = []
    for (team, player), row in stats.player_box.iterrows():
        record: dict[str, Any] = {"team": team, "player": player}
        for column in PLAYER_COLUMNS:
            if column not in record:
                value = row[column]
                record[column] = None if pd.isna(value) else (float(value) if column == "completion_pct" else int(value))
        record["provisional"] = int(bool(row["provisional"]))
        rows.append(record)
    return rows


def _events(snapshot: GameSnapshot, stats: GameStats) -> list[Any]:
    events = snapshot.official.events
    if not events:
        return [html.Li("No events yet.", className="muted")]
    elapsed, teams = {}, {}
    for name in GameStats.RAW_TABLES:
        table = getattr(stats, name)
        elapsed.update(table["elapsed"].items())
        teams.update(table["team"].items())
    scores = {int(row["event"]): "–".join(str(int(row[SCORE_PREFIX + team])) for team in stats.teams) for _, row in stats.score_timeline.iterrows()}
    items = []
    for index in range(len(events) - 1, max(len(events) - RECENT_EVENTS, 0) - 1, -1):
        event, provisional = events[index], index >= snapshot.settled_count
        team = teams.get(index) or getattr(event, "team", None) or ""
        seconds = elapsed.get(index)
        children: list[Any] = [
            html.Span("" if seconds is None or math.isnan(seconds) else _mmss(seconds), className="t"),
            html.Span(className="swatch", style={"background": _team_color(stats, team)}),
            html.Span(_describe_event(event, scores.get(index))),
        ]
        if provisional:
            children.append(html.Span("provisional", className="tag"))
        items.append(html.Li(children, className="event provisional" if provisional else "event", title=f"{team} · event {index + 1}"))
    return items


def _describe_event(event: yus.Event, score: str | None) -> str:
    if isinstance(event, ultimate.Throw):
        words = [event.player or "someone"]
        words += [str(value).replace("_", " ") for value in (event.type, event.direction) if value is not None]
        if event.receiver:
            words += ["to", event.receiver]
        if getattr(event, "hit_wall", False):
            words.append("off the wall")
        if getattr(event, "hit_net", False):
            words.append("off the net")
        text = " ".join(words)
        if event.scored:
            return f"{text} · goal" + (f" ({score})" if score else "")
        return text if event.completed else f"{text} · turnover"
    if isinstance(event, ultimate.Defense):
        return f"{'Interception' if event.intercepted else 'D'} by {event.player or 'someone'}"
    if isinstance(event, ultimate.Substitution):
        return f"{event.player or 'someone'} subs {'on' if event.sub_type == ultimate.SubType.SUB_ON else 'off'}"
    if isinstance(event, ultimate.Infraction):
        return f"Infraction by {event.player or 'someone'}"
    return type(event).__name__


def _unresolved(snapshot: GameSnapshot, stats: GameStats) -> list[Any]:
    unresolved, unmentioned = snapshot.unresolved, snapshot.unmentioned
    if not unresolved:
        return [html.P("Every name is a roster player.", className="muted")]
    blocks = []
    for team in list(dict.fromkeys(stats.teams + [team for team, _, _ in unresolved])):
        names = [(name, count) for t, name, count in unresolved if t == team]
        if not names:
            continue
        candidates = unmentioned.get(team, [])
        blocks.append(
            html.Div(
                [
                    html.H3([html.Span(className="swatch", style={"background": _team_color(stats, team)}), team]),
                    html.Ul([html.Li([html.B(name), html.Span(f" · {count} mention{'s' * (count != 1)}", className="muted")]) for name, count in names], className="names"),
                    html.P(["Not named yet: ", ", ".join(candidates) if candidates else "nobody"], className="candidates"),
                ],
                className="unresolved-team",
            )
        )
    return blocks


def _roster(snapshot: GameSnapshot, stats: GameStats) -> dict[str, Any]:
    unmentioned = snapshot.unmentioned
    roster = {}
    for i, team in enumerate(snapshot.game.teams):
        label = team.names[0] if team.names else f"team {i + 1}"
        roster[label] = {"candidates": unmentioned.get(label, []), "players": list(team.players)}
    return roster


# --- helpers


def _team_color(stats: GameStats, team: str | None) -> str:
    return TEAM_COLORS[stats.teams.index(team)] if team in stats.teams and stats.teams.index(team) < len(TEAM_COLORS) else MUTED


def _has_events(stats: GameStats) -> bool:
    return any(len(getattr(stats, name)) for name in GameStats.RAW_TABLES)


def _last_elapsed(stats: GameStats) -> float:
    values = [getattr(stats, name)["elapsed"].max() for name in GameStats.RAW_TABLES if len(getattr(stats, name))]
    values = [float(v) for v in values if not pd.isna(v)]
    return max(values) if values else 0.0


def _minutes(when: Any, stats: GameStats) -> float:
    if stats.start is None or pd.isna(when):
        return 0.0
    return (pd.Timestamp(when) - pd.Timestamp(stats.start)).total_seconds() / 60


def _mmss(seconds: float) -> str:
    sign, seconds = ("-" if seconds < 0 else ""), abs(int(seconds))
    hours, rest = divmod(seconds, 3600)
    return f"{sign}{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else f"{sign}{rest // 60}:{rest % 60:02d}"


def _pct(value: float) -> str:
    return "–" if pd.isna(value) else f"{value:.1f}".removesuffix(".0") + "%"


def _score_dtick(stats: GameStats) -> int:
    return 1 if max(stats.score.values(), default=0) <= 8 else 2


# ------------------------------------------------------------------------------------------------------------------- layout


def _card(title: str, body: Any, sub: str | None = None, wide: bool = False) -> html.Section:
    head = [html.H2(title)] + ([html.P(sub, className="sub")] if sub else [])
    return html.Section(head + (body if isinstance(body, list) else [body]), className="card wide" if wide else "card")


def _layout(refresh_ms: int, describing: bool) -> html.Div:
    waiting = _empty_figure("Waiting for the game…")
    unresolved: list[Any] = [html.Div(id="unresolved")]
    if describing:
        unresolved += [
            html.Div(
                [
                    dcc.Dropdown(id="describe-name", placeholder="Name to identify", options=[], className="field"),
                    dcc.Dropdown(id="describe-player", placeholder="Roster player", options=[], className="field"),
                    dcc.Input(id="describe-label", type="text", placeholder="…or a label (not identified yet)", className="field text", debounce=False),
                    html.Button("Assign", id="describe-submit", type="button", n_clicks=0),
                    html.Div(id="describe-status", className="status", role="status"),
                ],
                className="describe",
                role="group",
                **{"aria-label": "Identify a name"},
            ),
            dcc.Store(id="roster"),
        ]
    player_table = dash_table.DataTable(
        id="player-box",
        columns=[{"name": label, "id": column, "type": "text" if column in ("team", "player") else "numeric"} for column, label in PLAYER_COLUMNS.items()],
        data=[],
        sort_action="native",
        sort_by=[{"column_id": "goals", "direction": "desc"}],
        style_table={"overflowX": "auto"},
        style_as_list_view=True,
        style_header={"fontWeight": 600, "backgroundColor": SURFACE, "color": INK_2, "borderBottom": f"1px solid {AXIS}"},
        style_cell={"fontFamily": FONT, "fontSize": 13, "padding": "4px 6px", "backgroundColor": SURFACE, "color": INK, "border": "none", "borderBottom": f"1px solid {GRID}"},
        style_cell_conditional=[{"if": {"column_id": c}, "textAlign": "left"} for c in ("team", "player")],
        style_data_conditional=[{"if": {"filter_query": "{provisional} = 1"}, "fontStyle": "italic", "color": INK_2, "backgroundColor": "#f3f2ee"}],
    )
    return html.Div(
        [
            dcc.Interval(id="tick", interval=refresh_ms),
            dcc.Store(id="seen"),
            html.Header([html.Div(id="scoreboard", className="scoreboard"), html.Div(id="commentators", className="commentators")], className="top"),
            html.Main(
                [
                    _card("Score", _graph(waiting, 260, id="score-timeline"), "Running score. Shaded points: holds gray, breaks in the color of the team that broke.", wide=True),
                    _card("Game flow", _graph(waiting, 170, id="flow"), "Each possession, by how it ended; lines mark goals. Hatched: provisional.", wide=True),
                    _card("Teams", html.Div(id="team-box")),
                    _card("Recent events", html.Ol(id="events", className="events"), "Newest first. Italic: provisional, may still change."),
                    _card("Unresolved names", unresolved, "Names that are not roster players yet, and the players nobody has named.", wide=True),
                    _card("Players", [player_table, html.P(PLAYER_KEY, className="sub key")], "Tap a column to sort. Italic: includes provisional events.", wide=True),
                    _card("Throw types", html.Div(id="throw-types", className="per-team"), "Throws by type and outcome: count · completion rate.", wide=True),
                    _card("Directions", html.Div(id="directions", className="per-team"), "Throws by direction and outcome.", wide=True),
                    _card("Connections", html.Div(id="connections", className="per-team"), "Throws from each thrower (rows) to each receiver (columns).", wide=True),
                ],
                className="grid",
            ),
        ],
        className="page",
    )


_CSS = """
:root { color-scheme: light; --surface: %(SURFACE)s; --plane: %(PLANE)s; --ink: %(INK)s; --ink2: %(INK_2)s; --muted: %(MUTED)s;
  --grid: %(GRID)s; --axis: %(AXIS)s; --border: rgba(11,11,11,.10); }
* { box-sizing: border-box; }
body { margin: 0; background: var(--plane); color: var(--ink); font: 15px/1.4 %(FONT)s; }
.page { max-width: 1280px; margin: 0 auto; padding: 12px 16px 32px; }
.top { position: sticky; top: 0; z-index: 10; background: var(--plane); padding: 4px 0 8px; }
.scoreboard { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 10px 14px; }
.teams-score { display: flex; flex-wrap: wrap; justify-content: center; gap: 4px 28px; }
.team { display: flex; align-items: center; gap: 10px; }
.team-name { font-size: 18px; font-weight: 600; }
.score { font-size: 44px; font-weight: 700; line-height: 1; }
.meta { display: flex; justify-content: center; flex-wrap: wrap; gap: 4px 12px; color: var(--ink2); margin-top: 4px; }
.clock { font-variant-numeric: tabular-nums; font-weight: 600; color: var(--ink); }
.swatch { display: inline-block; width: 10px; height: 10px; border-radius: 3px; flex: none; margin-right: 6px; }
.commentators { display: flex; flex-wrap: wrap; gap: 2px 16px; font-size: 13px; margin-top: 6px; padding: 0 4px; }
.pending { font-style: italic; color: var(--ink2); }
.muted { color: var(--muted); }
.grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(min(100%%, 420px), 1fr)); }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; min-width: 0; }
.card.wide { grid-column: 1 / -1; }
.card h2 { font-size: 15px; font-weight: 600; margin: 0 0 2px; }
.card h3 { font-size: 14px; font-weight: 600; margin: 4px 0; display: flex; align-items: center; }
.sub { font-size: 12px; color: var(--muted); margin: 0 0 8px; }
.sub.key { margin: 8px 0 0; }
.per-team { display: grid; gap: 12px 20px; grid-template-columns: repeat(auto-fit, minmax(min(100%%, 360px), 1fr)); }
.team-figure { min-width: 0; }
.events { list-style: none; margin: 0; padding: 0; max-height: 440px; overflow-y: auto; }
.event { display: grid; grid-template-columns: 3.4em 16px 1fr auto; align-items: baseline; gap: 4px; padding: 5px 2px; border-bottom: 1px solid var(--grid); font-size: 14px; }
.event .t { font-variant-numeric: tabular-nums; color: var(--muted); font-size: 12px; }
.event.provisional { font-style: italic; color: var(--ink2);
  background: repeating-linear-gradient(135deg, transparent 0 6px, rgba(137,135,129,.09) 6px 12px); }
.tag { font-size: 11px; font-style: normal; border: 1px dashed var(--muted); border-radius: 4px; padding: 0 4px; color: var(--ink2); }
table.box { border-collapse: collapse; width: 100%%; font-variant-numeric: tabular-nums; font-size: 14px; }
table.box th, table.box td { padding: 5px 6px; border-bottom: 1px solid var(--grid); text-align: right; }
table.box th[scope=row] { text-align: left; font-weight: 400; color: var(--ink2); }
table.box thead th { font-weight: 600; white-space: nowrap; }
table.box .provisional { font-style: italic; }
.unresolved-team { margin-bottom: 8px; }
.names { margin: 0; padding-left: 18px; columns: 2 10em; }
.candidates { font-size: 13px; color: var(--ink2); margin: 4px 0 0; }
.describe { display: grid; gap: 8px; grid-template-columns: repeat(auto-fit, minmax(min(100%%, 180px), 1fr)); margin-top: 10px;
  padding-top: 10px; border-top: 1px solid var(--grid); }
.describe .text { font: inherit; padding: 7px 8px; border: 1px solid #ccc; border-radius: 4px; min-height: 36px; }
.describe button { font: inherit; font-weight: 600; padding: 7px 14px; border-radius: 6px; border: 1px solid #2a78d6; background: #2a78d6; color: white; cursor: pointer; }
.describe .status { grid-column: 1 / -1; font-size: 13px; color: var(--ink2); min-height: 1em; }
@media (max-width: 600px) {
  .page { padding: 8px 16px 24px; }
  .teams-score { gap: 4px 16px; }
  .score { font-size: 32px; }
  .team-name { font-size: 14px; }
  .top { position: static; }
}
""" % {"SURFACE": SURFACE, "PLANE": PLANE, "INK": INK, "INK_2": INK_2, "MUTED": MUTED, "GRID": GRID, "AXIS": AXIS, "FONT": FONT}

_INDEX = (
    "<!DOCTYPE html>\n<html lang='en'>\n<head>\n{%metas%}\n<title>{%title%}</title>\n{%favicon%}\n{%css%}\n<style>"
    + _CSS
    + "</style>\n</head>\n<body>\n{%app_entry%}\n<footer>\n{%config%}\n{%scripts%}\n{%renderer%}\n</footer>\n</body>\n</html>"
)
