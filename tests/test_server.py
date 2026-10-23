import contextlib
import datetime as dt
import itertools
import json
import math
import os
import pathlib
import re
import shutil
import socket
import subprocess
import threading
import time
import warnings
import wave
from collections.abc import Callable, Iterator

import numpy as np
import pytest

import yus
from tests.data.gruindoor_20250114T2030 import TEAM_FILES, build_game
from yus.session import GameSession
from yus.web import replay
from yus.web.server import FRAME, GameServer, build_arg_parser, create_app, event_text, open_session
from yus.sports import ultimate

with warnings.catch_warnings():  # starlette's TestClient prefers httpx2 to the installed httpx
    warnings.simplefilter("ignore")
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

STATIC = pathlib.Path(__file__).parents[1] / "yus" / "web" / "static"
NOW = 1_768_000_000.0  # the server's clock in most tests (2026-01-09)
PHRASES = ["black pulls", "picked up by pikachu", "backhand to glasses", "scoober to tristan", "backhand to close crop", "flick to kaia for the score"]


class FakeTranscriber:
    """Says the next scripted phrase as a group for every `every` seconds of audio fed, as if heard at that time."""

    def __init__(self, start: dt.datetime, sample_rate: int, phrases: list[str], every: float = 1.0):
        self.start, self.sample_rate, self.phrases, self.every = start, sample_rate, phrases, every
        self.samples = 0
        self.said = 0
        self.feeds: list[np.ndarray] = []
        self.flushed = False

    @property
    def audio_s(self) -> float:
        return self.samples / self.sample_rate

    @property
    def pending_text(self) -> str:
        return "..." if self.audio_s > self.said * self.every and self.said < len(self.phrases) and not self.flushed else ""

    @property
    def open_text(self) -> str:
        return ""

    @property
    def horizon(self) -> dt.datetime:
        return self.start + dt.timedelta(seconds=self.said * self.every)

    def feed(self, samples: np.ndarray) -> list[yus.TranscriptGroup]:
        assert samples.dtype == np.float32
        self.samples += len(samples)
        self.feeds.append(samples)
        groups = []
        while self.said < len(self.phrases) and (self.said + 1) * self.every <= self.audio_s:
            groups.append(self._group(self.said))
            self.said += 1
        return groups

    def flush(self) -> list[yus.TranscriptGroup]:
        self.flushed = True
        return []

    def _group(self, i: int) -> yus.TranscriptGroup:
        group = yus.TranscriptGroup()
        interpretation = group.add_interpretation(confidence=0.9)
        for k, word in enumerate(self.phrases[i].split()):
            interpretation.add_word(word, start=self.start + dt.timedelta(seconds=i * self.every + 0.1 * k), duration=dt.timedelta(seconds=0.1))
        return group


class Factory:
    def __init__(self, phrases: list[str] = PHRASES, every: float = 1.0):
        self.phrases, self.every = phrases, every
        self.made: list[FakeTranscriber] = []

    def __call__(self, start: dt.datetime, sample_rate: int) -> FakeTranscriber:
        self.made.append(FakeTranscriber(start, sample_rate, self.phrases, self.every))
        return self.made[-1]


@pytest.fixture
def game() -> yus.Game:
    return build_game()


def make_server(game: yus.Game, directory: pathlib.Path | None, factory: Factory | None = None, clock: Callable[[], float] = lambda: NOW, **options) -> GameServer:
    return GameServer(GameSession(game, directory=directory), factory, clock=clock, **{"tick": 0.02, **options})


@contextlib.contextmanager
def client_for(server: GameServer, **options) -> Iterator[TestClient]:
    with TestClient(create_app(server, **{"dashboard": False, **options})) as client:
        yield client


def frame(seq: int, capture_ms: float, seconds: float = 0.1, rate: int = 16000, value: int = 1000) -> bytes:
    return FRAME.pack(seq, capture_ms) + np.full(round(seconds * rate), value, dtype="<i2").tobytes()


def hello(name: str = "Gavin", stream: str = "s1", focus: str | None = None, client_time: float = NOW * 1000, rate: int = 16000) -> dict:
    return {"type": "hello", "commentator": name, "focus_team": focus, "sample_rate": rate, "client_time": client_time, "stream": stream}


def send_audio(ws, first: int, count: int, start_ms: float = NOW * 1000, value: int = 1000) -> None:
    for seq in range(first, first + count):
        ws.send_bytes(frame(seq, start_ms + 100 * seq, value=value))


