# Q6: Not all work is equally hard. What does that imply?

## What the research says

The corpus supports this strongly but implicitly. Three threads converge:

### Thread 1: test-time compute scaling is per-question

- **"Let's Verify Step by Step"** (OpenAI) and the **PRM Survey** establish that harder questions benefit from more search/verification compute. Process reward models are explicitly a mechanism for directing more compute at harder steps.
- **MPBench** evaluates process-error identification — implicitly assumes that catching a specific error type deserves specific compute allocation.
- **Marco DeepResearch** uses Verifier-Guided Test-time Scaling: easy questions terminate fast on Joint-Verify; hard ones exhaust the T_max=600 tool-call budget.

### Thread 2: orchestration patterns imply cost-per-subtask variance

- **Microsoft Azure Orchestration Patterns** documents the *concurrent* pattern (parallel fan-out) as the natural fit for decomposable sub-questions of varying difficulty. Easy sub-questions return fast; hard ones keep running.
- **xbench-DeepSearch** explicitly measures per-task Cost and Time — these vary by task even within a single benchmark.

### Thread 3: context budget varies by sub-question

- **LiteResearcher** documents 4B-agent exhaustion at ~20 browsed pages on a 128K context. But a simple lookup (Test Case 1-style) may need 2 pages; a sparse-emerging topic (Test Case 3) may need all 128K and still be evidence-thin.
- **Anthropic** frames this as "attention budget is finite" — implicitly per-question.

### What the corpus does NOT document

**No formal algorithm for allocating compute per sub-question.** No "difficulty estimator" is described. Budgets are either global (T_max) or LLM-judged ("search until I feel done"). This is a real design gap.

## Design implication for an API-based system

**Allocate compute per sub-question, not per query.** Make difficulty an explicit first-class property.

### Concrete mechanism

1. **At intake**, the decomposition step assigns each sub-question a **complexity class**:
   - `lookup` — single retrieval suffices (Test Case 1-style).
   - `synthesis` — multiple sources need reconciling, no genuine conflict expected.
   - `contested` — literature disagrees (Test Case 2-style); needs multi-perspective + explicit conflict surfacing.
   - `sparse` — evidence is thin or emerging (Test Case 3-style); needs broader search + explicit uncertainty.

2. **Each class gets different default budgets:**
   - `lookup`: 1-3 tool calls, no verifier.
   - `synthesis`: 5-15 tool calls, lightweight verifier (claim-faithfulness check).
   - `contested`: 15-40 tool calls, multi-perspective query expansion, independent verifier agent, explicit conflict section in output.
   - `sparse`: 30-80 tool calls, broader query diversity, explicit evidence-thinness flag in output.

3. **Budgets are elastic.** If a sub-question classified as `lookup` fails to terminate cheaply, it gets reclassified and reallocated — not killed. Classification was the cheap guess; real execution overrides it.

4. **Parallelism is per-class.** `lookup` sub-questions run concurrently; `contested` ones run sequentially so the verifier isn't swamped and the conflict resolution has breathing room.

### What this buys you

- The system doesn't spend contested-question compute on lookups. Direct cost savings.
- The output honestly reflects difficulty: a `sparse` sub-question's answer includes "the evidence is thin" as a first-class field, not as an afterthought.
- The evaluation story is better: per-class pass rates expose where the system is weak, rather than a single aggregate score that hides variance.

### Anti-pattern this design avoids

**Uniform budgets.** Giving every sub-question the same tool-call budget means simple questions burn tokens unnecessarily and hard questions terminate prematurely. The corpus universally supports variable allocation in principle; no source prescribes the mechanism.

## Key failure mode to instrument against

**Difficulty-class misclassification at intake.** If the decomposer calls something `lookup` that's actually `contested`, the output will look confident and shallow. Mitigation: the verifier catches this — if the first retrieval reveals conflicting sources, the class upgrades and more compute flows in.

## Residual uncertainty

- The class taxonomy above is hypothesis, not evidence-derived. The four assessment test cases suggest it; the corpus doesn't validate it. Empirical calibration required.
- Whether difficulty should be estimated by a separate model call or derived from the LLM's own perplexity / confidence signals — no corpus guidance.

## Anchor sources

- Marco DeepResearch (Verifier-Guided Test-time Scaling, per-question termination)
- PRM Survey + Let's Verify Step by Step (compute-at-harder-steps principle)
- xbench-DeepSearch (per-task cost/time metrics)
- LiteResearcher (context-budget-per-question evidence)
- Anthropic — Effective Context Engineering (attention-budget framing)
