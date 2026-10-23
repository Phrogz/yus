"""Event extraction phase: turn a play-by-play transcript into game events.

`EventExtractor` is a rule-based, streaming extractor for indoor Ultimate: feed it transcript groups as they arrive and read
`events` (final ones first, then provisional ones). `extract_events` runs it over a whole transcript. The yus-events
command-line tool (`cli`) does the same for transcript JSON files. `llm.AssistedExtractor` optionally sends the groups the rules
may have misread to a local LLM (Ollama) for a second reading.
"""

from yus.processing.event_extraction.extractor import Association, EventExtractor, extract_events, team_label
from yus.processing.event_extraction.llm import AssistedExtractor, LLMAssistant

__all__ = ["AssistedExtractor", "Association", "EventExtractor", "LLMAssistant", "extract_events", "team_label"]
