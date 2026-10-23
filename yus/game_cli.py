"""yus-game: process the recordings of one game afterwards, from one or more commentators, into one official event stream and
its stats: a game directory that GameSession.load and `yus-serve --load` open, an HTML report, and CSV tables.

yus-game --team white.json --team dark.json [--descriptions game-descriptions.json] \
    --commentator "Gavin Kistner=20250114T2030-0700.ogg" [--commentator "Sam=sam.transcript.json@-12:dark" ...] \
    [--game-dir DIR] [--html report.html] [--csv-dir DIR]

Each commentator is NAME=PATH[@OFFSET][:FOCUS]. PATH is a recording, transcribed by yus-transcribe, or a yus Transcript JSON.
OFFSET is seconds added to that commentator's times; merging estimates what remains (up to 20 s). FOCUS is the team they follow,
whose events they win conflicts on. The rest is what GameSession does live: EventExtractor, PlayerResolver with the descriptions,
merging (two or more commentators) and compute_stats. See docs/postgame.md.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import html
import json
import math
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unicodedata

import pandas as pd
import pydantic

import yus
from yus.processing.event_unification import GameDescriptions, PlayerResolver
from yus.processing.stats import GameStats
from yus.processing.stats.compute import SCORE_PREFIX
from yus.processing.transcription import transcribe as tr
from yus.session import GameSession, GameSnapshot
from yus.web.server import event_text

SPORT = "ultimate/indoor"
TOLERANCE = 3.0  # seconds: merge_streams's default, the most two reports of one action are apart


class Source(pydantic.BaseModel):
    """One --commentator: who, their recording or transcript, seconds to add to their times, and the team they follow."""

    name: str
    path: pathlib.Path
    offset: float | None = pydantic.Field(None, description="Seconds added to this commentator's times before merging.")
    focus: str | None = pydantic.Field(None, description="The team this commentator follows (any of its names).")

    @property
    def audio(self) -> bool:
        """Whether the path is a recording to transcribe, not a transcript JSON."""
        return self.path.suffix.lower() != ".json"


def parse_source(text: str, teams: list[yus.Team]) -> Source:
    """NAME=PATH[@OFFSET][:FOCUS] as a Source; ValueError if malformed. A PATH that exists is taken whole, "@" and ":" included."""
    name, equals, rest = text.partition("=")
    if not equals or not name.strip() or not rest:
        raise ValueError(f"{text!r} is not NAME=PATH[@OFFSET][:FOCUS]")
    path, offset, focus, seconds = rest, None, None, ""
    if not pathlib.Path(path).exists() and ":" in path:
        path, _, focus = path.rpartition(":")
    if not pathlib.Path(path).exists() and "@" in path:
        path, _, seconds = path.rpartition("@")
        try:
            offset = float(seconds)
        except ValueError:
            offset = math.nan
    bad_focus = focus is not None and PlayerResolver(teams).team_index(focus) is None
    bad_offset = offset is not None and not math.isfinite(offset)
    if not pathlib.Path(path).is_file():
        raise ValueError(f"{text!r}: no file {rest if bad_focus or bad_offset else path}")
    if bad_focus:
        raise ValueError(f"{text!r}: no team is called {focus!r}; teams: {[team.names for team in teams]}")
    if bad_offset:
        raise ValueError(f"{text!r}: the offset {seconds!r} is not a number of seconds")
    return Source(name=name.strip(), path=pathlib.Path(path), offset=offset, focus=focus)


def recording_start(path: pathlib.Path) -> dt.datetime | None:
    """When a recording started, as yus-transcribe finds it: its metadata, else a time in its name; None if neither says."""
    found = tr.recording_start_from_metadata(path)
    return found[0] if found else tr.recording_start_from_filename(path)


def transcript_path(recording: pathlib.Path, stop: float | None = None) -> pathlib.Path:
    """Where a recording's transcript is kept: beside it, as yus-transcribe writes it (with `stop`, .stopS.transcript.json)."""
    return recording.with_suffix(".transcript.json" if stop is None else f".stop{stop:g}.transcript.json")