def wait_until(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def receive_until(ws, condition: Callable[[dict], bool], timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        message = ws.receive_json()
        if condition(message):
            return message
    raise AssertionError("no such message")


def until_closed(ws, timeout: float = 5.0) -> tuple[list[dict], int]:
    """The messages the server sends `ws` until it closes it, and the close code."""
    messages, codes = [], []

    def read():
        try:
            while True:
                messages.append(ws.receive_json())
        except WebSocketDisconnect as closed:
            codes.append(closed.code)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(timeout)
    assert codes, f"the socket was not closed; messages: {messages}"
    return messages, codes[0]


def test_pages_are_served(game):
    with client_for(make_server(game, None)) as client:
        for path in ("/", "/commentate", "/admin"):
            response = client.get(path)
            assert response.status_code == 200 and response.headers["content-type"].startswith("text/html"), path
        for path in ("/static/commentate.js", "/static/pcm-worklet.js", "/static/admin.js", "/static/game.js", "/static/style.css"):
            assert client.get(path).status_code == 200, path
        script = client.get("/static/commentate.js")
        assert "getUserMedia" in script.text and script.headers["cache-control"] == "no-cache"  # phones check for a new script
        assert client.get("/dashboard/").status_code == 503  # no dashboard given
        state = client.get("/api/state").json()
        assert state["summary"] == "Dump & Drizzle 0, Category 5 0" and state["commentators"] == [] and [t["name"] for t in state["teams"]] == ["Dump & Drizzle", "Category 5"]
        assert client.get("/api/state?events=x").status_code == 400


def test_static_files_are_packaged():
    """A wheel (uv tool install, pip install .) carries only the package data pyproject.toml declares."""
    import fnmatch
    import tomllib

    import yus.web.server

    declared = tomllib.loads((pathlib.Path(__file__).parents[1] / "pyproject.toml").read_text())["tool"]["setuptools"]["package-data"]["yus.web"]
    files = [path.relative_to(yus.web.server.STATIC.parent).as_posix() for path in yus.web.server.STATIC.iterdir()]
    assert files and all(any(fnmatch.fnmatch(name, pattern) for pattern in declared) for name in files)


def test_audio_becomes_transcript_events_and_state(game, tmp_path):
    factory = Factory()
    server = make_server(game, tmp_path, factory)
    with client_for(server) as client, client.websocket_connect("/ws/audio") as ws:
        ws.send_json(hello(client_time=NOW * 1000 - 5000))  # the phone's clock is 5 s behind the server's
        welcome = ws.receive_json()
        assert welcome == {"type": "welcome", "commentator": "Gavin", "focus_team": None, "ack": -1, "stream": "s1"}
        send_audio(ws, 0, 45, start_ms=NOW * 1000 - 5000)  # 4.5 s of audio, captured as the hello was sent
        update = receive_until(ws, lambda m: m.get("ack") == 44 and len(m.get("transcript", [])) == 4)
        assert [line["text"] for line in update["transcript"]] == PHRASES[:4]
        assert update["pending"] == "..." and update["live"]
        assert [e["text"] for e in update["events"]] == ["Matt Whitlock backhand to glasses: caught", "glasses scoober to Tristan Weber: caught"]
        assert [e["provisional"] for e in update["events"]] == [False, True]  # the open throw
        state = client.get("/api/state").json()
        assert state["event_count"] == 2 and state["settled_count"] == 1
        assert {"team": "Dump & Drizzle", "name": "glasses", "mentions": 2} in state["unresolved"]
        (commentator,) = state["commentators"]
        assert commentator["name"] == "Gavin" and commentator["groups"] == 4 and commentator["connected"] and commentator["received_s"] == 4.5
    (transcriber,) = factory.made
    assert transcriber.start == dt.datetime.fromtimestamp(NOW)  # capture time on the phone's clock, moved to the server's
    assert transcriber.sample_rate == 16000 and transcriber.samples == 45 * 1600
    assert np.allclose(np.concatenate(transcriber.feeds), 1000 / 32768)
    groups = server.session.snapshot().transcripts["Gavin"]
    assert groups[1].words[0].start == dt.datetime.fromtimestamp(NOW + 1)


def test_reconnect_continues_the_same_commentator(game, tmp_path):
    factory = Factory()
    server = make_server(game, tmp_path, factory)
    with client_for(server) as client:
        with client.websocket_connect("/ws/audio") as ws:
            ws.send_json(hello())
            ws.receive_json()
            send_audio(ws, 0, 15)
            receive_until(ws, lambda m: m.get("ack") == 14)
        with client.websocket_connect("/ws/audio") as ws:
            ws.send_json(hello())  # same stream: carry on
            assert ws.receive_json()["ack"] == 14
            send_audio(ws, 10, 15)  # frames 10-14 again (a phone resending what it had not seen acknowledged), then 15-24
            update = receive_until(ws, lambda m: m.get("ack") == 24 and len(m.get("transcript", [])) == 2)
        assert [line["text"] for line in update["transcript"]] == PHRASES[:2]
        stream = server.streams["Gavin"]
        assert stream.received_s == pytest.approx(2.5) and stream.segments == 1
        assert len(factory.made) == 1 and factory.made[0].samples == 25 * 1600
        assert server.session.commentators == ["Gavin"]


def test_segments_restart_after_a_new_stream_a_long_gap_or_a_stop(game, tmp_path):
    factory = Factory()
    server = make_server(game, tmp_path, factory)
    with client_for(server) as client:
        with client.websocket_connect("/ws/audio") as ws:
            ws.send_json(hello())
            ws.receive_json()
            send_audio(ws, 0, 10)
            ws.send_bytes(frame(10, NOW * 1000 + 3000))  # 2 s of frames lost: filled with silence
            ws.send_bytes(frame(11, NOW * 1000 + 13100))  # 10 s later: a new segment
            receive_until(ws, lambda m: m.get("ack") == 11)
            wait_until(lambda: len(factory.made) == 2)
            first, second = factory.made
            wait_until(lambda: first.flushed)
            assert first.samples == 31 * 1600 and not second.flushed
            assert second.start == dt.datetime.fromtimestamp(NOW + 13.1)
            ws.send_json({"type": "stop"})
            wait_until(lambda: second.flushed)
            assert not server.streams["Gavin"].busy
        with client.websocket_connect("/ws/audio") as ws:
            ws.send_json(hello(stream="s2"))  # the page was reloaded: sequence numbers start again
            assert ws.receive_json()["ack"] == -1
            send_audio(ws, 0, 3, start_ms=NOW * 1000 + 20000)
            receive_until(ws, lambda m: m.get("ack") == 2)
    assert len(factory.made) == 3 and factory.made[2].flushed  # shutdown flushes
    assert len(server.streams["Gavin"].files) == 3


def test_idle_commentators_are_advanced(game, tmp_path):
    now = [NOW]
    factory = Factory(PHRASES[:3])
    server = make_server(game, tmp_path, factory, clock=lambda: now[0])
    with client_for(server) as client, client.websocket_connect("/ws/audio") as ws:
        ws.send_json(hello())
        ws.receive_json()
        send_audio(ws, 0, 30)
        update = receive_until(ws, lambda m: m.get("ack") == 29 and len(m.get("transcript", [])) == 3)
        assert [e["provisional"] for e in update["events"]] == [True]  # "backhand to glasses" is still open
        ws.send_json({"type": "stop"})
        now[0] = NOW + 10  # silence: more than the extractor's 6 s timeout after the last words
        update = receive_until(ws, lambda m: m.get("events") and not m["events"][-1]["provisional"])
        assert not update["live"]


def test_describe_re_resolves_names(game, tmp_path):
    server = make_server(game, tmp_path, Factory())
    with client_for(server) as client:
        with client.websocket_connect("/ws/audio") as ws:
            ws.send_json(hello())
            ws.receive_json()
            send_audio(ws, 0, 40)
            receive_until(ws, lambda m: len(m.get("transcript", [])) == 4)
        response = client.post("/api/describe", json={"team": "white", "descriptions": ["glasses"], "player": "ari weissman"})
        assert response.status_code == 200, response.text
        assert response.json()["description"] == {"team": "white", "descriptions": ["glasses"], "player": "Ari Weissman"}
        state = client.get("/api/state").json()
        assert [e["text"] for e in state["events"]] == ["Matt Whitlock backhand to Ari Weissman: caught", "Ari Weissman scoober to Tristan Weber: caught"]
        assert all(u["name"] != "glasses" for u in state["unresolved"])
        assert state["descriptions"][-1]["player"] == "Ari Weissman"
        assert client.post("/api/describe", json={"team": "purple", "descriptions": ["x"]}).status_code == 400
        assert client.post("/api/describe", json={"team": "white"}).status_code == 400
        assert client.post("/api/describe", content=b"not json").status_code == 400


def test_save_on_shutdown_and_resume(game, tmp_path):
    factory = Factory()
    server = make_server(game, tmp_path, factory, save_every=3600)
    with client_for(server) as client, client.websocket_connect("/ws/audio") as ws:
        ws.send_json(hello(name="B / Other", focus="dark"))
        assert ws.receive_json()["focus_team"] == "dark"
        send_audio(ws, 0, 25)
        receive_until(ws, lambda m: m.get("ack") == 24)
    assert (tmp_path / "session.json").exists() and (tmp_path / "transcripts" / "B_Other.json").exists()
    (path,) = server.streams["B / Other"].files
    assert path.parent == tmp_path / "audio" and path.name == f"B_Other-{dt.datetime.fromtimestamp(NOW):%Y%m%dT%H%M%S}.wav"
    with wave.open(str(path)) as audio:
        assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth(), audio.getnframes()) == (16000, 1, 2, 25 * 1600)
        assert np.all(np.frombuffer(audio.readframes(10), dtype="<i2") == 1000)
    loaded = GameSession.load(tmp_path)
    assert loaded.commentators == ["B / Other"] and loaded.snapshot().commentators[0].focus_team == "dark"
    assert [g.words[0].text for g in loaded.snapshot().transcripts["B / Other"]] == ["black", "picked"]
    resumed = GameServer(loaded, Factory(), clock=lambda: NOW + 60, tick=0.02)
    assert resumed.saved_version == loaded.version
    with client_for(resumed) as client, client.websocket_connect("/ws/audio") as ws:
        ws.send_json(hello(name="B / Other", stream="s2"))
        assert ws.receive_json()["focus_team"] == "dark"  # as saved
        send_audio(ws, 0, 10, start_ms=(NOW + 60) * 1000)
        receive_until(ws, lambda m: m.get("ack") == 9 and len(m.get("transcript", [])) == 3)
    assert len(GameSession.load(tmp_path).snapshot().transcripts["B / Other"]) == 3
    assert len(list((tmp_path / "audio").glob("*.wav"))) == 2


def test_hellos_that_are_refused(game):
    server = make_server(game, None, Factory())
    with client_for(server) as client:
        for bad, error in [(hello(focus="purple"), "No team is called 'purple'"), ({**hello(), "commentator": "  "}, "commentator name"), ({"type": "hello"}, "commentator")]:
            with client.websocket_connect("/ws/audio") as ws:
                ws.send_json(bad)
                message = ws.receive_json()
                assert message["type"] == "error" and error in message["message"]
                with pytest.raises(WebSocketDisconnect) as closed:
                    ws.receive_json()
                assert closed.value.code == 1008
        with client.websocket_connect("/ws/audio") as ws:
            ws.send_json(hello())
            ws.receive_json()
            ws.send_bytes(b"\x00\x01\x02")
            assert receive_until(ws, lambda m: m["type"] == "error")["message"] == "Malformed audio frame of 3 bytes"
        assert server.session.commentators == ["Gavin"]


def test_a_newer_connection_replaces_the_older(game):
    factory = Factory()
    server = make_server(game, None, factory)
    with client_for(server) as client, client.websocket_connect("/ws/audio") as old:
        old.send_json(hello(stream="A"))
        old.receive_json()
        send_audio(old, 0, 20)
        receive_until(old, lambda m: m.get("ack") == 19)
        with client.websocket_connect("/ws/audio") as new:
            new.send_json(hello(stream="B"))  # another phone under the same name
            assert new.receive_json()["ack"] == -1
            old.send_bytes(frame(20, NOW * 1000 + 2000))  # the old phone's next frame, already on its way: not taken
            messages, code = until_closed(old)
            assert messages[-1]["message"].startswith("Replaced") and code == 4000  # the page gives up rather than taking the name back
            send_audio(new, 0, 5, start_ms=NOW * 1000 + 3000, value=2000)
            receive_until(new, lambda m: m.get("ack") == 4)
        assert server.streams["Gavin"].connection is None
    audio = np.concatenate([np.concatenate(t.feeds) for t in factory.made])
    assert np.sum(np.isclose(audio, 1000 / 32768)) == 20 * 1600 and np.sum(np.isclose(audio, 2000 / 32768)) == 5 * 1600


def test_pausing_or_going_silent_ends_the_segment(game, tmp_path):
    now = [NOW]
    factory = Factory(PHRASES[:3])
    server = make_server(game, tmp_path, factory, clock=lambda: now[0], idle_after=20)
    stream = None
    with client_for(server) as client, client.websocket_connect("/ws/audio") as ws:
        ws.send_json(hello())
        ws.receive_json()
        send_audio(ws, 0, 30)
        update = receive_until(ws, lambda m: m.get("ack") == 29 and len(m.get("transcript", [])) == 3)
        assert update["events"][-1]["provisional"]
        ws.send_json({"type": "pause"})  # the phone's audio was suspended: its last words are committed
        stream = server.streams["Gavin"]
        wait_until(lambda: factory.made[0].flushed and not stream.busy)
        now[0] = NOW + 10
        update = receive_until(ws, lambda m: m.get("events") and not m["events"][-1]["provisional"])  # advanced while connected
        send_audio(ws, 30, 10, start_ms=NOW * 1000 + 7000)  # resumed 7 s later: a new segment, at the time it was captured
        receive_until(ws, lambda m: m.get("ack") == 39 and m.get("live"))
        assert len(factory.made) == 2 and factory.made[1].start == dt.datetime.fromtimestamp(NOW + 10)
        now[0] = NOW + 15
        time.sleep(0.1)
        assert stream.next_ms is not None  # still connected, nothing heard for 5 s: the segment stays open
        now[0] = NOW + 31  # nothing heard for longer than idle_after, though connected (a phone that could not say it paused)
        wait_until(lambda: factory.made[1].flushed)
        assert stream.connected and stream.segments == 2


def test_phone_times_that_cannot_be_right_are_not_used(game):
    factory = Factory()
    server = make_server(game, None, factory)
    with client_for(server) as client:
        for name, client_time, capture in [
            ("Wild", -1e300, 1e300),  # neither can be right: the frame was just captured
            ("Seconds", NOW, NOW * 1000),  # client time in seconds, not ms: ignored; the capture time is right
            ("Behind", NOW * 1000 - 7_200_000, NOW * 1000 - 7_200_000),  # a phone clock 2 h behind: corrected
        ]:
            with client.websocket_connect("/ws/audio") as ws:
                ws.send_json(hello(name=name, client_time=client_time))
                ws.receive_json()
                ws.send_bytes(frame(0, capture))
                ws.send_bytes(frame(1, math.nan))  # no capture time: continues
                receive_until(ws, lambda m: m.get("ack") == 1)
    starts = {name: t.start for name, t in zip(["Wild", "Seconds", "Behind"], factory.made, strict=True)}
    assert starts == {"Wild": dt.datetime.fromtimestamp(NOW - 0.1), "Seconds": dt.datetime.fromtimestamp(NOW), "Behind": dt.datetime.fromtimestamp(NOW)}
    assert all(t.samples == 2 * 1600 for t in factory.made)


def test_state_cache_stays_small(game, tmp_path):
    server = make_server(game, tmp_path, Factory())
    with client_for(server) as client:
        with client.websocket_connect("/ws/audio") as ws:
            ws.send_json(hello())
            ws.receive_json()
            send_audio(ws, 0, 60)
            receive_until(ws, lambda m: m.get("ack") == 59 and len(m.get("transcript", [])) == 6)
        wait_until(lambda: not server.streams["Gavin"].busy)
        count = client.get("/api/state?events=0").json()["event_count"]
        assert count >= 3
        everything = client.get("/api/state?events=-1").json()["events"]
        for n in (-7, count, 10**12, *range(10**6, 10**6 + 50)):
            assert client.get(f"/api/state?events={n}").json()["events"] == everything
        assert len(client.get("/api/state?events=2").json()["events"]) == 2
        assert set(server._state_cache) == {-1, 0, 2}


def test_a_transcription_error_clears_when_it_works_again(game):
    factory = Factory()
    failing = [True]

    def make(start, sample_rate):
        transcriber = factory(start, sample_rate)
        feed = transcriber.feed
        transcriber.feed = lambda samples: (_ for _ in ()).throw(RuntimeError("boom")) if failing[0] else feed(samples)
        return transcriber

    server = GameServer(GameSession(build_game()), make, clock=lambda: NOW, tick=0.02)
    with client_for(server) as client, client.websocket_connect("/ws/audio") as ws:
        ws.send_json(hello())
        ws.receive_json()
        send_audio(ws, 0, 5)
        assert receive_until(ws, lambda m: m.get("error"))["error"] == "RuntimeError: boom"
        failing[0] = False
        send_audio(ws, 5, 15)
        receive_until(ws, lambda m: m.get("ack") == 19 and not m["busy"] and m["error"] is None)
        assert client.get("/api/state").json()["commentators"][0]["error"] is None


def test_a_failing_view_does_not_end_updates(game, monkeypatch):
    server = make_server(game, None, Factory())

    def broken(name):
        raise RuntimeError("no view")

    monkeypatch.setattr(server, "commentator_view", broken)
    with client_for(server) as client, client.websocket_connect("/ws/audio") as ws:
        ws.send_json(hello())
        ws.receive_json()
        assert receive_until(ws, lambda m: m.get("error"))["error"] == "RuntimeError: no view"
        send_audio(ws, 0, 5)
        receive_until(ws, lambda m: m.get("ack") == 4)


def test_finish_commits_the_last_words_and_closes_the_game(game, tmp_path):
    factory = Factory(every=0.5)
    server = make_server(game, tmp_path, factory)
    with client_for(server) as client:
        with client.websocket_connect("/ws/audio") as ws:
            ws.send_json(hello())
            ws.receive_json()
            send_audio(ws, 0, 20)
            receive_until(ws, lambda m: m.get("ack") == 19)
            response = client.post("/api/finish")
            assert response.json()["finished"] and response.json()["summary"].startswith("Dump & Drizzle 0, Category 5 0")
            assert receive_until(ws, lambda m: m.get("finished"))["events"][-1]["provisional"] is False
        assert factory.made[0].flushed and server.session.finished
        with client.websocket_connect("/ws/audio") as ws:
            ws.send_json(hello())
            assert ws.receive_json()["message"] == "The game has finished"
    assert (tmp_path / "session.json").exists()


def test_dashboard_is_mounted(game):
    calls = []

    def create_dashboard(get_snapshot, describe, requests_pathname_prefix):
        calls.append((get_snapshot, describe, requests_pathname_prefix))

        def wsgi(environ, start_response):
            start_response("200 OK", [("Content-Type", "text/plain")])
            return [f"{environ['SCRIPT_NAME']}|{environ['PATH_INFO']}|{get_snapshot().summary}".encode()]

        return wsgi

    server = make_server(game, None)
    with TestClient(create_app(server, dashboard=create_dashboard)) as client:
        assert client.get("/dashboard/_dash-layout").text == "/dashboard|/_dash-layout|Dump & Drizzle 0, Category 5 0"
    ((get_snapshot, describe, prefix),) = calls
    assert get_snapshot == server.session.snapshot and describe == server.session.describe and prefix == "/dashboard/"


def test_the_real_dashboard_is_mounted(game):
    pytest.importorskip("yus.web.dashboard")
    with TestClient(create_app(make_server(game, None))) as client:
        response = client.get("/dashboard/")
        assert response.status_code == 200 and "/dashboard/" in response.text


def test_key_is_required_when_set(game):
    server = make_server(game, None, Factory())
    with TestClient(create_app(server, dashboard=False, key="sesame")) as client:
        assert client.get("/").status_code == 403
        assert client.get("/api/state?key=wrong").status_code == 403
        response = client.get("/api/state?events=0&key=sesame", follow_redirects=False)
        assert response.status_code == 303 and response.headers["location"] == "/api/state?events=0"
        assert "samesite=lax" in response.headers["set-cookie"].lower()  # kept when the link was opened from another app
        assert client.get("/api/state?events=0").status_code == 200  # the cookie
        for path, location in [("//example.com/", "/example.com/"), ("/\\example.com/", "/%5Cexample.com/")]:  # the redirect stays here
            response = client.get(f"http://testserver{path}?key=sesame", follow_redirects=False)
            assert response.status_code == 303 and response.headers["location"] == location, path
        client.cookies.clear()
        with pytest.raises(WebSocketDisconnect) as closed, client.websocket_connect("/ws/audio") as ws:
            ws.receive_json()
        assert closed.value.code == 4403
        with client.websocket_connect("/ws/audio?key=sesame") as ws:
            ws.send_json(hello())
            assert ws.receive_json()["type"] == "welcome"


def test_event_text():
    when = dt.datetime(2026, 1, 1)
    assert (
        event_text(ultimate.Throw(when=when, team="white", player="Kaia Mann", type="flick", direction="up_line", completed=True, scored=True))
        == "Kaia Mann flick up line to someone: score"
    )
    assert event_text(ultimate.Defense(when=when, team="dark", intercepted=True)) == "someone: interception"
    assert event_text(ultimate.Substitution(when=when, team="dark", player="Jo", sub_type="sub_on")) == "Jo subs on"


def test_open_session(tmp_path):
    args = build_arg_parser().parse_args(["--team", str(TEAM_FILES[0]), "--team", str(TEAM_FILES[1]), "--game-dir", str(tmp_path / "g")])
    session = open_session(args, dt.datetime(2026, 1, 9, 19, 30))
    assert session.directory == tmp_path / "g" and session.game.when == dt.datetime(2026, 1, 9, 19, 30) and len(session.game.teams) == 2
    session.save()
    with pytest.raises(SystemExit, match="--load"):
        open_session(args, dt.datetime(2026, 1, 9, 19, 31))
    assert open_session(build_arg_parser().parse_args(["--load", str(tmp_path / "g")]), dt.datetime.now()).game.teams == session.game.teams
    with pytest.raises(SystemExit, match="--team"):
        open_session(build_arg_parser().parse_args([]), dt.datetime.now())
    with pytest.raises(SystemExit, match="two or more"):  # a forgotten second --team: the extractor would have no opponent
        open_session(build_arg_parser().parse_args(["--team", str(TEAM_FILES[0]), "--game-dir", str(tmp_path / "h")]), dt.datetime.now())


@contextlib.contextmanager
def running(app) -> Iterator[str]:
    """Serve `app` with uvicorn on a free local port; yields the audio socket's URL."""
    import uvicorn

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    wait_until(lambda: server.started, timeout=10)
    try:
        yield f"ws://127.0.0.1:{sock.getsockname()[1]}/ws/audio"
    finally:
        server.should_exit = True
        thread.join(10)


def test_replay_streams_audio_to_a_running_server(game, tmp_path):
    factory = Factory()
    server = GameServer(GameSession(game, directory=tmp_path), factory, tick=0.05)
    samples = (0.1 * np.sin(np.arange(16000 * 6) * 2 * np.pi * 440 / 16000)).astype(np.float32)
    messages = []
    with running(create_app(server, dashboard=False)) as url:
        before = dt.datetime.now()
        result = replay.stream_audio(url, samples, "Replay", focus_team="white", speed=0, on_message=messages.append, timeout=10)
        with pytest.raises(RuntimeError, match="No team"):
            replay.stream_audio(url, samples[:1600], "Other", focus_team="purple", speed=0)
    assert result.finished and result.frames == 60 and result.acked == 59 and result.audio_s == 6.0
    assert before <= result.start <= before + dt.timedelta(seconds=2)  # the first sample's capture time, which the server stamps
    assert dt.timedelta(0) <= factory.made[0].start - result.start < dt.timedelta(seconds=1)
    assert [line["text"] for line in result.last["transcript"]] == PHRASES
    assert result.last["summary"] == "Dump & Drizzle 1, Category 5 0 (2 provisional events)"  # the scoring group waits for the next one
    (transcriber,) = factory.made
    assert transcriber.flushed and np.allclose(np.concatenate(transcriber.feeds), samples, atol=1 / 32768)
    assert (tmp_path / "session.json").exists()


def test_a_socket_without_the_key_is_closed_with_4403(game):
    """Browsers see only 1006 for a refused handshake, so the socket is accepted and then closed with the code."""
    from websockets.exceptions import ConnectionClosed
    from websockets.sync.client import connect

    with running(create_app(make_server(game, None), dashboard=False, key="sesame")) as url, connect(url, open_timeout=5) as ws:
        with pytest.raises(ConnectionClosed) as closed:
            ws.recv(timeout=5)
        assert closed.value.rcvd.code == 4403


def test_replay_frames():
    samples = np.array([0.5, -0.5, 1.0, -1.0, 0.0], dtype=np.float32)
    (first, second) = list(replay.frames(samples, 1000.0, frame_s=3 / 16000))
    assert FRAME.unpack_from(first) == (0, 1000.0) and np.frombuffer(first, "<i2", offset=FRAME.size).tolist() == [16384, -16384, 32767]
    assert FRAME.unpack_from(second) == (1, 1000.0 + 3 / 16) and np.frombuffer(second, "<i2", offset=FRAME.size).tolist() == [-32768, 0]
    assert replay.with_key("ws://h/ws/audio", "a b") == "ws://h/ws/audio?key=a+b"


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_page_scripts_parse():
    for path in STATIC.glob("*.js"):
        result = subprocess.run([NODE, "--check", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, f"{path.name}: {result.stderr}"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_downsampler_keeps_speech_and_removes_aliases():
    script = """
    const { Downsampler } = require(process.argv[1]);
    const out = {};
    for (const rate of [48000, 44100]) for (const freq of [440, 3000, 12000]) {
      const d = new Downsampler(rate, 16000), y = [];
      const x = Float32Array.from({ length: rate }, (_, i) => Math.sin(2 * Math.PI * freq * i / rate));
      for (let i = 0; i < x.length; i += 128) d.process(x.subarray(i, i + 128), (v) => y.push(v));
      const tail = y.slice(1000);
      out[`${rate}/${freq}`] = [y.length, Math.sqrt(tail.reduce((s, v) => s + v * v, 0) / tail.length)];
    }
    console.log(JSON.stringify(out));
    """
    result = subprocess.run([NODE, "-e", script, str(STATIC / "pcm-worklet.js")], capture_output=True, text=True, check=True)
    levels = json.loads(result.stdout)
    for rate in (48000, 44100):
        assert levels[f"{rate}/440"][0] == 16000  # one second in, one second out
        assert levels[f"{rate}/440"][1] == pytest.approx(0.707, abs=0.01) and levels[f"{rate}/3000"][1] == pytest.approx(0.707, abs=0.02)
        assert levels[f"{rate}/12000"][1] < 0.01  # would alias to 4 kHz: at least 37 dB down


# commentate.js in a node vm with a stub DOM, a settable clock (clock.now) and fake sockets; prints the steps' value as JSON.
PAGE = """
const vm = require("vm"), fs = require("fs");
const clock = { now: 1768000000000 }, sockets = [], listeners = {}, intervals = [], elements = {};
class FakeDate extends Date { static now() { return clock.now; } }
class FakeSocket {
  constructor(url) { Object.assign(this, { url, readyState: 0, sent: [], closed: false, bufferedAmount: 0 }); sockets.push(this); }
  send(data) { this.sent.push(data); }
  close() { this.closed = true; this.readyState = 2; }
}
Object.assign(FakeSocket, { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 });
const element = () => ({ value: "", textContent: "", style: {}, classList: { add() {}, remove() {} }, addEventListener() {}, focus() {}, replaceChildren() {}, append() {} });
const page = {
  Date: FakeDate, WebSocket: FakeSocket, clock, sockets, listeners, intervals,
  document: {
    getElementById: (id) => (elements[id] ||= element()), addEventListener: (type, f) => (listeners[type] ||= []).push(f),
    createElement: element, createTextNode: () => ({}),
  },
  navigator: {}, location: { protocol: "https:", host: "game.test" }, localStorage: { getItem: () => "", setItem() {} },
  setInterval: (f) => intervals.push(f), setTimeout() {}, fetch: () => new Promise(() => {}),
};
page.window = page;
vm.createContext(page);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), page);
vm.runInContext(`
  function frame() { onFrame({ pcm: new Int16Array(1600).buffer, level: 0 }); }
  function tick() { intervals.forEach((f) => f()); }
  function open(ws) { ws.readyState = WebSocket.OPEN; ws.onopen(); ws.onmessage({ data: JSON.stringify({ type: "welcome", ack: -1 }) }); }
  function kinds(ws) { return ws.sent.map((m) => (typeof m === "string" ? JSON.parse(m).type : "frame")); }
`, page);
console.log(JSON.stringify(vm.runInContext(process.argv[2], page)));
"""


def run_page(steps: str):
    result = subprocess.run([NODE, "-e", PAGE, str(STATIC / "commentate.js"), f"(() => {{ {steps} }})()"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_page_capture_times_follow_pauses():
    """Capture times count samples, so they survive a busy page; when the audio clock stops (suspended), they start again."""
    steps = """
    const ctx = { state: "running", currentTime: 0, baseLatency: 0.01 };
    const play = (ms) => { clock.now += ms; ctx.currentTime += ms / 1000; };
    Object.assign(state, { audio: { ctx }, live: true });
    for (let i = 0; i < 5; i++) { play(100); frame(); }
    play(2000);  // the page was busy for 2 s: the audio went on, and its frames arrive at once
    for (let i = 0; i < 20; i++) frame();
    clock.now += 8000;  // suspended for 8 s: the audio clock stopped
    for (let i = 0; i < 2; i++) { play(100); frame(); }
    const times = state.frames.map((f) => new DataView(f.data).getFloat64(4, true));
    return { steps: times.slice(1).map((t, i) => Math.round(t - times[i])), behind: Math.round(clock.now - times[times.length - 1] - 100) };
    """
    result = run_page(steps)
    assert result == {"steps": [100] * 24 + [8100, 100], "behind": 10}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_page_tells_the_server_when_audio_pauses():
    steps = """
    const ctx = { state: "running", currentTime: 0, baseLatency: 0 };
    ui.name.value = "Gavin";
    Object.assign(state, { audio: { ctx }, live: true, wantSocket: true, lastFrame: clock.now });
    connect();
    const ws = sockets[0];
    open(ws);
    frame();
    ctx.state = "suspended";
    tick(); tick();
    ctx.state = "running";
    clock.now += 5000; ctx.currentTime += 0.1;
    frame();
    ws.onmessage({ data: JSON.stringify({ type: "update", ack: 1 }) });
    tick();
    clock.now += 4000;  // running, but no audio for 4 s
    tick(); tick();
    return kinds(ws);
    """
    assert run_page(steps) == ["hello", "frame", "pause", "frame", "pause"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_page_reconnects_at_once_when_the_socket_goes_silent():
    """A half-open socket (a network drop with no reset) takes a browser a minute to close: the page doesn't wait for it."""
    steps = """
    ui.name.value = "Gavin";
    state.wantSocket = true;
    connect();
    const first = sockets[0];
    open(first);
    clock.now += 9000;  // nothing heard
    tick();
    clock.now += 9000;  // the next socket never opens either
    tick();
    return { sockets: sockets.length, closed: first.closed, detached: first.onclose === null, current: state.ws === sockets[2] };
    """
    assert run_page(steps) == {"sockets": 3, "closed": True, "detached": True, "current": True}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_page_resumes_audio_on_a_touch_and_stops_on_refusals():
    steps = """
    const resumed = [];
    state.audio = { ctx: { state: "suspended", resume: () => resumed.push(1) } };
    for (const type of ["touchend", "click"]) (listeners[type] || []).forEach((f) => f({}));  // what iOS counts as a gesture
    state.audio = null;
    ui.name.value = "Gavin";
    state.wantSocket = true;
    connect();
    sockets[0].onclose({ code: 1003, reason: "bad frame" });  // resending the same frame would fail again
    return { resumed: resumed.length, wantSocket: state.wantSocket, fatal: state.fatal };
    """
    assert run_page(steps) == {"resumed": 2, "wantSocket": False, "fatal": "bad frame"}


CHROME = os.environ.get("YUS_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
# A synthetic microphone: headless Chrome's fake capture device hangs getUserMedia on macOS.
FAKE_MICROPHONE = """navigator.mediaDevices.getUserMedia = async (constraints) => {
  window.constraints = constraints;
  const context = new AudioContext({ sampleRate: 44100 });
  for (const type of ["touchend", "click"]) document.addEventListener(type, () => context.resume());  // like the page's own context, it waits for a tap
  const tone = context.createOscillator(), gain = context.createGain(), out = context.createMediaStreamDestination();
  tone.frequency.value = 440;
  gain.gain.value = 0.5;
  tone.connect(gain).connect(out);
  tone.start();
  return out.stream;
}"""


class Browser:
    """Headless Chrome driven over the DevTools protocol: one tab."""

    def __init__(self, ws):
        self.ws, self.ids, self.session = ws, itertools.count(1), None
        target = self.call("Target.createTarget", url="about:blank")["targetId"]
        self.session = self.call("Target.attachToTarget", targetId=target, flatten=True)["sessionId"]

    def call(self, method: str, **params):
        i = next(self.ids)
        self.ws.send(json.dumps({"id": i, "method": method, "params": params, **({"sessionId": self.session} if self.session else {})}))
        while (message := json.loads(self.ws.recv(timeout=20))).get("id") != i:
            pass
        assert "error" not in message, message
        return message["result"]

    def js(self, expression: str):
        result = self.call("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True)
        assert "exceptionDetails" not in result, result["exceptionDetails"]
        return result["result"].get("value")

    def wait(self, expression: str, timeout: float = 10.0):
        wait_until(lambda: self.js(expression), timeout)

    def tap(self):
        """A finger tap: its pointerdown is no user gesture for audio, its touchend is."""
        for kind, points in (("touchStart", [{"x": 5, "y": 5}]), ("touchEnd", [])):
            self.call("Input.dispatchTouchEvent", type=kind, touchPoints=points)


@pytest.mark.skipif(os.environ.get("YUS_SLOW_TESTS") != "1" or not os.path.exists(CHROME), reason="needs YUS_SLOW_TESTS=1 and Chrome (YUS_CHROME)")
def test_commentate_page_in_chrome(game, tmp_path):
    """The real page in headless Chrome: audio waits for a tap, then goes from a 44.1 kHz context to the transcriber at 16 kHz;
    a dropped connection reconnects and continues the segment, a pause ends it and a tap starts the next at the right time, and
    stop ends that."""
    from websockets.sync.client import connect

    factory = Factory()
    server = GameServer(GameSession(game, directory=tmp_path), factory, tick=0.1)
    command = [CHROME, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={tmp_path / 'profile'}", "--mute-audio", "--no-first-run", "about:blank"]
    with running(create_app(server, dashboard=False)) as url, subprocess.Popen(command, stderr=subprocess.PIPE, text=True) as chrome:
        try:
            devtools = next(match.group(1) for line in chrome.stderr if (match := re.search(r"DevTools listening on (ws://\S+)", line)))
            with connect(devtools, max_size=None) as ws:
                tab = Browser(ws)
                tab.call("Page.navigate", url=url.replace("ws://", "http://").replace("/ws/audio", "/commentate"))
                tab.wait("document.readyState === 'complete' && document.getElementById('focus').options.length === 3")
                tab.js(FAKE_MICROPHONE)
                tab.js("document.getElementById('name').value = 'Chrome'; document.getElementById('focus').value = 'Category 5'; document.getElementById('toggle').click()")
                tab.wait("document.getElementById('status').textContent === 'Audio paused: tap anywhere to resume'")  # no user gesture yet
                tab.tap()
                tab.wait("document.getElementById('status').textContent === 'Live'")
                assert tab.js("window.constraints") == {"audio": {"echoCancellation": False, "channelCount": 1}}
                tab.wait("document.querySelectorAll('#transcript li').length >= 2")
                assert tab.js("document.querySelector('#transcript li').textContent").endswith("black pulls")
                stream = server.streams["Chrome"]
                received = stream.received_s
                tab.js("state.ws.close()")  # the connection drops; audio is kept and resent
                tab.wait("document.getElementById('status').textContent.startsWith('Reconnecting')")
                tab.wait("document.getElementById('status').textContent === 'Live'")
                wait_until(lambda: stream.received_s > received + 1)
                tab.js("state.audio.ctx.suspend()")  # a phone call, or the page in the background
                wait_until(lambda: stream.next_ms is None and factory.made[0].flushed)  # the page said so: the last words are committed
                time.sleep(2)
                tab.tap()
                resumed = time.time()
                tab.wait("document.getElementById('status').textContent === 'Live'")
                wait_until(lambda: len(factory.made) == 2)
                assert abs(factory.made[1].start.timestamp() - resumed) < 0.5  # not 2 s early
                tab.js("document.getElementById('toggle').click()")
                tab.wait("document.getElementById('status').textContent === 'Stopped (connected)'")
                wait_until(lambda: factory.made[1].flushed)
        finally:
            chrome.terminate()
    assert stream.segments == 2 and server.session.snapshot().commentators[0].focus_team == "Category 5"
    first, second = factory.made
    audio = np.concatenate(first.feeds)
    assert first.sample_rate == 16000 and first.samples + second.samples == pytest.approx(stream.received_s * 16000)
    assert np.sqrt(np.mean(audio[1600:] ** 2)) == pytest.approx(0.5 / np.sqrt(2), rel=0.02)  # the tone, downsampled
