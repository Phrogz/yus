# Event Extraction Design Document

## Overview

This document outlines the approach for `yus-events`, a command-line tool that converts timestamped transcripts
(produced by `yus-transcribe`) into structured event streams for game analysis.

## Goal

Convert spoken play-by-play commentary like:

> *"picked up by pikachu backhand to glasses flick to kaia deed by somebody on dark"*

Into structured events:

```python
Throw(when=..., team="white", player="pikachu", type=BACKHAND, receiver="glasses", completed=True, scored=False)
Throw(when=..., team="white", player="glasses", type=FLICK, receiver="kaia", completed=False, scored=False)
Defense(when=..., team="dark", player=None, intercepted=False)
```

---

## Input/Output Flow

```txt
┌─────────────────────┐      ┌──────────────────────┐      ┌─────────────────────┐
│   Audio File        │      │   Transcript JSON    │      │   Events JSON       │
│   (game.wav)        │─────▶│   (game.transcript.  │─────▶│   (game.events.     │
│                     │      │    json)             │      │    json)            │
│                     │      │                      │      │                     │
│                     │      │  • Word timestamps   │      │  • Throw events     │
│                     │      │  • Confidence scores │      │  • Defense events   │
│                     │      │  • Grouped phrases   │      │  • Substitutions    │
│                     │      │                      │      │  • Infractions      │
└─────────────────────┘      └──────────────────────┘      └─────────────────────┘
     yus-transcribe                yus-events
```

---

## Data Structures Recap

### Input: Transcript JSON

The transcript JSON contains:

```json
{
  "game": null,
  "commentator": null,
  "groups": [
    {
      "interpretations": [
        {
          "confidence": 0.75,
          "words": [
            { "text": "picked", "confidence": 0.9, "start": "2025-01-14T20:31:12.8", "duration": "PT0.3S" },
            { "text": "up", "confidence": 0.92, "start": "2025-01-14T20:31:13.1", "duration": "PT0.3S" },
            { "text": "by", "confidence": 0.88, "start": "2025-01-14T20:31:13.4", "duration": "PT0.3S" },
            { "text": "pikachu", "confidence": 0.92, "start": "2025-01-14T20:31:13.7", "duration": "PT0.9S" }
          ]
        }
      ]
    }
  ]
}
```

### Output: Event Types (Indoor Ultimate)

From [yus/sports/ultimate/__init__.py](../yus/sports/ultimate/__init__.py) and [yus/sports/ultimate/indoor.py](../yus/sports/ultimate/indoor.py):

| Event Type    | Key Fields                                                                          |
| ------------- | ----------------------------------------------------------------------------------- |
| `Throw`       | when, team, player, type, direction, receiver, completed, scored, hit_wall, hit_net |
| `Defense`     | when, team, player, intercepted                                                     |
| `Substitution`| when, team, player, sub_type (SUB_ON/SUB_OFF)                                       |
| `Infraction`  | when, team, player (details TBD)                                                    |

---

## Proposed Approach: Local LLM with Structured Output

### Why a Local LLM?

1. __Natural Language Understanding__ – Commentary is fast, informal, elliptical. Traditional parsers fail on:
   - *"pikachu backhand glasses flick tristan hammer!"* (implicit receivers, no "to")
   - *"off the wall no score"* (context from prior throw needed)

2. __Context Propagation__ – The LLM maintains state:
   - *"backhand to glasses"* → knows team is still "white" from earlier
   - *"deed by somebody"* → creates Defense event on opposing team

3. __Privacy & Offline__ – Runs entirely on the user's machine; no internet required.

4. __Customizability__ – Fine-tuning is possible for specific sports or commentators.

### Candidate Local LLM Engines

| Engine               | Pros                                           | Cons                              |
| -------------------- | ---------------------------------------------- | --------------------------------- |
| __llama.cpp__        | Fast, GGUF support, Apple Silicon optimized    | Python bindings vary              |
| __Ollama__           | Easy install, model management, REST API       | Extra daemon, slightly slower     |
| __vLLM__             | Very fast, batching, OpenAI-compatible         | Heavier, GPU-focused              |
| __mlx-lm__           | Native Apple Silicon, fast                     | macOS only                        |
| __llama-cpp-python__ | Direct Python bindings to llama.cpp            | Good balance of speed and control |

__Recommended__: Start with __Ollama__ for ease of setup and model management, with a fallback to __llama-cpp-python__ for tighter integration and lower overhead.

### Model Selection

