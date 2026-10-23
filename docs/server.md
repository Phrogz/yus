# Live Game Server

`yus-serve` runs one game live. Commentators open a page on their phones and stream their microphones to it. The server
transcribes each one as they speak, extracts events, and serves the score, the events and the stats while the game is on.

```text
phone /commentate ──hello, PCM16 frames over /ws/audio──> CommentatorStream ──worker thread──> LiveTranscriber
     ^                                                        │ WAV per segment                    │ groups, pending text, horizon
     └──── acks, transcript, events, score (JSON) ────────────┘                                    v
browsers: / (score)  /admin (identify names)  /dashboard/ (Dash)  /api/state  <──snapshot()── GameSession ──> files
```

- One Starlette app (served by uvicorn) holds one `GameSession` (see [session.md](session.md)).
- Each commentator gets a `CommentatorStream`. It takes the phone's frames in order and only once, timestamps them, writes
  them to WAV files, and queues them for a `LiveTranscriber` (see [live_transcription.md](live_transcription.md)).
- The transcriber runs in the commentator's own worker thread, so decoding never blocks the event loop. The worker feeds
  everything queued in one call. It hands the session the groups that closed, the open and pending text, and
  `advance(transcriber.horizon)`.
- A background task runs every second. It advances commentators who are not streaming (stopped, paused, or no frame for
  2 minutes) to the current time, so their open throw becomes final after the session's timeout and other commentators'
  events can settle. It also saves the session every 10 s when it changed, and again at shutdown.
- The Dash app from `yus.web.dashboard` is mounted at `/dashboard/` through `a2wsgi` (see [dashboard.md](dashboard.md)).

## Running a Game

```bash
yus-serve --team team_dump_and_drizzle.json --team team_category_5.json \
    --ssl-certfile yus.pem --ssl-keyfile yus-key.pem          # phones need HTTPS: see below
```

The server prints the commentators' link (`https://<this Mac's LAN address>:8000/commentate`) and the game page's link.
On the commentate page each commentator enters a name, picks the team they follow (or both), and taps the big button.
`/admin` lists the names nobody has identified yet, with the likely players first, and assigns them. It also takes free-form
descriptions and has a "Finish game" button.

| option | |
|---|---|
| `--team T.json` | a team file; repeat for each team (see [usage.md](usage.md#team-json-files)) |
| `--descriptions D.json` | per-game descriptions known before the game |
| `--game-dir DIR` | where the game is saved (default `games/<start time>`). It refuses a directory that already holds a game |
| `--load DIR` | resume a saved game (its teams and descriptions are used) |
| `--sport` | default `ultimate/indoor` |
| `--host`, `--port` | default `0.0.0.0:8000` (every interface) |
| `--ssl-certfile F --ssl-keyfile F` | serve HTTPS |
| `--asr auto\|mlx\|faster-whisper\|none` | Whisper backend. `none` only records audio. The model is loaded and warmed up once at startup and shared by all commentators |
| `--model` | default `large-v3-turbo` |
| `--key KEY` | require a shared key: open links once with `?key=KEY` (it is then kept in a cookie). Use it whenever the server is reachable from outside your network |
| `--no-audio` | do not save audio |

`yus-replay` streams an audio file to a running server as a phone would. It is for demos and end-to-end tests:

```bash
yus-replay 20250114T2030-0700.ogg --commentator Gavin --url wss://192.168.1.20:8000/ws/audio --insecure --speed 1
```

It prints transcript lines, final events and score changes. At the end it stops and waits until the server has transcribed
everything. `--speed 2` streams twice as fast and `--speed 0` as fast as possible. `--start`/`--stop` select seconds of the
file. Use `--key` with the server's key, and `--insecure` to skip checking a self-signed certificate.

### HTTPS for phones

Browsers only give a page the microphone over HTTPS (or on `localhost`). This was not set up or tried on real phones here;
choose one of these:

1. **A local certificate on the LAN (mkcert).** Phones and the Mac must be on the same Wi-Fi. Gym Wi-Fi often isolates
   clients from each other; a phone hotspot or a travel router avoids that.
   ```bash
   brew install mkcert && mkcert -install                 # creates a local CA and trusts it on this Mac
   mkcert 192.168.1.20 localhost                          # this Mac's LAN address -> 192.168.1.20+1.pem and -key.pem
   yus-serve --team ... --ssl-certfile 192.168.1.20+1.pem --ssl-keyfile 192.168.1.20+1-key.pem
   ```
   Each phone must trust the CA once. `mkcert -CAROOT` shows the folder with `rootCA.pem`; share only that file, never
   `rootCA-key.pem`.
   - iPhone: AirDrop or email the file and install the profile (Settings > General > VPN & Device Management). Then turn on
     full trust in Settings > General > About > Certificate Trust Settings.
   - Android: Settings > Security > Encryption & credentials > Install a certificate > CA certificate. Menu names vary.

   Without a trusted certificate, the browser shows a warning, and the page may still be refused the microphone.
2. **A tunnel with a public HTTPS address.** For example `cloudflared tunnel --url http://localhost:8000` gives a random
   `https://….trycloudflare.com` address, and WebSockets work through it. `tailscale funnel 8000` and `ngrok http 8000` are
   alternatives. No certificate is needed on the phones, but the game is then on the internet: use `--key`. Each phone
   needs about 260 kbit/s of upload.
