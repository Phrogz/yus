"""Tests for yus-transcribe's prompt building, mondegreen replacement, recording start, and backend wiring (no model is loaded)."""

import datetime as dt
import inspect
import json
import pathlib
import re
import time
from collections import Counter
from types import SimpleNamespace
from typing import Any, Callable

import pytest

import yus
from yus.processing.transcription import transcribe as tr
from yus.sports.ultimate import indoor

DATA = pathlib.Path(__file__).parent / "data"
T0 = dt.datetime(2025, 1, 14, 20, 30, 33)


@pytest.fixture(scope="module")
def teams() -> list[yus.Team]:
    return tr.load_teams_from_files([DATA / "team_category_5.json", DATA / "team_dump_and_drizzle.json"])


@pytest.fixture(scope="module")
def replacements(teams: list[yus.Team]) -> tr.Replacements:
    return tr.load_replacements("ultimate/indoor", teams)


def whisper_word(text: str, start: float, end: float, probability: float = 0.9) -> SimpleNamespace:
    return SimpleNamespace(word=text, start=start, end=end, probability=probability)


def segment(*words: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(start=words[0].start, end=words[-1].end, text="".join(w.word for w in words), avg_logprob=-0.2, words=list(words))


def transcribe_words(segments: list[SimpleNamespace], replacements: tr.Replacements, fired: Counter[tuple[str, str]] | None = None) -> list[list[yus.Word]]:
    transcript = tr.transcript_from_segments(segments, recording_start=T0, show_progress=False, replacements=replacements, fired=fired)
    return [group.words for group in transcript.groups]


def texts(words: list[yus.Word]) -> list[str]:
    return [w.text for w in words]


# Mondegreen replacement ---------------------------------------------------------------------------------------------


def test_words_lose_leading_space(replacements: tr.Replacements) -> None:
    [words] = transcribe_words([segment(whisper_word(" Flick", 1.0, 1.3), whisper_word(" to", 1.3, 1.4), whisper_word(" Kaia.", 1.4, 1.8))], replacements)
    assert texts(words) == ["Flick", "to", "Kaia."]


def test_single_word_mondegreen_keeps_punctuation(replacements: tr.Replacements) -> None:
    [words] = transcribe_words([segment(whisper_word(" Backhand", 0.0, 0.4), whisper_word(" to", 0.4, 0.5), whisper_word(" Takaya,", 0.5, 1.0))], replacements)
    assert texts(words) == ["Backhand", "to", "Kaia Mann,"]


def test_multi_word_mondegreen_becomes_one_word(replacements: tr.Replacements) -> None:
    seg = segment(
        whisper_word(" Huck", 10.0, 10.3, 0.95),
        whisper_word(" to", 10.3, 10.4, 0.9),
        whisper_word(" feather", 10.5, 10.8, 0.6),
        whisper_word(" brush.", 10.8, 11.2, 0.7),
    )
    [words] = transcribe_words([seg], replacements)
    assert texts(words) == ["Huck", "to", "Adam Federbusch."]
    merged = words[2]
    assert merged.start == T0 + dt.timedelta(seconds=10.5)
    assert merged.duration == dt.timedelta(seconds=0.7)
    assert merged.confidence == 0.6


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ([" Close", " crop"], ["Ben Kishter"]),
        ([" SHORT", " CROWN!"], ["Ben Kishter!"]),
        ([" the", " kid"], ["Serayan Knappe-Butler"]),
        ([" Steven", " Butler,"], ["Stephen Butler,"]),
        ([" scooper"], ["scoober"]),
        ([" Feather", " bush"], ["Adam Federbusch"]),  # longest match first: not "Feather" + replaced "bush"
        ([" bush"], ["Adam Federbusch"]),
        ([" the", " kids"], ["the", "kids"]),
        # mishearings learned from the 2025-01-14 20:30 game's audio
        ([" Flick", " to", " Kaya."], ["Flick", "to", "Kaia Mann."]),
        ([" Steven", " picks"], ["Stephen Butler", "picks"]),
        ([" Kidd", " flicks"], ["Serayan Knappe-Butler", "flicks"]),
        ([" Fetterbush"], ["Adam Federbusch"]),
        ([" Scuba", " to"], ["scoober", "to"]),
        ([" Flick", " -hawk"], ["Flick", "-huck"]),
        ([" the", " endzone"], ["the", "end zone"]),
        ([" D", " by"], ["deed", "by"]),
    ],
)
def test_mondegreen_phrases(replacements: tr.Replacements, spoken: list[str], expected: list[str]) -> None:
    seg = segment(*(whisper_word(text, i, i + 1) for i, text in enumerate(spoken)))
    [words] = transcribe_words([seg], replacements)
    assert texts(words) == expected


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ([" the.", " Kid"], ["the.", "Kid"]),
        ([" close,", " crop"], ["close,", "crop"]),
        ([" Steven;", " Butler"], ["Stephen Butler;", "Butler"]),  # not "steven butler", but "steven" alone still matches
        ([" feather?", " bush"], ["feather?", "Adam Federbusch"]),  # not "feather bush", but "bush" alone still matches
        ([" close…", " crop"], ["close…", "crop"]),
        ([" close—", " crop"], ["close—", "crop"]),
        ([" close-", " crop"], ["close-", "crop"]),
        ([" close)", " crop"], ["close)", "crop"]),
        ([' close"', " crop"], ['close"', "crop"]),
        ([" Close", " crop."], ["Ben Kishter."]),  # punctuation after the last word is fine
    ],
)
def test_mondegreen_phrases_do_not_cross_punctuation(replacements: tr.Replacements, spoken: list[str], expected: list[str]) -> None:
    seg = segment(*(whisper_word(text, i, i + 1) for i, text in enumerate(spoken)))
    [words] = transcribe_words([seg], replacements)
    assert texts(words) == expected


