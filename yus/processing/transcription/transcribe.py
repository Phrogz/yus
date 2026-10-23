"""Script to transcribe an audio file into a timestamped transcript using Whisper.

Exposed as yus-transcribe command-line tool.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import math
import pathlib
import platform
import re
import statistics
import sys
from collections import Counter
from types import SimpleNamespace
from typing import Any, Callable, Iterable, cast

import yus
from yus.sports import ultimate
from yus.sports.ultimate import indoor

# Whisper conditions on at most n_text_ctx // 2 - 1 prompt tokens: the last 223 of an initial prompt, or the first 223 of faster-whisper hotwords.
PROMPT_TOKEN_BUDGET = 223

SPORT_VOCABULARY: dict[str, tuple[list[yus.Term], dict[str, list[str]]]] = {
    "ultimate": (ultimate.terms, ultimate.mondegreens),
    "ultimate/indoor": (indoor.terms, indoor.mondegreens),
}

BACKENDS = ("auto", "faster-whisper", "mlx")
DEFAULT_MODELS = {"faster-whisper": "large-v3", "mlx": "large-v3-turbo"}
MLX_MODELS = {
    **{size: f"mlx-community/whisper-{size}-mlx" for size in "tiny tiny.en base base.en small small.en medium medium.en large-v1 large-v2 large-v3".split()},
    "large": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "turbo": "mlx-community/whisper-large-v3-turbo",
}

# Project recordings are named like 20250114T2030-0700.ogg (seconds and UTC offset optional). A malformed offset (sign plus 2+ digits) is
# captured so it can be rejected; a take number such as "-1" is not an offset.
FILENAME_TIMESTAMP = re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})?([Zz]|[+-]\d{2}[\d:]*)?(?![\d:])")
UTC_OFFSET = re.compile(r"([+-])(\d{2}):?(\d{2})")

# Creation time tags in audio file metadata, most trusted first: local time with its UTC offset (iPhone recordings), then a UTC time.
CREATION_TIME_TAGS = ("com.apple.quicktime.creationdate", "creation_time")

# A word ending a clause; a mondegreen phrase may not continue past one.
CLAUSE_END = re.compile(r"[.?!,;:…—–)\]\"”-]\W*$")

# Mondegreen table: normalized word sequence -> replacement text, e.g. ("feather", "brush") -> "Adam Federbusch".
Replacements = dict[tuple[str, ...], str]


def _dedupe(phrases: Iterable[str]) -> list[str]:
    """Strip phrases and drop blanks and case-insensitive repeats, keeping the first occurrence."""
    seen: set[str] = set()
    result: list[str] = []
    for phrase in phrases:
        p = phrase.strip()
        if p and p.lower() not in seen:
            seen.add(p.lower())
            result.append(p)
    return result


def load_terms(sport: str, extra_terms: Iterable[str]) -> list[str]:
    """Prompt vocabulary, most important first: custom terms, then the sport's terms by descending weight."""
    sport_terms = sorted(SPORT_VOCABULARY.get(sport, ([], {}))[0], key=lambda t: -t.weight)  # stable: keeps definition order within a weight
    return _dedupe([*extra_terms, *(t.phrase for t in sport_terms)])


def load_roster(teams: list[yus.Team]) -> list[str]:
    """One prompt entry per player, with nicknames in parentheses, e.g. "Matt Whitlock (Pikachu)"."""
    nicknames: dict[str, list[str]] = {}
    for team in teams:
        for name, info in team.players.items():
            player_nicks = info if isinstance(info, list) else info.nicknames
            nicknames[name.strip()] = _dedupe([*nicknames.get(name.strip(), []), *player_nicks])
    return [f"{name} ({', '.join(nicks)})" if nicks else name for name, nicks in nicknames.items()]


def estimate_tokens(text: str) -> int:
    """Conservative Whisper token count when no tokenizer is available (English text with proper names averages ~3.2 characters per token)."""
    return math.ceil(len(text) / 2.5)


