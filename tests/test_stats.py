import datetime
import pathlib
import re
import time

import pandas as pd
import pytest

import yus
from tests.data.gruindoor_20250114T2030 import TEAM_FILES, build_game
from yus.processing.stats import GameStats, compute_stats
from yus.processing.stats import cli
from yus.sports import ultimate
from yus.sports.ultimate import indoor

DATA = pathlib.Path(__file__).parent / "data"
EVENTS = DATA / "gruindoor_20250114T2030-eventstream.json"  # the raw stream: names as spoken
DESCRIPTIONS = DATA / "gruindoor_20250114T2030-descriptions.json"
WHITE, BLACK = "Dump & Drizzle", "Category 5"  # labels when the teams are given


@pytest.fixture(scope="module")
def game() -> yus.Game:
    return build_game()


@pytest.fixture(scope="module")
def stats(game: yus.Game) -> GameStats:
    assert game.official_stream is not None
    return compute_stats(game.official_stream)


@pytest.fixture(scope="module")
def phrases(game: yus.Game) -> list[tuple[datetime.datetime, str]]:
    """(start, text) of each group of the hand-made transcript: an independent source for the numbers the stats derive."""
    return [(group.start, " ".join(word.text for word in group.words)) for group in game.transcripts[0].groups]


def said(phrases: list[tuple[datetime.datetime, str]], pattern: str) -> int:
    return sum(len(re.findall(pattern, text)) for _, text in phrases)


def throw(team: str, player: str | None, receiver: str | None, completed: bool = True, scored: bool = False, second: float = 0.0) -> indoor.Throw:
    when = datetime.datetime(2025, 1, 14, 20, 31) + datetime.timedelta(seconds=second)
    return indoor.Throw(when=when, team=team, player=player, receiver=receiver, completed=completed, scored=scored)


# --- key numbers, cross-checked against the transcript words ---


def test_score_matches_scoring_phrases(stats: GameStats, phrases):
    # Every goal is "... for a score", except one said as "in the end zone caught by hat" ("nope, not in the end zone caught by" is no goal).
    goals = said(phrases, r"\bfor a score\b") + said(phrases, r"(?<!not )in the end zone caught by")
    assert goals == 23
    assert stats.score == {"white": 14, "black": 9}
    assert len(stats.score_timeline) == goals
    assert stats.score_timeline.iloc[-1][["score_white", "score_black"]].tolist() == [14, 9]
    assert stats.summary() == "white 14, black 9 (point 24 in play)"  # the recording ends mid-point


def test_ds_match_deed_and_stolen(stats: GameStats, phrases):
    assert len(stats.defenses) == said(phrases, r"\b(deed|stolen)\b") == 9
    assert stats.defenses["intercepted"].sum() == said(phrases, r"\bstolen\b") == 2
    assert stats.team_box["ds"].to_dict() == {"white": 5, "black": 4}
    assert stats.team_box["interceptions"].sum() == 2
    # a D is made by the team not in possession, and ends that possession
    possessions = stats.possessions.loc[stats.defenses["possession"]]
    assert (possessions["team"].to_numpy() != stats.defenses["team"].to_numpy()).all()
    assert (possessions["outcome"] == "turnover").all()


def test_turnovers_match_announced_incompletions(stats: GameStats, phrases):
    # every incomplete throw was announced as a D, a drop, a turf, or "no score"
    announced = sum(bool(re.search(r"\b(deed|stolen|dropped|turf|turfed|no score)\b", text)) for _, text in phrases)
    assert announced == stats.team_box["turnovers"].sum() == 21
    assert stats.team_box["turnovers"].to_dict() == {"white": 8, "black": 13}


def test_pickups_said_for_a_team_start_its_possessions(stats: GameStats, phrases):
    pickup = re.compile(r"\bpick(?:s|ed)?(?: it)? up\b(?: by [a-z ]+?)? (?:for|on) (white|dark|black)\b|\bchecks in for (white|dark|black)\b")
    throws = stats.throws
    firsts = set(throws.groupby("possession").head(1).index)
    checked = 0
    for start, text in phrases:
        if match := pickup.search(text):
            team = {"dark": "black"}.get(match.group(1) or match.group(2), match.group(1) or match.group(2))
            first = throws[throws["when"] >= start].iloc[0]
            assert (first["team"], first.name in firsts) == (team, True), text
            checked += 1
    assert checked == 32


