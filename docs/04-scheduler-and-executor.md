# 04 — Scheduler and Executor

The scheduler is the system's deterministic core. No LLM call happens
inside it. The executor is the layer that owns LLM work — it resolves
models, dispatches to handlers, and hands back a `TaskResult`.

## Scheduler

### Responsibilities

- Compute the **ready set** (tasks whose deps are satisfied).
- Dispatch the ready set in parallel via `asyncio.gather`.
- Apply each handler's `TaskResult` under a write lock.
- Invoke the replanner between ticks at configured cadence and budget.
- Raise `SchedulerDeadlock` if there are still `PENDING` tasks but
  nothing can run.

### Main loop

`Scheduler.run()`:

```python
while not self.task_graph.all_terminal():
    ready = self.task_graph.get_ready()
    if not ready:
        raise SchedulerDeadlock(...)
    tick_results = await asyncio.gather(
        *(self._run_one(t) for t in ready),
        return_exceptions=True,
    )
    completed_since_replan += len(ready)
    if replanner and completed_since_replan >= cadence and replans_done < budget:
        await self._run_replan_cycle()
        completed_since_replan = 0
        replans_done += 1
```

`return_exceptions=True` is defense-in-depth — `_run_one` already
swallows handler exceptions and marks the task `ABANDONED`, but if
something more fundamental blows up (an OOM, a bug in the wrapper
itself), the surviving tasks still complete this tick.

### `_run_one` — one task's lifecycle

1. `task.status = RUNNING`.
2. Fire `on_task_start` callback (UI + CLI progress line).
3. `await executor.execute(task, notes)` — returns a `TaskResult` on
   success.
4. On exception: log, set `status = ABANDONED`, fire `on_task_done`
   with a synthetic failure `TaskResult`. **Do not re-raise.** The
   scheduler itself is only failed if it can't make progress at all.
5. On success: acquire the write lock, apply the result, release,
   fire `on_task_done`.

### `_apply_result` — what the write lock protects

Under the lock, for every result:

1. **Note mutations.**
   - `create` → `note_graph.add(note)`; append to `task.writes_notes`.
   - `replace` → `note_graph.replace(note, by=task.id)`; version bumps.
2. **Spawned tasks.** Stamp `parent_id = task.id`, add to the task
   graph, append to `task.spawned_sub_tasks`.
3. **Dep-edge grafts.** For each `DepEdgeAdd`, look up the downstream
   task and append a `DepEdge` unless one already exists for that
   upstream. Silently idempotent.
4. **Task abandonment.** For each `abandoned_task_ids` entry, call
   `TaskGraph.abandon_task(tid)` — status → `ABANDONED` and dep edges
   pointing at it are dropped from every other task.

Callback fires:

- `on_note_mutation(mut, task)` — one per mutation (both `create` and
  `replace`).
- `on_task_done(task, result)` — one per task.

### Replanner cycle

`_run_replan_cycle()` pauses the tick loop, awaits the replanner
callback, and applies its result under the same write lock path. Two
differences from regular task-result application:

- The "completing task" is synthetic — there is no task ID the
  mutations are attributed to. `on_note_mutation` is fired with
  `task=None`.
- Only `create` note mutations are honored from the replanner path;
  `replace` would need a `by` TaskID and the replanner doesn't have
  one. If cascade note-replaces are ever needed, the guidance in the
  comments is to route them through a dedicated task type.

A replanner failure is caught and logged; the cycle is skipped but the
run continues. Replanner budget is not decremented on failure — the
comment is explicit that we don't want a flaky replanner to burn the
budget.

### Deadlock detection

`SchedulerDeadlock` is raised when `get_ready()` returns `[]` but
`all_terminal()` is also false. Deadlock typically indicates:

- A dep edge points at a task that was abandoned without cascading
  (bug in cascade logic).
- A dep edge points at a task that no longer exists (shouldn't happen;
  the task graph has no delete).

The exception message dumps every still-`PENDING` task and its dep
edges so the mode of failure is visible in logs.

## Executor

### Responsibilities

- Resolve `(role, tier) → model_id` via `RoutingConfig.model_id_for`.
- Enforce the cross-family invariant at model-selection time for task
  types listed in `routing.cross_family_invariant.applies_to`.
- Dispatch to the registered handler for the task's `type`.
- Expose `HandlerContext.track(agent, user)` — a thin wrapper around
  `agent.run(user)` that records token usage into the `TokenUsageTracker`
  and logs a structured line per LLM call.

### `HandlerContext`

```python
@dataclass(frozen=True)
class HandlerContext:
    task: Task                    # the task being run
    notes: NoteReader             # read-only view of the note graph
    model_id: str                 # resolved by routing
    routing: RoutingConfig        # so handlers can resolve other roles/tiers
    local: LocalConfig            # api_base_url, keys, retrieval config
    tracker: TokenUsageTracker    # per-run token bookkeeping

    async def track(self, agent, user_input):
        """Run agent.run() and record usage + log llm_call line."""
```

Handlers build their own `pydantic_ai.Agent` instances inside the
handler — this is intentional so different task types can use
different `output_type` / `system_prompt` combinations. The model
itself is constructed by `agent_factory.make_model(model_id, local)`
which strips the family prefix (`anthropic/claude-opus-4-7` →
`claude-opus-4-7`) and wraps an `OpenAIProvider` pointed at the
`local.llm.api_base_url`.

### Cross-family invariant

`AgentExecutor._forbidden_family(task, notes)` inspects `VERIFY_CLAIM`
tasks:

