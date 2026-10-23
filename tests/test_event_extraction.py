"""Tests for rule-based event extraction (yus.processing.event_extraction, the yus-events tool).

Accuracy thresholds are measured on the labeled game, split in time: dev (tuned on) before SPLIT, test (held out) after it.
"""

import collections
import datetime as dt
import json
import pathlib
import random
import time

import pytest

import yus
from tests.data.gruindoor_20250114T2030 import build_game
from yus.processing.evaluation import score
from yus.processing.event_extraction import AssistedExtractor, Association, EventExtractor, LLMAssistant, extract_events, team_label
from yus.processing.event_extraction import cli
from yus.processing.event_unification import GameDescriptions, PlayerResolver
from yus.sports import ultimate
from yus.sports.ultimate import ThrowDirection, ThrowType, indoor

DATA = pathlib.Path(__file__).parent / "data"
HAND_MADE = DATA / "gruindoor_20250114T2030-transcript.json"
WHISPER = DATA / "gruindoor_20250114T2030-whisper-turbo.json"  # a real Whisper large-v3-turbo transcript of the game's audio
SPLIT = dt.datetime(2025, 1, 14, 20, 38, 30, 900000)
WINDOWS = {"dev": {"stop": SPLIT}, "test": {"start": SPLIT}}
NOW = dt.datetime(2025, 1, 1, 12)


@pytest.fixture(scope="module")
def game() -> yus.Game:
    return build_game()


@pytest.fixture(scope="module")
def resolver(game: yus.Game) -> PlayerResolver:
    return PlayerResolver(game.teams, GameDescriptions.model_validate_json((DATA / "gruindoor_20250114T2030-descriptions.json").read_text()))


@pytest.fixture(scope="module")
def transcripts() -> dict[str, yus.Transcript]:
    return {path.name: yus.Transcript.model_validate_json(path.read_text()) for path in (HAND_MADE, WHISPER)}


def group(text: str, start: dt.datetime, step: float = 0.4) -> yus.TranscriptGroup:
    """A transcript group of `text`'s words, `step` seconds apart."""
    result = yus.TranscriptGroup()
    interpretation = result.add_interpretation()
    for k, word in enumerate(text.split()):
        interpretation.add_word(word, start=start + dt.timedelta(seconds=step * k), duration=dt.timedelta(seconds=step))
    return result


def extract(*texts: str, teams: list[yus.Team] | None = None, timeout: float | None = None) -> EventExtractor:
    """An extractor fed one group per text, 5 seconds apart, then finished."""
    extractor = EventExtractor(teams, timeout=timeout)
    for k, text in enumerate(texts):
        extractor.feed(group(text, NOW + dt.timedelta(seconds=5 * k)))
    extractor.finish()
    return extractor


def brief(event: yus.Event) -> tuple:
    """(class, team, player, receiver or interception, ...) for compact comparisons."""
    if isinstance(event, ultimate.Throw):
        flags = "".join(c for c, on in (("C", event.completed), ("S", event.scored), ("W", getattr(event, "hit_wall", False))) if on)
        return ("Throw", event.team, event.player, event.receiver, event.type and event.type.value, event.direction and event.direction.value, flags)
    assert isinstance(event, ultimate.Defense)
    return ("Defense", event.team, event.player, event.intercepted)


# Accuracy on the labeled game ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("split, f1, exact", [("dev", 0.99, 0.98), ("test", 0.97, 0.90)])  # measured: dev 1.000 / 1.000, test 0.990 / 0.942
def test_hand_made_transcript(game: yus.Game, transcripts: dict[str, yus.Transcript], split: str, f1: float, exact: float):
    predicted = extract_events(transcripts[HAND_MADE.name], game.teams)
    result = score(predicted, game.event_streams[0], teams=game.teams, **WINDOWS[split])
    assert result.overall.f1 >= f1 and result.exact.f1 >= exact


# Measured on the real Whisper transcript (WER 0.10). Names as spoken differ from the ground truth wherever Whisper's text did
# ("Adam Federbusch" for "federbusch", "Kaia Mann" for "kaia"), so the "resolved" rows map both sides with PlayerResolver.
#   raw:      dev 0.990 / 0.760   test 0.990 / 0.663
#   resolved: dev 0.990 / 0.948   test 0.990 / 0.837
@pytest.mark.parametrize(
    "split, resolved, f1, exact",
    [("dev", False, 0.97, 0.72), ("test", False, 0.97, 0.62), ("dev", True, 0.97, 0.92), ("test", True, 0.97, 0.80)],
)
def test_whisper_transcript(game: yus.Game, resolver: PlayerResolver, transcripts: dict[str, yus.Transcript], split: str, resolved: bool, f1: float, exact: float):
    predicted = extract_events(transcripts[WHISPER.name], game.teams)
    result = score(predicted, game.event_streams[0], teams=game.teams, resolve=resolver if resolved else None, **WINDOWS[split])
    assert result.overall.f1 >= f1 and result.exact.f1 >= exact