def test_player_numbers_match_transcript(stats: GameStats, phrases):
    box = stats.player_box
    assert box.loc[("white", "Serayan Knappe-Butler"), "goals"] == said(phrases, r"\bthe kid for a score\b") == 3
    assert box.loc[("white", "Stephen Butler"), ["ds", "interceptions"]].tolist() == [said(phrases, r"\b(deed|stolen) by stephen butler\b"), 1] == [2, 1]
    assert box.loc[("black", "gloves"), ["ds", "interceptions"]].tolist() == [said(phrases, r"\b(deed|stolen) by gloves\b"), 1] == [2, 1]
    assert box.loc[("white", "Kaia Mann"), "drops_or_misses"] == said(phrases, r"\bto kaia (dropped|deed)\b") == 3
    # "backhand to yellow border", "backhand federbusch", "to naked for a score": assist federbusch, hockey assist yellow sleeve
    assert stats.score_timeline.loc[1, ["team", "assist", "scorer", "hockey_assist"]].tolist() == ["black", "Adam Federbusch", "Collin Ruprecht", "yellow sleeve"]
    assert box.loc[("black", "Adam Federbusch"), ["throws", "completions", "assists", "turnovers"]].tolist() == [14, 13, 5, 1]
    assert box["hockey_assists"].sum() == stats.score_timeline["hockey_assist"].notna().sum() == 18


def test_points_holds_and_breaks(stats: GameStats):
    points = stats.points
    assert len(points) == 24
    assert points.loc[1, ["o_team", "scored_by", "hold"]].tolist() == ["white", "black", False]  # black pulled; white turned it over
    assert points.loc[1, "start"] == pd.Timestamp("2025-01-14T20:31:11.5")  # the pull: the game's start
    assert (points["start"].iloc[1:].to_numpy() == points["end"].iloc[:-1].to_numpy()).all()
    assert points["duration_s"].sum() == pytest.approx((points["end"].iloc[-1] - points["start"].iloc[0]).total_seconds())
    assert pd.isna(points.loc[24, "hold"]) and points.loc[24, "scored_by"] is None
    box = stats.team_box
    assert box[["holds", "breaks", "o_points", "d_points"]].to_dict("index") == {
        "white": {"holds": 6, "breaks": 8, "o_points": 10, "d_points": 14},
        "black": {"holds": 6, "breaks": 3, "o_points": 14, "d_points": 10},
    }


# --- invariants ---


def test_team_box_invariants(stats: GameStats):
    box = stats.team_box
    assert (box["completions"] + box["turnovers"] == box["throws"]).all()
    assert (box["holds"] + box["breaks"] == box["goals"]).all()
    assert (box["o_points"] + box["d_points"] == len(stats.points)).all()
    assert box["throws"].sum() == len(stats.throws)
    assert box["possessions"].sum() == len(stats.possessions) == 44
    assert stats.points["scored_by"].value_counts().to_dict() == stats.score == box["goals"].to_dict()
    assert box["goals_per_possession"].to_dict() == {"white": round(14 / 22, 2), "black": round(9 / 22, 2)}
    assert box[["hucks", "huck_completions", "wall_throws", "net_throws"]].to_dict("index") == {
        "white": {"hucks": 9, "huck_completions": 6, "wall_throws": 2, "net_throws": 0},
        "black": {"hucks": 9, "huck_completions": 4, "wall_throws": 4, "net_throws": 0},
    }


def test_possessions_alternate(stats: GameStats):
    teams = stats.possessions["team"].tolist()
    assert all(a != b for a, b in zip(teams, teams[1:]))
    # indoor: the team scored on picks up
    points = stats.points
    assert (points["o_team"].iloc[1:].to_numpy() != points["scored_by"].iloc[:-1].to_numpy()).all()
    assert stats.possessions["outcome"].value_counts().to_dict() == {"goal": 23, "turnover": 21}
    assert not stats.points["suspect"].any()


def test_points_where_the_scorers_pick_up_are_suspect():
    # Indoor, the team scored on picks up; a point the scorers start points to a wrong goal or team in the events.
    stream = yus.EventStream(events=[throw("white", "kaia", "joe", scored=True), throw("white", "joe", "kaia", second=20), throw("white", "kaia", "joe", scored=True, second=25)])
    stream.add(throw("black", "hat", "bush", second=40))
    stats = compute_stats(stream)
    assert stats.points["suspect"].tolist() == [False, True, False]
    assert stats.points["o_team"].tolist() == ["white", "white", "black"]  # o_team still says what the events say