def load_transcript(path: pathlib.Path) -> yus.Transcript:
    """A yus Transcript JSON. ValueError if the file is not one (no `groups`: an event stream, a team file) or has no words."""
    try:
        text = path.read_text()
        data = json.loads(text)
    except (OSError, ValueError) as error:
        raise ValueError(f"could not read {path}: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("groups"), list):
        raise ValueError(f"{path} is not a yus transcript: it has no groups")
    transcript = yus.Transcript.model_validate_json(text)
    if not transcript.words:
        raise ValueError(f"{path} has no words: leave this commentator out")
    return transcript


def transcribe(
    audio: pathlib.Path,
    team_files: list[pathlib.Path],
    start: dt.datetime,
    keep: pathlib.Path | None = None,
    *,
    asr: str = "auto",
    model: str | None = None,
    stop: float | None = None,
) -> yus.Transcript:
    """The recording transcribed by yus-transcribe, its words timed from `start`, also written to `keep`. It runs in its own process,
    which gives Whisper's memory back when it is done. `stop`: decode only this many seconds."""
    with tempfile.TemporaryDirectory(prefix="yus-game-") as directory:
        output = pathlib.Path(directory) / "transcript.json"
        command = [sys.executable, "-m", "yus.processing.transcription.transcribe", str(audio), "--output", str(output), "--recording-start", start.isoformat(), "--backend", asr]
        command += [arg for path in team_files for arg in ("--team", str(path))]
        command += ["--model", model] if model else []
        command += ["--stop", f"{stop:g}"] if stop is not None else []
        try:
            subprocess.run(command, check=True)
        except subprocess.CalledProcessError as error:
            raise SystemExit(f"Error: yus-transcribe failed on {audio} (exit status {error.returncode})") from error
        if keep is not None:
            try:
                shutil.copyfile(output, part := keep.with_name(keep.name + ".part"))
                part.replace(keep)
            except OSError as error:
                print(f"Warning: could not keep the transcript as {keep}: {error}", file=sys.stderr)
        return load_transcript(output)


def shifted(transcript: yus.Transcript, seconds: float) -> yus.Transcript:
    """A copy of the transcript with every word `seconds` later."""
    moved = yus.Transcript.model_validate(transcript.model_dump())
    for group in moved.groups:
        for interpretation in group.interpretations:
            for word in interpretation.words:
                word.start += dt.timedelta(seconds=seconds)
    return moved


def first_word(transcript: yus.Transcript) -> dt.datetime | None:
    return next((group.words[0].start for group in transcript.groups if group.words), None)


def saved_transcript(source: Source, stop: float | None = None, again: bool = False) -> yus.Transcript | None:
    """The source's transcript if it needs no transcribing: its JSON, or the one kept beside its recording (unless `again`).
    ValueError for a file that is not a transcript."""
    if not source.audio:
        return load_transcript(source.path)
    kept = transcript_path(source.path, stop)
    return load_transcript(kept) if kept.exists() and not again else None


def game_start(source: Source, transcript: yus.Transcript | None) -> dt.datetime | None:
    """When the first commentator's record starts, which names the game: their recording's start, else their first word, moved by
    their offset; None while that is not known (a recording without a start, not transcribed yet)."""
    start = (recording_start(source.path) if source.audio else None) or (first_word(transcript) if transcript is not None else None)
    return start + dt.timedelta(seconds=source.offset) if start is not None and source.offset else start


def read_transcripts(
    sources: list[Source],
    saved: list[yus.Transcript | None],
    team_files: list[pathlib.Path],
    *,
    asr: str = "auto",
    model: str | None = None,
    stop: float | None = None,
) -> list[yus.Transcript]:
    """Each source's transcript (`saved`, else its recording transcribed and kept beside it), its times moved by its offset. A
    recording is timed from its start (metadata or file name), else from the first commentator's: their recording's start, or
    their transcript's first word."""
    transcripts = []
    reference: dt.datetime | None = None
    for source, transcript in zip(sources, saved):
        start = recording_start(source.path) if source.audio else None
        if transcript is not None:
            if source.audio:
                print(f"{source.name}: using {transcript_path(source.path, stop)} (--retranscribe to transcribe {source.path.name} again)", file=sys.stderr)
        else:
            if start is None:
                start = reference or dt.datetime.now().replace(microsecond=0)
                print(f"{source.name}: {source.path.name} does not say when it started; taken as {start:%Y-%m-%d %H:%M:%S} (give @OFFSET if not)", file=sys.stderr)
            print(f"Transcribing {source.name}: {source.path}", file=sys.stderr, flush=True)
            try:
                transcript = transcribe(source.path, team_files, start, transcript_path(source.path, stop), asr=asr, model=model, stop=stop)
            except ValueError as error:
                raise SystemExit(f"Error: {error}") from error
        reference = reference or start or first_word(transcript)
        transcripts.append(shifted(transcript, source.offset) if source.offset else transcript)
    return transcripts


def process(game: yus.Game, descriptions: GameDescriptions | None, sources: list[Source], transcripts: list[yus.Transcript], directory: pathlib.Path | None = None) -> GameSession:
    """The finished session of the game, every commentator's transcript fed at once (as `replay(speed=0)` would), saved to `directory`.
    Raises ValueError for a description or focus the teams don't allow, or word times both naive and with a UTC offset."""
    session = GameSession(game, descriptions, directory)
    for source in sources:
        session.add_commentator(source.name, source.focus)
    for source, transcript in zip(sources, transcripts):
        session.add_groups(source.name, transcript.groups)
    session.finish()
    if directory is not None:
        session.save()
    return session


# ---------------------------------------------------------------------------------------------------------------- for a person to fix


def wrong_team_names(snap: GameSnapshot) -> list[str]:
    """Names said for one team that nobody of it answers to (no player, no description), but one player of another team does
    ("tristan" said for black is white's Tristan Weber): the event's team is wrong, or the name needs a description. From each
    commentator's raw events (PlayerResolver.team_conflicts)."""
    resolver = PlayerResolver(snap.game.teams, snap.descriptions)
    forms: dict[tuple[str, str, str], collections.Counter[str]] = collections.defaultdict(collections.Counter)
    said: dict[tuple[str, str, str], set[str]] = collections.defaultdict(set)
    for c in snap.commentators:
        for conflict in resolver.team_conflicts(snap.raw[c.name], c.name):
            key = (conflict.team, conflict.roster_team, resolver.resolve(conflict.name, conflict.roster_team, c.name) or conflict.name)
            forms[key][conflict.name] += 1
            said[key].add(c.name)
    found = []
    for (team, roster_team, player), counts in sorted(forms.items(), key=lambda item: -item[1].total()):
        by = f", by {' and '.join(sorted(said[(team, roster_team, player)]))}" if len(snap.commentators) > 1 else ""
        found.append(f'"{counts.most_common(1)[0][0]}" ({counts.total()}x for {team}{by}) is {roster_team}\'s {player}')
    return found


def team_disagreements(snap: GameSnapshot, tolerance: float = TOLERANCE, gap: float = 15.0) -> list[str]:
    """Stretches of play that commentators put on different teams. Merging pairs only events of one team, so both reports stay in
    the official stream: events of one kind, each from one commentator, within `tolerance` seconds of each other and of different
    teams, matched closest first. Matches less than `gap` seconds apart, with the same commentators and teams, form one stretch."""
    if snap.merge is None:
        return []
    events, start, names = snap.official.events, snap.stats.start, [c.name for c in snap.commentators]
    source = [next(k for k, index in enumerate(pair) if index is not None) if sum(index is not None for index in pair) == 1 else -1 for pair in snap.merge.pairs]
    stretches: list[list[tuple[int, int]]] = []
    for a, b in _team_matches(events, source, tolerance):
        last = stretches[-1][-1] if stretches else None
        if last and _sides(events, source, last) == _sides(events, source, (a, b)) and (events[min(a, b)].when - events[max(last)].when).total_seconds() < gap:
            stretches[-1].append((a, b))
        else:
            stretches.append([(a, b)])
    found = []
    for stretch in stretches:
        (a, b), last = stretch[0], stretch[-1]
        span = clock(events[min(a, b)].when, start) + (f"–{clock(events[max(last)].when, start)}" if len(stretch) > 1 else "")
        (first, team), (second, other) = _sides(events, source, (a, b))
        kind = _plural(len(stretch), type(events[a]).__name__.lower())
        found.append(f"{span}: {kind} {names[first]} put on {team}, {names[second]} on {other} (e.g. {event_text(events[a])} / {event_text(events[b])})")
    return found


def _team_matches(events: list[yus.Event], source: list[int], tolerance: float) -> list[tuple[int, int]]:
    """(a, b): merged events from one commentator each (`source`, -1 for several), the first's commentator added first, of one kind
    and different teams, within `tolerance` seconds; closest first, each event in one match at most; in the order of the stream."""
    candidates = []
    for a, event in enumerate(events):
        for b in range(a + 1, len(events)):
            other = events[b]
            if (apart := (other.when - event.when).total_seconds()) > tolerance:
                break
            if (
                min(source[a], source[b]) >= 0
                and source[a] != source[b]
                and type(other).__name__ == type(event).__name__
                and getattr(other, "team", None) != getattr(event, "team", None)
            ):
                candidates.append((apart, a, b) if source[a] < source[b] else (apart, b, a))
    used: set[int] = set()
    matches = []
    for _, a, b in sorted(candidates):
        if a not in used and b not in used:
            used |= {a, b}
            matches.append((a, b))
    return sorted(matches, key=min)


def _sides(events: list[yus.Event], source: list[int], match: tuple[int, int]) -> tuple[tuple[int, str | None], ...]:
    return tuple((source[i], getattr(events[i], "team", None)) for i in match)


def clock(when: dt.datetime, start: dt.datetime | None) -> str:
    """Game time, e.g. "4:05" (the time of day without a start). A time with a UTC offset is made naive as compute_stats does: in
    its own zone, or this computer's for UTC."""
    if start is None:
        return f"{when:%H:%M:%S}"
    if when.utcoffset() is not None and start.utcoffset() is None:
        when = when.astimezone(when.tzinfo if when.utcoffset() else None).replace(tzinfo=None)
    seconds = round((when - start).total_seconds())
    sign, seconds = "-" if seconds < 0 else "", abs(seconds)
    return f"{sign}{seconds // 60}:{seconds % 60:02d}"


def report_lines(snap: GameSnapshot, sources: list[Source]) -> list[str]:
    """What the terminal shows: the score, each commentator, the merge, unresolved names and team conflicts."""
    lines = [snap.summary]
    for k, (c, source) in enumerate(zip(snap.commentators, sources)):
        notes = [f"{c.groups} groups", f"{len(snap.raw[c.name].events)} events"]
        if source.offset:
            notes.append(f"moved {source.offset:+g} s")
        if snap.merge is not None and k:
            notes.append(f"offset {snap.merge.offsets[k]:+.2f} s")
        if c.focus_team:
            notes.append(f"focus {c.focus_team}")
        lines.append(f"  {c.name}: {', '.join(notes)}")
    if snap.merge is not None:
        rules = collections.Counter(conflict.rule for conflict in snap.merge.conflicts)
        settled = ", ".join(f"{rule} {count}" for rule, count in rules.most_common())
        lines.append(f"Merged: {len(snap.official.events)} events; {len(snap.merge.conflicts)} fields settled between commentators" + (f" ({settled})" if settled else ""))
    if snap.unresolved:
        lines.append("Unresolved names (describe them in the descriptions file, then run again):")
        by_team: dict[str, list[str]] = collections.defaultdict(list)
        for team, name, count in snap.unresolved:
            by_team[team].append(f"{name} {count}x")
        for team, names in by_team.items():
            missing = snap.unmentioned.get(team) or []
            lines.append(f"  {team}: {', '.join(names)}" + (f" (not mentioned: {', '.join(missing)})" if missing else ""))
    if conflicts := wrong_team_names(snap) + team_disagreements(snap):
        lines.append("Team conflicts:")
        lines += [f"  {line}" for line in conflicts]
    return lines


# ---------------------------------------------------------------------------------------------------------------- report and tables


def write_csv(stats: GameStats, directory: pathlib.Path) -> list[pathlib.Path]:
    """Every stats table as DIRECTORY/<table>.csv, as `yus-stats --format csv` writes them."""
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, frame in stats.tables().items():
        frame.to_csv(path := directory / f"{name}.csv")
        paths.append(path)
    return paths


_STYLE = """
:root { --bg: #fff; --fg: #1d1d1f; --muted: #6e6e73; --line: #e3e3e8; --head: #f4f4f6; --warn: #a24a00; }
@media (prefers-color-scheme: dark) { :root { --bg: #18181b; --fg: #ececf0; --muted: #a0a0aa; --line: #34343a; --head: #232328; --warn: #ffb066; } }
body { margin: 0 auto; max-width: 72rem; padding: 1.5rem 1rem 3rem; font: 15px/1.45 system-ui, sans-serif; color: var(--fg); background: var(--bg); }
h1 { font-size: 1.8rem; margin: 0.2rem 0; font-variant-numeric: tabular-nums; } h2 { font-size: 1.15rem; margin: 2rem 0 0.6rem; }
h3 { font-size: 1rem; margin: 1.2rem 0 0.4rem; } .meta { color: var(--muted); margin: 0; }
.scroll { overflow-x: auto; } ul { padding-left: 1.2rem; } li { margin: 0.2rem 0; }
table { border-collapse: collapse; font-size: 0.85rem; font-variant-numeric: tabular-nums; }
th, td { padding: 0.25rem 0.6rem; border-bottom: 1px solid var(--line); text-align: right; white-space: nowrap; }
th { background: var(--head); font-weight: 600; } th:first-child, td:first-child, .text { text-align: left; } td.text { white-space: normal; }
.unknown { font-style: italic; color: var(--warn); } details { margin-top: 1rem; } summary { cursor: pointer; font-weight: 600; }
"""

_TEAM_ROWS = {
    "goals": "goals",
    "holds": "holds",
    "breaks": "breaks",
    "o_points": "points on offense",
    "possessions": "possessions",
    "throws": "throws",
    "completions": "completions",
    "completion_pct": "completion %",
    "turnovers": "turnovers",
    "ds": "Ds",
    "interceptions": "interceptions",
    "hucks": "hucks",
    "huck_completion_pct": "huck completion %",
    "wall_throws": "off the wall",
    "goals_per_possession": "goals per possession",
}
_PLAYER_COLUMNS = {
    "goals": "goals",
    "assists": "assists",
    "hockey_assists": "hockey assists",
    "throws": "throws",
    "completion_pct": "completion %",
    "catches": "catches",
    "drops_or_misses": "drops or misses",
    "turnovers": "turnovers",
    "ds": "Ds",
    "interceptions": "interceptions",
    "hucks": "hucks",
}


def report_html(snap: GameSnapshot, sources: list[Source]) -> str:
    """A standalone page: the score, the commentators, what to check, box scores, the points and every event."""
    stats, game = snap.stats, snap.game
    teams = stats.teams
    title = " vs ".join(teams) + f", {game.when:%Y-%m-%d %H:%M}"
    score = " – ".join(f"{_e(team)} <b>{stats.score.get(team, 0)}</b>" for team in teams)
    span = clock(snap.official.events[-1].when, stats.start) if snap.official.events else "0:00"
    parts = [
        f'<p class="meta">Indoor Ultimate · {game.when:%A %d %B %Y, %H:%M}</p><h1>{score}</h1>',
        f'<p class="meta">{len(snap.official.events)} events from {_plural(len(snap.commentators), "commentator")} · {_plural(len(stats.points), "point")}'
        f" · the last at {span}</p>",
        "<h2>Commentators</h2>",
        _commentators(snap, sources),
        _checks(snap),
        "<h2>Teams</h2>",
        _table([""] + teams, [[label] + [_number(stats.team_box.at[team, column]) for team in teams] for column, label in _TEAM_ROWS.items()]),
        "<h2>Players</h2>",
    ]
    for team in teams:
        parts.append(f"<h3>{_e(team)}</h3>{_players(stats, game, team)}")
    parts += ["<h2>Points</h2>", _points(stats), "<details><summary>Every event</summary>", _events(snap), "</details>"]
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_e(title)}</title><style>{_STYLE}</style></head>\n<body>\n" + "\n".join(parts) + "\n</body></html>\n"
    )