def build_prompt(
    roster: list[str],
    terms: list[str],
    *,
    prefix: str = "",
    count_tokens: Callable[[str], int] = estimate_tokens,
    budget: int = PROMPT_TOKEN_BUDGET,
) -> str:
    """Prompt text of `prefix`, then the roster, then as many terms (in order) as fit in `budget` tokens; players are dropped from the end only if the roster alone does not fit."""

    def render(players: list[str], kept_terms: list[str]) -> str:
        parts = [prefix.strip(), f"Players: {', '.join(players)}." if players else "", f"Terms: {', '.join(kept_terms)}." if kept_terms else ""]
        return " ".join(p for p in parts if p)

    def fits(text: str) -> bool:
        return count_tokens(" " + text) <= budget  # Whisper encodes the prompt with a leading space

    if prefix.strip() and not fits(prefix.strip()):
        size = count_tokens(" " + prefix.strip())
        print(f"Warning: the --prompt text alone is {size} tokens, over the prompt budget of {budget}; Whisper will truncate it.", file=sys.stderr, flush=True)
    players = list(roster)
    while players and not fits(render(players, [])):
        players.pop()
    if len(players) < len(roster):
        print(f"Warning: prompt budget of {budget} tokens only fits {len(players)} of {len(roster)} players.", file=sys.stderr, flush=True)
    kept: list[str] = []
    for term in terms:
        if fits(render(players, kept + [term])):
            kept.append(term)
    return render(players, kept)


def phrases_from_file(path: pathlib.Path | None) -> list[str]:
    if not path:
        return []
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def normalize_token(text: str) -> str:
    """Matching form of one ASR word: lowercase, punctuation stripped (" Kaya," -> "kaya")."""
    return re.sub(r"[^\w']+", "", text.lower()).strip("'")


def phrase_key(phrase: str) -> tuple[str, ...]:
    return tuple(t for t in (normalize_token(w) for w in phrase.split()) if t)


def load_replacements(sport: str, teams: list[yus.Team]) -> Replacements:
    """Map each known mishearing (sport mondegreens and players' "mondegreens") to the text that replaces it."""
    replacements: Replacements = {}

    def add(mishearing: str, canonical: str) -> None:
        if key := phrase_key(mishearing):
            replacements[key] = canonical

    for canonical, variants in SPORT_VOCABULARY.get(sport, ([], {}))[1].items():
        for variant in variants:
            add(variant, canonical)
    for team in teams:
        for official_name, info in team.players.items():
            if isinstance(info, yus.PlayerInfo):
                for mishearing in info.mondegreens:
                    add(mishearing, official_name)
    return replacements


def find_replacements(texts: list[str], replacements: Replacements, fired: Counter[tuple[str, str]] | None = None) -> list[tuple[int, int, str]]:
    """Find mondegreens in consecutive words, longest phrase first, not spanning a clause-ending word like "the." or "close,".
    Returns (first index, end index, replacement) spans; the replacement keeps the leading punctuation of the first word and
    the trailing punctuation of the last. Counts each replacement in `fired` by (normalized mishearing, replacement)."""
    if not replacements:
        return []
    longest = max(len(key) for key in replacements)
    keys = [normalize_token(t) for t in texts]
    clause_ends = [bool(CLAUSE_END.search(t.strip())) for t in texts]
    spans: list[tuple[int, int, str]] = []
    i = 0
    while i < len(keys):
        for n in range(min(longest, len(keys) - i), 0, -1):
            key = tuple(keys[i : i + n])
            if all(key) and key in replacements and not any(clause_ends[i : i + n - 1]):
                lead = re.match(r"\W*", texts[i].strip())
                trail = re.search(r"\W*$", texts[i + n - 1].strip())
                spans.append((i, i + n, f"{lead.group() if lead else ''}{replacements[key]}{trail.group() if trail else ''}"))
                if fired is not None:
                    fired[(" ".join(key), replacements[key])] += 1
                i += n
                break
        else:
            i += 1
    return spans


def replace_mondegreens(words: list[yus.Word], replacements: Replacements, fired: Counter[tuple[str, str]] | None = None) -> list[yus.Word]:
    """Replace each mondegreen phrase by one Word spanning the matched words, with their lowest confidence."""
    result: list[yus.Word] = []
    done = 0
    for a, b, text in find_replacements([w.text for w in words], replacements, fired):
        matched = words[a:b]
        result.extend(words[done:a])
        start = matched[0].start
        end = matched[-1].start + matched[-1].duration
        result.append(yus.Word(text=text, start=start, duration=end - start, confidence=min(w.confidence for w in matched)))
        done = b
    result.extend(words[done:])
    return result


