# Codebase map

Module-by-module tour of `src/deep_research_agent/`. For *how the pieces
fit together*, read [architecture.md](architecture.md) first.

```
src/deep_research_agent/
├─ cli.py                CLI entry point (`dra research` / `dra serve`)
├─ config.py             LocalConfig (TOML) + RoutingConfig (YAML) loaders
├─ agent_factory.py      model_id → pydantic-ai OpenAIChatModel
├─ observability.py      Silences noisy third-party loggers
├─ token_usage.py        Per-agent-per-model token tracker
├─ run_id.py             `new_run_id()` — shared CLI/server id format
├─ run_artifacts.py      Writes notes.json / report.md / report.json to a run dir
├─ _time.py              `utc_now()` helper shared across layers
├─ schemas/              Typed domain models (notes, sources, enums, IDs)
├─ retrieval/            HTTP clients: Brave, Semantic Scholar, arXiv, fetch
├─ agents/               Agent loops + shared memory + tools + run_config
└─ server/               FastAPI app, WebSocket, live UI + on-disk history
```

## Top level

**`cli.py`** — `dra research "query"` runs one session headless and writes
artifacts under `runs/<run_id>/`. `dra serve` starts the FastAPI app.
Both paths share `research_run` from `agents/researcher.py`.

**`config.py`** — two config shapes:
- `LocalConfig` (TOML, gitignored): `llm.api_base_url`, `llm.api_key`,
  retrieval API keys, rate-limit overrides.
- `RoutingConfig` (YAML, tracked): `tiers[LOW|MID|HIGH]` each with
  `generative` / `judgment` / `cheap_deterministic` → model_id strings.
  Profiles: `routing_lean.yaml` (default; Haiku 5.5 + Luna-high) and
  `routing_diverse.yaml` (Haiku/Sonnet/Opus 5.5 + GPT-6 Luna/Sol/Astra).

**`agent_factory.py`** — pure glue. Takes a routing model_id like
`anthropic/claude-opus-5-5`, strips the family prefix, and builds an
`OpenAIChatModel` pointed at the local endpoint. Pins
`max_tokens=16384`. A `:<effort>` suffix (`openai/gpt-6-luna:high`) is
sent as `reasoning_effort`. Claude models get LiteLLM
`cache_control_injection_points` (system prompt + trailing message) so
each tool turn reads the previous turn's prefix from the prompt cache;
GPT models cache automatically.

**`observability.py`** — pins noisy third-party loggers (pdfminer,
httpx, urllib3, …) at WARNING so their DEBUG streams don't drown real
errors. Called once at startup from `cli.py`.

**`token_usage.py`** — `TokenUsageTracker` aggregates
`RequestUsage` snapshots keyed by `(agent_id, agent_type, model_id)`.
Produces a rich-format table for logs and a JSON dump for artifacts.

**`run_id.py`** — `new_run_id()` returns `YYYYMMDDTHHMMSS-xxxxxxxx`.
One-stop formatter so the CLI, server, and on-disk history reader all
agree on the id shape. `server/history.py` guards against path
traversal with the same regex.

**`_time.py`** — tiny `utc_now()` helper. Every timestamp in the note
graph comes from here so the schemas layer, agent loops, and server
never drift on tz-awareness.

**`run_artifacts.py`** — `persist_run_artifacts(run_dir, notes,
report_markdown, report_json, run_summary)` writes `notes.json` +
`report.md` (+ optional `report.json` + optional `run_summary.json`)
in parallel. Shared by the CLI path and `server/runner.py` so both
dump the same artifact shape. Also hosts `summarize_notes` (the
shared note-counter helper used by both the live and on-disk summary
endpoints) and `build_run_summary` (assembles the `run_summary.json`
payload, which mirrors `GET /api/run/{run_id}/summary` so the
history index can skip re-parsing `notes.json`). Token usage is
intentionally left out — callers save it separately so even a failed
main dump still leaves a usable `token_usage.json` on disk.

## `schemas/`

Pure pydantic models. No behavior.

- **`enums.py`** — `NoteType`, `SourceState` (SCOUTED/FETCHED/ANALYZED),
  `Tier` (1..5), `QuestionClassification`, `RoleClass`, `TaskTier`,
  `ClaimType`, `VerificationStatus`.
- **`ids.py`** — `NoteID`, `SourceID`, `RunID` newtypes.
- **`note.py`** — `Note` proper plus the discriminated
  `NoteMetadata` union (`LandscapeMetadata`, `SourceNoteMetadata`,
  `QuestionMetadata`, `SynthesisMetadata`, …).
- **`source.py`** — `SourceMetadata` (the payload behind a source note),
  `ReadingEntry`, `ClaimItem`, `StructuredContent`. Source-note
  semantics live here: append-only `readings`, per-analyst quoted
  claims, tier + peer-review flags, content-kind classification.

## `retrieval/`

Low-level HTTP clients. No agent awareness — they produce `SearchHit` /
`FetchResult` dataclasses.

