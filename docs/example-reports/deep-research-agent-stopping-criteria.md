# Research report

**Query:** What are the best methods of making sure a deep research agent stops eventually but also doesn't stop too soon

## Partial report (reconstructed from answered questions)

_The top-level researcher did not commit a final report. The sub-question answers below were recovered from the note graph._

### [synthesis] What are the main evidence-sufficiency / evidence-aware termination methods for deep research agents (e.g., pre-defined sufficiency conditions, coverage checklists, completeness detectors, data saturation)? How do they work mechanically and what are their strengths and weaknesses?

# Evidence-Sufficiency / Evidence-Aware Termination Methods for Deep Research Agents

## Opening Takeaway

Deep research agents face a fundamental tension: stopping too early yields shallow, incomplete outputs, while stopping too late wastes compute and money. The field has developed a spectrum of termination methods—from hard mechanical limits to semantically rich evidence-sufficiency conditions—each with distinct failure modes, and no single approach dominates. The state of the art combines multiple complementary mechanisms: structural hard limits as safety nets, with evidence-aware or coverage-based checks as the primary stopping logic.

---

## 1. The Core Termination Problem

Research agents operate in a loop (observe → reason → act → update → repeat). The loop must end, but when? The fundamental failure modes are:

- **Premature stopping**: The agent stops after one good-looking result or asks the human for permission to continue despite having a clear task list [source-c558bba4bb5a].
- **Infinite looping**: The agent repeatedly calls tools without producing output, burning tokens and money [source-0e85c5aca940].
- **Phantom completion**: The agent believes it has completed a task that was never actually recorded [source-c558bba4bb5a].

These failure modes motivate distinct termination methods.

---

## 2. Taxonomy of Termination Methods

### 2.1 Hard Resource Limits (Iteration, Time, Token, Cost Caps)

**Mechanism**: The loop is terminated unconditionally when a counter (iterations, wall-clock time, tokens consumed, API cost) exceeds a preset threshold.

**Examples from practice**:
- `--max-iterations` (default 5) and `--max-time` (default 10 minutes) in qx-labs/agents-deep-research [source-a9c7d0b52dc4]
- Hard `max_iterations` limit of 5–10 in standard agent architectures [source-0e85c5aca940]
- Hermes Agent's `max_iterations` (default 60) with a `_handle_max_iterations()` fallback that makes a final tool-less summarization call [source-34ba1d703705]
- Budget manager in MCP-Agent's Deep Orchestrator: "if we exceeded the time/cost/token budget, it would end the workflow" [source-d1dc95618197]

**Strengths**:
- Guaranteed termination; prevents runaway costs
- Simple to implement; zero semantic overhead
- Supported natively by OpenAI Agents SDK and LangChain [source-0e85c5aca940]

**Weaknesses**:
- Purely mechanical; unresponsive to evidence quality or task completeness
- Abrupt cutoff gives the agent no opportunity to consolidate findings: "the LLM has no opportunity to proactively wrap up, consolidate its findings, or produce a quality final response before being cut off" [source-34ba1d703705]
- Fixed thresholds poorly adapted to task complexity

---

### 2.2 Graduated Budget Pressure (Soft Warning Before Hard Limit)

**Mechanism**: Before the hard limit is reached, the system injects ephemeral system messages into the LLM's context window warning it to consolidate findings. This uses a two-tier approach:

```
// CAUTION tier — 10 iterations before the end
"[SYSTEM: Iteration N/M. Start wrapping up — respond with text soon.]"
// WARNING tier — last 3 iterations  
"[SYSTEM: You are on iteration N of M. You MUST respond with your final answer NOW. Do not call any more tools.]"
```
[source-34ba1d703705]

Messages are injected into the copy sent to the API (not persisted to session history) to avoid polluting context.

**Strengths**:
- Bridges hard limits and quality output: the agent can thoughtfully conclude rather than being abruptly cut off
- Trivial to implement (~20 lines of code); no architectural changes
- Does not pollute session history

**Weaknesses**:
- "May cause premature wrap-up — aggressive thresholds might make the LLM stop working too early" [source-34ba1d703705]
- Threshold tuning is task-dependent: "the right thresholds likely depend on task type; a fixed percentage may not be optimal for all cases" [source-34ba1d703705]
- Does not directly assess evidence quality; purely countdown-based

---

### 2.3 Pre-Defined Sufficiency Conditions (Evidence-Aware Termination)

**Mechanism**: Before each research step is executed, explicit sufficiency conditions are defined. The agent is required to gather and evaluate evidence against those conditions before moving on. Each step has a pre-declared "done" state.

The key paper "Don't Stop Early: Scalable Enterprise Deep Research with Controlled Information Flow and Evidence-Aware Termination" (arXiv 2604.24978) [source-80437d80a1b5] formalizes this as: **each research step defines explicit sufficiency conditions before execution; agents gather and evaluate evidence until these conditions are met**. This reduces both early termination (steps end before evidence is truly sufficient) and inconsistency in analytical depth across runs.

**Strengths**:
- Each step ends when evidence is sufficient, not when a clock runs out
- Improves consistency: the agent doesn't skip steps due to time pressure
- Reduces both under-investigation and over-investigation at the step level

**Weaknesses**:
- Requires anticipating what "sufficient" means for each step in advance—difficult for open-ended research
- Defining overly lenient conditions leads to shallow conclusions; overly strict ones cause infinite loops
- Content-based evaluation is more expensive than counting iterations

In R&D contexts, Causaly [source-fb6ad62c2856] describes these as "predefined criteria specifying when an AI agent's task is complete," reflecting implicit thresholds on evidence completeness, methodological clarity, limitations, and residual risk.

---

### 2.4 Coverage Checklists and Completeness Detectors

**Mechanism**: The agent derives a checklist of required information elements from the original query/goal. A small LLM call periodically scores current coverage against the checklist. When all checklist items are covered (or a satisfactory proportion), the loop terminates.

"A small LLM call scoring coverage against a checklist derived from the original goal works better" than either aggressive early stopping or lenient looping [source-84eb244e9438].

In multi-agent planning systems, this is formalized as a **completeness detector**: "checks all key elements from original query are covered by subtasks; non-redundancy principle. More than 15% of queries exhibit coverage issues during decomposition" [source-2d6bdd8963cb].

**Practical variants**:
- **Knowledge gap agents**: The qx-labs deep researcher's "Knowledge Gap Agent" drives the research loop. The loop continues only as long as knowledge gaps exist: "Identifies knowledge gaps in the current research, Strategically selects the appropriate tools to fill those gaps, Executes research actions through specialized agents" [source-a9c7d0b52dc4]. When no gaps remain, the loop naturally terminates.
- **Objective verification step**: The Deep Orchestrator adds an explicit verification step after execution: "If objective verification is not satisfied, replan and repeat" [source-d1dc95618197]. This creates a loop that terminates when the objective is demonstrably met.
- **TODO.md checklists**: In the Agentic Researcher framework, "a TODO.md file is equally critical, as it prevents the agent from forgetting about open questions, unverified claims, and deferred work" [source-c558bba4bb5a]. The checklist functions as a coverage tracker: the agent is "done" when all TODO items are checked off or explicitly deferred.

**Strengths**:
- Directly tied to task requirements rather than resource consumption
- Catches missing coverage that hard limits miss
- Explicit and inspectable: humans can audit what was covered

**Weaknesses**:
- Checklist quality depends on query decomposition quality; 15% of queries have coverage issues even with automated decomposition [source-2d6bdd8963cb]
- LLM-based coverage checks can hallucinate completeness ("I've covered X") when coverage is actually partial
- Checklists may be too rigid for highly open-ended exploratory research

---

### 2.5 Data Saturation / Novelty Diminishing Returns

**Mechanism**: Borrowed from qualitative research methodology, **data saturation** is the point at which new data no longer contributes additional insights. "Grounded theory uses saturation to determine when to stop collecting new data — new data is redundant" [source-9d3d419b0c41].

Applied to AI agents, this means: monitor the marginal informational gain of each new retrieved document or research step. When new steps consistently fail to add novel information (the "gain" drops below a threshold), terminate.

**Analogous approaches in RAG**: FAIR-RAG [source-becd9d06fd92] "transforms RAG into dynamic, evidence-driven reasoning that iteratively identifies and fills evidence gaps." When evidence gaps are exhausted, retrieval stops. This is saturation-in-practice for iterative retrieval.

**Strengths**:
- Naturally adaptive to the information landscape of the query
- Terminates exactly when more research would be redundant
- Avoids the "15 sources when 5 would have sufficed" problem

**Weaknesses**:
- Hard to operationalize: how does an LLM reliably detect that it has seen all the important information?
- Risk of false saturation: early convergence on a narrow evidence base before true coverage is reached
- Computationally expensive if novelty detection requires semantic comparison of accumulated evidence

---

### 2.6 Uncertainty-Driven Stopping

**Mechanism**: From autonomous robotics exploration [source-c235a27ece59], uncertainty-driven stopping terminates when the agent's internal uncertainty about the research topic drops below a threshold. Applied to LLM agents, this might manifest as: when the agent's reasoning traces no longer contain unresolved questions or express high uncertainty, terminate.

**Strengths**:
- Calibrated to what the agent "knows"
- Can prevent over-research of well-understood topics

**Weaknesses**:
- LLMs poorly calibrated for uncertainty quantification
- An agent may express false confidence well before genuine understanding is achieved
- Not yet standardized in production deep research agents

---

### 2.7 Policy Engines (Multi-Condition Decision Modules)

**Mechanism**: A dedicated policy module evaluates multiple signals (budget, objective verification, failure count, replan triggers) and decides among several exit conditions. The Deep Orchestrator's simple policy engine decides whether to: **Continue Executing**, **Trigger Replanning**, **Emergency Stop** (halt due to repeated failures), or **Force Completion** (complete due to budget overruns) [source-d1dc95618197].

**Strengths**:
- Separates termination logic from task execution logic (cleaner architecture)
- Handles multiple failure modes in one place
- Can combine evidence-aware and resource-based signals

**Weaknesses**:
- Complex policy engines can become brittle and hard to debug
- The MCP-Agent experience showed that "I over-complicated things with Adaptive Workflow" — a simpler architecture consistently won [source-d1dc95618197]
- Policy modules are often application-specific and not transferable

---

### 2.8 Human-in-the-Loop Escalation

**Mechanism**: When automated termination signals are ambiguous, the agent pauses and escalates to a human for a continue/stop decision. This is not a primary stopping mechanism but a fallback for high-stakes or high-uncertainty situations.

**Strengths**:
- Highest-quality stopping decision; human judgment for edge cases
- Required for irreversible actions or high-stakes research contexts

**Weaknesses**:
- Breaks automation; not scalable
- Latency penalty: humans may not be available to approve in real-time
- The Agentic Researcher found that "the agent consistently stopped to ask whether it should continue" is a major failure mode that commandments must explicitly suppress [source-c558bba4bb5a]

---

## 3. Interaction Between Methods: Layered Defense

In practice, production deep research agents layer multiple methods:

| Layer | Method | Role |
|---|---|---|
| Primary | Evidence-aware / coverage checklist / knowledge gap | Natural stopping point |
| Secondary | Objective verification | Confirm goal is met |
| Tertiary | Budget pressure (graduated warnings) | Graceful wind-down |
| Backstop | Hard limits (iterations / time / tokens) | Unconditional safety net |
| Emergency | Force completion / beast mode | Return partial results over nothing |

For example, qx-labs' agent uses knowledge gap detection as primary, with max_iterations and max_time as backstops [source-a9c7d0b52dc4]. The Deep Orchestrator adds objective verification + a policy engine on top of budget limits [source-d1dc95618197].

---

## 4. Open Research Problems

1. **Reliable completeness assessment**: LLMs claiming "I've covered everything" are often wrong. Calibrated completeness detection remains unsolved.
2. **Threshold generalization**: Iteration/time thresholds don't transfer across task types; evidence-aware thresholds don't transfer across domains.
3. **Saturation detection at scale**: Detecting diminishing informational returns in large document corpora is expensive.
4. **Premature stopping vs. over-investigation tradeoff**: No principled way to tune this tradeoff for arbitrary research tasks; empirical tuning is the current state of the art.
5. **Verification vs. termination conflict**: An agent instructed to verify claims thoroughly may never terminate, since verification can always be extended. The Agentic Researcher addresses this by making verification falsification-first (seek counterexamples) rather than comprehensive [source-c558bba4bb5a].

---

## Summary Table

| Method | Primary Signal | Strengths | Weaknesses |
|---|---|---|---|
| Hard resource limits | Iteration / time / token count | Simple, guaranteed | Ignores evidence quality; abrupt cutoff |
| Graduated budget pressure | Countdown with LLM warnings | Better final output quality | Can cause premature wrap-up; needs tuning |
| Pre-defined sufficiency conditions | Evidence meets per-step criteria | Evidence-driven, consistent depth | Requires knowing "done" in advance |
| Coverage checklists / completeness detectors | Query elements covered | Task-anchored; inspectable | Checklist quality depends on decomposition |
| Knowledge gap detection | Identified gaps exhausted | Natural loop termination | Gaps may be exhausted prematurely |
| Data saturation | Marginal novelty of new data | Adaptive, no redundant searching | Hard to operationalize in LLMs |
| Uncertainty-driven stopping | Agent's internal confidence | Calibrated to knowledge state | LLMs poorly calibrated; false confidence |
| Policy engine (multi-condition) | Combined signals | Handles multiple failure modes | Complexity risk; application-specific |
| Human-in-the-loop escalation | Human judgment | Highest quality | Breaks automation; not scalable |


### [synthesis] What hard resource-limit mechanisms do deep research agents use as safety nets to guarantee termination (max iterations, token budgets, wall-clock limits, budget managers, budget-pressure warnings)? What are typical values and best-practice patterns?

# Hard Resource-Limit Mechanisms in Deep Research Agents: Safety Nets, Typical Values, and Best Practices

## Opening Takeaway

Deep research agents universally deploy a **layered defense** of hard resource limits: (1) an iteration counter that halts the loop unconditionally, (2) a wall-clock timer as a parallel trip-wire, (3) token/context-window budgets with tiered warnings, (4) optional tool-call caps enforced by removing tools from the action space, and (5) budget-pressure messages that nudge the LLM to wrap up before the hard wall hits. Without at least some of these, agents silently loop until they run up four- or five-figure API bills [source-ecfbfdca31af][source-0e85c5aca940].

---

## 1. Maximum Iteration Limits

### What they are and why they exist

An iteration (or "step" / "turn") counter is the simplest and most universally deployed safety net. Every major framework ships one as a required parameter:

