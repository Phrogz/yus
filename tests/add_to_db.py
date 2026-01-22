import datetime

from tests.data.gruindoor_20250114T2030 import build_game
from yus.sports.ultimate import indoor
from yus.web import db


def offset_from_start(when: datetime.datetime) -> str:
    return f"{game.offset_from_start(when).total_seconds():.1f}"


game = build_game()

if game.official_stream:
    stream = game.official_stream
    throws = (evt for evt in stream.events if isinstance(evt, indoor.Throw))

    db.execmany(  # type: ignore
        """
        INSERT INTO throws (
            timestamp, team, player_name, throw_type, throw_direction,
            receiver, completed, scored, hit_the_wall, hit_the_net
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                offset_from_start(t.when),
                t.team,
                t.player,
                t.type,
                t.direction,
                t.receiver,
                t.completed,
                t.scored,
                t.hit_wall,
                t.hit_net,
            )
            for t in throws
        ],
    )

    # for d in (evt for evt in stream.events if isinstance(evt, ultimate.Defense)):
    #     print(
    #         "\t".join(
    #             [
    #                 offset_from_start(d.when),
    #                 d.team,
    #                 d.player or "-",
    #                 d.intercepted and "TRUE" or "FALSE",
    #             ]
    #         )
    #     )
