// Commentator page: stream the microphone to /ws/audio as 16 kHz PCM16 frames, and show what the server made of it.
// Frames are kept until the server acknowledges them, and resent after a reconnect.
"use strict";

const RATE = 16000;
const FRAME_SAMPLES = 1600; // 100 ms
const HEADER = 12; // uint32 sequence number, float64 capture time (ms since 1970), little-endian
const MAX_FRAMES = 3000; // 5 minutes kept for resending
const SEND_LIMIT = 512 * 1024; // bytes queued in the socket before waiting
const SILENT_MS = 8000; // no message for this long: reconnect
const MUTE_MS = 3000; // no audio for this long while live: warn

const $ = (id) => document.getElementById(id);
const ui = {
  name: $("name"), focus: $("focus"), toggle: $("toggle"), status: $("status"), level: $("level"),
  notice: $("notice"), transcript: $("transcript"), pending: $("pending"), events: $("events"), score: $("score"),
};

const state = {
  streamId: newId(),
  seq: 0, // next frame's sequence number
  frames: [], // frames not yet acknowledged: {seq, data}
  nextSend: 0, // first sequence number not yet sent on this socket
  acked: -1,
  dropped: 0,
  stopPending: false,
  live: false,
  captureBase: null, // capture time of the first sample since starting (ms since 1970)
  captured: 0, // samples captured since then
  lastFrame: 0, // when the microphone last gave a frame
  ws: null,
  welcomed: false,
  wantSocket: false,
  retries: 0,
  lastMessage: 0,
  audio: null, // {ctx, source, node, sink, stream}
  wakeLock: null,
  fatal: null, // why streaming stopped for good (the server refused it)
  problem: null, // why the microphone could not start
};

function newId() {
  if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
  return Array.from({ length: 4 }, () => Math.random().toString(16).slice(2, 10)).join("");
}

function load(key) {
  try { return localStorage.getItem(key) || ""; } catch (e) { return ""; }
}

function store(key, value) {
  try { localStorage.setItem(key, value); } catch (e) { /* private mode */ }
}

function setStatus(text, kind) {
  ui.status.textContent = text;
  ui.status.className = "status" + (kind ? " " + kind : "");
}

function showStatus() {
  if (state.fatal) return setStatus(state.fatal, "bad");
  if (state.problem && !state.live) return setStatus(state.problem, "bad");
  const audio = state.audio;
  if (state.live && audio && audio.ctx.state !== "running") return setStatus("Audio paused: tap anywhere to resume", "bad");
  if (state.live && Date.now() - state.lastFrame > MUTE_MS) return setStatus("No sound from the microphone", "bad");
  const waiting = (state.seq - 1 - state.acked) * (FRAME_SAMPLES / RATE);
  const open = state.ws && state.ws.readyState === WebSocket.OPEN && state.welcomed;
  if (state.live && open) setStatus(waiting > 1 ? `Live, catching up (${waiting.toFixed(0)} s to send)` : "Live", "ok");
  else if (state.live) setStatus(`Reconnecting... (${waiting.toFixed(0)} s of audio kept)`, "warn");
  else if (open) setStatus(waiting > 0.5 ? `Stopped, sending the rest (${waiting.toFixed(0)} s)` : "Stopped (connected)");
  else if (state.wantSocket) setStatus("Connecting...", "warn");
  else setStatus("Not started");
}

// ------------------------------------------------------------------ socket

