import copy
from datetime import datetime as DT
from datetime import timedelta as TD

import yus
from yus.sports import ultimate
from yus.sports.ultimate import indoor


def build_game() -> yus.Game:
    game = yus.Game(
        sport="ultimate/indoor",
        when=DT.fromisoformat("2025-01-14T20:31:11.5"),
        teams=[
            yus.Team(
                names=["Dump & Drizzle", "white", "light"],
                players={
                    "Matt Whitlock": ["Pikachu"],
                    "Kaia Mann": [],
                    "Emily Kraus": [],
                    "Alexis Rosas": [],
                    "Ari Weissman": [],
                    "Ben Kishter": [],
                    "Drew Rasmussen": [],
                    "Joe Oaks": [],
                    "Serayan Knappe-Butler": [],
                    "Stephen Butler": [],
                    "Tristan Weber": [],
                },
            ),
            yus.Team(
                names=["Category 5", "Cat 5", "dark", "black"],
                players={
                    "Jennifer Dasenbrock": [],
                    "Molly Lanning": [],
                    "Adam Federbusch": ["Busch"],
                    "Christopher Baines": [],
                    "Collin Ruprecht": [],
                    "Jacob Gernert": [],
                    "Jerry Swider": [],
                    "Nathan Speer": [],
                    "Sammy Allen": [],
                    "Thomas McPherson": [],
                    "Zach Ehler": ["Turtle"],
                    "George Abuhamad": [],
                },
            ),
        ],
    )

    transcript = build_transcript(game)
    raw_stream = build_raw_stream(transcript)

    game.transcripts.append(transcript)
    game.event_streams.append(raw_stream)
    game.official_stream = build_unified_stream(raw_stream)

    return game


