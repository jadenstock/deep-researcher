# ADR 0002 — Task granularity matches the natural reasoning unit

**Status:** Accepted (working principle; expected to tune during implementation)
**Date:** 2026-05-07
**Context in:** `tdd-v3.md` §4.3 (task types), §5.3 (agent executor), §5.7 (orchestration patterns)

---

## Context

TDD v3 defaults to **atomize-then-synthesize** across the pipeline: break every operation into the smallest independent task, parallelize, and then run a later task to merge the outputs. Concrete example from `single_researcher`: N parallel `ANALYZE_SOURCE` tasks produce N `source_note`s, then an `UPDATE_QUESTION_NOTE` task merges them into a question-level synthesis.

This is correct for per-item operations (scanning 50 search-hit snippets; verifying one specific claim at a time) where the reasoning unit really is a single item and the parallelism win is real. It is **wrong** for cross-item reasoning (landscape synthesis, position enumeration, conflict detection) where:

- The coherent reasoning spans multiple sources simultaneously.
- Forcing the split produces per-source notes that then require a second LLM to re-read them to do the cross-source work that should have been done in one place.
- Token cost goes up (each source analyzed for extraction, then summaries re-read for synthesis).
- Cross-source patterns (contradictions, convergence, tension) are harder to see when the analyzer only ever sees one source.

Without an explicit principle, the default-to-atomize impulse will propagate through implementation: "just split it into smaller tasks; it'll be easier to parallelize." That produces the exact pathology described.

## Decision

Task granularity matches the natural reasoning unit for the operation.

- **Per-item operations atomize.** One task per item.
  - `SCAN_SEARCH_RESULTS` — per batch of hits (but the batch is processed by a single scanner; the atomization is per-query, not per-hit).
  - `FETCH_AND_EXTRACT` — per URL.
  - `VERIFY_CLAIM` — per claim.
  - `ANALYZE_SOURCE` — per source (deep reading of one paper is one reasoning unit).

- **Cross-item operations do not atomize.** One task handles the whole set.
  - **Landscape Survey analysis** — one task reads 5–10 sources in rounds within its own agent loop and emits the `landscape_note` + stub source_notes. Not N separate per-source analyses followed by a merge.
  - **Question-level synthesis** — one task reads all source_notes for a question and emits the synthesis. Not N per-source-to-question-note updates followed by a merge.
  - **ACH consistency analysis** — the consistency matrix itself is per-(hypothesis, source) pair, so the per-pair tasks stay atomized; but the adjudication step (computing inconsistency scores, surfacing linchpin evidence, adopting a tentative position) is a single task reading the full matrix.

- **When in doubt, default to the larger unit.** Atomization has real costs (token overhead, plumbing, state management). Batching has costs too (context size, failure blast radius), but those are easier to recover from than the systematic cross-source blindness that aggressive atomization produces.

- **Allow iterative reading within a task.** An agent executing a single task can use its ReAct loop to read-reason-read-reason across many sources. This is normal, not a workaround. The task's boundary is defined by the deliverable (one `landscape_note`; one question-level synthesis), not by the number of tool calls.

## Alternatives Considered

### (A) Atomize everywhere; parallelize aggressively.
Rejected because it produces the cross-source blindness described in Context. It also multiplies per-task setup / teardown costs (fresh context, source-note loading, scheduler round-trip) for work that conceptually belongs in one context.

### (B) Batch everywhere; serialize.
Rejected because some operations (per-claim verification; per-URL fetch; per-snippet relevance judgment) are genuinely independent. Batching them into one task gives up real parallelism and creates a single large context that doesn't need to exist.

### (C) Make granularity configurable at runtime.
Rejected for the MVP. Too much complexity for unclear benefit. The principle gives us a reasonable default; we can introduce dynamic re-bundling later if profiling shows a specific pattern suffering.

## Consequences

### Positive

- Cross-source reasoning happens in one context, where contradictions, convergence, and tension are visible.
- Fewer tasks in the task graph → less scheduler overhead, less state to reconcile, smaller note graph.
- Fewer LLM calls in total (no re-summarizing per-source outputs for downstream synthesis).
- The principle is named, so implementation choices can be checked against it.
- Stub source_note / full source_note lifecycle falls out naturally — survey analyzer emits stubs; deep-research upgrades them.

### Negative

- Larger contexts per task → more tokens per call, slower per call, higher risk of context-window hits.
- Less parallelism → longer wall-clock time for the survey and synthesis phases.
- Larger failure blast radius → if the landscape analyzer fails mid-task, more work is lost than if it had been N small tasks (one failing in isolation). Mitigated by task-level checkpointing, which the TDD already specifies.
- Harder to reason about cost per task. The budget envelope shifts from "N × cheap MID calls" to "1 × variable-length MID/frontier call."

### Neutral

- This principle will likely get refined during implementation when specific profiling data shows a batching-vs-atomization choice was wrong. Both directions are recoverable.

## Open Questions

- For the **question-level synthesis** inside deep-research: currently TDD v3 splits this into per-source `ANALYZE_SOURCE` + a separate `UPDATE_QUESTION_NOTE`. Under this principle, should `UPDATE_QUESTION_NOTE` actually be the one doing the cross-source reasoning (reading all the analyzed source_notes for a question and synthesizing), while `ANALYZE_SOURCE` only extracts raw claims? That preserves atomization where it makes sense (per-paper extraction) and batches where it matters (cross-source synthesis). Likely yes. To be confirmed during TDD v4.
- For **ACH**: the N × M consistency matrix is currently fully atomized (one task per (hypothesis, source) pair). Under this principle, should one task evaluate one hypothesis against all sources instead (N tasks total, not N × M)? Reasoning unit per hypothesis is arguably "check this hypothesis against all available evidence." Worth stress-testing.
- What is the **context-budget limit** at which a batched task should be broken up anyway? Needs empirical data.

## References

- `phase-1-initial-design/05-tdd-v3.md` — TDD being revised.
- `phase-1-initial-design/03-workflow-motifs.md` — the professor+grad-students motif and the analogous "analysis notes need an agent to combine them" concern.
- Grilling session transcript — 2026-05-07.
