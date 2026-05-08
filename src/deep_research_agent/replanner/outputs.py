"""Output types for the bounded replanner.

The replanner's LLM returns a ReplanDecision that the scheduler
translates into concrete task/note mutations. Actions are a
discriminated union so the scheduler can match per-action-type without
re-parsing fields.

v3 step 1 scope: SpawnSubQuestion + NoOp. AbandonTask and
EscalatePattern land with cascade semantics (step 2) and the
multi_perspective / debate patterns (step 3+).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SpawnSubQuestion(BaseModel):
    """Add a new sub-question under the root decomposition.

    The scheduler will create a question_note, spawn a
    QUESTION_SYNTHESIZE task reading it, and add a dep edge onto the
    existing WRITE_REPORT so the report waits for the new synthesis.
    """

    action: Literal["spawn_subquestion"] = "spawn_subquestion"
    title: str = Field(..., description="Sub-question title. Must end with '?'.")
    description: str = Field(
        ..., description="1-2 sentences on what this sub-question needs to answer."
    )
    classification: Literal["lookup", "synthesis", "contested", "sparse"] = Field(
        ...,
        description=(
            "Same classifications as the decomposer. Informs later pattern "
            "selection (contested → multi_perspective, sparse → additional search)."
        ),
    )
    rationale: str = Field(
        ..., description="Why this sub-question is worth adding — tie to a visible gap."
    )


class AbandonSubQuestion(BaseModel):
    """Close out a sub-question that is not productive.

    Per ADR 0009: in-progress tasks on the sub-question complete but
    their outputs go to an archive decision_note; PENDING descendants
    are marked ABANDONED; dep edges from downstream tasks (e.g.
    WRITE_REPORT) pointing at those descendants are dropped so the
    run doesn't deadlock.

    Use sparingly — budget is scarce and abandoning work is a high-cost
    decision. Prefer spawn_subquestion to complement thin coverage over
    abandon_subquestion to remove it.
    """

    action: Literal["abandon_subquestion"] = "abandon_subquestion"
    question_note_id: str = Field(..., description="ID of the question_note to abandon.")
    rationale: str = Field(
        ...,
        description=(
            "Why this sub-question isn't productive. Cite a specific signal: "
            "off-topic sources dominating, synthesis abstaining, or landscape "
            "mis-classification."
        ),
    )


class EscalatePattern(BaseModel):
    """Re-run a sub-question under a heavier orchestration pattern.

    Use when single_researcher's synthesis has surviving dissent that
    wasn't adequately engaged — multi_perspective runs three framings
    (neutral/skeptic/advocate) over the same sources so disagreement
    surfaces in the claim stream.

    Scope for v3: only multi_perspective is supported. debate and ach
    land in subsequent steps.
    """

    action: Literal["escalate_pattern"] = "escalate_pattern"
    question_note_id: str = Field(..., description="The question_note to re-run.")
    target_pattern: Literal["multi_perspective"] = Field(
        "multi_perspective",
        description=(
            "Pattern to escalate to. Only multi_perspective is supported "
            "currently; debate / ach land in later steps."
        ),
    )
    rationale: str = Field(
        ...,
        description=(
            "Why single_researcher was insufficient — cite surviving dissent "
            "or thin engagement on a contested angle."
        ),
    )


class NoOp(BaseModel):
    """Skip this replan cycle with a stated reason."""

    action: Literal["no_op"] = "no_op"
    rationale: str = Field(..., description="Why no changes are warranted.")


ReplanAction = SpawnSubQuestion | AbandonSubQuestion | EscalatePattern | NoOp


class ReplanDecision(BaseModel):
    """The replanner's structured verdict for one cycle."""

    overall_rationale: str = Field(
        ...,
        description="1-2 sentences summarizing what you see in the current graph.",
    )
    actions: list[ReplanAction] = Field(
        default_factory=list,
        max_length=3,
        description=(
            "Mutations to apply. Keep to at most 3 per cycle. Prefer fewer, "
            "higher-signal actions over many speculative ones. Empty list is "
            "allowed and equivalent to [NoOp]."
        ),
    )
