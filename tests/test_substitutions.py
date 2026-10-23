"""Tests for substitutions: their extraction (yus.processing.event_extraction) and who is on the field (yus.processing.stats).

The labeled game is a draft: tests/data/subbing_20250128T2050-draft-eventstream.json, a commentary of substitutions and some play
(2025-01-28), labeled from its Whisper transcript and not yet checked by the owner. White is Dump & Drizzle; dark has no team file.
"""

import datetime as dt
import pathlib
import random
import time

import pytest

import yus
from tests.data.gruindoor_20250114T2030 import build_game
from tests.test_event_extraction import NAMES, PHRASES, stream
from yus.processing.evaluation import score
from yus.processing.event_extraction import Association, EventExtractor, extract_events
from yus.processing.event_unification import GameDescriptions, PlayerResolver
from yus.processing.stats import GameStats, compute_stats
from yus.sports import ultimate
from yus.sports.ultimate import SubType, indoor

DATA = pathlib.Path(__file__).parent / "data"
TRANSCRIPT = DATA / "subbing_20250128T2050-whisper-turbo.json"
TRUTH = DATA / "subbing_20250128T2050-draft-eventstream.json"
DESCRIPTIONS = DATA / "subbing_20250128T2050-descriptions.json"
NOW = dt.datetime(2025, 1, 1, 12)
ON, OFF = SubType.SUB_ON, SubType.SUB_OFF


@pytest.fixture(scope="module")
def teams() -> list[yus.Team]:
    return [yus.Team.model_validate_json((DATA / "team_dump_and_drizzle.json").read_text()), yus.Team(names=["dark", "black"])]


@pytest.fixture(scope="module")
def resolver(teams: list[yus.Team]) -> PlayerResolver:
    return PlayerResolver(teams, GameDescriptions.model_validate_json(DESCRIPTIONS.read_text()))


@pytest.fixture(scope="module")
def transcript() -> yus.Transcript:
    return yus.Transcript.model_validate_json(TRANSCRIPT.read_text())


@pytest.fixture(scope="module")
def truth() -> yus.EventStream:
    return yus.EventStream.model_validate_json(TRUTH.read_text())


def group(text: str, start: dt.datetime, step: float = 0.4) -> yus.TranscriptGroup:
    result = yus.TranscriptGroup()
    interpretation = result.add_interpretation()
    for k, word in enumerate(text.split()):
        interpretation.add_word(word, start=start + dt.timedelta(seconds=step * k), duration=dt.timedelta(seconds=step))
    return result


def extract(*texts: str, teams: list[yus.Team] | None = None, lineups: bool = False) -> EventExtractor:
    """An extractor fed one group per text, 5 seconds apart, then finished."""
    extractor = EventExtractor(teams, lineups=lineups)
    for k, text in enumerate(texts):
        extractor.feed(group(text, NOW + dt.timedelta(seconds=5 * k)))
    extractor.finish()
    return extractor


def subs(extractor: EventExtractor) -> list[tuple[str, str | None, str]]:
    return [(e.team, e.player, "on" if e.sub_type is ON else "off") for e in extractor.events if isinstance(e, ultimate.Substitution)]


def plays(extractor: EventExtractor) -> list[tuple]:
    return [(e.team, e.player, getattr(e, "receiver", None)) for e in extractor.events if not isinstance(e, ultimate.Substitution)]


