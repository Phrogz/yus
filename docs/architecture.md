# Architecture of YUS

## Data Overview by Phases

![visual flow of data and processing](img/architecture-flow.png)

Each phase says what it is, what is built, and what is not. The [README](../README.md#running-yus) shows how to run it all.

1. `Terms` (by sport)
   * Words and phrases likely to be said by commentators, and how speech recognition mishears them (mondegreens).
   * **Built:** indoor Ultimate's weighted terms and mondegreens (`yus/sports/ultimate`), which prime Whisper's prompt
     ([usage.md](usage.md#how-the-prompt-is-built)) and correct its transcripts.
   * **Not built:** other sports.
2. `Game`
   * The sport, the time of the game, and the teams: their names and colors, and their players' names, nicknames and
     mondegreens.
   * **Built:** `yus.Game`, `yus.Team` and team JSON files ([usage.md](usage.md#team-json-files)).
3. Play-by-Play
   * One mono audio stream per commentator.
   * **Built:** recordings, processed afterwards; live audio from phones, streamed to `yus-serve` and saved as WAV
     ([server.md](server.md)); `yus-replay`, which streams a recording as a phone would.
   * **Not tried:** real phones (only headless Chrome so far). HTTPS for phones is set up by hand
     ([server.md](server.md#https-for-phones)).
4. `Transcript`
   * Groups of words (bursts of speech); each word has a time and a confidence.
   * **Built:** Whisper (mlx-whisper large-v3-turbo on Apple Silicon, faster-whisper elsewhere). `yus-transcribe` handles a
     recording ([usage.md](usage.md)). `LiveTranscriber` transcribes live audio a few seconds behind the speaker
     ([live_transcription.md](live_transcription.md)). Word error rate on the test game: 0.10 for the whole recording,
     0.11–0.14 live.
   * **Not built:** alternative interpretations (each group has one), and models trained for a sport. A Google
     Speech-to-Text adapter (`yus/util.py`) predates Whisper and is unused.
5. `EventStream`
   * Each `Transcript` becomes a sequence of sport-specific events. For indoor Ultimate:
       * `Event` (base class): timestamp, duration, player 'name', player's team.
       * `Throw`: throw type (e.g. `flick`), throw direction (e.g. `dump`), receiver 'name',
         outcome (e.g. caught, dropped, turfed), did it hit the wall, or netting, was it a score.
       * `Defense`: whether it was caught by player (or just prevented the catch).
       * `Substitution`: subbing off or on to the field
       * `Infraction`: TBD
   * **Built:** `EventExtractor`, rules that produce `Throw` and `Defense` events, in a batch (`yus-events`) or live, with
     names as spoken; `yus-score` compares a stream with ground truth ([extraction.md](extraction.md)).
   * **Not built:** `Substitution` and `Infraction` events; taking a fact back ("in the end zone? nope"); phrasings of
     commentators other than the one recorded ([extraction.md](extraction.md#limitations)); the LLM-based extractor first
     proposed in [event_extraction_design.md](event_extraction_design.md).
6. _Event Unification_
   * One or more event streams for a single game become one official stream.
   * **Built:**
     * Player resolution (`PlayerResolver`): maps the names each commentator used ("pikachu", "the kid") to roster players,
       from the team files and a per-game descriptions file ([usage.md](usage.md#game-description-files)). Names it cannot
       resolve are listed for a person to identify. Live, a description or a spoken identification ("red shorts is Kaia")
       re-resolves earlier events.
     * Merging (`merge_streams`, and `LiveMerger` live): estimates each commentator's clock offset, pairs events that
       describe the same action, settles conflicts, and repairs outcomes from the game's grammar ([merging.md](merging.md)).
   * **Not built:** fuzzy name matching; unifying the labels commentators give unknown players; a command to merge recorded
     streams. Merging was tested only on synthetic streams and on one recording streamed twice.
7. `DataFrame`(s)
   * The official event stream becomes `pandas.DataFrame`s.
   * **Built:** `compute_stats` and `yus-stats`: box scores, points, possessions, the running score, throw types and
     directions, and who throws to whom ([stats.md](stats.md)).
   * **Not built:** line tracking (points played, plus-minus); stalls, fouls and callahans.
8. `Dash` components
   * Web pages that show the stats, built from filtered, grouped and aggregated event data.
   * **Built:** `GameSession` runs phases 5–7 live for one game and saves it ([session.md](session.md)). `yus-serve`
     serves the commentate, score and admin pages, and the Dash dashboard ([dashboard.md](dashboard.md)).
   * **Not built:** a dark theme and partial updates for the dashboard.

![class relationships](img/architecture-classes.png)

## End-to-End Results

The whole live pipeline, from audio streamed to `yus-serve` to the official stream and stats, was run in real time on the
real audio of the 2025-01-14 20:30 game (one commentator, 16 minutes) on an M3 Pro. See [results.md](results.md) for the
numbers, what went wrong, and how to reproduce them.

- **One commentator.** Event F1 0.975 (exact 0.792), final score 14–11 against 14–9, word error rate 0.117. Events showed
  a median 8.1 s after they were said and settled after 11.1 s. The GPU was busy 49% of the time.
- **Two commentators at once** (the same audio twice). Merged event F1 0.968–0.975 (exact 0.79–0.80), final score 13–10.
  The GPU was 97–99% busy, and events showed after 9–10 s. Settling took a median 44 s, and 31 s after a fix in the session.
- **Throughout:** the dashboard and admin pages answered while live, and reloading the saved game reproduced the final state.
