"""The live game server: phones stream commentary audio to it, and it serves the game's events and stats as they happen.

    phone /commentate --hello, PCM16 frames over /ws/audio--> CommentatorStream --worker thread--> LiveTranscriber
        --groups, pending text, horizon--> GameSession <--snapshot()-- /, /api/state, /admin, /dashboard/ (Dash)

One Starlette app holds one GameSession. Each commentator gets a CommentatorStream: it orders and de-duplicates the phone's
frames (a phone resends what was not acknowledged after a reconnect), timestamps them from the session's clock, records them
as WAV files, and feeds a LiveTranscriber in its own worker thread, so that decoding never blocks the event loop. A background
task advances idle commentators every second and saves the session every few seconds and at shutdown. See docs/server.md.

Exposed as the yus-serve command-line tool.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import datetime as dt
import hmac
import io
import json
import logging
import math
import pathlib
import queue
import re
import socket
import struct
import sys
import threading
import time
import wave
from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol
from urllib.parse import parse_qs

import numpy as np
import pydantic
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket, WebSocketDisconnect

import yus
from yus.processing.event_unification import GameDescriptions
from yus.session import GameSession, GameSnapshot
from yus.sports import ultimate

log = logging.getLogger("yus.server")

STATIC = pathlib.Path(__file__).parent / "static"
SAMPLE_RATE = 16000  # what the commentator page sends, and Whisper's rate

# A binary frame is this header, then mono PCM16 (little-endian) samples: the frame's sequence number within the phone's stream,
# and the capture time of its first sample on the phone's clock (ms since 1970).
FRAME = struct.Struct("<Id")
CONTIGUOUS_MS = 1000.0  # a frame starting this close to where the last one ended continues it
PAD_MS = 5000.0  # a gap up to this long (frames lost) is filled with silence; a longer one (or a jump back) starts a new segment
MAX_FRAME_S = 10.0  # longest frame accepted

TICK_S = 1.0  # how often idle commentators are advanced
SAVE_S = 10.0  # how often the session is saved, when it changed
IDLE_S = 120.0  # a commentator disconnected this long has their segment ended (their last words committed)
UPDATE_S = 0.25  # how often a phone is sent an update, when something changed
HEARTBEAT_S = 2.0  # ... and at least this often
TRANSCRIPT_LINES = 8  # transcript groups a phone shows
EVENT_LINES = 6  # events a phone shows

_STOP = object()  # worker: end the segment and exit
_FLUSH = object()  # worker: end the segment


class Transcriber(Protocol):
    """What the server needs of a LiveTranscriber (tests pass fakes)."""

    @property
    def pending_text(self) -> str: ...

    @property
    def open_text(self) -> str: ...

    @property
    def horizon(self) -> dt.datetime: ...

    def feed(self, samples: np.ndarray) -> list[yus.TranscriptGroup]: ...

    def flush(self) -> list[yus.TranscriptGroup]: ...


# (start: wall-clock time of the first sample, naive local; sample_rate) -> a Transcriber for one segment of one commentator's audio
TranscriberFactory = Callable[[dt.datetime, int], Transcriber]


class Hello(pydantic.BaseModel):
    """The first message on /ws/audio."""

    type: str = "hello"
    commentator: str = pydantic.Field(..., min_length=1, max_length=80)
    focus_team: str | None = pydantic.Field(None, description="Any name of the team this commentator follows; None for the whole game.")
    sample_rate: int = pydantic.Field(SAMPLE_RATE, ge=8000, le=192000)
    client_time: float | None = pydantic.Field(None, description="The phone's clock when it sent this, ms since 1970.")
    stream: str = pydantic.Field("", max_length=100, description="Id of the phone's audio stream (one per page load); sequence numbers count within it.")

    @pydantic.field_validator("commentator")
    @classmethod
    def _strip(cls, value: str) -> str:
        if not (value := " ".join(value.split())):
            raise ValueError("a commentator name is needed")
        return value

    @pydantic.field_validator("focus_team")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class DescribeRequest(pydantic.BaseModel):
    """POST /api/describe: GameSession.describe's arguments."""

    model_config = pydantic.ConfigDict(extra="forbid")

    team: str
    descriptions: list[str] | str
    player: str | None = None
    label: str | None = None
    commentator: str | None = None


@dataclasses.dataclass
class _Start:
    start: dt.datetime
    sample_rate: int


