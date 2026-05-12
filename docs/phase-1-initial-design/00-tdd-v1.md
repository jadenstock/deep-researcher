# Deep Research Agent — Initial Design (TDD v1)

**Status:** initial design, iteration 1. Expected to change after phase-2 research pokes at it.
**Scope:** API-based deep research agent. No model training. Target: assessment take-home deliverable — full design + MVP implementation.
**Grounded in:** `phase-0-research/findings.md` + `phase-0-research/thoughts.md` (architectural positions and tension resolutions).

---

## 1. Problem Statement

Given a natural-language research query, produce a structured report that:
- Answers the query with claims explicitly separated from their evidence.
- Flags confidence per claim and surfaces source agreement / disagreement.
- Iterates across multiple research threads, handles conflicting sources, and stays honest about what it couldn't resolve.

Non-scoped here: evaluation infrastructure (LLM-judge design), debugging observability tooling, graceful-degradation architecture, continual improvement loops. All deferred to post-MVP iteration.

---

## 2. Design Goals and Non-Goals

### Goals

1. **Task-centric architecture.** Tasks are the unit of work, not agents. Agents are ephemeral workers spun up to execute tasks.
2. **Plan is mutable.** The task graph evolves during execution. A dedicated replanner agent periodically reviews and revises.
3. **Claim quality over system sophistication.** Every factual statement in the output traces to a source, with a quote, a confidence, and a source tier.
4. **Model tiering by task type.** Cheap models do cheap work (summarize tool outputs, simple lookups). Frontier models do expensive work (synthesis, claim generation, final report).
5. **User-in-the-loop as a first-class control.** Configurable interactivity (L0–L5). The agent can ask the user mid-research when it hits meaningful branch points.
6. **Verification is mandatory.** Load-bearing claims go through an independent verifier, optionally with adversarial framing.
7. **Closed set of orchestration patterns.** Fixed library of named patterns (single-researcher, maker-checker, debate, multi-perspective) that higher-level agents can instantiate as tasks.

### Non-Goals (explicitly)

- Fine-tuning or training any model.
- Self-improvement loops that modify prompts automatically.
- Long-lived agent personas or cross-session persistent memory.
- Production-grade observability infrastructure.
- Automatic graceful degradation on tool failures beyond basic retry.
- End-of-run self-reflection as a design feature (revisit post-MVP).

---

## 3. System Architecture

### 3.1 Bird's-eye view

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              USER                                         │
└─────────────────────────────┬────────────────────────────────────────────┘
                              │ query, interactivity level
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  INTAKE                                                                   │
│   · decompose query into initial task graph                               │
│   · classify tasks (lookup / synthesis / contested / sparse)              │
│   · emit success criteria per task                                        │
└─────────────────────────────┬────────────────────────────────────────────┘
                              │ initial task graph
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  ORCHESTRATOR LOOP  (while open tasks exist and progress is non-zero)    │
│    ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐   │
│    │ TASK SCHEDULER   │──▶│ AGENT EXECUTOR    │──▶│ CLAIM + EVIDENCE │   │
│    │ · pick next task │   │ · model routing   │   │ STORE            │   │
│    │ · check deps     │   │ · fork context    │   │ · structured     │   │
│    │ · update graph   │◀──│ · spawn sub-tasks │   │   output         │   │
│    └──────────────────┘   └──────────────────┘   └──────────────────┘   │
│           │                       │                       │              │
│           │                       ▼                       │              │
│           │              ┌──────────────────┐             │              │
│           │              │ SEARCH & RETRIEVE│             │              │
│           │              │ · web / academic │             │              │
│           │              │ · tier tagging   │             │              │
│           │              │ · cache          │             │              │
│           │              └──────────────────┘             │              │
│           ▼                                               ▼              │
│    ┌──────────────────┐                           ┌──────────────────┐  │
│    │ REPLANNER        │                           │ VERIFIER PATTERN │  │
│    │ (periodic task)  │                           │ (spawned on      │  │
│    │ · review plan    │                           │  load-bearing    │  │
│    │ · revise graph   │                           │  claims)         │  │
│    └──────────────────┘                           └──────────────────┘  │
│           │                                                              │
│           ▼                                                              │
│    ┌──────────────────┐                                                  │
│    │ USER GATEWAY     │  (async-preferred; default fallback on          │
│    │ · scope-creep    │   non-response; respects interactivity level)   │
│    │   escalation     │                                                  │
│    └──────────────────┘                                                  │
└─────────────────────────────┬────────────────────────────────────────────┘
                              │ all tasks closed (progress exhausted)
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  FINAL SYNTHESIS                                                          │
│   · manager-tier agent assembles report from claim+evidence store         │
│   · structured output: claims | evidence | confidence | source agreement  │
└─────────────────────────────┬────────────────────────────────────────────┘
                              ▼
                         USER (report)