- **`brave.py`** — Brave Web Search client. Free-tier-aware rate limiting.
- **`semantic_scholar.py`** — S2 search + citations/references traversal
  (`get_citations`, `get_references` accept `DOI:…` and `ARXIV:…` paper
  ids).
- **`arxiv.py`** — arXiv API client with its own rate limiter.
- **`fetch.py`** — `fetch_and_extract(url)` — HTML (trafilatura) and PDF
  (MarkItDown, capped at 15MB / 20 pages) extraction to markdown.
- **`rate_limit.py`** — shared async semaphore + min-interval helpers.
- **`_http.py`** — shared retry loop used by Brave and Semantic Scholar:
  honors `Retry-After` on 429s with an exponential-backoff floor and a
  total-wait cap, plus an independent short-budget retry for transient
  transport errors (DNS blips, connection resets, read timeouts) so a
  flaky network moment doesn't eat into the 429 budget.
- **`__init__.py`** — `apply_retrieval_rate_limits(local.retrieval)` runs
  once at startup and programs the clients' intervals from config.

## `agents/`

All agent code and shared runtime state.

- **`deps.py`** — `Deps` dataclass passed to every agent via
  `RunContext[Deps]`. Holds the shared `NoteMemory`, retrieval clients,
  config, token tracker, event publisher, shared `httpx.AsyncClient`,
  and the per-run `RunConfig`. Immutable after construction —
  run-scoped mutable state (budgets, root-question id) lives in
  `build_*` closures owned by the agent that consumes it; the note
  graph is the only shared mutable surface between agents. `build_deps`
  applies `RunConfig.model_overrides` onto `routing` so downstream
  agent code resolves models through a single effective table.
- **`run_config.py`** — `RunConfig` frozen dataclass: per-run budgets
  (`analyst_budget`, `scout_budget_per_analyst`,
  `scout_search_budget`), a `model_overrides` map, and a
  `skip_landscape` toggle. `from_payload` builds one from the
  server's optional API payload (values clamped to slider ranges).
  `apply_to_routing` returns a new `RoutingConfig` with override slots
  swapped. `defaults_payload` produces the JSON served by
  `GET /api/config/defaults` so the UI sliders/dropdowns never
  hardcode defaults.
- **`memory.py`** — `NoteMemory`. Async-safe dict of `NoteID → Note`.
  Lock-serialized mutations, lock-free reads, URL-normalized dedup on
  source lookup, publisher callbacks on every create/update.
- **`schemas.py`** — tool-return / commit payloads: `SearchResult`,
  `FetchedContent`, `ScoutedSource`, `ScoutResult`,
  `QuestionSynthesis`, `ResearcherReport`, plus the
  `compose_report_markdown` helper used by both CLI and server dump
  paths.
- **`events.py`** — `EventPublisher` protocol, `NoOpPublisher`, the
  `_CURRENT_AGENT_ID` contextvar, and the `@instrumented` tool
  decorator that tags tool-call events with the currently running
  agent's id.
- **`_debug.py`** / **`_usage.py`** / **`_run.py`** — helpers called
  from every `*_run` wrapper. `log_run_node` walks the pydantic-ai
  `agent.iter()` node stream into the logger; `record_run_usage` posts
  `run.usage()` into the `TokenUsageTracker` and emits a `token_usage`
  event; `drive_agent` captures the shared iterate-and-log pattern
  (set agent-id contextvar, publish `on_agent_start`, iterate the run
  with logging + usage recording, publish `on_agent_done(ABANDONED)`
  on exception). Each `*_run` caller still owns reading its committed
  output, choosing a fallback, and publishing `on_agent_done(DONE)`.

### Agent loops

Each file exposes `build_<name>(deps, …) -> Agent` plus an async
`<name>_run(deps, …) -> <CommitPayload>` wrapper. Wrappers handle:
setting the `_CURRENT_AGENT_ID` contextvar, emitting `on_agent_start` /
`on_agent_done`, logging, crash-safe usage recording, and fallback
return values when the agent ends without committing.

- **`researcher.py`** — top-level director. Creates root QUESTION note,
  runs landscape, builds the researcher agent with closure-scoped
  `get_research_state` and `investigate_question` tools (the dispatch
  tool + analyst-budget counter live in the closure), runs the
  iterative loop, assembles a `ResearcherReport` from the root note.
- **`landscape.py`** — wide-filter scout pass. Pre-creates the
  LANDSCAPE note on entry; the agent's `write_landscape_brief` tool
  updates it in place. 4-round soft cap, terminates on diminishing
  returns.
- **`analyst.py`** — investigates one sub-question. `AnalystMode` is
  `explore` | `verify` | `adversarial`; mode selects the system-prompt
  framing block AND the routing `(role, tier)` (explore →
  generative, verify/adversarial → judgment). Builds with a
  closure-scoped `scout` tool + scout-budget counter. Commits its
  answer by updating the assigned QUESTION note in place;
  `analyst_run` reconstructs `QuestionSynthesis` from the note on
  return.
- **`scout.py`** — retrieval + triage sub-agent. Runs on the cheap
  deterministic tier. `build_scout` returns `(agent, outbox)` where
  `outbox` is a closure-owned `list[ScoutResult]` that
  `commit_scout_result` (registered as a closure tool) writes into;
  `scout_run` reads the last entry on return.