def test_unknown_players_count_for_their_team_only(stats: GameStats):
    throws, defenses, box = stats.throws, stats.defenses, stats.team_box
    players = stats.player_box.groupby(level="team").sum()
    assert not stats.player_box.index.get_level_values("player").isna().any()
    for team in stats.teams:
        mine = throws[throws["team"] == team]
        assert players.loc[team, "throws"] + mine["player"].isna().sum() == box.loc[team, "throws"]
        assert players.loc[team, "turnovers"] + (mine["player"].isna() & ~mine["completed"]).sum() == box.loc[team, "turnovers"]
        assert players.loc[team, "assists"] + (mine["player"].isna() & mine["scored"]).sum() == box.loc[team, "goals"]
        assert players.loc[team, "goals"] + (mine["receiver"].isna() & mine["scored"]).sum() == box.loc[team, "goals"]
        assert players.loc[team, "ds"] + (defenses["player"].isna() & (defenses["team"] == team)).sum() == box.loc[team, "ds"]
    assert (stats.player_box["targets"] == stats.player_box["catches"] + stats.player_box["drops_or_misses"]).all()
    known = throws.dropna(subset=["player", "receiver"])
    assert stats.connections["throws"].sum() == len(known)
    assert stats.connection_matrix("white").loc["glasses", "Tristan Weber"] == 7


def test_breakdowns_partition_the_throws(stats: GameStats):
    for table in (stats.throw_types, stats.directions):
        totals = table.groupby(level="team")[["throws", "completions", "goals", "turnovers"]].sum()
        pd.testing.assert_frame_equal(totals.loc[stats.teams], stats.team_box[["throws", "completions", "goals", "turnovers"]], check_names=False)
    assert stats.throw_types.loc[("white", "unknown"), "throws"] == 5
    assert stats.directions.loc[("black", "huck"), ["throws", "completions"]].tolist() == [9, 4]


def test_names_do_not_change_team_stats(game: yus.Game, stats: GameStats):
    raw = compute_stats(game.event_streams[0])  # names as spoken
    pd.testing.assert_frame_equal(raw.team_box, stats.team_box)
    pd.testing.assert_frame_equal(raw.points.drop(columns=["assist", "scorer"]), stats.points.drop(columns=["assist", "scorer"]))


def test_tables_keep_their_dtypes(stats: GameStats):
    assert stats.throws.dtypes[["completed", "scored", "hit_wall", "hit_net", "provisional"]].eq(bool).all()
    assert pd.api.types.is_bool_dtype(stats.defenses.dtypes["intercepted"])
    assert str(stats.defenses.dtypes["possession"]) == "Int64"
    assert str(stats.points.dtypes["hold"]) == "boolean"
    assert str(stats.throws.dtypes["when"]) == "datetime64[ns]"
    assert stats.player_box.dtypes[["throws", "goals", "ds"]].eq("int64").all()


# --- live use ---


def test_full_recompute_is_fast(game: yus.Game):
    assert game.official_stream is not None
    best = min(_seconds(lambda: compute_stats(game.official_stream, game.teams)) for _ in range(5))
    assert best < 0.050, f"{best * 1000:.1f} ms for {len(game.official_stream.events)} events"


def test_every_partial_stream_agrees_with_the_full_game(game: yus.Game):
    """Streaming == batch: stats after k events equal the full game's stats for those events, except the point and possession
    still in play."""
    assert game.official_stream is not None
    events = game.official_stream.events
    full = compute_stats(game.official_stream, game.teams)
    for k in range(len(events) + 1):
        part = compute_stats(yus.EventStream(game=game, events=events[:k]), game.teams)
        pd.testing.assert_frame_equal(part.throws, full.throws[full.throws.index < k])
        pd.testing.assert_frame_equal(part.defenses, full.defenses[full.defenses.index < k])
        pd.testing.assert_frame_equal(part.score_timeline, full.score_timeline.iloc[: len(part.score_timeline)])
        pd.testing.assert_frame_equal(part.possessions.iloc[:-1], full.possessions.iloc[: max(len(part.possessions) - 1, 0)])
        pd.testing.assert_frame_equal(part.points.iloc[:-1], full.points.iloc[: max(len(part.points) - 1, 0)])
        assert part.score == {team: int((full.score_timeline["event"] < k)[full.score_timeline["team"] == team].sum()) for team in full.teams}
        assert (part.team_box["completions"] + part.team_box["turnovers"] == part.team_box["throws"]).all()