class CommentatorStream:
    """One commentator's audio: frames in order and once each, timestamped, recorded, and transcribed by a worker thread.

    Audio arrives in segments: a segment is contiguous audio, transcribed by one Transcriber that starts at the segment's first
    sample. A segment ends when the commentator stops, when the phone starts a new stream (a reload), when frames jump back or
    leave a gap longer than PAD_MS, or after IDLE_S disconnected. Everything but the worker runs on the event loop.
    """

    def __init__(self, server: GameServer, name: str):
        self.server, self.name = server, name
        self.stream_id: str | None = None
        self.sample_rate = SAMPLE_RATE
        self.offset_ms = 0.0  # the server's clock minus the phone's
        self.last_seq = -1  # the last frame taken (acknowledged)
        self.next_ms: float | None = None  # where the open segment ends, on the phone's clock; None: no segment open
        self.connection: _Connection | None = None
        self.last_frame = 0.0  # server time of the last frame
        self.received_s = 0.0  # seconds of audio taken
        self.fed_s = 0.0  # ... and given to a transcriber (set by the worker)
        self.segments = 0
        self.files: list[pathlib.Path] = []
        self.error: str | None = None  # the worker's last error
        self._wav: wave.Wave_write | None = None
        self._file: io.BufferedWriter | None = None
        self._queue: queue.Queue[Any] = queue.Queue()
        self._rate = SAMPLE_RATE  # the worker's segment's sample rate
        self._worker: threading.Thread | None = None
        if server.transcriber_factory is not None:
            self._worker = threading.Thread(target=self._work, name=f"yus-asr-{name}", daemon=True)
            self._worker.start()

    @property
    def connected(self) -> bool:
        return self.connection is not None

    @property
    def busy(self) -> bool:
        """Whether the worker has audio or a flush still to process."""
        return self._queue.unfinished_tasks > 0

    @property
    def backlog_s(self) -> float:
        """Seconds of audio received but not yet given to the transcriber."""
        return max(0.0, self.received_s - self.fed_s) if self._worker else 0.0

    def hello(self, hello: Hello, now_ms: float) -> None:
        """A phone (re)connected. A new stream id or sample rate ends the open segment: sequence numbers start again."""
        if hello.stream != self.stream_id or hello.sample_rate != self.sample_rate:
            self.end_segment()
            self.stream_id, self.sample_rate, self.last_seq = hello.stream, hello.sample_rate, -1
        self.offset_ms = now_ms - hello.client_time if hello.client_time and math.isfinite(hello.client_time) else 0.0

    def receive(self, data: bytes, now: float) -> bool:
        """Take a binary frame; False if it was taken before. Raises ValueError for a malformed frame."""
        if len(data) < FRAME.size or (len(data) - FRAME.size) % 2 or len(data) - FRAME.size > 2 * MAX_FRAME_S * self.sample_rate:
            raise ValueError(f"Malformed audio frame of {len(data)} bytes")
        seq, capture_ms = FRAME.unpack_from(data)
        if seq <= self.last_seq:
            return False
        pcm = np.frombuffer(data, dtype="<i2", offset=FRAME.size)
        if not math.isfinite(capture_ms) or capture_ms <= 0:  # no capture time: assume it continues, else that it just ended
            capture_ms = self.next_ms if self.next_ms is not None else now * 1000 - self.offset_ms - len(pcm) / self.sample_rate * 1000
        if self.next_ms is not None and abs(capture_ms - self.next_ms) > CONTIGUOUS_MS:
            gap = capture_ms - self.next_ms
            if 0 < gap <= PAD_MS:
                self._audio(np.zeros(round(gap / 1000 * self.sample_rate), dtype=np.int16))
            else:
                self.end_segment()
        if self.next_ms is None:
            self._start_segment(capture_ms)
        self._audio(pcm)
        self.next_ms = capture_ms + len(pcm) / self.sample_rate * 1000
        self.last_seq, self.last_frame = seq, now
        return True

    def end_segment(self) -> None:
        """The commentator stopped: close the WAV file and have the transcriber commit everything."""
        if self.next_ms is None:
            return
        self.next_ms = None
        self._close_file()
        if self._worker:
            self._queue.put(_FLUSH)

    def stop(self) -> None:
        """End the segment and the worker (it exits once it has transcribed everything queued)."""
        self.end_segment()
        if self._worker:
            self._queue.put(_STOP)

    def join(self, timeout: float | None = None) -> None:
        if self._worker:
            self._worker.join(timeout)

    # ------------------------------------------------------------------ segments and files

    def _start_segment(self, capture_ms: float) -> None:
        start = dt.datetime.fromtimestamp((capture_ms + self.offset_ms) / 1000)  # naive local time on the server's clock
        self.segments += 1
        self._open_file(start)
        if self._worker:
            self._queue.put(_Start(start, self.sample_rate))

    def _audio(self, pcm: np.ndarray) -> None:
        if self._wav is not None:
            self._wav.writeframes(pcm.tobytes())
        self.received_s += len(pcm) / self.sample_rate
        if self._worker:
            self._queue.put(pcm)

    def _open_file(self, start: dt.datetime) -> None:
        if self.server.audio_directory is None:
            return
        self.server.audio_directory.mkdir(parents=True, exist_ok=True)
        stem = f"{file_stem(self.name)}-{start:%Y%m%dT%H%M%S}"  # yus-transcribe --recording-start auto reads the time back
        for i in range(1, 1000):
            path = self.server.audio_directory / (f"{stem}.wav" if i == 1 else f"{stem}-{i}.wav")
            try:
                self._file = path.open("xb")
                break
            except FileExistsError:
                continue
        else:
            return
        self._wav = wave.open(self._file, "wb")
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(self.sample_rate)
        self.files.append(path)

    def _close_file(self) -> None:
        if self._wav is not None and self._file is not None:
            self._wav.close()  # patches the header; leaves the file to us
            self._file.close()
        self._wav = self._file = None

    # ------------------------------------------------------------------ worker thread

    def _work(self) -> None:
        """Take everything queued, feed the audio in one call per segment (a decoder that fell behind catches up), repeat."""
        transcriber: Transcriber | None = None
        while True:
            items = [self._queue.get()]
            with contextlib.suppress(queue.Empty):
                while True:
                    items.append(self._queue.get_nowait())
            try:
                transcriber = self._process(items, transcriber)
            finally:
                for _ in items:
                    self._queue.task_done()
            if any(item is _STOP for item in items):
                return

    def _process(self, items: list[Any], transcriber: Transcriber | None) -> Transcriber | None:
        audio: list[np.ndarray] = []
        for item in [*items, None]:  # None: feed what was gathered
            if isinstance(item, np.ndarray):
                audio.append(item)
                continue
            try:
                self._feed(transcriber, audio)
                if item is not None and transcriber is not None:  # a new segment, a flush or the end: commit every word
                    transcriber, ended = None, transcriber
                    self._deliver(ended.flush(), ended)
                if isinstance(item, _Start):
                    self._rate = item.sample_rate
                    transcriber = self.server.transcriber_factory(item.start, item.sample_rate)  # type: ignore[misc]
            except Exception as error:  # keep the worker alive: log, drop the audio, and go on
                log.exception("Transcription failed for %s", self.name)
                self.error = f"{type(error).__name__}: {error}"
            audio = []
        return transcriber

    def _feed(self, transcriber: Transcriber | None, audio: list[np.ndarray]) -> None:
        if not audio:
            return
        samples = np.concatenate(audio).astype(np.float32) / 32768.0
        try:
            if transcriber is not None:
                self._deliver(transcriber.feed(samples), transcriber)
        finally:
            self.fed_s += len(samples) / self._rate

    def _deliver(self, groups: list[yus.TranscriptGroup], transcriber: Transcriber) -> None:
        session = self.server.session
        try:
            if groups:
                session.add_groups(self.name, groups)
            session.set_pending_text(self.name, " ".join(text for text in (transcriber.open_text, transcriber.pending_text) if text))
            session.advance(transcriber.horizon, self.name)
        except RuntimeError:
            if not session.finished:
                raise  # else the game finished: words after the end don't count


