"""Pydantic data models for the note graph.

The note graph is the agents' persistent memory across a run. Notes have
a type (source / question / synthesis / landscape) and a discriminated
metadata payload specific to that type.
"""

from .enums import (
    ClaimType,
    NoteType,
    QuestionClassification,
    RoleClass,
    SourceState,
    TaskTier,
    Tier,
    VerificationStatus,
)
from .ids import NoteID, RunID, SourceID, TaskID
from .note import (
    LandscapeMetadata,
    Link,
    Note,
    NoteMetadata,
    QuestionMetadata,
    SourceNoteMetadata,
    SynthesisMetadata,
)
from .source import ClaimItem, SourceMetadata

__all__ = [
    "ClaimItem",
    "ClaimType",
    "LandscapeMetadata",
    "Link",
    "Note",
    "NoteID",
    "NoteMetadata",
    "NoteType",
    "QuestionClassification",
    "QuestionMetadata",
    "RoleClass",
    "RunID",
    "SourceID",
    "SourceMetadata",
    "SourceNoteMetadata",
    "SourceState",
    "SynthesisMetadata",
    "TaskID",
    "TaskTier",
    "Tier",
    "VerificationStatus",
]