```

### 3.2 Architectural principle

Everything is a task. Agents exist only to execute tasks and die. Orchestration is the shape of the task graph, not a network of persistent agents.

This gives us:
- **Uniform abstraction** — one primitive (task) covers low-level retrieval, mid-level synthesis, and high-level replanning.
- **Natural hierarchy** — any agent can spawn sub-tasks; the graph captures dependencies.
- **Clean model-tier assignment** — task type maps directly to model choice.
- **Free progress signal** — task completion rate is the progress metric (see §9).

---

## 4. Core Data Model

### 4.1 Task

```python
Task {
  id: TaskID
  parent_id: TaskID | None             # the task that spawned this one
  goal: str                            # natural-language objective
  type: TaskType                       # see §4.2
  tier: TaskTier                       # LOW | MID | HIGH — drives model routing
  pattern: OrchestrationPattern | None # for tier=HIGH tasks that wrap a pattern
  status: PENDING | RUNNING | DONE | ESCALATED | ABANDONED
  success_criteria: str                # what "done" looks like; LLM-evaluable
  depends_on: [TaskID]
  produced_claims: [ClaimID]
  produced_sub_tasks: [TaskID]
  created_at, completed_at
}
```

### 4.2 Task types (closed set)

| Type | Tier | Typical model | Description |
|------|------|---------------|-------------|
| `DECOMPOSE` | HIGH | frontier | Break a goal into sub-tasks |
| `SEARCH` | LOW | cheap | Issue a search query, return hits |
| `FETCH_AND_EXTRACT` | LOW | cheap | Retrieve + parse a URL into excerpts |
| `SUMMARIZE_SOURCE` | LOW | cheap | Turn a retrieved document into structured excerpts + candidate claims |
| `RESEARCH_SUBQUESTION` | MID | mid | End-to-end sub-question execution (spawns SEARCH / FETCH / SUMMARIZE / CLAIM_EXTRACT tasks) |
| `EXTRACT_CLAIMS` | MID | mid | Produce structured claims with quotes + source tier from excerpts |
| `VERIFY_CLAIM` | MID | mid-to-frontier | Independently test a claim against retrieved evidence |
| `ADVERSARIAL_CRITIQUE` | MID | mid-to-frontier | Build the strongest counter-argument to a claim |
| `SYNTHESIZE` | HIGH | frontier | Merge multiple claims into a position on a sub-question |
| `REPLAN` | HIGH | frontier | Review the task graph against the original goal; mutate as needed |
| `SCOPE_ESCALATION` | — | — | Ask the user a clarification mid-research |
| `WRITE_REPORT` | HIGH | frontier | Produce the final structured report |

The tier column determines **which model backs the agent executing that task**. No training; just routing.

### 4.3 Claim

```python
Claim {
  id: ClaimID
  sub_question_id: TaskID               # which subtask this claim serves
  text: str                             # the claim itself
  supporting_evidence: [Evidence]       # ≥1 required for any saved claim
  conflicting_evidence: [Evidence]      # may be empty
  verification_status: UNVERIFIED | SELF | INDEPENDENT | CONTESTED
  confidence: FLOAT                     # agent-stated; calibrated by source tier + agreement count
  generated_by_task: TaskID
  verified_by_task: TaskID | None
}

