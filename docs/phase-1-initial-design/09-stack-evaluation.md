# Stack Evaluation — What to Build TDD v4 On

**Status:** pre-implementation. References TDD v4 (`07-tdd-v4-*`). Goal: pick a concrete Python stack before writing code.

**TL;DR.** Build a thin custom scheduler + task graph + note graph in plain Python + Pydantic models. Use **PydanticAI** for every place that talks to a model (agent executor, tools, structured output, cross-family routing). Skip LangGraph, skip pydantic-graph, skip durable-execution layers (Temporal/DBOS). The design already prescribes the orchestration semantics with too much specificity for a framework to carry them; the remaining work is mostly data plumbing and agent invocation, which is what PydanticAI is best at.

---

## 1. What the Design Actually Demands From a Stack

Extracted from TDD v4, in rough order of load-bearingness:

| Demand | Source | Implication |
|---|---|---|
| **Deterministic scheduler, no LLM.** Serial note writes, typed-dep staged waiting, mutation budget, cascade semantics (merge / split / abandon / add-edge), `CHECK_TERMINATION_READY` as a non-LLM structural audit. | §5.3, §5.14, ADR 0006, ADR 0009 | Scheduler is *your* code. No framework will model this loop for you without fighting it. |
| **Mutable task graph at runtime.** Replanner emits add/edit/abandon/merge/split operations under a per-cycle budget; cascade rules specified per mutation type. | §5.12, ADR 0009 | The graph is a data structure you own and mutate, not a compiled DAG handed to a framework. |
| **Task-centric / agent-ephemeral.** Tasks persist in a queue with a status machine (`PENDING`, `RUNNING`, `BLOCKED_ON_SYNTHESIS_DEP`, `BLOCKED_ON_SPLIT`, `DONE`, `ESCALATED`, `ABANDONED`). Each agent is a one-shot LLM call. | §3.3 principle 1, §4.1 | The agent layer is "stateless function that takes a Task + read-only note views, produces outputs." This is exactly what PydanticAI's `Agent.run()` is. |
| **Role-to-model routing with a hard cross-family invariant.** `VERIFY_CLAIM.family ≠ ANALYZE_SOURCE.family` enforced at model-selection time, not by prompt. | ADR 0008, §5.4 | Any framework with first-class multi-provider support works; PydanticAI and LangChain both do. You need per-call model selection, not per-agent-class. |
| **Note graph as shared memory.** Typed notes with versioning, serialized writes, progressive-disclosure default views, Obsidian export. | §3.3 principles 2–3, §4.2 | Plain Pydantic models + file-backed storage. No framework needed; frameworks actively get in the way if they try to manage "memory" for you. |
| **Agent tool set.** `load_note`, `search_notes`, `web_search`, `academic_search`, `fetch_and_extract`, `resolve_oa_pdf`, `load_source_section`, `create_note`, `edit_note`, `spawn_task`, `ask_user`. | §5.4 | Python functions registered as tools on an agent. Both PydanticAI and LangGraph support this cleanly. |
| **Closed set of orchestration patterns, each a sub-task DAG.** `single_researcher`, `maker_checker`, `multi_perspective`, `debate`, `ach`. | §5.9 | Each pattern is 5–10 lines of "emit these tasks with these deps." Not a framework concern. |
| **Ablation harness.** Per-run config file for model routing, so single-family / diverse-family configs are swappable. | §8 | Config-driven model selection. Trivial with any multi-provider lib. |
| **Observability.** Decision notes, tier rationale, cascade records, question-round tags visible in the Obsidian vault. | §3.3 principle 4, §5.15 | File-based vault export + optional tracing (Logfire/Langfuse) layered on top. |

**What the design does *not* demand** (worth noting, because frameworks often sell these):

- No durable execution / crash recovery (a take-home, not a service).
- No distributed scheduling.
- No streaming UI / websockets.
- No human-chat-loop — the user gateway is async-preferred with default fallback.
- No long-lived agent personas or cross-session memory.
- No RAG / vector store / embedding index (ADR 0007 explicit non-goal).
- No self-improvement / prompt versioning.

Every framework feature addressing the above items is dead weight for this project.

---

## 2. Core Options

### 2.1 LangGraph (+ LangChain ecosystem)

**What it is.** Graph-based agent orchestration framework from LangChain. Nodes are functions; state flows through typed channels with reducers; edges can be conditional or dynamic (`Send`). Checkpointing, interrupts, streaming built in.

**Fit against the design:**

