# Q7: When do you stop searching?

## What the research says

The corpus documents four stopping mechanisms, ranked by rigor:

### 1. Subjective agent determination (weakest)

The default. The LLM outputs a terminal token (`<answer>`, `</search>`) when it feels it has enough. Used by base ReAct and by Search-R1's prompting setup. **Failure mode:** premature convergence — "agents accept the first plausible answer and terminate exploration" (Marco DeepResearch, direct quote).

### 2. Hard budget (universal fallback)

Max tool calls, max turns. Every system documented in the corpus has this as an outermost safety net.
- Search-R1: max action budget.
- One Model, All Roles: max turns.
- Marco DeepResearch: T_max = 600 tool calls.
- Microsoft Azure: "iteration caps" with fallback behavior on hit.

Budgets are necessary but insufficient — they prevent runaway cost but do not determine quality. A system that always hits budget gives no signal about when it should have stopped.

### 3. Stop-hook / Ralph Loop (behavioral)

Single-source (Architectural Frameworks report): if the agent attempts to terminate before explicit completeness criteria are satisfied, the system intercepts and re-injects the original prompt, forcing continuation. This inverts the default — the system assumes the agent wants to stop prematurely and pushes back by construction.

### 4. Verifier-convergence (strongest, principled)

Marco DeepResearch's **Joint-Verify**: terminate only when multiple independently generated candidate answers all pass verification. The stopping criterion isn't the generator's judgment — it's an external convergence signal.

This is the most principled mechanism in the corpus for open-ended research. Its cost is running multiple generation traces to convergence.

### What the corpus does NOT document

- **Information-theoretic stopping** — no entropy-reduction thresholds, no information-gain calculations, no formal confidence-interval-based halting. Synthesis explicitly flags this as missing.
- **Cost-weighted stopping** — no source prescribes "stop when expected marginal information gain < marginal token cost." Obvious in principle; undocumented in practice.
- **Sub-question-level vs. query-level stopping** — sources treat the whole research query as one termination decision. But different sub-questions terminate at different points, and this is not documented.

## Design implication for an API-based system

**Stopping should be compositional: per-sub-question, not global.** The decision to stop is per-sub-question, driven by:

1. **Coverage check:** have all declared sub-questions been answered at least once?
2. **Sufficiency check (per sub-question):** does the current evidence meet the sub-question's success criteria (which were declared at intake)?
3. **Convergence check (per sub-question):** if the sub-question is classified as `contested` or `sparse`, did verification converge? For `lookup` and `synthesis`, is one verified claim enough?
4. **Marginal gain estimate:** has the last N tool calls produced novel claims? If not, additional calls are unlikely to help — stop that sub-question early.
5. **Global budget:** the outermost guard. If hit, synthesize from what's available with an explicit "budget-limited" flag in the report.

Criteria 1-3 are load-bearing. Criterion 4 is a heuristic (novelty decay) that catches repetitive-action-loop failures (LiteResearcher) cheaply. Criterion 5 is the safety net.

### Concrete mechanism

```
for each sub_question:
  while not done:
    if budget_exhausted_global or budget_exhausted_local: 
      done = True; flag_as_budget_limited
    elif novelty_decay(last_N_calls) < threshold:
      done = True; flag_as_saturated
    elif success_criteria_met(evidence) and (class in {lookup, synthesis} or verifier_converged):
      done = True; flag_as_satisfied
    else:
      execute_next_action()
```

### Exposing stop-reason in the report

Every sub-question's answer carries its stop-reason: `satisfied` / `saturated` / `budget_limited` / `no_evidence_found`. This makes the output honestly self-diagnostic. A `budget_limited` on a `contested` sub-question is a legitimate "we didn't converge" signal — far more useful than confident-looking output from a run that would have flipped its answer with 10 more tool calls.

## Key failure mode to instrument against

**Novelty-decay false positives.** The agent may issue queries that *look* redundant but are actually probing from different angles. Mitigation: compute novelty on *retrieved claim content*, not on query text. If new claims stop appearing, you've saturated; if queries look similar but claims are new, keep going.

## Residual uncertainty

- Calibration of the novelty-decay threshold. Needs empirical tuning on representative test cases.
- Whether verifier-convergence for `contested` sub-questions should require 2 or N agreeing candidates. Marco DeepResearch uses 2-candidate Joint-Verify; N=3 is probably safer but N×-cost.

## Anchor sources

- Marco DeepResearch (Joint-Verify convergence; T_max fallback; premature-convergence evidence)
- Search-R1 + One Model All Roles (hard budget patterns)
- Microsoft Azure Orchestration Patterns (iteration caps with fallback behavior)
- Architectural Frameworks report — Ralph Loop / Stop Hook (single-source)
- LiteResearcher (repetitive-loop failure that novelty-decay catches)
