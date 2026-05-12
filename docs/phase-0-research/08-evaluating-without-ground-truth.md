# Q8: No ground truth exists for a research report. How do you know yours is good?

## What the research says

The corpus documents a clear evolution from outcome-only evaluation to **orthogonal quality dimensions scored independently**. Four benchmarks span the space:

### The four benchmark families

| Benchmark | Measures | Key metric | Limitation |
|-----------|----------|------------|------------|
| **GAIA** | End-to-end task correctness | Final-answer pass@1 | Static; obscures process failures; rewards lucky guesses |
| **xbench-DeepSearch** | Plan → search → reason → summarize pipeline | Task completion + cost/time | Black-box output scoring; Chinese-centric |
| **CRYSTAL** | Step-level reasoning fidelity | Match F1, Ordered Match F1 | Multimodal-focused; incomplete reference paths |
| **Personalized Deep Research (PDR-Bench)** | User-aligned research output | PQR framework: **P**ersonalization + **Q**uality + **R**eliability | Chinese-only; compute-limited to 150/250 queries |

### The PQR framework (PDR-Bench) is the most transferable

PDR-Bench decomposes "is this report good?" into three orthogonal axes, each scored independently by an LLM judge with dynamically allocated weights:

- **P (Personalization Alignment):** Goal Alignment, Content Alignment, Presentation Fit, Actionability.
- **Q (Content Quality):** Depth & Insight, Logical Coherence, Clarity & Readability.
- **R (Factual Reliability):** Factual Accuracy (automated verification against retrieved source content), Citation Coverage.

The structural insight is that these axes **can't be summed into one number meaningfully**. A report with perfect R (every claim traceable) but poor Q (incoherent) is bad. A report with strong Q but poor R is dangerous. They have to be tracked separately.

### What the corpus explicitly notes as unsolved

- Standardizing evaluation across research domains ("biomedical vs. materials science") — no unified methodology.
- Cost-efficiency trade-offs across process-oriented benchmarks — not quantified.
- Evaluation without any kind of reference (not even user-provided criteria) — PDR-Bench assumes user profiles; CRYSTAL assumes reference reasoning steps.

### Documented LLM-judge pathologies (from the related corpus)

- **Agreeableness bias:** LLM judges tend to validate rather than critique. Binary rails miss errors.
- **Self-preference:** LLM judges rate their own family's outputs higher.
- **Calibration via small expert-labeled sets** (5-50 samples) can adjust judge rails but breaks at capability frontiers.

## Design implication for an API-based system

**Evaluate on three orthogonal axes. Never produce a single aggregate score.**

### Proposed evaluation framework for the MVP

1. **Faithfulness (claim-level, mechanical):**
   - For every claim in the report, the system has attached a quote + source.
   - A small-model check: "does this quote semantically support this claim?" Returns supported / contradicted / unclear.
   - Score: % of claims mechanically supported.
   - **This is the one metric you can fully automate without human labels.** It directly tests citation-without-reading.

2. **Coverage (report-level, vs. intake plan):**
   - Intake produced a sub-question decomposition.
   - For each sub-question, is there at least one non-trivial claim addressing it?
   - Score: % of sub-questions with claim coverage above a length/content threshold.

3. **Source-agreement / conflict surfacing (report-level):**
   - For each load-bearing claim, count supporting and contradicting sources.
   - Does the report surface conflicts when they exist, or silently pick a side?
   - Score: % of claims where conflict (if present in retrieved evidence) is acknowledged in the report text.

4. **Confidence calibration (report-level, slower):**
   - On held-out test cases with known answers (even if narrow), does stated confidence correlate with correctness?
   - Expected Calibration Error (ECE) if you can get discrete bins.

5. **Human spot-check (always-on, expensive):**
   - On a small sample, a human labels: is this report useful? Is it honest about gaps?
   - You cannot automate this out. PDR-Bench's use of an LLM judge is a stand-in; an LLM judge is a production monitoring signal, not a replacement for eyes.

### Why this design works for the take-home

The assessment says: *"Final output must separate claims from evidence and indicate confidence and source agreement."* This is exactly axes 1 + 3. The structure of your claim output and the structure of your evaluation are the same thing — you evaluate what the report itself exposes.

### The comparison / ablation hook

The assessment requires at least one comparison or ablation. Good options grounded in this research:
- **With vs. without independent verifier agent** (Marco DeepResearch-inspired): measure faithfulness axis.
- **Observation masking vs. summarization** for context management (Anthropic vs. naive baseline): measure coverage on long-horizon test cases.
- **Multi-perspective query generation vs. single-prompt queries** (STORM-inspired): measure source-agreement/conflict-surfacing axis on contradictory-source prompts (Test Case 2).

## Key failure mode to instrument against

**LLM-judge agreeableness.** If you use an LLM to score faithfulness, it will lean toward "supported." Calibrate the judge on a small set of human-labeled supported/contradicted/unclear examples. Report the judge's TPR and TNR separately, not aggregate accuracy.

## Residual uncertainty

- Whether automated faithfulness evaluation (judge scoring quote vs. claim) correlates with human judgment in this specific domain. Untested in corpus; needs calibration with a small labeled set.
- Whether coverage can be meaningfully measured when the decomposition itself might be wrong. A bad decomposition → 100% coverage of the wrong things. Needs a secondary check on decomposition quality.

## Anchor sources

- PDR-Bench (PQR framework, orthogonal axes)
- CRYSTAL (process-level step fidelity)
- GAIA + xbench-DeepSearch (final-answer paradigms and their documented limits)
- AWS — Evaluating AI Agents (production lessons on agent evaluation)
- Marco DeepResearch (faithfulness as verification signal)