def normalize_text(text: str, replacements: Replacements, fired: Counter[tuple[str, str]] | None = None) -> str:
    tokens = text.split()
    result: list[str] = []
    done = 0
    for a, b, replacement in find_replacements(tokens, replacements, fired):
        result.extend(tokens[done:a])
        result.append(replacement)
        done = b
    result.extend(tokens[done:])
    return " ".join(result)


def word_probability(word: Any) -> float:
    """A Whisper word's probability; 0 when missing or not finite (a NaN would make the transcript's JSON invalid)."""
    probability = float(getattr(word, "probability", None) or 0.0)
    return probability if math.isfinite(probability) else 0.0


def segment_logprob(seg: Any) -> float:
    """The segment's avg_logprob or, when Whisper reports none or a value that is not finite (mlx-whisper gives NaN for about 1 decode in 6),
    the mean log probability of its words, as yus-live-transcribe does; 0 for a segment without words. Never NaN or infinite."""
    logprob = float(seg.avg_logprob) if getattr(seg, "avg_logprob", None) is not None else math.nan
    if math.isfinite(logprob):
        return logprob
    probabilities = [word_probability(w) for w in getattr(seg, "words", None) or [] if w.word.strip()]
    return statistics.fmean(math.log(max(p, 1e-6)) for p in probabilities) if probabilities else 0.0


def segment_words(seg: Any, recording_start: dt.datetime, replacements: Replacements, fired: Counter[tuple[str, str]] | None = None) -> list[yus.Word]:
    """Words of one Whisper segment, without the leading space Whisper puts on each word, and with mondegreens replaced."""
    if not getattr(seg, "words", None):
        # Fallback: no word timings provided; create a single word with segment text.
        text = normalize_text(seg.text.strip(), replacements, fired)
        start = recording_start + dt.timedelta(seconds=float(seg.start))
        return [yus.Word(text=text, start=start, duration=dt.timedelta(seconds=float(seg.end) - float(seg.start)), confidence=segment_logprob(seg))] if text else []
    words: list[yus.Word] = []
    for w in seg.words:
        if text := w.word.strip():
            start = recording_start + dt.timedelta(seconds=float(w.start))
            words.append(yus.Word(text=text, start=start, duration=dt.timedelta(seconds=float(w.end) - float(w.start)), confidence=word_probability(w)))
    return replace_mondegreens(words, replacements, fired)


def transcript_from_segments(
    segments: Iterable[Any],
    *,
    recording_start: dt.datetime,
    duration: float | None = None,
    show_progress: bool = True,
    show_text: bool = False,
    replacements: Replacements | None = None,
    start_time: float | None = None,
    stop_time: float | None = None,
    fired: Counter[tuple[str, str]] | None = None,
) -> yus.Transcript:
    """Build a Transcript from Whisper segments (objects with start, end, text, avg_logprob and optional words having word, start, end, probability)."""
    transcript = yus.Transcript()
    last_reported: int | None = None
    replacements = replacements or {}
    for seg in segments:
        # Skip segments outside the requested time range. Segments come in time order, so stop at the first one past
        # stop_time: faster-whisper decodes lazily, and then decodes no further.
        if start_time is not None and float(seg.end) < start_time:
            continue
        if stop_time is not None and float(seg.start) >= stop_time:
            break

        if show_progress and duration:
            percent = int(min(100, max(0, (float(seg.end) / duration) * 100)))
            if last_reported is None or percent >= last_reported + 5:
                last_reported = percent
                print(f"Processing audio: {percent}%", file=sys.stderr, flush=True)

        words = segment_words(seg, recording_start, replacements, fired)
        if not words:
            continue

        interp = transcript.add_group().add_interpretation(confidence=segment_logprob(seg))
        interp.words.extend(words)
        if show_text:
            print(interp.transcript, flush=True)

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
    # Back-references are excluded via field config (exclude=True) on:
    # - Interpretation.group (back-reference to TranscriptGroup)
    # - TranscriptGroup.transcript (back-reference to Transcript)
    # - Transcript.game (back-reference to Game)
    # These are restored on load via model_post_init hooks.
    output_path.write_text(json.dumps(transcript.model_dump(mode="json"), indent=2, sort_keys=True) + "\n")