def test_mondegreens_do_not_span_segments(replacements: tr.Replacements) -> None:
    groups = transcribe_words([segment(whisper_word(" to", 0.0, 0.2), whisper_word(" feather", 0.2, 0.5)), segment(whisper_word(" brush", 2.0, 2.4))], replacements)
    assert [texts(g) for g in groups] == [["to", "feather"], ["brush"]]


def test_fired_replacements_are_counted(replacements: tr.Replacements) -> None:
    fired: Counter[tuple[str, str]] = Counter()
    seg = segment(whisper_word(" Feather", 0.0, 0.3), whisper_word(" brush,", 0.3, 0.6), whisper_word(" feather", 0.6, 0.9), whisper_word(" brush.", 0.9, 1.2))
    transcribe_words([seg], replacements, fired)
    assert fired == Counter({("feather brush", "Adam Federbusch"): 2})


def test_no_replacements_leaves_words(replacements: tr.Replacements) -> None:
    [words] = transcribe_words([segment(whisper_word(" feather", 0.0, 0.3), whisper_word(" brush", 0.3, 0.6))], {})
    assert texts(words) == ["feather", "brush"]


def test_segment_text_fallback_without_word_timings(replacements: tr.Replacements) -> None:
    fired: Counter[tuple[str, str]] = Counter()
    segs = [
        SimpleNamespace(start=5.0, end=7.0, text=" Dump to close crop.", avg_logprob=-0.3, words=None),
        SimpleNamespace(start=8.0, end=9.0, text=" Close, crop. The kid!", avg_logprob=-0.3, words=None),
    ]
    groups = transcribe_words(segs, replacements, fired)
    assert [texts(g) for g in groups] == [["Dump to Ben Kishter."], ["Close, crop. Serayan Knappe-Butler!"]]
    assert groups[0][0].duration == dt.timedelta(seconds=2)
    assert fired == Counter({("close crop", "Ben Kishter"): 1, ("the kid", "Serayan Knappe-Butler"): 1})


def test_bad_team_file_is_an_error(tmp_path: pathlib.Path) -> None:
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not json")
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps({"names": ["White"], "players": {"Kaia Mann": {"mondegreens": "takaya", "nicknames": 3}}}))
    for path in (bad_json, invalid):
        with pytest.raises(SystemExit, match=re.escape(f"could not load team file {path}: ")):
            tr.load_teams_from_files([DATA / "team_category_5.json", path])
    with pytest.raises(SystemExit, match="validation error"):
        tr.load_teams_from_files([invalid])