def test_extracted_names_are_as_spoken_and_teams_are_team_names(game: yus.Game, transcripts: dict[str, yus.Transcript]):
    events = extract_events(transcripts[WHISPER.name], game.teams).events
    names = {name for event in events for name in (getattr(event, "player", None), getattr(event, "receiver", None)) if name}
    assert {"pikachu", "close crop", "adam federbusch", "kaia mann", "the kid", "yellow fringe"} <= names
    assert all(name == name.lower() for name in names)
    teams = PlayerResolver(game.teams)
    assert all(teams.team_index(event.team) is not None for event in events if isinstance(event, ultimate.UltimateEvent))
    assert [event.when for event in events] == sorted(event.when for event in events)


# Streaming -----------------------------------------------------------------------------------------------------------


def stream(extractor: EventExtractor, groups: list[yus.TranscriptGroup], ticks: random.Random | None = None) -> list[yus.Event]:
    """Feed groups one at a time (with clock ticks in the silences when `ticks` is given), checking that final events never change."""
    final: list[yus.Event] = []
    for k, item in enumerate(groups):
        if ticks is not None and k and extractor.timeout is not None:
            end = max(w.start + w.duration for w in groups[k - 1].words)
            extractor.advance(end + (item.start - end) * ticks.random())  # the transcript is complete up to a time before the next words
        extractor.feed(item)
        assert extractor.final_count >= len(final)
        assert extractor.events[: len(final)] == final
        final = extractor.events[: extractor.final_count]
        assert [e.when for e in extractor.events] == sorted(e.when for e in extractor.events)
    extractor.finish()
    assert extractor.final_count == len(extractor.events)
    assert extractor.events[: len(final)] == final
    return extractor.events


@pytest.mark.parametrize("name", [HAND_MADE.name, WHISPER.name])
@pytest.mark.parametrize("timeout", [None, 3.0])
def test_streaming_ends_with_the_batch_events(game: yus.Game, transcripts: dict[str, yus.Transcript], name: str, timeout: float | None):
    transcript = transcripts[name]
    batch = extract_events(transcript, game.teams, timeout=timeout).events
    assert stream(EventExtractor(game.teams, timeout=timeout), transcript.groups, random.Random(1)) == batch


PHRASES = [
    "picked up by {n}", "{n} picks it up for {t}", "flick to {n}", "backhand swing to {n}", "dump", "huck", "to {n}", "deed by {n}", "dropped",
    "for a score", "in the end zone", "off the wall", "stolen by {n}", "{n} backhand to {n}", "turf", "no score", "{n} is {n}", "{t} pulls",
    "score is five to three", "um", "{n}", "caught by {n}", "hammer put", "to the end zone", "checks it in", "sorry", "{n} throws it away",
    "what's the score", "5-4 {t}", "{n} with the d", "{n} gets it", "on {t} we have {n}, {n} and {n}", "{n} is {n} on {t}", "{t}", "for",
    "D'd by {n} for {t}", "{t} picks it up", "D-line comes on for {t}", "{n} is {n} and {n} is {n}", "{n}'s huck", "uh-huh",
    "nope", "not in the end zone", "not a score", "not {n}", "that wasn't {n}", "that was {n}", "sorry, to {n}", "actually", "wait, {n}",
    "for a score", "joe", "tristan", "george", "turtle", "deed by joe", "nope, not in", "{n} not in position", "out of the end zone",
    "sorry, {n}, what a throw", "er",
]  # fmt: skip
NAMES = ["kaia", "pikachu", "close crop", "the kid", "somebody", "gloves", "Adam Federbusch", "red shorts", "José", "Kaia Mann's"]


