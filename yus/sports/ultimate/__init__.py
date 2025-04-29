import enum

import pydantic

import yus


class UltimateEvent(yus.Event):
    """
    Base class for all events, with the minimal common fields.
    """

    team: str = pydantic.Field(..., description='The team of the player (e.g., "white" or "black/dark").')
    player: str | None = pydantic.Field(None, description="The name/nickname/number/id of the player who initiated the event.")


class ThrowType(enum.StrEnum):
    FLICK = enum.auto()
    BACKHAND = enum.auto()
    HAMMER = enum.auto()
    BLADE = enum.auto()
    SCOOBER = enum.auto()
    CHICKEN_WING = enum.auto()


class ThrowDirection(enum.StrEnum):
    DUMP = enum.auto()
    SWING = enum.auto()
    UP_LINE = enum.auto()
    CROSS_FIELD = enum.auto()
    HUCK = enum.auto()


class Throw(UltimateEvent):
    """
    Represents a single throw (pass) by the offense, and its outcome.
    """

    type: ThrowType | None = pydantic.Field(None, description="The style of throw (flick, backhand, hammer, etc.).")
    direction: ThrowDirection | None = pydantic.Field(None, description="The general direction (dump, swing, huck, cross-field, etc.).")
    receiver: str | None = pydantic.Field(None, description='Name of the intended receiver (e.g. "kaia", "someone", or None if unknown).')
    completed: bool = pydantic.Field(..., description="True if the disc was successfully caught by the intended receiver.")
    scored: bool = pydantic.Field(..., description="True if the catch occurred in the end zone, resulting in a point.")


class Defense(UltimateEvent):
    """
    Represents a defensive play (block or interception).
    """

    intercepted: bool = pydantic.Field(False, description="Did the defender catch the disc, or just prevent the catch?")


class SubType(enum.StrEnum):
    SUB_ON = enum.auto()
    SUB_OFF = enum.auto()


class Substitution(UltimateEvent):
    """
    Represents a player substitution (either subbing on or off).
    """

    sub_type: SubType = pydantic.Field(..., description="SUB_ON or SUB_OFF.")


class Infraction(UltimateEvent):
    """
    A foul or violation.
    """
    called_on_plyr: str | None = pydantic.Field(None, description='Name of the player that called the infraction.')
    called_on_team: str | None = pydantic.Field(None, description='Name of the team that the infraction was called on.')
    contested: bool = pydantic.Field(False, description="True if the violation was contested.")


terms: list[yus.Term] = []
terms.extend(
    yus.Term(phrase=s.replace("_", " "), weight=1.0)
    for s in """
        flick backhand swing swing_to swings_to dump dump_to dumps_to
        to end_zone for_a_score for_the_score for_a_goal goal score
        picked_up_by tapped_in taps_it_in
        white dark black for_white for_dark for_black
    """.split()
)
terms.extend(
    yus.Term(phrase=s.replace("_", " "), weight=0.7)
    for s in """
        pull
        hammer scoober blade
        swing dump huck laser
        pick injury foul violation travel strip stall stalled_out called
        turf turfed
        turn turnover dropped D intercepted deed deed_by subs subbed
    """.split()
)
terms.extend(
    yus.Term(phrase=s.replace("_", " "), weight=0.2)
    for s in """
        checks_it_in checks_in checks_it
        thumber chicken_wing pizza
    """.split()
)


__all__ = ["terms", "UltimateEvent", "Throw", "Defense", "ThrowType", "ThrowDirection", "SubType"]