# Phrasings ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "texts, expected",
    [
        (["Pikachu subs off, Blondie subs on."], [("white", "pikachu", "off"), ("white", "blondie", "on")]),  # blondie: pikachu's swap
        (["Close crop, Emily off."], [("white", "close crop", "off"), ("white", "emily", "off")]),  # one list, one team
        (["Tanner off purple off mock on Dylan on"], [("", "tanner", "off"), ("", "purple", "off"), ("", "mock", "on"), ("", "dylan", "on")]),
        (["Ari and Ben coming on."], [("white", "ari", "on"), ("white", "ben", "on")]),
        (["Subbing on: Ari and Ben."], [("white", "ari", "on"), ("white", "ben", "on")]),
        (["Fulmer on for Cynic."], [("", "fulmer", "on"), ("", "cynic", "off")]),
        (["Red shorts off for dark, kaia is on."], [("dark", "red shorts", "off"), ("white", "kaia", "on")]),
        (["26 off, 25 on.", "5 off."], [("", "26", "off"), ("", "25", "on"), ("", "5", "off")]),  # jersey numbers
        (["Kyle", "Fulmer on"], [("", "kyle", "on"), ("", "fulmer", "on")]),  # a name ending a group starts the next one's list
        (["Kaia comes in, Tristan goes off."], [("white", "kaia", "on"), ("white", "tristan", "off")]),  # words that also describe play
        (["Joe comes in for Kaia.", "Emily heads off"], [("white", "joe", "on"), ("white", "kaia", "off"), ("white", "emily", "off")]),
    ],
)
def test_substitution_phrasings(teams: list[yus.Team], texts: list[str], expected: list):
    extractor = extract(*texts, teams=teams)
    assert subs(extractor) == expected and plays(extractor) == []


def test_substitutions_between_throws(teams: list[yus.Team]):
    extractor = extract("picked up by kaia for white", "Kaia flicked to 26, backhand swing to 50, Tristan off, Blondie on.", teams=teams)
    assert plays(extractor) == [("white", "kaia", "26"), ("white", "26", "50")]  # 50 was the throw's, not a substitution
    assert subs(extractor) == [("white", "tristan", "off"), ("white", "blondie", "on")]
    receiver = extract("picked up by kaia for white", "Backhand swing close crop, Pikachu off, Emily on.", teams=teams)
    assert plays(receiver) == [("white", "kaia", "close crop")] and subs(receiver) == [("white", "pikachu", "off"), ("white", "emily", "on")]


@pytest.mark.parametrize(
    "text",
    [
        "Sebastian flick up to blue yellow on the end zone for a score",  # "on" followed by more of the sentence
        "Flick to Tristan. D-line comes on for dark.",
        "Flick to Tristan, off the wall, dropped.",
        "Flick to the Kid, he's on fire.",
        "Kaia coming in, flick to Kaia.",  # "coming in", "goes off" substitute only when the sentence, or another substitution, follows
        "Flick huck, Joe comes in, catches it.",
        "Flick to Tristan, it goes off the wall.",
    ],
)
def test_on_and_off_that_substitute_nobody(teams: list[yus.Team], text: str):
    assert subs(extract("picked up by kaia for white", text, teams=teams)) == []


def test_a_team_said_across_groups_is_still_a_teams(teams: list[yus.Team]):
    extractor = extract("picked up by blue on", "dark. Flick to kaia.", teams=teams)  # "on" after a pickup: "on dark"
    assert plays(extractor) == [("dark", "blue", "kaia")] and subs(extractor) == []
    lineup = extract("picked up by kaia for white", "Flick to tristan, dropped... on", "dark we have Sebastian and Cynic.", teams=teams)
    assert lineup.team_of("cynic") == 1  # an "on" that substitutes nobody waits for its team


def test_an_identification_split_before_its_team_is_read_as_one(teams: list[yus.Team]):
    start = ["picked up by kaia for white", "flick to tristan."]
    split = extract(*start, "Red shorts is Kaia on", "white. Red shorts picks it up.", teams=teams)
    whole = extract(*start, "Red shorts is Kaia on white. Red shorts picks it up.", teams=teams)
    assert split.associations == whole.associations == [Association("white", "red shorts", "kaia")]
    assert (plays(split), subs(split)) == (plays(whole), subs(whole)) and subs(split) == []
    assert subs(extract("Dark picks it up, flick to Blue.", "Blue is Sebastian on", "dark. Blue throws it away.", teams=teams)) == []
    assert subs(extract(*start, "Red shorts is Kaia on", "Flick to joe.", teams=teams)) == [("white", "kaia", "on")]  # no team next: as said
    assert subs(extract("Dylan off.", "Kaia is on", teams=teams)) == [("", "dylan", "off"), ("white", "kaia", "on")]  # nothing next
    paused = EventExtractor(teams, timeout=2.0)
    for k, text in enumerate(["Kaia is on", "Dark picks it up."]):
        paused.feed(group(text, NOW + dt.timedelta(seconds=5 * k)))
    assert subs(paused) == [("white", "kaia", "on")] and paused.final_count == 1  # a pause: no team is coming