def test_blank_segments_are_skipped(replacements: tr.Replacements) -> None:
    groups = transcribe_words([segment(whisper_word(" ", 0.0, 0.1)), segment(whisper_word(" Pull!", 1.0, 1.5))], replacements)
    assert [texts(g) for g in groups] == [["Pull!"]]


# Prompt -------------------------------------------------------------------------------------------------------------


def token_counter(name: str) -> Callable[[str], int]:
    if name == "estimate":
        return tr.estimate_tokens
    pytest.importorskip("mlx_whisper", reason="Whisper's tiktoken tokenizer comes with mlx-whisper (uv sync --extra mlx, Apple Silicon only)")
    return tr.mlx_token_counter(SimpleNamespace(is_multilingual=True, num_languages=100), "en")


def test_roster_lists_each_player_once(teams: list[yus.Team]) -> None:
    roster = tr.load_roster(teams)
    assert len(roster) == sum(len(team.players) for team in teams)
    assert "Matt Whitlock (Pikachu)" in roster
    assert "Adam Federbusch (Busch)" in roster
    assert "Kaia Mann" in roster
    assert "Federbusch" not in roster and "Adam" not in roster  # no separate first/last names


def test_terms_in_descending_weight() -> None:
    terms = tr.load_terms("ultimate/indoor", ["Pikachu Special"])
    weights: dict[str, float] = {}
    for term in indoor.terms:
        weights.setdefault(term.phrase.lower(), term.weight)  # first (highest) weight of a repeated term
    assert terms[0] == "Pikachu Special"
    sport = [weights[t.lower()] for t in terms[1:]]
    assert sport == sorted(sport, reverse=True)
    assert len(terms) == len({t.lower() for t in terms})


@pytest.mark.parametrize("counter", ["estimate", "whisper"])
def test_prompt_fits_budget_and_keeps_roster(teams: list[yus.Team], counter: str) -> None:
    count = token_counter(counter)
    roster = tr.load_roster(teams)
    terms = tr.load_terms("ultimate/indoor", [])
    prompt = tr.build_prompt(roster, terms, count_tokens=count)
    assert count(" " + prompt) <= tr.PROMPT_TOKEN_BUDGET
    assert prompt.startswith("Players: " + ", ".join(roster) + ". Terms: flick, backhand,")
    assert "off the net" not in prompt  # lowest weight terms are the ones dropped
    # a smaller budget never overflows either, dropping terms before players
    small = tr.build_prompt(roster, terms, count_tokens=count, budget=60)
    assert count(" " + small) <= 60
    assert small.startswith("Players: Jennifer Dasenbrock")


