# Q4: When does adding another agent help vs. hurt?

## What the research says

This is the most genuinely contested question in the corpus. Reputable sources land in opposite places.

### Pro single-agent positions

- **Microsoft Azure Orchestration Patterns** (Tier 3, vendor-architectural): *"Default to a single agent with tools unless strict security boundaries or tool overload necessitate multiple agents."* The rationale: multi-agent coordination adds latency, token cost, and cascading-failure surfaces.
- **SFR-DeepResearch** (Tier 2, arXiv): empirically argues single-agent RL-trained systems generalize better to unseen tasks than multi-agent pipelines, which "over-specialize in rigid heuristic workflows."
- **LiteResearcher** (Tier 2, arXiv): documents single-agent context exhaustion but treats this as a failure to be engineered around (via sub-agent isolation), not a reason to shard into peer agents.

### Pro multi-agent positions

- **Marco DeepResearch** (Tier 2, arXiv): verification-driven design requires a **separate** verifier agent with independent tool access. Same-agent self-verification is empirically insufficient.
- **GPT Researcher** (Tier 3, documented): uses a hierarchical Chief Editor + specialist researchers + writer pattern. Claim: role specialization + adversarial review improves factuality.
- **MARS / MARSHAL** (Tier 2, arXiv): empirical evidence that multi-agent self-play generalizes to zero-shot reasoning improvements. Not directly applicable to API-only deployment but establishes that multi-agent dynamics can enhance rather than constrain reasoning.
- **Towards Scientific Intelligence** (Tier 2): documents "constructive tension" — multiple agents assigned distinct evaluation perspectives resolve conflicts that single-agent self-critique cannot.

### The actual frontier of disagreement

Both sides agree single-agent-with-tools suffices for *simple* research. Both sides agree long-horizon research needs context isolation. The disagreement is **what to do with the isolated context**:

- **Single-agent camp:** spawn ephemeral sub-agents whose only job is to return distilled summaries. They're not "agents" in a collaboration sense — they're stateless context-isolation workers. The system is still a single agent conceptually.
- **Multi-agent camp:** give separate agents persistent roles (researcher, critic, writer) with different prompts, different tools, and independent authority to push back. This is where you get debate, maker-checker loops, and verifier convergence.

Framed this way, the question isn't "one or many agents" — it's **"do you need an independent verification perspective, or just cleaner context for the generator?"**

## Design implication for an API-based system

**Add another agent when you need an independent perspective. Don't add one for context cleanliness alone.**

Concrete rules:

1. **Context cleanliness** → spawn stateless sub-agents. Single "conceptual agent" model. (Anthropic pattern.)
2. **Verification on load-bearing claims** → dedicated verifier agent with independent tool access, different prompt framing, ideally different temperature or model. (Marco DeepResearch pattern.)
3. **Adversarial stress-testing on contested claims** → separate critic agent whose explicit prompt is to find counter-evidence. (STORM / Towards Scientific Intelligence.)
4. **Never add an agent for "specialization"** unless the specialization comes with its own tools or evaluation criteria. "Research agent" + "writing agent" with the same tools and the same prompt is coordination overhead with no separation benefit.

### Heuristic for "does adding this agent help?"

Ask: **what evidence would this agent access, or what reasoning path would it take, that the current agent provably does not?** If the answer is "different phrasing of the same prompt," don't add it. If the answer is "independent tool access" or "adversarial framing" or "evaluation against different criteria," add it.

## Key failure mode to instrument against

**Agent-inflation bias.** It's tempting to add agents because the design feels more sophisticated. The O(N²) coordination cost is real; token bills compound; cascading failures multiply. Every added agent must earn its keep with a measurable quality delta on a held-out eval, not a plausible story.

## Residual uncertainty

- No source provides a quantitative threshold for "when does the verification benefit exceed the coordination overhead." This will be empirical for any specific deployment.
- The question of **which model to use per agent** (same model different temperature? different model family?) is not documented. Intuition says model diversity helps verification; evidence in this corpus doesn't directly support this.

## Anchor sources

- Microsoft Azure Orchestration Patterns (default single-agent)
- SFR-DeepResearch, LiteResearcher (generalization argument)
- Marco DeepResearch (verifier sub-agent with independent access)
- GPT Researcher (hierarchical orchestration pattern)
- MARS / MARSHAL (multi-agent generalization evidence)
- Towards Scientific Intelligence (constructive-tension / role-based verification)
