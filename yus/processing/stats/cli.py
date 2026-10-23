"""yus-stats: print or write the stats tables of an event stream JSON file.

yus-stats game.events.json --team white.json --team dark.json --descriptions game-descriptions.json
yus-stats game.events.json --team white.json --team dark.json --format csv -o game-stats/
"""

from __future__ import annotations

import argparse
import html
import json
import pathlib
import sys

import pandas as pd
import pydantic

import yus
import yus.sports.ultimate.indoor  # noqa: F401  (registers the indoor event types that EventStream JSON names)
from yus.processing.event_unification import GameDescriptions, PlayerResolver
from yus.processing.stats.compute import GameStats, compute_stats

ALL_TABLES = GameStats.DERIVED_TABLES + GameStats.ON_FIELD_TABLES + GameStats.RAW_TABLES

_HTML_STYLE = """
body { font-family: system-ui, sans-serif; margin: 1.5rem; color: #1d1d1f; background: #fff; }
h1 { font-size: 1.4rem; } h2 { font-size: 1.1rem; margin-top: 2rem; }
table { border-collapse: collapse; font-size: 0.85rem; font-variant-numeric: tabular-nums; }
th, td { padding: 0.2rem 0.6rem; border-bottom: 1px solid #ddd; text-align: right; white-space: nowrap; }
th { background: #f4f4f6; }
@media (prefers-color-scheme: dark) { body { color: #eee; background: #18181b; } th { background: #26262b; } th, td { border-color: #3a3a40; } }
"""


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yus-stats", description="Compute game stats (box scores, points, possessions, ...) from an event stream JSON file.")
    parser.add_argument("events", type=pathlib.Path, help='EventStream JSON, events tagged with "__type__" (as yus-events writes it).')
    parser.add_argument("--team", dest="teams", action="append", type=pathlib.Path, default=[], help="Team JSON file; repeat per team. Resolves names to players.")
    parser.add_argument("--descriptions", type=pathlib.Path, help="Per-game descriptions JSON (GameDescriptions); needs --team.")
    parser.add_argument("--commentator", help="Whose stream this is, for commentator-specific descriptions.")
    parser.add_argument("--format", choices=["text", "csv", "html"], default="text", help="Output format (default: text).")
    parser.add_argument(
        "--tables", help=f"Comma-separated tables to output (default: the derived ones; on_field, lines, shifts if a team has subs). Choices: {', '.join(ALL_TABLES)}."
    )
    parser.add_argument("-o", "--output", type=pathlib.Path, help="Output file (text, html; default: stdout) or directory (csv; default: EVENTS-stats/ beside EVENTS).")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.descriptions and not args.teams:
        parser.error("--descriptions needs --team files to resolve against")
    tables = [name.strip() for name in args.tables.split(",") if name.strip()] if args.tables else []
    if unknown := [name for name in tables if name not in ALL_TABLES]:
        parser.error(f"unknown table(s) {', '.join(unknown)}; choices: {', '.join(ALL_TABLES)}")

    stream = _load(args.events, yus.EventStream)
    teams = [_load(path, yus.Team) for path in args.teams]
    if teams:
        resolver = PlayerResolver(teams, _load(args.descriptions, GameDescriptions) if args.descriptions else None)
        if unresolved := resolver.unresolved(stream, commentator=args.commentator):
            print("Unidentified players: " + ", ".join(f"{name!r} ({team}, {count}x)" for team, name, count in unresolved), file=sys.stderr)
        stream = resolver.resolve_stream(stream, commentator=args.commentator)

    stats = compute_stats(stream, teams or None)
    selected = stats.tables(tables or stats.derived())
    if args.format == "csv":
        directory = args.output or args.events.with_name(args.events.name.removesuffix(".json") + "-stats")
        directory.mkdir(parents=True, exist_ok=True)
        for name, frame in selected.items():
            frame.to_csv(directory / f"{name}.csv")
        print(f"{stats.summary()}\nWrote {len(selected)} tables to {directory}", file=sys.stderr)
        return 0
    text = format_html(stats, selected, title=args.events.name) if args.format == "html" else format_text(stats, selected)
    if args.output:
        args.output.write_text(text)
        print(f"{stats.summary()}\nWrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


def format_text(stats: GameStats, tables: dict[str, pd.DataFrame]) -> str:
    """The summary line, then each table under its name."""
    parts = [f"Score: {stats.summary()}\n"]
    with pd.option_context("display.width", 250, "display.max_columns", None, "display.max_rows", None, "display.max_colwidth", 40):
        for name, frame in tables.items():
            parts.append(f"\n== {name} ({len(frame)} rows) ==\n{frame.to_string() if len(frame) else '(none)'}\n")
    return "".join(parts)


def format_html(stats: GameStats, tables: dict[str, pd.DataFrame], title: str) -> str:
    """A standalone HTML page with the summary and each table."""
    body = "".join(f"<h2>{html.escape(name)}</h2>\n{frame.to_html(na_rep='', float_format=lambda x: f'{x:g}', border=0)}\n" for name, frame in tables.items())
    return (
        f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)} stats</title><style>{_HTML_STYLE}</style></head>\n"
        f"<body><h1>{html.escape(stats.summary())}</h1>\n{body}</body></html>\n"
    )


def _load[M: pydantic.BaseModel](path: pathlib.Path, model: type[M]) -> M:
    try:
        return model.model_validate(json.loads(path.read_text()))
    except (OSError, ValueError) as exc:  # pydantic.ValidationError and json.JSONDecodeError are ValueErrors
        raise SystemExit(f"Error: could not load {path} as {model.__name__}: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
