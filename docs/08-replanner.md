# 08 — Bounded Replanner

The replanner is the system's running second opinion. It wakes
periodically, reads the graph, and decides whether to add work,
abandon work, or escalate a sub-question to a heavier pattern. It
**cannot** terminate the run — termination is a separate structural
check plus a six-gate LLM audit.

## Why bounded

The replanner is bounded three ways:

1. **Cadence**: runs once every `replan_cadence` task completions
   (default 10).
2. **Budget**: runs at most `replan_budget` times per run (default 3).
3. **Authority**: its only outputs are `SpawnSubQuestion`,
   `AbandonSubQuestion`, `EscalatePattern`, or `NoOp`. Termination is
   a separate chain (`CHECK_TERMINATION_READY` → `VALIDATE_COMPLETION`).

## Trigger

Inside `Scheduler.run()`:

```python
completed_since_replan += len(ready)
if replanner and completed_since_replan >= cadence and replans_done < budget:
    await self._run_replan_cycle()
    completed_since_replan = 0
    replans_done += 1
```

Runs **between ticks**, not during. The graph is stable when the
replanner snapshots it.

## Snapshot

`_format_graph_snapshot(task_graph, note_graph)` builds a compact
human-readable snapshot for the replanner LLM. It's deliberately
small — the replanner is not paid to chew through every source note.

The snapshot contains:

- Root query (from the landscape_note's `raw_query`).
- Landscape summary + under-covered areas.
- All sub-questions with their bottom line (if synthesized), surviving
  dissent, or the task status (if not yet synthesized).
- Aggregate verification counts across all claims: how many SUPPORTS /
  REFUTES / INCONCLUSIVE.
- Source count.

## LLM call

Model: `routing.model_id_for(RoleClass.JUDGMENT, TaskTier.MID)` — the
replanner uses the judgment family specifically because its job is
adjudicating the graph, not generating new content.

Prompt: `REPLAN_SYSTEM` (round 4/5 framing — premortem + metacognitive
saturation check).

Output: `ReplanDecision` — one `overall_rationale` + up to 3 `actions`.

## Actions

All four action types live in `replanner/outputs.py` as a Pydantic
discriminated union:

### `SpawnSubQuestion`

```python
action: "spawn_subquestion"
title: str                    # must end with "?"
description: str
classification: "lookup" | "synthesis" | "contested" | "sparse"
rationale: str                # must cite a specific gap
```

Applied by `_apply_spawn_subquestion`:

1. Create a new `question_note`.
2. Emit a `QUESTION_SYNTHESIZE` task on it via `emit_question_synthesize`.
3. Find the pending `WRITE_REPORT` task and graft a dep edge onto it
   (`DepEdgeAdd`) so the report waits for the new synthesis.

Use case: landscape surfaced an under-covered area the decomposer
missed; one sub-question's synthesis referenced an entity no other
sub-question owns; verified refutations suggest a reformulation is
needed.

### `AbandonSubQuestion`

```python
action: "abandon_subquestion"
question_note_id: str
rationale: str                # must cite a specific failure signal
```

Applied by `_apply_abandon_subquestion`:

1. Find every non-terminal (PENDING / RUNNING /
   BLOCKED_ON_SYNTHESIS_DEP / BLOCKED_ON_SPLIT) task whose
   `reads_notes` contains the question_note.
2. Mark them all `ABANDONED` via `TaskResult.abandoned_task_ids` — the
   scheduler's `abandon_task` both flips status and strips incoming
   dep edges.
3. Write an archive `decision_note` (`category="abandoned_sub_question_archive"`)
   linked via `archives_question` to the question_note.

RUNNING tasks finish their current iteration (the scheduler only
swaps status after `execute` returns) and their output is applied —
but because their downstream dep edges were stripped, nothing further
blocks on them.

Use sparingly: prefer spawning a reformulated replacement over
abandoning the original unless evidence shows the original is dead
(off-topic sources dominate, synthesis abstains with no path forward).

### `EscalatePattern`

```python
action: "escalate_pattern"
question_note_id: str
target_pattern: "multi_perspective" | "debate" | "ach"
rationale: str
```

Applied by `_apply_escalate_pattern`:

1. Emit a new `QUESTION_SYNTHESIZE` task on the same question_note.
2. Override the spawned task's `.pattern` to the escalation target
   (mutating the Task in place — `emit_question_synthesize` doesn't
   take a pattern arg today).
3. Graft the new QS onto `WRITE_REPORT`.

The original `single_researcher` synthesis stays — having both gives
the report writer the surface reading and the multi-framing view. The
report has both syntheses in its context.

### `NoOp`

```python
action: "no_op"
rationale: str
```

Explicit skip. The replanner still writes a `decision_note` so the
cycle is visible in the graph and UI. Saturation framing — when in
doubt, `NoOp` beats speculative additions.

## Cycle output

`run_replanner` returns `(results, decision_note)`:

- `results: list[TaskResult]` — one per action. Applied by the
  scheduler's `_apply_replan_result` path under the write lock.
- `decision_note: Note` — `category="replan_cycle"`, body is the
  rationale plus a bullet list of actions taken.

`decision_note.links` point at every newly-created note via
`spawned_by_replan` edges so the UI and exporter can trace what each
cycle produced.

## Scheduler integration

`_apply_replan_result` mirrors `_apply_result` with two caveats:

- No completing task — `on_note_mutation` fires with `task=None`.
- Only `create` mutations accepted. `replace` from the replanner path
  would need a task ID for the `by` attribution, and the cycle
  doesn't have one. Cascade replaces must go through a dedicated task
  type instead.

A replanner failure (`ReplannerFailed`) is caught in `_run_replan_cycle`
and logged; the cycle is skipped and the run continues. Replanner
budget is **not** decremented on failure — a flaky replanner
shouldn't burn the budget.

## What the replanner can NOT do

- Change the root query / AIMS.
- Rewrite an existing synthesis (the new synthesis replaces the old
  only at the QS-task level; `synthesis_note`s themselves are never
  mutated, only superseded by newer ones).
- Terminate the run.
- Decide about the completion audit.
- Touch source_notes directly (no `ANALYZE_SOURCE` mutation action).

All authority escalation is a typed, budgeted mutation. This is the
whole point of "bounded replanner."

## Event plumbing for UI

The replanner runs outside the scheduler's task-dispatch path, so the
normal `on_task_start` / `on_task_done` don't fire for it. The server
runner (`server/runner.py`) wraps the replanner call in a synthetic
task event pair:

```python
start_evt, synth_id = event_replan_started(cycle_num, routing)
session.publish(start_evt)
try:
    result = await run_replanner(...)
except Exception:
    session.publish(event_replan_done(synth_id, "replan failed", failed=True))
    raise
session.publish(event_replan_done(synth_id, verdict))
```

`event_replan_started` builds a `TaskSummary` with `type="REPLAN"`,
`status="RUNNING"`, the resolved `judgment / MID` model ID, and a
synthetic task ID (`replan_cycle_01`, `replan_cycle_02`, …). The
frontend shows a card in the Running Agents panel just like any real
task.
