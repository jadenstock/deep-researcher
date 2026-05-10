"""Source-note internals (TDD §4.4).

Sources live in a shared corpus across all sub-questions. A source enters
the corpus as SCOUTED (URL + title + snippet only) from a SCOUT_SOURCES
task, gets promoted to FETCHED when its content is pulled and tiered,
then accumulates claims as ANALYZE_SOURCE runs against it for one or more
questions. `analyzed_for` tracks which questions have already consumed
the source so analysis isn't repeated; `relevance` holds the
(question_id → score) map from the batch relevance scorer and drives
which questions get their own ANALYZE_SOURCE spawned against this source.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .enums import (
    ClaimType,
    Methodology,
    Reproducibility,
    SourceState,
    Tier,
    VerificationStatus,
)


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
    """A verbatim-quoted claim extracted from a source.

    A single claim is extracted in service of one or more questions
    (via `for_questions`) - the same source may yield different claims
    when analyzed against different question lenses. The synthesizer
    filters claims by question_id before composing its digest.
    """

    id: str
    text: str
    quote: str = Field(..., min_length=1)  # invariant: every claim has a non-empty quote
    page_or_section: str | None = None
    extractor_confidence: float = Field(..., ge=0.0, le=1.0)
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    # Family of the model that extracted this claim (e.g. "anthropic", "openai").
    # Populated by the analyzer and consumed by the executor's ADR 0008
    # cross-family invariant - VERIFY_CLAIM must route to a different family.
    analyzed_by_family: str | None = None
    # Framing the analyzer used for this extraction - "neutral" under the
    # default single_researcher pattern, or one of the multi_perspective
    # framings (e.g. "skeptic", "advocate").
    perspective: str = "neutral"
    # Populated by VERIFY_CLAIM when the claim is checked.
    verification_rationale: str | None = None
    verification_note_id: str | None = None
    # LLMs the source evaluates this claim on (verbatim from the source).
    models_tested: list[str] = Field(default_factory=list)
    # Taxonomy used to triage verification (see ClaimType). EXTERNAL is the
    # safe default - claims of unknown type shouldn't silently be excluded
    # from verify; the analyzer stamps the real type when it can.
    claim_type: ClaimType = ClaimType.EXTERNAL
    # Question(s) this claim was extracted in service of. One claim often
    # belongs to just one question, but the synthesizer may pull the same
    # claim across multiple questions if a later ANALYZE_SOURCE pass on a
    # different lens finds it continues to apply; we append rather than
    # duplicate the ClaimItem.
    for_questions: list[str] = Field(default_factory=list)


class EvalItem(BaseModel):
    methodology: Methodology
    sample_size: int | None = None
    reproducibility: Reproducibility = Reproducibility.UNKNOWN
    limitations_noted_by_authors: list[str] = Field(default_factory=list)
    agent_skepticism: str


class SourceMetadata(BaseModel):
    """Metadata payload on a source_note.

    Attached to a Note of type SOURCE via the discriminated metadata union
    in schemas.note. Tier-related fields are optional because sources enter
    the corpus as SCOUTED (no classification yet) and only get tiered when
    FETCH_AND_EXTRACT promotes them to FETCHED.
    """

    url: str
    title: str
    authors: list[str] = Field(default_factory=list)
    venue: str | None = None
    year: int | None = None
    # Lifecycle state in the shared corpus. Handlers consume this to gate
    # work: FETCH_AND_EXTRACT only runs on SCOUTED; ANALYZE_SOURCE only on
    # FETCHED/ANALYZED; SYNTHESIZE only reads ANALYZED sources with claims
    # tagged for its question.
    state: SourceState = SourceState.SCOUTED
    # tier/confidence/peer_reviewed are None/defaults until the source is
    # FETCHED - the tier classifier runs during FETCH_AND_EXTRACT.
    tier: Tier | None = None
    tier_rationale: str = ""
    classifier_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    peer_reviewed: bool = False
    citation_count: int | None = None
    raw_content_ref: str | None = None  # path to on-disk cached full content
    structured_content: StructuredContent | None = None
    summary: str | None = None
    landscape_contribution: str | None = None  # survey-only; one-line "what this adds"
    claims: list[ClaimItem] = Field(default_factory=list)  # populated on analyzer upgrade
    evaluation: EvalItem | None = None  # populated on analyzer upgrade
    # Shared-corpus fields. `relevance` maps question_id → 0..1 score from
    # the batch relevance scorer and determines which questions get their
    # own ANALYZE_SOURCE spawned against this source. `analyzed_for` records
    # questions already analyzed so analysis isn't repeated. `discovered_by`
    # captures the scout strategy / task so we can attribute coverage.
    relevance: dict[str, float] = Field(default_factory=dict)
    analyzed_for: list[str] = Field(default_factory=list)
    discovered_by: str | None = None
    # Strategy label from retrieval/scout.py - "direct", "contrarian",
    # "technical", "time_bounded", "venue", "landscape_seed", "verify_seed",
    # etc. Useful for post-hoc coverage analysis.
    scout_strategy: str | None = None