def test_a_score_line_keeps_its_numbers(teams: list[yus.Team]):
    """Numbers above 20 are jersey numbers ("flick to 26"), except in a score line."""
    for line in ("21 to 19.", "21-19.", "19 to 21.", "21 to nothing."):
        extractor = extract("picked up by kaia for white", f"Flick to tristan. {line}", "Flick to joe.", teams=teams)
        assert plays(extractor) == [("white", "kaia", "tristan"), ("white", "tristan", "joe")], line
    assert plays(extract("picked up by kaia for white", "Flick to 26. 26 to 50.", teams=teams)) == [("white", "kaia", "26"), ("white", "26", "50")]


def test_teams_from_what_was_said_swaps_and_earlier_substitutions(teams: list[yus.Team]):
    extractor = extract("Dylan picks up for dark.", "Dylan off.", "Small gloves on.", "Small gloves off, Cynic on.", "Pikachu off, Cynic off.", teams=teams)
    assert subs(extractor) == [
        ("dark", "dylan", "off"),  # said: "picks up for dark"
        ("dark", "small gloves", "on"),  # dylan's swap
        ("dark", "small gloves", "off"),  # its earlier substitution
        ("dark", "cynic", "on"),  # small gloves' swap
        ("white", "pikachu", "off"),  # the roster
        ("dark", "cynic", "off"),  # an off after an off is no swap: its earlier substitution
    ]


def test_an_identification_of_someone_substituted_for_the_other_team(teams: list[yus.Team]):
    extractor = extract("Dylan picks up for dark.", "Dylan off, small gloves on.", "Small gloves is Joe.", "Cody off, Joe on.", teams=teams)
    assert extractor.associations == []  # not white's Joe Oaks: small gloves plays for dark
    assert subs(extractor)[-1] == ("dark", "joe", "on")


def test_a_correction_takes_back_the_last_substitution(teams: list[yus.Team]):
    assert subs(extract("Dylan on.", "Nope.", "Dylan off, mock on.", teams=teams)) == [("", "dylan", "off"), ("", "mock", "on")]
    assert subs(extract("Kaia on. Sorry, Tristan on.", teams=teams)) == [("white", "tristan", "on")]
    assert subs(extract("Kaia off, er, Tristan on.", teams=teams)) == [("white", "kaia", "off"), ("white", "tristan", "on")]  # a hesitation
    assert subs(extract("Kaia off, sorry, Emily off.", teams=teams)) == [("white", "emily", "off")]
    assert subs(extract("Kaia off. Sorry, that was a great throw.", teams=teams)) == [("white", "kaia", "off")]


@pytest.mark.parametrize(
    "texts, expected",
    [
        (["Dylan off.", "Kaia on.", "Tristan on, wait, Pikachu."], [("white", "dylan", "off"), ("white", "kaia", "on"), ("white", "pikachu", "on")]),
        (["Dylan off.", "Nope. Kaia on.", "Tristan on, wait, Pikachu."], [("white", "kaia", "on"), ("white", "pikachu", "on")]),
        (["Picked up by kaia for white.", "Flick huck, caught by Joe, Tristan off.", "Sorry, Emily."], [("white", "emily", "off")]),
    ],
)
def test_a_correction_parsing_again_keeps_what_was_decided(teams: list[yus.Team], texts: list[str], expected: list):
    """A correction of a finished event parses the group before again: dylan's swap with kaia, the "nope" that took dylan back, and
    a correction of a substitution said while a throw was open are all made again; final events never change."""
    extractor = EventExtractor(teams)
    stream(extractor, [group(text, NOW + dt.timedelta(seconds=5 * k)) for k, text in enumerate(texts)])
    assert subs(extractor) == expected


