import json
import pathlib

import pytest

import yus
from tests.data.gruindoor_20250114T2030 import build_game
from yus.processing.event_unification import GameDescriptions, PlayerResolver
from yus.processing.event_unification.players import normalize
from yus.sports import ultimate
from yus.sports.ultimate import indoor

DATA = pathlib.Path(__file__).parent / "data"
DESCRIPTIONS = DATA / "gruindoor_20250114T2030-descriptions.json"


@pytest.fixture(scope="module")
def game() -> yus.Game:
    return build_game()


@pytest.fixture(scope="module")
def descriptions() -> GameDescriptions:
    return GameDescriptions.model_validate_json(DESCRIPTIONS.read_text())


def count(stream: yus.EventStream, name: str) -> int:
    return sum(name in (evt.player, getattr(evt, "receiver", None)) for evt in stream.events if isinstance(evt, ultimate.UltimateEvent))


def test_reproduces_ground_truth_unified_stream(game: yus.Game, descriptions: GameDescriptions):
    raw, expected = game.event_streams[0], game.official_stream
    assert expected is not None
    resolved = PlayerResolver(game.teams, descriptions).resolve_stream(raw)
    assert resolved.model_dump(mode="json") == expected.model_dump(mode="json")
    assert raw.events[0].player == "pikachu"  # the raw stream is left as spoken


def test_rosters_alone_resolve_names_nicknames_and_mondegreens(game: yus.Game):
    resolver = PlayerResolver(game.teams)
    assert resolver.resolve("pikachu", "white") == "Matt Whitlock"  # nickname
    assert resolver.resolve("Tristan", "white") == "Tristan Weber"  # unique first name
    assert resolver.resolve("stephen butler", "white") == "Stephen Butler"  # full name
    assert resolver.resolve("federbusch", "dark") == "Adam Federbusch"  # unique last name, any team name
    assert resolver.resolve("Knappe-Butler", "Dump and Drizzle") == "Serayan Knappe-Butler"  # a hyphenated last name said whole
    assert resolver.resolve("bush", "Category 5") == "Adam Federbusch"  # mondegreen
    assert resolver.resolve("Kaya", "white") == "Kaia Mann"  # mondegreen
    assert resolver.resolve("turtle", "black") == "Zach Ehler"
    assert resolver.resolve("butler", "white") == "butler"  # Stephen Butler or Serayan Knappe-Butler: ambiguous
    assert resolver.resolve("tristan", "black") == "tristan"  # rosters are per team
    assert resolver.resolve("the kid", "white") == "the kid"  # descriptions are not in team files
    assert resolver.resolve(None, "white") is None
    assert resolver.resolve("tristan", None) == "tristan"


def test_nicknames_beat_parts_of_other_names():
    teams = [yus.Team(names=["white"], players={"Ben Kishter": [], "Benjamin Smith": ["Ben"], "Mary O'Neil": []})]
    resolver = PlayerResolver(teams)
    assert resolver.resolve("Ben", "white") == "Benjamin Smith"
    assert resolver.resolve("O'Neil", "white") == "Mary O'Neil"
    assert resolver.resolve("O", "white") == "O"  # single letters are not names


def test_unresolved_lists_what_a_person_must_identify(game: yus.Game, descriptions: GameDescriptions):
    raw = game.event_streams[0]
    unresolved = PlayerResolver(game.teams).unresolved(raw)
    assert unresolved[:3] == [("Dump & Drizzle", "glasses", 32), ("Dump & Drizzle", "close crop", 23), ("Dump & Drizzle", "blondie", 21)]
    assert ("Dump & Drizzle", "the kid", 15) in unresolved  # "kid" and "the kid" are one description
    assert {name for _, name, _ in unresolved} >= {"hat", "naked", "gloves", "yellow fringe", "red stripe"}
    described = PlayerResolver(game.teams, descriptions).unresolved(raw)
    assert {name for _, name, _ in described} == {"glasses", "blondie", "gloves", "red stripe", "yellow sleeve", "leg stripe", "bluey"}
    assert ("Category 5", "yellow sleeve", 19) in described  # an unknown player's labelled group still needs identifying


def test_unmentioned_players_are_candidates(game: yus.Game, descriptions: GameDescriptions):
    candidates = PlayerResolver(game.teams, descriptions).unmentioned_players(game.event_streams[0])
    assert candidates["Dump & Drizzle"] == ["Alexis Rosas", "Ari Weissman", "Drew Rasmussen"]  # "glasses" and "blondie" are two of these
    assert "Christopher Baines" not in candidates["Category 5"]