def test_provisional_events_are_flagged(game: yus.Game, stats: GameStats):
    assert game.official_stream is not None
    last_goal = int(stats.score_timeline["event"].iloc[-1])
    flagged = compute_stats(game.official_stream, provisional_from=last_goal)
    assert flagged.throws["provisional"].to_dict() == {i: i >= last_goal for i in flagged.throws.index}
    assert not flagged.defenses["provisional"].any()  # the last D ("deed by gloves") came before the last goal
    assert flagged.score_timeline["provisional"].tolist() == [False] * 22 + [True]
    assert flagged.points["provisional"].tolist() == [False] * 22 + [True, True]
    assert flagged.possessions["provisional"].sum() == 3
    assert flagged.player_box.loc[("black", "Adam Federbusch"), "provisional"]  # threw the last goal
    assert not flagged.player_box.loc[("black", "Collin Ruprecht"), "provisional"]
    assert flagged.summary() == f"white 14, black 9 (point 24 in play; {len(game.official_stream.events) - last_goal} provisional events)"
    for name in GameStats.DERIVED_TABLES + GameStats.RAW_TABLES:  # flags only: the numbers are the same
        plain, marked = getattr(stats, name), getattr(flagged, name)
        pd.testing.assert_frame_equal(marked.drop(columns="provisional"), plain.drop(columns="provisional"))


def test_every_row_a_provisional_event_changes_is_flagged(game: yus.Game):
    """Live, the last few events are provisional: every derived row that is new, or differs from the stats of the final events
    alone, is flagged."""
    assert game.official_stream is not None
    events = game.official_stream.events
    for n in range(1, len(events) + 1, 4):
        for k in {max(n - 1, 0), max(n - 3, 0)}:
            marked = compute_stats(yus.EventStream(game=game, events=events[:n]), game.teams, provisional_from=k)
            final = compute_stats(yus.EventStream(game=game, events=events[:k]), game.teams)
            for name in GameStats.DERIVED_TABLES:
                assert not (missed := _unflagged_changes(getattr(marked, name), getattr(final, name))), (n, k, name, missed)


def test_provisional_events_flag_every_team_and_possession_they_change():
    # white scores, black scores, then a provisional white throw starts point 3: both teams' o_points / d_points change
    events = [throw("white", "kaia", "joe", scored=True), throw("black", "hat", "bush", second=3), throw("black", "bush", "hat", scored=True, second=5)]
    stats = compute_stats(yus.EventStream(events=[*events, throw("white", "kaia", "joe", second=8)]), provisional_from=3)
    assert stats.team_box[["o_points", "d_points", "provisional"]].to_dict("index") == {
        "white": {"o_points": 2, "d_points": 1, "provisional": True},
        "black": {"o_points": 1, "d_points": 2, "provisional": True},
    }
    # a provisional throw by the other team turns the possession before it from "in play" to "unknown"
    stats = compute_stats(yus.EventStream(events=[throw("white", "kaia", "joe"), throw("black", "hat", "bush", second=3)]), provisional_from=1)
    assert stats.possessions[["outcome", "provisional"]].values.tolist() == [["unknown", True], ["in play", True]]


def test_empty_stream(game: yus.Game):
    stats = compute_stats(yus.EventStream())
    assert stats.score == {} and stats.teams == [] and stats.start is None
    assert stats.summary() == "no events yet"
    assert all(frame.empty for frame in stats.tables().values())
    assert list(stats.throws.columns)[:4] == ["when", "elapsed", "team", "player"]
    assert pd.api.types.is_bool_dtype(stats.throws.dtypes["completed"])

    with_teams = compute_stats(yus.EventStream(), game.teams)
    assert with_teams.score == {WHITE: 0, BLACK: 0}
    assert with_teams.summary() == f"{WHITE} 0, {BLACK} 0"
    assert with_teams.team_box["throws"].tolist() == [0, 0]
    assert with_teams.team_box["completion_pct"].isna().all()
    assert with_teams.connection_matrix(WHITE).empty


