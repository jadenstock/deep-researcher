"""Pydantic output types for LLM agents used by v0 handlers.

Defined here rather than inline so handlers stay readable and the
output shapes can be reused across patterns in later milestones.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AnalyzedClaim(BaseModel):
    """One claim extracted from a single source."""

    text: str = Field(..., description="Paraphrased claim, one sentence.")
    quote: str = Field(
        ...,
        min_length=1,
        description=(
            "Verbatim passage from the source that supports the claim. "
            "Must be a direct copy, not a paraphrase."
        ),
    )
    extractor_confidence: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="0..1 confidence that the quote supports the claim.",
    )


class AnalyzerOutput(BaseModel):
    claims: list[AnalyzedClaim] = Field(
        default_factory=list,
        description=(
            "Up to 3 claims from this source that bear on the question. " "Empty if irrelevant."
        ),
    )
    off_topic: bool = Field(
        default=False, description="True if the source did not address the question at all."
    )


class SynthesizerOutput(BaseModel):
    bottom_line: str = Field(..., description="One-sentence direct answer to the question.")
    synthesis: str = Field(
        ...,
        description=(
            "Multi-paragraph synthesis integrating the evidence. Reference source "
            "titles or URLs inline when making a claim."
        ),
    )
    disagreements: list[str] = Field(
        default_factory=list,
        description="Points where the sources materially disagree with each other.",
    )
    confidence_note: str = Field(
        default="",
        description="One sentence on how much the available evidence supports the bottom line.",
    )


class ReportOutput(BaseModel):
    markdown: str = Field(
        ...,
        description="Complete research report in markdown, ready to save to disk.",
    )
