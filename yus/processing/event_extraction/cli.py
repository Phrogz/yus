"""yus-events: extract game events from a play-by-play transcript JSON file (as written by yus-transcribe).

yus-events game.transcript.json --team white.json --team dark.json [-o game.events.json] [--timeout 6] [--llm MODEL [--llm-url URL] [--llm-budget S]]
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import statistics
import sys

import pydantic

import yus
from yus.processing.event_extraction.extractor import EventExtractor
from yus.processing.event_extraction.llm import DEFAULT_BUDGET, DEFAULT_URL, AssistedExtractor, Call, LLMAssistant
from yus.sports import ultimate


def summary(stream: yus.EventStream, extractor: EventExtractor | AssistedExtractor) -> str:
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


def llm_summary(model: str, calls: list[Call], groups: int) -> str:
    """One line on what the LLM did: groups sent, outcomes, and how long it took."""
    outcomes = collections.Counter(call.outcome for call in calls)
    latencies = [call.latency for call in calls if call.latency is not None]
    took = f"; {statistics.median(latencies):.1f} s median, {max(latencies):.1f} s max" if latencies else ""
    shown = ", ".join(f"{count} {outcome}" for outcome, count in outcomes.most_common())
    return f"LLM {model}: sent {len(calls)} of {groups} groups" + (f" ({shown}{took})" if calls else "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract indoor Ultimate events from a play-by-play transcript JSON file.")
    parser.add_argument("transcript", type=pathlib.Path, help="transcript JSON (from yus-transcribe)")
    parser.add_argument("--team", type=pathlib.Path, action="append", default=[], help="team JSON file; one for each team (default: teams 'white' and 'black')")
    parser.add_argument("-o", "--output", type=pathlib.Path, help="output path (default: game.events.json for game.transcript.json, else <transcript stem>.events.json)")
    parser.add_argument("--timeout", type=float, help="finalize a throw after this many seconds without speech, as live extraction would (default: wait for the next words)")
    parser.add_argument("--llm", metavar="MODEL", help="also send groups the rules may have misread to this Ollama model (e.g. qwen2.5-coder:14b)")
    parser.add_argument("--llm-url", default=DEFAULT_URL, help=f"Ollama's address (default: {DEFAULT_URL})")
    parser.add_argument("--llm-budget", type=float, default=DEFAULT_BUDGET, help=f"seconds to wait for each answer before keeping the rules' events (default: {DEFAULT_BUDGET:g})")
    args = parser.parse_args(argv)
    if len(args.team) == 1:
        parser.error("--team: give a file for each team (two or more), or none")

    try:
        transcript = yus.Transcript.model_validate_json(args.transcript.read_text())
        teams = [yus.Team.model_validate_json(path.read_text()) for path in args.team]
    except (OSError, pydantic.ValidationError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    extractor: EventExtractor | AssistedExtractor = EventExtractor(teams or None, timeout=args.timeout)
    if args.llm:
        extractor = AssistedExtractor(extractor, LLMAssistant(args.llm, url=args.llm_url, budget=args.llm_budget), wait=True)
    for group in transcript.groups:
        extractor.feed(group)
    extractor.finish()
    stream = yus.EventStream(transcript=transcript, events=extractor.events)
    output = args.output or args.transcript.with_name(args.transcript.stem.removesuffix(".transcript") + ".events.json")
    output.write_text(json.dumps(stream.model_dump(mode="json"), indent=2) + "\n")
    print(f"Wrote {output}")
    print(summary(stream, extractor))
    if isinstance(extractor, AssistedExtractor):
        print(llm_summary(args.llm, extractor.calls, extractor.groups))
        errors = [call.error for call in extractor.calls if call.outcome == "error"]
        if errors:
            print(f"LLM errors ({len(errors)}), the rules' events kept: {errors[0]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
