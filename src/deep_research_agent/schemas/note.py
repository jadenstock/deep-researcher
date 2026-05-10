"""Note graph models (TDD §4.2 + §4.4).

Note is the only long-term memory. Every note has a typed metadata payload
discriminated by `type`. Links are typed edges between notes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from .enums import NoteType, QuestionClassification
from .ids import NoteID, SourceID, TaskID
from .source import SourceMetadata


class Link(BaseModel):
    target_id: NoteID
    edge_type: str  # e.g. "supports", "refutes", "cites", "perspective_of"
    context: str | None = None


# --- Per-type metadata payloads ---------------------------------------------


class ThemeItem(BaseModel):
    name: str
    description: str
    sources: list[SourceID] = Field(default_factory=list)


class PositionItem(BaseModel):
    label: str
    description: str
    supporting_sources: list[SourceID] = Field(default_factory=list)


class LandscapeMetadata(BaseModel):
    type: Literal[NoteType.LANDSCAPE] = NoteType.LANDSCAPE
    themes: list[ThemeItem] = Field(default_factory=list)
    positions: list[PositionItem] = Field(default_factory=list)
    key_sources: list[SourceID] = Field(default_factory=list)
    under_covered_areas: list[str] = Field(default_factory=list)
    methodology_distribution: dict[str, float] = Field(default_factory=dict)
    tier_distribution: dict[int, int] = Field(default_factory=dict)
    peer_review_fraction: float = 0.0
    raw_query: str


class SourceNoteMetadata(SourceMetadata):
    """Source metadata with the discriminator tag."""

    type: Literal[NoteType.SOURCE] = NoteType.SOURCE


class QuestionMetadata(BaseModel):
    type: Literal[NoteType.QUESTION] = NoteType.QUESTION
    classification: QuestionClassification
    adopted_position: str | None = None
    status: Literal["OPEN", "IN_PROGRESS", "SYNTHESIZED"] = "OPEN"


class SynthesisMetadata(BaseModel):
    type: Literal[NoteType.SYNTHESIS] = NoteType.SYNTHESIS
    pattern: str  # OrchestrationPattern value
    surviving_dissent: list[str] = Field(default_factory=list)
    linchpin_evidence: list[SourceID] = Field(default_factory=list)
    # Triangulation: how many distinct sources carried claims that
    # feed this synthesis. A cheap proxy for independent corroboration
    # - the validator reads this alongside the synthesis text when
    # auditing gate 6 (triangulation adequacy).
    triangulation_score: int = 0
    # Distinct tiers the contributing sources span (1..5). Wider
    # spread = sturdier triangulation even if count is modest.
    distinct_tiers: int = 0


class DecisionMetadata(BaseModel):
    type: Literal[NoteType.DECISION] = NoteType.DECISION
    category: str  # e.g. "aims_scoping", "replan_cycle", "cascade_mutation"
    rationale: str
    relates_to_task: TaskID | None = None


class OpenQuestionMetadata(BaseModel):
    type: Literal[NoteType.OPEN_QUESTION] = NoteType.OPEN_QUESTION
    reason_excluded: str  # e.g. "scope_creep_narrow_choice", "out_of_scope"


class HypothesisMetadata(BaseModel):
    type: Literal[NoteType.HYPOTHESIS] = NoteType.HYPOTHESIS
    hypothesis_text: str
    inconsistency_score: float | None = None
    supporting_evidence: list[SourceID] = Field(default_factory=list)
    inconsistent_evidence: list[SourceID] = Field(default_factory=list)
    neutral_evidence: list[SourceID] = Field(default_factory=list)
    tentatively_adopted: bool = False


NoteMetadata = Annotated[
    LandscapeMetadata
    | SourceNoteMetadata
    | QuestionMetadata
    | SynthesisMetadata
    | DecisionMetadata
    | OpenQuestionMetadata
    | HypothesisMetadata,
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
    last_modified_by: TaskID | None = None
    last_modified_at: datetime
    created_by: TaskID | None = None
    created_at: datetime