def _commentators(snap: GameSnapshot, sources: list[Source]) -> str:
    rows = []
    for k, (c, source) in enumerate(zip(snap.commentators, sources)):
        offset = (source.offset or 0.0) + (snap.merge.offsets[k] if snap.merge is not None else 0.0)
        rows.append([_e(c.name), _e(c.focus_team or "both"), _e(source.path.name), str(c.groups), str(len(snap.raw[c.name].events)), f"{offset:+.2f} s"])
    return _table(["commentator", "follows", "from", "groups", "events", "clock offset"], rows, text={1, 2})


def _checks(snap: GameSnapshot) -> str:
    items = []
    if snap.unresolved:
        by_team: dict[str, list[str]] = collections.defaultdict(list)
        for team, name, count in snap.unresolved:
            by_team[team].append(f'<span class="unknown">{_e(name)}</span> {count}x')
        teams = "".join(
            f"<li><b>{_e(team)}</b>: {', '.join(names)}" + (f". Not mentioned: {_e(', '.join(missing))}" if (missing := snap.unmentioned.get(team)) else "") + "</li>"
            for team, names in by_team.items()
        )
        items.append(f"<li>Unresolved names: describe them in the game's descriptions file, then run again.<ul>{teams}</ul></li>")
    items += [f"<li>Team conflict: {_e(line)}</li>" for line in wrong_team_names(snap) + team_disagreements(snap)]
    conflicts = snap.merge.conflicts if snap.merge is not None else []
    if conflicts:
        names = [c.name for c in snap.commentators]
        rows = [
            [
                clock(snap.official.events[conflict.event].when, snap.stats.start),
                _e(event_text(snap.official.events[conflict.event])),
                _e(conflict.field),
                _e("; ".join(f"{name}: {value}" for name, value in zip(names, conflict.values) if value is not None)),
                _e(str(conflict.chosen)),
                _e(conflict.rule),
            ]
            for conflict in conflicts
        ]
        table = _table(["time", "event", "field", "said", "kept", "rule"], rows, text={1, 3})
        items.append(f"<li><details><summary>{_plural(len(conflicts), 'field')} the commentators disagreed on</summary>{table}</details></li>")
    return "<h2>To check</h2><ul>" + ("".join(items) or "<li>Nothing: every name is a roster player and no team conflicts.</li>") + "</ul>"


