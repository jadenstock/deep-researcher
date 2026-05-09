"""Shared corpus: URL-keyed view over source_notes.

The corpus is the single pool of sources that all sub-questions draw
from. A source enters the corpus as SCOUTED from any SCOUT_SOURCES
task (landscape-seeded, question-seeded, or verify-seeded), gets
promoted to FETCHED by FETCH_AND_EXTRACT, and accumulates claims for
one or more questions as ANALYZE_SOURCE runs against it.

This module provides:
- `canonicalize_url`: stable URL key so the same source retrieved via
  different queries dedupes to one note.
- `CorpusIndex`: a read-only view over a NoteReader that finds sources
  by URL, state, or question-relevance.
"""

from .registry import CorpusIndex, canonicalize_url

__all__ = ["CorpusIndex", "canonicalize_url"]
