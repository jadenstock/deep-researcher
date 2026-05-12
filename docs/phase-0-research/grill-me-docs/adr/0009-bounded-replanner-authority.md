# ADR 0009 — Bounded replanner authority: termination is not a replanner prerogative, mutations are budgeted, cascades have concrete semantics

**Status:** Accepted
**Date:** 2026-05-07
**Context in:** `tdd-v3.md` §5.10 (replanner), §5.12 (stopping + completion gates), ADRs 0001, 0005, 0006

---

## Context

Across ADRs 0001, 0005, and 0006, the replanner accumulated authority: add/edit/abandon tasks, merge and split sub-questions, detect and add typed dependencies, detect scope creep, raise user escalations. TDD v3 §5.12 additionally wired the stopping signal to "task graph exhausted AND replanner emits no new tasks" — which makes "replanner decided nothing more needs doing" equivalent to "the run terminates."

That's a large concentration of power in one LLM-judgment role. Three specific failure modes that are currently silent:

1. **Premature termination by replanner silence.** A same-family replanner making the "stop" decision and a same-family `VALIDATE_COMPLETION` judgment gate rubber-stamping it produces silent under-research, even with ADR 0008's routing (the replanner is still a generative-family role).
2. **Graph churn from unbounded mutations.** Nothing limits how many mutations a replanner can emit per cycle. A replanner that finds something to restructure every cycle destabilizes research.
3. **Undefined cascading semantics.** ADR 0006 explicitly flagged this — if the replanner mutates a parent sub-question, what happens to in-progress tasks on it?

## Decision

Three bounded authorities on the replanner.

### (a) Termination is separated from replanner silence

A new deterministic task type — `CHECK_TERMINATION_READY` — runs *after* a replan cycle in which the replanner emitted no mutations. Its checks (no LLM calls):

- No `PENDING` tasks remain.
- Every sub-question has status `SYNTHESIZED`.
- Scope-creep has not been escalated with user choosing "broaden" (which would contradict terminating).
- Every **contested** sub-question has at least one completed disconfirmation task (`ADVERSARIAL_CRITIQUE`, `debate`, or `ach`). Structural check: the task graph contains such a task in DONE status linked to the sub-question.

Only if all checks pass does `VALIDATE_COMPLETION` run. If any fail, the scheduler emits targeted remediation tasks (e.g., spawn an `ADVERSARIAL_CRITIQUE` on the contested sub-question that lacks one) and the run continues.

This creates an inspectable, deterministic gate between replanner silence and report writing.

### (b) Replanner mutation budget is configurable

Per-replan-cycle cap on mutations: `replanner_mutation_budget` (config, default ≈ 3).

- If the replanner wants to emit more, it emits the highest-priority `replanner_mutation_budget` mutations and records the rest in the cycle's `decision_note` under "deferred to next cycle."
- Cadence itself is configurable: `replanner_cadence` (config, default ≈ every 10 completions). Expected to tune empirically per deployment; Jaden wants to measure.

### (c) Cascading mutation semantics are specified

When the replanner mutates a sub-question with in-progress tasks:

- **Merge sub-questions A + B → AB.** Tasks on A and B complete and write into AB's `question_note`. No abort. Redundant analysis is tolerated; it enriches AB.
- **Split sub-question A → A1 + A2.** Tasks pause (new task status `BLOCKED_ON_SPLIT`). Replanner specifies branch assignment per task; for ambiguous assignments, the `decision_note` records rationale. Tasks resume targeting their assigned branch.
- **Abandon sub-question A.** In-progress tasks on A complete but outputs go to a `decision_note` archive (`abandoned_sub_question_archive`) — not to a live `question_note`. Preserves audit trail; no wasted compute.
- **Add dependency edge upstream → downstream.** In-progress synthesis on `downstream` completes (no abort). Any subsequent synthesis-phase task on `downstream` blocks on `upstream`'s synthesis. A fresh synthesis on `downstream` spawns after `upstream` resolves.

Task schema gains a new status: `BLOCKED_ON_SPLIT`.

## Alternatives Considered

### (A) No bounds; trust the replanner.
Rejected. The three failure modes are real. Termination-by-silence is particularly dangerous because it's invisible.

### (B) (a) only — termination check, no mutation bound, no cascade specs.
Partially accepted; (a) is the most load-bearing. But (b) and (c) are cheap additions that protect against the remaining failure modes.

### (C) User-facing termination confirmation instead of deterministic check.
Considered. Rejected because at lower interactivity levels (L0, L3 with timeout) it collapses to auto-approve, which is exactly the failure mode (a) is designed to prevent. A deterministic structural check doesn't depend on user responsiveness.

### (D) Hard mutation cap (non-configurable).
Rejected. Cadence and budget are empirical. Different topics behave differently. Jaden explicitly wants these as config parameters to tune.

## Consequences

### Positive

- Premature termination now requires the task graph to *structurally* look done, not just the replanner's judgment to say so. Big guardrail against same-family bias.
- Graph churn is bounded. Replan cycles have predictable cost.
- Cascading semantics are specified — implementation can handle mutations deterministically without edge-case bugs.
- Configurable cadence and budget support the ablation philosophy: we can sweep these as parameters in experiments.

### Negative

- Extra task type (`CHECK_TERMINATION_READY`) and status (`BLOCKED_ON_SPLIT`). Minor schema growth.
- Contested-sub-question disconfirmation check in (a) requires the task-graph audit to know which sub-questions are classified `contested`. That's already on the `question_note` metadata; just need to read it.
- Remediation from the termination check could re-loop indefinitely if something is structurally unfixable. Mitigated by the existing `VALIDATE_COMPLETION` remediation cap (max 2 cycles) carrying over. If the termination check fails the same way twice, it escalates.

### Neutral

- This ADR converts previously implicit, informally-specified replanner behavior into explicit configurable mechanisms. No new power added; existing power bounded.

## Open Questions

- **Default values for `replanner_mutation_budget` and `replanner_cadence`.** 3 and 10 are guesses. Jaden plans to measure.
- **Priority ordering of deferred mutations** when the replanner emits more than the budget. Needs a concrete rule — probably "mutations that unblock other tasks first, mutations that abandon stalled work second, cosmetic merges last." Defer to implementation.
- **Split-task branch assignment.** When tasks are mid-flight on a sub-question being split and their branch isn't obvious, the replanner has to emit a decision. Could get it wrong. Audit via decision_notes; no programmatic fix for MVP.

## References

- ADR 0005 — scope-creep detection (replanner responsibility).
- ADR 0006 — typed dependencies + runtime detection (replanner responsibility), explicitly flagged cascading semantics as open.
- ADR 0008 — role-to-model routing; partially but not fully addresses same-model bias at the termination juncture.
- Grilling session transcript — 2026-05-07.