SUB_PHRASES = [
    "{n} off", "{n} on", "{n} subs off", "{n} subs on", "{n} off, {n} on", "{n}, {n} off", "{n} on for {n}", "{n} off for {t}",
    "subbing on: {n} and {n}", "{n} comes on", "{n} is on", "nope", "sorry, {n} on", "26 off", "25 on", "{n} off {n} off {n} on",
    "on {t} we have {n}, {n} and {n}", "{n} coming in", "{n} back on", "{n} heads off", "{n} off, er, {n} on", "starting with {n} and {n}",
]  # fmt: skip


def random_commentary(rng: random.Random) -> list[yus.TranscriptGroup]:
    """test_event_extraction's random commentary, with substitutions."""
    phrases, names, words = PHRASES + SUB_PHRASES * 2, [*NAMES, "26", "dylan", "fulmer"], []
    for _ in range(rng.randint(5, 40)):
        text = rng.choice(phrases)
        while "{" in text:
            text = text.replace("{n}", rng.choice(names), 1).replace("{t}", rng.choice(["white", "dark", "black", "Category 5"]), 1)
        words += [w.capitalize() if rng.random() < 0.2 else w for w in text.split()]
        words[-1] += rng.choice(["", "", ".", ",", "?", "!", "..."])
    groups, clock = [], NOW
    while words:
        size = rng.randint(1, 8)
        groups.append(group(" ".join(words[:size]), clock, step=rng.choice([0.4, 0.4, 0.0])))
        clock += dt.timedelta(seconds=0.4 * size + rng.choice([0.2, 1.0, 2.5, 4.0, 8.0]))
        words = words[size:]
    return groups


@pytest.mark.parametrize("seed", [*range(40), 259, 6025])  # 259, 6025: a correction parsing again lost a swap's team, a "nope"
def test_random_commentary_with_substitutions_streams_like_batch(seed: int):
    teams = build_game().teams
    rng = random.Random(seed)
    groups = random_commentary(rng)
    timeout, lineups = rng.choice([None, 0.0, 2.0, 6.0]), rng.random() < 0.5
    batch = extract_events(yus.Transcript(groups=groups), teams, timeout=timeout, lineups=lineups).events
    assert stream(EventExtractor(teams, timeout=timeout, lineups=lineups), groups, rng) == batch
    compute_stats(yus.EventStream(events=batch), teams)


def test_substitutions_said_during_a_throw_follow_it(teams: list[yus.Team]):
    extractor = EventExtractor(teams)
    for k, text in enumerate(["picked up by kaia for white", "flick huck.", "Tristan off, Blondie on.", "caught by joe"]):
        extractor.feed(group(text, NOW + dt.timedelta(seconds=5 * k)))
        if k == 2:
            assert extractor.final_count == 0 and [type(e).__name__ for e in extractor.events] == ["Throw", "Substitution", "Substitution"]
    extractor.finish()
    assert [e.when for e in extractor.events] == sorted(e.when for e in extractor.events)
    assert plays(extractor) == [("white", "kaia", "joe")] and len(subs(extractor)) == 2


def test_line_ups_are_substitutions_on_when_asked(teams: list[yus.Team]):
    line_up = "On white we have kaia, pikachu, tristan, glasses and short crop."
    extractor = extract(line_up, "Yeah, so we have Michelle's brother.", teams=teams, lineups=True)  # no team: no line-up
    assert subs(extractor) == [("white", name, "on") for name in ("kaia", "pikachu", "tristan", "glasses", "short crop")]
    assert extractor.events[0].when == NOW + dt.timedelta(seconds=1.6)  # when kaia was said
    assert subs(extract(line_up, teams=teams)) == []  # by default a line-up only teaches names and teams


def test_the_bundled_game_has_no_substitutions():
    """Gruindoor's commentary names no substitution; its line-up becomes five subs on only when asked, and changes nothing else."""
    game = build_game()
    transcript = yus.Transcript.model_validate_json((DATA / "gruindoor_20250114T2030-whisper-turbo.json").read_text())
    plain, lined = extract_events(transcript, game.teams), extract_events(transcript, game.teams, lineups=True)
    assert not any(isinstance(e, ultimate.Substitution) for e in plain.events)
    assert [(e.team, e.player) for e in lined.events if isinstance(e, ultimate.Substitution)] == [
        ("white", name) for name in ("kaia mann", "pikachu", "tristan", "glasses", "short crown")
    ]
    assert [e for e in lined.events if not isinstance(e, ultimate.Substitution)] == plain.events