### `agents/tools/`

Functions registered via `Agent.tool(...)`. All async, all decorated
with `@instrumented`.

- **`notes.py`** — note-graph tools. `create_source_note`,
  `update_source_after_reading`, `load_note`, `list_source_notes`,
  plus the terminal commits `answer_question` and
  `write_landscape_brief` (which updates the LANDSCAPE note
  pre-created by `landscape_run`). This is the longest file in the
  agents layer and the most important one to read when tracing
  behavior. Tools that need run-scoped state (`get_research_state`,
  `investigate_question`, `scout`, `commit_scout_result`) live as
  closures inside their owning `build_*` function, not here.
- **`search.py`** — `search_web`, `search_academic`,
  `find_related_papers` (S2 citation traversal).
- **`fetch.py`** — `fetch_url` (general markdown extract) and
  `scout_fetch` (scout-specific: fetches, extracts, writes to
  `note.content`, classifies `content_kind`, returns a short preview).

## `server/`

FastAPI app + live UI. Mirrors the CLI path but streams events.

- **`app.py`** — FastAPI app factory (`create_app`). Endpoints:
  - `GET /` — serves `static/index.html`.
  - `POST /api/run` — spawn a run with an optional `config` payload
    (parsed into a `RunConfig`), return `{run_id}`.
  - `GET /api/config/defaults` — budget defaults + slider ranges +
    model catalog + current routing defaults. Feeds the UI's Settings
    panel so nothing in the frontend hardcodes a default.
  - `GET /api/runs` — list in-process runs (current server lifetime).
  - `GET /api/history` — list completed runs on disk under `runs/`,
    newest first. Complements `/api/runs` for pre-restart runs.
  - `GET /api/history/{run_id}/notes` — note graph from the on-disk
    `notes.json`.
  - `GET /api/history/{run_id}/report` — `report.md` contents.
  - `GET /api/history/{run_id}/summary` — on-disk summary (tokens,
    note counts, duration).
  - `GET /api/note/{run_id}/{note_id}` — fetch a live note's JSON
    (used by the UI's report / node-detail tabs).
  - `GET /api/run/{run_id}/summary` — end-of-run debrief for a live
    run (tokens, note counts, duration).
  - `WS /api/ws/{run_id}` — replay history on connect, then stream live
    events.
- **`runner.py`** — `run_session(session, …)` runs one research session
  against a `RunSession`. Wires a `SessionPublisher` (implements
  `EventPublisher`) into `build_deps`. Dumps the same artifacts as the
  CLI. Attaches a per-run `FileHandler` to the root logger filtered by a
  `contextvars`-based run id so concurrent server runs get clean
  `run.log` files.
- **`events.py`** — `RunSession` (per-run event history + subscriber
  queues), `SessionRegistry` (`run_id → RunSession`), and typed event
  constructors (`event_agent_started`, `event_note_created`,
  `event_tool_call_end`, …).
- **`history.py`** — read-only view of completed runs persisted under
  `runs/`. `SessionRegistry` only remembers the current process's
  runs; this module serves the complementary view from disk. Validates
  run ids against the `run_id.py` format (guarding path traversal and
  ignoring legacy `run_*_xxxx` directories) and exposes
  `list_history` / `read_notes` / `read_report_md` / `summarize`. Prefers
  the pre-built `run_summary.json` for both `list_history` and
  `summarize` and only falls back to parsing `notes.json` for legacy
  runs that predate the summary artifact. Disk reads are wrapped in
  `asyncio.to_thread` at the endpoint layer.
- **`static/index.html`** — single-page live UI. Agents-running panel,
  note graph, tool-call ticker, report viewer, token usage table.
  Fetched with `Cache-Control: no-store` so iteration on the frontend
  doesn't require a hard refresh.

## External contracts, at a glance

| Surface | What it is | Who calls it |
|---|---|---|
| `config/local.toml` | Endpoint + keys + rate-limit overrides | Loaded at startup by `cli.py` and `server/app.py` |
| `config/routing_*.yaml` | `(role, tier) → model_id` policy | Loaded once, read via `routing.model_id_for(role, tier)` |
| `runs/<run_id>/` | Artifacts: report.md, report.json, notes.json, token_usage.json, run.log | Written by CLI path and `server/runner.py` |
| `/api/ws/{run_id}` | Event stream (JSON-per-message) | UI's single-page client |

## What's *not* in the codebase

The current architecture has no:

- Central scheduler / task graph / deterministic dispatcher.
- Separate `SEARCH` / `SCAN_SEARCH_RESULTS` / `FETCH_AND_EXTRACT` /
  `ANALYZE_SOURCE` task nodes.
- Explicit replanner, completion gates, or pattern catalogue.
- `tiering/`, `confidence.py`, `phases/`, `replanner/`, `patterns/`,
  `export/`, `scheduler/`, `executor/` modules.

The codebase is agentic: budgets + prompts + tools do the work that a
scheduler/task-graph would.