| Framework | Parameter | Default | Notes |
|---|---|---|---|
| **LangChain AgentExecutor** | `max_iterations` | **15** | Setting to `None` explicitly risks infinite loops [source-d1ac481e8eae] |
| **LangGraph StateGraph** | `recursion_limit` (config key) | **25** | Raises `GraphRecursionError` on breach; overridable at invoke-time [source-bc763ba57205] |
| **Hermes Agent (NousResearch)** | `max_turns` / `agent.max_iterations` | **90** (parent); **50** (subagents via `delegation.max_iterations`) | Subagent total can exceed parent cap [source-9ce246ba229a] |
| **qx-labs agents-deep-research** | `--max-iterations` | **5** (IterativeResearcher); **3/section** (DeepResearcher) | Dual-limit: also has `--max-time` [source-a9c7d0b52dc4] |
| **Practitioner guidance** | `max_iterations` | **5–10** | Hard cap for most single-agent production use cases [source-0e85c5aca940] |
| **Google Gemini Deep Research** | internal | ~20–30 (standard); more for "Max" tier | Not user-configurable; "Max" runs more iterations [source-f54bec338412] |

**The range across the ecosystem is roughly 5–90**, varying by agent complexity. Deep research agents (which must traverse many sub-topics) sit at the upper end; general-purpose chatbot agents at the lower end.

### What happens on exhaustion

Two patterns dominate:
- **Force**: return an error string or static message (e.g., `"(Reached max iterations: 20)"`) that the agent hit its limit [source-34ba1d703705]. LangChain calls this `early_stopping_method='force'`.
- **Generate**: make one final tool-less LLM call, asking the model to synthesize whatever it has gathered so far (`early_stopping_method='generate'` in LangChain; `_handle_max_iterations()` in Hermes) [source-d1ac481e8eae][source-34ba1d703705].

The **generate/summarize pattern** is considered the better UX — it produces a partial but useful answer rather than a hard error.

### Best practice: early warning before the wall

The critical improvement over a bare hard limit is **budget-pressure signaling**: injecting ephemeral warnings into the LLM's context *before* the limit hits, so it can proactively conclude rather than be cut off mid-loop.

**Two-tier pattern** (from Utah/Inngest, proposed for Hermes) [source-34ba1d703705]:
```
// CAUTION tier — 10 iterations before the end
if (iterations >= maxIterations - 10) {
  "[SYSTEM: Iteration N/M. Start wrapping up — respond with text soon.]"
}
// WARNING tier — last 3 iterations
if (iterations >= maxIterations - 3) {
  "[SYSTEM: You are on iteration N of M. You MUST respond with your final
  answer NOW. Do not call any more tools.]"
}
```
Key design decisions:
- Messages are injected into `api_messages` (the copy sent to the API), **not** the persistent `messages` array — they don't pollute session history.
- Relative thresholds (percentages) scale better than absolute ones across different `max_iterations` values:
  - **CAUTION at 70%** of max_iterations
  - **WARNING at 90%** of max_iterations [source-34ba1d703705]

**Research paper backing**: The BATS paper [source-99aac1516aa6] empirically shows that without budget signals, standard ReAct agents hit a performance ceiling even when iterations/resources remain — they self-terminate prematurely because they believe they found an answer or are stuck, unaware of unused budget. The Budget Tracker (per-iteration status block appended to context) consistently improved accuracy across Gemini-2.5-Pro, Gemini-2.5-Flash, and Claude Sonnet-4.

---

## 2. Wall-Clock Time Limits

Wall-clock limits are deployed as a **parallel safety net** alongside iteration limits, guarding against slow individual turns (e.g., waiting on slow web fetch) that could inflate real time even with a bounded iteration count.

| Framework/Tool | Parameter | Default |
|---|---|---|
| LangChain AgentExecutor | `max_execution_time` | `None` (disabled by default; can set float in seconds) [source-d1ac481e8eae] |
| qx-labs deep-research | `--max-time` | **10 minutes** [source-a9c7d0b52dc4] |
| Agent Contracts (formal) | duration `τ` | Example: 30 s (URGENT), 60 s (ECONOMICAL), 90 s (BALANCED) [source-ecfbfdca31af] |

**When the clock fires**, the system exits the loop and forces final output production — the research agent auto-exits to produce its report [source-a9c7d0b52dc4]. The Agent Contracts framework formalizes this as the `EXPIRED` terminal state [source-ecfbfdca31af].

**Best practice**: use duration (seconds/minutes) as the operational primitive, not deadlines — a deadline is simply `activation_time + duration`. Set the time limit as the outer safety net, iteration limit as the inner one; whichever fires first terminates the loop.

---

## 3. Token Budgets and Context-Window Management

Token budgets address a different failure mode: even a bounded-iteration agent can accumulate massive context (especially in multi-agent pipelines where sub-agent outputs feed the orchestrator) and either hit the provider's hard limit or degrade in quality due to the "lost in the middle" problem.

### Hard internal token threshold

**Claude Code's pattern** (documented and widely adopted) [source-1769f8960de2]:
- Track cumulative `input_tokens` from API response `usage` fields.
- Set an internal threshold **below** the provider's API ceiling (example: `threshold = 150,000`).
- Enforce proactively: halt/compact before hitting the API error.

```python
context_tokens = 0
threshold = 150_000  # Set below model's hard limit
def call_claude(messages, system=""):
    global context_tokens
    response = anthropic_client.messages.create(...)
    context_tokens = response.usage.input_tokens
    return response
```

### Tiered budget warnings (Claude Code pattern)

| Level | Trigger | Action |
|---|---|---|
| **Notice** | 70% of threshold | "Compaction may happen soon" — user/orchestrator aware |
| **Warning** | 85% of threshold | "Compaction is imminent" |
| **Action** | 90% of threshold | Automatic compaction OR halt with clear message [source-1769f8960de2] |

This mirrors the iteration-budget CAUTION/WARNING pattern but on a token dimension.

### Context compaction as a recovery mechanism

When threshold is hit, compaction replaces conversation history with a concise summary (LLM-generated):
- Typical reduction: **60–80% context size** [source-1769f8960de2]
- Hermes Agent triggers compaction: **preflight at 50%** of context window, **gateway at 85%** [source-9ce246ba229a]
- After compaction, the original task specification must be preserved (pinned in system prompt) — compaction is lossy.

### Pre-execution budget checks

Before any expensive operation (read large file, spawn subagent, broad search), estimate token cost and compare to remaining budget:
```python
def check_budget(estimated_tokens, remaining_budget, operation_name):
    if estimated_tokens > remaining_budget * 0.8:
        return {"proceed": False, "reason": f"compact first"}
    return {"proceed": True}
```
Prevents the common failure mode of partial task completion mid-operation [source-1769f8960de2].

---

## 4. Tool-Call Budgets (Search/Action Caps)

For web-search deep research agents, **tool-call count is often more relevant than token count** as the primary budget dimension, since it directly bounds the agent's external information acquisition [source-99aac1516aa6].

### Hard enforcement mechanism: tool removal

**BCAS (Budget-Constrained Agentic Search)** implements the cleanest mechanism [source-fa971c6ccca6]:
> "The search cap is enforced as a hard tool constraint. Once the allowance is exhausted, the search tool is **removed from the available action list** and the model must answer with the information it has already gathered."

This is harder than a soft warning — the tool literally disappears from the action space. The loop then naturally terminates because the agent can only call `ready_to_answer`.

### Typical values

- Agent Contracts framework example: **10 web searches**, **50 API calls** total [source-ecfbfdca31af]
- BATS evaluation set each tool budget at **100** calls; empirically 0.8% of queries needed >50, so a per-run budget of 50 is practical [source-99aac1516aa6]
- BCAS empirical finding: **accuracy improves up to ~3 searches**, then plateaus — suggesting `max_searches=3` as a default for simple QA [source-fa971c6ccca6]

---

## 5. Multi-Dimensional Budget Managers

Production deep research agents combine all dimensions into a unified budget manager that stops the workflow when *any* resource is exceeded.

**MCP-Agent approach** [source-d1dc95618197]:
- Deep token tracking throughout: every agent, LLM call, and workflow uses push/pop token context nodes.
- Budget manager checks: time, cost (dollars), and token count simultaneously.
- On any budget hit: workflow terminates and triggers **"beast mode"** — a final agent that synthesizes a response from accumulated knowledge. *"Something is better than nothing."*

**Simple policy engine** (Deep Orchestrator) [source-d1dc95618197]:
1. **Continue**: proceed with current plan
2. **Replan**: revise approach based on new information
3. **Emergency Stop**: halt due to repeated failures
4. **Force Completion**: complete due to budget overruns

**Agent Contracts framework** [source-ecfbfdca31af] formalizes this as a 7-tuple contract covering all dimensions. It defines:
- `FULFILLED`: success criteria met within all constraints
- `VIOLATED`: constraint breached before success
- `EXPIRED`: duration exceeded
- `TERMINATED`: external cancellation

Empirical validation: contracts with `max_iterations=3, token_budget=50K` achieved **90% token reduction with 525× lower variance** vs unconstrained (no significant accuracy drop at p=0.13).

The framework also includes **conservation laws** for multi-agent systems: subagent budgets must sum to ≤ parent budget, with a reserve buffer of 10–15% for coordination overhead.

---

## 6. Enforcement Capability Matrix

From the Agent Contracts analysis of 8 frameworks [source-ecfbfdca31af]:

| Constraint Type | Hard Enforcement? | Mechanism |
|---|---|---|
| Iteration limits | **Full** | Count steps, halt at N_max |
| Duration limits | **Full** | Check elapsed time before each action |
| API call limits | **Full** | Count external invocations |
| Multi-call token budgets | **Full** | Stop after cumulative threshold |
| Cost ceilings | **Approximate** | Track cumulative; bound via max_tokens |
| Single-call token limits | **Partial** | Known only after call completes; can stop next call |

**Important caveat**: token consumption is only known *after* an LLM call completes (streaming APIs provide total only at end). This means:
- Contracts cannot prevent a single expensive call from exceeding budget
- They *can* prevent subsequent calls after budget is exceeded
- Hard enforcement works at the inter-call level; soft enforcement (budget-aware prompting) works within a call

---

## 7. Best-Practice Patterns Summary

1. **Always set both `max_iterations` AND `max_time`** as parallel limits. Use whichever fires first. Neither alone is sufficient [source-a9c7d0b52dc4].

2. **Use relative thresholds** (70%/90% of max) for budget pressure warnings rather than absolute offsets — they scale across different budget configurations [source-34ba1d703705].

3. **Inject budget warnings as ephemeral messages** (into the API call copy only, never persisted to session history) — avoid polluting conversation history [source-34ba1d703705][source-9ce246ba229a].

4. **On hard limit, generate not force** — make one final LLM call with no tools to produce a summary from accumulated findings, rather than returning a raw error string [source-d1ac481e8eae].

5. **Add pre-execution budget checks** before expensive operations (subagent spawning, large-file reads, broad searches) to avoid mid-task failures [source-1769f8960de2].

6. **Remove tools from the action space** when their budget is exhausted — this is harder than a soft message and ensures the agent cannot ignore the signal [source-fa971c6ccca6].

7. **Use a reserve buffer of 10–15%** of the total budget for coordination overhead in multi-agent systems [source-ecfbfdca31af].

8. **Track the most-constrained resource** (max of all utilization fractions) as a single scalar and warn at 80% [source-ecfbfdca31af].

9. **Trigger "beast mode"** (or equivalent graceful-degradation mode) when any budget hits — synthesize from accumulated knowledge rather than returning empty [source-d1dc95618197].

10. **Use deterministic (code-based) enforcement** wherever possible rather than relying on LLM self-regulation — "token elasticity" means LLMs often exceed stated constraints when told in a prompt alone [source-ecfbfdca31af][source-d1dc95618197].

---

## 8. Real-World Failure Motivating These Patterns

The $47,000 incident (two agents in a recursive clarification loop for 11 days with no stop conditions, no budget limits, no real-time cost monitoring) [source-ecfbfdca31af] and documented cases of agents burning $12 per single query in 47-iteration loops [source-0e85c5aca940] are the canonical motivators. Gartner predicts >40% of agentic AI projects will be canceled by 2027 due to escalating costs or inadequate risk controls [source-ecfbfdca31af]. Hard resource limits are not optional — they are the primary infrastructure separating a production-grade agent from a prototype.


### [contested] What causes deep research agents to stop too early (premature stopping) vs. loop indefinitely (runaway loops), and which design patterns (forced summarisation, loop detection, escalation, graceful degradation) best mitigate each failure mode? Note the tradeoff between over-aggressive and over-lenient stopping.

# Premature Stopping vs. Runaway Loops in Deep Research Agents: Causes, Mitigations, and the Stopping Tradeoff

## Opening Takeaway

Deep research agents fail in two opposite directions: they either stop too early (often due to a miscalibrated "sufficiency" signal or an overcautious LLM disposition) or loop indefinitely (because their local-context architecture lacks global progress awareness). Each failure mode has distinct root causes and is addressed by a different set of design patterns. The central challenge is that every mitigation for one failure mode can cause the other if miscalibrated — this tradeoff is structural and cannot be fully eliminated, only managed through layered, task-adaptive controls.

---

## 1. What Causes Premature Stopping

### 1.1 Miscalibrated or Absent Sufficiency Criteria
The most systematic cause is that agents lack explicit, query-derived stopping criteria. Without a defined checklist of what "complete" means for a specific task, the LLM falls back on proxies — a single plausible-looking result, internal confidence, or surface-level completion phrases — all of which tend to fire too early. The EDR paper [source-80437d80a1b5] identifies premature stopping as one of three named failure modes in enterprise deep research alongside uneven information coverage and context explosion, directly attributing it to the absence of "evidence-based completion criteria."

### 1.2 Over-Permission-Seeking Behavior (LLM Disposition)
Empirically, the dominant behavioral manifestation is unsolicited permission-seeking. As the Agentic Researcher paper documents: "despite having a long todo-list of potential tasks and experiments, the agent consistently stopped to ask whether it should continue" [source-c558bba4bb5a]. This is a failure of the underlying LLM's disposition toward excessive caution — the model treats ambiguity about whether to proceed as reason to stop, even when the research plan explicitly authorizes continuation.

### 1.3 Error Misclassification as Task Failure
A subtler variant: agents prematurely abandon entire sub-tasks by misclassifying transient errors as fundamental failures. "When encountering an implementation failure, agents often claim that the approach 'doesn't work' and move on to an alternative. In practice, however, most of these crashes are simple bugs that can be fixed easily" [source-c558bba4bb5a]. The agent conflates "this specific attempt failed" with "this approach is infeasible," triggering an early pivot rather than a debug-and-retry.

