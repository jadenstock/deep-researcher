# deep-research-agent

Evidence-grounded deep research agent. Takes a natural-language query, runs a
four-phase pipeline (landscape survey → decomposition → deep research →
completion & report), and produces an Analytic Pyramid-structured report with
claim-level traceability to quoted sources.

The core data structure is a typed, versioned **note graph** — every claim,
source, question, synthesis, decision, and hypothesis is a typed node with
typed links. Agents communicate only through it. Rendering the graph to any
particular format (markdown bundle, viewer, diagram) is a separate concern
addressed by the `export/` layer, not part of the core architecture.

Implements the v4 technical design. Architecture and decision record are
design-tracked locally (not in this repo).

## Status

Pre-implementation. Scaffolding + core data models only.

## Setup

```bash
uv sync
cp config/local.toml.example config/local.toml   # fill in api_base_url, api_key
uv run dra --help
```

All LLM traffic goes through a single OpenAI-compatible endpoint
(typically a LiteLLM router) configured in `config/local.toml`. The
routing config in `config/routing_*.yaml` selects which model identifier
to send per `(role, tier)`; the router resolves it to the upstream
family (Claude, GPT, Haiku, etc.).

## Package layout

```
src/deep_research_agent/
  schemas/       Pydantic models for Task, Note, SourceNote, etc.
  scheduler/     Task graph + note graph + deterministic dispatch loop
  executor/      Agent executor + role-to-model routing
  retrieval/     Serper + Semantic Scholar + arXiv + Unpaywall + fetch/extract
  tiering/       Reject list + LLM tier classifier + peer-review flag
  patterns/      single_researcher / maker_checker / multi_perspective /
                 debate / ach — each a sub-task DAG emitter
  phases/        Landscape survey, decomposition, completion, report writer
  replanner/     Bounded replanner with mutation budget and cadence
  tools/         Agent tool functions (load_note, fetch_and_extract, …)
  export/        Note-graph serialization (output format TBD; not load-bearing)
  confidence.py  Tier-weighted confidence formula + language ladder
  config.py      Routing config loader
  cli.py         Entry point

config/          Per-run routing policies (for ablation matrix)
runs/            Per-run outputs + serialized note graph (gitignored)
```

## Commands

```bash
# Run a research session
uv run dra research "your query here" --routing config/routing_diverse.yaml

# Replay a run against the cached tool results (no network)
uv run dra replay <run_id>
```