def test_partial_point_in_play():
    stream = yus.EventStream(events=[throw("white", "kaia", "joe", second=0), throw("white", "joe", "kaia", completed=False, second=2)])
    stream.add(ultimate.Defense(when=datetime.datetime(2025, 1, 14, 20, 31, 3), team="black", player=None))
    stream.add(throw("black", "hat", "turtle", second=5))
    stats = compute_stats(stream)
    assert stats.summary() == "white 0, black 0 (point 1 in play)"
    assert stats.possessions["outcome"].tolist() == ["turnover", "in play"]
    assert stats.points.loc[1, ["o_team", "possessions", "throws", "turnovers"]].tolist() == ["white", 2, 3, 1]
    assert stats.points.loc[1, "start"] == pd.Timestamp("2025-01-14T20:31:00")  # no game: time counts from the first event
    assert stats.team_box.loc["black", ["ds", "d_points", "o_points"]].tolist() == [1, 1, 0]
    assert stats.player_box.loc[("white", "joe"), ["throws", "turnovers", "catches"]].tolist() == [1, 1, 1]


def test_teams_merge_the_names_events_use(game: yus.Game):
    stream = yus.EventStream(events=[throw("white", "kaia", "joe", completed=False), throw("dark", "hat", "bush", second=3), throw("Black", "bush", "hat", second=4)])
    assert compute_stats(stream).teams == ["white", "dark", "Black"]
    stats = compute_stats(stream, game.teams)
    assert stats.teams == [WHITE, BLACK]
    assert stats.team_box["throws"].tolist() == [1, 2]
    assert stats.possessions["team"].tolist() == [WHITE, BLACK]


def test_events_without_a_team_get_the_team_with_the_disc(game: yus.Game):
    # The event extractor writes team "" when it can't tell, e.g. before any team is named:
    # "backhand to somebody", "flick huck dropped", "picks it up for white", "backhand to joe for a score"
    stream = yus.EventStream(events=[throw("", None, None), throw("", None, None, completed=False, second=5), throw("white", None, "joe", scored=True, second=10)])
    stats = compute_stats(stream, game.teams)
    assert stats.teams == [WHITE, BLACK] and stats.summary() == f"{WHITE} 1, {BLACK} 0"
    assert stats.throws["team"].tolist() == [BLACK, BLACK, WHITE]  # from the next throw: white picked up the turnover
    assert stats.team_box[["throws", "possessions", "turnovers", "goals", "o_points", "breaks"]].to_dict("index") == {
        WHITE: {"throws": 1, "possessions": 1, "turnovers": 0, "goals": 1, "o_points": 0, "breaks": 1},
        BLACK: {"throws": 2, "possessions": 1, "turnovers": 1, "goals": 0, "o_points": 1, "breaks": 0},
    }

    # from the previous throw: the same team after a completion, the other team after a turnover or a goal; a D is the defenders'
    when = datetime.datetime(2025, 1, 14, 20, 31)
    stream = yus.EventStream(events=[throw("white", "kaia", "joe"), throw("", "joe", "kaia", completed=False, second=2)])
    stream.add(ultimate.Defense(when=when + datetime.timedelta(seconds=3), team="", player="hat"))
    stream.add(throw("", "hat", "bush", scored=True, second=6))
    stream.add(ultimate.Defense(when=when + datetime.timedelta(seconds=9), team="", player="bush"))  # after black's goal: black defends
    stream.add(throw("", "kaia", "joe", second=10))
    stats = compute_stats(stream, game.teams)
    assert stats.throws["team"].tolist() == [WHITE, WHITE, BLACK, WHITE]
    assert stats.defenses["team"].tolist() == [BLACK, BLACK]
    assert stats.possessions["team"].tolist() == [WHITE, BLACK, WHITE]
    assert stats.points.loc[1, ["o_team", "scored_by", "hold"]].tolist() == [WHITE, BLACK, False]
    assert stats.points.loc[2, "o_team"] == WHITE and not stats.points["suspect"].any()

    # with one team known there is no "other team": the goal's team stays unknown, and out of every per-team table
    stats = compute_stats(yus.EventStream(events=[throw("white", "kaia", "joe", completed=False), throw("", "hat", "bush", scored=True, second=3)]))
    assert stats.teams == ["white"] and stats.summary() == "white 0"
    assert stats.throws["team"].tolist() == ["white", None]
    assert stats.team_box.loc["white", ["throws", "goals", "possessions"]].tolist() == [1, 0, 1]
    assert stats.player_box.index.get_level_values("player").tolist() == ["joe", "kaia"]
    assert stats.score_timeline[["team", "scorer", "score_white"]].values.tolist() == [[None, "bush", 0]]
    assert pd.isna(stats.points.loc[1, "hold"])
    assert compute_stats(yus.EventStream(events=[throw("", "hat", "bush")])).summary() == "no team known yet (point 1 in play)"


