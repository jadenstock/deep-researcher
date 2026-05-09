# Architecture Docs

Reference documentation for the current state of the deep-research-agent
codebase. Each document describes what a subsystem *is* — its types, its
flow, its failure behavior — not what it might eventually become.

## Contents

| # | Document | Scope |
|---|----------|-------|
| 01 | [System overview](01-overview.md) | Goals, pipeline shape, package layout, key invariants |
| 02 | [Data model](02-data-model.md) | Task graph, note graph, schemas, IDs, typed links |
| 03 | [Pipeline phases](03-pipeline-phases.md) | Landscape → Decompose → Deep Research → Completion & Report |
| 04 | [Scheduler and executor](04-scheduler-and-executor.md) | Dispatch loop, write lock, handler contract, task-result application |
| 05 | [Orchestration patterns](05-orchestration-patterns.md) | single_researcher / maker_checker / multi_perspective / debate / ACH |
| 06 | [Retrieval layer](06-retrieval-layer.md) | Brave / Semantic Scholar / arXiv / Unpaywall / fetch / rerank / structured content |
| 07 | [Tiering and confidence](07-tiering-and-confidence.md) | Reject list, LLM tier classifier, peer-review flag, confidence formula, language ladder |
| 08 | [Bounded replanner](08-replanner.md) | Cadence, budget, actions, cascade semantics |
| 09 | [Completion gates](09-completion-gates.md) | CHECK_TERMINATION_READY + VALIDATE_COMPLETION |
| 10 | [Routing and models](10-routing-and-models.md) | Role/tier/model resolution, cross-family invariant, ablation policy |
| 11 | [Live UI and observability](11-live-ui-and-observability.md) | FastAPI server, WebSocket events, token usage, logging, Logfire |
| 12 | [Run lifecycle](12-run-lifecycle.md) | End-to-end trace of a single run, files on disk, failure handling |

## Conventions

- Absolute paths are given relative to the repo root
  (`.../deep-research-agent/`).
- Module references use dot paths (`deep_research_agent.scheduler.scheduler`).
- Code snippets are lightly abridged for readability; the source file
  in the referenced module is authoritative.

## Quick start

- Entry point: `dra research "<query>"` (see `deep_research_agent.cli`).
- Live UI: `dra serve` then open <http://localhost:8000/>.
- Run artifacts: `runs/<run_id>/` — `report.md`, `notes/*.md`,
  `tasks.json`, `token_usage.json`, `run.log`.

For a 30-second summary, jump to [01-overview.md](01-overview.md).
