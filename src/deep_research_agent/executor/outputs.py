"""Pydantic output types for LLM agents used by v0 handlers.

Defined here rather than inline so handlers stay readable and the
output shapes can be reused across patterns in later milestones.
"""

from __future__ import annotations

from typing import Literal

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


class VerifierOutput(BaseModel):
    """Output from an independent verifier checking a claim."""

    verdict: Literal["SUPPORTS", "REFUTES", "INCONCLUSIVE"] = Field(
        ...,
        description=(
            "SUPPORTS if independent sources corroborate the claim. "
            "REFUTES if they contradict it (>=2 sources or 1 high-quality source). "
            "INCONCLUSIVE if the evidence is mixed or too thin to call."
        ),
    )
    rationale: str = Field(
        ...,
        description=(
            "2-4 sentences explaining the verdict, citing the specific "
            "independent sources you relied on."
        ),
    )
    disagreement_notes: list[str] = Field(
        default_factory=list,
        description="Specific points where independent sources disagree with the claim.",
    )


# --- ACH (Analysis of Competing Hypotheses) outputs -----------------------


class AchHypothesis(BaseModel):
    """One competing hypothesis in the ACH analysis."""

    label: str = Field(..., description="Short label (1-4 words) for the matrix.")
    text: str = Field(..., description="Full hypothesis as a complete, evaluable sentence.")


class AchHypothesisGenOutput(BaseModel):
    hypotheses: list[AchHypothesis] = Field(
        ..., min_length=2, max_length=5, description="2-5 mutually-exclusive hypotheses."
    )


class AchConsistencyVerdict(BaseModel):
    source_id: str = Field(..., description="The source_note.id under evaluation.")
    verdict: Literal["consistent", "inconsistent", "neutral"] = Field(
        ...,
        description=(
            "consistent: source corroborates the hypothesis. "
            "inconsistent: source contradicts it. "
            "neutral: source doesn't bear on the hypothesis."
        ),
    )
    rationale: str = Field(
        ...,
        description="1-2 sentences citing the specific claim/quote that drove the verdict.",
    )


class AchConsistencyOutput(BaseModel):
    verdicts: list[AchConsistencyVerdict] = Field(
        ...,
        description="One verdict per source_note evaluated against this hypothesis.",
    )


class AchAdjudicationOutput(BaseModel):
    adopted_label: str = Field(
        ...,
        description="Label of the tentatively adopted hypothesis.",
    )
    bottom_line: str = Field(..., description="One-sentence answer to the question.")
    synthesis: str = Field(
        ...,
        description=(
            "2-4 paragraphs: per-hypothesis inconsistency count with key inconsistent "
            "sources, then why the adopted hypothesis survives."
        ),
    )
    disagreements: list[str] = Field(
        default_factory=list,
        description="Sources where the adopted hypothesis has an inconsistency.",
    )
    confidence_note: str = Field(
        default="",
        description="One sentence on how close the call was.",
    )


class ThemeHint(BaseModel):
    """A theme the landscape surveyor spots across the snippets."""

    name: str = Field(..., description="Short name (1-4 words) for this theme / cluster.")
    description: str = Field(
        ..., description="1-2 sentences describing what sits under this theme."
    )


class PositionHint(BaseModel):
    """A stance or distinct position the snippets appear to take."""

    label: str = Field(..., description="Short label for the position (e.g. 'reasoning-genuine').")
    description: str = Field(
        ..., description="1-2 sentences on what this position claims or who holds it."
    )


class LandscapeOutput(BaseModel):
    """Structured output from the LANDSCAPE_SURVEY agent."""

    summary: str = Field(..., description="One-sentence summary of the landscape.")
    discussion: str = Field(
        ...,
        description=(
            "2-3 paragraph description of what's visible in the snippets: "
            "dominant framings, apparent consensus/dispute, evidence density."
        ),
    )
    themes: list[ThemeHint] = Field(
        default_factory=list,
        description="Named theme clusters present in the landscape.",
    )
    positions: list[PositionHint] = Field(
        default_factory=list,
        description=(
            "Distinct stances visible in the snippets. If only one framing appears, "
            "return a single-element list; if the question is contested across the "
            "snippets, list two or more."
        ),
    )
    under_covered_areas: list[str] = Field(
        default_factory=list,
        description="Aspects of the query the snippets do not seem to address.",
    )


class AIMSSpec(BaseModel):
    """Analytic Pyramid scoping for the research."""

    audience: str = Field(..., description="Who is this research for?")
    issue: str = Field(..., description="What specific problem is this query addressing?")
    message: str = Field(
        ..., description="What's the bottom-line judgment this research must produce?"
    )
    storyline: str = Field(
        ..., description="What logical sequence takes a reader from evidence to conclusion?"
    )


class SubQuestionSpec(BaseModel):
    title: str = Field(..., description="Concise title of the sub-question (one sentence).")
    description: str = Field(
        ..., description="1-2 sentences elaborating what the sub-question needs to answer."
    )
    classification: Literal["lookup", "synthesis", "contested", "sparse"] = Field(
        ...,
        description=(
            "lookup: single retrieval suffices. synthesis: multiple sources agree. "
            "contested: landscape shows 2+ distinct positions. sparse: evidence thin."
        ),
    )


class DecomposeOutput(BaseModel):
    aims: AIMSSpec
    sub_questions: list[SubQuestionSpec] = Field(
        ...,
        min_length=1,
        max_length=7,
        description=(
            "1-6 sub-questions. Bias toward 3-6 for non-trivial queries; "
            "recall beats parsimony for research. Single sub-question only "
            "when the query is genuinely narrow."
        ),
    )