| Aspect | Verdict |
|---|---|
| Mutable task graph | **Poor.** LangGraph graphs are compiled. Dynamic branching via `Send` works, but "merge two in-progress sub-questions and rewire deps mid-run" fights the abstraction. You'd end up representing the task graph as state inside a single top-level node — at which point LangGraph is just a `while` loop around your own scheduler. |
| Task-centric / agent-ephemeral | **Poor.** LangGraph's mental model is "nodes are agents; state moves between them." The design's inversion ("tasks persist, agents are one-shot") inverts that. |
| Typed-dep staged waiting | **Poor fit.** Reducers can express channel merges, but "retrieval ignores upstream synthesis deps; synthesis blocks on them" is a scheduler concern, not a graph-edge concern. |
| Role-to-model routing | **Good.** Pluggable model providers via LangChain. |
| Tool calling | **Good.** Standard. |
| Replanning | **Medium.** LangGraph has a "replanner" recipe but it assumes you regenerate the plan, not surgically mutate a running graph with cascade rules. |
| Checkpointing / human-in-the-loop | **Excellent, not needed.** For a take-home, these features are overhead. |

**When LangGraph *would* be right:** if the design were closer to "compiled plan-then-execute with conditional branches" rather than "mutable task queue with a runtime replanner." It isn't.

### 2.2 PydanticAI (+ optional pydantic-graph)

**What it is.** Anthropic-style agent library from the Pydantic team. Lean: each `Agent` is defined by a prompt, a set of Python-function tools, an output Pydantic model, and a model. First-class multi-provider (Anthropic, OpenAI, Gemini, Groq, Mistral, etc.). Ships with Logfire for tracing. `pydantic-graph` is a separate, optional FSM library from the same team.

**Fit against the design:**

| Aspect | Verdict |
|---|---|
| Mutable task graph | **N/A — PydanticAI doesn't try to solve this.** That's a feature: it leaves the scheduler to you. |
| Task-centric / agent-ephemeral | **Excellent.** `Agent.run(task_goal, deps=...)` is literally the ephemeral-agent pattern. |
| Typed data models | **Excellent.** Every schema in §4 of the TDD maps 1:1 to a Pydantic model; PydanticAI validates tool I/O against them. |
| Role-to-model routing | **Excellent.** Model is a per-call argument. A routing function `(role, tier, family_constraint) → ModelID` feeds straight into `Agent.run(model=...)`. The `family ≠` invariant becomes one line in the executor. |
| Tool calling | **Excellent.** Tools are typed Python functions registered with `@agent.tool`. Matches the agent tool list cleanly. |
| Structured output | **Excellent.** `output_type=SourceNote` gets you validated structured output by construction. |
| Replanning / graph mutation | **N/A.** You build it. |
| Observability | **Good.** Logfire integration is native; spans per agent call, per tool call. |

**When pydantic-graph adds value.** It models FSMs with typed transitions. The orchestration patterns (§5.9) are DAGs, not FSMs, and they're already trivially expressed as "emit these tasks with these deps" in the scheduler. Adding pydantic-graph on top is ceremony without payoff. Skip it.

### 2.3 Anthropic Agent SDK / Claude Agent SDK

**What it is.** Anthropic's managed and on-prem agent SDK. Close to Claude internals; MCP-native; built-in subagent delegation; matches Anthropic's own Claude Research architecture (orchestrator-worker).

**Fit against the design:**

| Aspect | Verdict |
|---|---|
| Cross-family routing (Claude + GPT + Haiku) | **Poor.** SDK is Claude-focused. Cross-family routing is ADR 0008's whole point; a Claude-only SDK breaks that at the foundation. |
| Orchestrator-worker pattern | Matches Claude Research's public architecture, which in turn influenced this TDD. |
| Tool calling, MCP | **Excellent.** |

**Verdict.** A great choice if the design committed to Claude-only. It doesn't. Skip.

### 2.4 OpenAI Agents SDK (née Swarm)

Multi-agent handoffs, guardrails, built around OpenAI's Responses API. Handoff-centric model is conversation-driven, not task-graph-driven. Same issue as the Anthropic SDK in reverse: provider lock-in is at odds with ADR 0008. Skip.

### 2.5 CrewAI / AutoGen

- **CrewAI:** role-based "crews" with processes. Personified agents, goal strings, autonomous delegation. The design explicitly rejects long-lived agent personas (§2 non-goals). Wrong abstraction.
- **AutoGen:** conversational GroupChat. Same mismatch — the design's memory is a note graph, not a chat transcript.

