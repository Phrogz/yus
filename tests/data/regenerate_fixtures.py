"""Regenerate the JSON fixtures from the Python ground truth in gruindoor_20250114T2030.py.

Run after editing the ground truth:  python -m tests.data.regenerate_fixtures
"""

import json
import pathlib

from tests.data.gruindoor_20250114T2030 import build_game

DATA = pathlib.Path(__file__).parent


def fixture_texts() -> dict[pathlib.Path, str]:
    """The exact text each fixture file should contain."""
    game = build_game()
    return {
        DATA / "gruindoor_20250114T2030-transcript.json": json.dumps(game.transcripts[0].model_dump(mode="json"), indent=2) + "\n",
        DATA / "gruindoor_20250114T2030-eventstream.json": json.dumps(game.event_streams[0].model_dump(mode="json"), indent=2) + "\n",
    }


def main() -> None:
    for path, text in fixture_texts().items():
        changed = not path.exists() or path.read_text() != text
        path.write_text(text)
        print(f"{'updated' if changed else 'unchanged'}: {path.name}")


if __name__ == "__main__":
    main()