def load_teams_from_files(team_files: list[pathlib.Path]) -> list[yus.Team]:
    teams: list[yus.Team] = []
    for path in team_files:
        try:
            teams.append(yus.Team(**json.loads(path.read_text())))
        except Exception as exc:
            raise SystemExit(f"Error: could not load team file {path}: {exc}") from exc
    return teams


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Transcribe an audio file to a timestamped transcript.")
    parser.add_argument("audio", type=pathlib.Path, help="Path to an audio file (wav/mp3/m4a/etc).")
    parser.add_argument("--sport", default="ultimate/indoor", help="Sport term set to bias toward (default: ultimate/indoor).")
    parser.add_argument(
        "--backend",
        choices=BACKENDS,
        default="auto",
        help="Whisper implementation: mlx (Apple Silicon GPU) or faster-whisper (CPU/CUDA). Default auto: mlx if mlx-whisper is installed and loads on an Apple Silicon Mac.",
    )
    parser.add_argument("--model", help="Whisper model size, Hugging Face repo id, or local path (default: large-v3 for faster-whisper, large-v3-turbo for mlx).")
    parser.add_argument("--language", default="en", help="Language code (default: en).")
    parser.add_argument("--compute-type", default="float32", help="CTranslate2 compute type, faster-whisper only (default: float32).")
    parser.add_argument("--device", default="auto", help="Device to use, faster-whisper only: auto/cpu/cuda (default: auto).")
    parser.add_argument("--num-workers", type=int, default=1, help="Number of worker threads, faster-whisper only (default: 1).")
    parser.add_argument("--cpu-threads", type=int, default=8, help="Number of CPU threads, faster-whisper only (default: 8).")
    parser.add_argument("--team", dest="teams", action="append", type=pathlib.Path, default=[], help="Team JSON file (can be specified multiple times).")
    parser.add_argument("--terms-file", type=pathlib.Path, help="Optional file with one custom phrase per line.")
    parser.add_argument("--prompt", default="", help="Optional extra prompt text.")
    parser.add_argument("--output", type=pathlib.Path, help="Output path (default: <audio>.transcript.json).")
    parser.add_argument("--text", action="store_true", help="Write plain text instead of JSON.")
    parser.add_argument(
        "--recording-start",
        default="auto",
        help="Recording start as an ISO timestamp (local wall-clock time: 20:30-07:00 is 20:30, but a UTC time ending in Z or +00:00 is converted to this"
        " computer's zone), 'now', or 'auto' (default): the creation time in the file's metadata, else a time in the file name like 20250114T2030-0700.ogg, else now.",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output and output location printing.")
    parser.add_argument("--print-transcript", action="store_true", help="Print transcript text to stdout as it is produced.")
    parser.add_argument("--start", type=float, help="Keep words from this many seconds into the file on (it is still decoded from its start).")
    parser.add_argument("--stop", type=float, help="Stop decoding this many seconds into the file.")
    parser.add_argument(
        "--condition-on-previous-text",
        action="store_true",
        help="Prompt each 30 s window with the text decoded so far (Whisper's default). Off by default: it tripled the error rate on play-by-play audio.",
    )
    parser.add_argument(
        "--hotwords",
        action="store_true",
        help="Pass the prompt as hotwords, priming every 30 s window instead of only the first (faster-whisper only). Off by default: in an mlx emulation of applying"
        " the prompt to every window, Whisper echoed the term list (faster-whisper hotwords themselves are untested).",
    )
    parser.add_argument("--no-mondegreens", action="store_false", dest="mondegreens", default=True, help="Do not replace known mishearings (mondegreens) in the output.")
    parser.add_argument(
        "--no-vad",
        action="store_false",
        dest="vad",
        default=True,
        help="Disable Voice Activity Detection (VAD); enabled by default to filter background noise (faster-whisper only).",
    )
    return parser


# Times are naive local wall-clock times, like the ground-truth fixtures and Game.when.


def wall_clock(when: dt.datetime) -> dt.datetime:
    """The local time as written: a time with a UTC offset (20:30-07:00) keeps its wall-clock time (20:30)."""
    return when.replace(tzinfo=None)


def utc_to_local(when: dt.datetime) -> dt.datetime:
    """This system's local wall-clock time at a UTC instant (a naive time is taken as UTC)."""
    return (when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)).astimezone().replace(tzinfo=None)


def local_naive(when: dt.datetime) -> dt.datetime:
    """A naive local time: a UTC time is converted to this system's local time, any other offset keeps its wall-clock time, naive stays."""
    if when.tzinfo is None:
        return when
    return utc_to_local(when) if when.utcoffset() == dt.timedelta(0) else wall_clock(when)


