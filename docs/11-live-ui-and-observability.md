# 11 — Live UI and Observability

The system runs in three modes — CLI, live server, or replay (stub)
— all sharing the same Scheduler and AgentExecutor. The observability
layer is how the differences between those modes surface.

## Live UI server

### Entry

`dra serve [--host 127.0.0.1] [--port 8000]` dispatches to
`cli._run_serve`, which builds a FastAPI app via
`server.create_app(routing_path, local_path, runs_dir)` and hands it
to `uvicorn.run`.

### Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Serves `server/static/index.html` with aggressive no-cache headers (the UI iterates fast) |
| GET | `/static/*` | Static asset mount for the single-page UI |
| POST | `/api/run` | Starts a new run; body: `{query: str}`; returns `{run_id}` |
| GET | `/api/runs` | List all known runs with started_at + finished |
| GET | `/api/note/{run_id}/{note_id}` | Full Note JSON for the graph viewer |
| WS | `/api/ws/{run_id}` | Event stream with history replay on connect |

### Run lifecycle

`POST /api/run` creates a `RunSession`, starts the run as a background
`asyncio.Task` (`run_session(...)`), and returns the run_id
immediately. The `asyncio.Task` is pinned on the session object so it
isn't GC'd mid-run.

`run_session` is the server-side analogue of the CLI's
`_run_research`. Same Scheduler, same AgentExecutor, same
register_handlers — the difference is the callbacks publish `Event`s
onto the `RunSession` instead of printing to the terminal.

### Event model

`server/events.py`:

```python
class Event(BaseModel):
    kind: Literal[
        "run_started",
        "task_started",
        "task_done",
        "note_created",
        "note_replaced",
        "run_done",
        "run_failed",
    ]
    at: datetime
    data: dict[str, Any]
```

Events are published onto:

- An append-only history list (cap: 5000), used to replay state to
  late WebSocket connectors.
- A set of subscriber `asyncio.Queue`s, one per live WebSocket.

### Running agents panel

`event_task_started` carries a `TaskSummary` with enough context to
render a card:

```python
class TaskSummary(BaseModel):
    id: str
    type: str                  # TaskType.value
    goal: str
    status: str
    parent_id: str | None
    reads_notes: list[str]
    writes_notes: list[str]
    pattern: str | None        # OrchestrationPattern.value
    tier: str | None
    role: str | None
    model_id: str | None       # resolved at event-emit time
    started_at: datetime | None
```

`model_id` is resolved via `routing.model_id_for(role, tier)`. For
VERIFY_CLAIM the executor may additionally apply the cross-family
invariant and select a different model; this field reflects the
default-family resolution (close enough for the UI; the run log has
the actual model used).

### Synthetic events for the replanner

The replanner runs between scheduler ticks, so `on_task_start` /
`on_task_done` don't fire for it. The server wraps the replanner in a
synthetic event pair:

```python
start_evt, synth_id = event_replan_started(cycle_num, routing)
# synth_id e.g. "replan_cycle_01"
session.publish(start_evt)
try:
    result = await run_replanner(...)
except Exception:
    session.publish(event_replan_done(synth_id, ..., failed=True))
    raise
session.publish(event_replan_done(synth_id, verdict))
```

The frontend gets a card in the Running Agents panel that looks like
any real task, with `type="REPLAN"` and the judgment/MID model ID.

### Note cache

`_on_note_mutation` captures the full `Note` into `session.notes[mut.note.id]`.
This is what `/api/note/{run_id}/{note_id}` returns — no
scheduler-internals reach needed.

### Frontend (static/index.html)

A single-page HTML file (~1000 lines, including inline CSS and JS).
Uses:

- **Cytoscape** (`cytoscape@3.30.2`) for the note-graph viewer.
- **WebCola + cytoscape-cola** for constraint-aware layout.
- **marked** for markdown rendering inside note content pop-outs.

The frontend connects to `/api/ws/{run_id}` on run start, replays
history, and then streams events. Each `note_created` /
`note_replaced` updates the graph; each `task_started` / `task_done`
updates the Running Agents panel; `run_done` / `run_failed` closes the
session UI.

Color palette is per-note-type (landscape, question, source, synthesis,
decision) — defined as CSS variables at the top of the style block.

## Logging

### Split-level logging

`server/app.py::_configure_logging` sets up:

- **Root logger**: `DEBUG`. Has to be the most permissive; handlers
  below filter their own levels.
- **Console handler**: `DRA_LOG_LEVEL` env var (default `INFO`). Keeps
  the terminal clean.
- **Per-run `FileHandler`**: `DEBUG` unconditionally. Attached by
  `runner._attach_run_log_handler(run_dir, run_id)` at run start;
  detached in the `finally` block at end. Writes to
  `runs/<id>/run.log`.
- **Optional `DRA_LOG_FILE` `FileHandler`**: `DRA_LOG_LEVEL`. Useful
  for long-lived process-wide logs.

The per-run file handler is **filtered by run_id**. A contextvar
(`_RUN_ID_CTX`) is set at `run_session` entry, and
`_RunIdFilter(run_id)` admits only records emitted in that
contextvar's scope. So concurrent runs in the same server process get
isolated log files — one run's debug lines never contaminate another's.

