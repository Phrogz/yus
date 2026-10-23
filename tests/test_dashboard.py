import json
import pathlib
import socket
import threading
import time
import urllib.request
from collections.abc import Iterator
from typing import Any

import dash
import pytest
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.test import Client
from werkzeug.wrappers import Response

import yus
from tests.data.gruindoor_20250114T2030 import build_game
from yus.processing.event_unification import GameDescriptions, PlayerResolver
from yus.session import GameSession, GameSnapshot, replay
from yus.web import dashboard
from yus.web.dashboard import create_dashboard, run_dashboard

DATA = pathlib.Path(__file__).parent / "data"
TRANSCRIPT = DATA / "gruindoor_20250114T2030-transcript.json"
DESCRIPTIONS = DATA / "gruindoor_20250114T2030-descriptions.json"
WHITE, BLACK = "Dump & Drizzle", "Category 5"
PROVISIONAL = 5  # the ground truth snapshot's last events still provisional


@pytest.fixture(scope="module")
def game() -> yus.Game:
    return build_game()


@pytest.fixture(scope="module")
def descriptions() -> GameDescriptions:
    return GameDescriptions.model_validate_json(DESCRIPTIONS.read_text())


@pytest.fixture(scope="module")
def transcript() -> yus.Transcript:
    return yus.Transcript.model_validate_json(TRANSCRIPT.read_text())


def truth_snapshot(game: yus.Game, descriptions: GameDescriptions, provisional: int = PROVISIONAL, version: int = 1) -> GameSnapshot:
    """The ground-truth game (the hand-made official stream, 14-9) as a session's snapshot, its last `provisional` events provisional."""
    from yus.session import _Views  # what a session computes on first read: stats, unresolved and unmentioned names

    official = game.official_stream
    assert official is not None
    settled = len(official.events) - provisional
    views = _Views(official, game.teams, settled, PlayerResolver(game.teams, descriptions))
    return GameSnapshot(
        version=version,
        game=game,
        commentators=[],
        transcripts={},
        raw={},
        resolved={},
        official=official,
        settled_count=settled,
        associations=[],
        descriptions=descriptions,
        merge=None,
        finished=False,
        views=views,
    )


def update(client: Client, app: dash.Dash, output: str, values: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """POST the callback whose outputs include `output` ("seen.data") as a browser would, with `values` ("id.prop" -> value) for its
    inputs and state. Returns {id: {prop: value}} for the outputs sent, or None when the callback sent nothing (PreventUpdate)."""
    values = values or {}
    key = next(key for key in app.callback_map if output in key)
    spec = app.callback_map[key]
    outputs = [dict(zip(("id", "property"), part.rsplit(".", 1))) for part in key.strip(".").split("...")]

    def fill(items: list[dict[str, str]]) -> list[dict[str, Any]]:
        return [dict(item, value=values.get(f"{item['id']}.{item['property']}")) for item in items]

    payload = {
        "output": key,
        "outputs": outputs if key.startswith("..") else outputs[0],
        "inputs": fill(spec["inputs"]),
        "state": fill(spec["state"]),
        "changedPropIds": [f"{spec['inputs'][0]['id']}.{spec['inputs'][0]['property']}"],
    }
    response = client.post("/dashboard/_dash-update-component", json=payload)
    if response.status_code == 204:
        return None
    assert response.status_code == 200, response.text
    return response.get_json()["response"]


def refresh(client: Client, app: dash.Dash, seen: dict[str, Any] | None = None) -> dict[str, Any] | None:
    return update(client, app, "seen.data", {"seen.data": seen})


def submit(client: Client, app: dash.Dash, **values: Any) -> dict[str, Any] | None:
    """Click the describe form's button with these field values (name, player, label)."""
    return update(client, app, "describe-status.children", {"describe-submit.n_clicks": 1} | {f"describe-{key}.value": value for key, value in values.items()})


def components(node: Any) -> Iterator[dict[str, Any]]:
    """Every component in a serialized Dash tree (as a callback response carries it), depth first."""
    if isinstance(node, list):
        for child in node:
            yield from components(child)
    elif isinstance(node, dict) and "props" in node:
        yield node
        yield from components(node["props"].get("children"))


def text(node: Any) -> str:
    """The text of a serialized Dash tree."""
    if isinstance(node, (str, int, float)):
        return str(node)
    if isinstance(node, list):
        return "".join(text(child) for child in node)
    if isinstance(node, dict) and "props" in node:
        return text(node["props"].get("children"))
    return ""


def layout_ids(app: dash.Dash) -> set[str]:
    found, stack = set(), [app.layout]
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, dash.development.base_component.Component):
            if getattr(node, "id", None):
                found.add(node.id)
            stack.append(getattr(node, "children", None))
    return found