def random_groups(rng: random.Random) -> list[yus.TranscriptGroup]:
    """Random commentary from PHRASES, with random punctuation and capitals, cut into groups of 1-8 words at random gaps. A third
    of the groups give all their words one start time, as Whisper sometimes does."""
    words: list[str] = []
    for _ in range(rng.randint(5, 40)):
        text = rng.choice(PHRASES)
        while "{" in text:
            text = text.replace("{n}", rng.choice(NAMES), 1).replace("{t}", rng.choice(["white", "dark", "black", "Category 5"]), 1)
        words += [w.capitalize() if rng.random() < 0.2 else w for w in text.split()]
        words[-1] += rng.choice(["", "", ".", ",", "?", "!", "..."])
    groups, clock = [], NOW
    while words:
        size = rng.randint(1, 8)
        groups.append(group(" ".join(words[:size]), clock, step=rng.choice([0.4, 0.4, 0.0])))
        clock += dt.timedelta(seconds=0.4 * size + rng.choice([0.2, 1.0, 2.5, 4.0, 8.0]))
        words = words[size:]
    return groups


@pytest.mark.parametrize("seed", range(40))
def test_random_commentary_streams_like_batch(game: yus.Game, seed: int):
    rng = random.Random(seed)
    groups = random_groups(rng)
    timeout = rng.choice([None, 0.0, 2.0, 6.0])
    transcript = yus.Transcript(groups=groups)
    batch = extract_events(transcript, game.teams, timeout=timeout).events
    assert stream(EventExtractor(game.teams, timeout=timeout), groups, rng) == batch
    labels = {team_label(team) for team in game.teams} | {""}
    assert all(event.team in labels for event in batch if isinstance(event, ultimate.UltimateEvent))
    assert all(name == name.lower() for event in batch for name in (getattr(event, "player", None), getattr(event, "receiver", None)) if name)


def test_provisional_throw_is_revised_then_final():
    extractor = EventExtractor(build_game().teams)
    extractor.feed(group("picked up by kaia for white", NOW))
    extractor.feed(group("flick huck", NOW + dt.timedelta(seconds=3)))
    assert (extractor.final_count, len(extractor.events)) == (0, 1)
    assert brief(extractor.events[0]) == ("Throw", "white", "kaia", None, "flick", "huck", "C")  # provisional: completed, no receiver yet
    extractor.feed(group("caught by pikachu for a score", NOW + dt.timedelta(seconds=6)))
    assert extractor.final_count == 0  # a score waits for the next group, which may take it back
    assert brief(extractor.events[0]) == ("Throw", "white", "kaia", "pikachu", "flick", "huck", "CS")
    extractor.feed(group("picked up by george", NOW + dt.timedelta(seconds=9)))
    assert extractor.final_count == 1


def test_timeout_finalizes_a_throw_after_silence():
    teams = build_game().teams
    extractor = EventExtractor(teams, timeout=6.0)
    extractor.feed(group("picked up by kaia for white", NOW))
    extractor.feed(group("flick huck", NOW + dt.timedelta(seconds=3)))  # ends at 3.8 s
    extractor.advance(NOW + dt.timedelta(seconds=9.5))
    assert extractor.final_count == 0
    extractor.advance(NOW + dt.timedelta(seconds=10))
    assert extractor.final_count == 1 and extractor.events[0].receiver is None  # type: ignore[attr-defined]
    without = extract("picked up by kaia for white", "flick huck", "caught by pikachu", teams=teams)
    assert brief(without.events[0])[3] == "pikachu"


# Phrasing --------------------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def teams() -> list[yus.Team]:
    return build_game().teams


def test_asr_punctuation_and_capitals(teams: list[yus.Team]):
    extractor = extract("Black pulls, picked up by Pikachu.", "Backhand, to glasses.", "Flick -huck to Kaia Mann, dropped.", teams=teams)
    assert [brief(e) for e in extractor.events] == [
        ("Throw", "white", "pikachu", "glasses", "backhand", None, "C"),
        ("Throw", "white", "glasses", "kaia mann", "flick", "huck", ""),
    ]


@pytest.mark.parametrize("text", ["deed by George", "D'd by George.", "dee'd by george", "blocked by george", "d by george", "Defense by George!"])
def test_defense_spellings(teams: list[yus.Team], text: str):
    extractor = extract("picked up by kaia for white", f"flick to tristan {text}", teams=teams)
    assert [brief(e) for e in extractor.events] == [("Throw", "white", "kaia", "tristan", "flick", None, ""), ("Defense", "dark", "george", False)]


@pytest.mark.parametrize("text", ["hammer to the endzone, caught by george", "hammer to the end zone caught by george", "Hammer the end zone George for score."])
def test_end_zone_spellings(teams: list[yus.Team], text: str):
    extractor = extract("Gloves picks it up for dark.", text, "Joe picks it up for white.", teams=teams)
    assert brief(extractor.events[0]) == ("Throw", "dark", "gloves", "george", "hammer", None, "CS")  # caught toward the end zone, then a pickup


