# ADR 0005 — Scope-creep detection operates at sub-question level, not raw task level

**Status:** Accepted
**Date:** 2026-05-07
**Context in:** `tdd-v3.md` §5.12 (stopping + completion gates), `phase-0-research/thoughts.md` Theme 4 (user's budget-rejection position)

---

## Context

The design commits to "no hard budgets — let it run if making progress" (user position from `phase-0-research/thoughts.md`). This makes scope-creep escalation the *only* mechanism preventing the system from running indefinitely. A wrong signal has two failure modes: false positive (stops mid-research with incomplete results) or false negative (loops forever, demo catastrophe).

TDD v3 §5.12 defined the signal at the raw task level: "over the last M completions, if new-task-creation-rate ≥ completion-rate for K consecutive replan cycles, escalate." This fails on several predictable cases:

1. **False positive on legitimate depth.** `multi_perspective` + ACH on a single contested sub-question spawns many tasks in a short window. At the raw-task level this is indistinguishable from scope creep. The system would escalate while working correctly.
2. **False positive on ACH fan-out.** Even after ADR 0004's batching reduces N×M to N tasks, an ACH invocation still bursts task creation. Same problem.
3. **False negative on replanner-driven breadth expansion.** If the replanner closes one sub-question while opening another, task rates balance and the signal never fires — but scope has materially grown.

The underlying issue: scope is a property of the sub-question space (breadth over time), not the raw task graph (which fluctuates with per-sub-question depth).

## Decision

Scope-creep detection operates at the **sub-question level**, not the raw-task level.

**Signal definition:**
- Maintain `open_sub_questions` = sub-questions whose `question_note` lacks a final synthesis.
- Per replan cycle, track `new_sub_questions_added` and `sub_questions_closed`.
- **Scope-creep fires** when, over K consecutive replan cycles (default K=2), `new_sub_questions_added > 0` AND `sub_questions_closed == 0`. Breadth is expanding, nothing finishing.

**Per-sub-question depth is explicitly not a scope-creep signal.** A sub-question spawning many internal tasks is legitimate work. If a single sub-question stalls (many tasks, no synthesis), a separate internal signal — sub-question exhaustion — nudges the replanner to review. This is internal; it does not escalate to the user.

**Structured escalation payload.** When scope-creep fires, the `SCOPE_ESCALATION` carries:
- The set of currently open sub-questions, grouped by research depth (well-researched / partially / barely started).
- A proposed narrow option: "stop adding new sub-questions; close out existing ones; report covers A, B, C; D and E surface as `open_question_notes`."
- A proposed broaden option: "continue; next N sub-questions the replanner is about to spawn are listed here."
- A default recommendation: narrow.

**Default fallback on non-response** (L0 or L3 timeout): narrow. Finish what's open, surface the rest as follow-ups in the Pyramid report.

## Alternatives Considered

### (A) Keep raw-task-rate tracking from TDD v3.
Rejected. Produces false positives on `multi_perspective` / ACH bursts and false negatives when breadth-expansion is replan-driven.

### (B) Hybrid: raw-task signal + sub-question signal.
Rejected. Either signal alone covers the bulk of real cases; combining them adds mental overhead without meaningful coverage gain. The sub-question signal is strictly better at capturing what "scope" actually means.

### (C) No scope-creep signal; rely entirely on user observability.
Rejected. That requires observability infrastructure we've explicitly deferred from MVP. Would also leave runs vulnerable to silent infinite loops if the user isn't watching.

### (D) Let the replanner itself decide when scope has crept and escalate directly.
Rejected as a sole mechanism but partially adopted. The replanner already raises `SCOPE_ESCALATION` when it detects unmanageable drift. The sub-question metric is the structural signal the replanner consults; the replanner still has authority to escalate on qualitative grounds.

## Consequences

### Positive

- Legitimate deep research on one contested sub-question (`multi_perspective` + ACH) is never confused with scope creep.
- Replan-driven breadth expansion is now visible and catchable.
- The escalation carries actionable choices (cut-list, extension-list, default), not abstract "keep going?" questions. Better UX for interactivity L3+.
- Default fallback is predictable — "narrow and list follow-ups" is the right conservative behavior when the user doesn't respond, and the user can anticipate it.

### Negative

- Sub-question-level counting requires tracking question-note status accurately. A subtle bug in "is this sub-question closed?" detection can make the signal fire wrong.
- Doesn't catch pathological per-sub-question behavior (one sub-question consuming all resources). Addressed by the separate sub-question-exhaustion internal signal, which is not a scope-creep escalation but a replanner nudge.
- The signal is still heuristic. K=2 is a guess; may need tuning.
- Scope-creep's default-narrow behavior produces shorter reports than a user running at L0 might want. If the user genuinely wants expansion, they need interactivity ≥ L1 to say so.

### Neutral

- This couples the scope-creep signal to the replanner's cadence (replan cycles). If replanner cadence changes (e.g., per ADR-0002's open question about adaptive cadence), the signal's sensitivity changes proportionally. Acceptable; documented here.

## Open Questions

- **K tuning.** K=2 may be too jumpy or too patient depending on topic. Empirical calibration needed.
- **Well-researched / partially / barely started categorization** in the escalation payload — needs concrete thresholds for the report.
- **User-facing UX for the structured escalation.** Not a design question at the level of this ADR, but an implementation concern when building the interactivity layer.

## References

- `phase-1-initial-design/05-tdd-v3.md` §5.12 — the raw-task-rate heuristic being replaced.
- `phase-0-research/thoughts.md` Theme 4 — budget-rejection position that made scope-creep load-bearing.
- ADR 0004 — ACH batching, which reduces but doesn't eliminate the fan-out false-positive under the old signal.
- Grilling session transcript — 2026-05-07.
