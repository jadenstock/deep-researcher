# Architecture

How the deep-research agent actually works. Read
[codebase-map.md](codebase-map.md) alongside this for a module-by-module view.

---

## Agent hierarchy

Four agent types. Parents dispatch children by calling a tool; each child
runs its own pydantic-ai loop and returns a typed payload.

```
                        researcher           (root; generative HIGH)
                       /           \
                      /             \
               landscape           analyst    (generative MID; or judgment MID in verify/adversarial)
                                     |
                                   scout      (cheap_deterministic MID)
```

- **researcher** (`agents/researcher.py`). Top-level orchestrator. Reads the
  landscape brief, decomposes the query, dispatches analysts in parallel,
  and commits the final report. Never sees raw source content — only
  analyst syntheses.
- **landscape** (`agents/landscape.py`). Wide-filter scouting pass that runs
  before decomposition. Up to 4 rounds of search, creates `SCOUTED` source
  notes, commits a ~300-600 word markdown brief that tells the researcher
  what the terrain looks like.
- **analyst** (`agents/analyst.py`). Investigates one specific sub-question
  end-to-end. Dispatches scouts for retrieval, deep-reads sources via
  `load_note`, records readings (with verbatim quotes) on source notes, and
  commits a `QuestionSynthesis` to its assigned question note.
- **scout** (`agents/scout.py`). Retrieval + triage. Runs search, creates
  source notes, skims content (`scout_fetch`), optionally traverses
  citations (`find_related_papers`), and commits a pre-digested sourcelist
  with tier/relevance guesses. Never reads sources deeply.

The intent of the split: the researcher's context stays full of **signal**
(syntheses, question states, source metadata), never SERP debris or raw
page text. Each layer's job is summarised below its layer.

## Dispatch modes

`investigate_question(question, mode)` on the researcher takes a `mode`
argument. This is the main lever the researcher has for controlling the
investigation's shape.

| Mode | Role class | Typical use |
|---|---|---|
| `explore` | `GENERATIVE` | Default. Fresh investigation of a new sub-question. |
| `verify` | `JUDGMENT` | Independently re-check a specific prior claim. Must route to a different model family than the `explore` that produced the claim. |
| `adversarial` | `JUDGMENT` | Steelman the opposite of a prior adopted position on a `contested` sub-question. |

The `verify`/`adversarial` modes prepend a **mode-framing** block to the
analyst's system prompt (see `MODE_FRAMING` in `agents/analyst.py`) so the
judgment-family model isn't just re-running the explore's investigation —
it comes in with falsification discipline.

## The note graph

All agents share one `NoteMemory` (`agents/memory.py`) keyed by `NoteID`.
A `Note` has:

- `id`, `type` (`QUESTION`, `SOURCE`, `LANDSCAPE`, `SYNTHESIS`, …),
  `title`, `description`, `content`
- `metadata` — a discriminated union keyed by `type` (see
  `schemas/note.py`). `SourceNoteMetadata` carries URL, tier, peer-review
  flag, readings; `QuestionMetadata` carries status, parent link, report
  markdown when answered; etc.
- `links` — typed edges to other notes (`cites`, `supports`, `refutes`, …).
- `version`, `created_at`, `last_modified_at`.

The graph is async-safe: `create` and `update` take a lock; reads are
lock-free (stale reads are acceptable). An optional `EventPublisher` is
notified on every mutation — that's how the UI streams the note graph.

### Key invariants

- **Verbatim quotes.** Every `ClaimItem` on a source note's readings
  carries a non-empty `quote` pulled directly from the content the analyst
  read. No quote → no claim.
- **Append-only readings.** Two analysts investigating different
  sub-questions can each read the same source; each appends a
  `ReadingEntry` tagged with its `by_agent_id` + `for_question_id`. No
  overwrites.
- **First-writer-wins on source-intrinsic fields.** `tier`,
  `peer_reviewed`, `summary` are set once (usually by the first reader)
  and stay put. Per-analyst judgments live on per-analyst readings.
- **URL-keyed dedup.** `create_source_note` normalizes and dedupes by URL
  so concurrent scouts never create parallel copies of the same source.

### Note types in practice

- `SOURCE` — every URL anyone pulls in. Lifecycle `SCOUTED` → `FETCHED`
  (scout fetched content) → `ANALYZED` (at least one reading exists).
- `QUESTION` — the root (user query) plus each sub-question. An analyst
  "answers" a question by updating its metadata in place
  (`status=SYNTHESIZED`, `report_markdown=…`, `confidence`, `sources_cited`).
- `LANDSCAPE` — the landscape brief note.
- `SYNTHESIS` — fallback note used only when the researcher ends without
  calling `answer_question` on the root, so the server still has
  *something* to surface in the UI's report tab.

## Control flow (single run)