def _players(stats: GameStats, game: yus.Game, team: str) -> str:
    box = stats.player_box
    if team not in box.index.get_level_values("team"):
        return '<p class="meta">No player named.</p>'
    rows = box.xs(team, level="team").sort_values(["goals", "assists", "throws"], ascending=False)
    roster = {player for t in game.teams if t.names and t.names[0] == team for player in t.players}
    return _table(
        ["player"] + list(_PLAYER_COLUMNS.values()),
        [
            [_e(player) if player in roster else f'<span class="unknown">{_e(player)}</span>'] + [_number(row[column]) for column in _PLAYER_COLUMNS]
            for player, row in rows.iterrows()
        ],
    )


def _points(stats: GameStats) -> str:
    teams, goals = stats.teams, stats.score_timeline.set_index("point")
    rows = []
    for point, row in stats.points.iterrows():
        scored = point in goals.index
        result = "" if pd.isna(row["hold"]) else "hold" if row["hold"] else "break"
        how = f"{_name(row['assist'])} → {_name(row['scorer'])}" if scored else "in play"
        running = "–".join(str(goals.at[point, SCORE_PREFIX + team]) for team in teams) if scored else ""
        rows.append(
            [
                str(point),
                clock(row["start"], stats.start),
                clock(row["end"], row["start"]),
                _e(_name(row["o_team"], "?")),
                _e(_name(row["scored_by"], "")) + (" (suspect)" if row["suspect"] else ""),
                result,
                _e(how),
                running,
                str(row["throws"]),
                str(row["turnovers"]),
            ]
        )
    return _table(["point", "start", "length", "offense", "scored by", "", "assist → goal", "score", "throws", "turnovers"], rows, text={3, 4, 5, 6})