class _Connection:
    """One open /ws/audio socket. Every send goes through `send`, so that two tasks never write at once."""

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.replaced = asyncio.Event()
        self._lock = asyncio.Lock()

    async def send(self, message: dict[str, Any]) -> None:
        async with self._lock:
            await self.websocket.send_json(message)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        async with self._lock:
            with contextlib.suppress(Exception):
                await self.websocket.close(code, reason)


class GameServer:
    """One game's session, its commentators' audio streams, and the background task that advances and saves them.

    server = GameServer(session, transcriber_factory)   # None: record audio only
    app = create_app(server)                           # serve with uvicorn; its lifespan runs `background()` and `close()`
    """

    def __init__(
        self,
        session: GameSession,
        transcriber_factory: TranscriberFactory | None = None,
        *,
        clock: Callable[[], float] = time.time,
        tick: float = TICK_S,
        save_every: float = SAVE_S,
        idle_after: float = IDLE_S,
        record_audio: bool = True,
    ):
        self.session = session
        self.transcriber_factory = transcriber_factory
        self.clock = clock
        self.tick, self.save_every, self.idle_after = tick, save_every, idle_after
        self.audio_directory = session.directory / "audio" if record_audio and session.directory is not None else None
        self.streams: dict[str, CommentatorStream] = {}
        saved = session.directory is not None and (session.directory / "session.json").exists()
        self.saved_version: int | None = session.version if saved else None  # e.g. a session just loaded
        self._saved_at = clock()
        self._save_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._state_cache: dict[int, dict[str, Any]] = {}  # per number of events, for one version
        self._state_version: int | None = None
        self._closed = False
        self._finishing = False

    def now(self) -> dt.datetime:
        """The session's clock: naive local time."""
        return dt.datetime.fromtimestamp(self.clock())

    def stream(self, name: str) -> CommentatorStream:
        if name not in self.streams:
            self.streams[name] = CommentatorStream(self, name)
        return self.streams[name]

    # ------------------------------------------------------------------ background

    async def background(self) -> None:
        """Every `tick`: end the segments of commentators disconnected for `idle_after`, advance idle commentators to now, and save
        every `save_every` seconds when the session changed."""
        while True:
            await asyncio.sleep(self.tick)
            try:
                idle = self._idle_commentators()
                if idle:
                    await run_in_threadpool(self._advance, idle)
                if self.clock() - self._saved_at >= self.save_every:
                    self._saved_at = self.clock()
                    await run_in_threadpool(self.save)
            except Exception:
                log.exception("Background tick failed")

    def _idle_commentators(self) -> list[str]:
        """Commentators with no segment open and nothing left to transcribe: their transcript is complete up to now."""
        idle = []
        for name in self.session.commentators:
            stream = self.streams.get(name)
            if stream is not None and stream.next_ms is not None:
                if stream.connected or self.clock() - stream.last_frame < self.idle_after:
                    continue
                stream.end_segment()
            if stream is None or not stream.busy:
                idle.append(name)
        return idle

    def _advance(self, names: list[str]) -> None:
        now = self.now()
        for name in names:
            self.session.advance(now, name)

    def save(self) -> bool:
        """Save the session if it changed since the last save (and has a directory). True if it was saved."""
        if self.session.directory is None:
            return False
        with self._save_lock:
            version = self.session.version
            if version == self.saved_version:
                return False
            self.session.save()
            self.saved_version = version
            return True

    async def close(self, timeout: float = 60.0) -> None:
        """Shut down: end every segment, let the workers transcribe what they have (up to `timeout` seconds), and save."""
        if self._closed:
            return
        self._closed = True
        for stream in self.streams.values():
            stream.stop()
        deadline = time.monotonic() + timeout
        for stream in self.streams.values():
            await run_in_threadpool(stream.join, max(0.0, deadline - time.monotonic()))
        await run_in_threadpool(self.save)

    @property
    def accepting(self) -> bool:
        """Whether audio is still taken (not once the game is finishing or finished)."""
        return not (self._finishing or self.session.finished)

    async def finish(self, timeout: float = 60.0) -> None:
        """End the game: stop taking audio, end every segment, wait for the transcribers to commit their words, finish the
        session, and save."""
        self._finishing = True
        for stream in self.streams.values():
            stream.end_segment()
        deadline = time.monotonic() + timeout
        while any(stream.busy for stream in self.streams.values()) and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        await run_in_threadpool(self.session.finish)
        await run_in_threadpool(self.save)

    # ------------------------------------------------------------------ views

    def state(self, events: int = 20) -> dict[str, Any]:
        """The game for /api/state: score, teams, commentators, the last `events` official events (-1: all), unresolved names."""
        snap = self.session.snapshot()
        with self._state_lock:
            if self._state_version != snap.version:
                self._state_cache, self._state_version = {}, snap.version
            cached = self._state_cache.get(events)
            if cached is None:
                cached = self._state_cache[events] = _game_state(snap, events)
        return {**cached, "commentators": [self._commentator_state(c.name, c.model_dump()) for c in snap.commentators]}

    def _commentator_state(self, name: str, state: dict[str, Any]) -> dict[str, Any]:
        stream = self.streams.get(name)
        live = {"connected": False, "live": False, "received_s": 0.0, "backlog_s": 0.0, "segments": 0, "error": None}
        if stream is not None:
            live = {
                "connected": stream.connected,
                "live": stream.next_ms is not None,
                "received_s": round(stream.received_s, 1),
                "backlog_s": round(stream.backlog_s, 1),
                "segments": stream.segments,
                "error": stream.error,
            }
        return {**state, **live}

    def commentator_view(self, name: str) -> dict[str, Any]:
        """What a commentator's phone shows: their latest transcript and pending text, their latest events, and the score."""
        snap = self.session.snapshot()
        state = next((c for c in snap.commentators if c.name == name), None)
        groups = snap.transcripts.get(name, [])[-TRANSCRIPT_LINES:]
        events = snap.resolved[name].events if name in snap.resolved else []
        first = max(0, len(events) - EVENT_LINES)
        start = _start(snap)
        return {
            "version": snap.version,
            "finished": snap.finished,
            "summary": snap.summary,
            "score": snap.score,
            "transcript": [{"time": _clock(group.start, start), "text": " ".join(w.text for w in group.words)} for group in groups if group.interpretations],
            "pending": state.pending_text if state else "",
            "events": [event_json(event, first + i, first + i >= (state.final_count if state else 0), start) for i, event in enumerate(events[first:])],
        }


