"""Bounded replanner — periodic LLM-driven course correction.

Invoked by the scheduler between ticks after every `replan_cadence`
task completions, up to `replan_budget` cycles per run. Reads a
snapshot of the graph, asks an LLM what to do, and returns a set of
task-graph / note-graph mutations that the scheduler applies under its
write lock.

In the streaming pipeline the replanner is the dynamic-coverage engine
as well as the bounded course-corrector. Levers:
- SpawnSubQuestion    — add a new question; spawns scout + QS.
- AbandonSubQuestion  — cascade abandon tasks under a question.
- EscalatePattern     — re-analyze + re-synthesize under a heavier pattern.
- SpawnScoutBurst     — widen coverage on an under-covered question.
- PromoteSource       — force ANALYZE_SOURCE for a (source, question) pair.
- TriggerSynthesis    — bypass the readiness gate for a question.
- NoOp                — record a decision_note and move on.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from pydantic_ai import Agent

from ..agent_factory import make_model
from ..config import LocalConfig, RoutingConfig
from ..patterns.single_researcher import (
    emit_analyze_source,
    emit_question_synthesize,
    emit_scout_sources,
)
from ..scheduler import DepEdgeAdd, NoteMutation, TaskResult
from ..scheduler.ids import new_note_id
from ..scheduler.note_graph import NoteGraph
from ..scheduler.task_graph import TaskGraph

if TYPE_CHECKING:
    from ..token_usage import TokenUsageTracker
from ..schemas import DecisionMetadata, Link, Note, NoteID, QuestionMetadata
from ..schemas.enums import (
    DependencyType,
    NoteType,
    OrchestrationPattern,
    QuestionClassification,
    RoleClass,
    SourceState,
    TaskStatus,
    TaskTier,
    TaskType,
)
from ..schemas.ids import TaskID
from ..schemas.note import SourceNoteMetadata
from .outputs import (
    AbandonSubQuestion,
    EscalatePattern,
    NoOp,
    PromoteSource,
    ReplanDecision,
    SpawnScoutBurst,
    SpawnSubQuestion,
    TriggerSynthesis,
)
from .prompts import REPLAN_SYSTEM

logger = logging.getLogger(__name__)

DEFAULT_CADENCE = 5
DEFAULT_BUDGET = 5


def _src_meta(note: Note) -> SourceNoteMetadata:
    return cast(SourceNoteMetadata, note.metadata)


def _now() -> datetime:
    return datetime.now(UTC)


def _format_graph_snapshot(task_graph: TaskGraph, note_graph: NoteGraph) -> str:
    """Compact human-readable snapshot for the replanner LLM.

    Shows the landscape, each sub-question's status + adopted position,
    coverage breakdown (total / analyzed / multi-question), and any
    surviving dissent. Keeps the snapshot small on purpose — the
    replanner uses this to pick levers, not to read every claim.
    """
    parts: list[str] = []

    question_notes = [n for n in note_graph.all() if n.type == NoteType.QUESTION]
    source_notes = [n for n in note_graph.all() if n.type == NoteType.SOURCE]
    landscape_notes = [n for n in note_graph.all() if n.type == NoteType.LANDSCAPE]

    if landscape_notes:
        ls = landscape_notes[0]
        parts.append(f"ROOT QUERY: {getattr(ls.metadata, 'raw_query', '(unknown)')}")
        parts.append("")
        parts.append("LANDSCAPE SUMMARY:")
        parts.append(f"  {ls.description}")
        under = getattr(ls.metadata, "under_covered_areas", []) or []
        if under:
            parts.append("  Under-covered areas surfaced by landscape:")
            for a in under:
                parts.append(f"    - {a}")
        parts.append("")

    # Coverage stats first — these drive the replanner's choice of levers.
    total = len(source_notes)
    by_state = {
        SourceState.SCOUTED: 0,
        SourceState.FETCHED: 0,
        SourceState.ANALYZED: 0,
    }
    multi_question = 0
    for sn in source_notes:
        meta = _src_meta(sn)
        if meta.state in by_state:
            by_state[meta.state] += 1
        if len(meta.analyzed_for) > 1:
            multi_question += 1
    parts.append("CORPUS COVERAGE:")
    parts.append(
        f"  total={total} scouted={by_state[SourceState.SCOUTED]} "
        f"fetched={by_state[SourceState.FETCHED]} "
        f"analyzed={by_state[SourceState.ANALYZED]} "
        f"multi_question={multi_question}"
    )
    parts.append("")

    # Per-question status with analyzed-source count (key signal for
    # SpawnScoutBurst / TriggerSynthesis decisions).
    synthesis_by_question: dict[str, Note] = {}
    for task in task_graph.all():
        if task.type != TaskType.QUESTION_SYNTHESIZE:
            continue
        if not task.reads_notes:
            continue
        q_id = task.reads_notes[0]
        for note in task.writes_notes:
            n = note_graph.get(note) if note in note_graph else None
            if n is not None and n.type == NoteType.SYNTHESIS:
                synthesis_by_question[q_id] = n

    parts.append(f"SUB-QUESTIONS ({len(question_notes)} total):")
    for q in question_notes:
        analyzed_count = sum(1 for sn in source_notes if q.id in _src_meta(sn).analyzed_for)
        parts.append(f"  Q[{q.id}]: {q.title} (analyzed_sources={analyzed_count})")
        s = synthesis_by_question.get(q.id)
        if s is not None:
            parts.append(f"    BLUF: {s.description}")
            disagreements = getattr(s.metadata, "surviving_dissent", []) or []
            if disagreements:
                parts.append("    Surviving dissent:")
                for d in disagreements[:3]:
                    parts.append(f"      - {d}")
        else:
            for task in task_graph.all():
                if task.type == TaskType.QUESTION_SYNTHESIZE and q.id in task.reads_notes:
                    poll = task.input_refs.get("poll_count", "0")
                    parts.append(
                        f"    (synthesis not yet complete — task status: "
                        f"{task.status.value}, poll_count={poll})"
                    )
                    break

    # In-flight retrieval + analysis — relevant for "is coverage still
    # growing" judgments.
    pending = {
        TaskType.SCOUT_SOURCES.value: 0,
        TaskType.FETCH_AND_EXTRACT.value: 0,
        TaskType.ANALYZE_SOURCE.value: 0,
        TaskType.RESCORE_RELEVANCE.value: 0,
    }
    for t in task_graph.all():
        if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING) and t.type.value in pending:
            pending[t.type.value] += 1
    parts.append("")
    parts.append("IN-FLIGHT RETRIEVAL: " + ", ".join(f"{k}={v}" for k, v in pending.items()))

    # Claim verification rollup (unchanged from earlier snapshots).
    verified_supports = 0
    verified_refutes = 0
    verified_inconclusive = 0
    for sn in source_notes:
        for c in _src_meta(sn).claims:
            v = c.verification_status.value if c.verification_status else ""
            if v == "SUPPORTS":
                verified_supports += 1
            elif v == "REFUTES":
                verified_refutes += 1
            elif v == "INCONCLUSIVE":
                verified_inconclusive += 1
    if verified_supports or verified_refutes or verified_inconclusive:
        parts.append(
            f"CLAIM VERIFICATIONS: {verified_supports} SUPPORTS, "
            f"{verified_refutes} REFUTES, {verified_inconclusive} INCONCLUSIVE"
        )

    return "\n".join(parts)


def _find_termination_task(task_graph: TaskGraph) -> TaskID | None:
    """Find the CHECK_TERMINATION_READY task (new: we graft onto the
    termination gate, not WRITE_REPORT — that way VERIFY / scout / ...
    all complete before the audit fires).
    """
    for t in task_graph.all():
        if t.type == TaskType.CHECK_TERMINATION_READY and t.status in {
            TaskStatus.PENDING,
            TaskStatus.BLOCKED_ON_SYNTHESIS_DEP,
        }:
            return t.id
    return None


# --- Action appliers ------------------------------------------------------


def _apply_spawn_subquestion(
    action: SpawnSubQuestion,
    task_graph: TaskGraph,
    parent_task_id: TaskID,
) -> TaskResult:
    q_note = Note(
        id=new_note_id("question"),
        type=NoteType.QUESTION,
        title=action.title,
        description=action.description,
        content=action.description,
        metadata=QuestionMetadata(
            classification=QuestionClassification(action.classification),
            status="OPEN",
        ),
        created_by=parent_task_id,
        created_at=_now(),
        last_modified_at=_now(),
    )

    termination_id = _find_termination_task(task_graph)
    scout = emit_scout_sources(
        goal=action.title,
        scout_mode="question",
        parent_task_id=parent_task_id,
        question_note_ids=[q_note.id],
    )
    qs_task = emit_question_synthesize(
        question_note_id=q_note.id,
        question=action.title,
        parent_task_id=parent_task_id,
        termination_task_id=termination_id,
    )

    added_deps: list[DepEdgeAdd] = []
    if termination_id is not None:
        added_deps.append(
            DepEdgeAdd(
                downstream=termination_id,
                upstream=qs_task.id,
                kind=DependencyType.PRODUCES_CONTEXT_FOR,
            )
        )

    return TaskResult(
        note_mutations=[NoteMutation(kind="create", note=q_note)],
        spawned_tasks=[scout, qs_task],
        added_dep_edges=added_deps,
        verdict=f"spawned sub-question: {action.title[:80]}",
    )


def _find_tasks_reading_question(task_graph: TaskGraph, question_note_id: str) -> list[TaskID]:
    non_terminal = {
        TaskStatus.PENDING,
        TaskStatus.RUNNING,
        TaskStatus.BLOCKED_ON_SYNTHESIS_DEP,
        TaskStatus.BLOCKED_ON_SPLIT,
    }
    ids: list[TaskID] = []
    for t in task_graph.all():
        if t.status in non_terminal and question_note_id in t.reads_notes:
            ids.append(t.id)
    return ids


def _apply_abandon_subquestion(
    action: AbandonSubQuestion,
    task_graph: TaskGraph,
    note_graph: NoteGraph,
    parent_task_id: TaskID,
) -> TaskResult:
    qid = cast(NoteID, action.question_note_id)
    if qid not in note_graph:
        logger.warning("abandon_subquestion target not found: %s", action.question_note_id)
        return TaskResult(verdict=f"abandon failed: unknown q_note {action.question_note_id}")

    q_note = note_graph.get(qid)
    task_ids = _find_tasks_reading_question(task_graph, action.question_note_id)

    archive = Note(
        id=new_note_id("decision"),
        type=NoteType.DECISION,
        title=f"Abandoned: {q_note.title[:80]}",
        description=f"Sub-question abandoned by replanner. Rationale: {action.rationale[:200]}",
        content=(
            f"**Original question:** {q_note.title}\n\n"
            f"**Rationale for abandonment:** {action.rationale}\n\n"
            f"**Tasks affected:** {len(task_ids)} non-terminal task(s)."
        ),
        links=[Link(target_id=q_note.id, edge_type="archives_question")],
        metadata=DecisionMetadata(
            category="abandoned_sub_question_archive",
            rationale=action.rationale,
            relates_to_task=parent_task_id,
        ),
        created_by=parent_task_id,
        created_at=_now(),
        last_modified_at=_now(),
    )

    return TaskResult(
        note_mutations=[NoteMutation(kind="create", note=archive)],
        abandoned_task_ids=list(task_ids),
        verdict=f"abandoned {len(task_ids)} task(s) under q_note {q_note.id}",
    )


def _apply_escalate_pattern(
    action: EscalatePattern,
    task_graph: TaskGraph,
    note_graph: NoteGraph,
    parent_task_id: TaskID,
) -> TaskResult:
    """Re-analyze the top analyzed sources under the heavier pattern,
    then spawn a new QUESTION_SYNTHESIZE with the pattern set. Original
    synthesis stays in the graph — the writer sees both.
    """
    pattern_map = {
        "multi_perspective": OrchestrationPattern.MULTI_PERSPECTIVE,
        "debate": OrchestrationPattern.DEBATE,
        "ach": OrchestrationPattern.ACH,
    }
    target_pattern = pattern_map[action.target_pattern]

    qid = cast(NoteID, action.question_note_id)
    # Find analyzed sources for this question, sorted by relevance.
    candidates: list[tuple[float, Note]] = []
    for sn in note_graph.all():
        if sn.type != NoteType.SOURCE:
            continue
        meta = _src_meta(sn)
        if action.question_note_id not in meta.analyzed_for:
            continue
        score = meta.relevance.get(action.question_note_id, 0.0)
        candidates.append((score, sn))
    candidates.sort(key=lambda p: p[0], reverse=True)
    top = [sn for _, sn in candidates[:6]]  # cap fan-out

    termination_id = _find_termination_task(task_graph)
    spawned = []
    for sn in top:
        spawned.append(
            emit_analyze_source(
                source_note_id=sn.id,
                question_note_id=qid,
                parent_task_id=parent_task_id,
                pattern=target_pattern,
            )
        )

    qs_task = emit_question_synthesize(
        question_note_id=qid,
        question=note_graph.get(qid).title if qid in note_graph else action.question_note_id,
        parent_task_id=parent_task_id,
        termination_task_id=termination_id,
        pattern=target_pattern,
    )
    spawned.append(qs_task)

    added_deps: list[DepEdgeAdd] = []
    if termination_id is not None:
        added_deps.append(
            DepEdgeAdd(
                downstream=termination_id,
                upstream=qs_task.id,
                kind=DependencyType.PRODUCES_CONTEXT_FOR,
            )
        )

    return TaskResult(
        note_mutations=[],
        spawned_tasks=spawned,
        added_dep_edges=added_deps,
        verdict=(
            f"escalated q_note {action.question_note_id} to {action.target_pattern} "
            f"with {len(top)} re-analyses"
        ),
    )


def _apply_spawn_scout_burst(
    action: SpawnScoutBurst,
    note_graph: NoteGraph,
    parent_task_id: TaskID,
) -> TaskResult:
    """Emit a new SCOUT_SOURCES task for a specific question. Cheap —
    just search API calls, no LLM until rescore.
    """
    qid = cast(NoteID, action.question_note_id)
    if qid not in note_graph:
        return TaskResult(verdict=f"scout_burst failed: unknown q_note {action.question_note_id}")
    q_note = note_graph.get(qid)
    scout = emit_scout_sources(
        goal=q_note.title,
        scout_mode="question",
        parent_task_id=parent_task_id,
        question_note_ids=[qid],
    )
    return TaskResult(
        spawned_tasks=[scout],
        verdict=f"scout_burst for q_note {qid}",
    )


def _apply_promote_source(
    action: PromoteSource,
    note_graph: NoteGraph,
    parent_task_id: TaskID,
) -> TaskResult:
    sid = cast(NoteID, action.source_note_id)
    qid = cast(NoteID, action.question_note_id)
    if sid not in note_graph or qid not in note_graph:
        return TaskResult(verdict="promote_source failed: unknown note id")
    analyze = emit_analyze_source(
        source_note_id=sid,
        question_note_id=qid,
        parent_task_id=parent_task_id,
    )
    return TaskResult(
        spawned_tasks=[analyze],
        verdict=f"promoted source {sid} for q {qid}",
    )


# Pull this from handlers.py to avoid import cycles.
_MAX_QS_POLLS_FOR_TRIGGER = 6


def _apply_trigger_synthesis(
    action: TriggerSynthesis,
    task_graph: TaskGraph,
    note_graph: NoteGraph,
    parent_task_id: TaskID,
) -> TaskResult:
    """Bypass the readiness gate: emit a QS with poll_count set high
    enough that the 'polls_exhausted' branch triggers immediately.
    """
    qid = cast(NoteID, action.question_note_id)
    if qid not in note_graph:
        return TaskResult(verdict=f"trigger_synthesis failed: unknown q_note {qid}")
    q_note = note_graph.get(qid)
    termination_id = _find_termination_task(task_graph)
    qs = emit_question_synthesize(
        question_note_id=qid,
        question=q_note.title,
        parent_task_id=parent_task_id,
        termination_task_id=termination_id,
        poll_count=_MAX_QS_POLLS_FOR_TRIGGER,  # triggers polls_exhausted branch
    )
    added_deps: list[DepEdgeAdd] = []
    if termination_id is not None:
        added_deps.append(
            DepEdgeAdd(
                downstream=termination_id,
                upstream=qs.id,
                kind=DependencyType.PRODUCES_CONTEXT_FOR,
            )
        )
    return TaskResult(
        spawned_tasks=[qs],
        added_dep_edges=added_deps,
        verdict=f"triggered synthesis for q {qid}",
    )


class ReplannerFailed(RuntimeError):
    """LLM call failed or returned malformed output — scheduler should no-op this cycle."""


async def run_replanner(
    task_graph: TaskGraph,
    note_graph: NoteGraph,
    routing: RoutingConfig,
    local: LocalConfig,
    parent_task_id: TaskID,
    tracker: TokenUsageTracker | None = None,
) -> tuple[list[TaskResult], Note]:
    """Run one replan cycle. Returns (mutations_to_apply, decision_note).

    The decision_note records the cycle's rationale + actions for UI /
    audit — it's always emitted, even on NoOp. Mutations are returned
    as a list of TaskResult so the scheduler can apply each via the
    existing `_apply_result` path without learning a new mutation type.
    """
    snapshot = _format_graph_snapshot(task_graph, note_graph)
    model_id = routing.model_id_for(RoleClass.JUDGMENT, TaskTier.MID)
    agent = Agent(
        make_model(model_id, local),
        output_type=ReplanDecision,
        system_prompt=REPLAN_SYSTEM,
    )
    t0 = time.monotonic()
    try:
        r = await agent.run(snapshot)
        decision = r.output
    except Exception as exc:
        logger.warning("replanner_failed err=%s", exc)
        raise ReplannerFailed(str(exc)) from exc
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if tracker is not None:
        usage = r.usage() if hasattr(r, "usage") else None
        if usage is not None:
            await tracker.record(model_id, usage, task_type="REPLAN")
            logger.info(
                "llm_call model=%s task=REPLAN in=%d out=%d ms=%d",
                model_id,
                getattr(usage, "input_tokens", 0) or 0,
                getattr(usage, "output_tokens", 0) or 0,
                elapsed_ms,
            )

    results: list[TaskResult] = []
    action_lines: list[str] = []
    for action in decision.actions:
        if isinstance(action, SpawnSubQuestion):
            results.append(_apply_spawn_subquestion(action, task_graph, parent_task_id))
            action_lines.append(f"- spawn_subquestion: {action.title} ({action.rationale})")
        elif isinstance(action, AbandonSubQuestion):
            results.append(
                _apply_abandon_subquestion(action, task_graph, note_graph, parent_task_id)
            )
            action_lines.append(
                f"- abandon_subquestion: {action.question_note_id} ({action.rationale})"
            )
        elif isinstance(action, EscalatePattern):
            results.append(_apply_escalate_pattern(action, task_graph, note_graph, parent_task_id))
            action_lines.append(
                f"- escalate_pattern: {action.question_note_id} → "
                f"{action.target_pattern} ({action.rationale})"
            )
        elif isinstance(action, SpawnScoutBurst):
            results.append(_apply_spawn_scout_burst(action, note_graph, parent_task_id))
            action_lines.append(
                f"- spawn_scout_burst: {action.question_note_id} ({action.rationale})"
            )
        elif isinstance(action, PromoteSource):
            results.append(_apply_promote_source(action, note_graph, parent_task_id))
            action_lines.append(
                f"- promote_source: {action.source_note_id}→{action.question_note_id}"
            )
        elif isinstance(action, TriggerSynthesis):
            results.append(_apply_trigger_synthesis(action, task_graph, note_graph, parent_task_id))
            action_lines.append(
                f"- trigger_synthesis: {action.question_note_id} ({action.rationale})"
            )
        elif isinstance(action, NoOp):
            action_lines.append(f"- no_op: {action.rationale}")

    body = decision.overall_rationale
    if action_lines:
        body += "\n\nActions:\n" + "\n".join(action_lines)
    decision_note = Note(
        id=new_note_id("decision"),
        type=NoteType.DECISION,
        title="Replan cycle",
        description=decision.overall_rationale[:280],
        content=body,
        links=[
            Link(target_id=r.note_mutations[0].note.id, edge_type="spawned_by_replan")
            for r in results
            if r.note_mutations
        ],
        metadata=DecisionMetadata(
            category="replan_cycle",
            rationale=decision.overall_rationale,
            relates_to_task=parent_task_id,
        ),
        created_by=parent_task_id,
        created_at=_now(),
        last_modified_at=_now(),
    )

    return results, decision_note