def _events(snap: GameSnapshot) -> str:
    stats, names = snap.stats, [c.name for c in snap.commentators]
    point = {index: p for table in stats.RAW_TABLES for index, p in getattr(stats, table)["point"].items()}
    notes: dict[int, list[str]] = collections.defaultdict(list)
    for conflict in snap.merge.conflicts if snap.merge is not None else []:
        notes[conflict.event].append(f"{conflict.field} ({conflict.rule})")
    rows = []
    for i, event in enumerate(snap.official.events):
        row = [str(i + 1), clock(event.when, stats.start), str(point.get(i, "")), _e(getattr(event, "team", "") or "?"), _e(event_text(event))]
        if snap.merge is not None:
            row += [_e(", ".join(name for name, index in zip(names, snap.merge.pairs[i]) if index is not None)), _e(", ".join(notes[i]))]
        rows.append(row)
    header = ["#", "time", "point", "team", "event"] + (["reported by", "disagreed on"] if snap.merge is not None else [])
    return _table(header, rows, text={3, 4, 5, 6})


def _table(header: list[str], rows: list[list[str]], text: set[int] | None = None) -> str:
    """An HTML table of cells that are HTML already; columns in `text` wrap and align left."""
    text = text or set()
    head = "".join(f"<th{' class=text' if i in text else ''}>{_e(h)}</th>" for i, h in enumerate(header))
    body = "".join("<tr>" + "".join(f"<td{' class=text' if i in text else ''}>{cell}</td>" for i, cell in enumerate(row)) + "</tr>\n" for row in rows)
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>\n{body}</tbody></table></div>'


