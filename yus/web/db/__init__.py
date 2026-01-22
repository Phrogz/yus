import contextlib
import pathlib
import sqlite3

path = pathlib.Path(__file__).parent / "yus.sqlite3"


def exec(sql: str) -> None:
    # https://stackoverflow.com/a/47501337/405017
    with contextlib.closing(sqlite3.connect(path)) as conn:
        with conn:
            with contextlib.closing(conn.cursor()) as cur:
                cur.execute(sql)


def execmany(sql: str, data: list[tuple]) -> None:  # type: ignore
    with contextlib.closing(sqlite3.connect(path)) as conn:
        with conn:
            with contextlib.closing(conn.cursor()) as cur:
                cur.executemany(sql, data)  # type: ignore