def _game_state(snap: GameSnapshot, events: int) -> dict[str, Any]:
    official = snap.official.events
    first = 0 if events < 0 else max(0, len(official) - events)
    start = _start(snap)
    return {
        "version": snap.version,
        "finished": snap.finished,
        "summary": snap.summary,
        "score": snap.score,
        "sport": snap.game.sport,
        "when": snap.game.when.isoformat(),
        "teams": [{"name": team.names[0] if team.names else f"team {i + 1}", "names": team.names, "players": list(team.players)} for i, team in enumerate(snap.game.teams)],
        "event_count": len(official),
        "settled_count": snap.settled_count,
        "events": [event_json(event, first + i, first + i >= snap.settled_count, start) for i, event in enumerate(official[first:])],
        "unresolved": [{"team": team, "name": name, "mentions": count} for team, name, count in snap.unresolved],
        "unmentioned": snap.unmentioned,
        "descriptions": [d.model_dump(exclude_none=True) for d in snap.descriptions.players],
    }


def _start(snap: GameSnapshot) -> dt.datetime | None:
    return snap.stats.start


def _clock(when: dt.datetime, start: dt.datetime | None) -> str:
    """Game time, e.g. "12:05" or "1:02:05" (the time of day without a start)."""
    try:
        seconds = (when - start).total_seconds() if start is not None else None
    except TypeError:  # naive and aware
        seconds = None
    if seconds is None:
        return f"{when:%H:%M:%S}"
    sign, seconds = ("-" if seconds < 0 else ""), abs(int(seconds))
    hours, minutes = divmod(seconds // 60, 60)
    return f"{sign}{hours}:{minutes:02d}:{seconds % 60:02d}" if hours else f"{sign}{minutes}:{seconds % 60:02d}"


def event_text(event: yus.Event) -> str:
    """A short line for an event, e.g. "Kaia Mann flick huck to Tristan Weber: score"."""
    who = getattr(event, "player", None) or "someone"
    if isinstance(event, ultimate.Throw):
        kind = " ".join(str(part).replace("_", " ") for part in (event.type, event.direction) if part) or "throw"
        outcome = "score" if event.scored else "caught" if event.completed else "not caught"
        extras = [name for name in ("hit_wall", "hit_net") if getattr(event, name, False)]
        notes = f" ({', '.join(name.replace('hit_', 'off the ') for name in extras)})" if extras else ""
        return f"{who} {kind} to {event.receiver or 'someone'}: {outcome}{notes}"
    if isinstance(event, ultimate.Defense):
        return f"{who}: {'interception' if event.intercepted else 'block'}"
    if isinstance(event, ultimate.Substitution):
        return f"{who} subs {'on' if event.sub_type == ultimate.SubType.SUB_ON else 'off'}"
    if isinstance(event, ultimate.Infraction):
        return f"infraction by {who}"
    return type(event).__name__


def event_json(event: yus.Event, index: int, provisional: bool, start: dt.datetime | None) -> dict[str, Any]:
    return {
        "index": index,
        "type": type(event).__name__,
        "time": event.when.isoformat(timespec="milliseconds"),
        "clock": _clock(event.when, start),
        "team": getattr(event, "team", None),
        "text": event_text(event),
        "scored": bool(getattr(event, "scored", False)),
        "provisional": provisional,
    }


def file_stem(name: str) -> str:
    """A name made file-safe, e.g. "B / Other" -> "B_Other"."""
    return re.sub(r"[^\w.-]+", "_", name, flags=re.ASCII).strip("._") or "commentator"


# ---------------------------------------------------------------------------------------------------------------------- the app


def create_app(server: GameServer, dashboard: Callable[..., Any] | bool = True, key: str | None = None) -> ASGIApp:
    """The ASGI app. `dashboard`: True mounts yus.web.dashboard's Dash app at /dashboard/ (when it can be imported), False doesn't,
    and a callable is used in its place (create_dashboard's signature). `key`: if set, every request needs it (see KeyMiddleware)."""

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        task = asyncio.create_task(server.background())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await server.close()

    routes: list[Any] = [
        Route("/", _page("index.html")),
        Route("/commentate", _page("commentate.html")),
        Route("/admin", _page("admin.html")),
        Route("/api/state", _api_state),
        Route("/api/describe", _api_describe, methods=["POST"]),
        Route("/api/finish", _api_finish, methods=["POST"]),
        WebSocketRoute("/ws/audio", _audio_socket),
        Mount("/static", app=_Revalidated(directory=STATIC), name="static"),
    ]
    dash_app = _dashboard_app(server, dashboard)
    if dash_app is not None:
        routes.append(Mount("/dashboard", app=dash_app))
    else:
        routes.append(Route("/dashboard/", _no_dashboard))
    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.server = server
    return KeyMiddleware(app, key) if key else app


class _Revalidated(StaticFiles):
    """Static files that browsers check for changes (ETag) before using, so that phones get new page scripts after an update."""

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def _page(name: str) -> Callable[[Request], Any]:
    async def endpoint(request: Request) -> Response:
        return FileResponse(STATIC / name, headers={"Cache-Control": "no-cache"})

    return endpoint


async def _no_dashboard(request: Request) -> Response:
    return HTMLResponse('<p>No dashboard: yus.web.dashboard could not be loaded (see the server log). <a href="/">Back</a></p>', status_code=503)


async def _api_state(request: Request) -> Response:
    server: GameServer = request.app.state.server
    try:
        events = int(request.query_params.get("events", "20"))
    except ValueError:
        return JSONResponse({"error": "events must be an integer"}, status_code=400)
    return JSONResponse(await run_in_threadpool(server.state, events))


async def _api_describe(request: Request) -> Response:
    server: GameServer = request.app.state.server
    try:
        body = DescribeRequest.model_validate_json(await request.body())
        record = await run_in_threadpool(server.session.describe, body.team, body.descriptions, body.player, body.label, body.commentator)
    except (pydantic.ValidationError, ValueError) as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    return JSONResponse({"description": record.model_dump(exclude_none=True), "version": server.session.version})


async def _api_finish(request: Request) -> Response:
    server: GameServer = request.app.state.server
    await server.finish()
    summary = await run_in_threadpool(lambda: server.session.snapshot().summary)
    return JSONResponse({"finished": True, "version": server.session.version, "summary": summary})


def _dashboard_app(server: GameServer, dashboard: Callable[..., Any] | bool) -> ASGIApp | None:
    if dashboard is False:
        return None
    if dashboard is True:
        try:
            from yus.web.dashboard import create_dashboard
        except ImportError as error:
            log.warning("No dashboard: %s", error)
            return None
        dashboard = create_dashboard
    from a2wsgi import WSGIMiddleware

    app = dashboard(server.session.snapshot, server.session.describe, requests_pathname_prefix="/dashboard/")
    return WSGIMiddleware(getattr(app, "server", app))  # a Dash app's Flask server, or a WSGI app


async def _audio_socket(websocket: WebSocket) -> None:
    """/ws/audio: a hello, then binary frames (and {"type": "stop"}); JSON updates go back. See docs/server.md."""
    server: GameServer = websocket.app.state.server
    await websocket.accept()
    connection = _Connection(websocket)
    hello = await _greet(server, connection)
    if hello is None:
        return
    stream = server.stream(hello.commentator)
    if stream.connection is not None:
        stream.connection.replaced.set()  # the newest connection wins: a phone that reconnected before its old socket timed out
    stream.connection = connection
    stream.hello(hello, server.clock() * 1000)
    focus = next((c.focus_team for c in server.session.snapshot().commentators if c.name == hello.commentator), None)
    await connection.send({"type": "welcome", "commentator": hello.commentator, "focus_team": focus, "ack": stream.last_seq, "stream": stream.stream_id})
    sender = asyncio.create_task(_send_updates(server, stream, connection))
    try:
        await _receive_audio(server, stream, connection)
    except ValueError as error:
        await connection.send({"type": "error", "message": str(error)})
        await connection.close(1003, "bad frame")
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await sender
        if stream.connection is connection:
            stream.connection = None


async def _greet(server: GameServer, connection: _Connection) -> Hello | None:
    """Read the hello and add its commentator if new; None (the socket closed) if the hello is refused."""
    try:
        hello = Hello.model_validate_json(await connection.websocket.receive_text())
        if not server.accepting:
            raise ValueError("The game has finished")
        if hello.commentator not in server.session.commentators:
            try:
                await run_in_threadpool(server.session.add_commentator, hello.commentator, hello.focus_team)
            except ValueError:
                if hello.commentator not in server.session.commentators:  # else another connection just added them
                    raise
        return hello
    except WebSocketDisconnect:
        return None
    except (pydantic.ValidationError, ValueError, RuntimeError, KeyError) as error:
        await connection.send({"type": "error", "message": str(error)})
        await connection.close(1008, "bad hello")
        return None


async def _receive_audio(server: GameServer, stream: CommentatorStream, connection: _Connection) -> None:
    while not connection.replaced.is_set():
        message = await connection.websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        if message.get("bytes") is not None:
            if server.accepting:
                stream.receive(message["bytes"], server.clock())
        elif message.get("text") is not None and _json(message["text"]).get("type") == "stop":
            stream.end_segment()


async def _send_updates(server: GameServer, stream: CommentatorStream, connection: _Connection) -> None:
    """Send the phone its acknowledgements and what changed, every UPDATE_S at most and HEARTBEAT_S at least."""
    sent: tuple[Any, ...] | None = None
    version: int | None = None
    last = 0.0
    while True:
        if connection.replaced.is_set():
            await connection.send({"type": "error", "message": "Replaced by a newer connection for this commentator"})
            await connection.close(4000, "replaced")
            return
        message: dict[str, Any] = {
            "type": "update",
            "ack": stream.last_seq,
            "live": stream.next_ms is not None,
            "busy": stream.busy,
            "received_s": round(stream.received_s, 1),
            "backlog_s": round(stream.backlog_s, 1),
            "error": stream.error,
        }
        key = tuple(message.values())
        if server.session.version != version:
            version = server.session.version
            try:
                message.update(await run_in_threadpool(server.commentator_view, stream.name))
            except Exception as error:
                log.exception("Could not show %s their view", stream.name)
                message["error"] = f"{type(error).__name__}: {error}"
        elif key == sent and time.monotonic() - last < HEARTBEAT_S:
            await asyncio.sleep(UPDATE_S)
            continue
        await connection.send(message)
        sent, last = key, time.monotonic()
        await asyncio.sleep(UPDATE_S)


def _json(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


class KeyMiddleware:
    """Require a shared key on every request: `?key=...` once (it is then kept in a cookie), or the cookie itself."""

    COOKIE = "yus_key"

    def __init__(self, app: ASGIApp, key: str):
        self.app, self.key = app, key

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        given = parse_qs(scope.get("query_string", b"").decode("latin-1")).get("key", [None])[0]
        cookies = Request(scope).cookies if scope["type"] == "http" else WebSocket(scope, receive, send).cookies
        if self._valid(given) and scope["type"] == "http":
            query = "&".join(part for part in scope.get("query_string", b"").decode("latin-1").split("&") if not part.startswith("key="))
            response = RedirectResponse(scope["path"] + (f"?{query}" if query else ""), status_code=303)
            response.set_cookie(self.COOKIE, self.key, httponly=True, samesite="lax", secure=scope.get("scheme") == "https", max_age=7 * 24 * 3600)
            return await response(scope, receive, send)
        if self._valid(given) or self._valid(cookies.get(self.COOKIE)):
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 4403, "reason": "key needed"})
        return await PlainTextResponse("Forbidden: open the link with ?key=... first", status_code=403)(scope, receive, send)

    def _valid(self, given: str | None) -> bool:
        return given is not None and hmac.compare_digest(given.encode(), self.key.encode())