# Accuracy on the subbing commentary -------------------------------------------------------------------------------------


def test_substitutions_found_in_the_subbing_commentary(teams: list[yus.Team], transcript: yus.Transcript, truth: yus.EventStream):
    """Measured: precision 1.000, recall 0.994 (177 true; Whisper's "Cinecon" is "Cynic on"); sub_type always right; team right
    for 0.795 (every other team is unknown, none wrong); player as spoken 0.824 (Whisper's "Sarayan", "Mach", ...)."""
    predicted = [e for e in extract_events(transcript, teams).events if isinstance(e, ultimate.Substitution)]
    result = score(predicted, [e for e in truth.events if isinstance(e, ultimate.Substitution)], teams=teams)
    assert result.overall.precision >= 0.98 and result.overall.recall >= 0.98
    assert result.fields["sub_type"].accuracy == 1.0 and result.fields["team"].accuracy >= 0.75
    assert not [m for m in result.matches if "team" in m.mismatches and m.mismatches["team"][1]]  # no team is wrong, only unknown


def test_streaming_matches_batch_on_the_subbing_commentary(teams: list[yus.Team], transcript: yus.Transcript):
    for timeout in (None, 6.0):
        batch = extract_events(transcript, teams, timeout=timeout).events
        extractor = EventExtractor(teams, timeout=timeout)
        shown: list[yus.Event] = []
        for k, item in enumerate(transcript.groups):
            extractor.feed(item)
            following = transcript.groups[k + 1].words[0].start if k + 1 < len(transcript.groups) else None
            for step in range(1, 20):
                now = item.words[-1].start + dt.timedelta(seconds=step)
                if following is not None and now >= following:
                    break
                extractor.advance(now)
            events = extractor.events
            assert events[: len(shown)] == shown  # final events never change
            assert [e.when for e in events] == sorted(e.when for e in events)
            shown = events[: extractor.final_count]
        extractor.finish()
        assert extractor.events == batch


# Who is on the field ----------------------------------------------------------------------------------------------------


def sub(team: str, player: str, kind: SubType, second: float) -> ultimate.Substitution:
    return ultimate.Substitution(when=NOW + dt.timedelta(seconds=second), team=team, player=player, sub_type=kind)


def throw(team: str, player: str | None, receiver: str | None, second: float, scored: bool = False) -> indoor.Throw:
    return indoor.Throw(when=NOW + dt.timedelta(seconds=second), team=team, player=player, receiver=receiver, completed=True, scored=scored)


def line(team: str, names: str, second: float) -> list[ultimate.Substitution]:
    return [sub(team, name, ON, second) for name in names.split()]


def test_on_field_from_a_line_up_and_swaps():
    stream = yus.EventStream(
        events=[
            *line("white", "a b c d e", 0),
            throw("white", "a", "b", 10, scored=True),  # point 1: white scores with a-e
            throw("black", "x", "y", 15),
            sub("white", "e", OFF, 20),
            sub("white", "f", ON, 21),  # one swap, made at 20, during point 2
            throw("black", "x", "y", 30, scored=True),  # point 2: black scores against a-d, f
            throw("white", "f", "a", 40),
        ]
    )
    stats = compute_stats(stream, line_size=5)
    white = stats.on_field.loc["white"]
    assert white.loc["e", ["points_played", "time_on_s", "goals_for", "goals_against", "plus_minus"]].tolist() == [2, 20.0, 1, 0, 1]  # on for part of point 2
    assert white.loc["f", ["points_played", "time_on_s", "plus_minus", "time_unknown_s"]].tolist() == [2, 20.0, -1, 0.0]  # off while a-e were on
    assert white.loc["a", ["points_played", "time_on_s", "plus_minus", "goals_unknown"]].tolist() == [3, 40.0, 0, 0]
    assert stats.lines.loc["white", ["time_s", "goals_for", "goals_against"]].to_dict("index") == {
        "a, b, c, d, e": {"time_s": 20.0, "goals_for": 1, "goals_against": 0},
        "a, b, c, d, f": {"time_s": 20.0, "goals_for": 0, "goals_against": 1},
    }
    assert "black" not in stats.on_field.index.get_level_values("team")  # nobody said who plays for black
    assert stats.shifts.query("player == 'f'")[["state", "duration_s"]].values.tolist() == [["off", 20.0], ["on", 20.0]]