3. **A reverse proxy with a real certificate** (for example Caddy) on a domain you control, forwarding to `yus-serve`.

For testing only, Android Chrome can treat one `http://` LAN address as secure (`chrome://flags`, "Insecure origins
treated as secure"). iOS has no such option.

## The Commentate Page

- **Microphone.** It calls `getUserMedia({audio: {echoCancellation: false, channelCount: 1}})`. An AudioWorklet
  (`static/pcm-worklet.js`) low-pass filters the audio at the device rate: a 31-tap windowed sinc with its cutoff at 7.2 kHz.
  It then resamples to 16 kHz mono PCM16 by linear interpolation, and posts 100 ms frames.
- **Frames.** Each frame gets a sequence number and the capture time of its first sample. The capture time is the start
  time plus the samples captured since, so it runs on the audio clock and a busy page that gets frames late does not move it.
  When the audio clock stood still for more than 1 s longer than the wall clock (the context was suspended), or the context
  left the running state, the start time is taken again from `Date.now()`, so audio after a pause is stamped when it was
  captured.
- **Kept until acknowledged.** Frames stay on the phone until the server acknowledges them, up to 5 minutes (9.6 MB); after
  that the oldest are dropped. After a dropped connection the page reconnects with backoff (0.5 s, doubling, at most 5 s). It
  resends what the server has not acknowledged, in order, holding back while more than 512 KB are queued in the socket. A
  page that hears nothing for 8 s (or whose socket has not opened after 8 s) drops that socket and connects again at once:
  it does not wait for the browser to close it, which takes a minute after a network drop that sent no reset.
- **Pauses.** When the audio context is suspended, or no frame came for 3 s, the page sends `{"type": "pause"}` once,
  after everything captured. The server then commits the last words and stops waiting for this commentator.
- **What it shows.** The connection state, a level meter, the last 8 transcript groups with the pending text, the
  commentator's last 6 events (provisional ones in italics), and the score.
- **Problems it reports:** "Audio paused" when the audio context is suspended (no user gesture, a phone call, the page in
  the background), and a tap anywhere resumes it (on `touchend` and `click`, which iOS counts as gestures, and
  `pointerdown`); "No sound from the microphone" after 3 s without frames; a page opened without HTTPS; refusals from the
  server. After close codes 1003, 1008, 4000 and 4403 it stops rather than reconnecting.
- **Screen.** A Screen Wake Lock keeps the screen on while live, and is requested again when the page comes back.
- Name and team are remembered in `localStorage`.
- It needs iOS 14.5 or newer (AudioWorklet). The wake lock needs iOS 16.4 or newer; without it the page asks the commentator
  to keep the screen on.

## Protocol (`/ws/audio`)

1. Text: `{"type": "hello", "commentator": "Gavin", "focus_team": "white" | null, "sample_rate": 16000, "client_time": <ms since 1970>, "stream": "<id per page load>"}`.
   The server adds the commentator if they are new. An unknown team, an empty name or a finished game get
   `{"type": "error", "message": ...}`, and the socket closes with code 1008.
2. Server: `{"type": "welcome", "commentator", "focus_team", "ack": <last frame taken, -1 for none>, "stream"}`.
3. Binary frames: `<uint32 sequence number><float64 capture time, ms since 1970 on the phone's clock>` (little-endian), then
   mono PCM16 samples. A malformed frame gets an error and close code 1003.
4. Text `{"type": "stop"}` (the commentator stopped) or `{"type": "pause"}` (their audio paused): the segment ends and the
   transcriber commits every word. Frames after a pause start a new segment.
5. Server, every 0.25 s when something changed and at least every 2 s: `{"type": "update", "ack", "live", "busy",
   "received_s", "backlog_s", "error"}`. When the session's version changed, the update also carries `version`, `finished`,
   `summary`, `score`, `transcript` (`[{time, text}]`), `pending` and `events` (`[{index, type, time, clock, team, text,
   scored, provisional}]`).

**Order and time.**
- Frames whose sequence number was already taken are dropped.
- The server's clock minus the phone's (`client_time`) is measured at each hello. A segment's first sample is stamped with its
  capture time plus that offset, as a naive local time like `yus-transcribe`'s.
- Times that cannot be right are not used. An offset of more than a day counts as 0. A capture time more than a day from
  the server's clock (after the offset), or missing, is taken as continuing the segment, or with none open, as just captured.
- Later frames continue the segment by sample count while their capture time is within 1 s of where the last frame ended.
  A gap of up to 5 s (lost frames) is filled with silence.
- A segment ends on a longer gap, a jump back in time, `stop` or `pause`, a new `stream` id or sample rate, or 2 minutes
  without a frame, connected or not. Each segment has its own transcriber and its own WAV file.

**Connections.** A second connection for the same name replaces the first: the newest connection wins, for example a phone
that reconnected before its old socket timed out. Nothing more is taken from the old connection, not even a frame already
on its way, and it gets an error and close code 4000. Close code 4403 means the key is missing; the socket is accepted
first, because browsers report a refused handshake only as 1006.

## HTTP API

- `GET /api/state?events=20`: `version`, `finished`, `summary`, `score`, `sport`, `when`, `teams` (`name`, `names`,
  `players`), `event_count`, `settled_count`, the last `events` official events (`-1` for all), `unresolved`
  (`[{team, name, mentions}]`), `unmentioned` (`{team: [players]}`), `descriptions`, and `commentators`. Each commentator has
  `CommentatorState`'s fields plus `connected`, `live`, `received_s`, `backlog_s`, `segments` and `error` (the transcriber's
  last error, until it next works). Everything but `commentators` is cached per version and per `events`. A negative
  `events`, or one past the number of events, means all of them.
