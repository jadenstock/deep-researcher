"""Typed ID aliases. String underneath; NewType for readability only."""

from __future__ import annotations

from typing import NewType

TaskID = NewType("TaskID", str)
NoteID = NewType("NoteID", str)
RunID = NewType("RunID", str)
# A SourceID is a NoteID that points at a source_note. Separate alias for clarity.
SourceID = NewType("SourceID", str)
