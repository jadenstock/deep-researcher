"""Note graph models.

Note is the only long-term memory. Every note has a typed metadata payload
discriminated by `type`. Links are typed edges between notes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from .enums import ConfidenceLevel, NoteType, QuestionClassification, QuestionStatus
from .ids import NoteID
from .source import SourceMetadata


class Link(BaseModel):
    target_id: NoteID
    edge_type: str  # e.g. "supports", "refutes", "cites", "perspective_of"
    context: str | None = None


# --- Per-type metadata payloads ---------------------------------------------


class LandscapeMetadata(BaseModel):
    type: Literal[NoteType.LANDSCAPE] = NoteType.LANDSCAPE
    raw_query: str


class SourceNoteMetadata(SourceMetadata):
    """Source metadata with the discriminator tag."""

    type: Literal[NoteType.SOURCE] = NoteType.SOURCE


class QuestionMetadata(BaseModel):
    type: Literal[NoteType.QUESTION] = NoteType.QUESTION
    classification: QuestionClassification
    adopted_position: str | None = None
    status: QuestionStatus = QuestionStatus.OPEN

    # Tree structure: None for the root question (the user's original query),
    # otherwise the id of the question this one was spawned from.
    parent_question_id: NoteID | None = None

    # Populated when an analyst answers the question via answer_question.
    # Kept here (on the question note) rather than on a separate synthesis
    # note so a question's lifecycle and answer live in one place.
    report_markdown: str | None = None
    confidence: ConfidenceLevel | None = None
    sources_cited: list[NoteID] = Field(default_factory=list)
    disagreements: list[str] = Field(default_factory=list)
    open_issues: list[str] = Field(default_factory=list)

    # Which analyst agent_id last updated this. Useful for the event UI
    # and for the researcher to tell "did I already dispatch on this?".
    answered_by_agent_id: str | None = None


class SynthesisMetadata(BaseModel):
    type: Literal[NoteType.SYNTHESIS] = NoteType.SYNTHESIS
    pattern: str  # OrchestrationPattern value


NoteMetadata = Annotated[
    LandscapeMetadata | SourceNoteMetadata | QuestionMetadata | SynthesisMetadata,
    Field(discriminator="type"),
]


# --- Note proper ------------------------------------------------------------


class Note(BaseModel):
    id: NoteID
    type: NoteType
    title: str
    description: str = ""
    content: str = ""
    links: list[Link] = Field(default_factory=list)
    metadata: NoteMetadata
    version: int = 1
    last_modified_at: datetime
    created_at: datetime
