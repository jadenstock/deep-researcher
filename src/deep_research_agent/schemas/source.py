"""Source-note internals (TDD §4.4)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .enums import Methodology, Reproducibility, Tier, VerificationStatus


class StructuredContent(BaseModel):
    """Section-level view of a long source.

    Present only when the raw converted markdown is ≥ 8K tokens. Short sources
    bypass this and the analyzer reads the full content directly.
    """

    title: str
    abstract: str | None = None
    section_headers: list[str] = Field(default_factory=list)
    first_paragraph_of_each_section: dict[str, str] = Field(default_factory=dict)
    table_of_contents: list[str] = Field(default_factory=list)
    figure_captions: list[str] = Field(default_factory=list)


class ClaimItem(BaseModel):
    """A verbatim-quoted claim extracted from a source."""

    id: str
    text: str
    quote: str = Field(..., min_length=1)  # invariant: every claim has a non-empty quote
    page_or_section: str | None = None
    extractor_confidence: float = Field(..., ge=0.0, le=1.0)
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED


class EvalItem(BaseModel):
    methodology: Methodology
    sample_size: int | None = None
    reproducibility: Reproducibility = Reproducibility.UNKNOWN
    limitations_noted_by_authors: list[str] = Field(default_factory=list)
    agent_skepticism: str


class SourceMetadata(BaseModel):
    """Metadata payload on a source_note.

    Attached to a Note of type SOURCE via the discriminated metadata union
    in schemas.note.
    """

    url: str
    title: str
    authors: list[str] = Field(default_factory=list)
    venue: str | None = None
    year: int | None = None
    tier: Tier
    tier_rationale: str = Field(..., min_length=1)
    classifier_confidence: float = Field(..., ge=0.0, le=1.0)
    peer_reviewed: bool  # deterministic; independent of tier
    citation_count: int | None = None
    raw_content_ref: str | None = None  # path to on-disk cached full content
    structured_content: StructuredContent | None = None
    summary: str | None = None
    landscape_contribution: str | None = None  # survey-only; one-line "what this adds"
    claims: list[ClaimItem] = Field(default_factory=list)  # populated on analyzer upgrade
    evaluation: EvalItem | None = None  # populated on analyzer upgrade