### 1.4 Phantom Completion from Memory Loss
Context window resets and compaction can cause agents to believe they have completed work they never actually did. Without external artifacts verifying completion, an agent re-reading a summarized history may conclude the task is done based on an implicit record that never happened [source-c558bba4bb5a].

### 1.5 Over-Aggressive Guardrail Thresholds
Hard iteration limits, if set too low, cause forced termination before genuine convergence. Budget pressure mechanisms, if injected too early, can prompt the LLM to wrap up before the task is done: "aggressive thresholds might make the LLM stop working too early" [source-34ba1d703705]. This is the guardail-induced premature stopping failure.

---

## 2. What Causes Runaway Loops

### 2.1 The Core Architectural Gap: Local Reasoning Without Global State
The most fundamental cause is architectural: LLM agents reason from their current context window. Each action's decision is locally reasonable, but the agent has no global state representation tracking retry counts, cycle detection, or progress metrics: "Nothing in the agent's context tells it that this is the fifteenth retry and that fifteen retries on the same ambiguous result constitutes a loop rather than persistent reasonable behavior" [source-20d38084afc2]. Each retry is individually justified; the loop is only visible globally.

### 2.2 "Loop Drift": Misinterpreted Termination Signals
The phenomenon called *Loop Drift* occurs when agents misinterpret completion signals, generate repetitive actions despite explicit "TERMINATE" instructions, or suffer inconsistent internal state: "the agent misinterprets termination signals, generates repetitive actions, or suffers from inconsistent internal state, leading to endless execution" [source-d8dbf4ae7a15]. A common example: the agent calls `save_file`, re-reads the document, summarizes again, calls `save_file` again — because "summarized" never becomes "truly done" in its internal model.

### 2.3 Three Distinct Loop Patterns
Three loop patterns account for the majority of runaway behavior [source-20d38084afc2]:
- **Same-tool retry loops**: repeated calls to a tool returning ambiguous results, each retry locally reasonable
- **Oscillation loops** (harder to detect): alternating between two actions where A makes B seem correct and B makes A seem correct — neither action fails, the loop is only visible globally
- **Re-planning loops** (most expensive): failed execution triggers re-planning; new plan fails similarly; repeated re-planning rapidly fills context with token-expensive reasoning at no progress

### 2.4 Missing Max-Turns Configuration (Especially in Multi-Agent Systems)
In frameworks like AutoGen, LangChain, and CrewAI, the three root causes of 90% of loops are: "missing `max_turns`, a termination function that never returns `True`, and agents whose system prompts don't include a clear 'done' signal" [source-ecb9eabede6e]. In multi-agent systems, even one agent without a cap is sufficient to sustain the loop.

### 2.5 Diminishing Returns and Over-Iteration
Beyond explicit loops, agents can "loop" in the sense of accumulating increasingly marginal (and eventually harmful) additional iterations. FAIR-RAG experiments demonstrate empirically that a 4th iteration "consistently leads to a degradation in average answer quality across all complex datasets" because "an additional retrieval cycle is more likely to introduce noisy or tangentially related information that complicates the final synthesis step" [source-becd9d06fd92]. For simple queries, even a second iteration is harmful.

---

## 3. Design Patterns That Mitigate Each Failure Mode

### 3.1 Forced Summarization (Mitigates Runaway Loops)
The standard triple-fix for runaway loops: hard `max_iterations` (typically 5–10 for simple agents; 20–60 for research agents), a token budget per request, and a forced summarize-and-return after N iterations without convergence: "After N iterations without convergence, force the agent to summarize what it has and return" [source-0e85c5aca940]. The key insight is that the **system** — not the agent — must own the termination guarantee: "the system running the agent, not the agent itself, is ultimately responsible for guaranteeing termination" [source-d8dbf4ae7a15].

The limitation of naive hard cutoffs is that the LLM receives no warning: it "hits the wall" and a post-hoc call is made with no opportunity for graceful consolidation [source-34ba1d703705]. This creates poor-quality forced summaries.

**Budget pressure** addresses this by injecting graduated pre-warning messages — the Utah/Inngest pattern: a CAUTION signal at 70–75% of budget ("start wrapping up"), and a WARNING at 90% ("final answer NOW, do not call more tools"). These are injected ephemerally into the API call only, without polluting the persistent context [source-34ba1d703705]. This transforms an abrupt cutoff into a graceful deceleration.

### 3.2 Loop Detection (Mitigates Runaway Loops)
**Turn/iteration limits** (AutoGen's `max_consecutive_auto_reply`, LangChain's `max_iterations`) are the first line of defense — every agent needs one by default [source-ecb9eabede6e].

**Repetitive-action detection** via sliding window: log the full action history; if the same action appears ≥3 times in the action log, terminate [source-20d38084afc2]. A practical heuristic: an agent exceeding 2× the expected step count has looped regardless of whether the repetition is detectable from the action sequence.

**Semantic cycle detection** via message hashing (MD5 over normalized message content in a sliding window) catches loops where different-worded messages express the same ideas: "Detect this by hashing recent messages to catch cycles through the same ideas without making progress" [source-ecb9eabede6e]. 

**Important caveat**: hash-based detection can false-positive on legitimately repetitive tasks like status updates. Threshold tuning (`max_repeats`) is required per workflow [source-ecb9eabede6e].

**Explicit progress tracking** in the agent's context — structured records of completed, failed, and remaining items — gives the agent global state visibility that counters local-reasoning myopia [source-20d38084afc2].

### 3.3 Escalation (Mitigates Both Failure Modes)
Escalation routes control to a human or an alternative system when the agent reaches a decision point it cannot resolve autonomously.

For **runaway loops**: ambiguous tool results that would trigger retry loops should be routed to a clarification step, a human review gate, or a fallback action instead: "Rather than retrying on ambiguity, route ambiguous tool results to a clarification step, a human review gate, or a fallback action. Retry logic without a retry limit is loop infrastructure" [source-20d38084afc2].

For **premature stopping**: escalation can be triggered by agents stuck at a decision boundary (uncertain whether to continue), surfacing the question to a human or a reviewer agent with explicit verdict authority. The Causaly RA-PI architecture formalizes this: "Termination here is not a magic threshold inside a single model. It is the outcome of a controlled exchange between a research role and a reviewer role, with explicit artifacts (evidence matrices, assumptions, limitations, verdict)" [source-fb6ad62c2856].

Budget pressure (Section 3.1) is itself a lightweight escalation from the orchestration layer to the LLM, communicating the system-level resource constraint.

### 3.4 Graceful Degradation (Mitigates Runaway Loops Without Causing Hard Failure)
Graceful degradation returns a partial result with explicit disclosure of gaps rather than either looping or failing completely: "Graceful degradation means the agent answers with what it has and tells the user what it could not fetch. That is the difference between a useful 80% answer and a useless 0% answer" [source-bd4d3c0f3779]. This is especially valuable when individual tools time out: the agent continues with available data rather than waiting indefinitely or aborting.

Degradation tiers should be mapped to tool criticality. For research agents, most information sources are non-critical (degradation acceptable with gap disclosure); for high-stakes transactional operations, graceful degradation is contraindicated: "You cannot gracefully degrade a money transfer" [source-bd4d3c0f3779].

In agentic research, the analog is the forced summarization with gap annotation: the agent reports what it found, explicitly lists what it could not retrieve, and returns — rather than looping in search of completeness or halting with no output.

### 3.5 Evidence-Based Completion Criteria / Coverage Checklists (Mitigates Premature Stopping)
The most powerful mitigation against premature stopping is replacing vague "I feel done" internal signals with explicit, query-derived sufficiency criteria.

The coverage-checklist pattern: before the research loop starts, decompose the goal into a checklist of required findings; at each iteration, an LLM evaluator audits the accumulated evidence against the checklist, identifies confirmed items and explicit gaps, and continues only if gaps remain [source-becd9d06fd92]. This is the core mechanism in FAIR-RAG's Structured Evidence Assessment (SEA) and the EDR architecture [source-80437d80a1b5, source-becd9d06fd92].

The agentic-search variant: "a small LLM call that scores coverage against a checklist derived from the original goal works better than a word-count heuristic" [source-84eb244e9438]. This provides a principled, auditable stopping signal tied to task requirements rather than internal model confidence.

Autonomy commandments (explicit rules like "continue until TODO.md is empty" or "do not stop to ask permission unless compute runtime exceeds days") address the LLM-disposition cause of premature stopping by overriding the model's default caution reflex [source-c558bba4bb5a].

The RA-PI (researcher-reviewer) dialogue structure, where a reviewer agent explicitly issues "needs revision" vs. "approved" verdicts, provides human-mirrored stopping logic: "If the PI is too strict for low-stakes questions, the system feels slow and overengineered. If it is too lenient for high-stakes questions, the outputs will not survive scrutiny" [source-fb6ad62c2856].

---

## 4. The Core Tradeoff: Over-Aggressive vs. Over-Lenient Stopping

The central tension is structural: **every mechanism that prevents premature stopping increases the risk of runaway loops, and vice versa**.

| Dimension | Over-Aggressive Stopping | Over-Lenient Stopping |
|---|---|---|
| **Coverage** | Missing sub-topics; shallow analysis | Redundant evidence; noise accumulation |
| **Quality** | Incomplete output; low confidence | Degraded synthesis from context overload |
| **Cost** | Underutilized compute budget | API cost explosion ($12–$1,000+ per query) |
| **User trust** | Answer feels superficial | Unpredictable latency; potential timeout |
| **Governance** | Missing required evidence dimensions | Cannot audit stopping decision |

The tradeoff plays out at multiple levels:
- **Checklist thresholds**: requiring 100% checklist satisfaction delays stopping for hard-to-fill gaps; requiring 80% risks premature stopping with known gaps undisclosed
- **Iteration limits**: too low = forced truncation of legitimate deep research; too high = runaway cost
- **Loop detection window**: tight windows false-positive on legitimately repetitive tasks; loose windows allow sustained oscillation loops [source-ecb9eabede6e]
- **Budget pressure timing**: early injection risks premature wrap-up; late injection risks an abrupt low-quality cutoff [source-34ba1d703705]
- **Escalation sensitivity**: escalating too readily interrupts flow; escalating too rarely lets loops persist

FAIR-RAG provides quantitative grounding for the tradeoff: optimal performance on multi-hop research tasks is at 2–3 iterations; 4+ iterations harm quality by introducing noise; 1 iteration causes premature stopping with incomplete coverage [source-becd9d06fd92]. For simple queries, even 2 iterations are over-lenient.

The Causaly framework frames this as a task-type dependency: "The termination logic has to encode both the purpose of the question and the evidence standards of the organization" [source-fb6ad62c2856]. Exploratory desk research accepts partial coverage; governance-level evidence packs require completeness. A single static stopping rule cannot serve both.

---

## 5. Synthesis: Layered Stopping Architecture

The evidence converges on a **layered, task-adaptive stopping architecture** as the best practice:

1. **Task decomposition into an explicit coverage checklist** — sets the success criteria before execution begins, enabling principled stopping
2. **Per-iteration evidence gap auditing (SEA/checklist scoring)** — drives continuation decisions from explicit gaps rather than vague confidence signals
3. **Stateful progress tracking** — accumulated completed/failed/remaining state gives the agent global visibility to prevent local-reasoning loops
4. **Graduated budget pressure** (CAUTION at ~70%, WARNING at ~90%) — bridges the gap between hard limits and graceful consolidation
5. **Hard external limits** (max_iterations, wall-clock timeout) as unconditional failsafe — the system, not the agent, is the final arbiter of termination
6. **Loop detection** (repetitive-action detection + semantic hashing) — active monitoring for the three loop patterns
7. **Graceful degradation on timeout** — partial results with gap disclosure rather than hard failure or infinite wait
8. **Escalation paths** for ambiguous tool results and threshold decision points — human or reviewer-agent override when the agent cannot autonomously resolve a stopping decision
9. **Task-adaptive calibration** — iteration budgets, checklist stringency, and escalation thresholds adjusted by query complexity and risk profile

The anti-pattern is any single-mechanism stopping system: a lone hard limit causes abrupt poor-quality cutoffs; a lone LLM-driven sufficiency signal yields inconsistent stopping; a lone coverage checklist with no budget pressure risks infinite pursuit of the last gap. Robustness requires the full stack.

---

## Source Quality Note

The evidence base is predominantly practitioner and preprint material (tiers 2–4); there is limited peer-reviewed academic work specifically on stopping-behavior design for agentic research systems. The FAIR-RAG preprint [source-becd9d06fd92] and EDR paper [source-80437d80a1b5] provide the strongest empirical grounding. The Agentic Researcher paper [source-c558bba4bb5a] provides rare first-hand documentation of production failure modes. Practitioner sources converge on the same patterns despite independent derivation, increasing confidence.

### [sparse] How do multi-agent / parallel sub-agent deep research architectures handle global stopping — how are sub-agent budgets aggregated, how does the orchestrator decide when enough sub-topics are covered, and what patterns prevent sub-agent budgets from collectively exceeding parent caps?

# Global Stopping in Multi-Agent / Parallel Sub-Agent Deep Research Architectures

## Opening Takeaway

Multi-agent deep research systems have no single universal solution for global stopping and budget aggregation — instead they layer three distinct mechanism classes: (1) hard budget caps at both parent and sub-agent level, (2) coverage-completeness signals that let the orchestrator know when enough sub-topics are done, and (3) "budget pressure" patterns that prevent collective overrun by degrading gracefully before hard limits hit. The hardest design challenge is the stop condition itself: too aggressive produces premature halting; too lenient results in silent budget exhaustion.

---

## 1. How Sub-Agent Budgets Are Aggregated

### The Multi-Agent Amplification Problem

In single-agent systems, token accumulation is predictable. In multi-agent pipelines it compounds non-linearly. Each sub-agent response feeds back into the orchestrator's context window, and the orchestrator's input tokens are charged on every subsequent request:

> "A three-agent pipeline where each agent produces 2,000 tokens of output can balloon the orchestrator's context by 6,000 tokens per cycle. Over ten cycles, that's 60,000 tokens of accumulated sub-agent output, plus the original task context, plus intermediate reasoning." [source-1769f8960de2]

This means naively summing per-sub-agent iteration caps is insufficient — the orchestrator's own context is a secondary budget that grows as a function of sub-agent outputs.

### Known Aggregation Patterns

**a) Independent Per-Sub-Agent Caps with Shared Wall-Clock Limit**  
The most common open-source pattern (exemplified by qx-labs/agents-deep-research) grants each IterativeResearcher its own `max_iterations` cap, while a shared `--max-time` parameter provides a global wall-clock ceiling:

> "Maximum time in minutes before the research loop auto-exits to produce a final output (default: 10)" [source-a9c7d0b52dc4]