function socketUrl() {
  return (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/audio";
}

function connect() {
  if (state.ws || !state.wantSocket) return;
  const ws = new WebSocket(socketUrl());
  ws.binaryType = "arraybuffer";
  state.ws = ws;
  state.welcomed = false;
  ws.onopen = () => {
    state.lastMessage = Date.now();
    ws.send(JSON.stringify({
      type: "hello", commentator: ui.name.value.trim(), focus_team: ui.focus.value || null,
      sample_rate: RATE, client_time: Date.now(), stream: state.streamId,
    }));
  };
  ws.onmessage = (event) => {
    state.lastMessage = Date.now();
    let message;
    try { message = JSON.parse(event.data); } catch (e) { return; }
    handle(message);
  };
  ws.onclose = (event) => {
    if (state.ws !== ws) return;
    state.ws = null;
    state.welcomed = false;
    if (event.code === 1008 || event.code === 4000 || event.code === 4403) {
      state.wantSocket = false;
      if (!state.fatal) state.fatal = event.reason || "The server refused the connection";
      stopAudio();
    }
    if (state.wantSocket) {
      const delay = Math.min(5000, 500 * 2 ** state.retries++);
      setTimeout(connect, delay);
    }
    showStatus();
  };
  ws.onerror = () => { /* onclose follows */ };
  showStatus();
}

function handle(message) {
  if (message.type === "welcome") {
    state.welcomed = true;
    state.retries = 0;
    state.fatal = null;
    acknowledge(message.ack);
    state.nextSend = state.acked + 1;
    ui.notice.textContent = message.focus_team ? `Following ${message.focus_team}.` : "";
    pump();
  } else if (message.type === "update") {
    acknowledge(message.ack);
    if ("transcript" in message) render(message);
    if (message.error) ui.notice.textContent = "Server: " + message.error;
  } else if (message.type === "error") {
    state.fatal = message.message;
  }
  showStatus();
}

function acknowledge(ack) {
  if (typeof ack !== "number" || ack <= state.acked) return;
  state.acked = ack;
  let drop = 0;
  while (drop < state.frames.length && state.frames[drop].seq <= ack) drop++;
  if (drop) state.frames.splice(0, drop);
}

// Send unsent frames in order while the socket keeps up, then a pending stop.
function pump() {
  const ws = state.ws;
  if (!ws || ws.readyState !== WebSocket.OPEN || !state.welcomed) return;
  for (const frame of state.frames) {
    if (frame.seq < state.nextSend) continue;
    if (ws.bufferedAmount > SEND_LIMIT) return;
    ws.send(frame.data);
    state.nextSend = frame.seq + 1;
  }
  if (state.stopPending && state.nextSend >= state.seq) {
    ws.send(JSON.stringify({ type: "stop" }));
    state.stopPending = false;
  }
}

setInterval(() => {
  if (state.ws && state.ws.readyState === WebSocket.OPEN && Date.now() - state.lastMessage > SILENT_MS) state.ws.close();
  pump();
  showStatus();
}, 500);

// ------------------------------------------------------------------ audio

function onFrame(data) {
  const pcm = new Int16Array(data.pcm);
  const now = Date.now();
  state.lastFrame = now;
  if (state.captureBase === null) {
    const latency = state.audio && state.audio.ctx.baseLatency ? state.audio.ctx.baseLatency * 1000 : 0;
    state.captureBase = now - (pcm.length / RATE) * 1000 - latency;
    state.captured = 0;
  }
  const buffer = new ArrayBuffer(HEADER + pcm.byteLength);
  const view = new DataView(buffer);
  view.setUint32(0, state.seq, true);
  view.setFloat64(4, state.captureBase + (state.captured / RATE) * 1000, true);
  new Int16Array(buffer, HEADER).set(pcm);
  state.captured += pcm.length;
  state.frames.push({ seq: state.seq++, data: buffer });
  if (state.frames.length > MAX_FRAMES) {
    state.frames.shift();
    state.dropped++;
    ui.notice.textContent = `No connection: the oldest audio is being dropped (${(state.dropped / 10).toFixed(0)} s so far).`;
  }
  ui.level.style.width = Math.min(100, Math.round(Math.sqrt(data.level) * 250)) + "%";
  pump();
}

async function start() {
  const name = ui.name.value.trim();
  if (!name) {
    ui.name.focus();
    return fail("Enter your name first");
  }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.AudioContext) {
    return fail("This browser can't record here: the page must be opened over HTTPS");
  }
  store("yus.name", name);
  store("yus.focus", ui.focus.value);
  state.fatal = null;
  const ctx = new AudioContext(); // in the click handler, as iOS requires
  ctx.resume();
  try {
    if (!ctx.audioWorklet) throw new Error("this browser has no AudioWorklet (iOS 14.5 or newer is needed)");
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, channelCount: 1 } });
    await ctx.audioWorklet.addModule("/static/pcm-worklet.js");
    const source = ctx.createMediaStreamSource(stream);
    const node = new AudioWorkletNode(ctx, "pcm16-downsampler", { processorOptions: { targetRate: RATE, frameSamples: FRAME_SAMPLES } });
    const sink = ctx.createGain();
    sink.gain.value = 0; // some browsers only run nodes that reach the destination
    node.port.onmessage = (event) => onFrame(event.data);
    source.connect(node);
    node.connect(sink).connect(ctx.destination);
    for (const track of stream.getAudioTracks()) {
      track.onended = () => { if (state.live) { ui.notice.textContent = "The microphone stopped (another app took it?)."; stop(); } };
    }
    state.audio = { ctx, source, node, sink, stream };
  } catch (error) {
    ctx.close();
    return fail("Microphone unavailable: " + (error.message || error.name || error));
  }
  state.problem = null;
  state.live = true;
  state.lastFrame = Date.now();
  state.captureBase = null;
  state.stopPending = false;
  state.wantSocket = true;
  ui.name.disabled = ui.focus.disabled = true;
  ui.toggle.textContent = "Stop";
  ui.toggle.classList.add("live");
  ui.notice.textContent = "";
  keepAwake();
  connect();
  showStatus();
}

