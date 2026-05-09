"""maker_checker pattern — claim selection + VERIFY_CLAIM emission.

After `QUESTION_SYNTHESIZE` produces a synthesis backed by claims
extracted across multiple source_notes, `maker_checker` picks the claims
worth independent verification and emits one `VERIFY_CLAIM` task per
claim. The verifier runs on the judgment role with a different model
family (ADR 0008), fetches its own independent sources, and returns a
SUPPORTS / REFUTES / INCONCLUSIVE verdict that updates the claim's
`verification_status` in place.

v2a scope (per design/phase-1-initial-design/10-implementation-plan.md):
- Simple claim selection: top N per synthesis by `extractor_confidence`,
  capped globally so a single question doesn't blow the cost budget.
- Full per-claim tier filtering + contested/sparse prioritization
  lands with v2b (once the LLM tier classifier exists).
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..scheduler.ids import new_task_id
from ..schemas import DepScope, Note, Task
from ..schemas.enums import (
    ClaimType,
    OrchestrationPattern,
    QuestionRound,
    RoleClass,
    TaskTier,
    TaskType,
)
from ..schemas.ids import TaskID
from ..schemas.source import ClaimItem

# Legacy fallbacks retained for callers that don't pass a config. The
# real defaults live in config.VerificationConfig.
DEFAULT_MAX_CLAIMS_PER_SYNTHESIS = 2
DEFAULT_MAX_CLAIMS_PER_RUN = 10


def select_claims_to_verify(
    source_notes: list[Note],
    already_selected: int = 0,
    *,
    max_per_synthesis: int = DEFAULT_MAX_CLAIMS_PER_SYNTHESIS,
    max_per_run: int = DEFAULT_MAX_CLAIMS_PER_RUN,
    skip_novel: bool = True,
) -> list[tuple[Note, ClaimItem]]:
    """Pick (source_note, claim) pairs worth independent verification.

    Filters:
    - Claims with empty quotes are excluded.
    - When `skip_novel` is true, claims tagged NOVEL_TO_SOURCE are
      excluded — they're about something invented / measured only in the
      source (e.g. "our proposed benchmark contains 1000 examples") so
      independent corroboration is structurally impossible.

    Returns remaining claims sorted by extractor_confidence descending,
    capped at `max_per_synthesis` for this call and `max_per_run` minus
    `already_selected` for the run overall.
    """
    candidates: list[tuple[Note, ClaimItem]] = []
    for note in source_notes:
        claims = getattr(note.metadata, "claims", None) or []
        for claim in claims:
            if not claim.quote.strip():
                continue
            if skip_novel and claim.claim_type == ClaimType.NOVEL_TO_SOURCE:
                continue
            candidates.append((note, claim))
    candidates.sort(key=lambda pair: pair[1].extractor_confidence, reverse=True)
    budget = max(0, max_per_run - already_selected)
    return candidates[: min(max_per_synthesis, budget)]


def emit_verify_claim(
    claim: ClaimItem,
    source_note: Note,
    question: str,
    write_report_task_id: TaskID | None,
    parent_task_id: TaskID,
) -> Task:
    """Emit a VERIFY_CLAIM task for one claim.

    The claim_id + source_note_id travel via `input_refs` so the
    executor can resolve the analyzer's family for the cross-family
    invariant without parsing `goal`. `write_report_task_id` is
    threaded through so the caller can graft this task onto the
    report's deps.
    """
    input_refs: dict[str, str] = {
        "claim_id": claim.id,
        "source_note_id": source_note.id,
        "question": question,
    }
    if write_report_task_id is not None:
        input_refs["write_report_task_id"] = write_report_task_id
    return Task(
        id=new_task_id(),
        parent_id=parent_task_id,
        goal=claim.text,
        type=TaskType.VERIFY_CLAIM,
        role=RoleClass.JUDGMENT,
        tier=TaskTier.MID,
        pattern=OrchestrationPattern.MAKER_CHECKER,
        question_round=QuestionRound.FALSIFICATION,
        reads_notes=[source_note.id],
        input_refs=input_refs,
        dep_scope=DepScope(retrieval_ignores=False, synthesis_waits=True),
        success_criteria="return SUPPORTS / REFUTES / INCONCLUSIVE verdict with rationale",
        created_at=datetime.now(UTC),
    )