```
build_deps(local, routing, events, run_config)  # shared NoteMemory, clients, tracker
  ↓
research_run(deps, query)                       # agents/researcher.py
  ├─ create root QUESTION note
  ├─ landscape_run(deps, query)                 # unless run_config.skip_landscape
  │    └─ landscape agent → write_landscape_brief (commit)
  └─ researcher agent loop:
       get_research_state → decide → investigate_question(s) in parallel
         └─ analyst_run(deps, qid, q, mode)
              ├─ list_source_notes (inventory shared corpus)
              ├─ scout(request) in parallel × N  (per-analyst scout budget)
              │    └─ scout agent: search_web / search_academic
              │       + create_source_note + scout_fetch
              │       + find_related_papers
              │       → commit_scout_result
              ├─ load_note on promising sources (deep read)
              ├─ update_source_after_reading (append ReadingEntry with claims)
              └─ answer_question (commit; updates QUESTION note)
       … more rounds …
       answer_question on root (commit final report)
```

### Budgets

Budgets live as closure-scoped counters owned by the agent whose tool
decrements them. Their starting values come from the run-scoped
`RunConfig` on `deps.run_config` (`agents/run_config.py`):

- **Analyst budget** — max analyst dispatches per run
  (`DEFAULT_ANALYST_BUDGET = 12`). Read in `research_run` and passed
  into `build_researcher(..., analyst_budget_start=...)`; decremented
  by the closure-scoped `investigate_question` tool. When 0 the tool
  raises `ModelRetry` asking the researcher to commit.
- **Scout budget (per analyst)** — max scout dispatches one analyst
  may make (`DEFAULT_SCOUT_BUDGET_PER_ANALYST = 6`). Read in
  `analyst_run` and passed into `build_analyst(...,
  scout_budget_start=...)`; decremented by the closure-scoped `scout`
  tool.
- **Scout search budget (per scout)** — shared ceiling across a
  scout's search tools (`DEFAULT_SCOUT_SEARCH_BUDGET = 16`, covers
  `search_web` + `search_academic` + `find_related_papers`
  combined). Read in `scout_run` and passed into `build_scout(...,
  search_budget_start=...)`; the three search tools share one
  closure counter so the scout can trade breadth for citation
  traversal without a separate pool.

Budgets are backstops. The agents' prompts push them toward doing less than
the cap.

### Per-run knobs (`RunConfig`)

`RunConfig` (`agents/run_config.py`) is a frozen dataclass attached to
`Deps`. The CLI uses defaults; the server accepts an optional `config`
payload on `POST /api/run` and builds one via `RunConfig.from_payload`
(values are clamped to the slider ranges defined in the same module).
Fields:

- `analyst_budget`, `scout_budget_per_analyst`, `scout_search_budget`
  — the three counters above.
- `model_overrides: dict[(TaskTier, RoleClass), str]` — per-slot
  routing overrides. Applied by `apply_to_routing` inside `build_deps`
  so agent code still resolves models via
  `deps.routing.model_id_for(role, tier)` and never sees the override
  directly.
- `skip_landscape: bool` — when `True`, `research_run` skips
  `landscape_run` entirely; the researcher starts with no brief and no
  pre-scouted corpus. Used for A/B comparisons of the landscape step.

### Root-question ID

The root question id is passed into `build_researcher(..., root_question_id=...)`
and closed over by the `get_research_state` and `investigate_question`
tools, so the researcher can discover its own root without threading it
through prompts and without any shared mutable dict.

## Tools

Tools live in `agents/tools/`. Every tool is decorated with
`@instrumented` (`agents/events.py`) which emits `tool_call_start` /
`tool_call_end` events tagged with the current agent's `agent_id` (via a
`ContextVar`, so `asyncio.gather` fan-outs tag correctly).

### By agent

| Agent | Tools it gets |
|---|---|
| researcher | `get_research_state`, `load_note`, `answer_question`, `investigate_question` |
| landscape | `search_web`, `search_academic`, `create_source_note`, `list_source_notes`, `write_landscape_brief` |
| analyst | `scout`, `list_source_notes`, `load_note`, `update_source_after_reading`, `answer_question` |
| scout | `search_web`, `search_academic`, `find_related_papers`, `create_source_note`, `list_source_notes`, `scout_fetch`, `commit_scout_result` |

### Terminal tools

Each agent has one *terminal* tool that commits its structured output.
Where possible, the commit lands on the note graph (the only shared
mutable surface); scout's output is genuinely ephemeral so it commits
into a closure-scoped outbox owned by `build_scout` instead.

- landscape → `write_landscape_brief` (updates the LANDSCAPE note
  pre-created by `landscape_run`)
- analyst → `answer_question` (updates assigned QUESTION note; the
  wrapping `analyst_run` reconstructs `QuestionSynthesis` from the note)