# ------------------------------------------------------------------------------------------------------------------ command line


def whisper_factory(teams: list[yus.Team], sport: str = "ultimate/indoor", backend: str = "auto", model: str = "large-v3-turbo", language: str = "en") -> TranscriberFactory:
    """Load Whisper once and make LiveTranscribers that share it. Decodes are serialized (one GPU): commentators take turns."""
    from yus.processing.transcription import live
    from yus.processing.transcription import transcribe as tr

    backend = tr.resolve_backend(backend)
    if repo_id := tr.resolve_hf_repo_id(model, backend):
        tr.ensure_model_downloaded(repo_id, ("weights.safetensors", "weights.npz") if backend == "mlx" else ("model.bin",))
    whisper = live.load_whisper(backend, model, language)
    prompt = live.live_prompt(teams, whisper, sport=sport)
    replacements = tr.load_replacements(sport, teams)
    lock = threading.Lock()

    def decode(audio: np.ndarray, prompt: str | None) -> list[dict[str, Any]]:
        with lock:
            return whisper(audio, prompt)

    decode(np.zeros(SAMPLE_RATE, dtype=np.float32), prompt)  # compile the model's kernels before the first commentator
    log.info("Whisper %s loaded with %s; prompt: %s", model, backend, prompt)
    return lambda start, sample_rate: live.LiveTranscriber(start, prompt, replacements, sample_rate=sample_rate, transcribe=decode)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve a live game: phones stream commentary audio to /commentate; / shows the score, /dashboard/ the stats.")
    parser.add_argument("--team", dest="teams", action="append", type=pathlib.Path, default=[], help="Team JSON file (repeat for each team).")
    parser.add_argument("--descriptions", type=pathlib.Path, help="Game descriptions JSON (who commentators' descriptions mean).")
    parser.add_argument("--game-dir", type=pathlib.Path, help="Directory for the game's files (default: games/<start time>).")
    parser.add_argument("--load", type=pathlib.Path, help="Resume the game saved in this directory (its teams and descriptions are used).")
    parser.add_argument("--sport", default="ultimate/indoor", help="Sport (default: ultimate/indoor).")
    parser.add_argument("--host", default="0.0.0.0", help="Address to listen on (default: 0.0.0.0, every interface).")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000).")
    parser.add_argument("--ssl-certfile", type=pathlib.Path, help="TLS certificate (phones need HTTPS for the microphone; see docs/server.md).")
    parser.add_argument("--ssl-keyfile", type=pathlib.Path, help="TLS private key.")
    parser.add_argument("--asr", choices=("auto", "mlx", "faster-whisper", "none"), default="auto", help="Whisper backend; none records audio without transcribing.")
    parser.add_argument("--model", default="large-v3-turbo", help="Whisper model (default: large-v3-turbo).")
    parser.add_argument("--key", help="Require this key: open pages once with ?key=KEY (kept in a cookie). For servers reachable from the internet.")
    parser.add_argument("--no-audio", action="store_false", dest="record_audio", default=True, help="Do not save commentators' audio.")
    return parser