def recording_start_from_metadata(path: pathlib.Path) -> tuple[dt.datetime, str] | None:
    """The creation time in an audio file's container or stream metadata, and the tag it came from; None if absent, invalid, or unreadable."""
    try:
        import av  # type: ignore[import-not-found]  # PyAV, installed with faster-whisper

        with av.open(str(path)) as container:
            tags = [{str(k).lower(): str(v) for k, v in metadata.items()} for metadata in [container.metadata, *(s.metadata for s in container.streams)]]
    except Exception:
        return None
    for tag in CREATION_TIME_TAGS:
        for value in (t[tag] for t in tags if tag in t):
            if not re.search(r"\d{2}:\d{2}", value):  # a date without a time of day would put every word hours off
                continue
            try:
                when = dt.datetime.fromisoformat(value.strip())
                if when.year > 1970:  # unset creation times read as the 1904 or 1970 epoch
                    return (utc_to_local(when) if tag == "creation_time" else local_naive(when)), tag
            except (ValueError, OverflowError):
                continue
    return None


def recording_start_from_filename(path: pathlib.Path) -> dt.datetime | None:
    """Parse a start time from a file name like 20250114T2030-0700.ogg (seconds optional; UTC offset optional, as Z, +HHMM or +HH:MM).
    None if absent or invalid, including an invalid offset."""
    match = FILENAME_TIMESTAMP.search(path.name)
    if not match:
        return None
    year, month, day, hour, minute, second, offset = match.groups()
    try:
        tzinfo: dt.tzinfo | None = dt.timezone.utc if offset in ("Z", "z") else None
        if offset and tzinfo is None:
            parts = UTC_OFFSET.fullmatch(offset)
            if not parts or int(parts[3]) >= 60:
                return None
            tzinfo = dt.timezone((-1 if parts[1] == "-" else 1) * dt.timedelta(hours=int(parts[2]), minutes=int(parts[3])))
        when = dt.datetime(int(year), int(month), int(day), int(hour), int(minute), int(second or 0), tzinfo=tzinfo)
        return utc_to_local(when) if offset in ("Z", "z") else wall_clock(when)
    except (ValueError, OverflowError):
        return None


def parse_recording_start(value: str, audio: pathlib.Path | None = None) -> tuple[dt.datetime, str]:
    """The recording start as a naive local time, and where it came from."""
    if value == "auto" and audio:
        if found := recording_start_from_metadata(audio):
            return found[0], f"{found[1]} in the file's metadata"
        if start := recording_start_from_filename(audio):
            return start, "the file name"
    if value in ("auto", "now"):
        return dt.datetime.now(), "now" if value == "now" else "now: no creation time in the file's metadata or valid time in its name"
    return local_naive(dt.datetime.fromisoformat(value)), "--recording-start"


def format_bytes(size: int | None) -> str:
    if size is None:
        return ""
    size_f = float(size)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_f < 1024:
            return f"{size_f:.1f} {unit}"
        size_f /= 1024
    return f"{size_f:.1f} PB"


def resolve_backend(backend: str) -> str:
    """Resolve auto to mlx on Apple Silicon with mlx-whisper installed and loading (CTranslate2 has no Metal support), else faster-whisper."""
    if backend != "auto":
        return backend
    if sys.platform != "darwin" or platform.machine() != "arm64" or importlib.util.find_spec("mlx_whisper") is None:
        return "faster-whisper"
    try:
        importlib.import_module("mlx_whisper")  # also loads MLX itself and mlx-whisper's own dependencies
    except Exception as exc:
        print(f"Note: mlx-whisper is installed but does not load ({exc}); using faster-whisper.", file=sys.stderr, flush=True)
        return "faster-whisper"
    return "mlx"


def resolve_hf_repo_id(model: str, backend: str = "faster-whisper") -> str | None:
    if pathlib.Path(model).exists():
        return None
    if "/" in model:
        return model
    if backend == "mlx":
        if model not in MLX_MODELS:
            raise SystemExit(f"Unknown model {model!r} for the mlx backend; use one of {', '.join(MLX_MODELS)}, a Hugging Face repo id, or a local path.")
        return MLX_MODELS[model]
    try:
        from faster_whisper import utils as fw_utils  # type: ignore[import-not-found]

        known = cast(dict[str, str], getattr(fw_utils, "_MODELS", {}))
    except Exception:
        known = {}
    return known.get(model, f"Systran/faster-whisper-{model}")


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