This is a *time-budget* aggregator: no matter how many iterations each sub-agent has individually, all are halted when the wall clock expires. Crucially, in this design, the total iterations across all sub-agents *can exceed the parent's cap* — this is an acknowledged limitation (noted in the NousResearch Hermes Agent docs summary), not a solved problem.

**b) Structured Handoffs as Context Isolation**  
A key pattern to prevent context explosion is routing sub-agent outputs through structured (typed) inputs/outputs rather than raw context passthrough:

> "MindStudio's multi-agent workflows enforce execution boundaries between agents, which naturally prevents context accumulation from cascading across the whole pipeline. Each agent in a workflow runs with its own context scope. Data passed between agents is structured (typed inputs and outputs), not raw conversation history." [source-1769f8960de2]

This provides *implicit* budget aggregation: the orchestrator's context doesn't grow unboundedly because sub-agent history is summarized to a typed struct at handoff.

**c) Context Compaction as Budget Recovery**  
Claude Code's approach — applicable to orchestrators — uses automatic context compaction at configurable thresholds (70%/85%/90% of the context limit), replacing accumulated history with a structured summary:

> "Claude Code sets strict upper bounds on context size during initialization. Rather than running until the API returns an error, it tracks accumulated token usage actively and enforces its own ceiling before hitting Anthropic's." [source-1769f8960de2]

Compaction reduces context by 60-80%, allowing long-running orchestrators to continue even as sub-agent outputs accumulate.

**d) Pre-Execution Budget Checks**  
Before spawning a new sub-agent or issuing a large tool call, the orchestrator can estimate token cost and compare against remaining budget:

> "If an operation would exceed the remaining budget, Claude Code either asks for user guidance, skips the operation and notes the limitation, or triggers compaction first to free up space before proceeding." [source-1769f8960de2]

This is the most sophisticated mechanism — it requires the orchestrator to maintain a running token tally from API response `usage` fields and apply size heuristics for file/search operations.

---

## 2. How the Orchestrator Decides When Enough Sub-Topics Are Covered

### The Coverage-Completeness Signal

The fundamental question is: has the research covered the original goal sufficiently? Three major approaches have emerged:

**a) LLM-as-Judge Coverage Scoring against a Checklist**  
The recommended pattern in agentic search literature is a small LLM call that scores the collected evidence against a checklist derived from the original goal:

> "A small LLM call that scores coverage against a checklist derived from the original goal works better than a word-count heuristic." [source-84eb244e9438]

This is paired with a shared stateful context object:

> "A more robust version would maintain a shared context object that accumulates: All queries tried (to avoid rephrasing the same one); All URLs fetched (to skip duplicates); A running summary of what is known vs. what is still unknown; A confidence score that drives the stop condition." [source-84eb244e9438]

The *confidence score* is the operationalized coverage signal: the orchestrator continues dispatching sub-agents until the score crosses a threshold.

**b) Outline-Driven Completion (Plan-First Architectures)**  
Systems like qx-labs DeepResearcher use a *planning step* to pre-enumerate the required sub-topics, then declare coverage complete when all planned sections have been filled by parallel sub-agents:

> "Takes a research topic and conducts preliminary research to form a report outline / plan... For each section of the report plan, runs parallel instances of the IterativeResearcher." [source-a9c7d0b52dc4]

This is analogous to qualitative research data saturation: stopping is not based on a fixed iteration count but on filling a predetermined topic structure. The orchestrator's stopping condition is: *all sections of the plan have been populated*.

**c) Artifact-Based Continuation Tracking**  
The Agentic Researcher framework uses a TODO.md checklist and report.tex file as coverage artifacts. At each context window reset, the agent re-reads both to determine remaining work:

> "At the beginning of every session (or after a context window reset), the agent re-reads report.tex, TODO.md, and the git log to restore continuity." [source-c558bba4bb5a]

This externalizes the coverage state to persistent files, decoupling it from in-context memory.

**d) Gap-Detection Loop**  
The canonical agentic search loop [source-84eb244e9438] alternates:
1. Generate queries from gaps in current knowledge
2. Fetch and score results
3. **Stop** if coverage score passes threshold; **continue** if gaps remain

Most well-scoped research tasks converge in 2–4 iterations under this scheme. The key insight is that the stop condition must be *evaluated*, not just counted:

> "The stop condition is the hardest part to get right. Too aggressive and the agent stops after one good-looking result. Too lenient and it loops until it hits the token or cost limit." [source-84eb244e9438]

### Failure Mode: Premature Stopping

A documented empirical failure mode — separate from budget exhaustion — is agents that halt prematurely by asking for permission even when the task plan has many remaining items:

> "A major problem we encountered was that, despite having a long todo-list of potential tasks and experiments, the agent consistently stopped to ask whether it should continue." [source-c558bba4bb5a]

This requires explicit commandments ("do not ask to continue if the plan specifies more work") to counteract.

---

## 3. Patterns That Prevent Sub-Agent Budgets from Collectively Exceeding Parent Caps

### Pattern 1: Two-Tier Budget Pressure (Ephemeral Message Injection)

The Utah/Inngest pattern (documented as a feature request for NousResearch Hermes Agent) is the most detailed known design:

> "CAUTION tier — 10 iterations before the end: '[SYSTEM: Iteration N/M. Start wrapping up — respond with text soon.]'  
> WARNING tier — last 3 iterations: '[SYSTEM: You are on iteration N of M. You MUST respond with your final answer NOW. Do not call any more tools.]'" [source-34ba1d703705]

Key design properties:
- Messages are injected into the *copy* sent to the API, not the persistent history (no context pollution)
- Two tiers provide *graduated pressure*: nudge first, then force
- Recommended thresholds: CAUTION at 70% of max_iterations, WARNING at 90%
- Thresholds should scale *relatively* not absolutely: "a 10-turn session needs earlier warnings than a 60-turn one" [source-34ba1d703705]

### Pattern 2: Tool Restriction at Budget Exhaustion

When budget pressure fires, an advanced pattern is to *reduce the available toolset*, specifically disabling heavy delegation tools:

> "When budget warning fires, optionally reduce the available toolset (e.g., remove heavy tools like delegate_task, browser)" [source-34ba1d703705]

This prevents new sub-agent spawns when the parent is near its budget limit — directly addressing the collective overrun problem by making delegation structurally impossible near the cap.

### Pattern 3: Forced Summarize-and-Return at Hard Limit

When the budget is fully exhausted, the standard fallback is to force a final summarization call with no tools:

> "Set a hard max_iterations limit (typically 5-10). Implement a token budget per request. After N iterations without convergence, force the agent to summarize what it has and return." [source-0e85c5aca940]

This prevents the worst failure mode — silent budget exhaustion with no output — by guaranteeing a partial result is produced.

### Pattern 4: Structured (Non-Passthrough) Handoffs

As noted above, preventing the orchestrator's context from accumulating raw sub-agent outputs is a structural way to enforce budget containment:

> "Data passed between agents is structured (typed inputs and outputs), not raw conversation history, so you're not dragging entire context windows through the system with every handoff." [source-1769f8960de2]

This pattern means the parent's context budget grows at a known, bounded rate proportional to the structured output schema, not the full sub-agent conversation.

### Pattern 5: Redirect Outputs Externally

The Agentic Researcher framework addresses the context growth problem by having sub-agents write long outputs to external files:

> "Prefer redirecting long-running output to log files and monitoring with tail. Only investigate logs in detail if something looks wrong." [source-c558bba4bb5a]

This is the "external state store" complement to structured handoffs: instead of returning large content inline, sub-agents write to disk and the orchestrator reads summaries.

---

## 4. Summary Table of Mechanisms

| Problem | Mechanism | Implementation Pattern |
|---|---|---|
| Sub-agent individual runaway | Hard `max_iterations` per sub-agent | Framework-level cap (5-60 iterations) |
| Collective overrun | Shared wall-clock `max_time` | Global timeout auto-exits all sub-agents |
| Orchestrator context explosion | Structured handoffs / typed outputs | Return schema-typed structs, not raw history |
| Orchestrator context explosion | Context compaction | LLM-summarize at 70-90% threshold |
| Coverage completeness | LLM checklist scoring | Goal-derived checklist + confidence score |
| Coverage completeness | Plan-first outline filling | Planner → parallel sections → proofreader |
| Premature stopping | Explicit continuation commandments | "Do not ask to continue if plan has items" |
| Sub-agent spawning near cap | Tool restriction at budget warning | Disable `delegate_task` at WARNING tier |
| Budget exhaustion with no output | Forced summarize-and-return | Final call with tools disabled at hard limit |

---

## 5. Open Issues and Limitations

1. **No standard aggregation protocol**: No framework reviewed has a formal mechanism for the parent to track *total tokens across all sub-agents in real time*. The most common approach (independent caps + wall clock) can still result in collective overruns in token terms, just bounded by time.

2. **Coverage heuristic fragility**: LLM-as-judge checklist scoring is effective but can be overconfident (stopping too early on topics it mistakenly believes are covered) or underconfident (looping on inherently open-ended questions). Calibration is task-specific.

3. **Context compaction is lossy**: Automatic compaction may discard details needed later in the task; critical state must be persisted externally before compaction to prevent loss. The risk grows with longer sessions and more sub-agents.

4. **Threshold tuning is task-specific**: Budget pressure thresholds appropriate for a 10-turn coding agent are wrong for a 60-turn research agent. Adaptive thresholds based on task complexity signals remain largely ad hoc.


### [adversarial] Steelman the opposite of the layered-stopping-architecture conclusion from [question-5f2f4b13f5ce] (the premature-vs-runaway sub-question). Specifically: make the strongest case that a simple single-mechanism stopping approach (e.g., just a generous hard iteration/time cap with forced summarization) outperforms complex multi-layered stopping stacks (coverage checklists + budget pressure + loop detection + escalation) for deep research agents in practice. Consider simplicity, brittleness, over-engineering, and real-world deployment evidence.

The strongest counter-case is that, in practice, a simple single-mechanism stopping policy — a generous hard step/time cap plus forced summarize-and-return — often beats layered stopping stacks for deep research agents because it is more reliable, easier to reason about, cheaper to deploy, and less brittle under real production failures. The practical evidence in mainstream agent frameworks and deployment writeups suggests that when semantic stopping logic fails, the thing that actually stops the run is still the hard cap; adding multiple higher-level stopping layers often adds configuration and failure surface faster than it adds dependable control. [source-0e85c5aca940] [source-c8c64b52fe9f] [source-04d30b6a54cf] [source-97c2ea8cfae2]

## Counter-case: why a simple cap can outperform a layered stopping stack

### 1) Hard caps are the mechanism that actually works when everything else fails
Layered stopping architectures sound robust because they promise semantic awareness: coverage checklists, budget pressure warnings, loop detectors, and escalation logic. But the practical problem is that these mechanisms themselves depend on correct state tracking, prompt fidelity, auxiliary evaluators, and cross-component coordination. When they misfire, the ultimate backstop is still a crude hard limit.

Official LangGraph docs define the core failure as a graph that "reached the maximum number of steps before hitting a stop condition," and note this is "often due to an infinite loop." Their remediation for legitimately deep/complex cases is not a more ornate termination stack, but simply: "pass in a higher `recursion_limit` value." [source-c8c64b52fe9f] That is a strong signal about real-world operability: even sophisticated graph systems anchor safety in a single, inspectable limit.

A live LangGraph bug report reinforces this. The user says the agent was "looping indefinitely until hitting the error mentioned above (recursion limit error)," and that even "explicitly specifying stop conditions within the prompt ... did not work." What actually terminated the runaway behavior was: "Recursion limit of 20 reached without hitting a stop condition." [source-04d30b6a54cf] In other words, semantic stopping failed; the simple cap succeeded.

### 2) Layered stopping is vulnerable to the same brittleness as the agent itself
A multi-layer stopping stack introduces more logic, more thresholds, and more interactions that can go wrong. You are not just trusting the base agent anymore; you are trusting the checklist generator, the coverage scorer, the no-progress detector, the budget-pressure signals, and the escalation router. Each is another moving part that may drift, conflict, or break.

The LangGraphJS issue where "`recursionLimit` config [is] ignored — still getting limit of 25" is revealing here. The expected behavior was simple: the configured limit should override the default. Instead, "the runtime still enforces a limit of 25." [source-b4bf6896d656] If even a single hard-limit config can be brittle, a layered stop stack with multiple interdependent signals has even more failure surface. Complexity does not just guard against failures; it creates its own control-plane failures.

This is the core adversarial point against the layered-architecture conclusion: more stopping logic is not free. It increases integration burden, test matrix size, observability requirements, and debugging difficulty. In practice, the team may spend more effort validating the stopping stack than improving task quality.

### 3) Simplicity is easier to calibrate, audit, and operate
A generous hard cap plus forced summarization is transparent. Operators can answer:
- What stops the run? The cap.
- What happens at the boundary? The agent summarizes and returns best-effort output.
- How do we tune it? Raise or lower the cap/time budget.

This simplicity matters operationally. The practical guide in [source-0e85c5aca940] recommends exactly this pattern: "Set a hard max_iterations limit (typically 5-10). Implement a token budget per request. After N iterations without convergence, force the agent to summarize what it has and return." The same source frames the core production danger as a silent infinite loop that can burn money without value: "This is the most expensive failure mode: silent cost explosion with no useful output." [source-0e85c5aca940]

That advice is not elegant, but it is legible. Teams can monitor average iterations, cap exceedance rate, partial-return rate, and cost per task. By contrast, layered stop stacks tend to produce ambiguous failures: did the coverage checker prematurely halt? Did loop detection falsely trigger on legitimate iterative refinement? Did budget pressure alter behavior without explicit failure? Those are harder to diagnose than "the run hit 20 steps and returned a summary."

### 4) Forced summarization degrades gracefully instead of failing opaquely
A simple cap with summarize-and-return does not pretend to know whether the task is truly complete. It makes a more modest claim: the run is over, here is what was found so far, and here are the remaining gaps. That is often preferable in research settings to a layered controller that asserts completion because a checklist scored high enough.

This matters because deep research tasks are frequently open-ended. Overconfident semantic termination can be worse than explicit truncation. A bounded agent that returns a partial but honest summary may outperform a more complex controller that stops “intelligently” but incorrectly.

The simple approach also aligns with how many mature engineering systems handle overload and uncertainty: bound execution and degrade gracefully. In this sense, summarize-and-return is a graceful degradation path, not a defect.