def test_times_with_a_utc_offset(game: yus.Game, stats: GameStats):
    """Times with a UTC offset become naive wall-clock times, so the tables are those of the naive times."""
    assert game.official_stream is not None
    mst = datetime.timezone(datetime.timedelta(hours=-7))
    events = game.official_stream.events

    def local(when: datetime.datetime) -> datetime.datetime:
        return when.replace(tzinfo=mst)

    def shifted(game_when, event_when) -> yus.EventStream:
        return yus.EventStream(
            game=game.model_copy(update={"when": game_when(game.when)}), events=[e.model_copy(update={"when": event_when(i, e.when)}) for i, e in enumerate(events)]
        )

    cases = {
        "game and events at -07:00": shifted(local, lambda i, when: local(when)),
        "naive game, events at -07:00": shifted(lambda when: when, lambda i, when: local(when)),
        "events alternately in UTC and at -07:00": shifted(local, lambda i, when: local(when).astimezone(datetime.UTC) if i % 2 else local(when)),
    }
    for case, stream in cases.items():
        result = compute_stats(stream)
        assert result.start == stats.start and result.start.tzinfo is None, case
        for name, frame in stats.tables().items():
            pd.testing.assert_frame_equal(getattr(result, name), frame, obj=f"{case}: {name}")

    # only UTC times: this system's local time, as transcription does
    result = compute_stats(yus.EventStream(events=[e.model_copy(update={"when": local(e.when).astimezone(datetime.UTC)}) for e in events]))
    assert result.throws["when"].tolist() == [local(events[i].when).astimezone().replace(tzinfo=None) for i in result.throws.index]
    pd.testing.assert_series_equal(result.throws["elapsed"], compute_stats(yus.EventStream(events=events)).throws["elapsed"])


def test_running_score_columns_cannot_clash_with_team_names():
    stream = yus.EventStream(events=[throw("provisional", "a", "b", scored=True), throw("goal", "c", "d", scored=True, second=5)])
    timeline = compute_stats(stream).score_timeline
    assert timeline.index.tolist() == [1, 2] and timeline["team"].tolist() == ["provisional", "goal"]
    assert timeline[["score_provisional", "score_goal"]].values.tolist() == [[1, 0], [1, 1]]
    assert timeline["provisional"].dtype == bool and not timeline["provisional"].any()


def test_live_stats_of_events_extracted_from_whisper(game: yus.Game):
    """The event extractor's output on the real Whisper transcript, resolved and recomputed after every transcript group."""
    from yus.processing.event_extraction.extractor import EventExtractor
    from yus.processing.event_unification import GameDescriptions, PlayerResolver

    transcript = yus.Transcript.model_validate_json((DATA / "gruindoor_20250114T2030-whisper-turbo.json").read_text())
    resolver = PlayerResolver(game.teams, GameDescriptions.model_validate_json(DESCRIPTIONS.read_text()))
    extractor = EventExtractor(game.teams, timeout=6.0)
    slowest = 0.0
    for group in [*transcript.groups, None]:
        extractor.feed(group) if group is not None else extractor.finish()
        stream = resolver.resolve_stream(yus.EventStream(events=list(extractor.events)))
        started = time.perf_counter()
        stats = compute_stats(stream, game.teams, provisional_from=extractor.final_count)
        slowest = max(slowest, time.perf_counter() - started)
        box = stats.team_box
        assert stats.teams == [WHITE, BLACK] and stats.throws["team"].notna().all() and stats.defenses["team"].notna().all()
        assert (box["completions"] + box["turnovers"] == box["throws"]).all() and box["throws"].sum() == len(stats.throws)
        assert box["goals"].sum() == len(stats.score_timeline) == sum(stats.score.values())
    assert sum(stats.score.values()) >= 23 and stats.possessions["outcome"].isin(["goal", "turnover", "in play"]).all()
    assert slowest < 0.050, f"{slowest * 1000:.1f} ms"