def test_a_swap_said_just_after_a_goal_was_made_between_points():
    start = [*line("white", "a b c d e", 0), throw("white", "a", "b", 10, scored=True)]
    end = [throw("black", "x", "y", 20), throw("black", "y", "x", 30, scored=True)]
    stats = compute_stats(yus.EventStream(events=[*start, sub("white", "b", OFF, 13), sub("white", "f", ON, 14), *end]), line_size=5)
    white = stats.on_field.loc["white", ["points_played", "time_on_s", "goals_for", "goals_against"]]
    assert white.loc[["a", "b", "f"]].values.tolist() == [[2, 30.0, 1, 1], [1, 10.0, 1, 0], [1, 20.0, 0, 1]]  # b scored, then left
    assert stats.lines.loc["white", ["points", "time_s", "goals_for", "goals_against"]].to_dict("index") == {
        "a, b, c, d, e": {"points": 1, "time_s": 10.0, "goals_for": 1, "goals_against": 0},
        "a, c, d, e, f": {"points": 1, "time_s": 20.0, "goals_for": 0, "goals_against": 1},
    }
    for late in ([end[0], sub("white", "b", OFF, 21), sub("white", "f", ON, 22)], [sub("white", "b", OFF, 21), sub("white", "f", ON, 22)]):
        events = [*start, *late, end[-1]]  # said after the next point's first throw, or 11 s after the goal: made during the point
        assert compute_stats(yus.EventStream(events=events), line_size=5).on_field.loc[("white", "b"), "points_played"] == 2


def test_unknown_on_field_state_is_not_guessed():
    events = [
        sub("white", "a", ON, 0),
        sub("white", "b", OFF, 0),  # b was on before: unknown since the start
        throw("white", "a", "c", 10, scored=True),  # c was never substituted: no row; a is on, b off
        throw("black", "x", "y", 15),
        sub("white", "a", ON, 20),  # a second "a on": "a off" was missed after a's throw at 10, so 10-20 is unknown
        throw("black", "x", "y", 30, scored=True),
    ]
    stats = compute_stats(yus.EventStream(events=events), line_size=5)
    white = stats.on_field.loc["white"]
    assert list(white.index) == ["a", "b"]
    assert white.loc["a", ["time_on_s", "time_unknown_s", "goals_for", "goals_against", "goals_unknown"]].tolist() == [20.0, 10.0, 1, 1, 0]
    assert white.loc["b", ["time_on_s", "time_unknown_s", "plus_minus"]].tolist() == [0.0, 0.0, 0]
    assert stats.lines.loc["white"].index.tolist() == ["unknown"]  # never five known on


def test_too_many_on_makes_the_line_unknown():
    events = [*line("white", "a b c d e", 0), sub("white", "f", ON, 10), throw("black", "x", "y", 20, scored=True)]  # e off was missed
    stats = compute_stats(yus.EventStream(events=events), line_size=5)
    assert stats.lines.loc["white", "time_s"].to_dict() == {"a, b, c, d, e": 10.0, "unknown": 10.0}
    assert stats.on_field.loc["white", "goals_unknown"].tolist() == [1] * 6
    assert compute_stats(yus.EventStream(events=events), line_size=None).lines.index.get_level_values("line").unique().tolist() == ["unknown"]


def test_a_substitution_without_a_team_gets_its_players():
    events = [sub("dark", "x", OFF, 0), sub("", "y", ON, 1), sub("dark", "y", OFF, 5), sub("", "x", ON, 6)]
    stats = compute_stats(yus.EventStream(events=events))
    assert stats.substitutions["team"].tolist() == ["dark"] * 4


