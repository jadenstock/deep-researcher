# ADR 0004 — ACH consistency matrix batches per hypothesis, not per (hypothesis, source) pair

**Status:** Accepted
**Date:** 2026-05-07
**Context in:** `tdd-v3.md` §5.7.5 (ACH pattern)
**Related:** ADR 0002 (task granularity matches reasoning unit)

---

## Context

TDD v3 §5.7.5 specified ACH's consistency analysis as fully atomized — one MID-tier task per (hypothesis, source) pair. For a realistic ACH invocation with N=4 hypotheses and M=15 source_notes, this is 60 MID-tier LLM calls just for the consistency matrix. ACH can fire more than once per run, so a Test Case 3-style research question plausibly produces 150+ MID-tier calls on ACH alone, on top of everything else the pipeline does.

ADR 0002 flagged this as an open question. The N × M atomization was a default, not a deliberate design — it fell out of "atomize everywhere." Under ADR 0002's principle (task boundary = natural reasoning unit), the right unit for a consistency evaluation is "one hypothesis against all available evidence," not "this hypothesis against this single source."

## Decision

The ACH consistency matrix is computed with **N tasks, not N × M**. Each task evaluates one hypothesis against all M source_notes and returns M consistency verdicts in a single structured output.

Specifically:

- **Input to one consistency task:** the hypothesis text + the M source_note digests (title, tier, one-line landscape contribution, relevant extracted claims with quotes).
- **Output:** a structured verdict per source — `{source_id, verdict: consistent | inconsistent | neutral, rationale: str}` — for all M sources.
- **Model tier:** MID, low temperature, frontier-context-window class (to hold M source digests comfortably).
- **Degrade path:** if M exceeds a soft limit (default 25 source digests), split the hypothesis task into two passes by source subset. If context-window constraints make even that unworkable on a specific run, fall back to per-pair atomization for that specific ACH invocation, logged in a `decision_note`.
- **Adjudication step (Phase 3 of ACH)** stays as a single HIGH-tier task that reads the full N × M verdict matrix, computes inconsistency scores, adopts the tentative position, and writes the `synthesis_note`.

Cost for a realistic ACH invocation: 4 MID consistency tasks + 1 HIGH adjudication task = 5 significant calls per ACH. Two ACH invocations per run ≈ 10 significant calls. Tractable for demo scale.

## Alternatives Considered

### (A) Keep per-pair atomization (original TDD v3 spec).
Rejected. Produces 60+ calls per ACH invocation on realistic inputs. Violates ADR 0002. Wall-clock and cost both problematic for a demo.

### (B) Per-hypothesis batching (accepted above).
Selected.

### (C) Two-stage ACH with linchpin-triage pre-selection.
Rejected for MVP. Reintroduces LLM-prior decision-making (picking "linchpin" sources ahead of evidence-consistent reasoning), which is the same class of problem ADR 0001 was designed to eliminate. Deferred as an optimization pass if per-hypothesis batching turns out to be too expensive in practice.

## Consequences

### Positive

- Cost reduction: N calls instead of N × M per ACH.
- Cross-source reasoning for a single hypothesis happens in one context — contradictions and patterns across sources are visible to the agent evaluating that hypothesis.
- Evaluating the same source across different hypotheses now happens in different task contexts, which likely reduces cross-hypothesis anchoring bias (the agent evaluating hypothesis H2 doesn't see its own reasoning on H1).
- Aligns with ADR 0002's principle without requiring re-argument.

### Negative

- Larger context per consistency task (M source digests). Mitigated by the source digest format (progressive disclosure) and the degrade path for large M.
- If a consistency task fails mid-way, we lose M verdicts instead of 1. Mitigated by task-level retry — the cost of re-running one hypothesis's consistency evaluation is bounded.
- Less parallelism — N parallel tasks instead of N × M. For realistic N=4, wall-clock still dominated by the longest hypothesis evaluation, not the count.

### Neutral

- Option (C) remains available as a future optimization if profiling shows specific ACH invocations are too expensive. The ADR makes the trade-off explicit so the future decision is traceable.

## References

- ADR 0002 (task granularity principle).
- `phase-1-initial-design/05-tdd-v3.md` §5.7.5 — the ACH spec being revised.
- Grilling session transcript — 2026-05-07.
