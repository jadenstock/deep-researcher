"""Source-note internals.

Sources live in a shared corpus across all sub-questions. A source enters
the corpus as SCOUTED (URL + title + snippet only), gets promoted to
FETCHED when its content is pulled and tiered, then accumulates claims
as analysts read it for one or more questions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .._time import utc_now
from .enums import ClaimType, SourceState, Tier, VerificationStatus

# Classification of how much of a source we actually retrieved. Set by
# scout_fetch after extraction.
#   full_text     - substantive body text (paper HTML render, long article)
#   abstract_only - short content only (arXiv abs page, DOI landing stub,
#                   paywall preview). Analyst should treat it as a summary.
#   unavailable   - fetch failed entirely (paywall block, 404, parse fail).
ContentKind = Literal["full_text", "abstract_only", "unavailable"]


class ClaimItem(BaseModel):
    """A verbatim-quoted claim extracted from a source."""

    id: str
    text: str
    quote: str = Field(..., min_length=1)
    page_or_section: str | None = None
    extractor_confidence: float = Field(..., ge=0.0, le=1.0)
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    claim_type: ClaimType = ClaimType.EXTERNAL
    # Question(s) this claim was extracted in service of. The synthesizer
    # filters claims by question_id; a later pass on a different lens may
    # append another question_id rather than duplicating the claim.
    for_questions: list[str] = Field(default_factory=list)


class ReadingEntry(BaseModel):
    """One analyst's reading of a source, append-only on the source note.

    Two analysts investigating different sub-questions can both read the
    same URL and each append their own ReadingEntry. Neither overwrites
    the other; the source note accumulates a stack of per-perspective
    extractions keyed by `for_question_id` + `by_agent_id`.
    """

    by_agent_id: str
    for_question_id: str  # NoteID of the question this reading was done for
    read_at: datetime = Field(default_factory=utc_now)
    claims: list[ClaimItem] = Field(default_factory=list)
    relevance_note: str = ""


class SourceMetadata(BaseModel):
    """Metadata payload on a source_note.

    Attached to a Note of type SOURCE via the discriminated metadata union
    in schemas.note. Tier-related fields are optional because sources enter
    the corpus as SCOUTED (no classification yet) and only get tiered when
    their content is fetched.
    """

    url: str
    title: str
    authors: list[str] = Field(default_factory=list)
    venue: str | None = None
    year: int | None = None
    # Persistent identifiers, populated when search hit supplied them.
    # `doi` feeds S2 citation/reference traversal; `pdf_url` is the
    # fallback URL tried by scout_fetch when the HTML render comes back
    # abstract-only (arxiv.org/abs redirect, DOI landing stub, etc.).
    doi: str | None = None
    pdf_url: str | None = None
    # Populated by scout_fetch after extraction - tells analysts whether
    # they have full body text or just an abstract/preview on this note.
    content_kind: ContentKind | None = None
    state: SourceState = SourceState.SCOUTED
    # tier/peer_reviewed are unset until the source is fetched and the
    # scout classifies it.
    tier: Tier | None = None
    tier_rationale: str = ""
    peer_reviewed: bool = False
    citation_count: int | None = None
    summary: str | None = None
    topics: list[str] = Field(
        default_factory=list,
        description=(
            "Cheap topic labels assigned at scout time (e.g. "
            "['benchmarks', 'evaluation-methodology']). Analysts and "
            "researcher use this for clustering / corpus overview."
        ),
    )
    # Per-reading extractions - append-only. Each analyst that reads this
    # source for a sub-question appends a ReadingEntry with its own claims
    # and relevance_note.
    readings: list[ReadingEntry] = Field(default_factory=list)