def traces(figure: dict[str, Any], name: str | None = None) -> list[dict[str, Any]]:
    return [trace for trace in figure["data"] if name is None or str(trace.get("name", "")).startswith(name)]


# --- layout and serving


def test_layout_has_every_panel(game, descriptions):
    snapshot = truth_snapshot(game, descriptions)
    ids = layout_ids(create_dashboard(lambda: snapshot, lambda *args, **kwargs: None))
    panels = {"scoreboard", "commentators", "score-timeline", "flow", "events", "unresolved", "team-box", "player-box", "throw-types", "directions", "connections"}
    assert panels | {"tick", "seen", "describe-name", "describe-player", "describe-label", "describe-submit", "describe-status"} <= ids
    without = layout_ids(create_dashboard(lambda: snapshot))
    assert panels <= without and not {id for id in without if id.startswith("describe")}


def test_serves_under_its_prefix_mounted_or_not(game, descriptions):
    snapshot = truth_snapshot(game, descriptions)
    app = create_dashboard(lambda: snapshot, refresh_ms=500)
    client = app.server.test_client()
    page = client.get("/dashboard/")
    assert page.status_code == 200
    config = json.loads(page.text.split('<script id="_dash-config" type="application/json">')[1].split("</script>")[0])
    assert config["url_base_pathname"] is None and config["requests_pathname_prefix"] == "/dashboard/"
    assert client.get("/dashboard/_dash-layout").status_code == 200
    assert '"interval": 500' in client.get("/dashboard/_dash-layout").text.replace(":500", ": 500")
    mounted = Client(DispatcherMiddleware(Response("not found", status=404), {"/dashboard": app.server}))  # like Starlette's Mount
    assert mounted.get("/dashboard/").status_code == 200
    assert mounted.get("/dashboard/_dash-dependencies").status_code == 200
    assert mounted.get("/elsewhere").status_code == 404


# --- what the callbacks show


@pytest.fixture(scope="module")
def truth(game, descriptions) -> dict[str, Any]:
    snapshot = truth_snapshot(game, descriptions)
    app = create_dashboard(lambda: snapshot, lambda *args, **kwargs: None)
    response = refresh(app.server.test_client(), app)
    assert response is not None
    return {"snapshot": snapshot, "response": response}


def test_scoreboard_shows_score_clock_and_state(truth):
    board = text(truth["response"]["scoreboard"]["children"])
    assert "Dump & Drizzle14" in board and "Category 59" in board
    assert "15:13" in board  # the last event, 913.7 s after the pull
    assert "live · point 24 in play · 5 provisional events" in board
    assert "No commentators yet." in text(truth["response"]["commentators"]["children"])


def test_score_timeline_steps_to_14_9_with_holds_and_breaks_shaded(truth):
    figure = truth["response"]["score-timeline"]["figure"]
    (white,), (black,) = traces(figure, WHITE), traces(figure, BLACK)
    assert white["line"]["shape"] == "hv" and white["y"][-1] == 14 and black["y"][-1] == 9
    assert white["name"] == f"{WHITE} 14"
    shapes = figure["layout"]["shapes"]
    assert len(shapes) == 23  # every decided point; the 24th is in play
    colors = [shape["fillcolor"] for shape in shapes]
    assert colors.count(dashboard.GRID) == 12  # holds
    assert colors.count(dashboard.TEAM_COLORS[0]) == 8 and colors.count(dashboard.TEAM_COLORS[1]) == 3  # white broke 8 times, black 3
    goals = [trace for trace in figure["data"] if trace.get("mode") == "markers"]
    assert sum(len(trace["x"]) for trace in goals) == 23
    assert "Goal 23: Adam Federbusch → yellow sleeve<br>14–9 · hold · 14:25" in goals[1]["customdata"]


