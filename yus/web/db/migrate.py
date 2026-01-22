from yus.web import db

db.exec("""
CREATE TABLE IF NOT EXISTS throws (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    team TEXT,
    player_name TEXT,
    throw_type TEXT,
    throw_direction TEXT,
    receiver TEXT,
    completed INTEGER,
    scored INTEGER,
    hit_the_wall INTEGER,
    hit_the_net INTEGER
)
""")