def ensure_model_downloaded(repo_id: str, weight_files: tuple[str, ...] = ("model.bin",)) -> None:
    try:
        from huggingface_hub import snapshot_download as hf_snapshot_download  # type: ignore[reportUnknownVariableType]
        from huggingface_hub import try_to_load_from_cache as hf_try_to_load  # type: ignore[reportUnknownVariableType]
        from huggingface_hub.constants import HUGGINGFACE_HUB_CACHE  # type: ignore[reportUnknownVariableType]
    except Exception:
        return

    snapshot_download = cast(Any, hf_snapshot_download)
    try_to_load = cast(Any, hf_try_to_load)

    # Check if already cached
    for filename in weight_files:
        try:
            if isinstance(try_to_load(repo_id, filename, cache_dir=HUGGINGFACE_HUB_CACHE), str):
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
    """Resolve device: auto will use cuda if CTranslate2 sees a CUDA device, otherwise cpu."""
    if device != "auto":
        return device
    try:
        import ctranslate2  # type: ignore[import-not-found]

        if ctranslate2.get_cuda_device_count() > 0:
            print("CUDA detected. Using GPU.", file=sys.stderr, flush=True)
            return "cuda"
    except Exception:
        pass
    return "cpu"


def faster_whisper_model_kwargs(args: argparse.Namespace, device: str) -> dict[str, Any]:
    model_kwargs: dict[str, Any] = {"compute_type": args.compute_type, "device": device, "num_workers": args.num_workers}
    if args.cpu_threads:
        model_kwargs["cpu_threads"] = args.cpu_threads
    return model_kwargs


def faster_whisper_transcribe_kwargs(args: argparse.Namespace, prompt: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "language": args.language,
        "vad_filter": args.vad,
        "word_timestamps": True,
        "condition_on_previous_text": args.condition_on_previous_text,
    }
    # Hotwords prime every 30 s window, an initial_prompt only the first. Hotwords are not combined with previous text,
    # since up to 223 tokens of each could overflow Whisper's 448-token decoder context.
    if args.hotwords and not args.condition_on_previous_text:
        kwargs["hotwords"] = prompt or None
    else:
        kwargs["initial_prompt"] = prompt or None
    return kwargs


def mlx_transcribe_kwargs(args: argparse.Namespace, model: str, prompt: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "path_or_hf_repo": model,
        "language": args.language,
        "initial_prompt": prompt or None,
        "word_timestamps": True,
        "condition_on_previous_text": args.condition_on_previous_text,
        "verbose": None if args.quiet else False,  # False shows a progress bar
    }
    if args.stop is not None:
        # Decode no further than --stop. Decoding still starts at 0 for --start: the prompt primes only the first window, and
        # starting there gives the windows, and so the words, of a whole-file run (primed at 400 s, Whisper invented text).
        kwargs["clip_timestamps"] = [0.0, args.stop]
    return kwargs


def faster_whisper_token_counter(model: Any, language: str) -> Callable[[str], int]:
    """Count tokens as faster-whisper encodes a prompt: with the model's own tokenizer, for the model's multilinguality."""
    from faster_whisper.tokenizer import Tokenizer  # type: ignore[import-not-found]

    tokenizer = Tokenizer(model.hf_tokenizer, model.model.is_multilingual, task="transcribe", language=language)
    return lambda text: len(tokenizer.encode(text))


def mlx_token_counter(model: Any, language: str) -> Callable[[str], int]:
    """Count tokens as mlx-whisper encodes a prompt: with the tokenizer for the model's multilinguality and number of languages."""
    from mlx_whisper.tokenizer import get_tokenizer  # type: ignore[import-not-found]

    tokenizer = cast(Any, get_tokenizer(model.is_multilingual, num_languages=model.num_languages, language=language, task="transcribe"))
    return lambda text: len(tokenizer.encode(text))


