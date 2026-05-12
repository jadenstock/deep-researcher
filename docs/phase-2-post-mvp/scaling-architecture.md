# Scaling & architectural improvements

Goal: identify what has to change in the system's **shape** (not its
prompts or model choices) before a single-developer MVP becomes
something that can run many concurrent users, survive crashes, recover
partial work, and be operated by more than one person.

Scope discipline: each item below names a **structural property the
MVP does not have**, explains where the gap shows up in the current
code, and proposes the minimum viable version that closes it. We do
not try to design the final distributed system here — only the next
defensible step from where the code actually is.

---

## Where the MVP will break first

Ranked by "first thing that stops being acceptable as load grows."

| # | Limitation | Where it lives today | What breaks when load grows |
|---|---|---|---|
| 1 | **Note graph is in-memory only** | `agents/memory.py:NoteMemory` — plain dict + `asyncio.Lock` | Crash mid-run loses everything. No resumability. Can't inspect a run in flight from another process. |
| 2 | **One run per process, no queue** | `server/runner.py:run_session` launched inline from `server/app.py` | Concurrent users share a single event loop; a long Opus run blocks others. No back-pressure. No fairness. |
| 3 | **No cross-run caching** | `retrieval/fetch.py` fetches fresh per run; tier classification re-runs; search results not shared | Two users researching adjacent topics pay the full token + network cost twice. Fetch is the slowest part of a run. |
| 4 | **Rate limits coordinated per-process** | `retrieval/rate_limit.py:get_bucket` — in-process singleton | The moment there are 2 workers, the Brave 1 QPS limit is silently violated and we start eating 429s. |
| 5 | **Events are in-process pub-sub** | `server/events.py:RunSession.publish` direct to WebSocket clients | A restart drops every live viewer. No way to reconnect a user to a run in progress from a different server instance. |
| 6 | **No durable run log beyond `runs/<id>/`** | `server/runner.py:_dump_artifacts` writes only at end | If the process dies mid-run the filesystem has `run.log` but no `notes.json` / `report.*`. Partial state is recoverable only from memory, which is gone. |
| 7 | **PDF conversion blocks a worker thread** | `retrieval/fetch.py:_pdf_to_markdown` via `asyncio.to_thread` | One pathological PDF stalls 45s of a worker. At 10 concurrent runs, MarkItDown contention dominates wall time. |
| 8 | **Secrets + config read at import time** | `config.py:LocalConfig` reads `config/local.toml` from disk | No clean separation between "what model to use" (ops), "where to find the API key" (platform), and "what query to run" (user). Painful to containerize. |
| 9 | **No cost / quota enforcement** | `token_usage.py` tracks, but nothing **stops** a run | A single runaway researcher loop can burn an unbounded dollar amount. Acceptable for solo; fatal for multi-tenant. |
| 10 | **Observability is log lines + event stream** | `observability.py` + `run.log` | No tracing across agent hops; no SLO dashboard; no way to answer "why did run X cost $N and take Y minutes" without hand-reading logs. |

Items 1–5 are the ones that have to be addressed before *any* real
multi-user deployment. 6–10 are the ones that have to be addressed
before calling the system "operable."

---

## Recommended improvements

Sequenced by dependency order — later items assume earlier ones are
in place.

### 1. Persist the note graph

**Problem.** `NoteMemory` is a dict. A crash loses all notes, tool
results, and dispatch state. A running agent can't be inspected from
outside the process.

**What to build.** A thin persistence layer behind the existing
`NoteMemory` interface. Two sensible MVPs:

- **SQLite per run.** One `runs/<run_id>/graph.sqlite` with a
  `notes` table (id, type, version, content blob, json metadata) and
  a `note_edges` table derived from typed edges. Every `create` /
  `update` writes through. The existing asyncio lock becomes a
  transaction boundary. Portable, zero infra, trivially inspectable
  with `sqlite3`.
- **Postgres for the server build.** Same schema, shared database,
  `run_id` column everywhere. Required once multiple server
  instances share state.

**Why this is step 1.** Everything else (resume, multi-worker,
dashboards) assumes the note graph is queryable from outside the
Python process.