### 5) Real deployment evidence favors bounded, minimal systems over ornate stop logic
The most practically relevant source in this corpus for long-running research-style work is the Deep Researcher Agent paper. Its success story is not built around a rich layered stopping stack. Instead, it emphasizes minimizing active control and overhead:
- "the LLM has nothing useful to contribute" during 90–99% of wall-clock training time [source-97c2ea8cfae2]
- a "Minimal-Toolset Leader-Worker Architecture" reduces per-call overhead by up to 73% [source-97c2ea8cfae2]
- the system sustained "30+ days" and "500+ experiment cycles" at about "$0.08 per 24-hour cycle" [source-97c2ea8cfae2]
- configuration relies on simple bounds like `max_steps_per_cycle: 3` and `cooldown_interval: 300` [source-97c2ea8cfae2]

The deeper lesson is that practical success came from reducing control overhead, bounding memory, minimizing tools, and using cheap/simple runtime constraints — not from inserting many semantic termination layers. For deep research agents, this is a serious argument that the right strategy is often to make the run cheap and bounded enough that longer execution is acceptable, rather than trying to micromanage stop decisions with a complex stack.

### 6) Over-engineering can hurt both quality and speed
[source-0e85c5aca940] explicitly warns that bad architectural choices can make an agent "production-viable or a money pit," and notes that custom ReAct loops offer "Full control" with "No framework overhead." [source-0e85c5aca940] This does not prove that simple systems are always better, but it strengthens the adversarial case that every added stopping layer has an opportunity cost:
- more tokens spent on meta-evaluation
- more prompts and state to maintain
- more knobs to tune per domain
- more false positives on legitimate deep exploration
- slower iteration for the engineering team

For many teams, especially those shipping internal tools or domain-specific research agents, a simple step/time cap with partial-return behavior may dominate because it is good enough, cheap enough, and robust enough. A layered stop stack can easily become a textbook example of solving the control problem at the expense of the product problem.

## Strongest specific objections to the layered-stopping conclusion

1. **The layered stack mistakes apparent sophistication for dependable control.** In real systems, the hard cap is still the true safety boundary. [source-c8c64b52fe9f] [source-04d30b6a54cf]
2. **Extra stopping layers add their own brittleness.** The control plane becomes another probabilistic, bug-prone subsystem. [source-b4bf6896d656]
3. **Simple caps are easier to calibrate and explain.** Operators understand them, can audit them, and can tune them quickly. [source-0e85c5aca940]
4. **Forced summarization is a graceful degradation strategy.** It often serves research workflows better than brittle semantic claims of completeness.
5. **Deployment evidence supports minimal bounded architectures.** The best concrete long-running example here succeeds through bounded memory, minimal tools, and simple limits, not layered stop logic. [source-97c2ea8cfae2]

## What this steelman does and does not establish
This adversarial case does **not** prove layered stopping is useless. It shows the original pro-layered conclusion is vulnerable on practicality grounds. In practice, a simple generous cap plus forced summarization may outperform a complex stopping stack when evaluated on total system value: implementation time, operational reliability, predictability, debugging ease, and cost containment.

If the question is not “What is the most theoretically nuanced stopping architecture?” but “What should a team ship for a deep research agent that works reliably in production?”, then the counter-case is strong: start with one blunt but dependable mechanism, make it generous enough not to truncate ordinary work, and optimize outputs around graceful partial returns rather than building an elaborate semantic stopping bureaucracy.


### [verify] Independently confirm or refute the claim (central to syntheses in [question-7f1fe6f12f5e] and [question-5f2f4b13f5ce]) that pre-defined evidence-sufficiency conditions / coverage checklists / knowledge-gap detection produce measurably better stopping behavior than hard iteration caps alone for deep research agents. Look for empirical benchmarks, ablations, or counter-evidence. The "Don't Stop Early" paper could not be fully fetched previously — try to verify its specific claims.

SUPPORTS (with important caveats).

Independent evidence mostly supports the claim that pre-defined evidence-sufficiency / verifier-guided / gap-detection stopping produces better stopping behavior than hard iteration caps alone. The strongest direct support comes from Stop-RAG, which explicitly compares adaptive stopping against fixed-iteration baselines and LLM self-stop on iterative RAG, and finds that adaptive stopping "consistently outperforms both fixed-iteration baselines and prompting-based stopping with LLMs" [source-746fd5df720b].

## What I verified

The prior claim had two parts:
1. **Adaptive, evidence-aware stopping beats hard iteration caps alone** for research-like agents.
2. The **"Don't Stop Early"** paper specifically substantiates that claim.

I looked for direct empirical comparisons, ablations, and counter-evidence.

## 1) Best direct independent evidence: adaptive stopping beats fixed caps in iterative retrieval

### Stop-RAG is the clearest independent test
Stop-RAG directly studies the stopping decision in iterative RAG and argues that fixed loop counts are fundamentally mismatched to per-query difficulty: fixed loops can "waste computation" on easy questions and "halt prematurely" on difficult ones [source-746fd5df720b]. It then reports that its learned adaptive controller "consistently outperforms both fixed-iteration baselines and prompting-based stopping with LLMs" [source-746fd5df720b].

The reported table shows this clearly in the authors' main pipeline:
- MuSiQue F1: **44.8 → 47.0**
- HotpotQA F1: **65.0 → 66.1**
- 2WikiMultihopQA F1: **64.9 → 68.2**
with analogous gains in EM and accuracy when moving from fixed-iteration "Our Pipeline" to "+ Stop-RAG" [source-746fd5df720b].

This is the strongest falsification-oriented evidence I found because it does exactly the comparison at issue: **adaptive stopping vs hard iteration cap**.

### But Stop-RAG also gives counter-evidence
This is not a universal win. The same paper reports a failure case: on **HotpotQA with CoRAG**, "Stop-RAG slightly underperforms both baselines" [source-746fd5df720b]. The authors attribute this to a regime where continuing retrieval to the full count can be better than stopping adaptively because recall matters more than distractor cost [source-746fd5df720b].

So the strongest independent paper supports the claim **on balance**, but also refutes any over-strong version like "adaptive sufficiency stopping always beats fixed caps."

## 2) Neighboring evidence: verifier-guided adaptive allocation beats fixed inference strategies

A second, broader line of evidence comes from adaptive test-time compute papers. These are not deep-research-agent papers per se, but they test the same core idea: **use intermediate verification/sufficiency signals to decide whether to continue or stop, instead of spending a fixed budget uniformly**.

### What If We Allocate Test-Time Compute Adaptively?
This paper says fixed strategies apply the same exploration budget even when early reasoning is already obviously good or bad [source-47166651eca6]. Its main result is that adaptive, verifier-guided inference "consistently outperforms uniform test-time scaling across all evaluated datasets" [source-47166651eca6].

The gains are substantial:
- MATH-500, Llama-3.1-8B: **43.8 → 65.4**
- MATH-500, Qwen-2.5-7B: **71.2 → 81.4**
for Direct vs Dynamic+PRM Selection [source-47166651eca6].

This is not direct evidence about research agents, but it independently confirms the **mechanistic thesis** behind the claim: stopping/continuation decisions informed by verification signals can beat fixed budgets.

### Caveat from the same paper
The benefit weakens on the hardest problems because the verifier signal itself becomes less reliable: gains on the top difficulty tier are "weaker due to less reliable verification signals" [source-47166651eca6]. So again, adaptive stopping helps when the control signal is good.

## 3) What about hard caps alone? They are not useless.

A useful counterweight is BCAS, which studies hard search and token budgets rather than evidence-sufficiency stopping. It enforces a strict cap by removing the search tool once the allowance is exhausted [source-fa971c6ccca6].

Its findings show that **hard caps alone already work reasonably well** in QA-style settings:
- "accuracy improves reliably up to about three searches"
- gains then show "diminishing returns after roughly three searches" [source-fa971c6ccca6]

This matters because it weakens any claim that evidence-sufficiency logic is necessary to beat simple caps by large margins in all settings. In some benchmarked retrieval tasks, a modest fixed cap captures much of the benefit [source-fa971c6ccca6].

So the evidence does **not** support a strong claim that fixed caps are broadly inadequate. Rather, it supports a narrower claim:
- fixed caps are a decent baseline,
- but adaptive stopping often improves on them,
- especially when the system has a meaningful signal about whether more evidence would help.

## 4) What I could verify about "Don't Stop Early"

I was able to read only the abstract-level content already in corpus for *Don't Stop Early*; I still could not verify full paper details beyond that. The abstract claims:
- enterprise deep research fails from "uneven information coverage, context explosion, and premature stopping"
- the system "enforces evidence-based completion criteria so agents iteratively collect information until sufficiency conditions are met"
- these criteria "reduce premature stopping and improve the consistency and depth of enterprise research outputs" [source-80437d80a1b5]

These claims are **plausible and directionally consistent** with the independent evidence above, especially Stop-RAG and adaptive-compute work. But I could not independently confirm the paper's internal ablation details, exact benchmark deltas, or whether it isolates evidence-sufficiency conditions from other architectural changes.

So my verdict does **not** rest on taking *Don't Stop Early* at face value. It rests on the fact that other papers independently show the same pattern.

## 5) Important counter-evidence against naive coverage/checklist interpretations

One reason to be careful: **coverage-like metrics do not always track true research quality**.

ResearcherBench evaluates deep research systems with expert rubrics plus factual metrics including groundedness/coverage, and finds that "Groundedness score and research quality show little correlation in frontier research evaluation" [source-c176e1f5578c]. It even reports that the best rubric performer had low groundedness, while the most grounded system had only mediocre rubric performance [source-c176e1f5578c]. The authors conclude that in frontier research, "valuable insights often emerge from deep synthesis and reasoning processes that transcend direct source attribution" [source-c176e1f5578c].

This does **not** refute adaptive stopping in general. But it does refute an overly simplistic version of the claim such as:
- more checklist coverage always means better stopping,
- or citation/coverage completeness is a universally valid stopping target.

The evidence supports **evidence-aware stopping**, but not necessarily **coverage-maximization as a universal proxy** for research quality.

## Bottom line

### Verdict: SUPPORTS
Independent evidence supports the core claim that **adaptive stopping based on evidence sufficiency / verification / detected remaining gaps usually produces better stopping behavior than hard iteration caps alone**.

### Why only medium confidence, not high?
Because the evidence is mixed in three ways:
1. The best direct paper (Stop-RAG) includes a real failure case where fixed iteration wins on one setting [source-746fd5df720b].
2. Some strong support comes from neighboring domains (iterative RAG, test-time compute allocation), not deep-research agents strictly defined [source-47166651eca6].
3. I could not fully fetch and audit the body of *Don't Stop Early*, so I cannot independently verify its detailed empirical claims beyond the abstract [source-80437d80a1b5].

### Most defensible formulation of the claim
A careful version that the evidence supports is:

> Compared with hard iteration caps alone, stopping mechanisms that use explicit evidence sufficiency, verifier signals, or identified knowledge gaps generally improve stopping decisions and end-task quality, but the advantage is task-dependent and depends on the quality of the stopping signal.

That formulation is supported by [source-746fd5df720b], [source-47166651eca6], and qualified by [source-fa971c6ccca6] and [source-c176e1f5578c].

## Sources