def run_faster_whisper(args: argparse.Namespace, model_name: str, roster: list[str], terms: list[str]) -> tuple[Iterable[Any], float | None]:
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - runtime error reporting only
        raise SystemExit("Missing dependency 'faster-whisper'. Install it with: uv sync\nAlso ensure ffmpeg is installed: brew install ffmpeg") from exc

    device = resolve_device(args.device)
    model = cast(Any, WhisperModel(model_name, **faster_whisper_model_kwargs(args, device)))  # type: ignore[reportUnknownArgumentType]
    count_tokens = faster_whisper_token_counter(model, args.language)
    prompt = build_prompt(roster, terms, prefix=args.prompt, count_tokens=count_tokens)
    report_prompt(args, prompt, count_tokens)
    result: Any = model.transcribe(str(args.audio), **faster_whisper_transcribe_kwargs(args, prompt))  # type: ignore[reportUnknownMemberType]
    total_duration = getattr(result[1], "duration", None)
    return cast(Iterable[Any], result[0]), float(total_duration) if total_duration else None


def run_mlx(args: argparse.Namespace, model: str, roster: list[str], terms: list[str]) -> list[Any]:
    try:
        import mlx.core as mx  # type: ignore[import-not-found]
        import mlx_whisper  # type: ignore[import-not-found]
        from mlx_whisper.transcribe import ModelHolder  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - runtime error reporting only
        raise SystemExit("Missing dependency 'mlx-whisper' (Apple Silicon, macOS 14+). Install it with: uv sync --extra mlx, or use --backend faster-whisper") from exc

    count_tokens = mlx_token_counter(ModelHolder.get_model(model, mx.float16), args.language)  # mlx_whisper.transcribe reuses this cached model
    prompt = build_prompt(roster, terms, prefix=args.prompt, count_tokens=count_tokens)
    report_prompt(args, prompt, count_tokens)
    result = cast(dict[str, Any], mlx_whisper.transcribe(str(args.audio), **mlx_transcribe_kwargs(args, model, prompt)))  # type: ignore[reportUnknownMemberType]
    return [SimpleNamespace(**{**seg, "words": [SimpleNamespace(**w) for w in seg.get("words", [])]}) for seg in result["segments"]]


def report_prompt(args: argparse.Namespace, prompt: str, count_tokens: Callable[[str], int]) -> None:
    if not args.quiet:
        print(f"Prompt ({count_tokens(' ' + prompt)} of {PROMPT_TOKEN_BUDGET} tokens): {prompt}", file=sys.stderr, flush=True)


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    backend = resolve_backend(args.backend)
    model_name: str = args.model or DEFAULT_MODELS[backend]
    recording_start, recording_start_source = parse_recording_start(args.recording_start, args.audio)
    teams = load_teams_from_files(args.teams)
    roster = load_roster(teams)
    terms = load_terms(args.sport, phrases_from_file(args.terms_file))
    replacements = load_replacements(args.sport, teams) if args.mondegreens else {}
    if args.hotwords and (backend == "mlx" or args.condition_on_previous_text):
        print("Warning: --hotwords needs the faster-whisper backend without --condition-on-previous-text; ignoring it.", file=sys.stderr, flush=True)

    repo_id = resolve_hf_repo_id(model_name, backend)
    if repo_id:
        try:
            ensure_model_downloaded(repo_id, ("weights.safetensors", "weights.npz") if backend == "mlx" else ("model.bin",))
        except Exception as exc:  # pragma: no cover - best-effort download hinting
            print(f"Warning: model pre-download failed ({exc}). Will try during load.", file=sys.stderr, flush=True)
    if not args.quiet:
        print(f"Recording start: {recording_start.isoformat()} (from {recording_start_source})", file=sys.stderr, flush=True)
        print(f"Transcribing with {backend} using {repo_id or model_name}", file=sys.stderr, flush=True)

    duration: float | None = None
    if backend == "mlx":
        segments: Iterable[Any] = run_mlx(args, repo_id or model_name, roster, terms)
    else:
        segments, duration = run_faster_whisper(args, model_name, roster, terms)

    fired: Counter[tuple[str, str]] = Counter()
    transcript = transcript_from_segments(
        segments,
        recording_start=recording_start,
        duration=duration,
        show_progress=not args.quiet,
        show_text=args.print_transcript,
        replacements=replacements,
        start_time=args.start,
        stop_time=args.stop,
        fired=fired,
    )
    output_path = args.output
    if not output_path:
        output_path = args.audio.with_suffix(".transcript.txt" if args.text else ".transcript.json")

    if args.text:
        write_transcript_text(transcript, output_path)
    else:
        write_transcript_json(transcript, output_path)

    if not args.quiet:
        for (heard, replacement), count in fired.most_common():
            print(f"Replaced {heard!r} with {replacement!r} ({count}x)", file=sys.stderr)
        print(f"Transcript written to: {output_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
