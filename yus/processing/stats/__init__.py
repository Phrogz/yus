"""Stats phase: turn a resolved event stream into pandas tables (box scores, points, possessions, connections, ...).

    stats = compute_stats(resolved_stream, teams=game.teams)
    stats.summary()          # "Dump & Drizzle 14, Category 5 9"
    stats.player_box         # one row per (team, player)

See docs/stats.md.
"""

from yus.processing.stats.compute import GameStats, compute_stats

__all__ = ["GameStats", "compute_stats"]