- `POST /api/describe` with `{"team", "descriptions": [...] | "...", "player"?, "label"?, "commentator"?}`: calls
  `GameSession.describe` and returns `{"description", "version"}`. Earlier events are resolved again. Bad input gets 400
  `{"error"}`.
- `POST /api/finish`: stops taking audio, ends every segment, waits up to 60 s for the transcribers to commit their last
  words, then finishes the session and saves it. It cannot be undone.

## Files

The game directory holds the session's files (`session.json`, `game.json`, `descriptions.json`, `transcripts/`, `events/`,
`official.json`; see [session.md](session.md#files)). Audio goes in `audio/<commentator>-<YYYYMMDDTHHMMSS>.wav`, one file per
segment, 16 kHz mono PCM16. The header is kept valid as frames are written, so a crash loses nothing. The time in the name is
the segment's start to the second, so `yus-transcribe --recording-start auto` reads it back (the fraction of a second is lost).

## Python API

```python
from yus.web.server import GameServer, create_app, whisper_factory

server = GameServer(session, whisper_factory(session.game.teams))    # or any (start, sample_rate) -> transcriber; None records only
app = create_app(server, dashboard=True, key=None)                    # ASGI; its lifespan runs server.background() and server.close()
uvicorn.run(app, host="0.0.0.0", port=8000)

from yus.web.replay import stream_audio
result = stream_audio("ws://localhost:8000/ws/audio", samples_16k, "Gavin", speed=1)   # -> ReplayResult(frames, acked, finished, last, ...)
```

- A transcriber needs `feed(samples)`, `flush()`, `pending_text`, `open_text` and `horizon`, as `LiveTranscriber` has. Tests
  use a scripted fake.
- `GameServer(session, factory, clock=time.time, tick=1, save_every=10, idle_after=120, record_audio=True)`.
- `whisper_factory` loads Whisper once, builds the roster prompt and the mondegreen replacements, and serializes decodes
  (one GPU).

## Measured

These numbers come from an Apple Silicon Mac, a local WebSocket, and the real audio of the 2025-01-14 20:30 game (961 s). No
Whisper model was loaded: the GPU was reserved for another measurement. A stand-in transcriber returned the real Whisper
transcript of the game (`tests/data/…-whisper-turbo.json`), each group 3 s after its last word, with `horizon` defined as
`LiveTranscriber`'s.

- **Correctness.** Streamed through `/ws/audio` (9,607 frames), the game came out exactly as when the same transcript is fed
  straight into a `GameSession`: 201 groups, 200 events, Dump & Drizzle 14, Category 5 10. Two commentators streaming the
  same game at once gave a merged stream of 200 events, the same score, and an estimated offset of 0.0 s.
- **Throughput.** Streaming at full speed, all 961 s were sent in 1.4 s, and acknowledged and transcribed by 1.6 s. That
  is about 0.16 ms per 100 ms frame, WAV writing included, with the client in the same process. Two commentators took 2.8 s.
- **Real time** (90 s at speed 1):
  - acknowledgements came a median 127 ms after a frame was sent (p95 240 ms, max 271 ms), bounded by the 0.25 s update
    period;
  - 358 messages, median 99 B; the 16 that carried the transcript and events were at most 1.8 KB.
- **Pages.**
  - `/api/state` for the whole game: 6.8 KB with the last 20 events (40 KB with all 200). It took 34–45 ms on the first
    request after a change (stats) and about 5 ms after that.
  - `/dashboard/` through a2wsgi: 9–11 ms.
- **Audio.**
  - Uplink: 256 kbit/s per phone plus 12 bytes per frame.
  - Disk: 1.9 MB per minute (30.7 MB for the game).
- **Review fixes**, with the reviewer's probes (headless Chrome, uvicorn):
  - A network drop that leaves the socket half-open: the page was on a new socket after 8.3 s, not 68.5 s.
  - Two phones streaming under one name: in 10 of 10 runs the newer phone lost no frames (before: 8–11 lost in 8 of 10),
    and the older one was closed with 4000.
  - An 8 s suspend, then a tap: the last frame's capture end was 57 ms behind the phone's clock (before: 8,056 ms), and the
    audio after it was a second segment.
- **Downsampler** (node, unit sines):
  - 440 Hz and 3 kHz pass at 48 and 44.1 kHz, within 0.15 dB.
  - 12 kHz, which would alias to 4 kHz, comes out at RMS 0.001 (−57 dB) from 48 kHz.
  - In headless Chrome, a 0.5-amplitude 440 Hz tone at 44.1 kHz reached the transcriber at 16 kHz with its RMS within 2%.
- **Tests.** `tests/test_server.py`, 10 s:
  - pages and static files;
  - hello and frames through to groups, events and `/api/state`, with timestamps on the server's clock;
  - a reconnect continuing the same segment, with resent frames dropped;
  - segments ending on a new stream, a long gap or a stop, and short gaps filled;
  - idle advancing;
  - `/api/describe` resolving names again;
  - saving at shutdown, then resuming with `--load`;
  - refused hellos, replaced connections (a frame on its way is not taken), `/api/finish`, the key (4403 after the
    handshake, redirects that stay on the server);
  - pauses and silent connected phones ending their segment; phone times that cannot be right; the `/api/state` cache;
    a transcription error clearing;
  - the dashboard mount (a fake, and the real `yus.web.dashboard`);
  - `yus-replay` against a real uvicorn server;
  - `node --check` of the page scripts, and the downsampler;
  - the commentate page's script in node with a stub DOM: capture times across a busy page and a pause, the pause message,
    reconnecting at once from a silent socket, resuming audio on `touchend`/`click`, stopping on 1003.

  With `YUS_SLOW_TESTS=1` and Chrome installed, it also drives the real commentate page in headless Chrome. Chrome's fake
  capture device hangs `getUserMedia` on macOS, so the page gets a synthetic microphone. The test covers a touch tap to
  resume (it fails with the old `pointerdown`-only listener), live audio, a dropped connection and reconnect, a suspend that
  ends the segment and a tap that starts the next at the right time, and stop.

## Limitations

- **Not tried on phones.** The commentate page was tried only in desktop headless Chrome, with a synthetic microphone; it
  has not been tried in iOS Safari or Android Chrome. iOS stops capturing when Safari goes to the background or the screen
  locks. The page reports silence, but cannot prevent it. If iOS also stops the page's scripts, the page cannot send
  `pause`, and the server ends that commentator's segment only after 2 minutes without a frame.
- **Whisper not run through the server.** The live latency and accuracy in
  [live_transcription.md](live_transcription.md#accuracy-and-latency) apply: words are committed about 6 s after they are
  spoken.
- **One GPU, taking turns.** Decodes are serialized. One commentator kept an M3 Pro busy about 50% of the time (1.4 s per 3 s
  decode). Two will nearly fill it, and with more, each transcriber decodes less often and falls further behind. Watch
  `backlog_s` and the transcript lag.
- **Long outages.**
  - After 2 minutes without a frame, connected or not, a commentator's segment ends and they are advanced to the current
    time. The server cannot tell a phone that paused without saying so from a network outage, so it does not do this
    sooner. Audio resent later starts a new segment, and its words can come before that advance, which can unsettle events
    (the session's "progress is trusted").
  - Past 5 minutes offline, the phone drops its oldest audio.
- **Clocks.**
  - The phone's clock offset is measured once per connection, without correcting for network delay (tens of ms on a LAN).
  - The capture time comes from `Date.now()` at the first frame and after each pause. The audio clock's drift against it
    is not corrected (usually well under 1 s an hour); an audio clock slower than the wall clock by more than 1 s in all
    is taken for a pause, which pads about 1 s of silence.
  - Idle commentators are advanced on the server's wall clock. With `yus-replay --speed` above 1, audio time runs ahead of
    it, which is harmless.
- **Names and access.**
  - Two people who enter the same name are one commentator, and the newer connection replaces the older.
  - The only access control is the optional shared `--key`, and anyone with the link can describe players or finish the game.
- **Echo.** `echoCancellation: false` is requested as asked. Browsers may still apply their own noise suppression and
  gain control, and that is not measured.
