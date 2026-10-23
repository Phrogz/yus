# YUS Copilot Instructions

YUS turns spoken play-by-play of an indoor Ultimate game into events and live stats. The pipeline is built end to end;
[docs/architecture.md](../docs/architecture.md) says what each phase does and what is not built, and the
[README](../README.md#running-yus) shows how to run it.

## Code layout

```text
audio -> Transcript -> raw EventStream (names as spoken) -> PlayerResolver -> merge -> official EventStream -> compute_stats -> pages
```

| path | what | doc |
|---|---|---|
| [yus/\_\_init\_\_.py](../yus/__init__.py) | pydantic domain models: `Term`, `PlayerInfo`, `Team`, `Game`, `Word`, `Interpretation`, `TranscriptGroup`, `Transcript`, `Event`, `EventStream` | |
| [yus/sports/ultimate](../yus/sports/ultimate/__init__.py) | `Throw`, `Defense`, `Substitution`, `Infraction`; the sport's prompt terms and mondegreens. [indoor.py](../yus/sports/ultimate/indoor.py) adds wall/net flags | |
| [yus/processing/transcription](../yus/processing/transcription) | `transcribe.py`: Whisper on a recording (`yus-transcribe`), prompt building, mondegreen replacement. `live.py`: `LiveTranscriber` (`yus-live-transcribe`) | [usage.md](../docs/usage.md), [live_transcription.md](../docs/live_transcription.md) |
| [yus/processing/event_extraction](../yus/processing/event_extraction) | `EventExtractor` / `extract_events`: rules over `lexicon.py` for throws, Ds and substitutions, with corrections; batch or live (`yus-events`). `llm.py`: an optional local-LLM second reading (`--llm`) | [extraction.md](../docs/extraction.md) |
| [yus/processing/evaluation.py](../yus/processing/evaluation.py) | `score()`: event F1 against ground truth (`yus-score`) | [extraction.md](../docs/extraction.md) |
| [yus/processing/event_unification](../yus/processing/event_unification) | `players.py`: `PlayerResolver` (with `team_conflicts`), `GameDescriptions`. `merge.py`: `merge_streams`, `LiveMerger` | [usage.md](../docs/usage.md#game-description-files), [merging.md](../docs/merging.md) |
| [yus/processing/stats](../yus/processing/stats) | `compute_stats` -> `GameStats` (pandas DataFrames); `on_field.py`: points played, playing time, plus-minus, lines; `yus-stats` | [stats.md](../docs/stats.md) |
| [yus/session.py](../yus/session.py) | `GameSession`: one game live (extract, resolve, merge, stats), `snapshot()`, save/load; `replay()` | [session.md](../docs/session.md) |
| [yus/game_cli.py](../yus/game_cli.py) | `yus-game`: a game's recordings or transcripts through `GameSession` afterwards; HTML report, CSV tables | [postgame.md](../docs/postgame.md) |
| [yus/web/server.py](../yus/web/server.py) | `yus-serve`: Starlette app, phones stream PCM over `/ws/audio`, `DecodeScheduler` shares the GPU; pages in `yus/web/static` | [server.md](../docs/server.md) |
| [yus/web/dashboard.py](../yus/web/dashboard.py) | the Dash dashboard, mounted at `/dashboard/` | [dashboard.md](../docs/dashboard.md) |
| [yus/web/replay.py](../yus/web/replay.py) | `yus-replay`: streams an audio file to `yus-serve` as a phone would | [server.md](../docs/server.md) |
| [yus/util.py](../yus/util.py) | an old Google Speech-to-Text adapter, unused | |

Console scripts are declared in [pyproject.toml](../pyproject.toml).

## Ground truth and tests

- [tests/data/gruindoor_20250114T2030.py](../tests/data/gruindoor_20250114T2030.py) holds one hand-made game: `build_game()`,
  `build_transcript()`, `build_raw_stream()` (events, names as spoken) and `build_unified_stream()` (names resolved).
  `python -m tests.data.regenerate_fixtures` rewrites its JSON fixtures after an edit.
- `tests/data/…-descriptions.json` is the game's descriptions file; `…-whisper-turbo.json` is a real Whisper transcript of it.
- `tests/data/subbing_20250128T2050-*`: another game's Whisper transcript, mostly substitutions, with a draft ground truth
  nobody has checked against the audio.
- Tests: `uv run pytest -q` (about 45 s). Tests that need the Whisper model, a GPU, the game's audio or Chrome run only with
  `YUS_SLOW_TESTS=1`. Lint: `ruff check yus tests` and `ruff format --check yus tests`.

## Conventions

- Python 3.13+, `uv`, type hints, pydantic models as the data structures; ruff with line length 180.
- New event types subclass `yus.Event` or a sport's base class; update the module's `__all__`.
- Times are naive local wall-clock datetimes.
- Names: team files hold only official names, real nicknames and true mishearings (mondegreens). What one commentator
  called someone in one game ("the kid", "red shorts") goes in that game's descriptions file. Extraction keeps names as
  spoken; `PlayerResolver` maps them to players.
- Mishearings of the sport's terms go in the sport's `mondegreens` (`yus/sports/ultimate`), not in extraction rules.
- Docs live in [docs/](../docs); update the doc for a module when its behaviour changes.