def test_prompt_prefix_comes_first(teams: list[yus.Team], capsys: pytest.CaptureFixture[str]) -> None:
    prompt = tr.build_prompt(tr.load_roster(teams), ["flick"], prefix="Indoor ultimate play-by-play.")
    assert prompt.startswith("Indoor ultimate play-by-play. Players: ")
    assert prompt.endswith("Terms: flick.")
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("roster", [[], ["Kaia Mann"]])
def test_prompt_prefix_over_budget_warns(roster: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    prefix = "Indoor ultimate play-by-play. " * 30
    assert tr.build_prompt(roster, ["flick"], prefix=prefix) == prefix.strip()
    assert f"the --prompt text alone is {tr.estimate_tokens(' ' + prefix.strip())} tokens, over the prompt budget of 223" in capsys.readouterr().err


def test_token_counters_follow_model_multilinguality() -> None:
    pytest.importorskip("mlx_whisper", reason="mlx-whisper is only installed on Apple Silicon (uv sync --extra mlx)")
    from mlx_whisper.tokenizer import get_tokenizer

    english = tr.mlx_token_counter(SimpleNamespace(is_multilingual=False, num_languages=99), "en")  # e.g. medium.en: n_vocab 51864
    multilingual = tr.mlx_token_counter(SimpleNamespace(is_multilingual=True, num_languages=100), "en")  # e.g. large-v3: n_vocab 51866
    assert english(" Ruprecht") == len(get_tokenizer(False).encode(" Ruprecht")) == 4
    assert multilingual(" Ruprecht") == len(get_tokenizer(True, num_languages=100).encode(" Ruprecht")) == 3


def test_faster_whisper_token_counter_uses_model_tokenizer() -> None:
    import tokenizers

    hf_tokenizer = tokenizers.Tokenizer(tokenizers.models.WordLevel({"flick": 0, "to": 1, "Kaia": 2, "[UNK]": 3}, unk_token="[UNK]"))
    hf_tokenizer.pre_tokenizer = tokenizers.pre_tokenizers.Whitespace()
    count = tr.faster_whisper_token_counter(SimpleNamespace(hf_tokenizer=hf_tokenizer, model=SimpleNamespace(is_multilingual=False)), "en")
    assert count(" flick to Kaia Mann") == 4
    with pytest.raises(ValueError, match="language code"):  # a multilingual model needs a language its tokenizer knows
        tr.faster_whisper_token_counter(SimpleNamespace(hf_tokenizer=hf_tokenizer, model=SimpleNamespace(is_multilingual=True)), "xx")


# Recording start ----------------------------------------------------------------------------------------------------


@pytest.fixture
def denver(monkeypatch: pytest.MonkeyPatch):
    """Run in a known local time zone (MST, UTC-7 in January), since UTC times are converted to local time."""
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset is not available on this platform")
    monkeypatch.setenv("TZ", "America/Denver")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("20250114T2030-0700.ogg", dt.datetime(2025, 1, 14, 20, 30)),  # an offset keeps the wall-clock time as written
        ("20250114T203033+0130.wav", dt.datetime(2025, 1, 14, 20, 30, 33)),
        ("20250114T203033-07:00.wav", dt.datetime(2025, 1, 14, 20, 30, 33)),
        ("20250114T2030+05:45.wav", dt.datetime(2025, 1, 14, 20, 30)),
        ("20250115T033033Z.m4a", T0),  # UTC is converted to local time
        ("20250115T033033z.m4a", T0),
        ("gruindoor_20250114T2030.mp3", dt.datetime(2025, 1, 14, 20, 30)),
        ("gruindoor_20250114T2030_take2.mp3", dt.datetime(2025, 1, 14, 20, 30)),
        ("20250114T2030-1.ogg", dt.datetime(2025, 1, 14, 20, 30)),  # a take number, not an offset
        ("game.wav", None),
        ("20251314T2030.ogg", None),  # no month 13
        ("20250114T20301.ogg", None),  # odd digit count
        ("20250114T2030+2400.ogg", None),  # offsets out of range
        ("20250114T2030-9999.ogg", None),
        ("20250114T2030+0760.ogg", None),  # minutes >= 60
        ("20250114T2030-07:60.ogg", None),
        ("20250114T2030-07.ogg", None),  # malformed offsets are not dropped
        ("20250114T2030-070.ogg", None),
        ("20250114T2030-07:00:00.ogg", None),
        ("20250114T2030+07:0.ogg", None),
    ],
)
def test_recording_start_from_filename(denver: None, name: str, expected: dt.datetime | None) -> None:
    assert tr.recording_start_from_filename(pathlib.Path("/some/dir") / name) == expected


def write_audio(path: pathlib.Path, stream_tags: dict[str, str] | None = None, container_tags: dict[str, str] | None = None) -> pathlib.Path:
    """Write a 20 ms silent audio file with the given metadata (ogg keeps stream tags; m4a keeps container tags)."""
    import av
    import numpy as np

    with av.open(str(path), "w") as container:
        stream: Any = container.add_stream("aac" if path.suffix == ".m4a" else "flac", rate=48000)
        stream.metadata.update(stream_tags or {})
        container.metadata.update(container_tags or {})
        frame = av.AudioFrame.from_ndarray(np.zeros((1, 960), dtype=np.int16), format="s16", layout="mono")
        frame.sample_rate = 48000
        for packet in [*stream.encode(frame), *stream.encode(None)]:
            container.mux(packet)
    return path


