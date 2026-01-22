# YUS Usage Guide

## Transcribing Audio

YUS includes a command-line tool for transcribing audio files of game commentary into structured, timestamped transcripts.

### Basic Usage

```bash
yus-transcribe path/to/audio.wav
```

This will create a JSON transcript file in the same directory as your audio file.

### Common Options

```bash
yus-transcribe audio.wav \
  --sport ultimate/indoor \
  --model large-v3 \
  --recording-start "2025-01-14T20:30:00" \
  --team team_dump_and_drizzle.json \
  --team team_category_5.json \
  --output game_transcript.json
```

**Key Options:**

- `--sport` - Sport type for terminology (default: `ultimate/indoor`)
- `--model` - Whisper model size: `tiny`, `base`, `small`, `medium`, `large-v3` (default: `large-v3`)
- `--recording-start` - ISO timestamp when recording started (default: `now`)
- `--team` - Team JSON file path (can be specified multiple times for different teams)
- `--output` - Output file path (default: `<audio>.transcript.json`)
- `--text` - Write plain text instead of JSON
- `--start` - Start transcription at this time (seconds)
- `--stop` - Stop transcription at this time (seconds)
- `--quiet` - Suppress progress output
- `--print-transcript` - Print transcript text to stdout as it's produced

### Advanced Options

- `--language` - Language code (default: `en`)
- `--device` - Device to use: `auto`, `cpu`, `cuda` (default: `auto`)
- `--compute-type` - CTranslate2 compute type (default: `float32`)
- `--num-workers` - Number of worker threads (default: 1)
- `--cpu-threads` - Number of CPU threads (default: 8)
- `--no-vad` - Disable Voice Activity Detection (VAD is enabled by default to filter background noise)
- `--terms-file` - File with custom phrases (one per line) to bias the ASR toward
- `--prompt` - Additional prompt text to guide the ASR

## Team JSON Files

Team JSON files help improve transcription accuracy by teaching the Automatic Speech Recognition (ASR) system about:

1. **Player names** - So it recognizes "Federbusch" instead of hearing gibberish
2. **Nicknames** - So you can say "Pikachu" or "Matt Whitlock" interchangeably
3. **Mondegreens** - So "feather brush" gets corrected to "Federbusch"

> **What is a mondegreen?** A mondegreen is a mishearing or misinterpretation of a phrase,
> especially in speech recognition. The term comes from a mishearing of the phrase
> "laid him on the green" as "Lady Mondegreen" in a Scottish ballad. In YUS, mondegreens are
> common ASR mistakes that should be automatically corrected to the proper player name.

### Why Use Team Files?

When transcribing game commentary, proper names (especially unusual surnames) are often misheard by ASR systems.
Team files solve this by:

- **Biasing the ASR** - Including all player names and nicknames in the vocabulary hints to the ASR model
- **Post-processing corrections** - Automatically fixing common mishearings in the transcript
- **Name normalization** - Allowing you to reference players by different names during commentary

### Team JSON Format

A team JSON file describes one team and its players. Here's the basic structure:

```json
{
  "names": ["Team Name", "alternate name", "color"],
  "players": {
    "Full Name": ["Nickname"],
    "Another Player": {
      "nicknames": ["Nick"],
      "mondegreen": ["common", "mishearing"]
    }
  }
}
```

### Simple Example

```json
{
  "names": ["Flight Club", "white", "light"],
  "players": {
    "Sarah Johnson": ["SJ"],
    "Mike Chen": [],
    "Alex Rodriguez": ["A-Rod"]
  }
}
```

### Fields

**`names`** (array of strings) - List of names for the team:

- Official team name
- Abbreviations
- Common color references (jersey colors)

**`players`** (object) - Player roster where keys are official full names and values can be:

1. **Simple array** - Just nicknames: `["Nickname1", "Nickname2"]`
2. **PlayerInfo object** with:
   - `nicknames` (array) - Alternative names you might use during commentary
   - `mondegreen` (array) - Common ASR mistakes (mondegreens) that should be corrected to the official name

**Empty arrays** (`[]`) are fine for players with no nicknames or mondegreens - it still helps the ASR know that name exists.

### Creating Team Files

1. **Start with the roster** - Get the official full names of all players
2. **Add common nicknames** - How do you actually refer to players during a game?
3. **Test transcription** - Run `yus-transcribe` on a sample
4. **Note mondegreens** - Review the transcript for mangled names
5. **Add corrections** - Update the `mondegreen` fields for any persistent mistakes
6. **Re-run transcription** - Your transcript should now be cleaner

### Tips for Better Transcription

- **Use both teams** - Specify team files for both teams playing: `--team team1.json --team team2.json`
- **Include jersey numbers** - If you reference players by number, add those as nicknames:
  `"Matt Whitlock": ["Pikachu", "14"]`
- **Physical descriptions** - If you don't know everyone's name yet, use distinctive features as
  temporary "nicknames": `"Unknown Player": ["red shorts", "tall guy"]`
- **Lower case in mondegreen** - The correction is case-insensitive, so you can use lowercase for mondegreens
- **First and last names** - Individual first/last names are automatically extracted, so
  "Adam Federbusch" makes both "Adam" and "Federbusch" available

### Using Multiple Team Files

You can specify multiple team files in a single transcription:

```bash
yus-transcribe game.wav \
  --team home_team.json \
  --team away_team.json \
  --team referees.json
```

All player names and corrections from all teams will be combined.

### Reusing Team Files

Once you create a team JSON file, you can reuse it for any game that team plays in.
Build up a library of team files for your league or tournament, and your transcriptions will get progressively better!

### Example Team File Locations

```txt
my_games/
  teams/
    flight_club.json
    category_5.json
    dump_and_drizzle.json
  recordings/
    2025-01-14_game1.wav
    2025-01-15_game2.m4a
```

Then transcribe with:

```bash
yus-transcribe recordings/2025-01-14_game1.wav \
  --team teams/dump_and_drizzle.json \
  --team teams/category_5.json
```

## Output Formats

### JSON Output (Default)

The default output is a structured JSON file containing:

- Transcript groups (sections of continuous speech)
- Multiple interpretations per group (if ASR provides alternatives)
- Individual words with timestamps and confidence scores

This format preserves all timing and confidence information for downstream processing.

### Text Output

Use `--text` for a simple tab-separated format:

```txt
START_TIME    END_TIME    TEXT
2025-01-14T20:31:12.800    2025-01-14T20:31:14.600    picked up by pikachu
2025-01-14T20:31:15.700    2025-01-14T20:31:17.200    backhand to glasses
```

This is easier for human review but loses individual word timing and confidence data.

## Next Steps

After transcription, the structured transcript can be:

1. **Reviewed and corrected** - Check for any remaining errors
2. **Converted to events** - Extract game actions (throws, scores, etc.)
3. **Analyzed for statistics** - Generate player and team stats
4. **Visualized** - Create interactive game visualizations

See the project documentation for information on event extraction and statistics generation.
