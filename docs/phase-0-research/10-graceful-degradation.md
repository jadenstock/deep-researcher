# Q10: What does graceful degradation look like when an agent or tool fails mid-research?

## What the research says

The corpus documents failure modes well but prescribes degradation patterns loosely. The relevant sources:

### Documented failure modes

1. **Tool failures:** rate limits, API timeouts, malformed responses, quota exhaustion. Multiple vendor/engineering sources (Microsoft Azure, AWS evaluating agents, Anthropic context engineering) note these as "always eventual" — you will hit them in production.
2. **Single-point-of-failure in orchestrator patterns** (Microsoft Azure): the central coordinator going down kills the whole workflow. Explicitly called out.
3. **Cascading failures in sequential pipelines** (Microsoft Azure): early-stage errors corrupt downstream. Common in tightly coupled pipelines.
4. **Infinite-loop failure modes** (Microsoft Azure + LiteResearcher): handoff loops, repetitive search queries, unbounded debate.
5. **Context exhaustion** (LiteResearcher): context window fills mid-task; generator loses coherence.

### Documented mitigations

- **Iteration caps with fallback behavior** (Microsoft Azure): when a loop hits its cap, either return the best current result with a quality warning *or* escalate to a human. The fallback path is mandatory — you don't just crash.
- **Peer-to-peer resilience** (Architectural Frameworks — single-source): no central coordinator means single-node failure doesn't halt the investigation. Trades resilience for coordination overhead.
- **Checkpoint-based retry** (LangChain docs): fail → fork from the last good checkpoint → retry with different parameters.
- **Verifier-convergence termination** (Marco DeepResearch): if verification fails, re-rollout from verification failure — not from scratch.

### What the corpus does NOT document

- **Explicit degradation policies** — what partial output looks like when a sub-agent fails permanently.
- **Tool-circuit-breaker patterns** — though borrowed directly from microservices, no corpus source describes them for agent systems.
- **Confidence-weighted degradation** — how the report should communicate that some sections are lower-confidence because of infrastructure failures, not evidence thinness.

## Design implication for an API-based system

**Degrade loudly and structurally, never silently.** Every failure class produces a specific, labeled output — the report itself reflects the failure.

### Failure → response matrix

| Failure class | Response | User-facing signal |
|---|---|---|
| **Tool rate limit** | Backoff + retry up to N times; on exhaustion, mark sub-questions that depended on this tool as "retrieval-limited" | Report notes "retrieval was rate-limited; results may be incomplete" for affected sub-questions |
| **Single tool down (e.g., a specific API)** | Route to fallback tool if available; otherwise continue with other tools | Report notes which intended sources were unavailable |
| **Sub-agent LLM call fails (transient)** | Retry with backoff; if transient error (timeout, 5xx), re-run | Invisible on success; logged |
| **Sub-agent LLM call fails (persistent)** | Mark that sub-question as "unanswered-system-error"; continue with other sub-questions | Report includes "we could not answer: [sub-question]" section |
| **Verifier fails** | Use verifier's last-known-good state; if no prior state, emit the claim with reduced confidence and flag "unverified due to verification failure" | Confidence on affected claims is explicitly lowered |
| **Context exhaustion mid-sub-question** | Compact via observation masking; if still over, hand off to a sub-agent with fresh context | Invisible on success; flagged if incomplete |
| **Orchestrator failure** | Write last checkpoint; surface partial results from completed sub-questions; refuse to fabricate the rest | Report is explicitly partial; sub-questions list status |
| **Global budget exhaustion** | Synthesize from what's gathered; flag "budget-limited" on unconverged sub-questions | Report includes "reached compute budget; some sub-questions not fully explored" |

### Design principles

1. **Sub-questions are the unit of degradation.** A single failed sub-question doesn't kill the report; the report produces a partial answer with explicit gaps. The PQR framework's separation of axes supports this — a sub-question that failed gets low R (no sources could be gathered) but doesn't torpedo the overall structure.

2. **No silent failures, ever.** Every degradation path must produce an explicit marker in the final output. A confident-looking paragraph that was actually synthesized from zero evidence because tools failed is worse than an explicit "we couldn't investigate this."

3. **Checkpoint before every risky operation.** Tool calls, expensive LLM calls, state writes — always checkpointed. Retry-from-checkpoint is dramatically cheaper than retry-from-scratch.

4. **Circuit-breaker the noisy dependencies.** Track per-tool error rates over a rolling window. When a tool hits a threshold, stop calling it for the rest of the session and annotate sub-questions that would have used it.

5. **Surface partial completeness as a first-class report field.** Something like `completeness: {sub_q_1: full, sub_q_2: budget_limited, sub_q_3: system_error}` — not buried in a footnote.

## Key failure mode the design guards against

**Fabricated recovery.** A subtle pathology: when a sub-agent fails, the orchestrator asks another sub-agent to cover, which works but then hallucinates rather than admitting the gap. Mitigation: when a sub-question is marked as failed and handed off, the replacement agent must receive a "fill minimum viable answer, explicitly flag uncertainty" prompt — not a general "answer this" prompt.

## Residual uncertainty

- Exact thresholds for circuit-breaker trip rates. Empirical per tool.
- Whether to retry with a different model on persistent LLM failure (model diversity as a resilience lever). Sensible but undocumented.
- User-facing UX for partial reports — the corpus is silent; probably out of scope for the MVP but worth a sentence in the design doc.

## Anchor sources

- Microsoft Azure Orchestration Patterns (iteration caps, fallback behaviors, single-point-of-failure warnings)
- Architectural Frameworks report (P2P resilience; single-source)
- LangChain Persistence + Time-Travel (checkpoint-based retry)
- Marco DeepResearch (re-rollout on verification failure; T_max fallback synthesis)
- AWS — Evaluating AI Agents (production lessons, error instrumentation)
- LiteResearcher (context-exhaustion failure evidence)