| Model                  | Size     | Notes                                  |
| ---------------------- | -------- | -------------------------------------- |
| __Mistral 7B__         | ~4-5 GB  | Good balance of speed and capability   |
| __Llama 3 8B__         | ~5 GB    | Strong reasoning, structured output    |
| __Phi-3 Mini (3.8B)__  | ~2.5 GB  | Very fast, surprisingly capable        |
| __Qwen2.5 7B__         | ~4.5 GB  | Excellent at following instructions    |

__Recommended__: Start with __Mistral 7B Instruct__ or __Qwen2.5 7B Instruct__ (both handle structured JSON output well).

---

## Implementation Plan

### Phase 1: Structured Prompt Design

Design a system prompt that instructs the LLM to:

1. Parse transcript groups sequentially
2. Maintain state (current team with possession, last player with disc)
3. Output structured JSON events

__Example System Prompt:__

```markdown
You are an expert at extracting Ultimate Frisbee game events from spoken play-by-play commentary.

Your task: Convert transcript text into structured game events.

CONTEXT you must track:

- Current team with possession (offense)
- Last player to have the disc

EVENT TYPES to emit:

1. Throw: `{"type": "Throw", "team": "...", "player": "...", "throw_type": "flick|backhand|hammer|scoober|blade|chicken_wing", "direction": "dump|swing|up_line|cross_field|huck", "receiver": "...", "completed": true/false, "scored": true/false, "hit_wall": true/false, "hit_net": true/false}`
2. Defense: `{"type": "Defense", "team": "...", "player": "...", "intercepted": true/false}`
3. Substitution: `{"type": "Substitution", "team": "...", "player": "...", "sub_type": "on|off"}`

RULES:

- "picked up by X" → X now has disc; implies completed throw unless this is turnover pickup
- "deed" or "D" or "intercepted by" → Defense event on opposing team
- "for a score" or "end zone" with catch → scored=true
- "dropped" or "turf" or "turfed" → completed=false
- "off the wall" or "off the glass" → hit_wall=true
- Team is inferred from player name or context; "for white", "on dark" indicates team

For each transcript group, output ONLY a JSON array of events. Include a "timestamp" field from the first word.
```

### Phase 2: Core Script Implementation

```txt
yus/processing/event_extraction/
├── __init__.py
├── extract.py          # Main script (yus-events entrypoint)
├── prompts.py          # System prompts and templates per sport
├── llm_backends/
│   ├── __init__.py
│   ├── base.py         # Abstract base class for LLM backends
│   ├── ollama.py       # Ollama integration
│   └── llamacpp.py     # llama-cpp-python integration
└── event_parser.py     # Parse LLM JSON output into yus Event objects
```

__CLI Interface:__

```bash
yus-events game.transcript.json \
  --sport ultimate/indoor \
  --model mistral:7b-instruct-v0.3-q4_K_M \
  --backend ollama \
  --team team1.json --team team2.json \
  --output game.events.json
```

__Key Options:__

| Option             | Description                                            |
| ------------------ | ------------------------------------------------------ |
| `--sport`          | Sport type for event schema (default: ultimate/indoor) |
| `--model`          | LLM model name (Ollama tag or GGUF path)               |
| `--backend`        | `ollama` or `llamacpp` (default: ollama)               |
| `--team`           | Team JSON for player name resolution                   |
| `--output`         | Output path (default: `<input>.events.json`)           |
| `--context-window` | How many past groups to include for context            |

### Phase 3: Processing Pipeline

```txt
┌───────────────────────────────────────────────────────────────────────────┐
│                        Event Extraction Pipeline                          │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  1. Load transcript JSON → yus.Transcript object                          │
│     - Uses Pydantic model_validate() for deserialization                  │
│     - Back-references restored automatically via model_post_init hooks    │
│                                                                           │
│  2. Load team files → yus.Team objects for player name validation         │
│                                                                           │
│  3. For each transcript group:                                            │
│     a. Build prompt with:                                                 │
│        - System instructions                                              │
│        - Prior N groups (sliding window for context)                      │
│        - Current group's text and word timestamps                         │
│        - Current game state (possession, last player)                     │
│     b. Call local LLM                                                     │
│     c. Parse JSON response into Event objects                             │
│     d. Validate and fix player names against team rosters                 │
│     e. Update game state based on events                                  │
│                                                                           │
│  4. Assemble all events into yus.EventStream                              │
│                                                                           │
│  5. Write EventStream as JSON via model_dump(mode="json")                 │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
```