def test_names_from_rosters_and_mondegreens_stay_whole(teams: list[yus.Team]):
    extractor = extract("Adam Federbusch picks it up.", "Backhand to Christopher Baines, flick to Adam Federbusch.", teams=teams)
    assert [brief(e)[:4] for e in extractor.events] == [("Throw", "dark", "adam federbusch", "christopher baines"), ("Throw", "dark", "christopher baines", "adam federbusch")]


def test_fillers_and_score_lines(teams: list[yus.Team]):
    extractor = extract("picked up by kaia for white", "score is five to three", "um, backhand to, uh, tristan", "okay so that's game point", teams=teams)
    assert [brief(e) for e in extractor.events] == [("Throw", "white", "kaia", "tristan", "backhand", None, "C")]


def test_a_name_ending_a_group_can_start_the_next(teams: list[yus.Team]):
    extractor = extract("picked up by kaia for white", "flick to tristan. George backhand dropped. Tristan", "picks up for white, backhand to Kaia.", teams=teams)
    assert [brief(e)[:4] for e in extractor.events] == [
        ("Throw", "white", "kaia", "tristan"),
        ("Throw", "dark", "george", None),  # george is on dark: the flick to tristan must have been turned over
        ("Throw", "white", "tristan", "kaia"),
    ]


def test_throws_continue_across_groups(teams: list[yus.Team]):
    extractor = extract("picked up by kaia for white", "flick", "swing, close crop", "flick put", "off the wall to turtle in the end zone for a score", teams=teams)
    assert [brief(e) for e in extractor.events] == [
        ("Throw", "white", "kaia", "close crop", "flick", "swing", "C"),
        ("Throw", "white", "close crop", "turtle", "flick", "huck", "CSW"),
    ]


def test_named_receiver_in_the_end_zone_after_a_completed_throw_is_a_new_throw(teams: list[yus.Team]):
    extractor = extract("picked up by glasses for white", "backhand to glasses. tristan in the end zone for a score", teams=teams)
    assert [brief(e)[2:4] for e in extractor.events] == [("glasses", "glasses"), ("glasses", "tristan")]
    assert extractor.events[-1].scored  # type: ignore[attr-defined]


def test_line_ups_teach_names_and_teams(teams: list[yus.Team]):
    extractor = extract("On dark we have yellow fringe, gloves and hat.", "white pulls", "gloves picks it up", "backhand to yellow fringe", teams=teams)
    assert [brief(e)[:4] for e in extractor.events] == [("Throw", "dark", "gloves", "yellow fringe")]


def test_other_phrasings(teams: list[yus.Team]):
    first = "picked up by kaia for white"
    assert brief(extract(first, "kaia to tristan, sorry, to joe", teams=teams).events[0])[2:4] == ("kaia", "joe")
    assert brief(extract(first, "kaia throws it away", teams=teams).events[0]) == ("Throw", "white", "kaia", None, None, None, "")
    assert brief(extract(first, "kaia hits pikachu", teams=teams).events[0])[2:4] == ("kaia", "pikachu")
    assert brief(extract(first, "kaia's huck, caught by joe", teams=teams).events[0])[2:4] == ("kaia", "joe")
    assert brief(extract(first, "flick to number twelve", teams=teams).events[0])[3] == "number twelve"
    assert [brief(e) for e in extract(first, "kaia to tristan", "callahan by george", teams=teams).events][1] == ("Defense", "dark", "george", True)


def test_without_teams_white_and_black_are_assumed():
    extractor = extract("on white we have kaia and close crop", "black pulls", "picked up by kaia", "flick to close crop", "deed by glasses for dark")
    assert [brief(e) for e in extractor.events] == [("Throw", "white", "kaia", "close crop", "flick", None, ""), ("Defense", "black", "glasses", False)]


def test_team_labels():
    assert team_label(yus.Team(names=["Dump & Drizzle", "white", "light"])) == "white"
    assert team_label(yus.Team(names=["Category 5", "Cat 5", "dark", "black"])) == "dark"
    assert team_label(yus.Team(names=["Flight Club"])) == "Flight Club"
    extractor = extract("Flight Club pulls", "picked up by sam for the Wizards", teams=[yus.Team(names=["Flight Club"]), yus.Team(names=["Wizards"])])
    assert extractor.possession == 1 and extractor.holder == "sam"


