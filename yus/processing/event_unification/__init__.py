"""Event unification phase: turn per-commentator event streams into one official stream for a game.

Steps, in order:
  1. Player resolution (`players`): map the names each commentator used ("pikachu", "the kid") to roster players.
  2. Stream merging (`merge`): align the resolved streams of several commentators, pair events that describe the same action,
     and settle their disagreements into one official stream.
"""

from yus.processing.event_unification.merge import Conflict, LiveMerger, MergeResult, NameLink, merge_streams
from yus.processing.event_unification.players import GameDescriptions, PlayerDescription, PlayerResolver

__all__ = ["Conflict", "GameDescriptions", "LiveMerger", "MergeResult", "NameLink", "PlayerDescription", "PlayerResolver", "merge_streams"]
