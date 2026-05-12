# Phase 0 — Research

NotebookLM-grounded research on deep research agent system design, conducted for a take-home assessment. User is designing an API-based system (not training), so training-specific findings are retained as landscape context but de-emphasized in design guidance.

## Contents

**High-level synthesis**
- [`findings.md`](findings.md) — Research Findings Document. Full synthesis across the corpus: architectural patterns, memory/context, conflict handling, stopping criteria, evaluation landscape, failure modes, open questions, corpus gaps.

**Sub-docs: each explicit question from the assessment**

From *"Questions worth thinking about—regardless of track"*:
1. [`01-planning-as-commitment-or-suggestion.md`](01-planning-as-commitment-or-suggestion.md) — When should a plan be a commitment vs. a suggestion?
2. [`02-vague-to-concrete-intake.md`](02-vague-to-concrete-intake.md) — Vague question in, concrete research out. What happens in between?
3. [`03-what-agents-should-share.md`](03-what-agents-should-share.md) — What should agents share, and what should they not?
4. [`04-when-another-agent-helps.md`](04-when-another-agent-helps.md) — When does adding another agent help vs. hurt?
5. [`05-staying-honest.md`](05-staying-honest.md) — Dead ends, contradictions, hallucinations — how does the system stay honest? + How do you prevent convergence on a comfortable wrong answer?
6. [`06-work-difficulty-and-compute.md`](06-work-difficulty-and-compute.md) — Not all work is equally hard. What does that imply?
7. [`07-stopping-criteria.md`](07-stopping-criteria.md) — When do you stop searching?

From *"Research & Post-Training"* (API-relevant only):
8. [`08-evaluating-without-ground-truth.md`](08-evaluating-without-ground-truth.md) — No ground truth exists for a research report. How do you know yours is good?

From *"Engineering & Infrastructure"*:
9. [`09-debugging-multi-agent.md`](09-debugging-multi-agent.md) — How do you debug a multi-agent workflow when something goes wrong three steps ago?
10. [`10-graceful-degradation.md`](10-graceful-degradation.md) — What does graceful degradation look like when an agent or tool fails mid-research?
11. [`11-improving-without-retraining.md`](11-improving-without-retraining.md) — What would it take for the system to get better over time without retraining?

## How the sub-docs are structured

Each sub-doc has a consistent pattern:
- **What the research says** — evidence-grounded summary with source citations and tier signals.
- **Design implication for an API-based system** — concrete design positions, not research restatements.
- **Key failure mode to instrument against** — the specific thing this design decision can still go wrong on.
- **Residual uncertainty** — what the corpus doesn't cover, where calibration/empiricism is required.
- **Anchor sources** — the specific papers/docs that back the claims.

## Corpus

- **Notebook ID:** `55d508ac-a85e-4848-bf67-56cb8b34253a` (NotebookLM)
- **Final corpus size:** 43 Tier 1-3 sources (22 arXiv / peer-reviewed, 21 engineering blogs / standards / framework docs)
- **Key sources by topic:**
  - *Architecture:* Microsoft Azure Orchestration Patterns, Architectural Frameworks report, A Survey on LLM-based Autonomous Agents
  - *Memory:* Anthropic Effective Context Engineering, Look Back to Reason Forward, LangChain Persistence, JetBrains Cutting Through the Noise
  - *Orchestration with verification:* Marco DeepResearch, GPT Researcher, Towards Scientific Intelligence
  - *Deep research agents specifically:* SFR-DeepResearch, LiteResearcher, Marco DeepResearch, AutoResearch-RL, Open-source DeepResearch (HF)
  - *Evaluation:* GAIA, xbench-DeepSearch, CRYSTAL, Personalized Deep Research (PDR-Bench)
  - *RL / PRMs (landscape only):* Search-R1, SCoRe, MARS, MARSHAL, PRM Survey, Let's Verify Step by Step
  - *Tools / MCP:* MCP spec, Anthropic/GCP/Databricks MCP guides, structured outputs

## Caveats

- Some Q&A responses cite papers (ECON, Synchronous Faithfulness Monitoring) that don't appear in the final pruned corpus. These references likely persist in the bibliography of the inline synthesis report and should be primary-source-verified before citation in a final design doc. Flagged in `findings.md`.
- The "evidence" in this folder is corpus-grounded synthesis — it is not original experimental data. Design positions are defensible but not exhaustive, and residual uncertainty is called out in each doc.