The CLI uses a simpler `logging.basicConfig` at `INFO` / `WARNING`.

### Per-run log

Every run gets `runs/<id>/run.log` at DEBUG level. Contains:

- `dispatch task_id=... type=...` — one per task.
- `llm_call model=... task=... in=N out=M ms=T` — one per agent run,
  emitted by `HandlerContext.track`.
- `brave_search query=... hits=... elapsed_ms=... attempts=...`.
- `fetch_ok url=... path=html_trafilatura|pdf_markitdown bytes=... md_chars=...`.
- `tier classifier failed url=... err=...` (on failure).
- `added dep edge downstream=... upstream=... kind=...`.
- `replan cycle applied actions=N decision_note=...`.
- `abandoned task_id=... dropped_dep_edges=...`.

Never need an env var to turn on debug-level logging — it's always
captured to disk.

## Logfire

`observability.py`:

- `setup_logfire(local)` — configures [Logfire](https://logfire.pydantic.dev)
  with the token from `local.observability.logfire_token` and
  instruments `pydantic_ai` + `httpx`.
- No-op when the token is absent.
- **Noise silencing**: on 401 (bad token), the OTLP exporter retries
  on every batch and emits "Failed to export span batch" to the
  terminal. `_silence_otel_and_logfire_noise` raises those loggers to
  `CRITICAL` and filters the matching `UserWarning` so a one-time
  warning from the setup path is all the user sees.

When Logfire is on, every `Agent.run()` and every `httpx` call is a
traceable span.

## Token usage tracking

`token_usage.py`. Per-run, per-model.

### `TokenUsageTracker`

Per-run (not process-global). The tracker is instantiated in the CLI
/ runner, attached to the `AgentExecutor`, and used via
`HandlerContext.track(agent, user)`:

```python
async def track(self, agent, user_input):
    t0 = time.monotonic()
    result = await agent.run(user_input)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    usage = result.usage() if hasattr(result, "usage") else None
    if usage:
        await self.tracker.record(
            self.model_id,
            usage,
            task_type=self.task.type.value,
        )
        logger.info(
            "llm_call model=%s task=%s in=%d out=%d ms=%d",
            self.model_id, self.task.type.value,
            usage.input_tokens or 0, usage.output_tokens or 0,
            elapsed_ms,
        )
    return result
```

### Accounted fields

Per `ModelTotals`:

- `calls`
- `input_tokens`, `output_tokens` (and their sum as `total_tokens`)
- `cache_read_tokens`, `cache_write_tokens`
- `tool_calls`
- `by_task_type` — dict mapping task type to call count

All fields are read defensively from the pydantic_ai `RunUsage`; a
pydantic_ai version bump that renames a field won't crash the run.

### Async safety

An `asyncio.Lock` serializes `record`. Int increments on CPython are
GIL-safe but the `by_task_type` dict mutation isn't, so the lock is
conservative — the overhead is irrelevant next to LLM latency.

### End-of-run output

The CLI and runner both:

- Log `tracker.format_table()` at INFO level — a nicely-formatted per-
  model table with calls + input + output + total:

  ```
  token usage summary:
    model                           calls          in         out       total
    ------------------------------  ------  ----------  ----------  ----------
    anthropic/claude-opus-4-7           12      45,210      12,004      57,214
    anthropic/claude-haiku-4-5          18       9,832       1,201      11,033
    openai/gpt-5.4                       4      18,002       2,890      20,892
    TOTAL                               34      73,044      16,095      89,139
  ```

- Save `runs/<id>/token_usage.json` via `tracker.save_json(...)` —
  structured JSON with `per_model` and `grand_totals`. This is the
  artifact for post-hoc cost analysis.

Token tracking is **always run**, whether the run finished or failed.
Costs don't care whether the report made it out.

## Other on-disk artifacts per run

```
runs/<run_id>/
  report.md              Final markdown report (if WRITE_REPORT succeeded)
  notes/<note_id>.md     One markdown file per note in the graph
  tasks.json             Full task graph snapshot
  token_usage.json       Per-model token counts
  run.log                DEBUG-level per-run log (server only)
```

The exporter (`export/markdown.py::export_run`) walks the note graph
and writes one `.md` file per note. Then it looks for the
`final_report` decision_note and extracts its `content` into
`report.md`. Then it dumps the task graph to `tasks.json`.

On run failure, the CLI / runner still call `export_run` in a `try
... except` so partial runs are autopsy-able from disk.

## Observability summary

| Signal | Where |
|--------|-------|
| Task dispatch | `run.log` at DEBUG (server) / stderr at WARNING (CLI) |
| LLM calls (model, task, tokens, latency) | `run.log` via `HandlerContext.track` |
| Per-model token totals | `runs/<id>/token_usage.json` + stderr summary |
| Note graph evolution | `runs/<id>/notes/*.md` + live WebSocket events |
| Task graph snapshot | `runs/<id>/tasks.json` |
| Replanner decisions | `decision_note`s in the note graph (category `replan_cycle`) |
| Verification outcomes | `decision_note`s in the note graph (category `verification`) |
| Completion audit | `decision_note`s in the note graph (categories `termination_readiness`, `completion_audit`) |
| HTTP + LLM traces | Logfire (when `logfire_token` is set) |