def open_session(args: argparse.Namespace, now: dt.datetime) -> GameSession:
    if args.load:
        if args.teams or args.descriptions:
            print("--load: using the saved game's teams and descriptions; --team and --descriptions are ignored", file=sys.stderr)
        return GameSession.load(args.load)
    if not args.teams:
        raise SystemExit("Give the teams (--team T.json, once per team), or --load a saved game")
    from yus.processing.transcription import transcribe as tr

    directory = args.game_dir or pathlib.Path("games") / f"{now:%Y%m%dT%H%M%S}"
    if (directory / "session.json").exists():
        raise SystemExit(f"{directory} already holds a game: resume it with --load {directory}")
    descriptions = GameDescriptions.model_validate_json(args.descriptions.read_text()) if args.descriptions else None
    game = yus.Game(sport=args.sport, when=now, teams=tr.load_teams_from_files(args.teams))
    directory.mkdir(parents=True, exist_ok=True)
    return GameSession(game, descriptions, directory)


def lan_address() -> str | None:
    """This computer's address on the local network (no packet is sent)."""
    with contextlib.suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect(("192.0.2.1", 9))  # TEST-NET-1: connect() on UDP only picks the route
        return probe.getsockname()[0]
    return None


def main() -> int:
    args = build_arg_parser().parse_args()
    if bool(args.ssl_certfile) != bool(args.ssl_keyfile):
        raise SystemExit("Give both --ssl-certfile and --ssl-keyfile")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    session = open_session(args, dt.datetime.now().replace(microsecond=0))
    factory = None if args.asr == "none" else whisper_factory(session.game.teams, session.game.sport, args.asr, args.model)
    server = GameServer(session, factory, record_audio=args.record_audio)
    app = create_app(server, key=args.key)

    import uvicorn

    scheme = "https" if args.ssl_certfile else "http"
    host = lan_address() if args.host in ("0.0.0.0", "::") else args.host
    query = f"?key={args.key}" if args.key else ""
    print(f"Game directory: {session.directory}", file=sys.stderr)
    print(f"Commentators: {scheme}://{host or 'localhost'}:{args.port}/commentate{query}", file=sys.stderr)
    print(f"Game page:    {scheme}://{host or 'localhost'}:{args.port}/{query}", file=sys.stderr)
    if scheme == "http":
        print("Phones need HTTPS for the microphone: see docs/server.md (mkcert certificate, or a tunnel).", file=sys.stderr)
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        ssl_certfile=str(args.ssl_certfile) if args.ssl_certfile else None,
        ssl_keyfile=str(args.ssl_keyfile) if args.ssl_keyfile else None,
        timeout_graceful_shutdown=5,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