def test_on_field_rows_a_provisional_event_changes_are_flagged():
    events = [*line("white", "a b c d e", 0), throw("white", "a", "b", 10, scored=True), sub("white", "e", OFF, 20), sub("white", "f", ON, 21)]
    for firm in range(len(events) - 2, len(events)):
        marked = compute_stats(yus.EventStream(events=events), provisional_from=firm)
        final = compute_stats(yus.EventStream(events=events[:firm]))
        for name in ("on_field", "lines", "shifts"):
            rows, before = getattr(marked, name), getattr(final, name)
            changed = [key for key in rows.index if key not in before.index or not rows.loc[key].drop("provisional").equals(before.loc[key].drop("provisional"))]
            assert rows.loc[changed, "provisional"].all(), (firm, name)


def test_on_field_stats_of_the_subbing_commentary(teams: list[yus.Team], resolver: PlayerResolver, truth: yus.EventStream, transcript: yus.Transcript):
    """From the draft truth: who was on the field is known for 87% of player-seconds; the extractor's stream, resolved, agrees with
    it wherever both know (Whisper's mishearings of names aside, see docs/stats.md)."""
    stats = compute_stats(resolver.resolve_stream(truth), teams)
    assert stats.score == {"Dump & Drizzle": 10, "dark": 9}
    white = stats.on_field.loc["Dump & Drizzle"]
    assert len(white) == 9 and white.loc["Tristan Weber", "points_played"] == 15
    assert (white["goals_for"] + white["goals_against"] + white["goals_unknown"] <= 19).all()
    known = stats.lines.drop(index="unknown", level="line")
    assert known.groupby("team")["time_s"].sum().round().to_dict() == {"Dump & Drizzle": 516.0, "dark": 650.0}
    assert (stats.shifts["duration_s"] > 0).all() and set(stats.shifts["state"]) == {"on", "off", "unknown"}
    extracted = compute_stats(resolver.resolve_stream(extract_events(transcript, teams, timeout=6.0)), teams)
    assert set(extracted.on_field.index.get_level_values("team")) == {"Dump & Drizzle", "dark"}
    assert isinstance(extracted, GameStats) and not extracted.on_field.empty


def test_recomputing_with_substitutions_stays_fast(teams: list[yus.Team], resolver: PlayerResolver, truth: yus.EventStream):
    stream = resolver.resolve_stream(truth)
    started = time.perf_counter()
    for _ in range(5):
        compute_stats(stream, teams)
    assert (time.perf_counter() - started) / 5 < 0.1  # measured: 10 ms (the bundled game, without substitutions: 7 ms)


def test_yus_stats_writes_the_on_field_tables_when_there_are_substitutions(teams: list[yus.Team], tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]):
    from yus.processing.stats import cli

    dark = tmp_path / "dark.json"
    dark.write_text(teams[1].model_dump_json())
    args = [str(TRUTH), "--team", str(DATA / "team_dump_and_drizzle.json"), "--team", str(dark), "--descriptions", str(DESCRIPTIONS)]
    assert cli.main([*args, "--format", "csv", "-o", str(tmp_path / "csv")]) == 0
    assert {"on_field", "lines", "shifts"} <= {path.stem for path in (tmp_path / "csv").iterdir()}
    assert cli.main([*args, "--tables", "on_field"]) == 0
    assert "== on_field (21 rows) ==" in capsys.readouterr().out


def test_the_dashboard_shows_points_minutes_and_plus_minus():
    from yus.web.dashboard import _player_rows

    events = [*line("white", "a b c d e", 0), throw("white", "a", "b", 60, scored=True), sub("white", "e", OFF, 90), sub("white", "f", ON, 91)]
    events.append(throw("black", "x", "y", 120, scored=True))
    rows = {row["player"]: row for row in _player_rows(compute_stats(yus.EventStream(events=events)))}
    assert (rows["a"]["throws"], rows["a"]["points_played"], rows["a"]["minutes_on"], rows["a"]["plus_minus"]) == (1, 2, 2.0, 0)
    assert (rows["f"]["throws"], rows["f"]["completion_pct"], rows["f"]["minutes_on"], rows["f"]["plus_minus"]) == (0, None, 0.5, -1)  # subbed on, no disc
    assert rows["x"]["minutes_on"] is None  # nobody said who plays for black