**Signal that it's working.** `sqlite3 runs/<id>/graph.sqlite
"SELECT type, count(*) FROM notes GROUP BY type"` works mid-run.

---

### 2. Checkpoint run state so a crashed run can resume

**Problem.** `drive_agent` in `agents/_run.py` runs a full agent loop
in memory. If the process dies between a tool call and the model's
next turn, the tool's side-effects (notes written) survive on disk —
but the **agent's conversation history and tool-call budget are gone**.
The researcher's "analyst dispatches remaining" counter is a closure
variable; the analyst's mid-loop message list is a pydantic-ai
in-memory object.

**What to build.** After every tool call, persist:
- the agent's `message_history` (pydantic-ai exposes it),
- its remaining budget(s),
- its `agent_id` / `run_id` / `parent_agent_id`.

At startup, the server checks for runs in a `RUNNING` state with no
live process and replays: load graph, load agent message histories,
reconstruct the researcher + any in-flight analysts, resume their
loops.

**Why it matters.** A 15-minute research run that dies 12 minutes in
should not have to restart from scratch. This is also what makes
"kill a worker during deploys" safe.

**Scope cut.** Don't try to resume mid-tool-call (e.g. a half-finished
PDF fetch). Tool calls are the atomic unit of progress; a resumed
run re-issues a tool call that didn't durably complete.

---

### 3. Move run execution off the request path

**Problem.** `server/app.py` launches `run_session` directly via
`asyncio.create_task`. The server process **is** the worker. One 20-
minute Opus run holds a WebSocket and an asyncio task on the same
process handling new requests.

**What to build.** Two-tier split:
- **API server** — accepts query, assigns `run_id`, enqueues a job,
  streams events back to the user from a durable event store.
- **Worker pool** — pulls jobs from the queue, runs `run_session`,
  publishes events to the store.

**MVP queue.** Redis Streams or Postgres `LISTEN/NOTIFY` are both
enough. Don't reach for Kafka. Don't reach for Celery — pydantic-ai
agents are async-native and Celery's sync worker model fights that.
A simple asyncio worker consuming a Redis Stream is sufficient.

**Why it matters.** This is the split that turns "one user at a
time" into "N workers serving a queue." It also makes cost caps
enforceable — a worker can kill a run that exceeds its budget
without taking the server down with it.

**Scope cut.** No autoscaling yet. Fixed worker count, Redis for
queue + event bus, one server in front. Autoscaling is step 7.

---

### 4. Durable event bus

**Problem.** `RunSession.publish` broadcasts in-memory to whatever
WebSocket clients happen to be connected. A user who refreshes the
page loses the run-so-far view. A server restart drops every live
viewer. A worker running on a different host can't tell the UI
anything.

**What to build.** An append-only event log per run in the shared
store (Redis Stream with `XADD` + `XREAD`, or Postgres `events`
table with `run_id, seq, ts, kind, payload_json`). The `EventPublisher`
writes here. The WebSocket handler reads from `seq=0` on connect,
then tails. A client reconnecting replays the whole run-so-far
deterministically.

**Why it matters.** This is what makes the UI survive restarts and
what lets the event stream become the source of truth for run
history (reconstructing `notes.json` from events is a bonus side
effect — you no longer need the end-of-run dump for history).

---

### 5. Shared fetch + tier cache across runs

**Problem.** Every run re-fetches URLs and re-classifies their
tier from scratch. `retrieval/fetch.py` and the tier classifier in
`agents/tools/search.py` (or wherever it lives) have no cross-run
store. Two users asking adjacent questions on the same day pay the
full latency + token cost twice. The CONTEXT doc claims "Tier
decisions are cached by URL" — this is aspirational; today the
cache is in-memory per run.

**What to build.** A small KV cache keyed on `(url, day_bucket)`
and on `(url, classifier_version)`:
- `fetched_content` (markdown + metadata + content_kind)
- `tier_classification` (tier + rationale + classifier_confidence)

Store blob in S3 / local disk, pointer row in Postgres. TTLs are
different for the two caches: content TTL ~7 days, tier
classification stable across the classifier version bump only.

**Why it matters.** Fetch + extract is the single slowest bucket in
an average run (trafilatura + PDF conversion dominate wall time).
Cross-run caching is where most cost/latency savings will actually
come from.

**Scope cut.** No semantic cache (embedding-based near-dup URL
matching) in MVP. Exact-URL cache is enough to capture most value.
Embedding dedup is a Phase-3 play.

---

### 6. Coordinate rate limits across workers

**Problem.** `retrieval/rate_limit.py:get_bucket` is an in-process
singleton. With 1 worker it respects Brave's 1 QPS cap; with 4
workers it silently violates it and we start eating 429s + (eventually)
bans.

**What to build.** A Redis-backed leaky-bucket / token-bucket shared
by all workers. Lua script for the atomic acquire. Same
`get_bucket(name, rate)` API so calling code doesn't change.

**Why it matters.** Without this, step 3 (multi-worker) silently
corrupts external API behavior. This is a small change but a
strict prerequisite for parallel workers.

---

### 7. Cost / budget enforcement at the worker

**Problem.** `TokenUsageTracker` (`token_usage.py`) is observational.
A researcher that decides to call `investigate_question` 50 times
in a pathological loop is bounded only by `DEFAULT_ANALYST_BUDGET=8`
— and nothing ties that budget to dollars. If the budget is raised
for a hard query, a loop can burn arbitrarily.

**What to build.** A per-run dollar cap propagated through `Deps`.
The `drive_agent` wrapper checks after each model call: if
cumulative cost for this run exceeds the cap, raise a terminal
`RunBudgetExceeded`. The worker catches it, marks the run
`BUDGET_EXCEEDED`, and commits whatever partial report exists
(same fallback path as today's exception branch).

**Why it matters.** This is the difference between "deploy to
real users" and "hope no one crafts a query that costs $400."
Operationally mandatory.

---

### 8. Observability — tracing + structured metrics

**Problem.** Today's debugging loop is `tail -f runs/<id>/run.log`
plus reading `token_usage.json` at the end. Acceptable for one
developer. Useless when three runs are happening in parallel on a
shared worker and one is slow for non-obvious reasons.

**What to build.** OpenTelemetry spans around the load-bearing
boundaries: `research_run`, `landscape_run`, `analyst_run`,
`scout_run`, `fetch_and_extract`, each model call. Propagate
`run_id` + `agent_id` in the span context. Emit traces to
whatever backend (Tempo, Honeycomb, Datadog — choice is a
deployment detail).

Parallel: structured metrics (Prometheus / OTel metrics):
- per-run wall-clock time
- per-run dollar cost (from the tracker)
- per-agent-type count and p50/p95 duration
- fetch cache hit rate (step 5)
- 429 / rate-limit hits per provider (step 6)

**Why it matters.** You cannot tune or debug the system at scale
without this. The ablation experiments in `ablation-ideas.md`
already ask for per-run metric extraction; an OTel metrics pipeline
is the same infrastructure generalized.

**Scope cut.** No custom dashboards in MVP — traces + a raw metrics
endpoint are enough to run the system. Dashboards are a follow-up
that depends on which backend you pick.

---

### 9. Config + secrets split

**Problem.** `config.py:LocalConfig` reads `config/local.toml`.
Routing reads `config/routing_diverse.yaml`. Secrets are
environment variables mixed into the same TOML. Works for one
developer; doesn't containerize cleanly.

**What to build.** Three-layer config:
- **Static ops config** (routing YAML, budgets, feature flags) —
  baked into the container image or mounted read-only.
- **Secrets** (API keys) — injected via env vars, never on disk.
- **Per-request config** (model overrides, analyst budget, dollar
  cap) — carried on the run job payload.

Nothing fancy — pydantic-settings + environment variables is the
boring, correct answer. The change is mostly discipline (don't
read files from inside agent code; pass `Deps.routing` through).

**Why it matters.** Required for any deployment that isn't "run
from a developer laptop." Also clarifies which settings are
per-run vs. per-deployment — a distinction that currently isn't
enforced anywhere.

---

### 10. Horizontal run isolation

**Problem.** Today's `Deps` carries an `httpx.AsyncClient`, a
`NoteMemory`, an `EventPublisher`, and the tracker. One crashed
run can corrupt shared state (the process singleton for rate
limits, the per-module `MarkItDown()` instance, the shared HTTP
client). A leak in one run affects the next.

**What to build.** Each run gets its own `Deps` already (good).
Extend the discipline: the worker process treats a run as a
subprocess or at least an asyncio task with a strict cleanup
contract. Kill the whole task on timeout; recycle the worker
process after N runs to bound memory growth (MarkItDown + pdfminer
have known leak patterns).

**Why it matters.** Makes the worker a reliable unit of isolation.
Prerequisite for safe autoscaling.

---

## Suggested order

1. **Persist the note graph (step 1).** Unlocks every other
   observability + recovery story.
2. **Checkpoint + resume (step 2).** Makes long runs operationally
   tolerable. Cheap once step 1 is done.
3. **Move execution to a worker (step 3) + durable event bus
   (step 4).** These are the same engineering effort; do them
   together. This is the multi-user unlock.
4. **Shared fetch/tier cache (step 5).** Biggest cost + latency
   win post-architectural. Depends on step 1 for schema, not on
   step 3.
5. **Distributed rate limits (step 6).** Hard prerequisite *before*
   step 3 actually goes multi-worker in production.
6. **Cost cap (step 7).** Has to land before opening to real users.
7. **Observability (step 8).** Needed to debug everything above.
8. **Config / secrets split (step 9).** Independent; do whenever the
   first container build happens.
9. **Worker isolation (step 10).** Last; hardens the shape rather
   than creating new capability.

---

## Appendix — out of scope (deliberately)

- **Distributed note graph (sharding across nodes).** A single
  Postgres can hold every note from every run we can reasonably
  expect at this stage. Don't shard early.
- **Embedding index over the note graph.** CONTEXT explicitly rejects
  this as "not a general-purpose RAG system." Keep that stance
  through Phase 2; revisit only if `load_note` + typed edges turn
  out to be insufficient for agent navigation.
- **Cross-run persistent memory.** CONTEXT: "Every run starts fresh;
  no cross-session memory." Keep that invariant — it simplifies
  privacy and caching reasoning. The fetch + tier cache (step 5)
  is not cross-session memory; it's provider-side artifact caching,
  which is a different thing.
- **Fine-tuning / eval-guided routing policy updates.** Project is
  API-only by charter. Routing is config; tuning it is a data
  question, not an architecture one.
- **Multi-region / HA deployment.** One region, one cluster is fine
  until usage warrants otherwise. Don't design for global before
  there's a user load that needs it.
- **Replacing pydantic-ai.** The agent loop abstraction is
  load-bearing and the project's investment in it is deep.
  Swapping is not an architectural improvement — it's a rewrite.