1. Reads `task.input_refs["source_note_id"]` and `input_refs["claim_id"]`.
2. Finds the matching `ClaimItem` on the referenced source_note.
3. Returns `claim.analyzed_by_family` (e.g. `"anthropic"`).

`select_model(routing, role, tier, task_type, forbidden_family)` checks
the resolved model family against the forbidden family. A match raises
`CrossFamilyViolation`. The structural guarantee is that the claim's
own analyzer cannot verify itself — the router has to pick from a
different family.

Fallback behavior: if `source_note_id` or `claim_id` is missing, or
the source/claim can't be found, the check short-circuits to `None`
(no restriction). This is a defensive path; under normal operation
every claim carries `analyzed_by_family`.

### Handler registration

`register_handlers(executor)` maps task types to handlers:

| Task type | Handler |
|-----------|---------|
| `LANDSCAPE_SURVEY` | `handle_landscape_survey` |
| `DECOMPOSE` | `handle_decompose` |
| `QUESTION_SYNTHESIZE` | `handle_question_synthesize` (fat handler) |
| `VERIFY_CLAIM` | `handle_verify_claim` |
| `CHECK_TERMINATION_READY` | `handle_check_termination_ready` |
| `VALIDATE_COMPLETION` | `handle_validate_completion` |
| `WRITE_REPORT` | `handle_write_report` |

The `TaskType` enum defines additional task types (`SEARCH`,
`SCAN_SEARCH_RESULTS`, `ANALYZE_SOURCE`, `ADVERSARIAL_CRITIQUE`,
`SYNTHESIZE`, `ANALYZE_CONSISTENCY`, `SCOPE_ESCALATION`) that have no
registered handler. The work those names describe is performed inline
inside the `QUESTION_SYNTHESIZE` handler; attempting to dispatch one
of them raises `UnhandledTaskType`.

### Handler shape

Every handler is `async def handle_<X>(ctx: HandlerContext) -> TaskResult`.
The handler:

1. Reads inputs from `ctx.task.reads_notes`, `ctx.task.input_refs`,
   `ctx.task.goal`.
2. Does LLM work via `Agent(make_model(ctx.model_id, ctx.local),
   output_type=..., system_prompt=...)` and `await ctx.track(agent, ...)`.
3. Optionally does retrieval via the `deep_research_agent.retrieval`
   package.
4. Constructs new or updated Notes.
5. Constructs any sub-tasks to spawn.
6. Returns `TaskResult(note_mutations=..., spawned_tasks=...,
   added_dep_edges=..., abandoned_task_ids=..., verdict=...)`.

Handlers must not mutate the note graph directly — they only return
mutations. This is a social contract; nothing in the code actually
stops a misbehaving handler from calling `notes.add(...)` if
`NoteReader` is an actual `NoteGraph` at runtime. In practice all
handlers are internal and obey the contract.

## Parallelism model

Two levels:

1. **Scheduler-level parallelism.** Within a tick, every ready task
   runs concurrently. Task-graph and note-graph writes are serialized
   by the lock, but the read-heavy handler body (LLM calls, HTTP
   fetches) runs without contention.
2. **Within-handler parallelism.** Handlers use `asyncio.gather`
   freely for their internal fan-out (per-source fetches, per-framing
   analyzer calls, per-hypothesis ACH consistency checks). These are
   invisible to the scheduler — one `TaskResult` comes back per task
   regardless of internal structure.

There is **no work-stealing**. All coordination is through
`asyncio.gather` and `asyncio.Lock`; the event loop is a single thread.
Heavy blocking work (PDF conversion via MarkItDown) is offloaded via
`asyncio.to_thread` with a wall-clock timeout — see
`retrieval/fetch.py`.

## Failure isolation

- **Handler raises**: task marked `ABANDONED`, run continues. Other
  tasks in the same tick are unaffected. Downstream tasks see this as
  a satisfied dep (the cascade rule).
- **LLM call fails**: handler's responsibility — usually caught and
  downgraded (e.g. `VALIDATE_COMPLETION` defaults to
  `PASS_WITH_WARNINGS`; `classify_source` returns Tier 3 with low
  confidence).
- **Replanner fails**: cycle skipped, budget not decremented, warning
  logged.
- **Scheduler deadlock**: run fails with `SchedulerDeadlock`. CLI
  catches, logs, and still exports whatever graph state exists.
- **Anything else**: caught by the top-level try in `cli._run_research`
  / `server/runner.run_session`, which always tries to export and
  always logs the token usage summary. Partial runs are autopsy-able.

## Observable callbacks

The scheduler exposes three hooks and one replanner callback:

```python
on_task_start: Callable[[Task], None]
on_task_done: Callable[[Task, TaskResult], None]
on_note_mutation: Callable[[NoteMutation, Task | None], None]
replanner: Callable[[TaskGraph, NoteGraph], Awaitable[tuple[list[TaskResult], Note]]]
```

- The CLI uses `on_task_start` / `on_task_done` to drive the Rich
  status spinner and per-task console lines.
- The server wires all three callbacks to publish `Event`s onto the
  `RunSession` for WebSocket subscribers.
- `on_note_mutation` is the hook the server uses to cache the full
  `Note` so `/api/note/{run_id}/{note_id}` can return it without
  reaching into scheduler internals.

## Token accounting

The executor's `HandlerContext.track` wrapper calls
`self.tracker.record(model_id, usage, task_type)` on every agent run.
The tracker is per-run, attached to the executor at construction. The
CLI and server both instantiate one `TokenUsageTracker` per run, log
`tracker.format_table()` at end-of-run, and save
`runs/<id>/token_usage.json` from `tracker.to_dict()`. See
[11-live-ui-and-observability.md](11-live-ui-and-observability.md) for
details.