def test_game_flow_shows_every_possession(truth):
    figure = truth["response"]["flow"]["figure"]
    by_outcome = {trace["name"]: trace for trace in figure["data"]}
    assert {name: len(trace["x"]) for name, trace in by_outcome.items()} == {"goal": 23, "turnover": 21}
    assert len(figure["layout"]["shapes"]) == 23  # a line at each goal
    hatched = by_outcome["turnover"]["marker"]["pattern"]
    assert hatched["shape"].count("/") == 1 and hatched["fillmode"] == "overlay"  # possession 44 holds the provisional events
    assert set(by_outcome["goal"]["y"]) == {WHITE, BLACK}


def test_team_box_holds_and_breaks(truth):
    table = truth["response"]["team-box"]["children"]
    rows = {text(row["props"]["children"][0]): [text(cell) for cell in row["props"]["children"][1:]] for row in components(table) if row["type"] == "Tr"}
    assert rows[""] == [WHITE, BLACK]
    assert rows["Goals"] == ["14", "9"]
    assert rows["Holds / O points"] == ["6/10", "6/14"]
    assert rows["Breaks / D points"] == ["8/14", "3/10"]
    assert rows["Completions"] == ["99 (92.5%)", "71 (84.5%)"]
    provisional = [cell["props"].get("className") for cell in components(table) if cell["type"] == "Th" and text(cell) in (WHITE, BLACK)]
    assert provisional == [None, "provisional"]  # the provisional events are black's


def test_player_box_rows(truth):
    rows = {(row["team"], row["player"]): row for row in truth["response"]["player-box"]["data"]}
    tristan = rows[(WHITE, "Tristan Weber")]
    assert (tristan["throws"], tristan["completions"], tristan["assists"], tristan["goals"], tristan["completion_pct"]) == (20, 20, 2, 1, 100.0)
    assert rows[(WHITE, "Ben Kishter")]["goals"] == 2
    assert sum(row["assists"] for row in rows.values() if row["team"] == WHITE) == 14  # every white goal had a named thrower
    assert {key for key, row in rows.items() if row["provisional"]} == {(BLACK, "Adam Federbusch"), (BLACK, "George Abuhamad"), (BLACK, "yellow sleeve")}


def test_throw_types_directions_and_connections(truth):
    response = truth["response"]
    white_types = next(component for component in components(response["throw-types"]["children"]) if component["type"] == "Graph")["props"]["figure"]
    bars = {trace["name"]: dict(zip(trace["y"], trace["x"])) for trace in white_types["data"] if trace["type"] == "bar"}
    assert (bars["completed"]["flick"], bars["goal"]["flick"], bars["turnover"]["flick"]) == (38, 8, 6)  # 52 flicks, 46 completed
    labels = next(trace for trace in white_types["data"] if trace.get("mode") == "text")
    assert " 52 · 88.5%" in labels["text"]

    graphs = [c["props"]["figure"] for c in components(response["directions"]["children"]) if c["type"] == "Graph"]
    huck = {trace["name"]: dict(zip(trace["y"], trace["x"])) for trace in graphs[0]["data"] if trace["type"] == "bar"}
    assert (huck["completed"]["huck"], huck["goal"]["huck"], huck["turnover"]["huck"]) == (0, 6, 3)
    assert len(graphs) == 2

    heat = next(c for c in components(response["connections"]["children"]) if c["type"] == "Graph")["props"]["figure"]["data"][0]
    assert heat["type"] == "heatmap"
    assert heat["z"][heat["y"].index("glasses")][heat["x"].index("Tristan Weber")] == 7
    assert heat["y"][:2] == ["Tristan Weber", "glasses"]  # the busiest throwers (20 and 18 throws) first


def test_recent_events_newest_first_with_provisional_ones_marked(truth):
    items = [c for c in components(truth["response"]["events"]["children"]) if c["type"] == "Li"]
    assert len(items) == dashboard.RECENT_EVENTS
    classes = [item["props"]["className"] for item in items]
    assert classes[:PROVISIONAL] == ["event provisional"] * PROVISIONAL and set(classes[PROVISIONAL:]) == {"event"}
    assert all(text(item).endswith("provisional") for item in items[:PROVISIONAL])
    assert text(items[0]) == "15:13Adam Federbusch flick huck · turnoverprovisional"
    assert next(text(item) for item in items if "goal" in text(item)) == "14:25Adam Federbusch backhand to yellow sleeve · goal (14–9)"