### JSON Round-Trip Serialization

The Pydantic models in `yus/__init__.py` support seamless JSON round-trip:

__Excluded Back-References__ (via `exclude=True` on fields):

- `Transcript.game` – back-reference to parent Game
- `TranscriptGroup.transcript` – back-reference to parent Transcript
- `Interpretation.group` – back-reference to parent TranscriptGroup

__Restored on Load__ (via `model_post_init` hooks):

- `Transcript.model_post_init()` restores `group.transcript` for all groups
- `TranscriptGroup.model_post_init()` restores `interp.group` for all interpretations

__Loading a Transcript:__

```python
import json
import yus

transcript_data = json.loads(path.read_text())
transcript = yus.Transcript.model_validate(transcript_data)
# Back-references are now restored and usable
```

__Saving an EventStream:__

```python
import json

event_json = event_stream.model_dump(mode="json")
path.write_text(json.dumps(event_json, indent=2))
```

### Phase 4: Output Format

The output will be a JSON-serialized `EventStream`:

```json
{
  "game": null,
  "transcript": null,
  "events": [
    {
      "type": "Throw",
      "when": "2025-01-14T20:31:15.7",
      "team": "white",
      "player": "pikachu",
      "throw_type": "backhand",
      "direction": null,
      "receiver": "glasses",
      "completed": true,
      "scored": false,
      "hit_wall": false,
      "hit_net": false
    },
    {
      "type": "Defense",
      "when": "2025-01-14T20:31:34.35",
      "team": "dark",
      "player": null,
      "intercepted": false
    }
  ]
}
```

---

## Challenges & Mitigations

| Challenge                            | Mitigation                                              |
| ------------------------------------ | ------------------------------------------------------- |
| Player names not in team roster      | Fuzzy match to roster; flag unresolved for review       |
| Context loss across groups           | Include sliding window of N prior groups in prompt      |
| Ambiguous team attribution           | Track possession state; require explicit "for dark" etc |
| LLM outputs malformed JSON           | Use JSON repair library; retry with stricter prompt     |
| Hallucinated events                  | Post-validate event sequences make sense temporally     |
| Performance (slow inference)         | Use quantized models (Q4_K_M); batch processing         |

---

## Testing Strategy

1. __Unit tests__ – Mock LLM responses; test JSON parsing and event construction
2. __Ground truth comparison__ – Compare output against `build_raw_stream()` in test data
3. __Metrics__:
   - Event count accuracy
   - Player name accuracy
   - Throw type/direction accuracy
   - Completion/score accuracy
4. __Regression suite__ – Store known-good event JSONs; fail if output changes unexpectedly

---

## Dependencies

Add to `pyproject.toml`:

```toml
dependencies = [
    # ... existing ...
    "ollama>=0.4.0",        # Ollama Python client
    # OR for llama-cpp:
    # "llama-cpp-python>=0.3.0",
]
```

__External requirements:__

- Ollama installed and running (`brew install ollama && ollama serve`)
- Model downloaded (`ollama pull mistral:7b-instruct-v0.3-q4_K_M`)
  - If the requested model is not downloaded, download it automatically.
  - If the requested model is not legal, raise an error and list available models.

---

## Next Steps (After Review)

1. [ ] Approve overall approach
2. [ ] Implement `extract.py` CLI skeleton
3. [ ] Build Ollama backend with structured prompts
4. [ ] Create simple test harness with simple transcript input
5. [ ] Test on `gruindoor_20250114T2030` transcript → compare to ground truth
6. [ ] Iterate on prompts based on accuracy
7. [ ] Add llama-cpp-python backend as alternative
8. [ ] Document in `usage.md`

---

## Open Questions

1. __Should we support non-LLM fallback?__ (e.g., rule-based regex parser for simpler cases)
   - Answer: Not until we see a strong need; focus on LLM first.
2. __How to handle multiple commentators?__ (different transcript → different event streams → unification)
   - Answer: Unification is a separate step; `yus-events` focuses on single transcript → event stream.
3. __Fine-tuning?__ If Ollama/llama.cpp accuracy is insufficient, consider fine-tuning on ground truth data.
   - Answer: Potential future enhancement; start with prompt engineering first.

---

## References

- [YUS Architecture](architecture.md)
- [Contributing Guide](CONTRIBUTING.md)
- [Usage Guide](usage.md)
- [Test Data: gruindoor_20250114T2030.py](../tests/data/gruindoor_20250114T2030.py) – ground truth events