def build_transcript(game: yus.Game) -> yus.Transcript:
    transcript = yus.Transcript(commentator="Gavin Kistner", game=game)

    # "on white we have kaia pikachu tristan glasses and short crop"
    transcript.add_group().add_interpretation(confidence=0.708).words.extend(
        [
            yus.Word(text="on", confidence=0.478, start=DT.fromisoformat("2025-01-14T20:30:47.6"), duration=TD(seconds=0.3)),
            yus.Word(text="white", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:30:47.9"), duration=TD(seconds=0.3)),
            yus.Word(text="we", confidence=0.749, start=DT.fromisoformat("2025-01-14T20:30:48.2"), duration=TD(seconds=0.3)),
            yus.Word(text="have", confidence=0.749, start=DT.fromisoformat("2025-01-14T20:30:48.5"), duration=TD(seconds=0.3)),
            yus.Word(text="kaia", confidence=0.592, start=DT.fromisoformat("2025-01-14T20:30:48.8"), duration=TD(seconds=0.75)),
            yus.Word(text="pikachu", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:30:49.55"), duration=TD(seconds=0.9)),
            yus.Word(text="tristan", confidence=0.672, start=DT.fromisoformat("2025-01-14T20:30:50.45"), duration=TD(seconds=0.6)),
            yus.Word(text="glasses", confidence=0.714, start=DT.fromisoformat("2025-01-14T20:30:51.05"), duration=TD(seconds=0.6)),
            yus.Word(text="and", confidence=0.435, start=DT.fromisoformat("2025-01-14T20:30:51.65"), duration=TD(seconds=0.3)),
            yus.Word(text="short", confidence=0.758, start=DT.fromisoformat("2025-01-14T20:30:51.95"), duration=TD(seconds=0.3)),
            yus.Word(text="crop", confidence=0.833, start=DT.fromisoformat("2025-01-14T20:30:52.25"), duration=TD(seconds=0.3)),
        ]
    )
    # "black pulls"
    transcript.add_group().add_interpretation(confidence=0.575).words.extend(
        [
            yus.Word(text="black", confidence=0.800, start=DT.fromisoformat("2025-01-14T20:31:11.5"), duration=TD(seconds=0.3)),
            yus.Word(text="pulls", confidence=0.350, start=DT.fromisoformat("2025-01-14T20:31:11.8"), duration=TD(seconds=0.3)),
        ]
    )

    # "picked up by pikachu"
    transcript.add_group().add_interpretation(confidence=0.910).words.extend(
        [
            yus.Word(text="picked", confidence=0.906, start=DT.fromisoformat("2025-01-14T20:31:12.8"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:31:13.1"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:31:13.4"), duration=TD(seconds=0.3)),
            yus.Word(text="pikachu", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:31:13.7"), duration=TD(seconds=0.9)),
        ]
    )

    # "backhand to glasses"
    transcript.add_group().add_interpretation(confidence=0.699).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:31:15.7"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:31:16.3"), duration=TD(seconds=0.3)),
            yus.Word(text="glasses", confidence=0.714, start=DT.fromisoformat("2025-01-14T20:31:16.6"), duration=TD(seconds=0.6)),
        ]
    )

    # "scoober to tristan"
    transcript.add_group().add_interpretation(confidence=0.753).words.extend(
        [
            yus.Word(text="scoober", confidence=0.850, start=DT.fromisoformat("2025-01-14T20:31:18.1"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:31:18.7"), duration=TD(seconds=0.3)),
            yus.Word(text="tristan", confidence=0.672, start=DT.fromisoformat("2025-01-14T20:31:19"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to close crop"
    transcript.add_group().add_interpretation(confidence=0.706).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:31:22.8"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:31:23.4"), duration=TD(seconds=0.3)),
            yus.Word(text="close", confidence=0.608, start=DT.fromisoformat("2025-01-14T20:31:23.7"), duration=TD(seconds=0.3)),
            yus.Word(text="crop", confidence=0.833, start=DT.fromisoformat("2025-01-14T20:31:24"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand dump to emily"
    transcript.add_group().add_interpretation(confidence=0.746).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:31:28.1"), duration=TD(seconds=0.6)),
            yus.Word(text="dump", confidence=0.772, start=DT.fromisoformat("2025-01-14T20:31:28.7"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:31:29"), duration=TD(seconds=0.3)),
            yus.Word(text="emily", confidence=0.830, start=DT.fromisoformat("2025-01-14T20:31:29.3"), duration=TD(seconds=0.9)),
        ]
    )

    # "backhand swing to glasses"
    transcript.add_group().add_interpretation(confidence=0.717).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:31:30.1"), duration=TD(seconds=0.6)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:31:30.7"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:31:31"), duration=TD(seconds=0.3)),
            yus.Word(text="glasses", confidence=0.714, start=DT.fromisoformat("2025-01-14T20:31:31.3"), duration=TD(seconds=0.6)),
        ]
    )

    # "flick to kaia deed by somebody on dark"
    transcript.add_group().add_interpretation(confidence=0.738).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:31:33"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:31:33.3"), duration=TD(seconds=0.3)),
            yus.Word(text="kaia", confidence=0.592, start=DT.fromisoformat("2025-01-14T20:31:33.6"), duration=TD(seconds=0.75)),
            yus.Word(text="deed", confidence=0.841, start=DT.fromisoformat("2025-01-14T20:31:34.35"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:31:34.65"), duration=TD(seconds=0.3)),
            yus.Word(text="somebody", confidence=0.796, start=DT.fromisoformat("2025-01-14T20:31:34.95"), duration=TD(seconds=0.9)),
            yus.Word(text="on", confidence=0.478, start=DT.fromisoformat("2025-01-14T20:31:35.85"), duration=TD(seconds=0.3)),
            yus.Word(text="dark", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:31:36.15"), duration=TD(seconds=0.3)),
        ]
    )

    # "picked up by blue on dark"
    transcript.add_group().add_interpretation(confidence=0.823).words.extend(
        [
            yus.Word(text="picked", confidence=0.906, start=DT.fromisoformat("2025-01-14T20:31:43"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:31:43.3"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:31:43.6"), duration=TD(seconds=0.3)),
            yus.Word(text="blue", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:31:43.9"), duration=TD(seconds=0.3)),
            yus.Word(text="on", confidence=0.478, start=DT.fromisoformat("2025-01-14T20:31:44.2"), duration=TD(seconds=0.3)),
            yus.Word(text="dark", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:31:44.5"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand swing to red stripe"
    transcript.add_group().add_interpretation(confidence=0.660).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:31:45"), duration=TD(seconds=0.6)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:31:45.6"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:31:45.9"), duration=TD(seconds=0.3)),
            yus.Word(text="red", confidence=0.430, start=DT.fromisoformat("2025-01-14T20:31:46.2"), duration=TD(seconds=0.3)),
            yus.Word(text="stripe", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:31:46.5"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to yellow border"
    transcript.add_group().add_interpretation(confidence=0.775).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:31:47"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:31:47.6"), duration=TD(seconds=0.3)),
            yus.Word(text="yellow", confidence=0.789, start=DT.fromisoformat("2025-01-14T20:31:47.9"), duration=TD(seconds=0.6)),
            yus.Word(text="border", confidence=0.930, start=DT.fromisoformat("2025-01-14T20:31:48.5"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand federbusch to naked for a score"
    transcript.add_group().add_interpretation(confidence=0.789).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:31:56.1"), duration=TD(seconds=0.6)),
            yus.Word(text="federbusch", confidence=0.930, start=DT.fromisoformat("2025-01-14T20:31:56.7"), duration=TD(seconds=0.9)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:31:57.6"), duration=TD(seconds=0.3)),
            yus.Word(text="naked", confidence=0.931, start=DT.fromisoformat("2025-01-14T20:31:57.9"), duration=TD(seconds=0.6)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:31:58.5"), duration=TD(seconds=0.3)),
            yus.Word(text="a", confidence=0.639, start=DT.fromisoformat("2025-01-14T20:31:58.8"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:31:59.1"), duration=TD(seconds=0.3)),
        ]
    )

    # "picked up by pikachu"
    transcript.add_group().add_interpretation(confidence=0.910).words.extend(
        [
            yus.Word(text="picked", confidence=0.906, start=DT.fromisoformat("2025-01-14T20:32:02.1"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:32:02.4"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:32:02.7"), duration=TD(seconds=0.3)),
            yus.Word(text="pikachu", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:32:03"), duration=TD(seconds=0.9)),
        ]
    )

    # "flick to close crop"
    transcript.add_group().add_interpretation(confidence=0.723).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:32:03.4"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:32:03.7"), duration=TD(seconds=0.3)),
            yus.Word(text="close", confidence=0.608, start=DT.fromisoformat("2025-01-14T20:32:04"), duration=TD(seconds=0.3)),
            yus.Word(text="crop", confidence=0.833, start=DT.fromisoformat("2025-01-14T20:32:04.3"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to joe"
    transcript.add_group().add_interpretation(confidence=0.739).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:32:05.3"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:32:05.9"), duration=TD(seconds=0.3)),
            yus.Word(text="joe", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:32:06.2"), duration=TD(seconds=0.3)),
        ]
    )

    # "joe big flick huck off the wall no score"
    transcript.add_group().add_interpretation(confidence=0.774).words.extend(
        [
            yus.Word(text="joe", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:32:09.9"), duration=TD(seconds=0.3)),
            yus.Word(text="big", confidence=0.430, start=DT.fromisoformat("2025-01-14T20:32:10.2"), duration=TD(seconds=0.3)),
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:32:10.5"), duration=TD(seconds=0.3)),
            yus.Word(text="huck", confidence=0.729, start=DT.fromisoformat("2025-01-14T20:32:10.8"), duration=TD(seconds=0.3)),
            yus.Word(text="off", confidence=0.867, start=DT.fromisoformat("2025-01-14T20:32:11.1"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:32:11.4"), duration=TD(seconds=0.3)),
            yus.Word(text="wall", confidence=0.964, start=DT.fromisoformat("2025-01-14T20:32:11.7"), duration=TD(seconds=0.3)),
            yus.Word(text="no", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:32:12"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:32:12.3"), duration=TD(seconds=0.3)),
        ]
    )

    # "picked up by federbusch for dark"
    transcript.add_group().add_interpretation(confidence=0.894).words.extend(
        [
            yus.Word(text="picked", confidence=0.906, start=DT.fromisoformat("2025-01-14T20:32:16.5"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:32:16.8"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:32:17.1"), duration=TD(seconds=0.3)),
            yus.Word(text="federbusch", confidence=0.930, start=DT.fromisoformat("2025-01-14T20:32:17.4"), duration=TD(seconds=0.9)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:32:18.3"), duration=TD(seconds=0.3)),
            yus.Word(text="dark", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:32:18.6"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand swing to somebody"
    transcript.add_group().add_interpretation(confidence=0.737).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:32:21.8"), duration=TD(seconds=0.6)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:32:22.4"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:32:22.7"), duration=TD(seconds=0.3)),
            yus.Word(text="somebody", confidence=0.796, start=DT.fromisoformat("2025-01-14T20:32:23"), duration=TD(seconds=0.9)),
        ]
    )

    # "backhand huck deed by stephen butler"
    transcript.add_group().add_interpretation(confidence=0.753).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:32:28"), duration=TD(seconds=0.6)),
            yus.Word(text="huck", confidence=0.729, start=DT.fromisoformat("2025-01-14T20:32:28.6"), duration=TD(seconds=0.3)),
            yus.Word(text="deed", confidence=0.841, start=DT.fromisoformat("2025-01-14T20:32:28.9"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:32:29.2"), duration=TD(seconds=0.3)),
            yus.Word(text="stephen", confidence=0.674, start=DT.fromisoformat("2025-01-14T20:32:29.5"), duration=TD(seconds=0.6)),
            yus.Word(text="butler", confidence=0.744, start=DT.fromisoformat("2025-01-14T20:32:30.1"), duration=TD(seconds=0.6)),
        ]
    )

    # "stephen picks it up for white"
    transcript.add_group().add_interpretation(confidence=0.837).words.extend(
        [
            yus.Word(text="stephen", confidence=0.674, start=DT.fromisoformat("2025-01-14T20:32:32"), duration=TD(seconds=0.6)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:32:32.6"), duration=TD(seconds=0.3)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:32:32.9"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:32:33.2"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:32:33.5"), duration=TD(seconds=0.3)),
            yus.Word(text="white", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:32:33.8"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick swing to tristan"
    transcript.add_group().add_interpretation(confidence=0.723).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:32:37"), duration=TD(seconds=0.3)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:32:37.3"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:32:37.6"), duration=TD(seconds=0.3)),
            yus.Word(text="tristan", confidence=0.672, start=DT.fromisoformat("2025-01-14T20:32:37.9"), duration=TD(seconds=0.6)),
        ]
    )

    # "hammer put to the end zone to somebody for a score"
    transcript.add_group().add_interpretation(confidence=0.718).words.extend(
        [
            yus.Word(text="hammer", confidence=0.627, start=DT.fromisoformat("2025-01-14T20:32:41.2"), duration=TD(seconds=0.6)),
            yus.Word(text="put", confidence=0.653, start=DT.fromisoformat("2025-01-14T20:32:41.8"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:32:42.1"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:32:42.4"), duration=TD(seconds=0.3)),
            yus.Word(text="end", confidence=0.588, start=DT.fromisoformat("2025-01-14T20:32:42.7"), duration=TD(seconds=0.3)),
            yus.Word(text="zone", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:32:43"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:32:43.3"), duration=TD(seconds=0.3)),
            yus.Word(text="somebody", confidence=0.796, start=DT.fromisoformat("2025-01-14T20:32:43.6"), duration=TD(seconds=0.9)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:32:44.5"), duration=TD(seconds=0.3)),
            yus.Word(text="a", confidence=0.639, start=DT.fromisoformat("2025-01-14T20:32:44.8"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:32:45.1"), duration=TD(seconds=0.3)),
        ]
    )

    # "somebody picks it up for dark"
    transcript.add_group().add_interpretation(confidence=0.853).words.extend(
        [
            yus.Word(text="somebody", confidence=0.796, start=DT.fromisoformat("2025-01-14T20:32:50.0"), duration=TD(seconds=0.9)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:32:50.9"), duration=TD(seconds=0.3)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:32:51.2"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:32:51.5"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:32:51.8"), duration=TD(seconds=0.3)),
            yus.Word(text="dark", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:32:52.1"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick swing to gloves"
    transcript.add_group().add_interpretation(confidence=0.771).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:32:52.2"), duration=TD(seconds=0.3)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:32:52.5"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:32:52.8"), duration=TD(seconds=0.3)),
            yus.Word(text="gloves", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:32:53.1"), duration=TD(seconds=0.3)),
        ]
    )

    # "gloves hammer to the end zone to george for a score for dark"
    transcript.add_group().add_interpretation(confidence=0.762).words.extend(
        [
            yus.Word(text="gloves", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:32:54.5"), duration=TD(seconds=0.3)),
            yus.Word(text="hammer", confidence=0.627, start=DT.fromisoformat("2025-01-14T20:32:54.8"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:32:55.4"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:32:55.7"), duration=TD(seconds=0.3)),
            yus.Word(text="end", confidence=0.588, start=DT.fromisoformat("2025-01-14T20:32:56"), duration=TD(seconds=0.3)),
            yus.Word(text="zone", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:32:56.3"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:32:56.6"), duration=TD(seconds=0.3)),
            yus.Word(text="george", confidence=0.881, start=DT.fromisoformat("2025-01-14T20:32:56.9"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:32:57.2"), duration=TD(seconds=0.3)),
            yus.Word(text="a", confidence=0.639, start=DT.fromisoformat("2025-01-14T20:32:57.5"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:32:57.8"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:32:58.1"), duration=TD(seconds=0.3)),
            yus.Word(text="dark", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:32:58.4"), duration=TD(seconds=0.3)),
        ]
    )

    # "kid picks it up for white"
    transcript.add_group().add_interpretation(confidence=0.864).words.extend(
        [
            yus.Word(text="kid", confidence=0.838, start=DT.fromisoformat("2025-01-14T20:33:00.5"), duration=TD(seconds=0.3)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:33:00.8"), duration=TD(seconds=0.3)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:33:01.1"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:33:01.4"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:33:01.7"), duration=TD(seconds=0.3)),
            yus.Word(text="white", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:33:02"), duration=TD(seconds=0.3)),
        ]
    )

    # "kid flicks to joe"
    transcript.add_group().add_interpretation(confidence=0.746).words.extend(
        [
            yus.Word(text="kid", confidence=0.838, start=DT.fromisoformat("2025-01-14T20:33:04.5"), duration=TD(seconds=0.3)),
            yus.Word(text="flicks", confidence=0.574, start=DT.fromisoformat("2025-01-14T20:33:04.8"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:33:05.1"), duration=TD(seconds=0.3)),
            yus.Word(text="joe", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:33:05.4"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick huck to kaia in the end zone for a score"
    transcript.add_group().add_interpretation(confidence=0.710).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:33:07"), duration=TD(seconds=0.3)),
            yus.Word(text="huck", confidence=0.729, start=DT.fromisoformat("2025-01-14T20:33:07.3"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:33:07.6"), duration=TD(seconds=0.3)),
            yus.Word(text="kaia", confidence=0.592, start=DT.fromisoformat("2025-01-14T20:33:07.9"), duration=TD(seconds=0.75)),
            yus.Word(text="in", confidence=0.692, start=DT.fromisoformat("2025-01-14T20:33:08.65"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:33:08.95"), duration=TD(seconds=0.3)),
            yus.Word(text="end", confidence=0.588, start=DT.fromisoformat("2025-01-14T20:33:09.25"), duration=TD(seconds=0.3)),
            yus.Word(text="zone", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:33:09.55"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:33:09.85"), duration=TD(seconds=0.3)),
            yus.Word(text="a", confidence=0.639, start=DT.fromisoformat("2025-01-14T20:33:10.15"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:33:10.45"), duration=TD(seconds=0.3)),
        ]
    )

    # "somebody picks it up for dark"
    transcript.add_group().add_interpretation(confidence=0.853).words.extend(
        [
            yus.Word(text="somebody", confidence=0.796, start=DT.fromisoformat("2025-01-14T20:33:12.9"), duration=TD(seconds=0.7)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:33:13.6"), duration=TD(seconds=0.2)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:33:13.8"), duration=TD(seconds=0.2)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:33:14"), duration=TD(seconds=0.2)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:33:14.2"), duration=TD(seconds=0.2)),
            yus.Word(text="dark", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:33:14.4"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to george"
    transcript.add_group().add_interpretation(confidence=0.755).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:33:15.2"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:33:15.8"), duration=TD(seconds=0.3)),
            yus.Word(text="george", confidence=0.881, start=DT.fromisoformat("2025-01-14T20:33:16.1"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to hat"
    transcript.add_group().add_interpretation(confidence=0.754).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:33:19.1"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:33:19.7"), duration=TD(seconds=0.3)),
            yus.Word(text="hat", confidence=0.880, start=DT.fromisoformat("2025-01-14T20:33:20.0"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to george"
    transcript.add_group().add_interpretation(confidence=0.755).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:33:20.3"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:33:20.9"), duration=TD(seconds=0.3)),
            yus.Word(text="george", confidence=0.881, start=DT.fromisoformat("2025-01-14T20:33:21.2"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand hat"
    transcript.add_group().add_interpretation(confidence=0.763).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:33:21.6"), duration=TD(seconds=0.6)),
            yus.Word(text="hat", confidence=0.880, start=DT.fromisoformat("2025-01-14T20:33:22.2"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick put"
    transcript.add_group().add_interpretation(confidence=0.683).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:33:22.4"), duration=TD(seconds=0.3)),
            yus.Word(text="put", confidence=0.653, start=DT.fromisoformat("2025-01-14T20:33:22.7"), duration=TD(seconds=0.3)),
        ]
    )

    # "off the wall to turtle in the end zone for a score"
    transcript.add_group().add_interpretation(confidence=0.769).words.extend(
        [
            yus.Word(text="off", confidence=0.867, start=DT.fromisoformat("2025-01-14T20:33:26"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:33:26.3"), duration=TD(seconds=0.3)),
            yus.Word(text="wall", confidence=0.964, start=DT.fromisoformat("2025-01-14T20:33:26.6"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:33:26.9"), duration=TD(seconds=0.3)),
            yus.Word(text="turtle", confidence=0.872, start=DT.fromisoformat("2025-01-14T20:33:27.2"), duration=TD(seconds=0.6)),
            yus.Word(text="in", confidence=0.692, start=DT.fromisoformat("2025-01-14T20:33:27.8"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:33:28.1"), duration=TD(seconds=0.3)),
            yus.Word(text="end", confidence=0.588, start=DT.fromisoformat("2025-01-14T20:33:28.4"), duration=TD(seconds=0.3)),
            yus.Word(text="zone", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:33:28.7"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:33:29"), duration=TD(seconds=0.3)),
            yus.Word(text="a", confidence=0.639, start=DT.fromisoformat("2025-01-14T20:33:29.3"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:33:29.6"), duration=TD(seconds=0.3)),
        ]
    )

    # "pikachu picks it up for white"
    transcript.add_group().add_interpretation(confidence=0.878).words.extend(
        [
            yus.Word(text="pikachu", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:33:30.7"), duration=TD(seconds=0.9)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:33:31.6"), duration=TD(seconds=0.3)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:33:31.9"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:33:32.2"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:33:32.5"), duration=TD(seconds=0.3)),
            yus.Word(text="white", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:33:32.8"), duration=TD(seconds=0.3)),
        ]
    )

    # "tapped in"
    transcript.add_group().add_interpretation(confidence=0.531).words.extend(
        [
            yus.Word(text="tapped", confidence=0.370, start=DT.fromisoformat("2025-01-14T20:33:34"), duration=TD(seconds=0.36)),
            yus.Word(text="in", confidence=0.692, start=DT.fromisoformat("2025-01-14T20:33:34.36"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand swing to tristan"
    transcript.add_group().add_interpretation(confidence=0.706).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:33:35.8"), duration=TD(seconds=0.6)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:33:36.4"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:33:36.7"), duration=TD(seconds=0.3)),
            yus.Word(text="tristan", confidence=0.672, start=DT.fromisoformat("2025-01-14T20:33:37"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to pikachu"
    transcript.add_group().add_interpretation(confidence=0.769).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:33:37"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:33:37.6"), duration=TD(seconds=0.3)),
            yus.Word(text="pikachu", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:33:37.9"), duration=TD(seconds=0.9)),
        ]
    )

    # "backhand to tristan"
    transcript.add_group().add_interpretation(confidence=0.685).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:33:39.5"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:33:40.1"), duration=TD(seconds=0.3)),
            yus.Word(text="tristan", confidence=0.672, start=DT.fromisoformat("2025-01-14T20:33:40.4"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to glasses"
    transcript.add_group().add_interpretation(confidence=0.699).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:33:40.5"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:33:41.1"), duration=TD(seconds=0.3)),
            yus.Word(text="glasses", confidence=0.714, start=DT.fromisoformat("2025-01-14T20:33:41.4"), duration=TD(seconds=0.6)),
        ]
    )

    # "flick to tristan"
    transcript.add_group().add_interpretation(confidence=0.707).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:33:45"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:33:45.3"), duration=TD(seconds=0.3)),
            yus.Word(text="tristan", confidence=0.672, start=DT.fromisoformat("2025-01-14T20:33:45.6"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to glasses"
    transcript.add_group().add_interpretation(confidence=0.699).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:33:47.1"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:33:47.7"), duration=TD(seconds=0.3)),
            yus.Word(text="glasses", confidence=0.714, start=DT.fromisoformat("2025-01-14T20:33:48"), duration=TD(seconds=0.6)),
        ]
    )

    # "flick to kaia dropped"
    transcript.add_group().add_interpretation(confidence=0.751).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:33:51.2"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:33:51.5"), duration=TD(seconds=0.3)),
            yus.Word(text="kaia", confidence=0.592, start=DT.fromisoformat("2025-01-14T20:33:51.8"), duration=TD(seconds=0.75)),
            yus.Word(text="dropped", confidence=0.963, start=DT.fromisoformat("2025-01-14T20:33:52.55"), duration=TD(seconds=0.54)),
        ]
    )

    # "gloves picks it up for dark"
    transcript.add_group().add_interpretation(confidence=0.865).words.extend(
        [
            yus.Word(text="gloves", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:33:56.2"), duration=TD(seconds=0.3)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:33:56.5"), duration=TD(seconds=0.3)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:33:56.8"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:33:57.1"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:33:57.4"), duration=TD(seconds=0.3)),
            yus.Word(text="dark", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:33:57.7"), duration=TD(seconds=0.3)),
        ]
    )

    # "hammer put to the end zone"
    transcript.add_group().add_interpretation(confidence=0.680).words.extend(
        [
            yus.Word(text="hammer", confidence=0.627, start=DT.fromisoformat("2025-01-14T20:33:58.6"), duration=TD(seconds=0.6)),
            yus.Word(text="put", confidence=0.653, start=DT.fromisoformat("2025-01-14T20:33:59.2"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:33:59.5"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:33:59.8"), duration=TD(seconds=0.3)),
            yus.Word(text="end", confidence=0.588, start=DT.fromisoformat("2025-01-14T20:34:00.1"), duration=TD(seconds=0.3)),
            yus.Word(text="zone", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:34:00.4"), duration=TD(seconds=0.3)),
        ]
    )

    # "caught by george for a score"
    transcript.add_group().add_interpretation(confidence=0.810).words.extend(
        [
            yus.Word(text="caught", confidence=0.814, start=DT.fromisoformat("2025-01-14T20:34:02.6"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:34:02.9"), duration=TD(seconds=0.3)),
            yus.Word(text="george", confidence=0.881, start=DT.fromisoformat("2025-01-14T20:34:03.2"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:34:03.5"), duration=TD(seconds=0.3)),
            yus.Word(text="a", confidence=0.639, start=DT.fromisoformat("2025-01-14T20:34:03.8"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:34:04.1"), duration=TD(seconds=0.3)),
        ]
    )

    # "glasses picks it up for white"
    transcript.add_group().add_interpretation(confidence=0.843).words.extend(
        [
            yus.Word(text="glasses", confidence=0.714, start=DT.fromisoformat("2025-01-14T20:34:04.8"), duration=TD(seconds=0.6)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:34:05.4"), duration=TD(seconds=0.3)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:34:05.7"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:34:06"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:34:06.3"), duration=TD(seconds=0.3)),
            yus.Word(text="white", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:34:06.6"), duration=TD(seconds=0.3)),
        ]
    )

    # "checked in"
    transcript.add_group().add_interpretation(confidence=0.494).words.extend(
        [
            yus.Word(text="checked", confidence=0.295, start=DT.fromisoformat("2025-01-14T20:34:08"), duration=TD(seconds=0.45)),
            yus.Word(text="in", confidence=0.692, start=DT.fromisoformat("2025-01-14T20:34:08.45"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick huck"
    transcript.add_group().add_interpretation(confidence=0.721).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:34:12.8"), duration=TD(seconds=0.3)),
            yus.Word(text="huck", confidence=0.729, start=DT.fromisoformat("2025-01-14T20:34:13.1"), duration=TD(seconds=0.3)),
        ]
    )

    # "deed by federbusch"
    transcript.add_group().add_interpretation(confidence=0.885).words.extend(
        [
            yus.Word(text="deed", confidence=0.841, start=DT.fromisoformat("2025-01-14T20:34:15"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:34:15.3"), duration=TD(seconds=0.3)),
            yus.Word(text="federbusch", confidence=0.930, start=DT.fromisoformat("2025-01-14T20:34:15.6"), duration=TD(seconds=0.9)),
        ]
    )

    # "bush picks it up"
    transcript.add_group().add_interpretation(confidence=0.859).words.extend(
        [
            yus.Word(text="bush", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:34:17.4"), duration=TD(seconds=0.3)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:34:17.7"), duration=TD(seconds=0.3)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:34:18"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:34:18.3"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick to yellow"
    transcript.add_group().add_interpretation(confidence=0.746).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:34:19.5"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:34:19.8"), duration=TD(seconds=0.3)),
            yus.Word(text="yellow", confidence=0.789, start=DT.fromisoformat("2025-01-14T20:34:20.1"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to bush"
    transcript.add_group().add_interpretation(confidence=0.739).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:34:21.5"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:34:22.1"), duration=TD(seconds=0.3)),
            yus.Word(text="bush", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:34:22.4"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick huck caught by blue in the end zone for a score"
    transcript.add_group().add_interpretation(confidence=0.755).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:34:23.8"), duration=TD(seconds=0.3)),
            yus.Word(text="huck", confidence=0.729, start=DT.fromisoformat("2025-01-14T20:34:24.1"), duration=TD(seconds=0.3)),
            yus.Word(text="caught", confidence=0.814, start=DT.fromisoformat("2025-01-14T20:34:24.4"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:34:24.7"), duration=TD(seconds=0.3)),
            yus.Word(text="blue", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:34:25"), duration=TD(seconds=0.3)),
            yus.Word(text="in", confidence=0.692, start=DT.fromisoformat("2025-01-14T20:34:25.3"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:34:25.6"), duration=TD(seconds=0.3)),
            yus.Word(text="end", confidence=0.588, start=DT.fromisoformat("2025-01-14T20:34:25.9"), duration=TD(seconds=0.3)),
            yus.Word(text="zone", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:34:26.2"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:34:26.5"), duration=TD(seconds=0.3)),
            yus.Word(text="a", confidence=0.639, start=DT.fromisoformat("2025-01-14T20:34:26.8"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:34:27.1"), duration=TD(seconds=0.3)),
        ]
    )

    # "close crop picks it up for white"
    transcript.add_group().add_interpretation(confidence=0.827).words.extend(
        [
            yus.Word(text="close", confidence=0.608, start=DT.fromisoformat("2025-01-14T20:34:28.7"), duration=TD(seconds=0.3)),
            yus.Word(text="crop", confidence=0.833, start=DT.fromisoformat("2025-01-14T20:34:29"), duration=TD(seconds=0.3)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:34:29.3"), duration=TD(seconds=0.3)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:34:29.6"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:34:29.9"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:34:30.2"), duration=TD(seconds=0.3)),
            yus.Word(text="white", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:34:30.5"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick swing"
    transcript.add_group().add_interpretation(confidence=0.741).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:34:32.7"), duration=TD(seconds=0.3)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:34:33"), duration=TD(seconds=0.3)),
        ]
    )

    # "to somebody for white"
    transcript.add_group().add_interpretation(confidence=0.819).words.extend(
        [
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:34:36.8"), duration=TD(seconds=0.3)),
            yus.Word(text="somebody", confidence=0.796, start=DT.fromisoformat("2025-01-14T20:34:37.1"), duration=TD(seconds=0.9)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:34:38"), duration=TD(seconds=0.3)),
            yus.Word(text="white", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:34:38.3"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand dump to glasses"
    transcript.add_group().add_interpretation(confidence=0.717).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:34:39.5"), duration=TD(seconds=0.6)),
            yus.Word(text="dump", confidence=0.772, start=DT.fromisoformat("2025-01-14T20:34:40.1"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:34:40.4"), duration=TD(seconds=0.3)),
            yus.Word(text="glasses", confidence=0.714, start=DT.fromisoformat("2025-01-14T20:34:40.7"), duration=TD(seconds=0.6)),
        ]
    )

    # "flick swing to close crop"
    transcript.add_group().add_interpretation(confidence=0.732).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:34:41.3"), duration=TD(seconds=0.3)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:34:41.6"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:34:41.9"), duration=TD(seconds=0.3)),
            yus.Word(text="close", confidence=0.608, start=DT.fromisoformat("2025-01-14T20:34:42.2"), duration=TD(seconds=0.3)),
            yus.Word(text="crop", confidence=0.833, start=DT.fromisoformat("2025-01-14T20:34:42.5"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand swing to glasses"
    transcript.add_group().add_interpretation(confidence=0.717).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:34:45"), duration=TD(seconds=0.6)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:34:45.6"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:34:45.9"), duration=TD(seconds=0.3)),
            yus.Word(text="glasses", confidence=0.714, start=DT.fromisoformat("2025-01-14T20:34:46.2"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to emily"
    transcript.add_group().add_interpretation(confidence=0.738).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:34:49"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:34:49.6"), duration=TD(seconds=0.3)),
            yus.Word(text="emily", confidence=0.830, start=DT.fromisoformat("2025-01-14T20:34:49.9"), duration=TD(seconds=0.9)),
        ]
    )

    # "backhand to glasses"
    transcript.add_group().add_interpretation(confidence=0.699).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:34:52.3"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:34:52.9"), duration=TD(seconds=0.3)),
            yus.Word(text="glasses", confidence=0.714, start=DT.fromisoformat("2025-01-14T20:34:53.2"), duration=TD(seconds=0.6)),
        ]
    )

    # "flick to close crop"
    transcript.add_group().add_interpretation(confidence=0.723).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:34:55.9"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:34:56.2"), duration=TD(seconds=0.3)),
            yus.Word(text="close", confidence=0.608, start=DT.fromisoformat("2025-01-14T20:34:56.5"), duration=TD(seconds=0.3)),
            yus.Word(text="crop", confidence=0.833, start=DT.fromisoformat("2025-01-14T20:34:56.8"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick put to the end zone off the wall to somebody for a score"
    transcript.add_group().add_interpretation(confidence=0.755).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:35:00.1"), duration=TD(seconds=0.3)),
            yus.Word(text="put", confidence=0.653, start=DT.fromisoformat("2025-01-14T20:35:00.4"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:35:00.7"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:35:01"), duration=TD(seconds=0.3)),
            yus.Word(text="end", confidence=0.588, start=DT.fromisoformat("2025-01-14T20:35:01.3"), duration=TD(seconds=0.3)),
            yus.Word(text="zone", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:35:01.6"), duration=TD(seconds=0.3)),
            yus.Word(text="off", confidence=0.867, start=DT.fromisoformat("2025-01-14T20:35:01.9"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:35:02.2"), duration=TD(seconds=0.3)),
            yus.Word(text="wall", confidence=0.964, start=DT.fromisoformat("2025-01-14T20:35:02.5"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:35:02.8"), duration=TD(seconds=0.3)),
            yus.Word(text="somebody", confidence=0.796, start=DT.fromisoformat("2025-01-14T20:35:03.1"), duration=TD(seconds=0.9)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:35:04"), duration=TD(seconds=0.3)),
            yus.Word(text="a", confidence=0.639, start=DT.fromisoformat("2025-01-14T20:35:04.3"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:35:04.6"), duration=TD(seconds=0.3)),
        ]
    )

    # "picked up by leg stripe"
    transcript.add_group().add_interpretation(confidence=0.839).words.extend(
        [
            yus.Word(text="picked", confidence=0.906, start=DT.fromisoformat("2025-01-14T20:35:08"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:35:08.3"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:35:08.6"), duration=TD(seconds=0.3)),
            yus.Word(text="leg", confidence=0.764, start=DT.fromisoformat("2025-01-14T20:35:08.9"), duration=TD(seconds=0.3)),
            yus.Word(text="stripe", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:35:09.2"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to hat"
    transcript.add_group().add_interpretation(confidence=0.754).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:35:10.0"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:35:10.6"), duration=TD(seconds=0.3)),
            yus.Word(text="hat", confidence=0.880, start=DT.fromisoformat("2025-01-14T20:35:10.9"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to bush"
    transcript.add_group().add_interpretation(confidence=0.739).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:35:12"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:35:12.6"), duration=TD(seconds=0.3)),
            yus.Word(text="bush", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:35:12.9"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick swing to naked"
    transcript.add_group().add_interpretation(confidence=0.787).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:35:15"), duration=TD(seconds=0.3)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:35:15.3"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:35:15.6"), duration=TD(seconds=0.3)),
            yus.Word(text="naked", confidence=0.931, start=DT.fromisoformat("2025-01-14T20:35:15.9"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to turtle"
    transcript.add_group().add_interpretation(confidence=0.752).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:35:20.5"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:35:21.1"), duration=TD(seconds=0.3)),
            yus.Word(text="turtle", confidence=0.872, start=DT.fromisoformat("2025-01-14T20:35:21.4"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand in the end zone caught by hat"
    transcript.add_group().add_interpretation(confidence=0.747).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:35:22.8"), duration=TD(seconds=0.6)),
            yus.Word(text="in", confidence=0.692, start=DT.fromisoformat("2025-01-14T20:35:23.4"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:35:23.7"), duration=TD(seconds=0.3)),
            yus.Word(text="end", confidence=0.588, start=DT.fromisoformat("2025-01-14T20:35:24"), duration=TD(seconds=0.3)),
            yus.Word(text="zone", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:35:24.3"), duration=TD(seconds=0.3)),
            yus.Word(text="caught", confidence=0.814, start=DT.fromisoformat("2025-01-14T20:35:24.6"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:35:24.9"), duration=TD(seconds=0.3)),
            yus.Word(text="hat", confidence=0.880, start=DT.fromisoformat("2025-01-14T20:35:25.2"), duration=TD(seconds=0.3)),
        ]
    )

    # "joe picks it up for white"
    transcript.add_group().add_interpretation(confidence=0.864).words.extend(
        [
            yus.Word(text="joe", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:35:29.5"), duration=TD(seconds=0.3)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:35:29.8"), duration=TD(seconds=0.3)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:35:30.1"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:35:30.4"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:35:30.7"), duration=TD(seconds=0.3)),
            yus.Word(text="white", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:35:31"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick huck"
    transcript.add_group().add_interpretation(confidence=0.721).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:35:33.8"), duration=TD(seconds=0.3)),
            yus.Word(text="huck", confidence=0.729, start=DT.fromisoformat("2025-01-14T20:35:34.1"), duration=TD(seconds=0.3)),
        ]
    )

    # "caught by pikachu for a score"
    transcript.add_group().add_interpretation(confidence=0.817).words.extend(
        [
            yus.Word(text="caught", confidence=0.814, start=DT.fromisoformat("2025-01-14T20:35:38.8"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:35:39.1"), duration=TD(seconds=0.3)),
            yus.Word(text="pikachu", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:35:39.4"), duration=TD(seconds=0.9)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:35:40.3"), duration=TD(seconds=0.3)),
            yus.Word(text="a", confidence=0.639, start=DT.fromisoformat("2025-01-14T20:35:40.6"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:35:40.9"), duration=TD(seconds=0.3)),
        ]
    )

    # "picked up by naked for black"
    transcript.add_group().add_interpretation(confidence=0.884).words.extend(
        [
            yus.Word(text="picked", confidence=0.906, start=DT.fromisoformat("2025-01-14T20:35:43"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:35:43.3"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:35:43.6"), duration=TD(seconds=0.3)),
            yus.Word(text="naked", confidence=0.931, start=DT.fromisoformat("2025-01-14T20:35:43.9"), duration=TD(seconds=0.6)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:35:44.5"), duration=TD(seconds=0.3)),
            yus.Word(text="black", confidence=0.800, start=DT.fromisoformat("2025-01-14T20:35:44.8"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand huck deed by joe in the end zone"
    transcript.add_group().add_interpretation(confidence=0.743).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:35:50.7"), duration=TD(seconds=0.6)),
            yus.Word(text="huck", confidence=0.729, start=DT.fromisoformat("2025-01-14T20:35:51.3"), duration=TD(seconds=0.3)),
            yus.Word(text="deed", confidence=0.841, start=DT.fromisoformat("2025-01-14T20:35:54.2"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:35:54.5"), duration=TD(seconds=0.3)),
            yus.Word(text="joe", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:35:54.8"), duration=TD(seconds=0.3)),
            yus.Word(text="in", confidence=0.692, start=DT.fromisoformat("2025-01-14T20:35:55.1"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:35:55.4"), duration=TD(seconds=0.3)),
            yus.Word(text="end", confidence=0.588, start=DT.fromisoformat("2025-01-14T20:35:55.7"), duration=TD(seconds=0.3)),
            yus.Word(text="zone", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:35:56"), duration=TD(seconds=0.3)),
        ]
    )

    # "picked up by close crop"
    transcript.add_group().add_interpretation(confidence=0.831).words.extend(
        [
            yus.Word(text="picked", confidence=0.906, start=DT.fromisoformat("2025-01-14T20:36:00.8"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:36:01.1"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:36:01.4"), duration=TD(seconds=0.3)),
            yus.Word(text="close", confidence=0.608, start=DT.fromisoformat("2025-01-14T20:36:01.7"), duration=TD(seconds=0.3)),
            yus.Word(text="crop", confidence=0.833, start=DT.fromisoformat("2025-01-14T20:36:02"), duration=TD(seconds=0.3)),
        ]
    )

    # "taps it in"
    transcript.add_group().add_interpretation(confidence=0.795).words.extend(
        [
            yus.Word(text="taps", confidence=0.806, start=DT.fromisoformat("2025-01-14T20:36:06"), duration=TD(seconds=0.3)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:36:06.3"), duration=TD(seconds=0.3)),
            yus.Word(text="in", confidence=0.692, start=DT.fromisoformat("2025-01-14T20:36:06.6"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick to pikachu"
    transcript.add_group().add_interpretation(confidence=0.791).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:36:07.8"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:36:08.1"), duration=TD(seconds=0.3)),
            yus.Word(text="pikachu", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:36:08.4"), duration=TD(seconds=0.9)),
        ]
    )

    # "backhand to kaia"
    transcript.add_group().add_interpretation(confidence=0.658).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:36:09.5"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:36:10.1"), duration=TD(seconds=0.3)),
            yus.Word(text="kaia", confidence=0.592, start=DT.fromisoformat("2025-01-14T20:36:10.4"), duration=TD(seconds=0.75)),
        ]
    )

    # "flick swing to pikachu"
    transcript.add_group().add_interpretation(confidence=0.786).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:36:12.5"), duration=TD(seconds=0.3)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:36:12.8"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:36:13.1"), duration=TD(seconds=0.3)),
            yus.Word(text="pikachu", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:36:13.4"), duration=TD(seconds=0.9)),
        ]
    )

    # "flick swing to close crop"
    transcript.add_group().add_interpretation(confidence=0.732).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:36:14.2"), duration=TD(seconds=0.3)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:36:14.5"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:36:14.8"), duration=TD(seconds=0.3)),
            yus.Word(text="close", confidence=0.608, start=DT.fromisoformat("2025-01-14T20:36:15.1"), duration=TD(seconds=0.3)),
            yus.Word(text="crop", confidence=0.833, start=DT.fromisoformat("2025-01-14T20:36:15.4"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick to the kid"
    transcript.add_group().add_interpretation(confidence=0.762).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:36:17"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:36:17.3"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:36:17.6"), duration=TD(seconds=0.3)),
            yus.Word(text="kid", confidence=0.838, start=DT.fromisoformat("2025-01-14T20:36:17.9"), duration=TD(seconds=0.3)),
        ]
    )

    # "dump to kaia"
    transcript.add_group().add_interpretation(confidence=0.700).words.extend(
        [
            yus.Word(text="dump", confidence=0.772, start=DT.fromisoformat("2025-01-14T20:36:26"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:36:26.3"), duration=TD(seconds=0.3)),
            yus.Word(text="kaia", confidence=0.592, start=DT.fromisoformat("2025-01-14T20:36:26.6"), duration=TD(seconds=0.75)),
        ]
    )

    # "flick in the end zone to the kid for a score"
    transcript.add_group().add_interpretation(confidence=0.735).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:36:27"), duration=TD(seconds=0.3)),
            yus.Word(text="in", confidence=0.692, start=DT.fromisoformat("2025-01-14T20:36:27.3"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:36:27.6"), duration=TD(seconds=0.3)),
            yus.Word(text="end", confidence=0.588, start=DT.fromisoformat("2025-01-14T20:36:27.9"), duration=TD(seconds=0.3)),
            yus.Word(text="zone", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:36:28.2"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:36:28.5"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:36:28.8"), duration=TD(seconds=0.3)),
            yus.Word(text="kid", confidence=0.838, start=DT.fromisoformat("2025-01-14T20:36:29.1"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:36:29.4"), duration=TD(seconds=0.3)),
            yus.Word(text="a", confidence=0.639, start=DT.fromisoformat("2025-01-14T20:36:29.7"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:36:30.0"), duration=TD(seconds=0.3)),
        ]
    )

    # "picked up by leg stripes"
    transcript.add_group().add_interpretation(confidence=0.872).words.extend(
        [
            yus.Word(text="picked", confidence=0.906, start=DT.fromisoformat("2025-01-14T20:36:34.8"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:36:35.1"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:36:35.4"), duration=TD(seconds=0.3)),
            yus.Word(text="leg", confidence=0.764, start=DT.fromisoformat("2025-01-14T20:36:35.7"), duration=TD(seconds=0.3)),
            yus.Word(text="stripes", confidence=0.884, start=DT.fromisoformat("2025-01-14T20:36:36"), duration=TD(seconds=0.6)),
        ]
    )

    # "flick to gloves"
    transcript.add_group().add_interpretation(confidence=0.771).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:36:37"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:36:37.3"), duration=TD(seconds=0.3)),
            yus.Word(text="gloves", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:36:37.6"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to leg stripes"
    transcript.add_group().add_interpretation(confidence=0.758).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:36:39.4"), duration=TD(seconds=0.5)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:36:39.9"), duration=TD(seconds=0.2)),
            yus.Word(text="leg", confidence=0.764, start=DT.fromisoformat("2025-01-14T20:36:40.1"), duration=TD(seconds=0.2)),
            yus.Word(text="stripes", confidence=0.884, start=DT.fromisoformat("2025-01-14T20:36:40.3"), duration=TD(seconds=0.6)),
        ]
    )

    # "stolen by stephen butler"
    transcript.add_group().add_interpretation(confidence=0.812).words.extend(
        [
            yus.Word(text="stolen", confidence=0.948, start=DT.fromisoformat("2025-01-14T20:36:40.6"), duration=TD(seconds=0.6)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:36:41.2"), duration=TD(seconds=0.3)),
            yus.Word(text="stephen", confidence=0.674, start=DT.fromisoformat("2025-01-14T20:36:41.5"), duration=TD(seconds=0.6)),
            yus.Word(text="butler", confidence=0.744, start=DT.fromisoformat("2025-01-14T20:36:42.1"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to the kid"
    transcript.add_group().add_interpretation(confidence=0.745).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:36:44.1"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:36:44.7"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:36:45"), duration=TD(seconds=0.3)),
            yus.Word(text="kid", confidence=0.838, start=DT.fromisoformat("2025-01-14T20:36:45.3"), duration=TD(seconds=0.3)),
        ]
    )

    # "stolen by gloves"
    transcript.add_group().add_interpretation(confidence=0.899).words.extend(
        [
            yus.Word(text="stolen", confidence=0.948, start=DT.fromisoformat("2025-01-14T20:36:45.6"), duration=TD(seconds=0.6)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:36:46.2"), duration=TD(seconds=0.3)),
            yus.Word(text="gloves", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:36:46.5"), duration=TD(seconds=0.3)),
        ]
    )

    # "gloves taps it in"
    transcript.add_group().add_interpretation(confidence=0.812).words.extend(
        [
            yus.Word(text="gloves", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:36:49.4"), duration=TD(seconds=0.3)),
            yus.Word(text="taps", confidence=0.806, start=DT.fromisoformat("2025-01-14T20:36:49.7"), duration=TD(seconds=0.3)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:36:50.0"), duration=TD(seconds=0.3)),
            yus.Word(text="in", confidence=0.692, start=DT.fromisoformat("2025-01-14T20:36:50.3"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to turtle"
    transcript.add_group().add_interpretation(confidence=0.752).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:36:51.8"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:36:52.4"), duration=TD(seconds=0.3)),
            yus.Word(text="turtle", confidence=0.872, start=DT.fromisoformat("2025-01-14T20:36:52.7"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to i dunno"
    transcript.add_group().add_interpretation(confidence=0.721).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:36:54.9"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:36:55.5"), duration=TD(seconds=0.3)),
            yus.Word(text="i", confidence=0.749, start=DT.fromisoformat("2025-01-14T20:36:55.8"), duration=TD(seconds=0.3)),
            yus.Word(text="dunno", confidence=0.750, start=DT.fromisoformat("2025-01-14T20:36:56.1"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to bush"
    transcript.add_group().add_interpretation(confidence=0.739).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:36:57"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:36:57.6"), duration=TD(seconds=0.3)),
            yus.Word(text="bush", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:36:57.9"), duration=TD(seconds=0.3)),
        ]
    )

    # "bush backhand to george"
    transcript.add_group().add_interpretation(confidence=0.775).words.extend(
        [
            yus.Word(text="bush", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:36:59.5"), duration=TD(seconds=0.3)),
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:36:59.8"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:37:00.4"), duration=TD(seconds=0.3)),
            yus.Word(text="george", confidence=0.881, start=DT.fromisoformat("2025-01-14T20:37:00.7"), duration=TD(seconds=0.3)),
        ]
    )

    # "george backhand dropped"
    transcript.add_group().add_interpretation(confidence=0.830).words.extend(
        [
            yus.Word(text="george", confidence=0.881, start=DT.fromisoformat("2025-01-14T20:37:02.4"), duration=TD(seconds=0.3)),
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:37:02.7"), duration=TD(seconds=0.6)),
            yus.Word(text="dropped", confidence=0.963, start=DT.fromisoformat("2025-01-14T20:37:03.3"), duration=TD(seconds=0.54)),
        ]
    )

    # "tristan picks up for white"
    transcript.add_group().add_interpretation(confidence=0.826).words.extend(
        [
            yus.Word(text="tristan", confidence=0.672, start=DT.fromisoformat("2025-01-14T20:37:05.7"), duration=TD(seconds=0.4)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:37:06.1"), duration=TD(seconds=0.2)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:37:06.3"), duration=TD(seconds=0.2)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:37:06.5"), duration=TD(seconds=0.2)),
            yus.Word(text="white", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:37:06.7"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to kaia"
    transcript.add_group().add_interpretation(confidence=0.658).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:37:06.8"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:37:07.4"), duration=TD(seconds=0.3)),
            yus.Word(text="kaia", confidence=0.592, start=DT.fromisoformat("2025-01-14T20:37:07.7"), duration=TD(seconds=0.75)),
        ]
    )

    # "flick swing to kid"
    transcript.add_group().add_interpretation(confidence=0.764).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:37:09.8"), duration=TD(seconds=0.3)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:37:10.1"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:37:10.4"), duration=TD(seconds=0.3)),
            yus.Word(text="kid", confidence=0.838, start=DT.fromisoformat("2025-01-14T20:37:10.7"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand swing to tristan"
    transcript.add_group().add_interpretation(confidence=0.706).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:37:13.6"), duration=TD(seconds=0.6)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:37:14.2"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:37:14.5"), duration=TD(seconds=0.3)),
            yus.Word(text="tristan", confidence=0.672, start=DT.fromisoformat("2025-01-14T20:37:14.8"), duration=TD(seconds=0.6)),
        ]
    )

    # "flick to blondie"
    transcript.add_group().add_interpretation(confidence=0.744).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:37:16.8"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:37:17.1"), duration=TD(seconds=0.3)),
            yus.Word(text="blondie", confidence=0.783, start=DT.fromisoformat("2025-01-14T20:37:17.4"), duration=TD(seconds=0.6)),
        ]
    )

    # "flick to glasses"
    transcript.add_group().add_interpretation(confidence=0.721).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:37:19.7"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:37:20.0"), duration=TD(seconds=0.3)),
            yus.Word(text="glasses", confidence=0.714, start=DT.fromisoformat("2025-01-14T20:37:20.3"), duration=TD(seconds=0.6)),
        ]
    )

    # "dump to tristan"
    transcript.add_group().add_interpretation(confidence=0.727).words.extend(
        [
            yus.Word(text="dump", confidence=0.772, start=DT.fromisoformat("2025-01-14T20:37:24.8"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:37:25.1"), duration=TD(seconds=0.3)),
            yus.Word(text="tristan", confidence=0.672, start=DT.fromisoformat("2025-01-14T20:37:25.4"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to glasses"
    transcript.add_group().add_interpretation(confidence=0.699).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:37:27.4"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:37:28"), duration=TD(seconds=0.3)),
            yus.Word(text="glasses", confidence=0.714, start=DT.fromisoformat("2025-01-14T20:37:28.3"), duration=TD(seconds=0.6)),
        ]
    )

    # "to tristan in the end zone for a score"
    transcript.add_group().add_interpretation(confidence=0.716).words.extend(
        [
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:37:30.0"), duration=TD(seconds=0.3)),
            yus.Word(text="tristan", confidence=0.672, start=DT.fromisoformat("2025-01-14T20:37:30.3"), duration=TD(seconds=0.6)),
            yus.Word(text="in", confidence=0.692, start=DT.fromisoformat("2025-01-14T20:37:30.9"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:37:31.2"), duration=TD(seconds=0.3)),
            yus.Word(text="end", confidence=0.588, start=DT.fromisoformat("2025-01-14T20:37:31.5"), duration=TD(seconds=0.3)),
            yus.Word(text="zone", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:37:31.8"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:37:32.1"), duration=TD(seconds=0.3)),
            yus.Word(text="a", confidence=0.639, start=DT.fromisoformat("2025-01-14T20:37:32.4"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:37:32.7"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to george"
    transcript.add_group().add_interpretation(confidence=0.755).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:37:35.8"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:37:36.4"), duration=TD(seconds=0.3)),
            yus.Word(text="george", confidence=0.881, start=DT.fromisoformat("2025-01-14T20:37:36.7"), duration=TD(seconds=0.3)),
        ]
    )

    # "george backhand huck"
    transcript.add_group().add_interpretation(confidence=0.752).words.extend(
        [
            yus.Word(text="george", confidence=0.881, start=DT.fromisoformat("2025-01-14T20:37:38"), duration=TD(seconds=0.3)),
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:37:38.3"), duration=TD(seconds=0.6)),
            yus.Word(text="huck", confidence=0.729, start=DT.fromisoformat("2025-01-14T20:37:38.9"), duration=TD(seconds=0.3)),
        ]
    )

    # "deed by glasses"
    transcript.add_group().add_interpretation(confidence=0.813).words.extend(
        [
            yus.Word(text="deed", confidence=0.841, start=DT.fromisoformat("2025-01-14T20:37:43.2"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:37:43.5"), duration=TD(seconds=0.3)),
            yus.Word(text="glasses", confidence=0.714, start=DT.fromisoformat("2025-01-14T20:37:43.8"), duration=TD(seconds=0.6)),
        ]
    )

    # "glasses picks it up for white"
    transcript.add_group().add_interpretation(confidence=0.843).words.extend(
        [
            yus.Word(text="glasses", confidence=0.714, start=DT.fromisoformat("2025-01-14T20:37:44.4"), duration=TD(seconds=0.6)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:37:45"), duration=TD(seconds=0.3)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:37:45.3"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:37:45.6"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:37:45.9"), duration=TD(seconds=0.3)),
            yus.Word(text="white", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:37:46.2"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick to tristan"
    transcript.add_group().add_interpretation(confidence=0.707).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:37:52.5"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:37:52.8"), duration=TD(seconds=0.3)),
            yus.Word(text="tristan", confidence=0.672, start=DT.fromisoformat("2025-01-14T20:37:53.1"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand swing to glasses"
    transcript.add_group().add_interpretation(confidence=0.717).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:37:56"), duration=TD(seconds=0.6)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:37:56.6"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:37:56.9"), duration=TD(seconds=0.3)),
            yus.Word(text="glasses", confidence=0.714, start=DT.fromisoformat("2025-01-14T20:37:57.2"), duration=TD(seconds=0.6)),
        ]
    )

    # "flick to tristan"
    transcript.add_group().add_interpretation(confidence=0.707).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:37:57.9"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:37:58.2"), duration=TD(seconds=0.3)),
            yus.Word(text="tristan", confidence=0.672, start=DT.fromisoformat("2025-01-14T20:37:58.5"), duration=TD(seconds=0.6)),
        ]
    )

    # "flick swing to blondie"
    transcript.add_group().add_interpretation(confidence=0.750).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:38:00.0"), duration=TD(seconds=0.3)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:38:00.3"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:38:00.6"), duration=TD(seconds=0.3)),
            yus.Word(text="blondie", confidence=0.783, start=DT.fromisoformat("2025-01-14T20:38:00.9"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to tristan"
    transcript.add_group().add_interpretation(confidence=0.685).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:38:05.3"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:38:05.9"), duration=TD(seconds=0.3)),
            yus.Word(text="tristan", confidence=0.672, start=DT.fromisoformat("2025-01-14T20:38:06.2"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to emily"
    transcript.add_group().add_interpretation(confidence=0.738).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:38:06.5"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:38:07.1"), duration=TD(seconds=0.3)),
            yus.Word(text="emily", confidence=0.830, start=DT.fromisoformat("2025-01-14T20:38:07.4"), duration=TD(seconds=0.9)),
        ]
    )

    # "backhand to tristan"
    transcript.add_group().add_interpretation(confidence=0.685).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:38:08.7"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:38:09.3"), duration=TD(seconds=0.3)),
            yus.Word(text="tristan", confidence=0.672, start=DT.fromisoformat("2025-01-14T20:38:09.6"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to blondie"
    transcript.add_group().add_interpretation(confidence=0.722).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:38:10.8"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:38:11.4"), duration=TD(seconds=0.3)),
            yus.Word(text="blondie", confidence=0.783, start=DT.fromisoformat("2025-01-14T20:38:11.7"), duration=TD(seconds=0.6)),
        ]
    )

    # "scoober in the end zone for a score to somebody"
    transcript.add_group().add_interpretation(confidence=0.742).words.extend(
        [
            yus.Word(text="scoober", confidence=0.850, start=DT.fromisoformat("2025-01-14T20:38:12.8"), duration=TD(seconds=0.6)),
            yus.Word(text="in", confidence=0.692, start=DT.fromisoformat("2025-01-14T20:38:13.4"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:38:13.7"), duration=TD(seconds=0.3)),
            yus.Word(text="end", confidence=0.588, start=DT.fromisoformat("2025-01-14T20:38:14"), duration=TD(seconds=0.3)),
            yus.Word(text="zone", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:38:14.3"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:38:14.6"), duration=TD(seconds=0.3)),
            yus.Word(text="a", confidence=0.639, start=DT.fromisoformat("2025-01-14T20:38:14.9"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:38:15.2"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:38:15.5"), duration=TD(seconds=0.3)),
            yus.Word(text="somebody", confidence=0.796, start=DT.fromisoformat("2025-01-14T20:38:15.8"), duration=TD(seconds=0.9)),
        ]
    )

    # "picked up by george"
    transcript.add_group().add_interpretation(confidence=0.899).words.extend(
        [
            yus.Word(text="picked", confidence=0.906, start=DT.fromisoformat("2025-01-14T20:38:17"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:38:17.3"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:38:17.6"), duration=TD(seconds=0.3)),
            yus.Word(text="george", confidence=0.881, start=DT.fromisoformat("2025-01-14T20:38:17.9"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to bluey"
    transcript.add_group().add_interpretation(confidence=0.752).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:38:21"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:38:21.6"), duration=TD(seconds=0.3)),
            yus.Word(text="bluey", confidence=0.873, start=DT.fromisoformat("2025-01-14T20:38:21.9"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand huck turfed"
    transcript.add_group().add_interpretation(confidence=0.731).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:38:24.3"), duration=TD(seconds=0.6)),
            yus.Word(text="huck", confidence=0.729, start=DT.fromisoformat("2025-01-14T20:38:24.9"), duration=TD(seconds=0.3)),
            yus.Word(text="turfed", confidence=0.817, start=DT.fromisoformat("2025-01-14T20:38:25.2"), duration=TD(seconds=0.54)),
        ]
    )

    # "tristan backhand to close crop"
    transcript.add_group().add_interpretation(confidence=0.699).words.extend(
        [
            yus.Word(text="tristan", confidence=0.672, start=DT.fromisoformat("2025-01-14T20:38:37.5"), duration=TD(seconds=0.6)),
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:38:38.1"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:38:38.7"), duration=TD(seconds=0.3)),
            yus.Word(text="close", confidence=0.608, start=DT.fromisoformat("2025-01-14T20:38:39"), duration=TD(seconds=0.3)),
            yus.Word(text="crop", confidence=0.833, start=DT.fromisoformat("2025-01-14T20:38:39.3"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to joe"
    transcript.add_group().add_interpretation(confidence=0.739).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:38:39.8"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:38:40.4"), duration=TD(seconds=0.3)),
            yus.Word(text="joe", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:38:40.7"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand across in the end zone emily for a score"
    transcript.add_group().add_interpretation(confidence=0.724).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:38:42.5"), duration=TD(seconds=0.6)),
            yus.Word(text="across", confidence=0.730, start=DT.fromisoformat("2025-01-14T20:38:43.1"), duration=TD(seconds=0.6)),
            yus.Word(text="in", confidence=0.692, start=DT.fromisoformat("2025-01-14T20:38:43.7"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:38:44"), duration=TD(seconds=0.3)),
            yus.Word(text="end", confidence=0.588, start=DT.fromisoformat("2025-01-14T20:38:44.3"), duration=TD(seconds=0.3)),
            yus.Word(text="zone", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:38:44.6"), duration=TD(seconds=0.3)),
            yus.Word(text="emily", confidence=0.830, start=DT.fromisoformat("2025-01-14T20:38:44.9"), duration=TD(seconds=0.9)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:38:45.8"), duration=TD(seconds=0.3)),
            yus.Word(text="a", confidence=0.639, start=DT.fromisoformat("2025-01-14T20:38:46.1"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:38:46.4"), duration=TD(seconds=0.3)),
        ]
    )

    # "picked up by naked for black"
    transcript.add_group().add_interpretation(confidence=0.884).words.extend(
        [
            yus.Word(text="picked", confidence=0.906, start=DT.fromisoformat("2025-01-14T20:38:51"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:38:51.3"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:38:51.6"), duration=TD(seconds=0.3)),
            yus.Word(text="naked", confidence=0.931, start=DT.fromisoformat("2025-01-14T20:38:51.9"), duration=TD(seconds=0.6)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:38:52.5"), duration=TD(seconds=0.3)),
            yus.Word(text="black", confidence=0.800, start=DT.fromisoformat("2025-01-14T20:38:52.8"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick swing to george"
    transcript.add_group().add_interpretation(confidence=0.775).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:38:55"), duration=TD(seconds=0.3)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:38:55.3"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:38:55.6"), duration=TD(seconds=0.3)),
            yus.Word(text="george", confidence=0.881, start=DT.fromisoformat("2025-01-14T20:38:55.9"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to yellow stripe"
    transcript.add_group().add_interpretation(confidence=0.722).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:38:59.1"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:38:59.7"), duration=TD(seconds=0.3)),
            yus.Word(text="yellow", confidence=0.789, start=DT.fromisoformat("2025-01-14T20:39:00.0"), duration=TD(seconds=0.6)),
            yus.Word(text="stripe", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:39:00.6"), duration=TD(seconds=0.3)),
        ]
    )

    # "scoober to hat"
    transcript.add_group().add_interpretation(confidence=0.822).words.extend(
        [
            yus.Word(text="scoober", confidence=0.850, start=DT.fromisoformat("2025-01-14T20:39:01"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:39:01.6"), duration=TD(seconds=0.3)),
            yus.Word(text="hat", confidence=0.880, start=DT.fromisoformat("2025-01-14T20:39:01.9"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to naked"
    transcript.add_group().add_interpretation(confidence=0.771).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:39:04.9"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:39:05.5"), duration=TD(seconds=0.3)),
            yus.Word(text="naked", confidence=0.931, start=DT.fromisoformat("2025-01-14T20:39:05.8"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand swing to purple leg stripe"
    transcript.add_group().add_interpretation(confidence=0.760).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:39:08.9"), duration=TD(seconds=0.6)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:39:09.5"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:39:09.8"), duration=TD(seconds=0.3)),
            yus.Word(text="purple", confidence=0.926, start=DT.fromisoformat("2025-01-14T20:39:10.1"), duration=TD(seconds=0.6)),
            yus.Word(text="leg", confidence=0.764, start=DT.fromisoformat("2025-01-14T20:39:10.7"), duration=TD(seconds=0.3)),
            yus.Word(text="stripe", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:39:11"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to yellow stripe yellow fringe"
    transcript.add_group().add_interpretation(confidence=0.754).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:39:12.8"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:39:13.4"), duration=TD(seconds=0.3)),
            yus.Word(text="yellow", confidence=0.789, start=DT.fromisoformat("2025-01-14T20:39:13.7"), duration=TD(seconds=0.6)),
            yus.Word(text="stripe", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:39:14.3"), duration=TD(seconds=0.3)),
            yus.Word(text="yellow", confidence=0.789, start=DT.fromisoformat("2025-01-14T20:39:14.6"), duration=TD(seconds=0.6)),
            yus.Word(text="fringe", confidence=0.848, start=DT.fromisoformat("2025-01-14T20:39:15.2"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to the end zone pants stripe off the wall no score"
    transcript.add_group().add_interpretation(confidence=0.748).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:39:15.5"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:39:16.1"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:39:16.4"), duration=TD(seconds=0.3)),
            yus.Word(text="end", confidence=0.588, start=DT.fromisoformat("2025-01-14T20:39:16.7"), duration=TD(seconds=0.3)),
            yus.Word(text="zone", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:39:17"), duration=TD(seconds=0.3)),
            yus.Word(text="pants", confidence=0.550, start=DT.fromisoformat("2025-01-14T20:39:17.3"), duration=TD(seconds=0.3)),
            yus.Word(text="stripe", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:39:17.6"), duration=TD(seconds=0.3)),
            yus.Word(text="off", confidence=0.867, start=DT.fromisoformat("2025-01-14T20:39:17.9"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:39:18.2"), duration=TD(seconds=0.3)),
            yus.Word(text="wall", confidence=0.964, start=DT.fromisoformat("2025-01-14T20:39:18.5"), duration=TD(seconds=0.3)),
            yus.Word(text="no", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:39:18.8"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:39:19.1"), duration=TD(seconds=0.3)),
        ]
    )

    # "picked up by close crop for white"
    transcript.add_group().add_interpretation(confidence=0.843).words.extend(
        [
            yus.Word(text="picked", confidence=0.906, start=DT.fromisoformat("2025-01-14T20:39:19.9"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:39:20.2"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:39:20.5"), duration=TD(seconds=0.3)),
            yus.Word(text="close", confidence=0.608, start=DT.fromisoformat("2025-01-14T20:39:20.8"), duration=TD(seconds=0.3)),
            yus.Word(text="crop", confidence=0.833, start=DT.fromisoformat("2025-01-14T20:39:21.1"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:39:21.4"), duration=TD(seconds=0.3)),
            yus.Word(text="white", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:39:21.7"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to tristan"
    transcript.add_group().add_interpretation(confidence=0.685).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:39:21.8"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:39:22.4"), duration=TD(seconds=0.3)),
            yus.Word(text="tristan", confidence=0.672, start=DT.fromisoformat("2025-01-14T20:39:22.7"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to pikachu"
    transcript.add_group().add_interpretation(confidence=0.769).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:39:22.9"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:39:23.5"), duration=TD(seconds=0.3)),
            yus.Word(text="pikachu", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:39:23.8"), duration=TD(seconds=0.9)),
        ]
    )

    # "backhand swing to joe"
    transcript.add_group().add_interpretation(confidence=0.747).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:39:27"), duration=TD(seconds=0.6)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:39:27.6"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:39:27.9"), duration=TD(seconds=0.3)),
            yus.Word(text="joe", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:39:28.2"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick to pikachu"
    transcript.add_group().add_interpretation(confidence=0.791).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:39:30.6"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:39:30.9"), duration=TD(seconds=0.3)),
            yus.Word(text="pikachu", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:39:31.2"), duration=TD(seconds=0.9)),
        ]
    )

    # "backhand to close crop"
    transcript.add_group().add_interpretation(confidence=0.706).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:39:34.2"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:39:34.8"), duration=TD(seconds=0.3)),
            yus.Word(text="close", confidence=0.608, start=DT.fromisoformat("2025-01-14T20:39:35.1"), duration=TD(seconds=0.3)),
            yus.Word(text="crop", confidence=0.833, start=DT.fromisoformat("2025-01-14T20:39:35.4"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to kaia swing"
    transcript.add_group().add_interpretation(confidence=0.686).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:39:36"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:39:36.6"), duration=TD(seconds=0.3)),
            yus.Word(text="kaia", confidence=0.592, start=DT.fromisoformat("2025-01-14T20:39:36.9"), duration=TD(seconds=0.75)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:39:37.65"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick to close crop swing"
    transcript.add_group().add_interpretation(confidence=0.732).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:39:40.0"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:39:40.3"), duration=TD(seconds=0.3)),
            yus.Word(text="close", confidence=0.608, start=DT.fromisoformat("2025-01-14T20:39:40.6"), duration=TD(seconds=0.3)),
            yus.Word(text="crop", confidence=0.833, start=DT.fromisoformat("2025-01-14T20:39:40.9"), duration=TD(seconds=0.3)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:39:41.2"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to pikachu"
    transcript.add_group().add_interpretation(confidence=0.769).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:39:42"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:39:42.6"), duration=TD(seconds=0.3)),
            yus.Word(text="pikachu", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:39:42.9"), duration=TD(seconds=0.9)),
        ]
    )

    # "backhand to stephen butler for a score"
    transcript.add_group().add_interpretation(confidence=0.726).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:39:44.5"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:39:45.1"), duration=TD(seconds=0.3)),
            yus.Word(text="stephen", confidence=0.674, start=DT.fromisoformat("2025-01-14T20:39:45.4"), duration=TD(seconds=0.6)),
            yus.Word(text="butler", confidence=0.744, start=DT.fromisoformat("2025-01-14T20:39:46"), duration=TD(seconds=0.6)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:39:46.6"), duration=TD(seconds=0.3)),
            yus.Word(text="a", confidence=0.639, start=DT.fromisoformat("2025-01-14T20:39:46.9"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:39:47.2"), duration=TD(seconds=0.3)),
        ]
    )

    # "hat checks in for dark"
    transcript.add_group().add_interpretation(confidence=0.827).words.extend(
        [
            yus.Word(text="hat", confidence=0.880, start=DT.fromisoformat("2025-01-14T20:39:57.3"), duration=TD(seconds=0.3)),
            yus.Word(text="checks", confidence=0.843, start=DT.fromisoformat("2025-01-14T20:39:57.6"), duration=TD(seconds=0.3)),
            yus.Word(text="in", confidence=0.692, start=DT.fromisoformat("2025-01-14T20:39:57.9"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:39:58.2"), duration=TD(seconds=0.3)),
            yus.Word(text="dark", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:39:58.5"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to turtle"
    transcript.add_group().add_interpretation(confidence=0.752).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:39:58.8"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:39:59.4"), duration=TD(seconds=0.3)),
            yus.Word(text="turtle", confidence=0.872, start=DT.fromisoformat("2025-01-14T20:39:59.7"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to leg stripe"
    transcript.add_group().add_interpretation(confidence=0.716).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:40:00.0"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:40:00.6"), duration=TD(seconds=0.3)),
            yus.Word(text="leg", confidence=0.764, start=DT.fromisoformat("2025-01-14T20:40:00.9"), duration=TD(seconds=0.3)),
            yus.Word(text="stripe", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:40:01.2"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to hat"
    transcript.add_group().add_interpretation(confidence=0.754).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:40:03"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:40:03.6"), duration=TD(seconds=0.3)),
            yus.Word(text="hat", confidence=0.880, start=DT.fromisoformat("2025-01-14T20:40:03.9"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to leg stripe"
    transcript.add_group().add_interpretation(confidence=0.716).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:40:05.5"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:40:06.1"), duration=TD(seconds=0.3)),
            yus.Word(text="leg", confidence=0.764, start=DT.fromisoformat("2025-01-14T20:40:06.4"), duration=TD(seconds=0.3)),
            yus.Word(text="stripe", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:40:06.7"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick to bush"
    transcript.add_group().add_interpretation(confidence=0.761).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:40:07"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:40:07.3"), duration=TD(seconds=0.3)),
            yus.Word(text="bush", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:40:07.6"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick put to turtle off the wall for a score"
    transcript.add_group().add_interpretation(confidence=0.784).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:40:10.0"), duration=TD(seconds=0.3)),
            yus.Word(text="put", confidence=0.653, start=DT.fromisoformat("2025-01-14T20:40:10.3"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:40:10.6"), duration=TD(seconds=0.3)),
            yus.Word(text="turtle", confidence=0.872, start=DT.fromisoformat("2025-01-14T20:40:10.9"), duration=TD(seconds=0.6)),
            yus.Word(text="off", confidence=0.867, start=DT.fromisoformat("2025-01-14T20:40:11.5"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:40:11.8"), duration=TD(seconds=0.3)),
            yus.Word(text="wall", confidence=0.964, start=DT.fromisoformat("2025-01-14T20:40:12.1"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:40:12.4"), duration=TD(seconds=0.3)),
            yus.Word(text="a", confidence=0.639, start=DT.fromisoformat("2025-01-14T20:40:12.7"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:40:13"), duration=TD(seconds=0.3)),
        ]
    )

    # "glasses picks it up for white"
    transcript.add_group().add_interpretation(confidence=0.843).words.extend(
        [
            yus.Word(text="glasses", confidence=0.714, start=DT.fromisoformat("2025-01-14T20:40:17"), duration=TD(seconds=0.6)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:40:17.6"), duration=TD(seconds=0.3)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:40:17.9"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:40:18.2"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:40:18.5"), duration=TD(seconds=0.3)),
            yus.Word(text="white", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:40:18.8"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick swing to stephen butler"
    transcript.add_group().add_interpretation(confidence=0.727).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:40:22.4"), duration=TD(seconds=0.3)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:40:22.7"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:40:23"), duration=TD(seconds=0.3)),
            yus.Word(text="stephen", confidence=0.674, start=DT.fromisoformat("2025-01-14T20:40:23.3"), duration=TD(seconds=0.6)),
            yus.Word(text="butler", confidence=0.744, start=DT.fromisoformat("2025-01-14T20:40:23.9"), duration=TD(seconds=0.6)),
        ]
    )

    # "flick to the kid"
    transcript.add_group().add_interpretation(confidence=0.762).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:40:25.4"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:40:25.7"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:40:26"), duration=TD(seconds=0.3)),
            yus.Word(text="kid", confidence=0.838, start=DT.fromisoformat("2025-01-14T20:40:26.3"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick to close crop"
    transcript.add_group().add_interpretation(confidence=0.723).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:40:29.6"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:40:29.9"), duration=TD(seconds=0.3)),
            yus.Word(text="close", confidence=0.608, start=DT.fromisoformat("2025-01-14T20:40:30.2"), duration=TD(seconds=0.3)),
            yus.Word(text="crop", confidence=0.833, start=DT.fromisoformat("2025-01-14T20:40:30.5"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick swing to the kid"
    transcript.add_group().add_interpretation(confidence=0.763).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:40:34.5"), duration=TD(seconds=0.3)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:40:34.8"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:40:35.1"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:40:35.4"), duration=TD(seconds=0.3)),
            yus.Word(text="kid", confidence=0.838, start=DT.fromisoformat("2025-01-14T20:40:35.7"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to blondie"
    transcript.add_group().add_interpretation(confidence=0.722).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:40:37.4"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:40:38"), duration=TD(seconds=0.3)),
            yus.Word(text="blondie", confidence=0.783, start=DT.fromisoformat("2025-01-14T20:40:38.3"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to kaia"
    transcript.add_group().add_interpretation(confidence=0.658).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:40:38.5"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:40:39.1"), duration=TD(seconds=0.3)),
            yus.Word(text="kaia", confidence=0.592, start=DT.fromisoformat("2025-01-14T20:40:39.4"), duration=TD(seconds=0.75)),
        ]
    )

    # "flick swing to stephen butler"
    transcript.add_group().add_interpretation(confidence=0.727).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:40:42.9"), duration=TD(seconds=0.3)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:40:43.2"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:40:43.5"), duration=TD(seconds=0.3)),
            yus.Word(text="stephen", confidence=0.674, start=DT.fromisoformat("2025-01-14T20:40:43.8"), duration=TD(seconds=0.6)),
            yus.Word(text="butler", confidence=0.744, start=DT.fromisoformat("2025-01-14T20:40:44.4"), duration=TD(seconds=0.6)),
        ]
    )

    # "flick into the end zone to the kid for a score"
    transcript.add_group().add_interpretation(confidence=0.747).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:40:46.3"), duration=TD(seconds=0.3)),
            yus.Word(text="into", confidence=0.823, start=DT.fromisoformat("2025-01-14T20:40:46.6"), duration=TD(seconds=0.6)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:40:47.2"), duration=TD(seconds=0.3)),
            yus.Word(text="end", confidence=0.588, start=DT.fromisoformat("2025-01-14T20:40:47.5"), duration=TD(seconds=0.3)),
            yus.Word(text="zone", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:40:47.8"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:40:48.1"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:40:48.4"), duration=TD(seconds=0.3)),
            yus.Word(text="kid", confidence=0.838, start=DT.fromisoformat("2025-01-14T20:40:48.7"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:40:49"), duration=TD(seconds=0.3)),
            yus.Word(text="a", confidence=0.639, start=DT.fromisoformat("2025-01-14T20:40:49.3"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:40:49.6"), duration=TD(seconds=0.3)),
        ]
    )

    # "turtle picks it up for dark checks it in"
    transcript.add_group().add_interpretation(confidence=0.846).words.extend(
        [
            yus.Word(text="turtle", confidence=0.872, start=DT.fromisoformat("2025-01-14T20:40:52.9"), duration=TD(seconds=0.6)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:40:53.5"), duration=TD(seconds=0.3)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:40:53.8"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:40:54.1"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:40:54.4"), duration=TD(seconds=0.3)),
            yus.Word(text="dark", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:40:54.7"), duration=TD(seconds=0.3)),
            yus.Word(text="checks", confidence=0.843, start=DT.fromisoformat("2025-01-14T20:40:55"), duration=TD(seconds=0.3)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:40:55.3"), duration=TD(seconds=0.3)),
            yus.Word(text="in", confidence=0.692, start=DT.fromisoformat("2025-01-14T20:40:55.6"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to bush"
    transcript.add_group().add_interpretation(confidence=0.739).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:40:56.7"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:40:57.3"), duration=TD(seconds=0.3)),
            yus.Word(text="bush", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:40:57.6"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick to leg stripe"
    transcript.add_group().add_interpretation(confidence=0.732).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:40:59.5"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:40:59.8"), duration=TD(seconds=0.3)),
            yus.Word(text="leg", confidence=0.764, start=DT.fromisoformat("2025-01-14T20:41:00.1"), duration=TD(seconds=0.3)),
            yus.Word(text="stripe", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:41:00.4"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to i don't know"
    transcript.add_group().add_interpretation(confidence=0.766).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:41:02.4"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:41:03"), duration=TD(seconds=0.3)),
            yus.Word(text="i", confidence=0.749, start=DT.fromisoformat("2025-01-14T20:41:03.3"), duration=TD(seconds=0.3)),
            yus.Word(text="don't", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:41:03.6"), duration=TD(seconds=0.3)),
            yus.Word(text="know", confidence=0.905, start=DT.fromisoformat("2025-01-14T20:41:03.9"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand deed by the kid no score"
    transcript.add_group().add_interpretation(confidence=0.805).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:41:05.2"), duration=TD(seconds=0.6)),
            yus.Word(text="deed", confidence=0.841, start=DT.fromisoformat("2025-01-14T20:41:05.8"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:41:06.1"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:41:06.4"), duration=TD(seconds=0.3)),
            yus.Word(text="kid", confidence=0.838, start=DT.fromisoformat("2025-01-14T20:41:06.7"), duration=TD(seconds=0.3)),
            yus.Word(text="no", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:41:07"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:41:07.3"), duration=TD(seconds=0.3)),
        ]
    )

    # "kid picks it up for white"
    transcript.add_group().add_interpretation(confidence=0.864).words.extend(
        [
            yus.Word(text="kid", confidence=0.838, start=DT.fromisoformat("2025-01-14T20:41:12.9"), duration=TD(seconds=0.3)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:41:13.2"), duration=TD(seconds=0.3)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:41:13.5"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:41:13.8"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:41:14.1"), duration=TD(seconds=0.3)),
            yus.Word(text="white", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:41:14.4"), duration=TD(seconds=0.3)),
        ]
    )

    # "checks it in"
    transcript.add_group().add_interpretation(confidence=0.807).words.extend(
        [
            yus.Word(text="checks", confidence=0.843, start=DT.fromisoformat("2025-01-14T20:41:15"), duration=TD(seconds=0.3)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:41:15.3"), duration=TD(seconds=0.3)),
            yus.Word(text="in", confidence=0.692, start=DT.fromisoformat("2025-01-14T20:41:15.6"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick to emily"
    transcript.add_group().add_interpretation(confidence=0.760).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:41:15.9"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:41:16.2"), duration=TD(seconds=0.3)),
            yus.Word(text="emily", confidence=0.830, start=DT.fromisoformat("2025-01-14T20:41:16.5"), duration=TD(seconds=0.9)),
        ]
    )

    # "flick to blondie"
    transcript.add_group().add_interpretation(confidence=0.744).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:41:19.4"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:41:19.7"), duration=TD(seconds=0.3)),
            yus.Word(text="blondie", confidence=0.783, start=DT.fromisoformat("2025-01-14T20:41:20.0"), duration=TD(seconds=0.6)),
        ]
    )

    # "blade in the end zone nope not in the end zone caught by somebody"
    transcript.add_group().add_interpretation(confidence=0.732).words.extend(
        [
            yus.Word(text="blade", confidence=0.708, start=DT.fromisoformat("2025-01-14T20:41:23.2"), duration=TD(seconds=0.3)),
            yus.Word(text="in", confidence=0.692, start=DT.fromisoformat("2025-01-14T20:41:23.5"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:41:23.8"), duration=TD(seconds=0.3)),
            yus.Word(text="end", confidence=0.588, start=DT.fromisoformat("2025-01-14T20:41:24.1"), duration=TD(seconds=0.3)),
            yus.Word(text="zone", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:41:24.4"), duration=TD(seconds=0.3)),
            yus.Word(text="nope", confidence=0.650, start=DT.fromisoformat("2025-01-14T20:41:26"), duration=TD(seconds=0.3)),
            yus.Word(text="not", confidence=0.881, start=DT.fromisoformat("2025-01-14T20:41:26.3"), duration=TD(seconds=0.3)),
            yus.Word(text="in", confidence=0.692, start=DT.fromisoformat("2025-01-14T20:41:26.6"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:41:26.9"), duration=TD(seconds=0.3)),
            yus.Word(text="end", confidence=0.588, start=DT.fromisoformat("2025-01-14T20:41:27.2"), duration=TD(seconds=0.3)),
            yus.Word(text="zone", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:41:27.5"), duration=TD(seconds=0.3)),
            yus.Word(text="caught", confidence=0.814, start=DT.fromisoformat("2025-01-14T20:41:27.8"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:41:28.1"), duration=TD(seconds=0.3)),
            yus.Word(text="somebody", confidence=0.796, start=DT.fromisoformat("2025-01-14T20:41:28.4"), duration=TD(seconds=0.9)),
        ]
    )

    # "dump to blondie"
    transcript.add_group().add_interpretation(confidence=0.764).words.extend(
        [
            yus.Word(text="dump", confidence=0.772, start=DT.fromisoformat("2025-01-14T20:41:29"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:41:29.3"), duration=TD(seconds=0.3)),
            yus.Word(text="blondie", confidence=0.783, start=DT.fromisoformat("2025-01-14T20:41:29.6"), duration=TD(seconds=0.6)),
        ]
    )

    # "power dump to tristan"
    transcript.add_group().add_interpretation(confidence=0.708).words.extend(
        [
            yus.Word(text="power", confidence=0.650, start=DT.fromisoformat("2025-01-14T20:41:34.9"), duration=TD(seconds=0.6)),
            yus.Word(text="dump", confidence=0.772, start=DT.fromisoformat("2025-01-14T20:41:35.5"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:41:35.8"), duration=TD(seconds=0.3)),
            yus.Word(text="tristan", confidence=0.672, start=DT.fromisoformat("2025-01-14T20:41:36.1"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to blondie"
    transcript.add_group().add_interpretation(confidence=0.722).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:41:38.2"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:41:38.8"), duration=TD(seconds=0.3)),
            yus.Word(text="blondie", confidence=0.783, start=DT.fromisoformat("2025-01-14T20:41:39.1"), duration=TD(seconds=0.6)),
        ]
    )

    # "flick to the kid for a score"
    transcript.add_group().add_interpretation(confidence=0.761).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:41:40.8"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:41:41.1"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:41:41.4"), duration=TD(seconds=0.3)),
            yus.Word(text="kid", confidence=0.838, start=DT.fromisoformat("2025-01-14T20:41:41.7"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:41:42"), duration=TD(seconds=0.3)),
            yus.Word(text="a", confidence=0.639, start=DT.fromisoformat("2025-01-14T20:41:42.3"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:41:42.6"), duration=TD(seconds=0.3)),
        ]
    )

    # "bush picks it up"
    transcript.add_group().add_interpretation(confidence=0.859).words.extend(
        [
            yus.Word(text="bush", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:41:44"), duration=TD(seconds=0.3)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:41:44.3"), duration=TD(seconds=0.3)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:41:44.6"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:41:44.9"), duration=TD(seconds=0.3)),
        ]
    )

    # "blade to bush"
    transcript.add_group().add_interpretation(confidence=0.760).words.extend(
        [
            yus.Word(text="blade", confidence=0.708, start=DT.fromisoformat("2025-01-14T20:41:49.8"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:41:50.1"), duration=TD(seconds=0.3)),
            yus.Word(text="bush", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:41:50.4"), duration=TD(seconds=0.3)),
        ]
    )

    # "bush scoober to bluey in the end zone for a score"
    transcript.add_group().add_interpretation(confidence=0.757).words.extend(
        [
            yus.Word(text="bush", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:41:52.2"), duration=TD(seconds=0.3)),
            yus.Word(text="scoober", confidence=0.850, start=DT.fromisoformat("2025-01-14T20:41:52.5"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:41:53.1"), duration=TD(seconds=0.3)),
            yus.Word(text="bluey", confidence=0.873, start=DT.fromisoformat("2025-01-14T20:41:53.4"), duration=TD(seconds=0.6)),
            yus.Word(text="in", confidence=0.692, start=DT.fromisoformat("2025-01-14T20:41:54"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:41:54.3"), duration=TD(seconds=0.3)),
            yus.Word(text="end", confidence=0.588, start=DT.fromisoformat("2025-01-14T20:41:54.6"), duration=TD(seconds=0.3)),
            yus.Word(text="zone", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:41:54.9"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:41:55.2"), duration=TD(seconds=0.3)),
            yus.Word(text="a", confidence=0.639, start=DT.fromisoformat("2025-01-14T20:41:55.5"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:41:55.8"), duration=TD(seconds=0.3)),
        ]
    )

    # "tristan picks it up for white"
    transcript.add_group().add_interpretation(confidence=0.836).words.extend(
        [
            yus.Word(text="tristan", confidence=0.672, start=DT.fromisoformat("2025-01-14T20:42:01.3"), duration=TD(seconds=0.6)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:42:01.9"), duration=TD(seconds=0.3)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:42:02.2"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:42:02.5"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:42:02.8"), duration=TD(seconds=0.3)),
            yus.Word(text="white", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:42:03.1"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to blondie"
    transcript.add_group().add_interpretation(confidence=0.722).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:42:03.1"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:42:03.7"), duration=TD(seconds=0.3)),
            yus.Word(text="blondie", confidence=0.783, start=DT.fromisoformat("2025-01-14T20:42:04"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to joe"
    transcript.add_group().add_interpretation(confidence=0.739).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:42:06.8"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:42:07.4"), duration=TD(seconds=0.3)),
            yus.Word(text="joe", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:42:07.7"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to tristan"
    transcript.add_group().add_interpretation(confidence=0.685).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:42:08.5"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:42:09.1"), duration=TD(seconds=0.3)),
            yus.Word(text="tristan", confidence=0.672, start=DT.fromisoformat("2025-01-14T20:42:09.4"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to glasses"
    transcript.add_group().add_interpretation(confidence=0.699).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:42:10.4"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:42:11"), duration=TD(seconds=0.3)),
            yus.Word(text="glasses", confidence=0.714, start=DT.fromisoformat("2025-01-14T20:42:11.3"), duration=TD(seconds=0.6)),
        ]
    )

    # "flick swing to pikachu"
    transcript.add_group().add_interpretation(confidence=0.786).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:42:16.8"), duration=TD(seconds=0.3)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:42:17.1"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:42:17.4"), duration=TD(seconds=0.3)),
            yus.Word(text="pikachu", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:42:17.7"), duration=TD(seconds=0.9)),
        ]
    )

    # "flick swing to tristan"
    transcript.add_group().add_interpretation(confidence=0.723).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:42:18.5"), duration=TD(seconds=0.3)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:42:18.8"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:42:19.1"), duration=TD(seconds=0.3)),
            yus.Word(text="tristan", confidence=0.672, start=DT.fromisoformat("2025-01-14T20:42:19.4"), duration=TD(seconds=0.6)),
        ]
    )

    # "hammer to the end zone blondie for a score"
    transcript.add_group().add_interpretation(confidence=0.721).words.extend(
        [
            yus.Word(text="hammer", confidence=0.627, start=DT.fromisoformat("2025-01-14T20:42:20.8"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:42:21.4"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:42:21.7"), duration=TD(seconds=0.3)),
            yus.Word(text="end", confidence=0.588, start=DT.fromisoformat("2025-01-14T20:42:22"), duration=TD(seconds=0.3)),
            yus.Word(text="zone", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:42:22.3"), duration=TD(seconds=0.3)),
            yus.Word(text="blondie", confidence=0.783, start=DT.fromisoformat("2025-01-14T20:42:22.6"), duration=TD(seconds=0.6)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:42:23.2"), duration=TD(seconds=0.3)),
            yus.Word(text="a", confidence=0.639, start=DT.fromisoformat("2025-01-14T20:42:23.5"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:42:23.8"), duration=TD(seconds=0.3)),
        ]
    )

    # "bush picks up for dark"
    transcript.add_group().add_interpretation(confidence=0.855).words.extend(
        [
            yus.Word(text="bush", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:42:26.8"), duration=TD(seconds=0.3)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:42:27.1"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:42:27.4"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:42:27.7"), duration=TD(seconds=0.3)),
            yus.Word(text="dark", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:42:28"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand swing to george"
    transcript.add_group().add_interpretation(confidence=0.758).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:42:31.8"), duration=TD(seconds=0.6)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:42:32.4"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:42:32.7"), duration=TD(seconds=0.3)),
            yus.Word(text="george", confidence=0.881, start=DT.fromisoformat("2025-01-14T20:42:33"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to naked"
    transcript.add_group().add_interpretation(confidence=0.771).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:42:34.2"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:42:34.8"), duration=TD(seconds=0.3)),
            yus.Word(text="naked", confidence=0.931, start=DT.fromisoformat("2025-01-14T20:42:35.1"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to yellow fringe"
    transcript.add_group().add_interpretation(confidence=0.755).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:42:39.2"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:42:39.8"), duration=TD(seconds=0.3)),
            yus.Word(text="yellow", confidence=0.789, start=DT.fromisoformat("2025-01-14T20:42:40.1"), duration=TD(seconds=0.6)),
            yus.Word(text="fringe", confidence=0.848, start=DT.fromisoformat("2025-01-14T20:42:40.7"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick turf"
    transcript.add_group().add_interpretation(confidence=0.779).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:42:42"), duration=TD(seconds=0.3)),
            yus.Word(text="turf", confidence=0.846, start=DT.fromisoformat("2025-01-14T20:42:42.3"), duration=TD(seconds=0.3)),
        ]
    )

    # "joe picks up for white"
    transcript.add_group().add_interpretation(confidence=0.859).words.extend(
        [
            yus.Word(text="joe", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:42:48.8"), duration=TD(seconds=0.3)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:42:49.1"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:42:49.4"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:42:49.7"), duration=TD(seconds=0.3)),
            yus.Word(text="white", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:42:50.0"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick tristan"
    transcript.add_group().add_interpretation(confidence=0.692).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:42:51.1"), duration=TD(seconds=0.3)),
            yus.Word(text="tristan", confidence=0.672, start=DT.fromisoformat("2025-01-14T20:42:51.4"), duration=TD(seconds=0.6)),
        ]
    )

    # "flick to glasses"
    transcript.add_group().add_interpretation(confidence=0.721).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:42:54"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:42:54.3"), duration=TD(seconds=0.3)),
            yus.Word(text="glasses", confidence=0.714, start=DT.fromisoformat("2025-01-14T20:42:54.6"), duration=TD(seconds=0.6)),
        ]
    )

    # "flick put to close crop for a score"
    transcript.add_group().add_interpretation(confidence=0.728).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:42:59.6"), duration=TD(seconds=0.3)),
            yus.Word(text="put", confidence=0.653, start=DT.fromisoformat("2025-01-14T20:42:59.9"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:43:00.2"), duration=TD(seconds=0.3)),
            yus.Word(text="close", confidence=0.608, start=DT.fromisoformat("2025-01-14T20:43:00.5"), duration=TD(seconds=0.3)),
            yus.Word(text="crop", confidence=0.833, start=DT.fromisoformat("2025-01-14T20:43:00.8"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:43:01.1"), duration=TD(seconds=0.3)),
            yus.Word(text="a", confidence=0.639, start=DT.fromisoformat("2025-01-14T20:43:01.4"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:43:01.7"), duration=TD(seconds=0.3)),
        ]
    )

    # "george picks up for dark"
    transcript.add_group().add_interpretation(confidence=0.864).words.extend(
        [
            yus.Word(text="george", confidence=0.881, start=DT.fromisoformat("2025-01-14T20:43:08.4"), duration=TD(seconds=0.3)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:43:08.7"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:43:09"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:43:09.3"), duration=TD(seconds=0.3)),
            yus.Word(text="dark", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:43:09.6"), duration=TD(seconds=0.3)),
        ]
    )

    # "scoober swing to naked"
    transcript.add_group().add_interpretation(confidence=0.822).words.extend(
        [
            yus.Word(text="scoober", confidence=0.850, start=DT.fromisoformat("2025-01-14T20:43:09.7"), duration=TD(seconds=0.6)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:43:10.3"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:43:10.6"), duration=TD(seconds=0.3)),
            yus.Word(text="naked", confidence=0.931, start=DT.fromisoformat("2025-01-14T20:43:10.9"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to yellow fringe"
    transcript.add_group().add_interpretation(confidence=0.755).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:43:11.8"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:43:12.4"), duration=TD(seconds=0.3)),
            yus.Word(text="yellow", confidence=0.789, start=DT.fromisoformat("2025-01-14T20:43:12.7"), duration=TD(seconds=0.6)),
            yus.Word(text="fringe", confidence=0.848, start=DT.fromisoformat("2025-01-14T20:43:13.3"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to turtle"
    transcript.add_group().add_interpretation(confidence=0.752).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:43:14.8"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:43:15.4"), duration=TD(seconds=0.3)),
            yus.Word(text="turtle", confidence=0.872, start=DT.fromisoformat("2025-01-14T20:43:15.7"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand bobbled and dropped by hat no score"
    transcript.add_group().add_interpretation(confidence=0.790).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:43:16.4"), duration=TD(seconds=0.6)),
            yus.Word(text="bobbled", confidence=0.840, start=DT.fromisoformat("2025-01-14T20:43:17"), duration=TD(seconds=0.6)),
            yus.Word(text="and", confidence=0.435, start=DT.fromisoformat("2025-01-14T20:43:17.6"), duration=TD(seconds=0.3)),
            yus.Word(text="dropped", confidence=0.963, start=DT.fromisoformat("2025-01-14T20:43:17.9"), duration=TD(seconds=0.54)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:43:18.44"), duration=TD(seconds=0.3)),
            yus.Word(text="hat", confidence=0.880, start=DT.fromisoformat("2025-01-14T20:43:18.74"), duration=TD(seconds=0.3)),
            yus.Word(text="no", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:43:19.04"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:43:19.34"), duration=TD(seconds=0.3)),
        ]
    )

    # "glasses picks up for white"
    transcript.add_group().add_interpretation(confidence=0.835).words.extend(
        [
            yus.Word(text="glasses", confidence=0.714, start=DT.fromisoformat("2025-01-14T20:43:21"), duration=TD(seconds=0.6)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:43:21.6"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:43:21.9"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:43:22.2"), duration=TD(seconds=0.3)),
            yus.Word(text="white", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:43:22.5"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick to tristan"
    transcript.add_group().add_interpretation(confidence=0.707).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:43:25"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:43:25.3"), duration=TD(seconds=0.3)),
            yus.Word(text="tristan", confidence=0.672, start=DT.fromisoformat("2025-01-14T20:43:25.6"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to kaia"
    transcript.add_group().add_interpretation(confidence=0.658).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:43:27"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:43:27.6"), duration=TD(seconds=0.3)),
            yus.Word(text="kaia", confidence=0.592, start=DT.fromisoformat("2025-01-14T20:43:27.9"), duration=TD(seconds=0.75)),
        ]
    )

    # "flick dump to glasses"
    transcript.add_group().add_interpretation(confidence=0.734).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:43:32.2"), duration=TD(seconds=0.3)),
            yus.Word(text="dump", confidence=0.772, start=DT.fromisoformat("2025-01-14T20:43:32.5"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:43:32.8"), duration=TD(seconds=0.3)),
            yus.Word(text="glasses", confidence=0.714, start=DT.fromisoformat("2025-01-14T20:43:33.1"), duration=TD(seconds=0.6)),
        ]
    )

    # "flick to stephen"
    transcript.add_group().add_interpretation(confidence=0.708).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:43:35.3"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:43:35.6"), duration=TD(seconds=0.3)),
            yus.Word(text="stephen", confidence=0.674, start=DT.fromisoformat("2025-01-14T20:43:35.9"), duration=TD(seconds=0.6)),
        ]
    )

    # "flick put huck close crop in the end zone for a score"
    transcript.add_group().add_interpretation(confidence=0.714).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:43:37.8"), duration=TD(seconds=0.3)),
            yus.Word(text="put", confidence=0.653, start=DT.fromisoformat("2025-01-14T20:43:38.1"), duration=TD(seconds=0.3)),
            yus.Word(text="huck", confidence=0.729, start=DT.fromisoformat("2025-01-14T20:43:38.4"), duration=TD(seconds=0.3)),
            yus.Word(text="close", confidence=0.608, start=DT.fromisoformat("2025-01-14T20:43:40.0"), duration=TD(seconds=0.3)),
            yus.Word(text="crop", confidence=0.833, start=DT.fromisoformat("2025-01-14T20:43:40.3"), duration=TD(seconds=0.3)),
            yus.Word(text="in", confidence=0.692, start=DT.fromisoformat("2025-01-14T20:43:40.6"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:43:40.9"), duration=TD(seconds=0.3)),
            yus.Word(text="end", confidence=0.588, start=DT.fromisoformat("2025-01-14T20:43:41.2"), duration=TD(seconds=0.3)),
            yus.Word(text="zone", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:43:41.5"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:43:41.8"), duration=TD(seconds=0.3)),
            yus.Word(text="a", confidence=0.639, start=DT.fromisoformat("2025-01-14T20:43:42.1"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:43:42.4"), duration=TD(seconds=0.3)),
        ]
    )

    # "naked picks up for dark"
    transcript.add_group().add_interpretation(confidence=0.874).words.extend(
        [
            yus.Word(text="naked", confidence=0.931, start=DT.fromisoformat("2025-01-14T20:43:43.8"), duration=TD(seconds=0.6)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:43:44.4"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:43:44.7"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:43:45"), duration=TD(seconds=0.3)),
            yus.Word(text="dark", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:43:45.3"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to somebody"
    transcript.add_group().add_interpretation(confidence=0.726).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:43:50.5"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:43:51.1"), duration=TD(seconds=0.3)),
            yus.Word(text="somebody", confidence=0.796, start=DT.fromisoformat("2025-01-14T20:43:51.4"), duration=TD(seconds=0.9)),
        ]
    )

    # "backhand dump to naked"
    transcript.add_group().add_interpretation(confidence=0.771).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:43:54.7"), duration=TD(seconds=0.6)),
            yus.Word(text="dump", confidence=0.772, start=DT.fromisoformat("2025-01-14T20:43:55.3"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:43:55.6"), duration=TD(seconds=0.3)),
            yus.Word(text="naked", confidence=0.931, start=DT.fromisoformat("2025-01-14T20:43:55.9"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to leg stripe"
    transcript.add_group().add_interpretation(confidence=0.716).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:43:56.8"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:43:57.4"), duration=TD(seconds=0.3)),
            yus.Word(text="leg", confidence=0.764, start=DT.fromisoformat("2025-01-14T20:43:57.7"), duration=TD(seconds=0.3)),
            yus.Word(text="stripe", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:43:58"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to turf no score off the wall"
    transcript.add_group().add_interpretation(confidence=0.811).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:43:58"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:44:00.8"), duration=TD(seconds=0.3)),
            yus.Word(text="turf", confidence=0.846, start=DT.fromisoformat("2025-01-14T20:44:02.1"), duration=TD(seconds=0.3)),
            yus.Word(text="no", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:44:02.4"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:44:02.7"), duration=TD(seconds=0.3)),
            yus.Word(text="off", confidence=0.867, start=DT.fromisoformat("2025-01-14T20:44:03"), duration=TD(seconds=0.3)),
            yus.Word(text="the", confidence=0.759, start=DT.fromisoformat("2025-01-14T20:44:03.3"), duration=TD(seconds=0.3)),
            yus.Word(text="wall", confidence=0.964, start=DT.fromisoformat("2025-01-14T20:44:03.6"), duration=TD(seconds=0.3)),
        ]
    )

    # "glasses picks it up for white"
    transcript.add_group().add_interpretation(confidence=0.843).words.extend(
        [
            yus.Word(text="glasses", confidence=0.714, start=DT.fromisoformat("2025-01-14T20:44:05"), duration=TD(seconds=0.6)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:44:05.6"), duration=TD(seconds=0.3)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:44:05.9"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:44:06.2"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:44:06.5"), duration=TD(seconds=0.3)),
            yus.Word(text="white", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:44:06.8"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick to emily"
    transcript.add_group().add_interpretation(confidence=0.760).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:44:13"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:44:13.3"), duration=TD(seconds=0.3)),
            yus.Word(text="emily", confidence=0.830, start=DT.fromisoformat("2025-01-14T20:44:13.6"), duration=TD(seconds=0.9)),
        ]
    )

    # "blade to i dunno"
    transcript.add_group().add_interpretation(confidence=0.736).words.extend(
        [
            yus.Word(text="blade", confidence=0.708, start=DT.fromisoformat("2025-01-14T20:44:17.5"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:44:17.8"), duration=TD(seconds=0.3)),
            yus.Word(text="i", confidence=0.749, start=DT.fromisoformat("2025-01-14T20:44:18.1"), duration=TD(seconds=0.3)),
            yus.Word(text="dunno", confidence=0.750, start=DT.fromisoformat("2025-01-14T20:44:18.4"), duration=TD(seconds=0.6)),
        ]
    )

    # "flick to kaia dropped it"
    transcript.add_group().add_interpretation(confidence=0.778).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:44:21.4"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:44:21.7"), duration=TD(seconds=0.3)),
            yus.Word(text="kaia", confidence=0.592, start=DT.fromisoformat("2025-01-14T20:44:22"), duration=TD(seconds=0.75)),
            yus.Word(text="dropped", confidence=0.963, start=DT.fromisoformat("2025-01-14T20:44:22.5"), duration=TD(seconds=0.54)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:44:23.04"), duration=TD(seconds=0.3)),
        ]
    )

    # "picked up by somebody for dark"
    transcript.add_group().add_interpretation(confidence=0.872).words.extend(
        [
            yus.Word(text="picked", confidence=0.906, start=DT.fromisoformat("2025-01-14T20:44:27.8"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:44:28.1"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:44:28.4"), duration=TD(seconds=0.3)),
            yus.Word(text="somebody", confidence=0.796, start=DT.fromisoformat("2025-01-14T20:44:28.7"), duration=TD(seconds=0.9)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:44:29.6"), duration=TD(seconds=0.3)),
            yus.Word(text="dark", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:44:29.9"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to leg stripes"
    transcript.add_group().add_interpretation(confidence=0.758).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:44:34.4"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:44:35"), duration=TD(seconds=0.3)),
            yus.Word(text="leg", confidence=0.764, start=DT.fromisoformat("2025-01-14T20:44:35.3"), duration=TD(seconds=0.3)),
            yus.Word(text="stripes", confidence=0.884, start=DT.fromisoformat("2025-01-14T20:44:35.6"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to i don't know"
    transcript.add_group().add_interpretation(confidence=0.766).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:44:36"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:44:36.6"), duration=TD(seconds=0.3)),
            yus.Word(text="i", confidence=0.749, start=DT.fromisoformat("2025-01-14T20:44:36.9"), duration=TD(seconds=0.3)),
            yus.Word(text="don't", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:44:37.2"), duration=TD(seconds=0.3)),
            yus.Word(text="know", confidence=0.905, start=DT.fromisoformat("2025-01-14T20:44:37.5"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to leg stripes"
    transcript.add_group().add_interpretation(confidence=0.758).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:44:39.5"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:44:40.1"), duration=TD(seconds=0.3)),
            yus.Word(text="leg", confidence=0.764, start=DT.fromisoformat("2025-01-14T20:44:40.4"), duration=TD(seconds=0.3)),
            yus.Word(text="stripes", confidence=0.884, start=DT.fromisoformat("2025-01-14T20:44:40.7"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand dump to gloves"
    transcript.add_group().add_interpretation(confidence=0.755).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:44:43"), duration=TD(seconds=0.6)),
            yus.Word(text="dump", confidence=0.772, start=DT.fromisoformat("2025-01-14T20:44:43.6"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:44:43.9"), duration=TD(seconds=0.3)),
            yus.Word(text="gloves", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:44:44.2"), duration=TD(seconds=0.3)),
        ]
    )

    # "gloves hammer to turtle dropped it no score"
    transcript.add_group().add_interpretation(confidence=0.828).words.extend(
        [
            yus.Word(text="gloves", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:44:44.9"), duration=TD(seconds=0.3)),
            yus.Word(text="hammer", confidence=0.627, start=DT.fromisoformat("2025-01-14T20:44:45.2"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:44:45.8"), duration=TD(seconds=0.3)),
            yus.Word(text="turtle", confidence=0.872, start=DT.fromisoformat("2025-01-14T20:44:46.1"), duration=TD(seconds=0.6)),
            yus.Word(text="dropped", confidence=0.963, start=DT.fromisoformat("2025-01-14T20:44:46.7"), duration=TD(seconds=0.54)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:44:47.24"), duration=TD(seconds=0.3)),
            yus.Word(text="no", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:44:47.54"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:44:47.84"), duration=TD(seconds=0.3)),
        ]
    )

    # "stephen picks it up for white"
    transcript.add_group().add_interpretation(confidence=0.837).words.extend(
        [
            yus.Word(text="stephen", confidence=0.674, start=DT.fromisoformat("2025-01-14T20:45:03"), duration=TD(seconds=0.6)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:45:03.6"), duration=TD(seconds=0.3)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:45:03.9"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:45:04.2"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:45:04.5"), duration=TD(seconds=0.3)),
            yus.Word(text="white", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:45:04.8"), duration=TD(seconds=0.3)),
        ]
    )

    # "checks it in"
    transcript.add_group().add_interpretation(confidence=0.807).words.extend(
        [
            yus.Word(text="checks", confidence=0.843, start=DT.fromisoformat("2025-01-14T20:45:06.7"), duration=TD(seconds=0.3)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:45:07"), duration=TD(seconds=0.3)),
            yus.Word(text="in", confidence=0.692, start=DT.fromisoformat("2025-01-14T20:45:07.3"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick to joe"
    transcript.add_group().add_interpretation(confidence=0.761).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:45:10.3"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:45:10.6"), duration=TD(seconds=0.3)),
            yus.Word(text="joe", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:45:10.9"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick to blondie"
    transcript.add_group().add_interpretation(confidence=0.744).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:45:13.1"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:45:13.4"), duration=TD(seconds=0.3)),
            yus.Word(text="blondie", confidence=0.783, start=DT.fromisoformat("2025-01-14T20:45:13.7"), duration=TD(seconds=0.6)),
        ]
    )

    # "backhand to stephen"
    transcript.add_group().add_interpretation(confidence=0.686).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:45:16.4"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:45:17"), duration=TD(seconds=0.3)),
            yus.Word(text="stephen", confidence=0.674, start=DT.fromisoformat("2025-01-14T20:45:17.3"), duration=TD(seconds=0.6)),
        ]
    )

    # "flick huck deed by gloves no score"
    transcript.add_group().add_interpretation(confidence=0.814).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:45:18.5"), duration=TD(seconds=0.3)),
            yus.Word(text="huck", confidence=0.729, start=DT.fromisoformat("2025-01-14T20:45:18.8"), duration=TD(seconds=0.3)),
            yus.Word(text="deed", confidence=0.841, start=DT.fromisoformat("2025-01-14T20:45:19.1"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:45:19.4"), duration=TD(seconds=0.3)),
            yus.Word(text="gloves", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:45:19.7"), duration=TD(seconds=0.3)),
            yus.Word(text="no", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:45:20.0"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:45:20.3"), duration=TD(seconds=0.3)),
        ]
    )

    # "picked up by gloves for black"
    transcript.add_group().add_interpretation(confidence=0.873).words.extend(
        [
            yus.Word(text="picked", confidence=0.906, start=DT.fromisoformat("2025-01-14T20:45:23.1"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:45:23.4"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:45:23.7"), duration=TD(seconds=0.3)),
            yus.Word(text="gloves", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:45:24"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:45:24.3"), duration=TD(seconds=0.3)),
            yus.Word(text="black", confidence=0.800, start=DT.fromisoformat("2025-01-14T20:45:24.6"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand swing to leg stripe"
    transcript.add_group().add_interpretation(confidence=0.726).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:45:28.1"), duration=TD(seconds=0.6)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:45:28.7"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:45:29"), duration=TD(seconds=0.3)),
            yus.Word(text="leg", confidence=0.764, start=DT.fromisoformat("2025-01-14T20:45:29.3"), duration=TD(seconds=0.3)),
            yus.Word(text="stripe", confidence=0.716, start=DT.fromisoformat("2025-01-14T20:45:29.6"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to i don't know"
    transcript.add_group().add_interpretation(confidence=0.766).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:45:30.3"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:45:30.9"), duration=TD(seconds=0.3)),
            yus.Word(text="i", confidence=0.749, start=DT.fromisoformat("2025-01-14T20:45:31.2"), duration=TD(seconds=0.3)),
            yus.Word(text="don't", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:45:31.5"), duration=TD(seconds=0.3)),
            yus.Word(text="know", confidence=0.905, start=DT.fromisoformat("2025-01-14T20:45:31.8"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to bush"
    transcript.add_group().add_interpretation(confidence=0.739).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:45:33"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:45:33.6"), duration=TD(seconds=0.3)),
            yus.Word(text="bush", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:45:33.9"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to yellow fringe for a score"
    transcript.add_group().add_interpretation(confidence=0.757).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:45:36.8"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:45:37.4"), duration=TD(seconds=0.3)),
            yus.Word(text="yellow", confidence=0.789, start=DT.fromisoformat("2025-01-14T20:45:37.7"), duration=TD(seconds=0.6)),
            yus.Word(text="fringe", confidence=0.848, start=DT.fromisoformat("2025-01-14T20:45:38.3"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:45:38.6"), duration=TD(seconds=0.3)),
            yus.Word(text="a", confidence=0.639, start=DT.fromisoformat("2025-01-14T20:45:38.9"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:45:39.2"), duration=TD(seconds=0.3)),
        ]
    )

    # "stephen butler picks it up for white"
    transcript.add_group().add_interpretation(confidence=0.823).words.extend(
        [
            yus.Word(text="stephen", confidence=0.674, start=DT.fromisoformat("2025-01-14T20:45:39.8"), duration=TD(seconds=0.6)),
            yus.Word(text="butler", confidence=0.744, start=DT.fromisoformat("2025-01-14T20:45:40.4"), duration=TD(seconds=0.6)),
            yus.Word(text="picks", confidence=0.792, start=DT.fromisoformat("2025-01-14T20:45:41"), duration=TD(seconds=0.3)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:45:41.3"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:45:41.6"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:45:41.9"), duration=TD(seconds=0.3)),
            yus.Word(text="white", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:45:42.2"), duration=TD(seconds=0.3)),
        ]
    )

    # "checks it in"
    transcript.add_group().add_interpretation(confidence=0.807).words.extend(
        [
            yus.Word(text="checks", confidence=0.843, start=DT.fromisoformat("2025-01-14T20:45:42.5"), duration=TD(seconds=0.3)),
            yus.Word(text="it", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:45:42.8"), duration=TD(seconds=0.3)),
            yus.Word(text="in", confidence=0.692, start=DT.fromisoformat("2025-01-14T20:45:43.1"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick to blondie"
    transcript.add_group().add_interpretation(confidence=0.744).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:45:44.7"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:45:45"), duration=TD(seconds=0.3)),
            yus.Word(text="blondie", confidence=0.783, start=DT.fromisoformat("2025-01-14T20:45:45.3"), duration=TD(seconds=0.6)),
        ]
    )

    # "flick to joe"
    transcript.add_group().add_interpretation(confidence=0.761).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:45:46.4"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:45:46.7"), duration=TD(seconds=0.3)),
            yus.Word(text="joe", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:45:47"), duration=TD(seconds=0.3)),
        ]
    )

    # "cross field hammer turf"
    transcript.add_group().add_interpretation(confidence=0.666).words.extend(
        [
            yus.Word(text="cross", confidence=0.550, start=DT.fromisoformat("2025-01-14T20:45:55.7"), duration=TD(seconds=0.3)),
            yus.Word(text="field", confidence=0.640, start=DT.fromisoformat("2025-01-14T20:45:56"), duration=TD(seconds=0.3)),
            yus.Word(text="hammer", confidence=0.627, start=DT.fromisoformat("2025-01-14T20:45:56.3"), duration=TD(seconds=0.6)),
            yus.Word(text="turf", confidence=0.846, start=DT.fromisoformat("2025-01-14T20:45:56.9"), duration=TD(seconds=0.3)),
        ]
    )

    # "picked up by gloves for dark"
    transcript.add_group().add_interpretation(confidence=0.884).words.extend(
        [
            yus.Word(text="picked", confidence=0.906, start=DT.fromisoformat("2025-01-14T20:45:57.3"), duration=TD(seconds=0.3)),
            yus.Word(text="up", confidence=0.925, start=DT.fromisoformat("2025-01-14T20:45:57.6"), duration=TD(seconds=0.3)),
            yus.Word(text="by", confidence=0.883, start=DT.fromisoformat("2025-01-14T20:45:57.9"), duration=TD(seconds=0.3)),
            yus.Word(text="gloves", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:45:58.2"), duration=TD(seconds=0.3)),
            yus.Word(text="for", confidence=0.857, start=DT.fromisoformat("2025-01-14T20:45:58.5"), duration=TD(seconds=0.3)),
            yus.Word(text="dark", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:45:58.8"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to yellow fringe"
    transcript.add_group().add_interpretation(confidence=0.755).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:45:58.8"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:45:59.4"), duration=TD(seconds=0.3)),
            yus.Word(text="yellow", confidence=0.789, start=DT.fromisoformat("2025-01-14T20:45:59.7"), duration=TD(seconds=0.6)),
            yus.Word(text="fringe", confidence=0.848, start=DT.fromisoformat("2025-01-14T20:46:00.3"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick to george"
    transcript.add_group().add_interpretation(confidence=0.777).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:46:02.7"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:46:03"), duration=TD(seconds=0.3)),
            yus.Word(text="george", confidence=0.881, start=DT.fromisoformat("2025-01-14T20:46:03.3"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand dump to gloves"
    transcript.add_group().add_interpretation(confidence=0.755).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:46:05.7"), duration=TD(seconds=0.6)),
            yus.Word(text="dump", confidence=0.772, start=DT.fromisoformat("2025-01-14T20:46:06.3"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:46:06.6"), duration=TD(seconds=0.3)),
            yus.Word(text="gloves", confidence=0.865, start=DT.fromisoformat("2025-01-14T20:46:06.9"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand swing to yellow fringe"
    transcript.add_group().add_interpretation(confidence=0.758).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:46:10.1"), duration=TD(seconds=0.6)),
            yus.Word(text="swing", confidence=0.769, start=DT.fromisoformat("2025-01-14T20:46:10.7"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:46:11"), duration=TD(seconds=0.3)),
            yus.Word(text="yellow", confidence=0.789, start=DT.fromisoformat("2025-01-14T20:46:11.3"), duration=TD(seconds=0.6)),
            yus.Word(text="fringe", confidence=0.848, start=DT.fromisoformat("2025-01-14T20:46:11.9"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to bush"
    transcript.add_group().add_interpretation(confidence=0.739).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:46:12.8"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:46:13.4"), duration=TD(seconds=0.3)),
            yus.Word(text="bush", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:46:13.7"), duration=TD(seconds=0.3)),
        ]
    )

    # "blade to george"
    transcript.add_group().add_interpretation(confidence=0.775).words.extend(
        [
            yus.Word(text="blade", confidence=0.708, start=DT.fromisoformat("2025-01-14T20:46:16.3"), duration=TD(seconds=0.3)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:46:16.6"), duration=TD(seconds=0.3)),
            yus.Word(text="george", confidence=0.881, start=DT.fromisoformat("2025-01-14T20:46:16.9"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to yellow fringe"
    transcript.add_group().add_interpretation(confidence=0.755).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:46:19.5"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:46:20.1"), duration=TD(seconds=0.3)),
            yus.Word(text="yellow", confidence=0.789, start=DT.fromisoformat("2025-01-14T20:46:20.4"), duration=TD(seconds=0.6)),
            yus.Word(text="fringe", confidence=0.848, start=DT.fromisoformat("2025-01-14T20:46:21"), duration=TD(seconds=0.3)),
        ]
    )

    # "backhand to bush"
    transcript.add_group().add_interpretation(confidence=0.739).words.extend(
        [
            yus.Word(text="backhand", confidence=0.646, start=DT.fromisoformat("2025-01-14T20:46:23.3"), duration=TD(seconds=0.6)),
            yus.Word(text="to", confidence=0.737, start=DT.fromisoformat("2025-01-14T20:46:23.9"), duration=TD(seconds=0.3)),
            yus.Word(text="bush", confidence=0.835, start=DT.fromisoformat("2025-01-14T20:46:24.2"), duration=TD(seconds=0.3)),
        ]
    )

    # "flick huck turf no score"
    transcript.add_group().add_interpretation(confidence=0.791).words.extend(
        [
            yus.Word(text="flick", confidence=0.712, start=DT.fromisoformat("2025-01-14T20:46:25.2"), duration=TD(seconds=0.3)),
            yus.Word(text="huck", confidence=0.729, start=DT.fromisoformat("2025-01-14T20:46:25.5"), duration=TD(seconds=0.3)),
            yus.Word(text="turf", confidence=0.846, start=DT.fromisoformat("2025-01-14T20:46:25.8"), duration=TD(seconds=0.3)),
            yus.Word(text="no", confidence=0.886, start=DT.fromisoformat("2025-01-14T20:46:26.1"), duration=TD(seconds=0.3)),
            yus.Word(text="score", confidence=0.784, start=DT.fromisoformat("2025-01-14T20:46:26.4"), duration=TD(seconds=0.3)),
        ]
    )
    # """

    return transcript


def build_raw_stream(transcript: yus.Transcript) -> yus.EventStream:
    FL = ultimate.ThrowType.FLICK
    BH = ultimate.ThrowType.BACKHAND
    HM = ultimate.ThrowType.HAMMER
    BL = ultimate.ThrowType.BLADE
    SC = ultimate.ThrowType.SCOOBER

    DP = ultimate.ThrowDirection.DUMP
    SW = ultimate.ThrowDirection.SWING
    CF = ultimate.ThrowDirection.CROSS_FIELD
    HK = ultimate.ThrowDirection.HUCK

    Y = True
    N = False
    ZZ = None

    TW = "white"
    TB = "black"

    transcription_start_time = DT(2025, 1, 14, 20, 30, 33)

    def stamp(offset: float) -> DT:
        return transcription_start_time + TD(seconds=offset)

    def throw(
        offset: float,
        team: str,
        player: str | None,
        throw: ultimate.ThrowType | None,
        dir: ultimate.ThrowDirection | None,
        receiver: str | None,
        cmp: bool,
        scr: bool,
        wall: bool,
        net: bool,
    ) -> indoor.Throw:
        return indoor.Throw(
            when=stamp(offset),
            team=team,
            player=player,
            type=throw,
            direction=dir,
            receiver=receiver,
            completed=cmp,
            scored=scr,
            hit_wall=wall,
            hit_net=net,
        )

    def defns(offset: float, team: str, player: str | None, intercepted: bool) -> ultimate.Defense:
        return ultimate.Defense(
            when=stamp(offset),
            team=team,
            player=player,
            intercepted=intercepted,
        )

    def infract(offset: float,
                called_by_plyr: str,
                called_by_team: str,
                called_on_plyr: str,
                called_on_team: str,
                contest: bool=False) -> ultimate.Infraction:

        return ultimate.Infraction(when=stamp(offset),
                                   team=called_by_team,
                                   player=called_by_plyr,
                                   called_on_team=called_on_team,
                                   called_on_plyr=called_on_plyr,
                                   contested=contest)


    stream = yus.EventStream(transcript=transcript, game=transcript.game)

    # fmt: off
    stream.events = [
        #      time  tm  player            thr dir receiver         cmp  scr  wal  net
        throw( 42.7, TW, "pikachu",        BH, ZZ, "glasses",        Y,   N,   N,   N), # picked up by pikachu; backhand to glasses
        throw( 45.1, TW, "glasses",        SC, ZZ, "tristan",        Y,   N,   N,   N), # scoober to tristan
        throw( 49.8, TW, "tristan",        BH, ZZ, "close crop",     Y,   N,   N,   N), # backhand to close crop
        throw( 55.1, TW, "close crop",     BH, DP, "emily",          Y,   N,   N,   N), # backhand dump to emily
        throw( 57.1, TW, "emily",          BH, SW, "glasses",        Y,   N,   N,   N), # backhand swing to glasses
        throw( 60.0, TW, "glasses",        FL, ZZ, "kaia",           N,   N,   N,   N), # flick to kaia deed by somebody

        defns(61.35, TB, ZZ, N),                                                        # deed by somebody on dark
        throw( 72.0, TB, "blue",           BH, SW, "red stripe",     Y,   N,   N,   N), # picked up by blue on dark; backhand swing to red stripe
        throw( 74.0, TB, "red stripe",     BH, ZZ, "yellow border",  Y,   N,   N,   N), # backhand to yellow border
        throw( 83.1, TB, "yellow border",  BH, ZZ, "federbush",      Y,   N,   N,   N), # backhand federbush
        throw( 84.6, TB, "federbush",      ZZ, ZZ, "naked",          Y,   Y,   N,   N), # to naked for a score

        throw( 90.4, TW, "pikachu",        FL, ZZ, "close crop",     Y,   N,   N,   N), # picked up by pikachu; flick to close crop
        throw( 92.3, TW, "close crop",     BH, ZZ, "joe",            Y,   N,   N,   N), # backhand to joe
        throw( 97.2, TW, "joe",            FL, HK, ZZ,               N,   N,   Y,   N), # joe big flick huck off the wall no score

        throw(108.8, TB, "federbush",      BH, SW, ZZ,               Y,   N,   N,   N), # picked up by federbush for dark; backhand swing to somebody
        throw(115.0, TB, ZZ,               BH, HK, ZZ,               N,   N,   N,   N), # backhand huck deed by stephen butler

        defns(115.9, TW, "stephen butler", N),                                          # deed by stephen butler
        throw(124.0, TW, "stephen",        FL, SW, "tristan",        Y,   N,   N,   N), # stephen picks it up for white; flick swing to tristan
        throw(128.2, TW, "tristan",        HM, HK, ZZ,               Y,   Y,   N,   N), # hammer put to the end zone to somebody for a score

        throw(139.2, TB, ZZ,               FL, SW, "gloves",         Y,   N,   N,   N), # somebody picks it up for dark; flick swing to gloves
        throw(141.5, TB, "gloves",         HM, ZZ, "george",         Y,   Y,   N,   N), # gloves hammer to the end zone to george for a score for dark

        throw(151.5, TW, "kid",            FL, ZZ, "joe",            Y,   N,   N,   N), # kid picks it up for white ;kid flicks to joe
        throw(154.0, TW, "joe",            FL, HK, "kaia",           Y,   Y,   N,   N), # flick huck to kaia in the end zone for a score

        throw(162.2, TB, ZZ,               BH, ZZ, "george",         Y,   N,   N,   N), # somebody picks it up for dark; backhand to george
        throw(166.1, TB, "george",         BH, ZZ, "hat",            Y,   N,   N,   N), # backhand to hat
        throw(167.3, TB, "hat",            BH, ZZ, "george",         Y,   N,   N,   N), # backhand to george
        throw(168.6, TB, "george",         BH, ZZ, "hat",            Y,   N,   N,   N), # backhand hat
        throw(169.4, TB, "hat",            FL, HK, "turtle",         Y,   Y,   Y,   N), # flick put off the wall to turtle in the end zone for a score

        throw(182.8, TW, "pikachu",        BH, SW, "tristan",        Y,   N,   N,   N), # pikachu picks it up for white; tapped in; backhand swing to tristan
        throw(184.0, TW, "tristan",        BH, ZZ, "pikachu",        Y,   N,   N,   N), # backhand to pikachu
        throw(186.5, TW, "pikachu",        BH, ZZ, "tristan",        Y,   N,   N,   N), # backhand to tristan
        throw(187.5, TW, "tristan",        BH, ZZ, "glasses",        Y,   N,   N,   N), # backhand to glasses
        throw(192.0, TW, "glasses",        FL, ZZ, "tristan",        Y,   N,   N,   N), # flick to tristan
        throw(194.1, TW, "tristan",        BH, ZZ, "glasses",        Y,   N,   N,   N), # backhand to glasses
        throw(198.2, TW, "glasses",        FL, ZZ, "kaia",           N,   N,   N,   N), # flick to kaia dropped

        throw(205.6, TB, "gloves",         HM, ZZ, "george",         Y,   Y,   N,   N), # gloves picks it up for dark; hammer put to the end zone caught by george for a score

        throw(219.8, TW, "glasses",        FL, HK, ZZ,               N,   N,   N,   N), # glasses picks it up for white; checked in; flick huck deed by federbush

        defns(222.0, TB, "federbush", N),                                          # deed by federbush
        throw(226.5, TB, "bush",           FL, ZZ, "yellow",         Y,   N,   N,   N), # bush picks it up; flick to yellow
        throw(228.5, TB, "yellow",         BH, ZZ, "bush",           Y,   N,   N,   N), # backhand to bush
        throw(230.8, TB, "bush",           FL, HK, "blue",           Y,   Y,   N,   N), # flick huck caught by blue in the end zone for a score

        throw(239.7, TW, "close crop",     FL, SW, ZZ,               Y,   N,   N,   N), # close crop picks it up for white; flick swing to somebody for white
        throw(246.5, TW, ZZ,               BH, DP, "glasses",        Y,   N,   N,   N), # backhand dump to glasses
        throw(248.3, TW, "glasses",        FL, SW, "close crop",     Y,   N,   N,   N), # flick swing to close crop
        throw(252.0, TW, "close crop",     BH, SW, "glasses",        Y,   N,   N,   N), # backhand swing to glasses
        throw(256.0, TW, "glasses",        BH, ZZ, "emily",          Y,   N,   N,   N), # backhand to emily
        throw(259.3, TW, "emily",          BH, ZZ, "glasses",        Y,   N,   N,   N), # backhand to glasses
        throw(262.9, TW, "glasses",        FL, ZZ, "close crop",     Y,   N,   N,   N), # flick to close crop
        throw(267.1, TW, "close crop",     FL, HK, ZZ,               Y,   Y,   Y,   N), # flick put to the end zone off the wall to somebody for a score

        throw(277.0, TB, "leg stripe",     BH, ZZ, "hat",            Y,   N,   N,   N), # picked up by leg stripe; backhand to hat
        throw(279.0, TB, "hat",            BH, ZZ, "bush",           Y,   N,   N,   N), # backhand to bush
        throw(282.0, TB, "bush",           FL, SW, "naked",          Y,   N,   N,   N), # flick swing to naked
        throw(287.5, TB, "naked",          BH, ZZ, "turtle",         Y,   N,   N,   N), # backhand to turtle
        throw(289.8, TB, "turtle",         BH, ZZ, ZZ,               Y,   Y,   N,   N), # backhand in the end zone caught by

        throw(300.8, TW, "joe",            FL, HK, "pikachu",        Y,   Y,   N,   N), # joe picks it up for white; flick huck caught by pikachu for a score

        throw(317.7, TB, "naked",          BH, HK, ZZ,               N,   N,   N,   N), # picked up by naked for black; backhand huck deed by joe in the end zone

        defns(321.2, TW, "joe", N),                                          # deed by joe in the end zone
        throw(334.8, TW, "close crop",     FL, ZZ, "pikachu",        Y,   N,   N,   N), # picked up by close crop; taps it in; flick to pikachu
        throw(336.5, TW, "pikachu",        BH, ZZ, "kaia",           Y,   N,   N,   N), # backhand to kaia
        throw(339.5, TW, "kaia",           FL, SW, "pikachu",        Y,   N,   N,   N), # flick swing to pikachu
        throw(341.2, TW, "pikachu",        FL, SW, "close crop",     Y,   N,   N,   N), # flick swing to close crop
        throw(344.0, TW, "close crop",     FL, ZZ, "the kid",        Y,   N,   N,   N), # flick to the kid
        throw(353.0, TW, "the kid",        ZZ, DP, "kaia",           Y,   N,   N,   N), # dump to kaia
        throw(354.0, TW, "kaia",           FL, ZZ, "the kid",        Y,   Y,   N,   N), # flick in the end zone to the kid for a score

        throw(364.0, TB, "leg stripes",    FL, ZZ, "gloves",         Y,   N,   N,   N), # picked up by leg stripes; flick to gloves
        throw(366.4, TB, "gloves",         BH, ZZ, "leg stripes",    N,   N,   N,   N), # backhand to leg stripes; stolen by stephen butler

        defns(367.6, TW, "stephen butler", Y),                                          # stolen by stephen butler
        throw(371.1, TW, "stephen butler", BH, ZZ, "the kid",        N,   N,   N,   N), # stolen by stephen butler; backhand to the kid; stolen by gloves

        defns(372.6, TB, "gloves", Y),                                          # stolen by gloves
        throw(378.8, TB, "gloves",         BH, ZZ, "turtle",         Y,   N,   N,   N), # stolen by gloves; gloves taps it in; backhand to turtle
        throw(381.9, TB, "turtle",         BH, ZZ, ZZ,               Y,   N,   N,   N), # backhand to I dunno
        throw(384.0, TB, ZZ,               BH, ZZ, "bush",           Y,   N,   N,   N), # backhand to bush
        throw(386.8, TB, "bush",           BH, ZZ, "george",         Y,   N,   N,   N), # bush backhand to george
        throw(389.7, TB, "george",         BH, ZZ, ZZ,               N,   N,   N,   N), # george backhand dropped

        throw(393.8, TW, "tristan",        BH, ZZ, "kaia",           Y,   N,   N,   N), # tristan picks up for white; backhand to kaia
        throw(396.8, TW, "kaia",           FL, SW, "kid",            Y,   N,   N,   N), # flick swing to kid
        throw(400.6, TW, "kid",            BH, SW, "tristan",        Y,   N,   N,   N), # backhand swing to tristan
        throw(403.8, TW, "tristan",        FL, ZZ, "blondie",        Y,   N,   N,   N), # flick to blondie
        throw(406.7, TW, "blondie",        FL, ZZ, "glasses",        Y,   N,   N,   N), # flick to glasses
        throw(411.8, TW, "glasses",        ZZ, DP, "tristan",        Y,   N,   N,   N), # dump to tristan
        throw(414.4, TW, "tristan",        BH, ZZ, "glasses",        Y,   N,   N,   N), # backhand to glasses
        throw(417.0, TW, "glasses",        ZZ, ZZ, "tristan",        Y,   Y,   N,   N), # to tristan in the end zone for a score

        throw(422.8, TB, ZZ,               BH, ZZ, "george",         Y,   N,   N,   N), # backhand to george
        throw(425.0, TB, "george",         BH, HK, ZZ,               N,   N,   N,   N), # george backhand huck deed by glasses

        defns(430.2, TW, "glasses", N),                                          # deed by glasses
        throw(439.5, TW, "glasses",        FL, ZZ, "tristan",        Y,   N,   N,   N), # glasses picks it up for white; flick to tristan
        throw(443.0, TW, "tristan",        BH, SW, "glasses",        Y,   N,   N,   N), # backhand swing to glasses
        throw(444.9, TW, "glasses",        FL, ZZ, "tristan",        Y,   N,   N,   N), # flick to tristan
        throw(447.0, TW, "tristan",        FL, SW, "blondie",        Y,   N,   N,   N), # flick swing to blondie
        throw(452.3, TW, "blondie",        BH, ZZ, "tristan",        Y,   N,   N,   N), # backhand to tristan
        throw(453.5, TW, "tristan",        BH, ZZ, "emily",          Y,   N,   N,   N), # backhand to emily
        throw(455.7, TW, "emily",          BH, ZZ, "tristan",        Y,   N,   N,   N), # backhand to tristan
        throw(457.8, TW, "tristan",        BH, ZZ, "blondie",        Y,   N,   N,   N), # backhand to blondie
        throw(459.8, TW, "blondie",        SC, ZZ, ZZ,               Y,   Y,   N,   N), # scoober in the end zone for a score to somebody

        throw(468.0, TB, "george",         SC, SW, "bluey",          Y,   N,   N,   N), # picked up by george; backhand to bluey
        throw(471.3, TB, "bluey",          BH, HK, ZZ,               N,   N,   N,   N), # backhand huck turfed

        throw(485.1, TW, "tristan",        BH, ZZ, "close crop",     Y,   N,   N,   N),  # tristan backhand to close crop
        throw(486.8, TW, "close crop",     BH, ZZ, "joe",            Y,   N,   N,   N),  # backhand to joe
        throw(489.5, TW, "joe",            BH, CF, "emily",          Y,   Y,   N,   N),  # backhand across in the end zone emily for a score

        throw(502.0, TB, "naked",          FL, SW, "george",         Y,   N,   N,   N),  # picked up by naked for black; flick swing to george
        throw(506.1, TB, "george",         BH, ZZ, "yellow stripe",  Y,   N,   N,   N),  # backhand to yellow stripe
        throw(508.0, TB, "yellow stripe",  SC, ZZ, "hat",            Y,   N,   N,   N),  # scoober to hat
        throw(511.9, TB, "hat",            BH, ZZ, "naked",          Y,   N,   N,   N),  # backhand to naked
        throw(515.9, TB, "naked",          BH, SW, "purple leg stripe",Y, N,   N,   N),  # backhand swing to purple leg stripe
        throw(519.8, TB, "purple leg stripe", BH, ZZ, "yellow stripe yellow fringe", Y, N, N, N), # backhand to yellow stripe yellow fringe
        throw(522.5, TB, "yellow stripe yellow fringe", BH, ZZ, "pants stripe", N, N, Y, N), # backhand to the end zone pants stripe off the wall no score

        throw(528.8, TW, "close crop",     BH, ZZ, "tristan",        Y,   N,   N,   N),  # picked up by close crop for white; backhand to tristan
        throw(529.9, TW, "tristan",        BH, ZZ, "pikachu",        Y,   N,   N,   N),  # backhand to pikachu
        throw(534.0, TW, "pikachu",        BH, SW, "joe",            Y,   N,   N,   N),  # backhand swing to joe
        throw(537.6, TW, "joe",            FL, ZZ, "pikachu",        Y,   N,   N,   N),  # flick to pikachu
        throw(541.2, TW, "pikachu",        BH, ZZ, "close crop",     Y,   N,   N,   N),  # backhand to close crop
        throw(543.0, TW, "close crop",     BH, ZZ, "kaia",           Y,   N,   N,   N),  # backhand to kaia
        throw(547.0, TW, "kaia",           FL, SW, "close crop",     Y,   N,   N,   N),  # swing flick to close crop swing
        throw(549.0, TW, "close crop",     BH, ZZ, "pikachu",        Y,   N,   N,   N),  # backhand to pikachu
        throw(551.5, TW, "pikachu",        BH, ZZ, "stephen butler", Y,   Y,   N,   N),  # backhand to stephen butler for a score

        throw(565.8, TB, "hat",            BH, ZZ, "turtle",         Y,   N,   N,   N),  # hat checks in for dark; backhand to turtle
        throw(567.0, TB, "turtle",         BH, ZZ, "leg stripe",     Y,   N,   N,   N),  # backhand to leg stripe
        throw(570.0, TB, "leg stripe",     BH, ZZ, "hat",            Y,   N,   N,   N),  # backhand to hat
        throw(572.5, TB, "hat",            BH, ZZ, "leg stripe",     Y,   N,   N,   N),  # backhand to leg stripe
        throw(574.0, TB, "leg stripe",     FL, ZZ, "bush",           Y,   N,   N,   N),  # flick to bush
        throw(577.0, TB, "bush",           FL, HK, "turtle",         Y,   Y,   Y,   N),  # flick put to turtle off the wall for a score

        throw(589.4, TW, "glasses",        FL, SW, "stephen butler", Y,   N,   N,   N),  # glasses picks it up for white; flick swing to stephen butler
        throw(592.4, TW, "stephen butler", FL, ZZ, "the kid",        Y,   N,   N,   N),  # flick to the kid
        throw(596.6, TW, "the kid",        FL, ZZ, "close crop",     Y,   N,   N,   N),  # flick to close crop
        throw(601.5, TW, "close crop",     FL, SW, "the kid",        Y,   N,   N,   N),  # flick swing to the kid
        throw(604.4, TW, "the kid",        BH, ZZ, "blondie",        Y,   N,   N,   N),  # backhand to blondie
        throw(605.5, TW, "blondie",        BH, ZZ, "kaia",           Y,   N,   N,   N),  # backhand to kaia
        throw(609.9, TW, "kaia",           FL, SW, "stephen butler", Y,   N,   N,   N),  # flick swing to stephen butler
        throw(613.3, TW, "stephen butler", FL, ZZ, "the kid",        Y,   Y,   N,   N),  # flick into the end zone to the kid for a score

        throw(623.7, TB, "turtle",         BH, ZZ, "bush",           Y,   N,   N,   N),  # turtle picks it up for dark; checks it in; backhand to bush
        throw(626.5, TB, "bush",           FL, ZZ, "leg stripe",     Y,   N,   N,   N),  # flick to leg stripe
        throw(629.4, TB, "leg stripe",     BH, ZZ, ZZ,               Y,   N,   N,   N),  # backhand to I don't know
        throw(632.2, TB, ZZ,               BH, ZZ, ZZ,               N,   N,   N,   N),  # backhand deed by the kid

        defns(632.8, TW, "the kid", N),                                              # deed by the kid
        throw(642.9, TW, "the kid",        FL, ZZ, "emily",          Y,   N,   N,   N),  # flick to emily
        throw(646.4, TW, "emily",          FL, ZZ, "blondie",        Y,   N,   N,   N),  # flick to blondie
        throw(650.2, TW, "blondie",        BL, ZZ, ZZ,               Y,   N,   N,   N),  # blade in the end zone nope, not in the end zone, caught by somebody
        throw(656.0, TW, ZZ,               ZZ, DP, "blondie",        Y,   N,   N,   N),  # then dump to blondie
        throw(661.9, TW, "blondie",        ZZ, DP, "tristan",        Y,   N,   N,   N),  # power dump to tristan
        throw(665.2, TW, "tristan",        BH, ZZ, "blondie",        Y,   N,   N,   N),  # backhand to blondie
        throw(667.8, TW, "blondie",        FL, ZZ, "the kid",        Y,   Y,   N,   N),  # flick to the kid for a score

        throw(671.0, TB, "bush",           ZZ, ZZ, ZZ,               Y,   N,   N,   N),  # bush picks it up
        throw(676.8, TB, ZZ,               BL, ZZ, "bush",           Y,   N,   N,   N),  # blade to bush
        throw(679.5, TB, "bush",           SC, ZZ, "bluey",          Y,   Y,   N,   N),  # bush scoober to bluey in the end zone for a score

        throw(690.1, TW, "tristan",        BH, ZZ, "blondie",        Y,   N,   N,   N),  # tristan picks it up for white, backhand to blondie
        throw(693.8, TW, "blondie",        BH, ZZ, "joe",            Y,   N,   N,   N),  # backhand to joe
        throw(695.5, TW, "joe",            BH, ZZ, "tristan",        Y,   N,   N,   N),  # backhand to tristan
        throw(697.4, TW, "tristan",        BH, ZZ, "glasses",        Y,   N,   N,   N),  # backhand to glasses
        throw(703.8, TW, "glasses",        FL, SW, "pikachu",        Y,   N,   N,   N),  # flick swing to pikachu
        throw(705.5, TW, "pikachu",        FL, SW, "tristan",        Y,   N,   N,   N),  # flick swing to tristan
        throw(707.8, TW, "tristan",        HM, ZZ, "blondie",        Y,   Y,   N,   N),  # hammer to the end zone blondie for a score

        throw(718.8, TB, "bush",           BH, SW, "george",         Y,   N,   N,   N),  # bush picks up for dark, backhand swing to george
        throw(721.2, TB, "george",         BH, ZZ, "naked",          Y,   N,   N,   N),  # backhand to naked
        throw(726.2, TB, "naked",          BH, ZZ, "yellow fringe",  Y,   N,   N,   N),  # backhand to yellow fringe
        throw(729.0, TB, "yellow fringe",  FL, ZZ, ZZ,               N,   N,   N,   N),  # flick turf

        throw(738.1, TW, "joe",            FL, ZZ, "tristan",        Y,   N,   N,   N),  # flick tristan
        throw(741.0, TW, "tristan",        FL, ZZ, "glasses",        Y,   N,   N,   N),  # flick to glasses
        throw(746.6, TW, "glasses",        FL, HK, "close crop",     Y,   Y,   N,   N),  # flick put to close crop for a score

        throw(756.7, TB, "george",         SC, SW, "naked",          Y,   N,   N,   N),  # george picks up for dark, scoober swing to naked
        throw(758.8, TB, "naked",          BH, ZZ, "yellow fringe",  Y,   N,   N,   N),  # backhand to yellow fringe
        throw(761.8, TB, "yellow fringe",  BH, ZZ, "turtle",         Y,   N,   N,   N),  # backhand to turtle
        throw(763.4, TB, "turtle",         BH, ZZ, "hat",            N,   N,   N,   N),  # backhand bobbled/dropped by hat no score

        throw(772.0, TW, "glasses",        FL, ZZ, "tristan",        Y,   N,   N,   N),  # glasses picks up for white, flick to tristan
        throw(774.0, TW, "tristan",        BH, ZZ, "kaia",           Y,   N,   N,   N),  # backhand to kaia
        throw(779.2, TW, "kaia",           FL, DP, "glasses",        Y,   N,   N,   N),  # flick dump to glasses
        throw(782.3, TW, "glasses",        FL, ZZ, "stephen butler", Y,   N,   N,   N),  # flick to stephen butler
        throw(784.8, TW, "stephen butler", FL, HK, "close crop",     Y,   Y,   N,   N),  # flick put huck close crop in the end zone for a score

        throw(797.5, TB, "naked",          BH, ZZ, ZZ,               Y,   N,   N,   N),  # naked picks up for dark, backhand to somebody
        throw(801.7, TB, ZZ,               BH, DP, "naked",          Y,   N,   N,   N),  # backhand dump to naked
        throw(803.8, TB, "naked",          BH, ZZ, "leg stripe",     Y,   N,   N,   N),  # backhand to leg stripe
        throw(805.0, TB, "leg stripe",     BH, ZZ, ZZ,               N,   N,   Y,   N),  # backhand to turf no score off wall

        throw(820.0, TW, "glasses",        FL, ZZ, "emily",          Y,   N,   N,   N),  # glasses picks it up for white, flick to emily
        throw(824.5, TW, "emily",          BL, ZZ, ZZ,               Y,   N,   N,   N),  # blade to I dunno
        throw(828.4, TW, ZZ,               FL, ZZ, "kaia",           N,   N,   N,   N),  # flick to kaia, dropped it

        throw(841.4, TB, ZZ,               BH, ZZ, "leg stripes",    Y,   N,   N,   N),  # picked up by somebody for dark, backhand to leg stripes
        throw(843.0, TB, "leg stripes",    BH, ZZ, ZZ,               Y,   N,   N,   N),  # backhand to I don't know
        throw(846.5, TB, ZZ,               BH, ZZ, "leg stripes",    Y,   N,   N,   N),  # backhand to leg stripes
        throw(850.0, TB, "leg stripes",    BH, DP, "gloves",         Y,   N,   N,   N),  # backhand dump to gloves
        throw(852.2, TB, "gloves",         HM, ZZ, "turtle",         N,   N,   N,   N),  # hammer to turtle dropped it no score

        throw(877.3, TW, "stephen",        FL, ZZ, "joe",            Y,   N,   N,   N),  # stephen picks it up for white, flick to joe
        throw(880.1, TW, "joe",            FL, ZZ, "blondie",        Y,   N,   N,   N),  # flick to blondie
        throw(883.4, TW, "blondie",        BH, ZZ, "stephen",        Y,   N,   N,   N),  # backhand to stephen
        throw(885.5, TW, "stephen",        FL, HK, ZZ,               N,   N,   N,   N),  # flick huck deed by gloves

        defns(886.1, TB, "gloves", N),                                              # deed by gloves
        throw(895.1, TB, "gloves",         BH, SW, "leg stripe",     Y,   N,   N,   N),  # picked up by gloves for black, backhand swing to leg stripe
        throw(897.3, TB, "leg stripe",     BH, ZZ, ZZ,               Y,   N,   N,   N),  # backhand to I don't know
        throw(900.0, TB, ZZ,               BH, ZZ, "bush",           Y,   N,   N,   N),  # backhand to bush
        throw(903.8, TB, "bush",           BH, ZZ, "yellow fringe",  Y,   Y,   N,   N),  # backhand to yellow fringe for a score

        throw(911.7, TW, "stephen butler", FL, ZZ, "blondie",        Y,   N,   N,   N),  # stephen butler picks it up, flick to blondie
        throw(913.4, TW, "blondie",        FL, ZZ, "joe",            Y,   N,   N,   N),  # flick to joe
        throw(922.7, TW, "joe",            HM, CF, ZZ,               N,   N,   N,   N),  # cross field hammer turf

        throw(925.8, TB, "gloves",         BH, ZZ, "yellow fringe",  Y,   N,   N,   N),  # picked up by gloves for dark; backhand to yellow fringe
        throw(929.7, TB, "yellow fringe",  FL, ZZ, "george",         Y,   N,   N,   N),  # flick to george
        throw(932.7, TB, "george",         BH, DP, "gloves",         Y,   N,   N,   N),  # backhand dump to gloves
        throw(937.1, TB, "gloves",         BH, SW, "yellow fringe",  Y,   N,   N,   N),  # backhand swing to yellow fringe
        throw(939.8, TB, "yellow fringe",  BH, ZZ, "bush",           Y,   N,   N,   N),  # backhand to bush
        throw(943.3, TB, "bush",           BL, ZZ, "george",         Y,   N,   N,   N),  # blade to george
        throw(946.5, TB, "george",         BH, ZZ, "yellow fringe",  Y,   N,   N,   N),  # backhand to yellow fringe
        throw(950.3, TB, "yellow fringe",  BH, ZZ, "bush",           Y,   N,   N,   N),  # backhand to bush
        throw(952.2, TB, "bush",           FL, HK, ZZ,               N,   N,   N,   N),  # flick huck turf no score
    ]
    # fmt: on

    return stream


def build_unified_stream(raw: yus.EventStream) -> yus.EventStream:
    unified = copy.deepcopy(raw)

    # FIXME: Need someone who was there to tell me who the remaining unknown people are
    aliases: dict[str, set[str]] = {
        "Matt Whitlock": {"pikachu"},
        "Kaia Mann": {"kaia"},
        "Emily Kraus": {"emily"},
        "bluey": {"blue"},
        "Ben Kishter": {"close crop"},
        "Joe Oaks": {"joe"},
        "Serayan Knappe-Butler": {"kid", "the kid"},
        "Stephen Butler": {"stephen", "stephen butler"},
        "Tristan Weber": {"tristan"},
        "Adam Federbusch": {"bush", "federbush"},
        "Christopher Baines": {"hat"},
        "yellow sleeve": {"yellow", "yellow border", "yellow fringe", "yellow stripe", "yellow stripe yellow fringe"},
        "leg stripe": {"leg stripes", "pants stripe", "purple leg stripe"},
        "Zach Ehler": {"turtle"},
        "George Abuhamad": {"george"},
    }
    reverse_map = {v: player for player, player_aliases in aliases.items() for v in player_aliases}

    for evt in unified.events:
        if isinstance(evt, (indoor.Throw, ultimate.Defense)):
            if evt.player in reverse_map:
                evt.player = reverse_map[evt.player]

        if isinstance(evt, indoor.Throw):
            if evt.receiver in reverse_map:
                evt.receiver = reverse_map[evt.receiver]

    return unified