def test_unresolved_names_with_candidates(truth):
    snapshot, response = truth["snapshot"], truth["response"]
    panel = text(response["unresolved"]["children"])
    for team, name, count in snapshot.unresolved:
        assert f"{name} · {count} mentions" in panel
    assert "glasses · 32 mentions" in panel
    assert "Not named yet: Alexis Rosas, Ari Weissman, Drew Rasmussen" in panel
    options = response["describe-name"]["options"]
    assert options[0] == {"label": f"glasses ({WHITE}, 32×)", "value": json.dumps([WHITE, "glasses"])}
    assert response["roster"]["data"][WHITE]["candidates"] == ["Alexis Rosas", "Ari Weissman", "Drew Rasmussen"]


def test_nothing_provisional_once_settled(game, descriptions):
    snapshot = truth_snapshot(game, descriptions, provisional=0)
    app = create_dashboard(lambda: snapshot)
    response = refresh(app.server.test_client(), app)
    assert "provisional" not in json.dumps(response["events"]) and "provisional" not in text(response["scoreboard"]["children"])
    assert not any(row["provisional"] for row in response["player-box"]["data"])


# --- updates


def test_unchanged_version_sends_nothing_and_renders_once(game, descriptions, monkeypatch):
    snapshot = truth_snapshot(game, descriptions)
    renders = []
    heavy = dashboard._heavy
    monkeypatch.setattr(dashboard, "_heavy", lambda *args: renders.append(1) or heavy(*args))
    app = create_dashboard(lambda: snapshot)
    first, second = app.server.test_client(), app.server.test_client()  # two browsers
    shown = refresh(first, app)
    assert shown is not None and refresh(second, app) is not None
    assert refresh(first, app, shown["seen"]["data"]) is None  # PreventUpdate: HTTP 204
    assert len(renders) == 1


def test_new_version_with_the_same_stats_sends_only_the_scoreboard(game, descriptions, transcript):
    session = GameSession(game, descriptions)
    replay(session, transcript.model_copy(update={"groups": transcript.groups[:40]}), "Gavin")
    app = create_dashboard(session.snapshot, session.describe)
    client = app.server.test_client()
    shown = refresh(client, app)
    assert shown is not None and "score-timeline" in shown
    seen = shown["seen"]["data"]

    session.set_pending_text("Gavin", "flick to the")
    pending = refresh(client, app, seen)
    assert pending is not None and set(pending) == {"scoreboard", "commentators", "seen"}
    assert "Gavin · 40 phrases hearing: flick to the" in text(pending["commentators"]["children"])
    assert pending["seen"]["data"]["data"] == seen["data"] and pending["seen"]["data"]["key"] != seen["key"]

    session.add_groups("Gavin", transcript.groups[40:60])
    more = refresh(client, app, pending["seen"]["data"])
    assert more is not None and "score-timeline" in more and "player-box" in more
    assert refresh(client, app, more["seen"]["data"]) is None


def test_empty_session(game):
    session = GameSession(game)
    app = create_dashboard(session.snapshot)
    response = refresh(app.server.test_client(), app)
    assert response is not None
    assert "Dump & Drizzle0" in text(response["scoreboard"]["children"]) and "Category 50" in text(response["scoreboard"]["children"])
    assert response["score-timeline"]["figure"]["layout"]["annotations"][0]["text"] == "No points yet"
    assert text(response["events"]["children"]) == "No events yet."
    assert response["player-box"]["data"] == []


def test_clock_uses_the_latest_commentary(game, descriptions, transcript):
    session = GameSession(game, descriptions)
    replay(session, transcript.model_copy(update={"groups": transcript.groups[:30]}), "Gavin")
    snapshot = session.snapshot()
    last = transcript.groups[29].words[-1]
    expected = (last.start + last.duration - game.when).total_seconds()
    app = create_dashboard(session.snapshot)
    board = text(refresh(app.server.test_client(), app)["scoreboard"]["children"])
    assert dashboard._mmss(expected) in board and snapshot.finished is False