function fail(problem) {
  state.problem = problem;
  showStatus();
}

function stopAudio() {
  const audio = state.audio;
  state.audio = null;
  if (audio) {
    audio.node.port.onmessage = null;
    audio.source.disconnect();
    audio.node.disconnect();
    for (const track of audio.stream.getTracks()) track.stop();
    audio.ctx.close();
  }
  state.live = false;
  ui.toggle.textContent = "Start";
  ui.toggle.classList.remove("live");
  ui.level.style.width = "0";
  releaseWakeLock();
}

function stop() {
  stopAudio();
  state.stopPending = true; // after the last frame: the server commits the last words
  pump();
  showStatus();
}

ui.toggle.addEventListener("click", () => (state.live ? stop() : start()));

// ------------------------------------------------------------------ screen

async function keepAwake() {
  if (!("wakeLock" in navigator)) {
    ui.notice.textContent = "Keep this page open with the screen on: recording stops when the phone sleeps.";
    return;
  }
  try {
    state.wakeLock = await navigator.wakeLock.request("screen");
  } catch (e) {
    ui.notice.textContent = "Keep the screen on: the wake lock was refused.";
  }
}

function releaseWakeLock() {
  if (state.wakeLock) state.wakeLock.release().catch(() => {});
  state.wakeLock = null;
}

// An audio context can be suspended (no user gesture, a phone call, the page in the background); a tap resumes it.
document.addEventListener("pointerdown", () => {
  if (state.audio && state.audio.ctx.state !== "running") state.audio.ctx.resume();
});

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && state.live) keepAwake();
  if (document.visibilityState === "visible" && state.audio && state.audio.ctx.state !== "running") state.audio.ctx.resume();
});

// ------------------------------------------------------------------ display

function item(time, text, provisional) {
  const li = document.createElement("li");
  const t = document.createElement("span");
  t.className = "time";
  t.textContent = time;
  li.append(t, document.createTextNode(text));
  if (provisional) li.className = "provisional";
  return li;
}

function render(message) {
  ui.transcript.replaceChildren(...message.transcript.map((g) => item(g.time, g.text, false)));
  ui.pending.textContent = message.pending || "";
  ui.events.replaceChildren(...message.events.slice().reverse().map((e) => item(e.clock, e.text, e.provisional)));
  ui.score.textContent = message.summary || "";
  if (message.finished) {
    state.fatal = "The game has finished";
    state.wantSocket = false;
    if (state.live) stopAudio();
  }
}

async function loadTeams() {
  try {
    const response = await fetch("/api/state?events=0");
    const game = await response.json();
    for (const team of game.teams) {
      const option = document.createElement("option");
      option.value = team.name;
      option.textContent = team.names.length > 1 ? `${team.name} (${team.names.slice(1).join(", ")})` : team.name;
      ui.focus.append(option);
    }
    ui.focus.value = load("yus.focus");
    ui.score.textContent = game.summary;
  } catch (e) {
    ui.notice.textContent = "Could not reach the server.";
  }
}

ui.name.value = load("yus.name");
loadTeams();
showStatus();