# Corrections -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "texts",
    [
        ("blade in the end zone nope not in the end zone caught by somebody", "dump to blondie"),  # one group, as in the hand-made transcript
        ("Blade in the end zone?", "Nope, not in the end zone. Caught by somebody. Dump to Blondie?"),  # two, as Whisper heard it live
    ],
)
def test_a_retracted_score_is_a_catch_and_white_keeps_the_disc(teams: list[yus.Team], texts: tuple[str, ...]):
    extractor = extract("picked up by kaia for white", "flick to blondie", *texts, "power dump to tristan", teams=teams)
    assert [brief(e) for e in extractor.events][1:] == [
        ("Throw", "white", "blondie", None, "blade", None, "C"),
        ("Throw", "white", None, "blondie", None, "dump", "C"),
        ("Throw", "white", "power", "tristan", None, "dump", "C"),
    ]


@pytest.mark.parametrize("name", [HAND_MADE.name, WHISPER.name])
def test_the_bundled_games_retracted_score(game: yus.Game, transcripts: dict[str, yus.Transcript], name: str):
    events = extract_events(transcripts[name], game.teams).events
    seconds = [(event.when.replace(tzinfo=None) - dt.datetime(2025, 1, 14, 20, 30, 33)).total_seconds() for event in events]
    k = next(k for k, s in enumerate(seconds) if 649 < s < 651)  # "blade in the end zone, nope, not in the end zone, caught by somebody"
    assert brief(events[k]) == ("Throw", "white", "blondie", None, "blade", None, "C")
    assert [event.team for event in events[k + 1 : k + 5]] == ["white"] * 4 and events[k + 4].scored  # type: ignore[attr-defined]
    assert collections.Counter(event.team for event in events if getattr(event, "scored", False)) == {"white": 14, "dark": 9}  # the true score


def test_a_score_can_be_taken_back_by_the_next_group(teams: list[yus.Team]):
    first = "picked up by kaia for white"
    assert [brief(e) for e in extract(first, "flick to joe for a score", "No score.", "backhand to red shorts", teams=teams).events] == [
        ("Throw", "white", "kaia", "joe", "flick", None, ""),
        ("Throw", "dark", None, "red shorts", "backhand", None, "C"),  # the disc went to dark, not back to white
    ]
    assert brief(extract(first, "flick to joe in the end zone", "sorry, to tristan", teams=teams).events[0]) == ("Throw", "white", "kaia", "tristan", "flick", None, "CS")
    assert brief(extract(first, "flick to joe for a score. Gloves picks it up.", "Sorry, no score.", teams=teams).events[0])[-1] == ""  # after a pickup too
    assert brief(extract(first, "flick to joe for a score, nope, not in, no score", teams=teams).events[0])[-1] == ""
    assert brief(extract(first, "flick to joe in the end zone", "sorry, it wasn't in", teams=teams).events[0])[-1] == "C"
    after_a_defense = extract(first, "flick to joe for a score", "picked up by gloves. backhand to george. deed by tristan. No score.", teams=teams)
    assert brief(after_a_defense.events[0])[-1] == "CS"  # "no score" is about the last throw only


@pytest.mark.parametrize(
    "texts, scored",
    [
        (("flick to joe for a score", "picked up by gloves. out of the end zone, flick to turtle"), ("kaia", "joe")),
        (("flick to joe for a score", "picked up by gloves. turtle is not in this point"), ("kaia", "joe")),  # "not in" without "nope"
        (("huck to joe for the score, george not in position",), ("kaia", "joe")),
        (("huck to joe for the score", "sorry, kaia, that was a great throw"), ("kaia", "joe")),  # the name starts a remark
        (("flick to joe. joe backhand to emily for the score", "actually, tristan has been great tonight"), ("joe", "emily")),
        (("huck to joe for the score", "sorry, kaia"), ("kaia", "joe")),  # kaia threw it, so she did not catch it
    ],
)
def test_remarks_after_a_score_take_nothing_back(teams: list[yus.Team], texts: tuple[str, ...], scored: tuple[str, str]):
    events = extract("picked up by kaia for white", *texts, teams=teams).events
    assert [(e.team, e.player, e.receiver) for e in events if getattr(e, "scored", False)] == [("white", *scored)]


def test_a_correction_changes_one_of_two_throws_said_at_the_same_time(teams: list[yus.Team]):
    """Whisper sometimes gives several words one start time; a correction changes only the last of two throws among them."""

    def corrected(text: str) -> list[tuple]:
        extractor = EventExtractor(teams)
        extractor.feed(group("picked up by kaia for white", NOW))
        extractor.feed(group("flick to joe flick to tristan for a score", NOW + dt.timedelta(seconds=5), step=0.0))
        extractor.feed(group(text, NOW + dt.timedelta(seconds=10)))
        extractor.finish()
        return [brief(e)[2:4] + brief(e)[-1:] for e in extractor.events]

    assert corrected("no score") == [("kaia", "joe", "C"), ("joe", "tristan", "")]
    assert corrected("sorry, to george") == [("kaia", "joe", "C"), ("joe", "george", "CS")]


