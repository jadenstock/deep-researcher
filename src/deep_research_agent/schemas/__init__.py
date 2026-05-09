"""Pydantic data models for the task graph and note graph.

Every non-trivial type the system operates on lives here. These schemas are
the type-level specification of the TDD §4 data model; the rest of the code
reads and writes them.
"""

from .enums import (
    ClaimType,
    DependencyType,
    Methodology,
    NoteType,
    OrchestrationPattern,
    QuestionClassification,
    QuestionRound,
    Reproducibility,
    RoleClass,
    SourceState,
    TaskStatus,
    TaskTier,
    TaskType,
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
from .task import DepEdge, DepScope, Task

__all__ = [
    # enums
    "ClaimType",
    "DependencyType",
    "Methodology",
    "NoteType",
    "OrchestrationPattern",
    "QuestionClassification",
    "QuestionRound",
    "Reproducibility",
    "RoleClass",
    "SourceState",
    "TaskStatus",
    "TaskTier",
    "TaskType",
    "Tier",
    "VerificationStatus",
    # ids
    "NoteID",
    "RunID",
    "SourceID",
    "TaskID",
    # task
    "DepEdge",
    "DepScope",
    "Task",
    # source
    "ClaimItem",
    "EvalItem",
    "SourceMetadata",
    "StructuredContent",
    # note
    "DecisionMetadata",
    "HypothesisMetadata",
    "LandscapeMetadata",
    "Link",
    "Note",
    "NoteMetadata",
    "OpenQuestionMetadata",
    "PositionItem",
    "QuestionMetadata",
    "SourceNoteMetadata",
    "SynthesisMetadata",
    "ThemeItem",
]
