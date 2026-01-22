# YUS Copilot Instructions

## Project orientation

- Core domain models live in [yus/**init**.py](../yus/__init__.py): `Game`, `Team`, `Transcript`/`TranscriptGroup`/`Interpretation`, `EventStream`, and base `Event`.
- Sport-specific event models are under [yus/sports/ultimate](../yus/sports/ultimate/__init__.py); indoor Ultimate extends the base `Throw` with wall/net flags in [yus/sports/ultimate/indoor.py](../yus/sports/ultimate/indoor.py).
- The architecture is documented in [docs/architecture.md](../docs/architecture.md): Terms → Game → Transcript → EventStream → unified events → DataFrames → Dash UI.

## Data flow + examples (use these as references)

- Ground-truth fixtures live in [tests/data/gruindoor_20250114T2030.py](../tests/data/gruindoor_20250114T2030.py):
  - `build_transcript()` constructs timed `Word`s and `TranscriptGroup`s.
  - `build_raw_stream()` shows how `EventStream.events` are built from transcripts for indoor Ultimate.
  - `build_unified_stream()` demonstrates alias normalization for player names (reverse map over nicknames).

## Architectural phases (detail)

- Transcription: ASR responses become `Transcript`/`TranscriptGroup`/`Interpretation`/`Word` structures. See Google Speech-to-Text adapter in [yus/util.py](../yus/util.py) and contribution goals in [docs/CONTRIBUTING.md](../docs/CONTRIBUTING.md).
- Event extraction: convert `Transcript` to sport-specific events (`Throw`, `Defense`, etc.). The most complete reference mapping is in [tests/data/gruindoor_20250114T2030.py](../tests/data/gruindoor_20250114T2030.py) (`build_raw_stream()`).
- Event unification: merge multiple streams and normalize player aliases; see the alias map and reverse-map normalization in [tests/data/gruindoor_20250114T2030.py](../tests/data/gruindoor_20250114T2030.py) (`build_unified_stream()`).
- Stat generation: planned to derive pandas DataFrames from unified event streams and then aggregate; see architectural intent in [docs/architecture.md](../docs/architecture.md).
- Mobile/web app: visualization planned via Dash/Flask; track intended UI usage in [docs/architecture.md](../docs/architecture.md) and dependencies in [pyproject.toml](../pyproject.toml).

## Conventions & patterns

- Pydantic models are the canonical data structures. Prefer adding new event types as subclasses of `yus.Event` (or sport-specific base classes) and update `__all__` lists when adding exports.
- Terms vocabulary for ASR adaptation is defined as `yus.Term` lists per sport. See the weighted term lists in [yus/sports/ultimate/**init**.py](../yus/sports/ultimate/__init__.py) and the indoor extensions in [yus/sports/ultimate/indoor.py](../yus/sports/ultimate/indoor.py).
- Transcript conversions from Google Speech-to-Text live in [yus/util.py](../yus/util.py). Preserve the timestamp math when adding new ASR adapters.

## Storage + web integration

- Local storage uses sqlite at [yus/web/db/yus.sqlite3](../yus/web/db/yus.sqlite3), with helpers in [yus/web/db/**init**.py](../yus/web/db/__init__.py) and schema setup in [yus/web/db/migrate.py](../yus/web/db/migrate.py).
- Example data ingestion to sqlite is in [tests/add_to_db.py](../tests/add_to_db.py).

## Developer workflows

- Environment setup uses `uv` as described in [docs/CONTRIBUTING.md](../docs/CONTRIBUTING.md) (create venv, activate, `uv sync`).
- Python version is 3.13+ per [pyproject.toml](../pyproject.toml). Ruff config is defined there; keep line length at 140.
- Test/data exploration scripts include [tests/flat_events.py](../tests/flat_events.py) and [tests/add_to_db.py](../tests/add_to_db.py); treat these as executable examples rather than pytest suites.

## Integration points

- External ASR integration currently targets Google Speech-to-Text via `google-cloud-speech` in [yus/util.py](../yus/util.py).
- Visualization stack is intended to use Dash/Flask and Pandas (see dependencies in [pyproject.toml](../pyproject.toml) and architecture notes in [docs/architecture.md](../docs/architecture.md)).