def test_the_llm_is_asked_only_about_the_group_after_a_score(teams: list[yus.Team]):
    """The scoring group waits for the next one, which the model is asked about alone: its revision keeps the score."""
    sent: list[dict] = []
    revision = {"kind": "throw", "team": "dark", "player": "gloves", "receiver": "turtle", "type": "flick", "direction": "huck", "result": "caught", "wall": False}

    def post(url: str, body: dict, timeout: float) -> dict:
        sent.append(body)
        return {"message": {"content": json.dumps({"correct": False, "events": [revision]})}}

    extractor = AssistedExtractor(EventExtractor(teams), LLMAssistant("test", post=post), wait=True)
    for k, text in enumerate(["picked up by kaia for white", "flick to joe. backhand to tristan for a score", "picked up by gloves, actually a nice huck to turtle"]):
        extractor.feed(group(text, NOW + dt.timedelta(seconds=5 * k)))
    extractor.finish()
    assert [call.outcome for call in extractor.calls] == ["revised"]
    assert [brief(e)[1:] for e in extractor.events] == [
        ("white", "kaia", "joe", "flick", None, "C"),
        ("white", "joe", "tristan", "backhand", None, "CS"),
        ("dark", "gloves", "turtle", "flick", "huck", "C"),
    ]
    question = sent[0]["messages"][-1]["content"]
    assert "Disc before: dark\n" in question and "2. {" not in question and "started before" not in question


def test_a_score_is_final_after_the_timeout(teams: list[yus.Team]):
    extractor = EventExtractor(teams, timeout=6.0)
    extractor.feed(group("picked up by kaia for white", NOW))
    extractor.feed(group("flick to joe for a score", NOW + dt.timedelta(seconds=3)))  # ends at 5 s
    assert extractor.final_count == 0
    extractor.advance(NOW + dt.timedelta(seconds=12))
    assert extractor.final_count == 1
    extractor.feed(group("nope, not a score", NOW + dt.timedelta(seconds=13)))
    assert brief(extractor.events[0])[-1] == "CS"


@pytest.mark.parametrize(
    "text, receivers",
    [
        ("flick to joe. Joe backhand, sorry, that wasn't joe, that was tristan, to emily", [("kaia", "tristan"), ("tristan", "emily")]),
        ("flick to joe, sorry, tristan", [("kaia", "tristan")]),
        ("flick to joe, not joe, tristan", [("kaia", "tristan")]),
        ("flick to tristan, wait, he stepped out", [("kaia", "tristan")]),  # "stepped" is no known name
        ("flick to joe. Sorry, that was stupid", [("kaia", "joe")]),
    ],
)
def test_a_name_said_after_a_correction_replaces_the_last_one(teams: list[yus.Team], text: str, receivers: list[tuple[str, str]]):
    assert [brief(e)[2:4] for e in extract("picked up by kaia for white", text, teams=teams).events] == receivers


# Teams from rosters ----------------------------------------------------------------------------------------------------


def test_a_name_only_on_the_other_roster_corrects_the_team(teams: list[yus.Team]):
    extractor = extract("picked up by gloves for dark", "flick to green hat", "power dump to tristan", "backhand to blondie", teams=teams)
    assert [brief(e)[1:4] for e in extractor.events] == [("dark", "gloves", "green hat"), ("white", "power", "tristan"), ("white", "tristan", "blondie")]
    defense = extract("picked up by gloves for dark", "huck to naked for a score", "backhand huck", "deed by joe", teams=teams)  # a false score gave white the disc
    assert [brief(e)[:3] for e in defense.events][1:] == [("Throw", "dark", None), ("Defense", "white", "joe")]


@pytest.mark.parametrize(
    "texts",
    [
        ("picked up by gloves for dark", "flick to joe"),  # the team was said
        ("picked up by gloves for dark", "flick to turtle", "backhand to joe"),  # turtle plays for dark and caught dark's pass
        ("picked up by gloves for dark", "flick to green hat", "backhand to joe"),  # green hat caught dark's pass
        ("picked up by gloves for dark", "flick to green hat", "power dump to sam"),  # sam is on both rosters
        ("picked up by gloves for dark", "flick to green hat", "power dump to number twelve"),
    ],
)
def test_names_that_do_not_correct_the_team(teams: list[yus.Team], texts: tuple[str, ...]):
    both = [teams[0].model_copy(update={"players": {**teams[0].players, "Sam Lee": []}}), teams[1].model_copy(update={"players": {**teams[1].players, "Sam Park": []}})]
    assert {e.team for e in extract(*texts, teams=both).events} == {"dark"}


