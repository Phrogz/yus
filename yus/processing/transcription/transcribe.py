"""Script to transcribe an audio file into a timestamped transcript using Whisper.

Exposed as yus-transcribe command-line tool.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
from typing import Any, Iterable, cast

import yus
from yus.sports import ultimate
from yus.sports.ultimate import indoor


def load_terms(sport: str, extra_terms: Iterable[str], teams: list[yus.Team]) -> list[str]:
    base_terms: list[str] = []
    if sport in {"ultimate", "ultimate/indoor"}:
        if sport == "ultimate/indoor":
            base_terms = [t.phrase for t in indoor.terms]
        else:
            base_terms = [t.phrase for t in ultimate.terms]

    # Extract player names and aliases from teams
    player_terms: list[str] = []
    for team in teams:
        for player_name, info in team.players.items():
            player_terms.append(player_name)  # Full name: "Adam Federbusch"
            # Handle both list format and PlayerInfo dict format
            if isinstance(info, list):
                player_terms.extend(info)  # Simple list of nicknames
            else:  # PlayerInfo
                player_terms.extend(info.nicknames)  # Nicknames from PlayerInfo
            # Also add individual first/last names
            name_parts = player_name.split()
            if len(name_parts) > 1:
                player_terms.extend(name_parts)  # ["Adam", "Federbusch"]

    all_terms = base_terms + player_terms + list(extra_terms)
    deduped: list[str] = []
    seen: set[str] = set()
    for term in all_terms:
        t = term.strip()
        if not t:
            continue
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped


def phrases_from_file(path: pathlib.Path | None) -> list[str]:
    if not path:
        return []
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def load_replacements(sport: str, teams: list[yus.Team]) -> dict[str, str]:
    canonical_to_variants: dict[str, list[str]] = {}
    if sport in {"ultimate", "ultimate/indoor"}:
        if sport == "ultimate/indoor":
            canonical_to_variants = indoor.mondegreens
        else:
            canonical_to_variants = ultimate.mondegreens

    replacements: dict[str, str] = {}
    for canonical, variants in canonical_to_variants.items():
        replacements[canonical.lower()] = canonical
        for variant in variants:
            replacements[variant.lower()] = canonical

    # Add team-specific replacements for common misrecognitions from PlayerInfo
    for team in teams:
        for official_name, info in team.players.items():
            # Only PlayerInfo dicts have mondegreens; skip simple lists
            if not isinstance(info, list) and info.mondegreens:
                for mishearing in info.mondegreens:
                    replacements[mishearing.lower()] = official_name

    return replacements


def normalize_word(word: str, replacements: dict[str, str]) -> str:
    return replacements.get(word.lower(), word)


def normalize_text(text: str, replacements: dict[str, str]) -> str:
    return " ".join(normalize_word(token, replacements) for token in text.split())


def transcript_from_segments(
    segments: Iterable[Any],
    *,
    recording_start: dt.datetime,
    duration: float | None = None,
    show_progress: bool = True,
    show_text: bool = False,
    replacements: dict[str, str] | None = None,
    start_time: float | None = None,
    stop_time: float | None = None,
) -> yus.Transcript:
    transcript = yus.Transcript()
    last_reported: int | None = None
    replacements = replacements or {}
    for seg in segments:
        # Skip segments outside the requested time range
        if start_time is not None and float(seg.end) < start_time:
            continue
        if stop_time is not None and float(seg.start) >= stop_time:
            continue

        if show_progress and duration:
            percent = int(min(100, max(0, (float(seg.end) / duration) * 100)))
            if last_reported is None or percent >= last_reported + 5:
                last_reported = percent
                print(f"Processing audio: {percent}%", file=sys.stderr, flush=True)

        group = transcript.add_group()
        interp = group.add_interpretation(confidence=seg.avg_logprob if seg.avg_logprob is not None else 0.0)

        if getattr(seg, "words", None):
            for w in seg.words:
                start = recording_start + dt.timedelta(seconds=float(w.start))
                word_duration = dt.timedelta(seconds=float(w.end) - float(w.start))
                word_text = normalize_word(w.word, replacements)
                interp.add_word(word_text, start=start, duration=word_duration, confidence=float(w.probability or 0.0))
        else:
            # Fallback: no word timings provided; create a single word with segment text.
            start = recording_start + dt.timedelta(seconds=float(seg.start))
            segment_duration = dt.timedelta(seconds=float(seg.end) - float(seg.start))
            segment_text = normalize_text(seg.text.strip(), replacements)
            interp.add_word(segment_text, start=start, duration=segment_duration, confidence=float(seg.avg_logprob or 0.0))

        if show_text:
            text = normalize_text(seg.text.strip(), replacements)
            if text:
                print(text, flush=True)

    return transcript


def write_transcript_text(transcript: yus.Transcript, output_path: pathlib.Path) -> None:
    lines: list[str] = []
    for group in transcript.groups:
        interp = group.interpretations[0] if group.interpretations else None
        if not interp:
            continue
        start = interp.start.isoformat()
        end = (interp.start + interp.duration).isoformat()
        lines.append(f"{start}\t{end}\t{interp.transcript}")

    output_path.write_text("\n".join(lines) + "\n")


def write_transcript_json(transcript: yus.Transcript, output_path: pathlib.Path) -> None:
    # Exclude circular back-references:
    # - Interpretation.group (back-reference to TranscriptGroup)
    # - TranscriptGroup.transcript (back-reference to Transcript)
    exclude_spec: dict[str, Any] = {
        "groups": {
            "__all__": {
                "transcript": True,  # Exclude TranscriptGroup.transcript
                "interpretations": {
                    "__all__": {
                        "group": True,  # Exclude Interpretation.group
                    }
                },
            }
        }
    }
    output_path.write_text(json.dumps(transcript.model_dump(mode="json", exclude=exclude_spec), indent=2, sort_keys=True) + "\n")


def load_teams_from_files(team_files: list[pathlib.Path]) -> list[yus.Team]:
    teams: list[yus.Team] = []
    for path in team_files:
        try:
            data = json.loads(path.read_text())
            team = yus.Team(**data)
            teams.append(team)
        except Exception as exc:
            print(f"Warning: Failed to load team from {path}: {exc}", file=sys.stderr)
    return teams


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Transcribe an audio file to a timestamped transcript.")
    parser.add_argument("audio", type=pathlib.Path, help="Path to an audio file (wav/mp3/m4a/etc).")
    parser.add_argument("--sport", default="ultimate/indoor", help="Sport term set to bias toward (default: ultimate/indoor).")
    parser.add_argument("--model", default="large-v3", help="Whisper model size or path (default: large-v3).")
    parser.add_argument("--language", default="en", help="Language code (default: en).")
    parser.add_argument("--compute-type", default="float32", help="CTranslate2 compute type (default: float32).")
    parser.add_argument("--device", default="auto", help="Device to use: auto/cpu/cuda (default: auto).")
    parser.add_argument("--num-workers", type=int, default=1, help="Number of worker threads (default: 1).")
    parser.add_argument("--cpu-threads", type=int, default=8, help="Number of CPU threads (default: 8).")
    parser.add_argument("--team", dest="teams", action="append", type=pathlib.Path, default=[], help="Team JSON file (can be specified multiple times).")
    parser.add_argument("--terms-file", type=pathlib.Path, help="Optional file with one custom phrase per line.")
    parser.add_argument("--prompt", default="", help="Optional extra prompt text.")
    parser.add_argument("--output", type=pathlib.Path, help="Output path (default: <audio>.transcript.json).")
    parser.add_argument("--text", action="store_true", help="Write plain text instead of JSON.")
    parser.add_argument("--recording-start", default="now", help="ISO timestamp for recording start (default: now).")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output and output location printing.")
    parser.add_argument("--print-transcript", action="store_true", help="Print transcript text to stdout as it is produced.")
    parser.add_argument("--start", type=float, help="Start time in seconds.")
    parser.add_argument("--stop", type=float, help="Stop time in seconds.")
    parser.add_argument(
        "--no-vad",
        action="store_false",
        dest="vad",
        default=True,
        help="Disable Voice Activity Detection (VAD); enabled by default to filter background noise.",
    )
    return parser


def parse_recording_start(value: str) -> dt.datetime:
    if value == "now":
        return dt.datetime.now(dt.timezone.utc)
    return dt.datetime.fromisoformat(value)


def format_bytes(size: int | None) -> str:
    if size is None:
        return ""
    size_f = float(size)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_f < 1024:
            return f"{size_f:.1f} {unit}"
        size_f /= 1024
    return f"{size_f:.1f} PB"


def resolve_hf_repo_id(model: str) -> str | None:
    if pathlib.Path(model).exists():
        return None
    if "/" in model:
        return model
    return f"Systran/faster-whisper-{model}"


def estimate_repo_size(repo_id: str) -> int | None:
    try:
        from huggingface_hub import model_info
    except Exception:
        return None

    try:
        info = model_info(repo_id)
    except Exception:
        return None

    total = 0
    has_size = False
    for sibling in info.siblings or []:
        if sibling.size is not None:
            total += sibling.size
            has_size = True
    return total if has_size else None


def ensure_model_downloaded(repo_id: str) -> None:
    try:
        from huggingface_hub import snapshot_download as hf_snapshot_download  # type: ignore[reportUnknownVariableType]
        from huggingface_hub import try_to_load_from_cache as hf_try_to_load  # type: ignore[reportUnknownVariableType]
        from huggingface_hub.constants import HUGGINGFACE_HUB_CACHE  # type: ignore[reportUnknownVariableType]
    except Exception:
        return

    snapshot_download = cast(Any, hf_snapshot_download)
    try_to_load = cast(Any, hf_try_to_load)

    # Check if already cached
    try:
        cache_path = try_to_load(repo_id, "model.bin", cache_dir=HUGGINGFACE_HUB_CACHE)
        if cache_path is not None:
            return  # Already downloaded, skip message
    except Exception:
        pass  # Not cached, continue with download

    size = estimate_repo_size(repo_id)
    size_str = format_bytes(size)
    msg = f"Downloading model {repo_id}"
    if size_str:
        msg += f" ({size_str})"
    msg += "..."
    print(msg, file=sys.stderr, flush=True)
    snapshot_download(repo_id=repo_id)
    print("Model ready.", file=sys.stderr, flush=True)


def resolve_device(device: str) -> str:
    """Resolve device: auto will use cuda if available, otherwise cpu."""
    if device != "auto":
        return device
    try:
        import torch  # type: ignore[import-not-found]

        device = "cuda" if torch.cuda.is_available() else "cpu"  # type: ignore[reportUnknownMemberType]
        if device == "cuda":
            print(f"CUDA detected. Using GPU: {torch.cuda.get_device_name(0)}", file=sys.stderr, flush=True)  # type: ignore[reportUnknownMemberType]
    except Exception:
        device = "cpu"
    return device


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    try:
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - runtime error reporting only
        raise SystemExit("Missing dependency 'faster-whisper'. Install it with: uv sync\nAlso ensure ffmpeg is installed: brew install ffmpeg") from exc

    recording_start = parse_recording_start(args.recording_start)
    teams = load_teams_from_files(args.teams)
    extra_terms = phrases_from_file(args.terms_file)
    terms = load_terms(args.sport, extra_terms, teams)
    prompt = " ".join([args.prompt] + terms).strip()
    replacements = load_replacements(args.sport, teams)

    repo_id = resolve_hf_repo_id(args.model)
    if repo_id:
        try:
            ensure_model_downloaded(repo_id)
        except Exception as exc:  # pragma: no cover - best-effort download hinting
            print(f"Warning: model pre-download failed ({exc}). Will try during load.", file=sys.stderr, flush=True)

    # Resolve device: auto will use cuda if available, otherwise cpu
    device = resolve_device(args.device)

    # Build WhisperModel kwargs
    model_kwargs: dict[str, Any] = {"compute_type": args.compute_type, "device": device, "num_workers": args.num_workers}
    if args.cpu_threads:
        model_kwargs["cpu_threads"] = args.cpu_threads

    model = cast(Any, WhisperModel(args.model, **model_kwargs))  # type: ignore[reportUnknownArgumentType]

    # Build transcribe kwargs
    transcribe_kwargs: dict[str, Any] = {
        "language": args.language,
        "initial_prompt": prompt or None,
        "vad_filter": args.vad,
        "word_timestamps": True,
    }

    result: Any = model.transcribe(str(args.audio), **transcribe_kwargs)  # type: ignore[reportUnknownMemberType]
    segments = cast(Iterable[Any], result[0])
    _info = result[1]

    total_duration = getattr(_info, "duration", None)
    transcript = transcript_from_segments(
        segments,
        recording_start=recording_start,
        duration=float(total_duration) if total_duration else None,
        show_progress=not args.quiet,
        show_text=args.print_transcript,
        replacements=replacements,
        start_time=args.start,
        stop_time=args.stop,
    )
    output_path = args.output
    if not output_path:
        output_path = args.audio.with_suffix(".transcript.txt" if args.text else ".transcript.json")

    if args.text:
        write_transcript_text(transcript, output_path)
    else:
        write_transcript_json(transcript, output_path)

    if not args.quiet:
        print(f"Transcript written to: {output_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
