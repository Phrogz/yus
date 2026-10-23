"""yus-replay: stream an audio file to a running yus-serve over /ws/audio, as a phone would, for demos and end-to-end tests.

    yus-replay 20250114T2030-0700.ogg --commentator Gavin --url ws://localhost:8000/ws/audio --speed 1

It sends the hello, then 100 ms PCM16 frames with sequence numbers and capture times (the capture clock starts now and runs at
the audio's pace, so the server timestamps the audio as if it were spoken now), then a stop, and waits until the server has
acknowledged every frame and transcribed everything. See docs/server.md.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import ssl
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import numpy as np

from yus.web.server import FRAME, SAMPLE_RATE

FRAME_S = 0.1


@dataclasses.dataclass
class ReplayResult:
    frames: int
    audio_s: float
    elapsed_s: float
    acked: int  # the last frame the server acknowledged
    finished: bool  # whether the server confirmed it had transcribed everything before the timeout
    last: dict[str, Any]  # the last update with the commentator's view (transcript, pending, events, summary)


def frames(samples: np.ndarray, start_ms: float, frame_s: float = FRAME_S, sample_rate: int = SAMPLE_RATE) -> Iterator[bytes]:
    """Binary /ws/audio frames for mono float32 `samples`: header (sequence number, capture time) and PCM16."""
    pcm = np.clip(np.asarray(samples, dtype=np.float32) * 32768.0, -32768, 32767).astype("<i2")
    size = max(1, round(frame_s * sample_rate))
    for seq, first in enumerate(range(0, len(pcm), size)):
        yield FRAME.pack(seq, start_ms + first / sample_rate * 1000) + pcm[first : first + size].tobytes()


def with_key(url: str, key: str | None) -> str:
    if not key:
        return url
    parts = urlsplit(url)
    return urlunsplit(parts._replace(query="&".join(filter(None, [parts.query, urlencode({"key": key})]))))


def stream_audio(
    url: str,
    samples: np.ndarray,
    commentator: str,
    *,
    focus_team: str | None = None,
    speed: float = 1.0,
    key: str | None = None,
    insecure: bool = False,
    on_message: Callable[[dict[str, Any]], None] | None = None,
    timeout: float = 120.0,
    clock: Callable[[], float] = time.time,
) -> ReplayResult:
    """Stream 16 kHz mono float32 `samples` to the server at `url` (ws:// or wss://) at `speed` (1 real time, 0 as fast as
    possible), then stop and wait up to `timeout` seconds for the server to transcribe everything. Raises RuntimeError if the
    server refuses the hello."""
    from websockets.sync.client import connect

    if speed < 0:
        raise ValueError(f"speed must be 0 or more, got {speed}")
    context = None
    if url.startswith("wss:"):
        context = ssl.create_default_context()
        if insecure:
            context.check_hostname, context.verify_mode = False, ssl.CERT_NONE
    start_ms = clock() * 1000
    hello = {"type": "hello", "commentator": commentator, "focus_team": focus_team, "sample_rate": SAMPLE_RATE, "client_time": start_ms, "stream": uuid.uuid4().hex}
    began = time.monotonic()
    with connect(with_key(url, key), ssl=context, max_size=None, open_timeout=10) as ws:
        ws.send(json.dumps(hello))
        welcome = json.loads(ws.recv(timeout=10))
        if welcome.get("type") != "welcome":
            raise RuntimeError(welcome.get("message") or f"Unexpected reply: {welcome}")
        listener = _Listener(ws, on_message)
        listener.start()
        sent = 0
        for sent, frame in enumerate(frames(samples, start_ms), start=1):
            if speed > 0 and (wait := began + (sent - 1) * FRAME_S / speed - time.monotonic()) > 0:
                time.sleep(wait)
            ws.send(frame)
        stopped = time.monotonic()
        ws.send(json.dumps({"type": "stop"}))
        listener.wait_for(sent - 1, stopped)
        finished = listener.done.wait(timeout)
        ws.close()
        listener.join(5)
    return ReplayResult(sent, len(samples) / SAMPLE_RATE, time.monotonic() - began, listener.acked, finished, listener.last)


class _Listener(threading.Thread):
    """Reads the server's messages; `done` is set by the first update, after the stop, acknowledging every frame with nothing
    left to transcribe."""

    def __init__(self, ws: Any, on_message: Callable[[dict[str, Any]], None] | None):
        super().__init__(daemon=True)
        self.ws, self.on_message = ws, on_message
        self.acked = -1
        self.last: dict[str, Any] = {}
        self.done = threading.Event()
        self._target: tuple[int, float] | None = None
        self._lock = threading.Lock()

    def wait_for(self, last_seq: int, after: float) -> None:
        """Set `done` once an update received after `after` (monotonic time) acknowledges `last_seq` with nothing left to do."""
        with self._lock:
            self._target = (last_seq, after)

    def run(self) -> None:
        for raw in self.ws:
            message = json.loads(raw)
            if self.on_message:
                self.on_message(message)
            if message.get("type") != "update":
                continue
            self.acked = max(self.acked, message.get("ack", -1))
            if "transcript" in message:
                self.last = message
            with self._lock:
                target = self._target
            if target and self.acked >= target[0] and time.monotonic() > target[1] and not message.get("live") and not message.get("busy"):
                self.done.set()


class Printer:
    """Prints each new transcript line and event, and score changes."""

    def __init__(self) -> None:
        self.seen: set[tuple[str, str]] = set()
        self.summary = ""

    def __call__(self, message: dict[str, Any]) -> None:
        if message.get("type") == "error":
            print(f"server: {message.get('message')}", file=sys.stderr, flush=True)
        for line in message.get("transcript", []):
            if (key := (line["time"], line["text"])) not in self.seen:
                self.seen.add(key)
                print(f"{line['time']:>6}  {line['text']}", flush=True)
        for event in message.get("events", []):
            if not event["provisional"] and (key := (event["time"], event["text"])) not in self.seen:
                self.seen.add(key)
                print(f"{event['clock']:>6}  > {event['text']}", flush=True)
        if message.get("summary") and message["summary"] != self.summary:
            self.summary = message["summary"]
            print(f"        = {self.summary}", flush=True)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stream an audio file to a running yus-serve as a phone would.")
    parser.add_argument("audio", type=pathlib.Path, help="Audio file (wav/mp3/m4a/ogg/...).")
    parser.add_argument("--commentator", required=True, help="Commentator name.")
    parser.add_argument("--url", default="ws://localhost:8000/ws/audio", help="The server's audio socket (default: ws://localhost:8000/ws/audio; wss:// for HTTPS).")
    parser.add_argument("--focus", help="The team this commentator follows (any of its names).")
    parser.add_argument("--speed", type=float, default=1.0, help="1 (default) streams in real time, 2 twice as fast, 0 as fast as possible.")
    parser.add_argument("--start", type=float, help="Start this many seconds into the audio.")
    parser.add_argument("--stop", type=float, help="Stop this many seconds into the audio.")
    parser.add_argument("--key", help="The server's --key.")
    parser.add_argument("--insecure", action="store_true", help="Do not verify the server's TLS certificate (a self-signed one).")
    parser.add_argument("--timeout", type=float, default=120.0, help="Seconds to wait for transcription to finish after the last frame (default: 120).")
    parser.add_argument("--quiet", action="store_true", help="Do not print transcript lines and events.")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    from yus.processing.transcription.live import load_audio

    audio = load_audio(args.audio)
    audio = audio[int((args.start or 0) * SAMPLE_RATE) : int(args.stop * SAMPLE_RATE) if args.stop is not None else None]
    print(f"Streaming {len(audio) / SAMPLE_RATE:.1f} s of {args.audio} to {args.url} as {args.commentator!r} at speed {args.speed:g}", file=sys.stderr, flush=True)
    try:
        result = stream_audio(
            args.url,
            audio,
            args.commentator,
            focus_team=args.focus,
            speed=args.speed,
            key=args.key,
            insecure=args.insecure,
            on_message=None if args.quiet else Printer(),
            timeout=args.timeout,
        )
    except (OSError, RuntimeError) as error:
        print(f"Failed: {error}", file=sys.stderr)
        return 1
    print(f"Sent {result.frames} frames ({result.audio_s:.1f} s) in {result.elapsed_s:.1f} s; acknowledged up to {result.acked}", file=sys.stderr)
    print(result.last.get("summary", "") if result.finished else "The server had not finished transcribing when the timeout ran out", file=sys.stderr)
    return 0 if result.finished else 2


if __name__ == "__main__":
    raise SystemExit(main())