def test_description_learned_live_fixes_earlier_events(game: yus.Game):
    raw = game.event_streams[0]
    resolver = PlayerResolver(game.teams)
    assert count(resolver.resolve_stream(raw), "the kid") + count(resolver.resolve_stream(raw), "kid") == 15
    resolver.describe("white", ["the kid"], player="Serayan Knappe-Butler")  # e.g. someone tells the scorekeeper mid-game
    assert count(resolver.resolve_stream(raw), "Serayan Knappe-Butler") == 15
    resolver.describe("white", ["the kid"], player="stephen butler")  # a later correction wins; roster spelling is restored
    assert resolver.resolve("kid", "white") == "Stephen Butler"
    assert [d.player for d in resolver.descriptions.players] == ["Serayan Knappe-Butler", "Stephen Butler"]  # what to save with the game


def test_identifying_an_unknown_players_label_names_the_whole_group(game: yus.Game, descriptions: GameDescriptions):
    resolver = PlayerResolver(game.teams, descriptions)
    assert resolver.resolve("yellow border", "black") == "yellow sleeve"
    resolver.describe("black", ["yellow sleeve"], player="Jerry Swider")
    resolved = resolver.resolve_stream(game.event_streams[0])
    assert count(resolved, "Jerry Swider") == 19 and count(resolved, "yellow sleeve") == 0
    assert resolver.resolve("leg stripes", "black") == "leg stripe"  # an unknown player without a label is named by its first description


def test_events_resolve_one_at_a_time(game: yus.Game, descriptions: GameDescriptions):
    resolver = PlayerResolver(game.teams, descriptions)
    throw = indoor.Throw(when="2025-01-14T20:40:00", team="white", player="the kid", receiver="Pikachu", completed=True, scored=False)
    resolved = resolver.resolve_event(throw)
    assert (resolved.player, resolved.receiver, throw.player) == ("Serayan Knappe-Butler", "Matt Whitlock", "the kid")
    defense = ultimate.Defense(when="2025-01-14T20:40:01", team="black", player="yellow border")
    assert resolver.resolve_event(defense).player == "yellow sleeve"
    unnamed = indoor.Throw(when="2025-01-14T20:40:02", team="white", completed=True, scored=False)
    assert "receiver" not in resolver.resolve_event(unnamed).model_dump(exclude_unset=True)  # unchanged fields stay unset
    other = yus.Event(when="2025-01-14T20:40:03")
    assert resolver.resolve_event(other) == other and resolver.resolve_event(other) is not other


def test_commentator_specific_descriptions(game: yus.Game):
    resolver = PlayerResolver(game.teams)
    resolver.describe("white", ["red shorts"], player="Kaia Mann", commentator="Gavin Kistner")
    resolver.describe("white", ["red shorts"], player="Emily Kraus")
    assert resolver.resolve("red shorts", "white", commentator="gavin kistner") == "Kaia Mann"
    assert resolver.resolve("red shorts", "white", commentator="Someone Else") == "Emily Kraus"
    event = ultimate.Defense(when="2025-01-14T20:40", team="white", player="red shorts")
    stream = yus.EventStream(transcript=yus.Transcript(commentator="Gavin Kistner"), events=[event])
    assert resolver.resolve_stream(stream).events[0].player == "Kaia Mann"  # the stream's commentator comes from its transcript...
    loaded = yus.EventStream.model_validate_json(stream.model_dump_json())  # ...which a stream loaded from JSON doesn't have
    assert resolver.resolve_stream(loaded).events[0].player == "Emily Kraus"
    assert resolver.resolve_stream(loaded, commentator="Gavin Kistner").events[0].player == "Kaia Mann"


def test_invalid_input_is_rejected(game: yus.Game):
    resolver = PlayerResolver(game.teams)
    with pytest.raises(ValueError, match="No team is called 'purple'"):
        resolver.describe("purple", ["hat"], player="Christopher Baines")
    with pytest.raises(ValueError, match="'Tristan Weber' is not on the roster of 'Category 5'"):
        resolver.describe("black", ["hat"], player="Tristan Weber")
    with pytest.raises(ValueError, match="Empty description"):
        resolver.describe("black", ["hat", " ... "], player="Christopher Baines")
    with pytest.raises(ValueError, match="Two teams are called 'White!'"):
        PlayerResolver([yus.Team(names=["Red Team", "white"]), yus.Team(names=["Blue Team", "White!"])])


def test_descriptions_file_round_trips(descriptions: GameDescriptions):
    assert GameDescriptions.model_validate_json(descriptions.model_dump_json()) == descriptions
    assert json.loads(DESCRIPTIONS.read_text())["players"][0]["player"] == "Ben Kishter"


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("The Kid's,", "kid"),
        ("Knappe-Butler", "knappe butler"),
        ("  Yellow   Border ", "yellow border"),
        ("the", "the"),
        ("Pikachu’s", "pikachu"),
        ("kidʼs", "kid"),
        ("Dump & Drizzle", "dump and drizzle"),
        ("Zoë", "zoë"),
        ("yellow_border", "yellow border"),
        ("...", ""),
    ],
)
def test_normalize(spoken: str, expected: str):
    assert normalize(spoken) == expected