IPHONE_TAGS = {"creation_time": "2025-01-15T03:30:33.000000Z", "com.apple.quicktime.creationdate": "2025-01-14T20:30:33-0700"}


@pytest.mark.parametrize(
    ("name", "stream_tags", "container_tags", "expected"),
    [
        ("rec.ogg", IPHONE_TAGS, {}, (T0, "com.apple.quicktime.creationdate")),  # like 20250114T2030-0700.ogg
        ("rec.ogg", {"COM.APPLE.QUICKTIME.CREATIONDATE": "2025-01-14T22:30:33+01:00"}, {}, (dt.datetime(2025, 1, 14, 22, 30, 33), "com.apple.quicktime.creationdate")),
        ("rec.ogg", {"creation_time": "2025-01-15T03:30:33.000000Z"}, {}, (T0, "creation_time")),
        ("rec.ogg", {"creation_time": "1970-01-01T00:00:00.000000Z", "com.apple.quicktime.creationdate": "garbage"}, {}, None),
        ("rec.ogg", {"com.apple.quicktime.creationdate": "2025-01-14", "creation_time": "2025-01-15T03:30:33Z"}, {}, (T0, "creation_time")),  # no time of day
        ("rec.m4a", {}, {"creation_time": "2025-01-15T03:30:33Z"}, (T0, "creation_time")),
        ("rec.ogg", {}, {}, None),
    ],
)
def test_recording_start_from_metadata(
    denver: None, tmp_path: pathlib.Path, name: str, stream_tags: dict[str, str], container_tags: dict[str, str], expected: tuple[dt.datetime, str] | None
) -> None:
    assert tr.recording_start_from_metadata(write_audio(tmp_path / name, stream_tags, container_tags)) == expected


def test_recording_start_from_unreadable_file(tmp_path: pathlib.Path) -> None:
    (tmp_path / "notes.ogg").write_text("not audio")
    assert tr.recording_start_from_metadata(tmp_path / "notes.ogg") is None
    assert tr.recording_start_from_metadata(tmp_path / "missing.ogg") is None


def test_parse_recording_start(denver: None, tmp_path: pathlib.Path) -> None:
    tagged = write_audio(tmp_path / "20250101T0000-0700.ogg", IPHONE_TAGS)
    untagged = write_audio(tmp_path / "20250114T2030-0700.ogg")
    assert tr.parse_recording_start("auto", tagged) == (T0, "com.apple.quicktime.creationdate in the file's metadata")  # metadata beats the file name
    assert tr.parse_recording_start("auto", untagged) == (dt.datetime(2025, 1, 14, 20, 30), "the file name")
    assert tr.parse_recording_start("auto", pathlib.Path("20250115T033033Z.ogg")) == (T0, "the file name")  # a missing file has no metadata
    assert tr.parse_recording_start("2025-01-14T20:30:33", tagged) == (T0, "--recording-start")
    assert tr.parse_recording_start("2025-01-14T20:30:33-04:00", tagged) == (T0, "--recording-start")  # explicit input keeps its wall-clock time
    assert tr.parse_recording_start("2025-01-15T03:30:33Z", tagged) == (T0, "--recording-start")  # ...unless it is UTC, as in ffprobe's creation_time
    for value, audio in [("auto", pathlib.Path("game.wav")), ("auto", None), ("now", tagged)]:
        before = dt.datetime.now()
        start, source = tr.parse_recording_start(value, audio)
        assert start.tzinfo is None and before <= start <= dt.datetime.now()
        assert source.startswith("now")


# CLI and backends ---------------------------------------------------------------------------------------------------


def test_cli_defaults() -> None:
    args = tr.build_arg_parser().parse_args(["game.ogg"])
    assert (args.backend, args.model, args.recording_start) == ("auto", None, "auto")
    assert (args.condition_on_previous_text, args.hotwords, args.mondegreens, args.vad) == (False, False, True, True)
    args = tr.build_arg_parser().parse_args(["game.ogg", "--backend", "mlx", "--condition-on-previous-text", "--no-mondegreens"])
    assert (args.backend, args.condition_on_previous_text, args.mondegreens) == ("mlx", True, False)


