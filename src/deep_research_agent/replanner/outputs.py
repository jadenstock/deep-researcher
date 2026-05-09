"""Output types for the bounded replanner.

Mid-run the replanner is the dynamic-coverage engine: it can add more
scouting, promote specific sources, trigger synthesis when a question is
saturated, and the original four levers (spawn / abandon / escalate /
no_op). The scheduler translates a ReplanDecision into concrete
task/note mutations through `_apply_*` in replanner.py.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SpawnSubQuestion(BaseModel):
    """Add a new sub-question under the root decomposition.

    The scheduler will create a question_note, spawn a
    QUESTION_SYNTHESIZE task reading it + a per-question SCOUT_SOURCES
    task, and add a dep edge onto the termination gate so CHECK only
    runs once the new question has synthesized.
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

    PENDING descendants are marked ABANDONED; dep edges from downstream
    tasks pointing at those descendants are dropped so the run doesn't
    deadlock. Use sparingly — budget is scarce; prefer spawn_subquestion
    to complement thin coverage over abandon to remove it.
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

    Spawns ANALYZE_SOURCE tasks with the new pattern against the top
    existing analyzed sources for this question, then a QUESTION_SYNTHESIZE
    with the corresponding synthesizer mode. Original synthesis stays —
    the report writer sees both.
    """

    action: Literal["escalate_pattern"] = "escalate_pattern"
    question_note_id: str = Field(..., description="The question_note to re-run.")
    target_pattern: Literal["multi_perspective", "debate", "ach"] = Field(
        ...,
        description=(
            "multi_perspective: three framings (neutral/skeptic/advocate). "
            "debate: two framings + judge synthesizer. "
            "ach: enumerate + adjudicate hypotheses."
        ),
    )
    rationale: str = Field(
        ...,
        description=(
            "Why single_researcher was insufficient — cite surviving dissent "
            "or thin engagement on a contested angle."
        ),
    )


class SpawnScoutBurst(BaseModel):
    """Widen coverage on an under-covered question (or topic).

    Emits a new SCOUT_SOURCES task that runs the standard per-question
    reformulation bundle (direct / evidence / review). Use when a
    question's analyzed-source count is low AND no retrieval is pending
    (corpus has saturated on a thin evidence base).
    """

    action: Literal["spawn_scout_burst"] = "spawn_scout_burst"
    question_note_id: str = Field(
        ...,
        description=(
            "The question_note this scout burst serves. The topic of the "
            "scout task defaults to the question's title."
        ),
    )
    rationale: str = Field(
        ...,
        description=(
            "Cite the specific coverage gap — e.g. 'only 2 fetched sources "
            "at tier ≤ 3 for this question, and no scout is in flight'."
        ),
    )


class PromoteSource(BaseModel):
    """Force ANALYZE_SOURCE for a specific (source, question) pair.

    Use when a high-tier source is in the corpus but scored below the
    analyze threshold for a specific question — the relevance scorer
    was too conservative. Rare; mostly a safety valve.
    """

    action: Literal["promote_source"] = "promote_source"
    source_note_id: str = Field(..., description="The source_note to analyze.")
    question_note_id: str = Field(..., description="The question to analyze it for.")
    rationale: str = Field(..., description="Why this source should be analyzed.")


class TriggerSynthesis(BaseModel):
    """Force a question's synthesis NOW regardless of the readiness gate.

    Use when the replanner decides this question has diminishing returns
    on further retrieval (e.g. contested with no new evidence surfacing)
    or when the run is approaching budget. Spawns a fresh QS with
    poll_count=MAX_QS_POLLS so the readiness gate auto-passes on the
    `polls_exhausted` branch.
    """

    action: Literal["trigger_synthesis"] = "trigger_synthesis"
    question_note_id: str = Field(..., description="Which question to synthesize.")
    rationale: str = Field(
        ..., description="Why the gate should be skipped — cite a specific reason."
    )


class NoOp(BaseModel):
    """Skip this replan cycle with a stated reason."""

    action: Literal["no_op"] = "no_op"
    rationale: str = Field(..., description="Why no changes are warranted.")


ReplanAction = (
    SpawnSubQuestion
    | AbandonSubQuestion
    | EscalatePattern
    | SpawnScoutBurst
    | PromoteSource
    | TriggerSynthesis
    | NoOp
)


class ReplanDecision(BaseModel):
    """The replanner's structured verdict for one cycle."""

    overall_rationale: str = Field(
        ...,
        description="1-2 sentences summarizing what you see in the current graph.",
    )
    actions: list[ReplanAction] = Field(
        default_factory=list,
        max_length=4,
        description=(
            "Mutations to apply. Keep to at most 4 per cycle. Prefer fewer, "
            "higher-signal actions over many speculative ones. Empty list is "
            "allowed and equivalent to [NoOp]."
        ),
    )
