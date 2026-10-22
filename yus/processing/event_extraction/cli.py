"""yus-events: extract game events from a play-by-play transcript JSON file (as written by yus-transcribe).

yus-events game.transcript.json --team white.json --team dark.json [-o game.events.json] [--timeout 6]
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

import pydantic

import yus
from yus.processing.event_extraction.extractor import EventExtractor
from yus.sports import ultimate


def summary(stream: yus.EventStream, extractor: EventExtractor) -> str:
    """A few lines on what was found: event counts, goals per team, and spoken identifications."""
    throws = [event for event in stream.events if isinstance(event, ultimate.Throw)]
    goals = collections.Counter(event.team for event in throws if event.scored)
    kinds = collections.Counter(type(event).__name__ for event in stream.events)
    others = ", ".join(f"{count} {kind.lower()}s" for kind, count in kinds.items() if kind != "Throw")
    lines = [
        f"{len(stream.events)} events: {len(throws)} throws ({sum(not t.completed for t in throws)} incomplete)" + (f", {others}" if others else ""),
        "Goals: " + (", ".join(f"{team or '?'} {count}" for team, count in goals.most_common()) or "none"),
    ]
    if extractor.associations:
        lines.append("Identified: " + "; ".join(f"{a.description} is {a.name}" + (f" ({a.team})" if a.team else "") for a in extractor.associations))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract indoor Ultimate events from a play-by-play transcript JSON file.")
    parser.add_argument("transcript", type=pathlib.Path, help="transcript JSON (from yus-transcribe)")
    parser.add_argument("--team", type=pathlib.Path, action="append", default=[], help="team JSON file; one for each team (default: teams 'white' and 'black')")
    parser.add_argument("-o", "--output", type=pathlib.Path, help="output path (default: <transcript stem>.events.json)")
    parser.add_argument("--timeout", type=float, help="finalize a throw after this many seconds without speech, as live extraction would (default: wait for the next words)")
    args = parser.parse_args(argv)
    if len(args.team) == 1:
        parser.error("--team: give a file for each team (two or more), or none")

    try:
        transcript = yus.Transcript.model_validate_json(args.transcript.read_text())
        teams = [yus.Team.model_validate_json(path.read_text()) for path in args.team]
    except (OSError, pydantic.ValidationError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    extractor = EventExtractor(teams or None, timeout=args.timeout)
    for group in transcript.groups:
        extractor.feed(group)
    extractor.finish()
    stream = yus.EventStream(transcript=transcript, events=extractor.events)
    output = args.output or args.transcript.with_name(args.transcript.stem + ".events.json")
    output.write_text(json.dumps(stream.model_dump(mode="json"), indent=2) + "\n")
    print(f"Wrote {output}")
    print(summary(stream, extractor))
    return 0


if __name__ == "__main__":
    sys.exit(main())