Skip both.

### 2.6 DSPy

Optimizer-first framework. The design's "no training, no prompt optimization" non-goal kills its reason to exist here. Skip.

### 2.7 Durable-execution layers (Temporal, DBOS, Prefect, Restate)

PydanticAI ships first-class integrations with all four. They give you crash recovery, retries, replay, durable state. For a production long-running research service this is genuinely valuable. For a take-home whose failure mode is "run it again," the operational complexity dwarfs the benefit. Skip for MVP; revisit if this ever becomes a service.

### 2.8 Plain SDKs + Pydantic (no agent framework)

Just `anthropic`, `openai`, `pydantic`, and hand-written tool-calling loops.

**Fit:** perfectly adequate. You lose ~200 lines of boilerplate around retries, tool-call dispatch, and structured output parsing. You gain zero framework churn risk.

**When this wins:** if PydanticAI's multi-provider abstraction ever leaks (e.g., you need a Claude-only feature like prompt caching at fine granularity that PydanticAI's abstraction doesn't expose). For v4 MVP the abstractions fit; no reason to go lower.

---

## 3. Recommendation

### 3.1 Primary stack

```
┌─────────────────────────────────────────────────────────────────┐
│  Your code (~60% of the project)                                │
│                                                                  │
│  Scheduler (deterministic, no LLM)                              │
│    · task queue + status state machine                          │
│    · staged dep waiting (ADR 0006)                              │
│    · serial note-write mutation queue                           │
│    · replanner dispatch (cadence + budget)                      │
│    · CHECK_TERMINATION_READY                                    │
│                                                                  │
│  Task graph + Note graph                                        │
│    · Pydantic models per §4.1–4.5                               │
│    · file-backed persistence (JSON + markdown vault)            │
│    · progressive-disclosure views                               │
│                                                                  │
│  Orchestration pattern DAGs                                     │
│    · five functions that emit task lists + deps                 │
│    · single_researcher / maker_checker / multi_perspective      │
│      / debate / ach                                             │
│                                                                  │
│  Replanner + VALIDATE_COMPLETION gates                          │
│    · prompt scaffolding + output parsing around LLM calls       │
└──────────────────────────┬──────────────────────────────────────┘
                           │ LLM calls, tool calls
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  PydanticAI (~25% — agent invocation layer)                     │
│                                                                  │
│  Agent class per role_class × task_type                         │
│    · typed output_type (SourceNote, LandscapeNote, etc.)        │
│    · tools as @agent.tool functions                             │
│    · model= resolved per-call by the routing config             │
│                                                                  │
│  Cross-family invariant                                         │
│    · one helper: select_model(role, tier, forbidden_family)     │
│                                                                  │
│  Logfire tracing (optional)                                     │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Provider SDKs via PydanticAI                                   │
│  anthropic · openai · (google-genai optional)                   │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Supporting libraries

- **Pydantic v2** — all data models. The TDD's §4 schemas are already written in this style.
- **`httpx`** — HTTP fetch for the retrieval layer (Serper, Semantic Scholar, arXiv, Unpaywall).
- **`trafilatura`** — HTML → main content extraction.
- **`markitdown`** — PDF → markdown (ADR 0007).
- **`diskcache`** or simple JSON-on-disk — `(tool, args_hash, day_bucket)` cache keying.
- **`logfire`** (optional, recommended) — Pydantic team's tracing; one-line instrumentation for PydanticAI.
- **`rich`** — console progress bars and structured run output, since runs take minutes.
- **`asyncio`** — the scheduler's dispatch loop. PydanticAI is async-native; retrieval fan-out parallelizes naturally.

### 3.3 Explicitly NOT using

- LangGraph / LangChain — abstraction mismatch with the mutable task graph.
- pydantic-graph — the patterns are simple DAGs; FSM layer adds nothing.
- CrewAI / AutoGen — wrong memory + agent-persona model.
- Temporal / DBOS / Prefect — production durability, not take-home scope.
- Any vector DB / embedding store — violates the "no full RAG" non-goal (ADR 0007).
- Anthropic SDK alone / OpenAI Agents SDK alone — single-provider locks out cross-family routing (ADR 0008).

---

## 4. How Each TDD Requirement Lands on This Stack

| TDD requirement | Where it lives |
|---|---|
| Task + Note + SourceNote + ClaimItem schemas (§4) | Pydantic v2 models in `schemas/` |
| Task status machine + scheduler (§5.3) | Hand-written `Scheduler` class; asyncio dispatch loop |
| Staged waiting on typed deps (ADR 0006) | `Scheduler.next_ready()` filter logic |
| Cascade semantics (ADR 0009) | `TaskGraph.apply_mutation()` methods per mutation type |
| Mutation budget + cadence (ADR 0009) | Scheduler counters + `Replanner.propose()` returning ≤ N |
| `CHECK_TERMINATION_READY` (ADR 0009) | Pure function over the task + note graph; zero LLM |
| Role-to-model routing (ADR 0008) | `routing.select_model(role, tier, forbidden_family)`; fed into `Agent.run(model=...)` |
| Cross-family invariant (ADR 0008) | One assertion in `VerifyClaimExecutor`: `model.family != claim.source.analyzed_by.family` |
| Agent tool set (§5.4) | `@agent.tool` functions over the note graph + retrieval layer |
| Orchestration patterns (§5.9) | Five pure functions in `patterns/`, each returning a list of `Task` with typed deps |
| Question-round framing (§5.8) | Prompt scaffold strings keyed on `QuestionRound`; injected into agent system prompts |
| Source tiering (§5.7) | Deterministic reject list + one small PydanticAI agent with `output_type=TierClassification` |
| ACH per-hypothesis batching (ADR 0004) | Inside the `ach` pattern fn; one `AnalyzeConsistency` task per hypothesis |
| Replanner (§5.12) | PydanticAI agent with structured output `ReplanDecision`; scheduler applies within budget |
| Completion gates (§5.14) | Six rule functions; G2 + G4 use a judgment-family agent; rest deterministic |
| Obsidian vault export (§5.15) | File-writer: one markdown file per note, wikilinks for `Link`s |
| Ablation harness (§8) | `config/routing_*.yaml` files; single entry point flag selects which |

No row above required a framework to own the abstraction. That's the tell that custom + PydanticAI is right-sized.

---

## 5. Risks of This Choice

1. **More hand-written scheduler code.** Mitigation: the design already specifies the scheduler semantics exhaustively (§5.3, ADR 0006, ADR 0009). Writing it is translation, not invention. Est. 400–600 LOC for the core scheduler + task graph + note graph.
2. **No framework-provided visualization of the run.** Mitigation: the Obsidian vault export *is* the visualization. Decision notes + cascade records are legible without a UI. Logfire adds per-call tracing for debugging.
3. **PydanticAI API surface churn.** PydanticAI is mature (1.0+ as of 2026) but still evolving. Mitigation: the exposure surface is small — `Agent`, `@tool`, `output_type`, `Agent.run()`. Easy to wrap.
4. **If the take-home evaluator expects a framework-forward answer.** Mitigation: the evaluation doc (08) and this doc make the decision legible. Having a clear rationale for *not* using LangGraph is itself a signal of design maturity.

---

## 6. Under- / Over- / Perfectly-Engineered?

**Verdict: perfectly engineered for the scope.**

- **Under-engineered path would be:** plain SDKs, no PydanticAI, no structured output validation. Buys 100 LOC, costs schema-level correctness guarantees and cross-family abstraction. Not worth it.
- **Over-engineered path would be:** LangGraph for the main loop + pydantic-graph per pattern + Temporal for durability + Langfuse + FastAPI for an interactive UI. Each layer adds impedance against the TDD's prescriptive scheduler semantics. Multiplies the surface area of things that can go wrong.
- **This stack** keeps you writing the code that *is* the design contribution (scheduler, replanner, patterns, note graph, tiering) and off-loads the boring parts (model dispatch, tool calling, structured output, tracing) to a thin, well-fit library.

---

## 7. Open Questions for Implementation Phase

1. Should the note graph be SQLite-backed instead of file-backed for faster progressive-disclosure queries on large runs? Probably not for MVP (<200 notes/run); revisit if scale grows.
2. Is Logfire worth the signup / cost? If budget-free, use it; if not, standard Python logging with a structured JSON formatter covers the take-home.
3. Should the replanner be one big agent call or split into per-check agents (typed-dep detection, scope creep, bias scan)? Probably one call with a structured multi-section output; easier to inspect. Worth prototyping both.
4. Fallback when a provider is down mid-run: retry same family once, then break the cross-family invariant and log a `decision_note`? Or fail the task and let the replanner re-dispatch? Current answer: latter — preserves the invariant. Revisit if it causes too many stalls.