- **[source-80437d80a1b5]** [Don't Stop Early: Scalable Enterprise Deep Research with Controlled Information Flow and Evidence-Aware Termination](https://arxiv.org/abs/2604.24978) - tier 2
  - Evidence-based termination criteria — each research step defines explicit sufficiency conditions before execution. Agents gather and evaluate evidence until these conditions are met, reducing early termination and improving consistency in analytical depth.
- **[source-fb6ad62c2856]** [How Termination Conditions Strengthen Agentic Systems in R&D - Causaly](https://www.causaly.com/blog/how-termination-conditions-strengthen-agentic-systems-in-r-d) - tier 3
  - Reflects implicit thresholds on evidence completeness, methodological clarity, limitations, and residual risk. Termination conditions are predefined criteria specifying when an AI agent's task is complete or when it must stop.
- **[source-c235a27ece59]** [Enough is Enough: Towards Autonomous Uncertainty-driven Stopping Criteria](https://arxiv.org/html/2204.10631) - tier 2
  - Addresses the practical problem of autonomously deciding when exploration must be terminated or changed — stopping criteria based on uncertainty for autonomous robotic exploration.
- **[source-84eb244e9438]** [How Agentic Search Actually Works: The Research Loop Link-Fetching Agents Miss](https://dev.to/tokozen/how-agentic-search-actually-works-the-research-loop-link-fetching-agents-miss-6ln) - tier 4
  - Too aggressive and the agent stops after one good-looking result. Too lenient and it loops until token or cost limit. A small LLM call scoring coverage against a checklist derived from the original goal works better.
- **[source-c757cfcfc0f7]** [The Agent Deployment Gap: Why Your LLM Loop Isn't Production-Ready](https://www.zenml.io/blog/the-agent-deployment-gap-why-your-llm-loop-isnt-production-ready-and-what-to-do-about-it) - not-tiered
  - At its core, an agent is just a loop with tools and an LLM — while not task_complete: think, choose_tool, execute, update context. Discusses production-readiness challenges.
- **[source-c558bba4bb5a]** [The Agentic Researcher: A Practical Guide to AI-Assisted Research in Mathematics and Machine Learning](https://arxiv.org/html/2603.15914v1) - tier 2
  - A major problem encountered was that despite having a long todo-list of potential tasks, the agent consistently stopped to ask whether it should continue — illustrating premature stopping behavior.
- **[source-32626245fd8b]** [Anthropic Just Proved That Agentic AI Needs Governance Harnesses](https://theairuntime.com/p/anthropic-just-proved-that-agentic) - not-tiered
  - Evaluating whether an agent stopped when it should have is central to governance. Introduces SAFE framework: Scope, Anchored Decisions, Flow Integrity, Escalation — for runtime control signals.
- **[source-440554f58fb7]** [Endless loop detection to avoid high LLM usage costs (browser-use GitHub issue)](https://github.com/browser-use/browser-use/issues/191) - not-tiered
  - Practical issue report about an agent getting into an endless loop in an agentic system, requesting loop detection mechanisms.
- **[source-e55202046006]** [What Is the AI Agent Loop? The Core Architecture Behind Autonomous AI Systems](https://blogs.oracle.com/developers/what-is-the-ai-agent-loop-the-core-architecture-behind-autonomous-ai-systems) - not-tiered
  - The agent loop operates across five stages (perceive, reason, act, update, repeat) until the task is complete or a stopping condition is met.
- **[source-34ba1d703705]** [Iteration Budget Pressure — Warn the LLM Before Max Iterations Hit (NousResearch hermes-agent issue)](https://github.com/NousResearch/hermes-agent/issues/414) - tier 3
  - Feature request: warn the LLM before max iterations hit using a budget pressure signal. Addresses the failure mode where agents exhaust iterations doing tool calls without producing a response.
- **[source-1769f8960de2]** [AI Agent Token Budget Management: How Claude Code Prevents Runaway API Costs](https://www.mindstudio.ai/blog/ai-agent-token-budget-management-claude-code) - tier 3
  - Claude Code enforces hard token limits, compaction thresholds, and pre-execution budget checks. Practical implementation patterns for agent token budget management.
- **[source-0e85c5aca940]** [AI Agent Architecture: Building Systems That Think, Plan, and Act](https://dev.to/tutorialq/ai-agent-architecture-building-systems-that-think-plan-and-act-4ca0) - tier 4
  - Set hard max_iterations limit (typically 5–10); implement token budget per request; after N iterations without convergence, force agent to summarize what it has and return.
- **[source-9ce246ba229a]** [Agent Loop Internals — Hermes Agent (NousResearch)](https://hermes-agent.nousresearch.com/docs/developer-guide/agent-loop) - tier 3
  - Each agent gets its own budget. Subagents get independent budgets capped at delegation.max_iterations (default 50). Total iterations across parent + subagents can exceed the parent's cap.
- **[source-d1dc95618197]** [Building a Deep Research Agent Using MCP-Agent](https://thealliance.ai/blog/building-a-deep-research-agent-using-mcp-agent) - tier 3
  - Budget manager for adaptive orchestrator — if time/cost/token budget is exceeded, it ends the workflow. Practical implementation of deep research agent using MCP-Agent.
- **[source-a9c7d0b52dc4]** [qx-labs/agents-deep-research: Iterative Deep Research (GitHub)](https://github.com/qx-labs/agents-deep-research) - tier 3
  - --max-time: maximum time in minutes before the research loop auto-exits to produce final output (default: 10). Open-source iterative deep research implementation using OpenAI Agents SDK.
- **[source-f54bec338412]** [Google Gemini Deep Research Max: The Best Research Agent Available via API](https://www.mindstudio.ai/blog/google-gemini-deep-research-max-api) - not-tiered
  - Standard Deep Research might run 20–30 search iterations. The 'Max' designation means the loop runs longer and harder.
- **[source-9d3d419b0c41]** [Saturation in Qualitative Research: Exploring its Conceptualization and Operationalization (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC5993836/) - tier 1 - peer-reviewed
  - Data saturation: the point at which new data no longer contributes additional insights. Grounded theory uses saturation to determine when to stop collecting new data — new data is redundant.
- **[source-d5880a33fc9c]** [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/html/2210.03629) - not-tiered
  - ReAct synergizes reasoning traces and task-specific actions in an interleaved manner, helping the model track and update action plans. Foundational paper for the ReAct agent framework.
- **[source-becd9d06fd92]** [FAIR-RAG: Faithful Adaptive Iterative Refinement for Retrieval-Augmented Generation](https://arxiv.org/html/2510.22344) - tier 2
  - FAIR-RAG: agentic framework that transforms RAG into dynamic, evidence-driven reasoning that iteratively identifies and fills evidence gaps. Relevant for iterative retrieval stopping logic.
- **[source-42d7cf59e123]** [Human-in-the-Loop in Agentic Workflows: From Definition to Walkthrough (Orkes)](https://orkes.io/blog/human-in-the-loop/) - not-tiered
  - Inserting HUMAN task into agent workflow — configuring retry logic, timeouts, escalation paths. Production pattern for human-in-the-loop in agentic workflows.
- **[source-d3ce3903f13b]** [Human-in-the-Loop: A 2026 Guide to AI Oversight and Escalation](https://www.strata.io/blog/agentic-identity/practicing-the-human-in-the-loop/) - not-tiered
  - Identity-aware orchestration layer that can pause agent execution, route approval requests to authorized humans, enforce time-boxed decision windows, and log every intervention for audit.
- **[source-fdefed7cacca]** [How OpenAI's Deep Research Works (PromptLayer blog)](https://blog.promptlayer.com/how-deep-research-works/) - not-tiered
  - OpenAI Deep Research follows the classic Plan-Act-Observe loop from the ReAct paradigm. Explains the internal architecture and how the loop runs.
- **[source-fc87b6c35a00]** [How OpenAI, Gemini, and Claude Use Agents to Power Deep Research (ByteByteGo)](https://blog.bytebytego.com/p/how-openai-gemini-and-claude-use) - not-tiered
  - How OpenAI, Gemini, and Claude use agents to power deep research. Perplexity's deep research agent uses an iterative information retrieval loop. Compares architectures across providers.
- **[source-2d6bdd8963cb]** [Agent-Oriented Planning in Multi-Agent Systems (arXiv 2410.02189)](https://arxiv.org/html/2410.02189v2) - tier 2
  - Agent-oriented planning in multi-agent systems: completeness detector checks all key elements from original query are covered by subtasks; non-redundancy principle. More than 15% of queries exhibit coverage issues during decomposition.
- **[source-fcf6bd1472e1]** [Demystifying Evals for AI Agents (Anthropic Engineering)](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) - not-tiered
  - Anthropic engineering post on demystifying evals for AI agents. LLM-based rubrics can flag unsupported claims and gaps in coverage, verify coherence and completeness of research outputs.
- **[source-c6717e1f8f94]** [Deep Research API with the Agents SDK (OpenAI Cookbook)](https://developers.openai.com/cookbook/examples/deep_research_api/introduction_to_deep_research_api_agents) - not-tiered
  - OpenAI Deep Research API: patterns for scalable, production-ready research workflows using modular multi-agent design — triage, clarification, instruction, and research agents.
- **[source-34e0c4463e28]** [I Built Open Source Deep Research — Here's How It Works (Reddit/LLMDevs)](https://www.reddit.com/r/LLMDevs/comments/1jpfa8f/i_built_open_source_deep_research_heres_how_it/) - not-tiered
  - Open-source deep research: 5–7 research loops running in parallel for different sub-topics, feeding back findings to a writing agent for consolidation. Illustrates multi-threaded research loop design.
- **[source-bd4d3c0f3779]** [How to Set Graceful Degradation Timeouts for AI Agents (how2.sh)](https://how2.sh/posts/how-to-build-agent-tool-timeout-envelopes-for-safer-rollouts-for-mission-critical-automations/) - tier 3
  - Implement graceful degradation timeouts for AI agent tool calls so agents return partial results instead of failing completely.
- **[source-6f782bdd101d]** [A New Query Expansion Approach via Agent-Mediated Dialogic Inquiry](https://arxiv.org/html/2502.08557) - not-tiered
  - Query expansion via agent-mediated dialogic inquiry: Socratic Questioning Agent reformulates queries iteratively. Relevant to how research agents refine information needs before stopping.
- **[source-ecfbfdca31af]** [Agent Contracts: A Formal Framework for Resource-Bounded Autonomous AI Systems](https://arxiv.org/html/2601.08815) - tier 2 - peer-reviewed
  - Formal framework for resource-bounded agents: unifies input/output specs, multi-dimensional resource constraints, temporal boundaries, and success criteria into coherent governance.
- **[source-97c2ea8cfae2]** [Deep Researcher Agent: An Autonomous Framework for 24/7 Deep Learning Experimentation with Zero-Cost Monitoring](https://arxiv.org/html/2604.05854v1) - tier 2
  - Deep Researcher Agent with continuous Think-Reflect-Execute loop; operates at zero LLM cost during GPU training (90–99% of wall-clock time) with two-tier memory system maintaining constant size.
- **[source-0f9186e0d22a]** [Context Engineering for AI Agents: Token Economics and Production Optimization Strategies](https://www.getmaxim.ai/articles/context-engineering-for-ai-agents-production-optimization-strategies/) - not-tiered
  - Implementation patterns for context window budget management: token accounting, compaction thresholds, pre-execution checks, and configurable warning thresholds.
- **[source-c807f40d5009]** [Add per-request wall-clock timeout budget (Hermes Agent Issue #5450)](https://github.com/NousResearch/hermes-agent/issues/5450) - not-tiered
  - Wall-clock timeout architecture: distinguishes between stale stream detection (180s default) and total request budget; activity-based timeout avoids killing long-running but active processes.
- **[source-10d296e4cf40]** [How AI Agents Handle Stalled Tasks and Timeouts: Lessons From My Production Failure](https://dev.to/bobrenze/how-ai-agents-handle-stalled-tasks-and-timeouts-lessons-from-my-production-failure-1jj9) - not-tiered
  - Practical lessons on enforcing hard wall-clock timeouts: every task has maximum duration (not estimated but enforced); exceeding it kills the task.
- **[source-0a30658a044b]** [What Is Agent Orchestration? Why It's the Biggest Unsolved Problem in the AI Stack](https://www.mindstudio.ai/blog/agent-orchestration-biggest-unsolved-problem-ai-stack) - not-tiered
  - Cost envelopes for agent orchestration: every agent run has a defined budget that stops the agent execution when exceeded (not just alerts). Orchestrator-to-subagent delegation with audit trails and escalation.
- **[source-c8c64b52fe9f]** [GRAPH_RECURSION_LIMIT - LangChain Docs](https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT) - tier 3
  - Official LangGraph error documentation on GRAPH_RECURSION_LIMIT: when a StateGraph reaches the maximum number of steps before hitting a stop condition, often due to infinite loops.
- **[source-bc763ba57205]** [Setting Recursion Limit in LangGraph StateGraph - Stack Overflow](https://stackoverflow.com/questions/78337975/setting-recursion-limit-in-langgraphs-stategraph-with-pregel-engine) - not-tiered
  - Stack Overflow Q&A: How to set recursion limit in LangGraph's StateGraph with Pregel engine. Example error: GraphRecursionError with limit of 25 reached.
- **[source-04d30b6a54cf]** [LangGraph Bug #6731: Agent infinite looping until recursion limit](https://github.com/langchain-ai/langgraph/issues/6731) - tier 3
  - GitHub issue: Agent infinite looping until recursion limit error is hit. Shows error with recursion limit of 20, mentions setting `recursion_limit` config key as fix.
- **[source-9810262f98c1]** [Agent Recursion Between Tools and Agent - LangGraph Discussion #1725](https://github.com/langchain-ai/langgraph/discussions/1725) - not-tiered
  - GitHub discussion: Agent falls back into infinite loop continuously jumping between agent and tool node after tool returns response.
- **[source-7b44b27ca9de]** [Define How Deep Your LangGraph Agent Should Think - Medium](https://medium.com/fundamentals-of-artificial-intelligence/define-how-deep-your-langgraph-agent-should-think-0aca2acdaceb) - not-tiered
  - Medium article: How to handle LangGraph recursion limits, infinite loops, and maximum recursion error in agent workflows.
- **[source-247411f9f938]** [Reddit: Why Does the Recursion Limit Exist in LangGraph?](https://www.reddit.com/r/LangChain/comments/1h226yc/discussion_why_does_the_recursion_limit_exist_in/) - not-tiered
  - Reddit discussion from LangChain community: Explores why recursion limits exist—performance vs. infinite loop prevention—in complex multi-branch agents.
- **[source-41e7a02ca873]** [Cap the max number of iterations - LangChain Official Docs](https://python.langchain.com/v0.1/docs/modules/agents/how_to/max_iterations/) - not-tiered
  - Official LangChain documentation on capping agent max iterations. Shows AgentExecutor configuration for max_iterations, max_execution_time, and early_stopping_method.
- **[source-27538cda1303]** [10 Quick Fixes to Stop AI Agent Loops - Max Iterations in LangChain](https://inforsome.com/agent-max-iterations-fix/) - not-tiered
  - Technical guide: How to fix LangChain agent max_iterations stops. Shows AgentExecutor config with max_iterations=30, max_execution_time=60, early_stopping_method=generate.
- **[source-42297664e5ca]** [Agent stopped due to max iterations: fixes that work](https://doinamerica.com/agent-stopped-max-iterations-fix/) - not-tiered
  - Explains LangChain agent safety cap: Agent stopped due to max iterations means the AI agent hit its iteration safety cap (often max_steps) and quit before finishing.
- **[source-e2d81701f305]** [LangGraph GitHub Repository](https://github.com/langchain-ai/langgraph) - not-tiered
  - Official LangGraph GitHub repo: Build resilient language agents as graphs. Provides durable execution with automatic failure recovery and resumption.
- **[source-f16adbc59769]** [Agent AI with LangGraph: A Modular Framework for Machine Translation](https://arxiv.org/html/2412.03801) - not-tiered
  - Peer-reviewed: LangGraph application for modular agent design in machine translation, demonstrating LangGraph's graph-based execution model.
- **[source-ee6a4cb78077]** [Intelligent Spark Agents: A Modular LangGraph Framework for ML Workflows](https://arxiv.org/html/2412.01490) - not-tiered
  - Peer-reviewed: Modular LangGraph framework for scalable machine learning workflows, covering agent orchestration and graph-structured execution.
- **[source-828481dd4d95]** [LLM Multi-Agent Implementation Based on LangGraph and CrewAI](https://arxiv.org/html/2411.18241) - not-tiered
  - LangGraph and CrewAI integration for multi-agent systems, focusing on graph architecture efficiency and team collaboration.
- **[source-99aac1516aa6]** [Budget-Aware Tool-Use Enables Effective Agent Scaling](https://arxiv.org/html/2511.17006v1) - tier 2
  - Budget-aware tool-use: agents continue sampling new sequences until the budget is fully consumed; number of sampled sequences varies across questions based on budget constraint enforcement.
- **[source-fa971c6ccca6]** [Quantifying the Accuracy and Cost Impact of Design Decisions in Budget-Constrained Agentic LLM Search](https://arxiv.org/html/2603.08877) - tier 2
  - Budget-Constrained Agent Search (BCAS): tracks remaining search calls and cumulative completion budget; search cap enforced as hard tool constraint — once exhausted, search tool removed from available actions.
- **[source-6611926d4d62]** [AgentBudget - Real-time cost enforcement for AI agents](https://agentbudget.dev) - not-tiered
  - AgentBudget: real-time cost enforcement for AI agents with automatic tracking of spent/remaining budget and full cost breakdowns using zero-change client wrapper pattern.
- **[source-f442d30fa537]** [How AI Agent Payments Actually Work — And Where They Break](https://dev.to/maxberg/how-ai-agent-payments-actually-work-and-where-they-break-183m) - not-tiered
  - Framework comparison: CrewAI has iteration caps, LangChain has observability hooks, but most lack pre-execution enforcement of dollar-denominated policies — monitoring exists but hard enforcement is rare.
- **[source-f4b5ab725d1c]** [AI Agent Budget Control: Enforce Hard Spend Limits — Cycles](https://runcycles.io/blog/ai-agent-budget-control-enforce-hard-spend-limits) - not-tiered
  - AI Agent Budget Control: atomic reservations for enforcement; budget controls generate operational data dashboards alone cannot provide for tracking failures.
- **[source-b77ea5b3bb13]** [Hermes Agent v0.13 Reference: Tenacity + Multi-Agent Kanban + /goal + Pluggable Providers](https://blakecrosley.com/guides/hermes) - not-tiered
  - Hermes Agent v0.13: iteration budget pressure warns model before exhaustion (default: 90 turns); budget pressure triggers at two tiers based on remaining iterations (default maxIterations = 20 for main agent).
- **[source-20d38084afc2]** [Why Does Your AI Agent Get Stuck in Infinite Loops?](https://www.pithycyborg.com/why-does-your-ai-agent-get-stuck-in-infinite-loops/) - tier 3
  - AI agents loop because they have no native mechanism to detect that they are repeating themselves. The agent issues a tool call, receives an ambiguous result, issues the same tool call again, and continues indefinitely.
- **[source-d8dbf4ae7a15]** [Why AI Agents Get Stuck in Loops, and How to Prevent It](https://www.fixbrokenaiapps.com/blog/ai-agents-infinite-loops) - tier 4
  - Loop Drift occurs when the agent misinterprets termination signals, generates repetitive actions, or suffers from inconsistent internal state, leading to endless execution.
- **[source-e59a3ebaa169]** [The Agent Loop Problem: When "Smart" Won't Stop](https://medium.com/@Modexa/the-agent-loop-problem-when-smart-wont-stop-ccbf8489180f) - not-tiered
  - Minimal pattern that stops infinite tool ping-pong using hashlib fingerprinting of tool and args. Shows normalized state hashing approach for loop detection.
- **[source-8abe32b8435d]** [r/AI_Agents on Reddit: The "Infinite Loop" fear is real. How are you preventing your agents from burning $100 in 10 minutes?](https://www.reddit.com/r/AI_Agents/comments/1qnavt9/the_infinite_loop_fear_is_real_how_are_you/) - not-tiered
  - Checking signatures of each tool call before execution. Same tool + same args = cached result. Same tool + slightly rephrased args = jitter detection with counter-based blocking.
- **[source-ecb9eabede6e]** [Fix Infinite Loops in Multi-Agent Chat Frameworks in 20 Minutes](https://markaicode.com/fix-infinite-loops-multi-agent-chat/) - tier 3
  - Detect infinite loops by hashing recent messages to catch cycles through the same ideas without making progress.
- **[source-559e6e9779bc]** [Formalizing the Safety, Security, and Functional Properties of Agentic AI Systems](https://arxiv.org/html/2510.14133v2) - not-tiered
  - Formal verification of system behavior using temporal logic to enable detection of coordination edge cases and prevention of deadlocks.
- **[source-1c754aa7f252]** [r/AI_associates on Reddit: Agent-to-agent deadlocks are the most boring but most deadly failure mode](https://www.reddit.com/r/AI_associates/comments/1ndffjp/agenttoagent_deadlocks_are_the_most_boring_but/) - not-tiered
  - Deadlock detection using wait-for graphs: model agent dependencies like in operating systems. If Agent A waits for B while B waits for A, detect a cycle.
- **[source-b4bf6896d656]** [recursionLimit config ignored in LangGraphJS Issue #1524](https://github.com/langchain-ai/langgraphjs/issues/1524) - tier 3
  - GitHub issue #1524: recursionLimit config ignored in LangGraphJS, default still 25 even when withConfig() override attempted.
- **[source-278a6628c813]** [GRAPH_RECURSION_LIMIT Troubleshooting Guide - LangGraph GitHub](https://github.com/langchain-ai/langgraph/blob/main/docs/docs/troubleshooting/errors/GRAPH_RECURSION_LIMIT.md) - not-tiered
  - Official LangGraph troubleshooting doc: Complex graphs can hit default recursion_limit naturally. Pass higher recursion_limit value in config when invoking graph.
- **[source-d1ac481e8eae]** [LangChain AgentExecutor max_iterations Default (15)](https://sj-langchain.readthedocs.io/en/latest/agents/langchain.agents.agent.AgentExecutor.html) - tier 1
  - LangChain AgentExecutor API: Default max_iterations is 15. Controls maximum number of steps to take before ending execution loop.
- **[source-f1b15af94956]** [AgentExecutor Field Reference - LangChain 0.0.107](https://langchain-doc.readthedocs.io/en/latest/reference/modules/agents.html) - not-tiered
  - Official LangChain docs show AgentExecutor max_iterations default is 15, early_stopping_method='force'. Standard pattern for agent loop safety.
- **[source-38b0837555ca]** [LangChain Agent Executor Deep Dive - Aurelio AI](https://www.aurelio.ai/learn/langchain-agent-executor) - not-tiered
  - LangChain Agent Executor Deep Dive: Custom implementation example with max_iterations config pattern in agent initialization.
- **[source-e5554bbdce2a]** [Claude Code Context Window: Optimize Your Token Usage](https://claudefa.st/blog/guide/mechanics/context-management) - not-tiered
  - Claude Code token enforcement: tracks running tally of context size using API response token counts; halts or compacts before crossing configurable threshold. Uses compaction blocks to summarize conversation.
- **[source-d284e9dab258]** [Claude Code Costs: How We Cut $13/dev/day to $4 (Real Scripts)](https://branch8.com/posts/claude-code-token-limits-cost-optimization-apac-teams) - not-tiered
  - Practical session limits: sessionLimit 500K tokens before compact/restart; dailyLimit 2M tokens/day per dev (~$6-8); autoCompactAt triggers at 60% of session limit to avoid hard wall.
- **[source-9dc66e028d90]** [Compaction - Claude API Docs](https://platform.claude.com/docs/en/build-with-claude/compaction) - not-tiered
  - Compaction API pattern: detects input token threshold exceedance; generates conversation summary; creates compaction block; continues response with compacted context to free memory.
- **[source-8e28179197e2]** [Markaicode: Stop AI Agent Loops in Autonomous Coding — Circuit Breaker and Memory Integration](https://markaicode.com/fix-ai-agent-looping-autonomous-coding/) - not-tiered
  - Circuit-breaker logic integrating memory into agent execution loop; feedback mechanism that surfaces patterns invisible to LLM alone for autonomous coding agents.
- **[source-705d04615966]** [FAILURE.md — AI Agent Failure Mode Protocol](https://failure.md/) - not-tiered
  - Defines failure modes and escalation: graceful degradation (reduced capability), partial failure (isolation/retries), cascading failure (circuit breaker), silent failure (quarantine/human review).
- **[source-326066343111]** [Medium: Resilience Circuit Breakers for Agentic AI — Graceful Degradation and Escalation](https://medium.com/@michael.hannecke/resilience-circuit-breakers-for-agentic-ai-cc7075101486) - not-tiered
  - Circuit breaker patterns: graceful degradation (reduced capability, limit reasoning), escalation (human handoff, alternative agent, queue). Production reliability patterns.
- **[source-09c22853351e]** [DEV Community: AI Agent Circuit Breakers — The Reliability Pattern Production Teams Miss](https://dev.to/waxell/ai-agent-circuit-breakers-the-reliability-pattern-production-teams-are-missing-5bpg) - not-tiered
  - After three consecutive failures on same step, default should be termination and escalation (not retry). Detects scope violations and cascading failures.
- **[source-8da217475603]** [Cordum: AI Agent Circuit Breaker Pattern — Policy Fail Modes and Production Observability](https://cordum.io/blog/ai-agent-circuit-breaker-pattern) - not-tiered
  - Circuit breaker controls for AI agents: policy fail modes, retry boundaries, and production-grade observability for stopping cascading tool failures.
- **[source-b625946dee94]** [Meganova: Circuit Breakers in AI Agent Systems — Reliability at Scale](https://blog.meganova.ai/circuit-breakers-in-ai-agent-systems-reliability-at-scale/) - not-tiered
  - Circuit breaker prevents one unavailable model from taking down entire system. Audit trails, graceful degradation, and fallback activation logging for compliance.
- **[source-15c64906e5e7]** [DEV Community: 5 AI Agent Error Handling Patterns — Layered Defense Preventing Runaway Spirals](https://dev.to/thedailyagent/5-ai-agent-error-handling-patterns-that-keep-your-agent-running-at-3-am-2j0j) - not-tiered
  - Four-layer error handling: Layer 1 catches model degradation before token burn; Layer 2 blocks dangerous actions; Layer 3 contains partial failures; Layer 4 limits blast radius when agent spirals.
- **[source-4fc42d21e432]** [Brandon Lincoln Hendricks: Circuit Breaker Patterns for AI Agent Reliability — Production Implementation](https://brandonlincolnhendricks.com/research/circuit-breaker-patterns-ai-agent-reliability) - not-tiered
  - Load testing to verify graceful degradation rather than collapse. Gradually increase request rates until circuit breakers open; test failure modes systematically.
- **[source-40ef670856d1]** [DEV Community: How to Build AI Agents That Fail Safely — Circuit Breakers, Health Checks, Graceful Degradation](https://dev.to/the_bookmaster/how-to-build-ai-agents-that-fail-safely-circuit-breakers-health-checks-and-graceful-degradation-4c0i) - not-tiered
  - Comprehensive patterns for production-ready agents: circuit breakers, health checks, graceful degradation. Turning 'magic' into reliable systems.
- **[source-a2753f52aac5]** [Galileo: Why Multi-Agent Systems Fail — Context Collapse and Lossy Compression Tradeoffs](https://galileo.ai/blog/why-multi-agent-systems-fail) - not-tiered
  - Context collapse and lossy compression tradeoff: summarizing context saves tokens but risks losing critical edge-case details defined by earlier agents.
- **[source-f6c1dfcfda24]** [Why Do Multi-Agent LLM Systems Fail? (arXiv 2503.13657)](https://arxiv.org/html/2503.13657v3) - not-tiered
  - Framework using LLM agents to quantify multi-dimensional evaluation criteria. AgDebugger and MAS debugger tools for inspecting, editing, and debugging agent message histories and failures.
- **[source-8e9727219002]** [BuildMVPFast: LLM Error Handling and Fallback Strategies — Retry, Fallback Chains, Graceful UX](https://www.buildmvpfast.com/blog/building-with-unreliable-ai-error-handling-fallback-strategies-2026) - not-tiered
  - Production patterns: retry with backoff, multi-model fallback chains, circuit breakers, and graceful degradation UX based on real outage data.
- **[source-e3d2d8498901]** [ORQ: Why Multi-Agent LLM Systems Fail — Evaluators, Validators, and Loop Detection](https://orq.ai/blog/why-do-multi-agent-llm-systems-fail) - not-tiered
  - Use evaluators (RAGAS, LLM-as-Judge) to validate collaborative output. Move to production with controlled handoffs, output validators, fallback logic, and loop detection.
- **[source-be0c21c35dea]** [FutureAGI: Why Multi-Agent LLM Systems Fail (2026 Guide) — Structured Summaries vs Raw History](https://futureagi.substack.com/p/why-do-multi-agent-llm-systems-fail) - not-tiered
  - Fix context collapse: stop passing raw conversation history; use structured summaries and explicit state objects capturing key decisions instead.
- **[source-85dda179ef69]** [Managing Complex Failure Analysis Workflows with LLM-based Reasoning and Acting Agents (arXiv)](https://arxiv.org/html/2506.15567v1) - not-tiered
  - Custom agent wrapper managing ReAct loop until final response. Parameters: timeout, maximum iterations, parsing error recovery. AgentExecutor pattern.
- **[source-e50b46072eb8]** [A-MEM: Agentic Memory for LLM Agents](https://arxiv.org/abs/2502.12110) - not-tiered
  - A-MEM: Agentic Memory for LLM Agents - memory systems for LLM agents that go beyond basic storage/retrieval with sophisticated memory organization to prevent loops.
- **[source-798defcf48a0]** [Stop Your AI Agents From Crashing, Looping, and Burning Through Tokens](https://dev.to/pavelgj/stop-your-ai-agents-from-crashing-looping-and-burning-through-tokens-2g70) - not-tiered
  - Three open-source middleware for Google's Genkit that handle graceful error recovery, intelligent loop detection, and automatic context compression.
- **[source-da0597cfd09f]** [Agentic Resource Exhaustion: The "Infinite Loop" Attack of the AI Era](https://medium.com/@instatunnel/agentic-resource-exhaustion-the-infinite-loop-attack-of-the-ai-era-76a3f58c62e3) - not-tiered
  - The enterprise AI control plane needs continuous authorization on every resource agents touch, with verification before every action and least-privilege access controls.
- **[source-e8238c60d45e]** [Agents: Loop Control (Vercel AI SDK)](https://ai-sdk.dev/docs/agents/loop-control) - not-tiered
  - stopWhen parameter controls when to stop execution based on tool results. Default is stepCountIs(20) as safety measure to prevent runaway loops.
- **[source-b3d1110d7c01]** [Feature Request: Implement Agentic Loop Detection Service (Claude Code)](https://github.com/anthropics/claude-code/issues/4277) - not-tiered
  - Feature request for Loop Detection Service that actively monitors agent behavior during a turn to identify and halt repetitive loops early.
- **[source-0aaa790256c4]** [Agentic AI: The Agent Loop & Tools for Building Autonomous Agents (You.com)](https://you.com/resources/the-agent-loop-how-ai-agents-actually-work-and-how-to-build-one) - not-tiered
  - After evaluating outcomes, agents must decide to iterate or stop based on control logic (state machines, LangGraph, Temporal) with safeguards like rate limits, iteration caps, and timeouts.
- **[source-585d6f71c5b9]** [Agentic AI's OODA Loop Problem](https://www.schneier.com/blog/archives/2025/10/agentic-ais-ooda-loop-problem.html) - not-tiered
  - Agentic AI security trilemma: fast, smart, secure — pick any two. Fast and smart means you can't verify inputs. Smart and secure means slow because AI itself can't be used for verification.
- **[source-b1ed15786d6e]** [r/AI_Agents on Reddit: How to un loop AI agents?](https://www.reddit.com/r/AI_Agents/comments/1s7th7b/how_to_un_loop_ai_agents/) - not-tiered
  - Fingerprint the state each step or take a compact snapshot. If agent proposes same tool call against same state, don't run it. Add hard guard for repeated (state, action) pairs to prevent replaying.
- **[source-03901d5ac2f3]** [LangGraph - State Graphs for Agentic Workflows](https://vanducng.dev/2025/05/29/LangGraph-State-Graphs-for-Agentic-Workflows/) - not-tiered
  - LangGraph: state graphs are directed graphs where each node is a step and edges define transitions. State changes are explicit and traceable. Loops are bounded by graph structure.
- **[source-454677471160]** [AgentDiagnose: An Open Toolkit for Diagnosing LLM Agent Trajectories](https://aclanthology.org/2025.emnlp-demos.15/) - not-tiered
  - AgentDiagnose: evaluation module for five agentic competencies including backtracking & exploration, and visualization via t-SNE action embeddings, word clouds, and state-transition timelines.
- **[source-c50edfba6a2c]** [Agent Trajectory Monitors: Ensuring AI Agents Follow The Right Path](https://www.montecarlodata.com/blog-agent-trajectory-monitors) - not-tiered
  - Agent Trajectory Monitors allow teams to define expected trajectories and receive alerts when traces violate expectations, enabling detection of unexpected behavior changes.
- **[source-0d7c429d8bc8]** [Agent Tracing for Debugging Multi-Agent AI Systems](https://www.getmaxim.ai/articles/agent-tracing-for-debugging-multi-agent-ai-systems/) - not-tiered
  - Agent Tracing captures every decision, message, and state transition across agents. Platforms provide distributed tracing, visual replay, automated evaluation, and in-context debugging.
- **[source-1cccb63a90ce]** [How to evaluate your agent with trajectory evaluations - LangChain Docs](https://docs.langchain.com/langsmith/trajectory-evals) - not-tiered
  - LangChain trajectory evals: evaluate agent trajectories via trajectory match against reference or LLM judge on exact sequence of messages and tool calls.
- **[source-e4a25ecaf5c2]** [A Study of Thought-Action-Result Trajectories](https://software-lab.org/publications/ase2025_trajectories.pdf) - not-tiered
  - A Study of Thought-Action-Result Trajectories: mining sequential action patterns in agent trajectories to identify recurrent decision-making patterns and state transitions.
- **[source-752b431d0730]** [ResearchRubrics: A Benchmark of Prompts and Rubrics For Evaluating Deep Research Agents](https://arxiv.org/html/2511.07685v1) - not-tiered
  - Standardized benchmark with 2,500+ expert-written rubrics to assess deep research agents on factual grounding, reasoning, and clarity. Can evaluate stopping criteria effectiveness through rubric pass/fail rates.
- **[source-773016154043]** [Review, Refine, Repeat: Understanding Iterative Decoding of AI Agents with Dynamic Evaluation and Selection](https://arxiv.org/html/2504.01931v1) - not-tiered
  - Addresses trade-off between quality improvement and computational efficiency in iterative decoding for agentic tasks. Explores adaptive stopping, speculative decoding, and verifier-guided selection for efficiency.
- **[source-c603dbd7d510]** [DeepResearch Bench II: Diagnosing Deep Research Agents via Rubrics from Expert Report](https://arxiv.org/html/2601.08536v1) - not-tiered
  - Benchmark comparing diverse deep research systems (OpenAI, Gemini, Perplexity, Qwen, etc.) with binary rubric scoring. Evaluates stopping effectiveness across multiple commercial and open systems.
- **[source-0940134cd3d4]** [A Rigorous Benchmark with Multidimensional Evaluation for Deep Research Agents: From Answers to Reports](https://arxiv.org/html/2510.02190v1) - not-tiered
  - Rigorous multidimensional evaluation of 13 models including 5 deep research agents; uses zero temperature for reproducibility and independent rubric scoring on semantic quality.
- **[source-f225d4805fd8]** [Evidence Sufficiency Under Delayed Ground Truth: Proxy Monitoring for Risk Decision Systems](https://arxiv.org/html/2604.15740) - not-tiered
  - Formalizes evidence sufficiency with four dimensions (completeness, freshness, reliability, representativeness) and decision-readiness gates. Relevant framework for evidence-based termination criteria.
- **[source-746fd5df720b]** [Stop-RAG: Value-Based Retrieval Control for Iterative RAG](https://arxiv.org/html/2510.14337v1) - tier 2
  - Adaptive stopping criteria trained with forward-value for retrieval control. Consistently outperforms fixed-iteration baselines on multi-hop QA benchmarks.
- **[source-83204a9e78a1]** [Knowledge-Aware Iterative Retrieval for Multi-Agent Systems](https://arxiv.org/html/2503.13275v2) - not-tiered
  - Systematic gap detection and targeted re-querying mechanisms for iterative retrieval. Filters contexts using knowledge-based relevance, contrasting with static search strategies.
- **[source-cbb4862a2937]** [SAGE: Benchmarking and Improving Retrieval for Deep Research Agents](https://arxiv.org/html/2602.05975) - not-tiered
  - Benchmark for scientific literature retrieval with 1,200 queries across four domains. Evaluates six deep research agents; all systems struggle with reasoning-intensive retrieval.
- **[source-a07049c4d5f0]** [Static-DRA: A Hierarchical Tree-based Approach for Deep Research Agents](https://arxiv.org/html/2512.03887) - not-tiered
  - Configurable Depth and Breadth parameters for controlling research intensity. Hierarchical tree-based static workflow for deep research.
- **[source-06b1593f627e]** [IGMiRAG: Intuition-Guided Retrieval-Augmented Generation with Adaptive Mining](https://arxiv.org/html/2602.07525) - not-tiered
  - Hierarchical heterogeneous hypergraph with adaptive mining of in-depth memory. Addresses costly disjointed retrieval in traditional approaches.
- **[source-b0b4f76eed7c]** [RAG-Gym: Systematic Optimization of Language Agents for RAG](https://arxiv.org/html/2502.13957) - not-tiered
  - Comprehensive platform exploring prompt engineering, actor tuning, and critic training for agentic RAG. Includes Re-squared-Search framework.
- **[source-c176e1f5578c]** [ResearcherBench: Evaluating Deep AI Research Systems on the Frontiers of Scientific Inquiry](https://arxiv.org/pdf/2507.16280) - tier 2
  - First benchmark focused on frontier AI scientific questions. Evaluates coverage-based criteria: high groundedness (citation coverage) doesn't always correlate with research quality—valuable insights emerge from creative synthesis.
- **[source-0052fb9c95bf]** [When Iterative RAG Beats Ideal Evidence: A Diagnostic Study in Scientific Multi-hop QA](https://arxiv.org/html/2601.19827v1) - not-tiered
  - Diagnostic study on iterative RAG vs ideal evidence. FAIR-RAG formalizes evidence sufficiency by decomposing questions, identifying gaps, triggering targeted query refinement until evidence is complete.
- **[source-f8ecfdd49acc]** [RMIT-ADM+S / R2RAG: Adaptive Retrieval with Evidence Sufficiency at NeurIPS 2025](https://arxiv.org/html/2602.20735) - not-tiered
  - Award-winning NeurIPS competition system. R2RAG: dynamically adapts retrieval strategy based on inferred query complexity and evidence sufficiency using lightweight components.
- **[source-d98dbb659192]** [MultiHop-RAG: Benchmarking Retrieval-Augmented Generation for Multi-Hop Queries](https://arxiv.org/html/2401.15391) - not-tiered
  - Multi-hop QA benchmark with dataset; existing RAG systems inadequate. Comprehensive evaluation framework for multi-hop reasoning and evidence retrieval.
- **[source-656086127109]** [Retrieval Augmented Generation (RAG) for Fintech: Agentic Design and Evaluation](https://arxiv.org/html/2510.25518) - not-tiered
  - Agentic RAG for fintech with query reformulation, sub-query decomposition, acronym resolution, and cross-encoder reranking. Specialized domain handling with iterative refinement.
- **[source-4dd5b361004b]** [The Cost of Dynamic Reasoning: Demystifying AI Agents and Test-Time Scaling from an AI Infrastructure Perspective](https://arxiv.org/html/2506.04301v1) - not-tiered
  - Infrastructure perspective on AI agents: Pareto analysis of accuracy vs. cost trade-offs. Shows empirical design variants with different iteration limits and their impact on accuracy and cost.
- **[source-99c3a574b01b]** [Optimal Stopping vs Best-Of-N for Inference Time Optimization](https://arxiv.org/html/2510.01394v1) - not-tiered
  - Adaptive stopping vs. fixed Best-of-N: Fixed generations waste compute when acceptable output found early or prompt is easy. Proposes optimal stopping approach for adaptive inference-time optimization.
- **[source-da0c13c56c7e]** [BudgetThinker: Empowering Budget-aware LLM Reasoning with Control Tokens](https://arxiv.org/html/2508.17196) - not-tiered
  - Budget-aware LLM reasoning with control tokens. Proposes dynamic insertion strategy and two-stage training to enforce target output length and teach model budget adherence vs. fixed budget caps.
- **[source-89cc2ee70142]** [Beyond Static Retrieval: Opportunities and Pitfalls of Iterative Retrieval in GraphRAG](https://arxiv.org/html/2509.25530) - not-tiered
  - Analysis of opportunities and pitfalls of iterative retrieval in GraphRAG. Examines benefits in coverage/hallucination reduction but identifies when multiple rounds don't improve outcomes.
- **[source-08ebbfd3d49e]** [Beyond Single Pass: KG-IRAG with Iterative Knowledge Retrieval for Temporal QA](https://arxiv.org/html/2503.14234) - not-tiered
  - KG-iRAG: iterative knowledge retrieval with temporal consistency verification. Consistently improves accuracy and calibration over strong baselines while reducing latency.
- **[source-217c18465a91]** [How Far Are We from Genuinely Useful Deep Research Agents? - OPPO AI Agent Team](https://arxiv.org/pdf/2512.01948) - not-tiered
  - Failure analysis of deep research agents: Insufficient External Information Acquisition (IIA)—agents fail to proactively gather necessary information, producing incomplete coverage outputs lacking empirical grounding.
- **[source-4ac693c804ad]** [OpenAI Deep Research: Honest Analysis and Real Limitations in 2025](https://futuresearch.ai/oaidr-feb-2025/) - not-tiered
  - OpenAI Deep Research limitations: Incomplete research is hard to detect automatically. Demonstrates the challenge of recognizing missing data without explicit coverage criteria.
- **[source-4eaf50ad9ddd]** [Step-DeepResearch Technical Report](https://arxiv.org/html/2512.20491v1) - not-tiered
  - ReAct-based research depth is often insufficient in specialized scenarios, failing user needs. Contrasts with hardcoded workflow patterns that impose high system complexity.
- **[source-0a7064303cfe]** [Why Your Deep Research Agent Fails? On Hallucination Evaluation in Full Research Trajectory](https://arxiv.org/html/2601.22984v1) - not-tiered
  - Trajectory-level hallucination analysis: End-to-end evaluation obscures intermediate failures like flawed planning that accumulate through research. Requires trajectory diagnostics.
- **[source-47166651eca6]** [What If We Allocate Test-Time Compute Adaptively?](https://arxiv.org/html/2602.01070) - tier 2
  - Adaptive test-time compute outperforms fixed allocation: Uncertainty or intermediate signals guide stopping dynamically. Adaptive schemes achieve 4x compute reduction vs. best-of-N with better performance.
- **[source-f2dc1ba91a6a]** [Adaptive Test-Time Compute Allocation for Reasoning LLMs via Constrained Policy Optimization](https://arxiv.org/html/2604.14853) - not-tiered
  - AdaCompute-GBM: Constrained policy optimization for dynamic reasoning depth and search breadth. Consistently outperforms all baselines, e.g. +1.9pp on GSM8K (94.6% baseline), with strict budget control.
- **[source-46ee1e2164fb]** [Hunt Globally: Deep Research AI Agents for Drug Asset Scouting](https://arxiv.org/html/2602.15019v1) - not-tiered
  - Diminishing returns in iterative retrieval: Simply iterating to find more assets is insufficient once obvious sources exhausted; sequential loop revisits similar evidence. Scaffold architecture drives completeness, not prolonged execution.
- **[source-f57c39fd2575]** [DeepSearchQA: Bridging the Comprehensiveness Gap for Deep Research](https://storage.googleapis.com/deepmind-media/DeepSearchQA/DeepSearchQA_benchmark_paper.pdf) - not-tiered
  - DeepSearchQA benchmark: Addresses completeness gap with set-based evaluation penalizing both under-retrieval and hedging. Agents must develop dynamic stopping criteria to determine when retrieved set is exhaustive.
- **[source-ac1bd4956168]** [Evaluating Deep Research Performance in the Wild with the DRACO Benchmark - Perplexity AI](https://research.perplexity.ai/articles/evaluating-deep-research-performance-in-the-wild-with-the-draco-benchmark) - not-tiered
  - DRACO benchmark: Evaluates deep research performance on real-world research tasks (not synthetic academic puzzles). Fully open source with complete rubrics for assessment.
- **[source-c3990c2ffb83]** [Beyond Task Completion: An Assessment Framework for Evaluating Agentic AI Systems](https://arxiv.org/html/2512.12791v1) - not-tiered
  - Tool orchestration failure analysis and memory precision-recall gaps in multi-agent systems. Motivation for adaptive evaluation strategies that select assessment depth based on risk levels.
- **[source-00c9e6708884]** [ReportBench: Evaluating Deep Research Agents via Academic Survey Tasks](https://arxiv.org/html/2508.15804v1) - not-tiered
  - ReportBench: Evaluates deep research agents on report synthesis via academic survey tasks. Commercial agents (OpenAI, Google) outperform standalone LLMs but room for improvement in breadth and consistency.
- **[source-7e3480ff5c53]** [Evaluation and Benchmarking of LLM Agents: A Survey](https://arxiv.org/html/2507.21504v1) - not-tiered
  - Survey on LLM agent evaluation: Advocates for automated evaluation, synthetic data generation, and LLM-as-judge. Emphasizes time- and cost-bounded evaluation protocols for iterative development.
- **[source-8416cc9c63de]** [Managing Uncertainty in LLM-based Multi-Agent System Operation](https://arxiv.org/html/2602.23005v1) - not-tiered
  - Managing uncertainty in multi-agent systems through completeness constraints, cross-source inconsistency detection, and calibrated confidence estimates.
- **[source-863a47e678f2]** [Can LLMs Express Their Uncertainty? Empirical Evaluation of Confidence Elicitation](https://arxiv.org/html/2306.13063v2) - not-tiered
  - Framework for LLM uncertainty: prompting strategies for verbalized confidence, sampling methods for multiple responses, aggregation for consistency. Empirical evaluation of three components.
- **[source-33bfde3a749e]** [Confidence Before Answering: A Paradigm Shift for Efficient LLM Uncertainty Estimation](https://arxiv.org/html/2603.05881) - not-tiered
  - Confidence before answering: sampling-based proxy for uncertainty; semantic entropy captures linguistic variation. Efficiency gains with localized uncertainty capture.
- **[source-fcc0b407efd3]** [AEMA: Verifiable Evaluation Framework for Trustworthy and Controlled Agentic LLM Systems](https://arxiv.org/html/2601.11903) - not-tiered
  - Process-aware, auditable framework for multi-agent evaluation. Plans, executes, and aggregates multi-step evaluations across heterogeneous workflows under human oversight in high-stakes domains.

