"""Event unification phase: turn per-commentator event streams into one official stream for a game.

Steps, in order:
  1. Player resolution (`players`): map the names each commentator used ("pikachu", "the kid") to roster players. Built.
  2. Stream merging: align events from several commentators and resolve conflicts. Not built yet.
"""

from yus.processing.event_unification.players import GameDescriptions, PlayerDescription, PlayerResolver

__all__ = ["GameDescriptions", "PlayerDescription", "PlayerResolver"]
