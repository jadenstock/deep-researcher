# 01 — System Overview

## What it is

An evidence-grounded deep research agent. Takes a natural-language query,
runs a four-phase pipeline, and produces an Analytic Pyramid-style
markdown research report with claim-level traceability to verbatim
source quotes.

The defining architectural choice is that **all long-term memory in a
run is a typed, versioned note graph**. Agents never talk to each other
directly; they read and write notes through the scheduler, and every
claim carries a quote plus provenance back to the source that produced
it.

## What it is not

- Not a training pipeline. API-only; no fine-tuning.
- Not a production observability system. Basic tracing only.
- Not a general-purpose RAG system. Progressive disclosure over a note
  graph; no embedding index.
- Not a persistent memory system. Every run starts fresh; no cross-session
  memory.

## Pipeline at a glance

```
  Query
    │
    ▼
  ┌───────────────────────┐   one LANDSCAPE_SURVEY task: broad Brave
  │ Phase 1 — Landscape   │   search (~8 hits), one LLM pass over
  │ Survey                │   snippets → landscape_note
  └───────────────────────┘
            │
            ▼
  ┌───────────────────────┐   one DECOMPOSE task: reads landscape_note,
  │ Phase 2 — Decompose   │   emits AIMS decision_note + N question_notes
  │                       │   + N QUESTION_SYNTHESIZE tasks + the
  │                       │   termination/report task chain
  └───────────────────────┘
            │
            ▼
  ┌───────────────────────┐   N QUESTION_SYNTHESIZE tasks run in
  │ Phase 3 — Deep        │   parallel under their chosen pattern
  │ Research              │   (single_researcher / multi_perspective /
  │ (+ bounded replanner) │   debate / ACH) with maker_checker spawning
  │                       │   VERIFY_CLAIM sub-tasks on top claims.
  │                       │   Replanner fires every N task completions.
  └───────────────────────┘
            │
            ▼
  ┌───────────────────────┐   CHECK_TERMINATION_READY (structural, no LLM)
  │ Phase 4 — Completion  │   → VALIDATE_COMPLETION (six-gate LLM audit)
  │ & Report              │   → WRITE_REPORT (assembles markdown from
  │                       │   note graph)
  └───────────────────────┘
            │
            ▼
  runs/<run_id>/report.md  +  notes/*.md  +  tasks.json  +  token_usage.json
```

## Package layout

```
src/deep_research_agent/
  __init__.py
  cli.py                       dra CLI entry point (research / replay / serve)
  config.py                    Routing (YAML, policy) + Local (TOML, secrets)
  agent_factory.py             PydanticAI model builder pointed at LiteLLM router
  confidence.py                Tier-weighted confidence formula + language ladder
  observability.py             Logfire instrumentation
  token_usage.py               Per-run, per-model token bookkeeping

  schemas/                     Pydantic models — the domain's type-level spec
    enums.py                     All enums (TaskType, TaskStatus, Tier, ...)
    ids.py                       NewType aliases: TaskID, NoteID, RunID, SourceID
    task.py                      Task, DepEdge, DepScope
    note.py                      Note + per-type metadata discriminated union
    source.py                    SourceMetadata, ClaimItem, EvalItem, StructuredContent

  scheduler/                   Deterministic dispatch (no LLM)
    scheduler.py                 Parallel tick loop, write lock, replanner hook
    task_graph.py                In-memory task store + ready-set + cascade
    note_graph.py                In-memory note store + version bump on replace
    ids.py                       Task/Note/Run ID factories

  executor/                    Agent executor + role-to-model routing
    executor.py                  Dispatcher: routing + cross-family invariant
    routing.py                   select_model() and CrossFamilyViolation
    handlers.py                  Per-task-type handlers (landscape, decompose, QS, ...)
    prompts.py                   System prompts per role
    outputs.py                   Pydantic output types for LLM agents

  retrieval/                   Search + fetch + extract
    brave.py                     Brave Search (with throttling + 429 retry)
    semantic_scholar.py          S2 paper search (citations, DOIs, OA PDFs)
    arxiv.py                     arXiv Atom feed parser
    unpaywall.py                 DOI → OA PDF rescue
    academic.py                  S2 + arXiv facade with dedup
    fetch.py                     httpx + trafilatura (HTML) / MarkItDown (PDF)
    rerank.py                    Lexical + recency rerank before fetch budget spend
    structure.py                 Size-first routing: StructuredContent for long docs
    cache.py                     Diskcache for deterministic replay (keyed on day)

  patterns/                    Orchestration patterns (task-emission + prompts)
    single_researcher.py         Baseline: one analyzer per source + synthesizer
    maker_checker.py             VERIFY_CLAIM fan-out on top claims
    multi_perspective.py         Neutral / skeptic / advocate framings
    debate.py                    Affirmative / negative + judge
    ach.py                       Analysis of Competing Hypotheses

  tiering/
    simple.py                    URL reject-list (social media, aggregators)
    classifier.py                LLM tier classifier (1-5 + rationale + peer_reviewed)

  phases/
    termination.py               CHECK_TERMINATION_READY + VALIDATE_COMPLETION task emission

  replanner/
    replanner.py                 Bounded periodic replanner
    prompts.py                   Round 4/5 system prompt
    outputs.py                   SpawnSubQuestion / AbandonSubQuestion / EscalatePattern / NoOp

  server/                      FastAPI live UI
    app.py                       Routes + WebSocket
    runner.py                    Runs a session + publishes events
    events.py                    Event models + per-run session/subscription
    static/index.html            Single-page Cytoscape-based note graph viewer

  export/
    markdown.py                  Serialize note graph to runs/<id>/notes/*.md + report.md

  tools/                       Agent-callable tool functions (scaffold only)
```

