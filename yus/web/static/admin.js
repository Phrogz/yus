// Admin page: identify unresolved names (POST /api/describe), watch commentators, finish the game.
"use strict";

const $ = (id) => document.getElementById(id);
let game = null;
let shown = null; // version of the unresolved table on screen

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

function option(value, text) {
  const node = el("option", text);
  node.value = value;
  return node;
}

function say(text, error) {
  $("message").textContent = text;
  $("message").className = error ? "error" : "muted";
}

function team(name) {
  return game.teams.find((t) => t.name === name || t.names.includes(name));
}

// Candidates for a name: players nobody has named yet first, then the rest of the roster.
function playerSelect(teamName) {
  const select = el("select");
  select.append(option("", "Who is it?"));
  const roster = team(teamName) ? team(teamName).players : [];
  const unmentioned = (game.unmentioned[teamName] || []).filter((p) => roster.includes(p));
  if (unmentioned.length) {
    const group = el("optgroup");
    group.label = "Not named yet";
    group.append(...unmentioned.map((p) => option(p, p)));
    select.append(group);
  }
  const group = el("optgroup");
  group.label = "Roster";
  group.append(...roster.filter((p) => !unmentioned.includes(p)).map((p) => option(p, p)));
  select.append(group);
  return select;
}

async function describe(body) {
  const response = await fetch("/api/describe", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || response.statusText);
  return result.description;
}

function renderUnresolved() {
  const rows = game.unresolved.map((u) => {
    const tr = el("tr");
    const select = playerSelect(u.team);
    const button = el("button", "Assign");
    button.type = "button";
    button.onclick = async () => {
      if (!select.value) return say("Pick a player first.", true);
      button.disabled = true;
      try {
        const d = await describe({ team: u.team, descriptions: [u.name], player: select.value });
        say(`"${u.name}" is now ${d.player}.`);
        shown = null;
        refresh();
      } catch (error) {
        say(error.message, true);
        button.disabled = false;
      }
    };
    const cell = el("td");
    cell.append(select);
    const action = el("td");
    action.append(button);
    tr.append(el("td", u.team), el("td", u.name), el("td", u.mentions), cell, action);
    return tr;
  });
  if (!rows.length) {
    const tr = el("tr");
    const td = el("td", "None", "muted");
    td.colSpan = 5;
    tr.append(td);
    rows.push(tr);
  }
  $("unresolved").replaceChildren(...rows);
}

function renderCommentators() {
  $("commentators").replaceChildren(...game.commentators.map((c) => {
    const tr = el("tr");
    const status = c.error ? "error: " + c.error : c.live ? "live" : c.connected ? "connected" : "offline";
    const audio = `${Math.round(c.received_s)} s` + (c.backlog_s > 1 ? ` (${c.backlog_s} s behind)` : "");
    tr.append(el("td", c.name), el("td", c.focus_team || "both"), el("td", status, c.error ? "error" : ""), el("td", c.groups), el("td", audio));
    return tr;
  }));
}

function renderDescriptions() {
  $("descriptions").replaceChildren(...game.descriptions.map((d) => {
    const who = d.player || `unknown (${d.label || d.descriptions[0]})`;
    return el("li", `${d.team}: ${d.descriptions.join(", ")} = ${who}` + (d.commentator ? ` (for ${d.commentator})` : ""));
  }));
}

function fillForm() {
  const teamSelect = $("d-team");
  if (!teamSelect.options.length) {
    teamSelect.append(...game.teams.map((t) => option(t.name, t.name)));
    teamSelect.onchange = fillPlayers;
    fillPlayers();
  }
  const commentators = $("d-commentator");
  const known = Array.from(commentators.options).map((o) => o.value);
  for (const c of game.commentators) if (!known.includes(c.name)) commentators.append(option(c.name, c.name));
}

function fillPlayers() {
  const players = $("d-player");
  players.replaceChildren(option("", "Unknown for now"), ...(team($("d-team").value) || { players: [] }).players.map((p) => option(p, p)));
}

$("describe").addEventListener("submit", async (event) => {
  event.preventDefault();
  const descriptions = $("d-descriptions").value.split(",").map((s) => s.trim()).filter(Boolean);
  if (!descriptions.length) return say("Enter at least one description.", true);
  try {
    const d = await describe({
      team: $("d-team").value, descriptions, player: $("d-player").value || null,
      label: $("d-label").value.trim() || null, commentator: $("d-commentator").value || null,
    });
    say(`Recorded: ${d.descriptions.join(", ")} = ${d.player || d.label || d.descriptions[0]}.`);
    $("d-descriptions").value = $("d-label").value = "";
    shown = null;
    refresh();
  } catch (error) {
    say(error.message, true);
  }
});

$("finish").addEventListener("click", async () => {
  if (!confirm("Finish the game? Commentators can't add anything after this.")) return;
  $("finish").disabled = true;
  try {
    const response = await fetch("/api/finish", { method: "POST" });
    const result = await response.json();
    say("Finished: " + result.summary);
  } catch (error) {
    say("Could not finish: " + error.message, true);
    $("finish").disabled = false;
  }
  refresh();
});

async function refresh() {
  try {
    const response = await fetch("/api/state?events=0");
    game = await response.json();
  } catch (error) {
    return say("Server unreachable", true);
  }
  $("summary").textContent = (game.finished ? "Final. " : "") + game.summary;
  $("finish").disabled = game.finished;
  // Rebuilding the table would reset a half-made choice, so only when the game changed and no choice is pending.
  const choosing = Array.from(document.querySelectorAll("#unresolved select")).some((s) => s.value);
  if (game.version !== shown && !choosing) {
    renderUnresolved();
    renderDescriptions();
    shown = game.version;
  }
  renderCommentators();
  fillForm();
}

refresh();
setInterval(refresh, 3000);