# Associations ----------------------------------------------------------------------------------------------------------


def test_spoken_identifications_become_associations(teams: list[yus.Team]):
    extractor = extract("picked up by kaia for white", "oh, red shorts is kaia", "backhand to red shorts", "Yellow fringe is Jerry Swider on dark.", teams=teams)
    assert extractor.associations == [Association("white", "red shorts", "kaia"), Association("dark", "yellow fringe", "jerry swider")]
    assert [brief(e)[2:4] for e in extractor.events] == [("kaia", "red shorts")]  # the identification itself is no event
    resolver = PlayerResolver(teams)
    for team, description, name in extractor.associations:  # as docs/extraction.md shows
        assert team is not None
        resolver.describe(team, [description], player=resolver.resolve(name, team))
    assert resolver.resolve("red shorts", "white") == "Kaia Mann" and resolver.resolve("yellow fringe", "dark") == "Jerry Swider"


def test_an_identification_does_not_take_an_open_throw(teams: list[yus.Team]):
    extractor = extract("picked up by kaia for white", "flick huck", "red shorts is kaia on white", "caught by joe", teams=teams)
    assert [brief(e)[2:4] for e in extractor.events] == [("kaia", "joe")]
    assert extractor.associations == [Association("white", "red shorts", "kaia")]
    inline = extract("picked up by kaia for white", "backhand to red shorts is pikachu", teams=teams)
    assert [brief(e)[3] for e in inline.events] == ["red shorts"] and inline.associations == [Association("white", "red shorts", "pikachu")]


# Command line and speed ------------------------------------------------------------------------------------------------


def test_cli(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]):
    transcript = tmp_path / "game.transcript.json"
    transcript.write_text(HAND_MADE.read_text())
    teams = ["--team", str(DATA / "team_dump_and_drizzle.json"), "--team", str(DATA / "team_category_5.json")]
    assert cli.main([str(transcript), *teams]) == 0
    written = yus.EventStream.model_validate_json((tmp_path / "game.events.json").read_text())  # not game.transcript.events.json
    assert len(written.events) == 200 and isinstance(written.events[0], indoor.Throw)
    out = capsys.readouterr().out
    assert "200 events: 191 throws (21 incomplete), 9 defenses\nGoals: white 14, dark 9\n" in out  # the true score
    assert cli.main([str(transcript), "-o", str(tmp_path / "x.json"), "--timeout", "3"]) == 0 and (tmp_path / "x.json").exists()
    assert json.loads((tmp_path / "x.json").read_text())["events"][0]["team"] == "white"
    assert cli.main([str(tmp_path / "missing.json")]) == 1
    with pytest.raises(SystemExit):  # one team file: the other team would have no name
        cli.main([str(transcript), *teams[:2]])
    assert "--team" in capsys.readouterr().err


def test_extraction_keeps_up_live(game: yus.Game, transcripts: dict[str, yus.Transcript]):
    groups = transcripts[WHISPER.name].groups
    extractor = EventExtractor(game.teams)
    started = time.perf_counter()
    for item in groups:
        extractor.feed(item)
        assert extractor.events is not None
    per_group = (time.perf_counter() - started) / len(groups)
    assert per_group < 0.002  # measured: about 20 microseconds per group


def test_throw_style_words_map_to_enums(teams: list[yus.Team]):
    extractor = extract("picked up by kaia for white", "scoober swing to joe", "chicken wing dump to emily", "blade up the line to tristan", teams=teams)
    assert [(e.type, e.direction) for e in extractor.events] == [  # type: ignore[attr-defined]
        (ThrowType.SCOOBER, ThrowDirection.SWING),
        (ThrowType.CHICKEN_WING, ThrowDirection.DUMP),
        (ThrowType.BLADE, ThrowDirection.UP_LINE),
    ]


# Phrasings found in review -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "texts",
    [
        ("picked up by kaia for white", "Kaia throws the disc to Joe."),
        ("picked up by kaia for white", "alright backhand to joe"),
        ("Picked up by Kaia for the white team", "flick to joe"),
        ("picked up by kaia for white", "uh-huh", "Right, flick to joe, guys."),
    ],
)
def test_common_words_are_not_names(teams: list[yus.Team], texts: tuple[str, ...]):
    assert [brief(e)[1:4] for e in extract(*texts, teams=teams).events] == [("white", "kaia", "joe")]


