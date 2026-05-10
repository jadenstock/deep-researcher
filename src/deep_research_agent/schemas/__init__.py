"""Pydantic data models for the note graph.

The note graph is the agents' persistent memory across a run. Notes
have a type (source / question / synthesis / hypothesis / ...) and a
discriminated metadata payload specific to that type.
"""

from .enums import (
    ClaimType,
    Methodology,
    NoteType,
    QuestionClassification,
    Reproducibility,
    RoleClass,
    SourceState,
    TaskTier,
    Tier,
    VerificationStatus,
)
from .ids import NoteID, RunID, SourceID, TaskID
from .note import (
    DecisionMetadata,
    HypothesisMetadata,
    LandscapeMetadata,
    Link,
    Note,
    NoteMetadata,
    OpenQuestionMetadata,
    PositionItem,
    QuestionMetadata,
    SourceNoteMetadata,
    SynthesisMetadata,
    ThemeItem,
)
from .source import ClaimItem, EvalItem, SourceMetadata, StructuredContent

__all__ = [
    # source
    "ClaimItem",
    # enums
    "ClaimType",
    # note
    "DecisionMetadata",
    "EvalItem",
    "HypothesisMetadata",
    "LandscapeMetadata",
    "Link",
    "Methodology",
    "Note",
    # ids
    "NoteID",
    "NoteMetadata",
    "NoteType",
    "OpenQuestionMetadata",
    "PositionItem",
    "QuestionClassification",
    "QuestionMetadata",
    "Reproducibility",
    "RoleClass",
    "RunID",
    "SourceID",
    "SourceMetadata",
    "SourceNoteMetadata",
    "SourceState",
    "StructuredContent",
    "SynthesisMetadata",
    "TaskID",
    "TaskTier",
    "ThemeItem",
    "Tier",
    "VerificationStatus",
]