Evidence {
  source: Source
  quote: str                            # verbatim passage from source
  supports_or_refutes: SUPPORTS | REFUTES
}

Source {
  id: SourceID
  url: str
  title: str
  authors: [str] | None
  venue: str | None                     # e.g., "arXiv", "NeurIPS 2024", "blog"
  tier: TIER_1 | TIER_2 | TIER_3 | TIER_4  # deterministic (see §6)
  retrieved_at: timestamp
  raw_content_ref: str                  # pointer to cached raw content
}
```

### 4.4 Invariants

- Every `Claim` has at least one `Evidence` with a non-empty `quote`. Unevidenced claims are not saved to the store.
- `Source.tier` is assigned deterministically at retrieval time (§6). No LLM-judge subjectivity.
- `Claim.confidence` is derived from source tier(s) and agreement count via a fixed formula, not just LLM-stated. (See §6.)

---

## 5. Components in Detail

### 5.1 Intake

A single HIGH-tier task: `DECOMPOSE`. Inputs: raw user query + configured interactivity level.

Outputs:
1. Initial task graph (mostly `RESEARCH_SUBQUESTION` tasks, one per identified sub-question).
2. Per-sub-question classification (lookup / synthesis / contested / sparse) — maps to task tier.
3. Per-sub-question success criteria — natural-language, LLM-evaluable.

If `interactivity_level >= 3` and decomposition confidence is low, intake emits a `SCOPE_ESCALATION` clarifying question before returning. Otherwise, commits and continues.

### 5.2 Task Scheduler

- Maintains the task graph.
- Picks the next ready task (dependencies satisfied, status `PENDING`).
- Dispatches tasks respecting async/parallelism constraints (LOW-tier tasks parallelize freely; MID and HIGH tasks serialize per sub-question to avoid verifier thrash).
- Listens for task completion; updates dependent task status.
- Triggers the periodic `REPLAN` task every N completions (configurable; default 10).

### 5.3 Agent Executor

Stateless. Given a task, it:
1. Routes to the appropriate model based on `task.tier`.
2. Forks a fresh context window. The agent sees only: the task goal, task-relevant prior claims, relevant context from the task's immediate parent. Not the full global state.
3. Executes the agent loop (ReAct-style: thought → tool call → observation → …).
4. Produces structured output (claims, sub-tasks, or a final answer for the task).
5. Writes back to the Claim + Evidence store; appends to the task graph.
6. Dies.

### 5.4 Search & Retrieval Layer

Explicit, first-class. Three tools exposed to agents:

- **`web_search(query)`** → `[SearchHit{url, title, snippet, domain}]`
  - Backend: Brave Search API or Serper (configurable).
  - Caches results by query hash + day bucket.
- **`academic_search(query)`** → `[SearchHit]` with additional `{authors, venue, year}`
  - Backend: arXiv API for now; semantic scholar optional.
- **`fetch_and_extract(url)`** → `Source` with `{title, authors, venue, raw_content, excerpts}`
  - Uses `httpx` + `trafilatura` for HTML extraction.
  - For arXiv URLs, pulls abstract + section headings from the metadata API; full PDF parse is optional.
  - **Tier tagging happens here** (see §6).

Design constraints:
- All fetches are cached on disk keyed by URL + retrieval date. A `replay` mode reads from cache without hitting the network — cheap for iteration and testing.
- Failures are surfaced back to the calling agent as structured errors; the agent decides whether to retry with a different query, escalate, or proceed with partial evidence. No defensive degradation logic at the infrastructure layer (per scope cuts).

### 5.5 Source Tiering (Deterministic)

Rule table, applied at fetch time. No LLM involved.

| Tier | Rule |
|------|------|
| **TIER_1 — Peer-reviewed** | Venue matches a known peer-reviewed publication set (NeurIPS, ICML, ICLR, ACL, EMNLP, Nature, Science, IEEE journals, etc.). Detected from arXiv metadata, DOI lookup, or URL patterns. |
| **TIER_2 — Preprint / institutional** | arXiv (without known acceptance), reputable institutional technical reports (RAND, NIST, National Academies), major AI lab blogs (Anthropic, OpenAI, DeepMind, Google Research). |
| **TIER_3 — Established tech publications / docs** | Major engineering blogs (AWS, Microsoft, GCP, Databricks), MCP spec / standards bodies, widely-used framework docs (LangChain, LlamaIndex). |
| **TIER_4 — Everything else** | Random blogs, unattributed content, vendor marketing, community aggregators. |

Tier assignment is a single function: `domain + path + metadata → Tier`. Reviewable, auditable, fast.

**Confidence formula** (for claims):
```
confidence_base = max(tier_weight[s.tier] for s in supporting_sources)
agreement_bonus = min(0.1 * (unique_supporting_sources - 1), 0.3)
contradiction_penalty = 0.2 * (1 if any(refutes) else 0)
confidence = clip(confidence_base + agreement_bonus - contradiction_penalty, 0, 1)
```
Where `tier_weight = {TIER_1: 0.9, TIER_2: 0.75, TIER_3: 0.55, TIER_4: 0.3}`.

This is a starting formula; expected to calibrate.

### 5.6 Claim + Evidence Store

Single source of truth for all facts the system believes. Append-only during a run; LLM agents read from it with filters (e.g., "all claims on sub-question Q"). Backed by an in-memory structured store for MVP; trivially swappable for SQLite.

### 5.7 Orchestration Patterns (closed set)

Named templates that expand into sub-task graphs. Higher-tier agents instantiate them.

- **`single_researcher`** — default for LOW/MID sub-questions. One `RESEARCH_SUBQUESTION` task; produces claims; done.
- **`maker_checker`** — researcher produces claims → `VERIFY_CLAIM` task fact-checks each claim against independent retrievals. Default for `contested` and `sparse` sub-questions.
- **`debate`** — researcher produces claims → `ADVERSARIAL_CRITIQUE` task builds the counter-argument → third agent judges which is better-supported by evidence. Used when two retrievals return contradictory claims.
- **`multi_perspective`** — decomposer generates N queries from different stakeholder framings → parallel `SEARCH` + `EXTRACT_CLAIMS` → merge. Used for `contested` sub-questions upfront, to avoid one-sided evidence collection.

Pattern selection happens at two points:
1. **At decomposition** — sub-question classification hints at a default pattern (e.g., `contested` → `multi_perspective` + `maker_checker`).
2. **At runtime** — when a mid-tier agent detects unexpected conflict (e.g., two claims in direct contradiction), it spawns a `debate` task to resolve.

### 5.8 Verification

A `VERIFY_CLAIM` task:
- Receives the claim + its quoted supporting evidence.
- Issues its own independent search using different query phrasings.
- Retrieves independent sources.
- Produces verdict: `SUPPORTS`, `REFUTES`, `INCONCLUSIVE`.
- Updates the claim's `verification_status` accordingly.

Adversarial mode: the verifier's prompt is explicitly framed as "find the strongest evidence *against* this claim." If the adversary finds nothing, that's a stronger signal than default verification.

Not every claim is verified — that's prohibitively expensive. Verification is triggered for:
- Claims with `tier_base < TIER_2`.
- Claims on sub-questions classified as `contested` or `sparse`.
- Claims that the final synthesis will load-bear on (manager-tier makes this call before `WRITE_REPORT`).

### 5.9 Replanner

A `REPLAN` task. Spawned periodically by the scheduler (every N task completions; N default = 10).

Reviews:
- Is the original goal still being served by the current open tasks?
- Are there sub-questions that have expanded far beyond their original scope?
- Are there new sub-questions that should be added based on accumulated claims?
- Are there open tasks that no longer contribute and should be abandoned?

Outputs a mutation to the task graph (add/edit/abandon tasks). Can also raise a `SCOPE_ESCALATION` if it detects scope creep it can't resolve alone.

### 5.10 User Gateway (Interactivity Layer)

Interactivity levels:

| Level | Behavior |
|-------|----------|
| **L0** | Never ask. Agent always uses the default fallback. |
| **L1** | Ask only on high-risk decisions (scope-expanding beyond original decomposition). |
| **L2** | Ask on major branch points (multiple plausible directions with material scope differences). |
| **L3** | Ask on branch points + intake decomposition confirmation. (Default.) |
| **L4** | Ask on branch points + verify contested claims before synthesis. |
| **L5** | Ask at every meaningful decision. |

**Mechanics:**
- **Async-preferred:** when a `SCOPE_ESCALATION` fires, the system continues safe parallel work (other research sub-questions, pending LOW-tier tasks) while waiting.
- **Default fallback:** every escalation comes with a pre-computed default answer. If the user doesn't respond within a timeout (default 5 min real-time / unbounded in stream mode), the agent proceeds with the default and annotates the final report: "proceeded with default: [X]."
- **Rendering:** escalations are surfaced via whatever UI/CLI hosts the session. For MVP, stdout + stdin prompt in interactive mode; API webhook in server mode (out of MVP).

### 5.11 Stopping and Progress

No hard tool-call or round budgets. Stopping is driven by two signals:

1. **Task completion.** When the task graph has no open tasks with non-trivial dependencies and the replanner is producing no new tasks, the research phase ends.
2. **Progress stall detection.** If over the last M task completions, the number of *new* tasks created ≥ the number *completed*, that's scope-expansion. If it persists (K consecutive replan cycles), the system raises a `SCOPE_ESCALATION`: "scope is creeping; keep looking, or narrow and surface these as follow-ups?"

Context-window-hit is not a stopping signal — it triggers context compaction or sub-agent delegation (per thoughts.md: "hitting context limit = signal that more context engineering is needed").

At termination, `WRITE_REPORT` assembles the final output from the Claim store.

---

## 6. End-to-End Flow: Example Walkthrough

**Query:** "Is chain-of-thought prompting an effective reasoning strategy for LLMs, or does it primarily improve output formatting?"

1. **Intake.** `DECOMPOSE` task (frontier model).
   - Output:
     - SQ1: "What evidence supports CoT improving reasoning?" — classified `contested`
     - SQ2: "What evidence supports CoT primarily improving formatting?" — classified `contested`
     - SQ3: "Under what conditions does CoT help vs. not?" — classified `synthesis`
   - Pattern defaults: SQ1 + SQ2 get `multi_perspective` + `maker_checker`; SQ3 gets `single_researcher`.

2. **Parallel research.** Scheduler dispatches three `RESEARCH_SUBQUESTION` tasks (mid-tier).
   - Each spawns LOW-tier `SEARCH` and `FETCH_AND_EXTRACT` tasks (parallel, cheap model).
   - Each fetch tags sources with tier (arXiv → TIER_2; NeurIPS papers on arXiv → TIER_1 once DOI/venue is matched).
   - MID-tier `EXTRACT_CLAIMS` tasks produce structured claims with quotes.

3. **Verification.** MID-tier `VERIFY_CLAIM` tasks fire for load-bearing claims. Adversarial mode on SQ1/SQ2 (contested).
   - Verifier for SQ1 finds evidence that CoT improvements are sometimes attributable to formatting (Wei et al. critique) → marks claim `CONTESTED`.

4. **Replanner fires** after 10 task completions.
   - Detects that SQ1 and SQ2 are producing overlapping evidence.
   - Adds a `debate` task: "resolve whether CoT's effect is reasoning or formatting, given the current evidence."

5. **Debate resolves** with a nuanced claim: "depends on task and model size." Claim added to store with `verification_status = INDEPENDENT`.

6. **Progress stall check.** Scheduler sees task-creation rate declining. No escalation needed.

7. **`WRITE_REPORT`** (frontier). Assembles from the claim store. Output structure:
   - Each sub-question gets its own section.
   - Each claim lists its evidence (with quotes, source + tier), confidence, and verification status.
   - Contested claims get explicit "position A vs. position B" framing with evidence for each.
   - Final section: "unresolved questions" (follow-ups surfaced by the replanner).

---

## 7. MVP vs. Deferred

### MVP (build this for the take-home demo)

- Task graph + scheduler (in-memory).
- Intake / DECOMPOSE.
- Agent executor with model routing (frontier / mid / cheap).
- Search layer (web + arXiv).
- Source tiering (deterministic table).
- Claim + Evidence store.
- Orchestration patterns: `single_researcher`, `maker_checker`, `multi_perspective`, `debate`.
- Verifier (default + adversarial modes).
- Replanner (periodic).
- User gateway at L0 and L3 (the two most useful levels); other levels stubbed.
- Stopping on task completion + scope-creep escalation.
- `WRITE_REPORT` producing structured markdown.

### Deferred (design noted; not implemented in MVP)

- L1, L2, L4, L5 interactivity levels.
- Self-reflection loop after run completion.
- Git-like source-change history.
- Observability UI.
- Production-grade graceful degradation.
- LLM-judge evaluation harness.
- Automatic prompt improvement.
- Cross-session persistent memory.

---

## 8. The Comparison / Ablation for the Take-Home

Assessment requires at least one comparison or ablation. Strongest candidates given this design:

1. **With vs. without the verifier tier.** Compare claim-level faithfulness (does each claim's quote support the claim?) with and without `VERIFY_CLAIM` tasks. Expected: significant drop in faithfulness without.
2. **Single-agent baseline vs. task-graph architecture.** Build a minimal single-agent ReAct baseline on the same queries; measure coverage of sub-questions and source diversity. Expected: task graph wins on breadth.
3. **Multi-perspective query generation vs. single-prompt search** on contested prompts (Test Case 2). Measure source diversity and whether contradictions are surfaced in the report.

Candidate **1** is the cleanest — it isolates the verifier as a design decision and has an obvious quality metric.

---

## 9. Open Questions (for Phase-2 Research)

These are the specific pieces of this design most worth stress-testing in the next research round.

1. **Progress-stall detection threshold.** The "task creation rate vs. completion rate" heuristic is reasonable but unvalidated. What do production deep-research systems actually use? Is there a better signal?
2. **When does verifier adversarial framing help vs. hurt?** An adversary that finds nothing is a strong signal; an over-zealous adversary can invalidate well-supported claims. The prompt framing here matters a lot.
3. **Pattern selection at runtime.** Who makes the call? The research sub-doc left this open. This design puts it in MID-tier agents, but the logic ("detect direct contradiction → spawn debate") needs sharper criteria.
4. **Confidence formula calibration.** The formula in §5.5 is a guess. Does it correlate with actual correctness on the test-case prompts? Expected: we'll iterate once we see real outputs.
5. **Sub-question independence assumption.** The task graph assumes sub-questions can be researched in parallel. Some queries (like Test Case 4, the multi-agent systems taxonomy) may require building up sub-questions in sequence. How does the design handle this?
6. **Replan frequency.** N=10 is a guess. Too frequent = thrash; too rare = commits to dead ends. Needs empirical calibration.
7. **Context compaction strategy.** Mentioned as the fallback for context-limit hits; not concretely specified. Observation masking vs. summarization in our loop — which do we default to?

---

## 10. Summary of Design Commitments (what reviewers will poke at)

- **Task-centric (not agent-centric).** Agents are ephemeral; tasks persist.
- **Closed pattern set** (single-researcher, maker-checker, multi-perspective, debate). Selected at decomposition or dynamically by mid-tier agents.
- **Deterministic source tiering.** Rule-based, no LLM judgment.
- **Structured claims with attached quotes.** Every claim is traceable; confidence derives from source tier + agreement formula.
- **Mandatory verification for load-bearing claims**, optionally adversarial.
- **User-in-the-loop via interactivity slider**; async-preferred; default fallbacks always exist.
- **No hard budgets**; stopping is task-graph-completion + scope-creep escalation.
- **Model tiering** (cheap / mid / frontier) per task type.
- **Replanning as a periodic task**, not a reactive-only mutation.
