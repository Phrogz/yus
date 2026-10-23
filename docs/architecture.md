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
     ([live_transcription.md](live_transcription.md)); in `yus-serve`, commentators take turns on the GPU, each decoding
     less often as more are live ([server.md](server.md)). Word error rate on the test game: 0.10 for the whole recording,
     0.11–0.15 live ([results.md](results.md)).
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
   * **Built:** `EventExtractor`, rules that produce `Throw`, `Defense` and `Substitution` events, in a batch (`yus-events`)
     or live, with names as spoken ([extraction.md](extraction.md)). A correction takes back what it contradicts in the most
     recent throw ("in the end zone? nope, not in", "sorry, to tristan"), and a throw whose players are only on the other
     team's roster moves to that team. `yus-score` compares a stream with ground truth. An optional local-LLM second
     reading (`--llm`) is off by default.
   * **Not built:** `Infraction` events; corrections of a throw type or of anything before the latest throw; phrasings of
     other commentators ([extraction.md](extraction.md#limitations)); the LLM-based extractor first proposed in
     [event_extraction_design.md](event_extraction_design.md). Line-ups said as substitutions are read only with
     `lineups=True`, off because the bundled ground truth lacks them.
6. _Event Unification_
   * One or more event streams for a single game become one official stream.
   * **Built:**
     * Player resolution (`PlayerResolver`): maps the names each commentator used ("pikachu", "the kid") to roster players,
       from the team files and a per-game descriptions file ([usage.md](usage.md#game-description-files)). Names it cannot
       resolve are listed for a person to identify. Live, a description or a spoken identification ("red shorts is Kaia")
       re-resolves earlier events. A name that only the other team's player answers to resolves to that player, and
       `team_conflicts()` lists those events; they keep their team.
     * Merging (`merge_streams`, and `LiveMerger` live): estimates each commentator's clock offset, pairs events that
       describe the same action, settles conflicts, and repairs outcomes from the game's grammar ([merging.md](merging.md)).
       A score one commentator heard stands when the other heard that throw as two.
     * `yus-game` merges a game's recordings or transcripts afterwards ([postgame.md](postgame.md)).
   * **Not built:** fuzzy name matching; unifying the labels commentators give unknown players; correcting the teams that
     `team_conflicts()` finds. Merging was tested only on synthetic streams and on one recording streamed twice.
7. `DataFrame`(s)
   * The official event stream becomes `pandas.DataFrame`s.
   * **Built:** `compute_stats` and `yus-stats`: box scores, points, possessions, the running score, throw types and
     directions, and who throws to whom; from substitutions, who is on the field: points played, playing time, plus-minus
     and lines ([stats.md](stats.md)).
   * **Not built:** stalls, fouls and callahans. On-field tracking was measured only offline, on one commentary of
     substitutions with a draft ground truth.
8. `Dash` components
   * Web pages that show the stats, built from filtered, grouped and aggregated event data.
   * **Built:** `GameSession` runs phases 5–7 live for one game and saves it ([session.md](session.md)). With several
     commentators, a merged event settles once every commentator has gone quiet past it. `yus-serve` serves the commentate,
     score and admin pages, and the Dash dashboard ([dashboard.md](dashboard.md)). `yus-game` writes an HTML report and CSV
     tables.
   * **Not built:** a dark theme and partial updates for the dashboard.

![class relationships](img/architecture-classes.png)

## End-to-End Results

The whole live pipeline, from audio streamed to `yus-serve` to the official stream and stats, was run in real time on the
real audio of the 2025-01-14 20:30 game (one commentator, 16 minutes) on an M3 Pro. See [results.md](results.md) for the
numbers, what went wrong, and how to reproduce them.

- **One commentator.** Event F1 0.975 (exact 0.817), final score 14–10 against 14–9, word error rate 0.115. Events showed
  a median 8.3 s after they were said and settled after 11.6 s. The GPU was busy 50% of the time.
- **Two commentators at once** (the same audio twice, 5 s apart). Merged event F1 0.966 (exact 0.809), final score 14–9.
  Taking turns, each decoding every 4.5 s, they kept the GPU 65% busy (98% when both decoded every 3 s). Events showed
  after a median 10.4 s and settled after 23.3 s (34.1 s in the run before the turns and the quiet settling).
- **Throughout:** the pages answered while live, no settled event changed, and reloading the saved game reproduced the final
  state. Today's extractor gives the same events from these runs' transcripts.
- **Not measured live:** substitutions and on-field tracking (this game's commentary has none); see
  [extraction.md](extraction.md#substitutions) and [stats.md](stats.md#measured).
