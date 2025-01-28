import datetime

from tests.data.gruindoor_20250114T2030 import build_game
from yus.sports import ultimate
from yus.sports.ultimate import indoor


def offset_from_start(when: datetime.datetime) -> str:
    return f"{game.offset_from_start(when).total_seconds():.1f}"


game = build_game()

if game.official_stream:
    stream = game.official_stream
    print("\t".join(["Seconds", "Team", "Player", "Type", "Direction", "Receiver", "Completed?", "Scored?", "Hit Wall?", "Hit Net?"]))
    for throw in (evt for evt in stream.events if isinstance(evt, indoor.Throw)):
        print(
            "\t".join(
                [
                    offset_from_start(throw.when),
                    throw.team,
                    throw.player or "-",
                    throw.type or "-",
                    throw.direction or "-",
                    throw.receiver or "-",
                    throw.completed and "TRUE" or "FALSE",
                    throw.scored and "TRUE" or "FALSE",
                    throw.hit_wall and "TRUE" or "FALSE",
                    throw.hit_net and "TRUE" or "FALSE",
                ]
            )
        )

    print()
    print("\t".join(["Seconds", "Team", "Player", "Intercepted?"]))
    for d in (evt for evt in stream.events if isinstance(evt, ultimate.Defense)):
        print(
            "\t".join(
                [
                    offset_from_start(d.when),
                    d.team,
                    d.player or "-",
                    d.intercepted and "TRUE" or "FALSE",
                ]
            )
        )