- researcher → `answer_question` (on root)
- scout → `commit_scout_result` (closure tool inside `build_scout`; writes
  into an outbox list that `scout_run` reads after the agent returns)

This pattern — commit via a tool call rather than a structured final
message — means invalid payloads surface as `ModelRetry` and the model
naturally retries within the same turn. It also means a durable record
lands in memory (for note-backed commits) even when the agent's wrapping
message stream is truncated or crashes afterwards.

## Model routing

`config.RoutingConfig` maps `(role_class, task_tier)` → `model_id`.
Resolution happens at agent construction time via
`routing.model_id_for(role, tier)` → `agent_factory.make_model(model_id,
local)`.

| Agent / mode | Role | Tier | In the default policy |
|---|---|---|---|
| researcher | `GENERATIVE` | `HIGH` | Claude Opus |
| landscape | `GENERATIVE` | `MID` | Claude Sonnet |
| analyst (`explore`) | `GENERATIVE` | `MID` | Claude Sonnet |
| analyst (`verify` / `adversarial`) | `JUDGMENT` | `MID` | GPT (different family) |
| scout | `CHEAP_DETERMINISTIC` | `MID` | Claude Haiku |

The "family" is the part before `/` in a `family/model` identifier. That
prefix is a local convention — the router receives the bare model name.
It's used for the cross-family invariant: a `verify` of a claim extracted
by family X must run on a model from family Y.

All calls go through the OpenAI-compatible endpoint in `local.toml`
(typically a LiteLLM router). `agent_factory.make_model` pins
`max_tokens=16384` because the upstream default truncated
`answer_question` tool-call args mid-report.

Per-run model overrides live on `RunConfig.model_overrides` and are
merged into `routing` inside `build_deps` (see above). The routing
YAML stays the default policy; the UI surfaces a curated `MODEL_CATALOG`
from `agents/run_config.py` for its dropdowns.

## Observability

Two event surfaces:

1. **Logs.** Standard `logging` with per-run log files in `runs/<id>/run.log`
   (attached via a `ContextVar` filter in `server/runner.py`, so concurrent
   server runs don't cross-contaminate). Logfire can be enabled via
   `local.toml` (see `observability.py`).
2. **Events.** `EventPublisher` protocol (`agents/events.py`) emits
   `agent_start`, `agent_done`, `note_created`, `note_replaced`,
   `tool_call_start`, `tool_call_end`, `token_usage`. The CLI path wires a
   `NoOpPublisher`; the server wires a `SessionPublisher` that forwards to
   a per-run `RunSession` whose WebSocket handler replays history on
   connect then streams new events.

Token usage is tracked per-agent-per-model in `TokenUsageTracker`
(`token_usage.py`). It's populated from `run.usage()` in every `*_run`
wrapper's `finally` block, so partial token burn on crashes still lands.

## Artifacts

Each run writes to `runs/<run_id>/`:

- `report.md` — human-readable final report. Composed by
  `compose_report_markdown` (handles happy path + crash/partial
  reconstruction from answered sub-question notes + sources appendix).
- `report.json` — typed `ResearcherReport` payload (success path only).
- `notes.json` — full note graph dump.
- `run_summary.json` — pre-built summary (query, started/finished
  timestamps, status, tokens, note counters). Mirrors
  `GET /api/run/{run_id}/summary` so the history index can list runs
  without re-parsing `notes.json`. Written on both success and
  partial paths; legacy runs without it fall back to on-the-fly
  summarization.
- `token_usage.json` — per-model token breakdown.
- `run.log` — per-run DEBUG log (server path only).

## Failure handling

Everything is structured to degrade rather than fail:

- Every `*_run` wrapper uses `agent.iter()` so `run.usage()` is readable
  from a `finally` block even when a deep tool call raises.
- If an agent ends without calling its terminal tool, the `*_run` returns
  a sensible fallback (empty `ScoutResult` with a coverage note;
  low-confidence `QuestionSynthesis` with an `open_issues` entry; etc.).
- The CLI/server paths always dump whatever's in memory, even on a run
  crash. A researcher that crashes mid-investigation still produces a
  `report.md` reconstructed from answered sub-question notes.

## Why this shape

- **Agents are real tool-using loops, not choreographed steps.** There's
  no central scheduler deciding what to run — the researcher decides.
  Budgets and prompts shape behavior; tools are the only contract.
- **The note graph is the only shared state.** Agents don't pass data
  through prompts (beyond opening messages and tool returns). This means
  any agent can pick up where another left off, concurrent dispatches
  can't corrupt each other, and the UI's view == the agents' view.
- **Context hygiene is structural, not hortatory.** The researcher *can't*
  read raw source content because it doesn't have the `fetch_url` or
  `update_source_after_reading` tools. The analyst *can't* eat SERP debris
  because `search_web` isn't in its tool set — only `scout` is.