def test_questions_and_score_lines_are_not_scores(teams: list[yus.Team]):
    first = "picked up by kaia for white"
    assert brief(extract(first, "flick to joe. What's the score?", teams=teams).events[0]) == ("Throw", "white", "kaia", "joe", "flick", None, "C")
    assert brief(extract(first, "flick huck. Score's five four.", teams=teams).events[0]) == ("Throw", "white", "kaia", None, "flick", "huck", "C")
    assert brief(extract(first, "flick to joe. Score!", teams=teams).events[0])[-1] == "CS"


def test_bare_team_names_count_only_after_a_pickup_or_defense(teams: list[yus.Team]):
    point = ("picked up by kaia for white", "backhand to tristan in the end zone for a score")
    after = ("picked up by red shorts", "flick to green hat")
    for line in ("That's 5-4 white.", "5-4 for white", "five four, white"):
        assert brief(extract(*point, line, *after, teams=teams).events[1])[:2] == ("Throw", "dark")  # white scored: dark has the disc
    assert brief(extract(point[0], "flick to the dark corner, tristan", teams=teams).events[0]) == ("Throw", "white", "kaia", "tristan", "flick", None, "C")
    assert extract("picked up by red shorts, dark", "flick to green hat", teams=teams).events[0].team == "dark"
    assert extract("picked up by red shorts", "deed by gloves, dark", "flick to green hat", teams=teams).events[-1].team == "dark"
    turnover = extract("picked up by george for dark", "flick to gloves", "white picks it up", "flick to joe", teams=teams)
    assert [brief(e)[:4] + brief(e)[-1:] for e in turnover.events] == [("Throw", "dark", "george", "gloves", ""), ("Throw", "white", None, "joe", "C")]


def test_a_team_reference_split_across_groups(teams: list[yus.Team]):
    extractor = extract("picked up by george for dark", "flick to gloves", "Kid picks it up for", "White. Checks it in.", "flick to joe", teams=teams)
    assert [brief(e)[:4] for e in extractor.events] == [("Throw", "dark", "george", "gloves"), ("Throw", "white", "kid", "joe")]
    assert extractor.team_of("kid") == 0  # "for | white" was about kid's pickup


@pytest.mark.parametrize("text", ["Flick to Tristan. D-line comes on for dark.", "flick to tristan the d line comes on for dark", "Flick to Tristan. The O-line is on for white."])
def test_d_line_is_not_a_defense(teams: list[yus.Team], text: str):
    extractor = extract("picked up by kaia for white", text, "backhand to joe", teams=teams)
    assert [brief(e)[:4] + brief(e)[-1:] for e in extractor.events] == [("Throw", "white", "kaia", "tristan", "C"), ("Throw", "white", "tristan", "joe", "C")]


def test_accented_names_stay_whole():
    teams = [yus.Team(names=["white"], players={"José Núñez": []}), yus.Team(names=["dark"], players={"Zoë Ng": []})]
    extractor = extract("Picked up by José.", "Flick to Zoë.", teams=teams)
    assert brief(extractor.events[0])[1:4] == ("white", "josé", "zoë")
    resolver = PlayerResolver(teams)
    assert (resolver.resolve("josé", "white"), resolver.resolve("zoë", "dark")) == ("José Núñez", "Zoë Ng")


def test_possessives_keep_known_names_whole(teams: list[yus.Team]):
    extractor = extract("picked up by federbusch for dark", "Adam Federbusch's huck, caught by George.", teams=teams)
    assert brief(extractor.events[0])[1:4] == ("dark", "adam federbusch", "george")


def test_two_identifications_in_one_sentence(teams: list[yus.Team]):
    extractor = extract("picked up by kaia for white", "flick huck", "Red shorts is Kaia and blue hat is Joe.", "dropped", teams=teams)
    assert [brief(e) for e in extractor.events] == [("Throw", "white", "kaia", None, "flick", "huck", "")]
    assert extractor.associations == [Association("white", "red shorts", "kaia"), Association("white", "blue hat", "joe")]


@pytest.mark.parametrize("text", ["kaia is wide open", "this game is intense", "pikachu is killing it tonight", "the kid is kaia's brother", "red shorts is kaia on dark"])
def test_is_clauses_that_identify_no_roster_player(teams: list[yus.Team], text: str):
    extractor = extract("picked up by kaia for white", "flick huck", text, "caught by joe", teams=teams)
    assert extractor.associations == []
    assert [brief(e)[1:4] for e in extractor.events] == [("white", "kaia", "joe")]


def test_without_rosters_nothing_is_identified():
    assert extract("on white we have kaia and close crop", "red shorts is kaia").associations == []
