// Game page: the score, commentators and latest events, from /api/state every 2 seconds.
"use strict";

const $ = (id) => document.getElementById(id);

function li(parts, className) {
  const item = document.createElement("li");
  for (const [text, cls] of parts) {
    const span = document.createElement("span");
    span.textContent = text;
    if (cls) span.className = cls;
    item.append(span);
  }
  if (className) item.className = className;
  return item;
}

function commentatorLine(c) {
  const dot = document.createElement("span");
  dot.className = "dot" + (c.live ? " live" : c.connected ? " on" : "");
  const parts = [[c.name, ""], [c.focus_team ? ` (${c.focus_team})` : "", "muted"], [` - ${c.groups} groups`, "muted"]];
  if (c.backlog_s > 2) parts.push([` - transcription ${c.backlog_s} s behind`, "error"]);
  if (c.error) parts.push([` - ${c.error}`, "error"]);
  const item = li(parts);
  item.prepend(dot);
  return item;
}

function render(game) {
  $("score").textContent = Object.entries(game.score).map(([team, goals]) => `${team} ${goals}`).join(" - ") || "-";
  $("summary").textContent = game.finished ? "Final. " + game.summary : game.summary;
  $("when").textContent = new Date(game.when).toLocaleString();
  const commentators = game.commentators.map(commentatorLine);
  $("commentators").replaceChildren(...(commentators.length ? commentators : [li([["None yet", "muted"]])]));
  const events = game.events.slice().reverse().map((e) => li([[e.clock, "time"], [e.text, ""]], e.provisional ? "provisional" : ""));
  $("events").replaceChildren(...(events.length ? events : [li([["None yet", "muted"]])]));
}

async function refresh() {
  try {
    const response = await fetch("/api/state?events=15");
    const game = await response.json();
    render(game);
  } catch (e) {
    $("summary").textContent = "Server unreachable";
  }
}

refresh();
setInterval(refresh, 2000);
