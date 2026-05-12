# Q3: What should agents share, and what should they not?

## What the research says

Two competing philosophies are documented. Both have multi-source evidence.

### Share everything (blackboard / shared memory)

- **Blackboard architecture** (Microsoft Azure — single-source): a shared knowledge space where any agent can contribute refinements based on its expertise. Good for incremental problem-solving and parallel work where order isn't fixed.
- **LangGraph cross-thread persistence** (`BaseStore` + semantic search): explicit mechanism for cross-agent memory, queried semantically rather than pushed.
- **Failure modes:** race conditions, state corruption, quadratic coordination as agent count grows, semantic contradictions when two agents write overlapping state.

### Share nothing (sub-agent context isolation)

- **Anthropic "Effective Context Engineering" + Architectural Frameworks:** the central argument. Spawn sub-agents with fresh context windows for deep exploration. They return only distilled summaries. The lead agent never sees the sub-agent's scratch work.
- **Rationale:** preserves the lead agent's context cleanliness (no context rot), bounds blast radius of any sub-agent hallucination, enables cheap parallelism (isolated contexts can run concurrently with no coordination).
- **Failure modes:** summary loss (the sub-agent knows something load-bearing that doesn't make it into the summary), duplicate work across sub-agents, inability to cross-reference evidence across threads without explicit plumbing.

### What everyone agrees on

- **The research plan / sub-question decomposition** is shared — it's the contract.
- **Tool-use observations** (raw web pages, long API responses) should **not** propagate up. This is the observation-masking consensus (Anthropic, JetBrains) — pass the derived claim, not the 40KB page.
- **Evidence / citations** should be shared as structured objects (claim + source + quote + confidence), not as free text. The structure is what makes cross-agent verification possible.

## Design implication for an API-based system

**Share derived artifacts, not raw context.** Specifically:

- **Share:** structured claims with citations, the research plan, sub-question status, verification results, final synthesis drafts.
- **Don't share:** raw tool outputs, intermediate reasoning traces, failed search queries, the agent's private scratchpad.
- **Share on request, not by default:** the full evidence chain for a specific claim. If a downstream verifier agent wants the 40KB source page for a claim, it can request it — not pre-loaded.

This maps cleanly to a **typed message bus between agents**. Each message is a structured object with a declared schema (Pydantic / structured outputs). Raw observations stay in each agent's private checkpoint state.

### Concrete shared schema (sketch)

```
Claim {
  id, text, confidence,
  sub_question_id,
  supporting_evidence: [{source_id, quote, supports|refutes}],
  conflicts_with: [other_claim_ids]
}
Evidence {
  source_id, url, retrieved_at, quality_tier,
  excerpt, full_text_ref
}
SubQuestion {
  id, text, decomposer_intent,
  success_criteria, status, claims: [claim_ids]
}
```

The orchestrator-worker pattern then reads naturally: lead agent owns the plan + final synthesis; researcher sub-agents own evidence gathering per sub-question; verifier agents operate on the typed Claim objects, not raw reasoning.

## Key failure mode to instrument against

**Summary drift.** Sub-agent distills evidence → distilled summary hides a contradiction that existed in raw evidence → lead agent builds on the wrong conclusion. Mitigation: make the sub-agent emit structured claims *with attached quotes* rather than a free-text summary. The quote is the evidence that survives distillation.

## Residual uncertainty

- No corpus source tells you the right granularity for shared messages. Too coarse (paragraph summaries) and you lose the quotes that survive verification; too fine (per-tool-call) and the shared bus becomes as noisy as raw context.
- Timestamp / versioning of shared state — when claim A is revised, do all downstream claims that cited it get invalidated? LangGraph's checkpoint model says yes, but no source prescribes the cascade policy.

## Anchor sources

- Anthropic — Effective Context Engineering (sub-agent isolation)
- Architectural Frameworks report (sub-agent isolation + blackboard tradeoffs)
- Microsoft Azure Orchestration Patterns (blackboard + shared-state patterns)
- LangChain Persistence + BaseStore (cross-thread memory mechanism)
- JetBrains Cutting Through the Noise (masking over summarization — share less)