def _number(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)) or value is pd.NA:
        return "–"
    return f"{value:.3g}" if isinstance(value, float) and not float(value).is_integer() else str(int(value)) if isinstance(value, (int, float)) else _e(str(value))


def _name(value: object, unknown: str = "someone") -> str:
    """A name from a table, which may be None or NaN."""
    return value if isinstance(value, str) and value else unknown


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'s' * (count != 1)}"


def _e(text: str) -> str:
    return html.escape(text, quote=False)


# ---------------------------------------------------------------------------------------------------------------- command line


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yus-game",
        description="Process one game's recordings afterwards: transcribe, extract, resolve, merge the commentators, and write the stats.",
    )
    parser.add_argument("--team", dest="teams", action="append", type=pathlib.Path, default=[], help="Team JSON file (repeat for each team).")
    parser.add_argument("--descriptions", type=pathlib.Path, help="The game's descriptions JSON (who commentators' descriptions mean).")
    parser.add_argument(
        "--commentator",
        dest="commentators",
        action="append",
        default=[],
        metavar="NAME=PATH[@OFFSET][:FOCUS]",
        help="A commentator: their recording (transcribed) or yus transcript JSON; OFFSET seconds added to their times (merging estimates up to 20 s more);"
        " FOCUS the team they follow. Repeat for each; the first is the clock reference.",
    )
    parser.add_argument(
        "--game-dir", type=pathlib.Path, help="Directory for the game, as yus-serve --load opens it (default: games/<start of the first commentator's recording or words>)."
    )
    parser.add_argument("--html", type=pathlib.Path, help="HTML report (default: GAME_DIR/report.html).")
    parser.add_argument("--csv-dir", type=pathlib.Path, help="Directory for the stats tables as CSV (default: GAME_DIR/stats).")
    parser.add_argument("--force", action="store_true", help="Replace a game already saved in the game directory.")
    parser.add_argument("--asr", choices=tr.BACKENDS, default="auto", help="Whisper backend for recordings (default: auto, as yus-transcribe).")
    parser.add_argument("--model", help="Whisper model for recordings (default: yus-transcribe's).")
    parser.add_argument("--stop", type=float, help="Transcribe only this many seconds of each recording (a quick try).")
    parser.add_argument("--retranscribe", action="store_true", help="Transcribe recordings again, replacing the transcripts kept beside them.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if len(args.teams) < 2:
        parser.error("--team: give a file for each team (two or more)")
    if not args.commentators:
        parser.error("--commentator: give at least one, NAME=PATH")
    teams = tr.load_teams_from_files(args.teams)
    try:
        descriptions = GameDescriptions.model_validate_json(args.descriptions.read_text()) if args.descriptions else None
        PlayerResolver(teams, descriptions)
    except (OSError, ValueError) as error:
        raise SystemExit(f"Error: could not load {args.descriptions or 'the teams'}: {error}") from error
    try:
        sources = [parse_source(text, teams) for text in args.commentators]
    except ValueError as error:
        parser.error(f"--commentator {error}")
    if len(names := [source.name for source in sources]) != len(set(names)):
        parser.error(f"--commentator: two commentators have one name: {names}")
    try:
        saved = [saved_transcript(source, args.stop, args.retranscribe) for source in sources]
    except ValueError as error:
        raise SystemExit(f"Error: {error}") from error
    when = game_start(sources[0], saved[0])
    if args.game_dir is not None or when is not None:
        _check_free(args.game_dir or _default_dir(when), args.force)  # before transcribing

    transcripts = read_transcripts(sources, saved, args.teams, asr=args.asr, model=args.model, stop=args.stop)
    when = when or first_word(transcripts[0]) or dt.datetime.now().replace(microsecond=0)
    directory = args.game_dir or _default_dir(when)
    replacing = _check_free(directory, args.force)
    try:
        session = process(yus.Game(sport=SPORT, when=when, teams=teams), descriptions, sources, transcripts, directory)
    except ValueError as error:
        raise SystemExit(f"Error: {error}") from error
    if replacing:
        remove_stale(directory)
    snap = session.snapshot()

    report = args.html or directory / "report.html"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(report_html(snap, sources))
    tables = write_csv(snap.stats, args.csv_dir or directory / "stats")
    print("\n".join(report_lines(snap, sources)))
    print(f"Game: {directory} (view it: yus-serve --load {directory} --asr none)\nReport: {report}\nCSV: {tables[0].parent} ({len(tables)} tables)")
    return 0


def remove_stale(directory: pathlib.Path) -> list[pathlib.Path]:
    """Delete the transcripts/ and events/ files of commentators that the game saved in `directory` no longer has (left by the
    game it replaced); the files deleted."""
    saved = json.loads((directory / "session.json").read_text())
    keep = {_file_key(f"{entry['file']}.json") for entry in saved["commentators"]}
    stale = [path for folder in ("transcripts", "events") for path in sorted((directory / folder).glob("*.json")) if _file_key(path.name) not in keep]
    for path in stale:
        path.unlink()
    return stale


def _file_key(name: str) -> str:
    """File names that are one file on a disk that ignores case and Unicode normalization (macOS) have one key."""
    return unicodedata.normalize("NFC", name).casefold()


def _default_dir(when: dt.datetime) -> pathlib.Path:
    return pathlib.Path("games") / f"{when:%Y%m%dT%H%M%S}"


def _check_free(directory: pathlib.Path, force: bool) -> bool:
    """Whether `directory` holds a game, which `force` lets this run replace; SystemExit if it does without `force`."""
    if (held := (directory / "session.json").exists()) and not force:
        raise SystemExit(f"Error: {directory} already holds a game: pass --force to replace it, or another --game-dir")
    return held


if __name__ == "__main__":
    raise SystemExit(main())