## Key architectural properties

- **Typed data flow.** Every inter-stage hand-off is a Pydantic model.
  The scheduler only shuffles `Task` objects around; executors emit
  `TaskResult` with typed `NoteMutation` / `Task` / `DepEdgeAdd` /
  `abandoned_task_ids` fields. See [02-data-model.md](02-data-model.md).
- **Single writer to the note graph.** The scheduler's write lock is
  the only place note state changes, applied from `TaskResult`
  mutations handed back by executors. This is what keeps parallel task
  dispatch safe without per-note locking.
- **Deterministic scheduling, LLM execution.** The scheduler has zero
  LLM calls. All model calls happen inside task handlers; all state
  transitions happen in the scheduler. The boundary is load-bearing
  for testability and for the replay subcommand.
- **Role-to-model routing as config, not code.** Every task declares
  `(role, tier)` — never a model name. A `RoutingConfig` (YAML) maps
  that pair to an identifier sent to the LiteLLM router. Same code,
  different routing configs, yields the ablation matrix.
  See [10-routing-and-models.md](10-routing-and-models.md).
- **Cross-family invariant, structurally enforced.** `VERIFY_CLAIM`
  must route to a model family different from the one that produced
  the claim. The check runs at model-selection time inside the
  executor — it cannot be bypassed by prompt discipline.
- **Evidence grounding with quotes.** Every `ClaimItem` requires a
  non-empty `quote`. Every `source_note` carries a `url`, tier,
  rationale, and (for long documents) a `StructuredContent` outline.
- **Four-level confidence discipline.** (1) LLM semantic tier, (2)
  peer-review boolean, (3) triangulation, (4) preliminary-anchor cap
  at 0.80 for non-peer-reviewed. See
  [07-tiering-and-confidence.md](07-tiering-and-confidence.md).
- **Bounded replanner.** The replanner mutates the plan, not the data,
  and does so under a per-run budget. It cannot terminate the run;
  termination requires the structural + six-gate audit.
  See [08-replanner.md](08-replanner.md).

## What runs look like

The CLI run prints one line per task completion:

```
dra run=run_20260508_... routing=diverse_default query='...'
  ✓ LANDSCAPE_SURVEY abc123 — landscape_note note_xxx: 4 themes, 2 positions
  ✓ DECOMPOSE def456 — 3 sub-question(s) — ...
  ✓ QUESTION_SYNTHESIZE ... — 6 sources synthesized — BLUF: ... · 2 VERIFY_CLAIM spawned
  ✓ VERIFY_CLAIM ... — SUPPORTS: ...
  ...
  ✓ CHECK_TERMINATION_READY ... — PASS · 0 structural gap(s)
  ✓ VALIDATE_COMPLETION ... — PASS: ...
  ✓ WRITE_REPORT ... — report emitted as note note_yyy
✓ run complete
  tasks completed: 22
  notes in graph:  31
  report:          runs/run_.../report.md
```

Under the live UI, the same events stream into a Cytoscape graph
rendered in the browser, plus a Running Agents panel that shows
in-flight task cards (including synthetic cards for replanner cycles
that run outside the normal dispatch path).

## Reading order

If you're new to the codebase:

1. [02-data-model.md](02-data-model.md) — the shape of the data.
2. [04-scheduler-and-executor.md](04-scheduler-and-executor.md) — how
   tasks get run.
3. [03-pipeline-phases.md](03-pipeline-phases.md) — the four phases.
4. [05-orchestration-patterns.md](05-orchestration-patterns.md) — the
   five patterns the QS handler can run under.
5. [12-run-lifecycle.md](12-run-lifecycle.md) — puts it all together
   with an end-to-end walk.

Everything else is reference material for specific subsystems.