# --- the describe form


def test_describe_form_calls_describe():
    calls: list[tuple[Any, ...]] = []

    def describe(team, descriptions, player=None, label=None):
        calls.append((team, descriptions, player, label))
        if player == "Nobody":
            raise ValueError("Nobody is not on Dump & Drizzle")

    game = build_game()
    session = GameSession(game)
    app = create_dashboard(session.snapshot, describe)
    client = app.server.test_client()
    glasses = json.dumps([WHITE, "glasses"])

    done = submit(client, app, name=glasses, player="Ari Weissman")
    assert calls == [(WHITE, ["glasses"], "Ari Weissman", None)]
    assert done["describe-status"]["children"] == f"Recorded: glasses ({WHITE}) is Ari Weissman."
    assert done["describe-name"]["value"] is None and done["describe-label"]["value"] == ""

    submit(client, app, name=json.dumps([BLACK, "blue"]), label="  bluey ")
    assert calls[-1] == (BLACK, ["blue"], None, "bluey")

    assert submit(client, app, name=glasses)["describe-status"]["children"].startswith("Pick a player")
    assert submit(client, app, player="Ari Weissman")["describe-status"]["children"] == "Pick a name first."
    failed = submit(client, app, name=glasses, player="Nobody")
    assert failed["describe-status"]["children"] == "Not recorded: Nobody is not on Dump & Drizzle" and "describe-name" not in failed
    assert len(calls) == 3


def test_player_choices_put_unnamed_players_first(game, descriptions):
    snapshot = truth_snapshot(game, descriptions)
    app = create_dashboard(lambda: snapshot, lambda *args, **kwargs: None)
    client = app.server.test_client()
    roster = refresh(client, app)["roster"]["data"]
    options = update(client, app, "describe-player.options", {"describe-name.value": json.dumps([WHITE, "glasses"]), "roster.data": roster})["describe-player"]["options"]
    assert options[0] == {"label": "Alexis Rosas (not named yet)", "value": "Alexis Rosas"}
    assert [option["value"] for option in options[3:]] == [player for player in game.teams[0].players if player not in roster[WHITE]["candidates"]]
    assert update(client, app, "describe-player.options", {"describe-name.value": None, "roster.data": roster})["describe-player"]["options"] == []


def test_describing_a_name_through_a_session_resolves_it(game, descriptions, transcript):
    session = GameSession(game, descriptions)
    replay(session, transcript, "Gavin")
    app = create_dashboard(session.snapshot, session.describe)
    client = app.server.test_client()
    before = refresh(client, app)
    assert "glasses · 32 mentions" in text(before["unresolved"]["children"])

    done = submit(client, app, name=json.dumps([WHITE, "glasses"]), player="Ari Weissman")
    assert done["describe-status"]["children"].startswith("Recorded")
    after = update(client, app, "seen.data", {"seen.data": before["seen"]["data"], "describe-status.children": done["describe-status"]["children"]})
    assert "glasses" not in text(after["unresolved"]["children"])
    assert any(row["player"] == "Ari Weissman" and row["throws"] == 18 for row in after["player-box"]["data"])

    refused = submit(client, app, name=json.dumps([WHITE, "blondie"]), player="Adam Federbusch")
    assert refused["describe-status"]["children"].startswith("Not recorded:")


# --- run_dashboard


def test_run_dashboard_serves_a_session(game, capsys):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    session = GameSession(game)
    stop = threading.Event()
    thread = threading.Thread(target=run_dashboard, args=(session, "127.0.0.1", port), kwargs={"stop": stop}, daemon=True)
    thread.start()
    deadline, status = time.monotonic() + 10, None
    try:
        while status is None and time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/dashboard/", timeout=2) as page:
                    status = page.status
            except OSError:
                time.sleep(0.05)
    finally:
        stop.set()
        thread.join(timeout=5)
    assert status == 200 and not thread.is_alive()
    assert f"http://127.0.0.1:{port}/dashboard/" in capsys.readouterr().out


def test_mmss():
    assert [dashboard._mmss(s) for s in (0, 59.9, 61, 913.7, 3725, -5)] == ["0:00", "0:59", "1:01", "15:13", "1:02:05", "-0:05"]
