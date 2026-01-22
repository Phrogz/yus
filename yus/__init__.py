from __future__ import annotations

import datetime

import pydantic


class Term(pydantic.BaseModel):
    """
    A word or phrase likely to be said in a play-by-play transcript.

    Args:
        phrase (str): The word or phrase said.
        weight (float): The likelihood of the phrase being said, from 0.0 to 1.0. Defaults to 1.0.
    """

    phrase: str = pydantic.Field(..., description="The word or phrase said.")
    weight: float = pydantic.Field(1.0, description="The likelihood of utterance, from 0.0 (least likely) to  1.0 (most likely).")


class PlayerInfo(pydantic.BaseModel):
    """
    Detailed information about a player, including nicknames and mondegreens.
    (A mondegreen is a mishearing or misinterpretation of a phrase.)
    """

    nicknames: list[str] = pydantic.Field(default_factory=list, description="Alternate names for the player (e.g. nicknames, jersey numbers).")
    mondegreens: list[str] = pydantic.Field(default_factory=list, description="Words or phrases to replace with the official name (e.g. 'feather brush' -> 'Federbusch').")


class Team(pydantic.BaseModel):
    """
    Represents a team in a specific game.
    A single organized team may have multiple Team instances to handle different sets of players or substitutions.
    """

    names: list[str] = pydantic.Field([], description="Names for the team, e.g. 'Flight Club' or 'white'.")
    players: dict[str, list[str] | PlayerInfo] = pydantic.Field(
        {},
        description="Player names mapping to either a list of nicknames, or a PlayerInfo dict with 'nicknames' and 'mondegreens' fields.",
    )


class Game(pydantic.BaseModel):
    """
    Represents a single played game.
    """

    sport: str = pydantic.Field(..., description="The sport played in the game.")
    when: datetime.datetime = pydantic.Field(..., description="The date/time when the game started.")
    teams: list[Team] = pydantic.Field(default_factory=lambda: list[Team](), description="The teams playing in the game.")
    transcripts: list[Transcript] = pydantic.Field(default_factory=lambda: list[Transcript](), description="The play-by-play transcript(s) for this game.")
    event_streams: list[EventStream] = pydantic.Field(default_factory=lambda: list[EventStream](), description="The event stream(s) for this game.")
    official_stream: EventStream | None = pydantic.Field(default=None, description="The official, unified event stream for this game.")

    def offset_from_start(self, when: datetime.datetime) -> datetime.timedelta:
        """Calculate the offset of a given time from the start of the game."""
        return when - self.when

    def __str__(self) -> str:
        return f"{self.sport} game on {self.when} between {' and '.join(f'{team.names[0]!r}' for team in self.teams)}"


class Word(pydantic.BaseModel):
    text: str
    confidence: float = 0.0
    start: datetime.datetime
    duration: datetime.timedelta = datetime.timedelta(seconds=0)


class Interpretation(pydantic.BaseModel):
    """One possible interpretation of a group of words."""

    words: list[Word] = []
    confidence: float = pydantic.Field(default=0.0, description="The confidence of this interpretation.")
    group: TranscriptGroup | None = pydantic.Field(default=None, description="The group this interpretation belongs to.")

    @property
    def transcript(self) -> str:
        return " ".join(word.text for word in self.words)

    @property
    def start(self) -> datetime.datetime:
        return self.words[0].start

    @property
    def duration(self) -> datetime.timedelta:
        return self.words[-1].start + self.words[-1].duration - self.words[0].start

    def add_word(
        self,
        text: str,
        *,
        start: datetime.datetime,
        duration: datetime.timedelta = datetime.timedelta(),
        confidence: float = 0.0,
    ) -> Word:
        word = Word(text=text, confidence=confidence, start=start, duration=duration)
        self.words.append(word)
        return word

    def __str__(self) -> str:
        a = self.start
        b = self.start + self.duration
        if self.group:
            a -= self.group.transcript.start
            b -= self.group.transcript.start
        return f"({self.confidence * 100:.0f}% {a}–{b}) {self.transcript}"


class TranscriptGroup(pydantic.BaseModel):
    """A section of words that definitely go together."""

    interpretations: list[Interpretation] = []
    transcript: Transcript

    @property
    def start(self) -> datetime.datetime:
        return self.interpretations[0].start

    @property
    def duration(self) -> datetime.timedelta:
        return self.interpretations[0].duration

    @property
    def words(self) -> list[Word]:
        if not self.interpretations:
            return []
        return self.interpretations[0].words

    def add_interpretation(self, confidence: float = 0.0) -> Interpretation:
        interp = Interpretation(group=self, confidence=confidence)
        self.interpretations.append(interp)
        return interp

    def __str__(self) -> str:
        return "\n".join(str(interp) for interp in self.interpretations)


class Transcript(pydantic.BaseModel):
    """Transcript of a game."""

    game: Game | None = pydantic.Field(default=None, description="The game being described.")
    commentator: str | None = pydantic.Field(default=None, description="The name of the person providing this play-by-play.")
    groups: list[TranscriptGroup] = []

    @property
    def words(self) -> list[Word]:
        return [word for group in self.groups for word in group.words]

    @property
    def start(self) -> datetime.datetime:
        return self.groups[0].start

    def duration(self) -> datetime.timedelta:
        return self.groups[-1].start + self.groups[-1].duration - self.groups[0].start

    def add_group(self) -> TranscriptGroup:
        group = TranscriptGroup(transcript=self)
        self.groups.append(group)
        return group

    def __str__(self) -> str:
        return "\n\n".join(str(group) for group in self.groups)


class Event(pydantic.BaseModel):
    """
    Base class for all events, with the minimal common fields.

    Args:
        when (datetime.datetime): The date/time when the event occurred.
    """

    when: datetime.datetime


class EventStream(pydantic.BaseModel):
    game: Game | None = pydantic.Field(default=None, description="The game being described.")
    transcript: Transcript | None = pydantic.Field(default=None, description="The play-by-play transcript these events are derived from.")
    events: list[Event] = []

    def add(self, evt: Event) -> EventStream:
        self.events.append(evt)
        return self


__all__ = ["Term", "Game", "Team", "Event", "EventStream", "Transcript", "TranscriptGroup", "Interpretation", "Word"]
