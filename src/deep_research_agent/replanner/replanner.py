"""Bounded replanner — periodic LLM-driven course correction.

Invoked by the scheduler after every `replan_cadence` task completions
(default 10), up to `replan_budget` cycles per run (default 3). Reads
a snapshot of the graph, asks an LLM what to do, and returns a set of
task-graph / note-graph mutations that the scheduler applies under its
write lock.

v3 step 1 scope:
- SpawnSubQuestion: add a new sub-question, question_note, QS task,
  and graft a dep edge onto WRITE_REPORT.
- NoOp: record a decision_note and move on.

AbandonTask + EscalatePattern + cascade propagation land in step 2+.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pydantic_ai import Agent

from ..agent_factory import make_model
from ..config import LocalConfig, RoutingConfig
from ..patterns.single_researcher import emit_question_synthesize
from ..scheduler import DepEdgeAdd, NoteMutation, TaskResult
from ..scheduler.ids import new_note_id
from ..scheduler.note_graph import NoteGraph
from ..scheduler.task_graph import TaskGraph
from ..schemas import DecisionMetadata, Link, Note, QuestionMetadata
from ..schemas.enums import (
    DependencyType,
    NoteType,
    OrchestrationPattern,
    QuestionClassification,
    RoleClass,
    TaskStatus,
    TaskTier,
    TaskType,
)
from ..schemas.ids import TaskID
from .outputs import AbandonSubQuestion, EscalatePattern, ReplanDecision, SpawnSubQuestion
from .prompts import REPLAN_SYSTEM

logger = logging.getLogger(__name__)

DEFAULT_CADENCE = 10
DEFAULT_BUDGET = 3


def _format_graph_snapshot(task_graph: TaskGraph, note_graph: NoteGraph) -> str:
    """Compact human-readable snapshot for the replanner LLM.

    Keeps the snapshot small on purpose — we're not paying for the
    replanner to chew through every source note. Shows: the root query,
    decomposed sub-questions with their synthesis status + bottom line,
    verification verdicts, and any surviving dissent.
    """
    parts: list[str] = []

    question_notes = [n for n in note_graph.all() if n.type == NoteType.QUESTION]
    synthesis_notes = [n for n in note_graph.all() if n.type == NoteType.SYNTHESIS]
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

    parts.append(f"SUB-QUESTIONS ({len(question_notes)} total):")
    # Map question_note.id -> synthesis that points at it
    synthesis_by_question: dict[str, Note] = {}
    for s in synthesis_notes:
        for link in s.links:
            if link.edge_type == "source_for_synthesis":
                # source_for_synthesis links synthesis -> source_notes, not -> question
                pass
        # A synthesis_note is created reading a question_note via reads_notes
        # on the task, not via a note link. Match by task instead.
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

    for q in question_notes:
        parts.append(f"  Q[{q.id}]: {q.title}")
        s = synthesis_by_question.get(q.id)
        if s is not None:
            parts.append(f"    BLUF: {s.description}")
            disagreements = getattr(s.metadata, "surviving_dissent", []) or []
            if disagreements:
                parts.append("    Surviving dissent:")
                for d in disagreements[:3]:
                    parts.append(f"      - {d}")
        else:
            # Find the task's status
            for task in task_graph.all():
                if task.type == TaskType.QUESTION_SYNTHESIZE and q.id in task.reads_notes:
                    parts.append(
                        f"    (synthesis not yet complete — task status: {task.status.value})"
                    )
                    break

    parts.append("")
    parts.append(f"SOURCES FETCHED: {len(source_notes)}")
    verified_supports = 0
    verified_refutes = 0
    verified_inconclusive = 0
    for sn in source_notes:
        for c in getattr(sn.metadata, "claims", []) or []:
            vs = getattr(c, "verification_status", None)
            if vs is None:
                continue
            v = vs.value if hasattr(vs, "value") else str(vs)
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


def _find_write_report_task(task_graph: TaskGraph) -> TaskID | None:
    for t in task_graph.all():
        if t.type == TaskType.WRITE_REPORT and t.status in {
            TaskStatus.PENDING,
            TaskStatus.BLOCKED_ON_SYNTHESIS_DEP,
        }:
            return t.id
    return None


def _now() -> datetime:
    return datetime.now(UTC)


def _apply_spawn_subquestion(
    action: SpawnSubQuestion,
    task_graph: TaskGraph,
    parent_task_id: TaskID,
) -> TaskResult:
    """Build the note + task + dep-edge mutations for a spawn action."""
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

    wr_id = _find_write_report_task(task_graph)
    qs_task = emit_question_synthesize(
        question_note_id=q_note.id,
        question=action.title,
        write_report_task_id=wr_id,
        parent_task_id=parent_task_id,
    )

    added_deps: list[DepEdgeAdd] = []
    if wr_id is not None:
        added_deps.append(
            DepEdgeAdd(
                downstream=wr_id,
                upstream=qs_task.id,
                kind=DependencyType.PRODUCES_CONTEXT_FOR,
            )
        )

    return TaskResult(
        note_mutations=[NoteMutation(kind="create", note=q_note)],
        spawned_tasks=[qs_task],
        added_dep_edges=added_deps,
        verdict=f"spawned sub-question: {action.title[:80]}",
    )


def _find_tasks_reading_question(task_graph: TaskGraph, question_note_id: str) -> list[TaskID]:
    """Every task whose reads_notes contains the question_note, filtered
    to non-terminal states (PENDING, RUNNING, BLOCKED_*). Terminal tasks
    are left alone — their outputs are already recorded.
    """
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
    """Cascade: abandon non-terminal tasks reading the question_note and
    write an archive decision_note. Per ADR 0009, in-progress tasks
    technically should complete and archive their outputs; for v3 step 2
    we simplify to "mark all non-terminal tasks ABANDONED" — RUNNING
    tasks finish their current iteration but their TaskResult is still
    applied (the scheduler only swaps the status after execute returns).
    """
    if action.question_note_id not in note_graph:
        logger.warning("abandon_subquestion target not found: %s", action.question_note_id)
        return TaskResult(verdict=f"abandon failed: unknown q_note {action.question_note_id}")

    q_note = note_graph.get(action.question_note_id)
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
    parent_task_id: TaskID,
) -> TaskResult:
    """Spawn a new QUESTION_SYNTHESIZE task on the target question_note
    with pattern=MULTI_PERSPECTIVE. Grafts it onto WRITE_REPORT so the
    report waits for the deeper analysis. The original single_researcher
    synthesis stays — having both gives the report writer both the
    surface reading and the multi-framing view.
    """
    wr_id = _find_write_report_task(task_graph)
    qs_task = emit_question_synthesize(
        question_note_id=action.question_note_id,
        question=action.question_note_id,  # overridden by the handler via reads_notes
        write_report_task_id=wr_id,
        parent_task_id=parent_task_id,
    )
    # Override the pattern on the spawned task. emit_question_synthesize
    # doesn't take a pattern arg today; we mutate the Task in place to
    # keep the single_researcher helper's signature stable.
    qs_task.pattern = OrchestrationPattern.MULTI_PERSPECTIVE

    added_deps: list[DepEdgeAdd] = []
    if wr_id is not None:
        added_deps.append(
            DepEdgeAdd(
                downstream=wr_id,
                upstream=qs_task.id,
                kind=DependencyType.PRODUCES_CONTEXT_FOR,
            )
        )

    return TaskResult(
        note_mutations=[],
        spawned_tasks=[qs_task],
        added_dep_edges=added_deps,
        verdict=(f"escalated q_note {action.question_note_id} to {action.target_pattern}"),
    )


class ReplannerFailed(RuntimeError):
    """LLM call failed or returned malformed output — scheduler should no-op this cycle."""


async def run_replanner(
    task_graph: TaskGraph,
    note_graph: NoteGraph,
    routing: RoutingConfig,
    local: LocalConfig,
    parent_task_id: TaskID,
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
    try:
        r = await agent.run(snapshot)
        decision = r.output
    except Exception as exc:
        logger.warning("replanner_failed err=%s", exc)
        raise ReplannerFailed(str(exc)) from exc

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
            results.append(_apply_escalate_pattern(action, task_graph, parent_task_id))
            action_lines.append(
                f"- escalate_pattern: {action.question_note_id} → "
                f"{action.target_pattern} ({action.rationale})"
            )
        else:
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