@pytest.mark.parametrize(
    ("flags", "prompt_key"),
    [
        ([], "initial_prompt"),
        (["--hotwords"], "hotwords"),
        (["--condition-on-previous-text"], "initial_prompt"),
        (["--condition-on-previous-text", "--hotwords"], "initial_prompt"),  # hotwords + previous text could overflow the decoder context
    ],
)
def test_faster_whisper_kwargs_match_signature(flags: list[str], prompt_key: str) -> None:
    from faster_whisper import WhisperModel

    args = tr.build_arg_parser().parse_args(["game.ogg", *flags])
    kwargs = tr.faster_whisper_transcribe_kwargs(args, "Players: Kaia Mann.")
    assert set(kwargs) <= set(inspect.signature(WhisperModel.transcribe).parameters)
    assert kwargs["condition_on_previous_text"] is ("--condition-on-previous-text" in flags)
    assert kwargs[prompt_key] == "Players: Kaia Mann."
    assert {"initial_prompt", "hotwords"} & set(kwargs) == {prompt_key}  # the prompt is passed once
    assert set(tr.faster_whisper_model_kwargs(args, "cpu")) <= set(inspect.signature(WhisperModel.__init__).parameters)


def test_mlx_kwargs_match_signature() -> None:
    mlx_whisper = pytest.importorskip("mlx_whisper", reason="mlx-whisper is only installed on Apple Silicon (uv sync --extra mlx)")
    from mlx_whisper.decoding import DecodingOptions

    args = tr.build_arg_parser().parse_args(["game.ogg"])
    kwargs = tr.mlx_transcribe_kwargs(args, tr.MLX_MODELS["large-v3-turbo"], "Players: Kaia Mann.")
    accepted = set(inspect.signature(mlx_whisper.transcribe).parameters) | set(inspect.signature(DecodingOptions).parameters)
    assert set(kwargs) <= accepted
    assert kwargs["condition_on_previous_text"] is False


def test_model_repos() -> None:
    assert tr.resolve_hf_repo_id("large-v3-turbo", "mlx") == "mlx-community/whisper-large-v3-turbo"
    assert tr.resolve_hf_repo_id("large-v3", "mlx") == "mlx-community/whisper-large-v3-mlx"
    assert tr.resolve_hf_repo_id("large-v3", "faster-whisper") == "Systran/faster-whisper-large-v3"
    assert tr.resolve_hf_repo_id("large-v3-turbo", "faster-whisper") == "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
    assert tr.resolve_hf_repo_id("someone/custom-whisper", "mlx") == "someone/custom-whisper"
    with pytest.raises(SystemExit):
        tr.resolve_hf_repo_id("no-such-size", "mlx")


def test_resolve_backend(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    assert tr.resolve_backend("faster-whisper") == "faster-whisper"
    monkeypatch.setattr(tr.sys, "platform", "darwin")
    monkeypatch.setattr(tr.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(tr.importlib.util, "find_spec", lambda name: object() if name == "mlx_whisper" else None)
    monkeypatch.setattr(tr.importlib, "import_module", lambda name: object())
    assert tr.resolve_backend("auto") == "mlx"
    assert capsys.readouterr().err == ""

    def broken_mlx(name: str) -> object:
        raise ImportError(f"dlopen({name}): Symbol not found: macOS 14 required")

    monkeypatch.setattr(tr.importlib, "import_module", broken_mlx)
    assert tr.resolve_backend("auto") == "faster-whisper"
    assert "mlx-whisper is installed but does not load (dlopen(mlx_whisper): Symbol not found" in capsys.readouterr().err
    monkeypatch.setattr(tr.platform, "machine", lambda: "x86_64")
    assert tr.resolve_backend("auto") == "faster-whisper"


def test_resolve_device_uses_ctranslate2(monkeypatch: pytest.MonkeyPatch) -> None:
    import ctranslate2

    assert tr.resolve_device("cpu") == "cpu"
    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", lambda: 1)
    assert tr.resolve_device("auto") == "cuda"
    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", lambda: 0)
    assert tr.resolve_device("auto") == "cpu"