def test_other_event_types_get_their_own_tables():
    when = datetime.datetime(2025, 1, 14, 20, 31)
    stream = yus.EventStream(events=[throw("white", "kaia", "joe", scored=True)])
    stream.add(ultimate.Substitution(when=when, team="white", player="kaia", sub_type=ultimate.SubType.SUB_OFF))
    stream.add(ultimate.Infraction(when=when, team="black", player="hat"))
    stream.add(yus.Event(when=when))  # not an Ultimate event: ignored
    stats = compute_stats(stream)
    assert stats.substitutions[["team", "player", "sub_type", "point"]].to_dict("records") == [{"team": "white", "player": "kaia", "sub_type": "sub_off", "point": 2}]
    assert stats.infractions["point"].tolist() == [2]  # after the goal: the next point
    assert len(stats.points) == 2 and stats.points.loc[2, "o_team"] is None
    assert stats.summary() == "white 1, black 0"


# --- yus-stats ---


def test_cli_text_resolves_names(game: yus.Game, capsys):
    team_args = [arg for path in TEAM_FILES for arg in ("--team", str(path))]
    assert cli.main([str(EVENTS), *team_args, "--descriptions", str(DESCRIPTIONS), "--tables", "team_box,player_box"]) == 0
    out, err = capsys.readouterr()
    assert out.startswith(f"Score: {WHITE} 14, {BLACK} 9 (point 24 in play)\n")
    assert "== team_box (2 rows) ==" in out and "== player_box (20 rows) ==" in out and "== points" not in out
    assert "Serayan Knappe-Butler" in out and "the kid" not in out
    assert "'glasses' (Dump & Drizzle, 32x)" in err  # still needs a person to identify


def test_cli_csv_matches_the_api(game: yus.Game, tmp_path: pathlib.Path):
    assert game.official_stream is not None
    team_args = [arg for path in TEAM_FILES for arg in ("--team", str(path))]
    assert cli.main([str(EVENTS), *team_args, "--descriptions", str(DESCRIPTIONS), "--format", "csv", "-o", str(tmp_path)]) == 0
    assert sorted(path.stem for path in tmp_path.iterdir()) == sorted(GameStats.DERIVED_TABLES)
    expected = compute_stats(game.official_stream, game.teams).player_box
    written = pd.read_csv(tmp_path / "player_box.csv", index_col=["team", "player"])
    pd.testing.assert_frame_equal(written, expected, check_dtype=False)


def test_cli_reads_times_with_a_utc_offset(tmp_path: pathlib.Path, capsys):
    shifted, count = re.subn(r'("when": "[^"]+)"', r'\1-07:00"', EVENTS.read_text())
    assert count == 200
    (tmp_path / "events.json").write_text(shifted)
    team_args = [arg for path in TEAM_FILES for arg in ("--team", str(path))]
    assert cli.main([str(EVENTS), *team_args, "--tables", "points,team_box,score_timeline"]) == 0
    plain = capsys.readouterr().out
    assert cli.main([str(tmp_path / "events.json"), *team_args, "--tables", "points,team_box,score_timeline"]) == 0
    assert capsys.readouterr().out == plain


def test_cli_html_and_without_teams(tmp_path: pathlib.Path, capsys):
    page = tmp_path / "stats.html"
    assert cli.main([str(EVENTS), "--format", "html", "-o", str(page), "--tables", "points,throws"]) == 0
    text = page.read_text()
    assert text.startswith("<!doctype html>") and "<h1>white 14, black 9 (point 24 in play)</h1>" in text
    assert text.count("<table") == 2
    with pytest.raises(SystemExit):
        cli.main([str(EVENTS), "--descriptions", str(DESCRIPTIONS)])  # descriptions need teams
    with pytest.raises(SystemExit, match="could not load"):
        cli.main([str(tmp_path / "missing.json")])
    with pytest.raises(SystemExit):
        cli.main([str(EVENTS), "--tables", "nope"])
    capsys.readouterr()


def _unflagged_changes(marked: pd.DataFrame, final: pd.DataFrame) -> list:
    """Index of the rows of `marked` that are new or differ from `final` but aren't flagged provisional."""
    rows, before = marked.drop(columns="provisional"), final.drop(columns="provisional")
    known = rows.index.isin(before.index)
    changed = ~known
    common = rows.index[known]
    changed[known] = (rows.loc[common].astype(str).to_numpy() != before.loc[common].astype(str).to_numpy()).any(axis=1)
    return rows.index[changed & ~marked["provisional"].to_numpy()].tolist()


def _seconds(fn) -> float:
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start
