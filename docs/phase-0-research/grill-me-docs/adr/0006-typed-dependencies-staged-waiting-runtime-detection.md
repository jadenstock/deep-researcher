# ADR 0006 — Typed dependencies, staged waiting, and runtime dependency detection

**Status:** Accepted
**Date:** 2026-05-07
**Context in:** `tdd-v3.md` §4.1 (task schema), §5.1 (decomposer), §5.2 (scheduler), §5.10 (replanner), §9 open question #5

---

## Context

TDD v3's orchestrator fans sub-questions out in parallel after decomposition. Every sub-question is treated as independent. The task schema has `depends_on: [TaskID]` but the decomposer has no explicit process for emitting dependencies, and the replanner has no rule for discovering them at runtime.

This is wrong for common research query shapes:

- **Consumes-another.** Test Case 4: "what are the patterns?" (SQ1) produces context for "where are the open problems?" (SQ3). Running SQ3 without SQ1's synthesis produces generic findings.
- **Compare-and-contrast.** "How do X, Y, Z differ?" decomposes into understand(X), understand(Y), understand(Z), and compare(...). The last needs the first three.
- **Temporal evolution.** "How has Z evolved?" decomposes into early-Z, current-Z, change-analysis. The third synthesizes across the first two.

Three failure modes under TDD v3 as-written:

1. Decomposer emits no dependencies; parallel fan-out produces thin downstream research and disconnected syntheses.
2. Decomposer over-conservatively serializes everything, losing parallelism even where sub-questions are genuinely independent.
3. Runtime-discovered dependencies (SQ1's research reveals SQ2 is actually a sub-topic) go unnoticed; the plan never restructures.

## Decision

Three coordinated changes.

### (a) Typed dependencies at decomposition

Task schema updates:
```python
depends_on: [(TaskID, DependencyType)]
DependencyType ∈ { produces_context_for, compared_against, temporally_follows, none }
```

The decomposer's Round-2 prompt gains an explicit dependency-identification step: "for each pair of sub-questions, which dependency type applies, if any?" Decomposer output includes a dependency graph, not just a task list.

### (b) Staged waiting

Dependencies block at the synthesis phase only, not at retrieval.

- Retrieval-phase tasks (SEARCH, SCAN, FETCH_AND_EXTRACT, ANALYZE_SOURCE) run in parallel regardless of dependency.
- Synthesis-phase tasks (SYNTHESIZE, UPDATE_QUESTION_NOTE when producing a final position) block on the upstream's synthesis completing.

Effect: SQ3 ("open problems") can be scanning and fetching open-problems literature in parallel while SQ1 ("patterns") is still analyzing. SQ3's synthesis unblocks when SQ1's synthesis lands; SQ3 then reasons over its accumulated sources plus SQ1's resolved position.

Implementation: dependency-scoping is a per-task-type attribute. Retrieval task types are marked `ignores_sub_question_dependencies=True`; synthesis task types are marked `waits_on_sub_question_dependencies=True`. The scheduler respects the attribute.

### (c) Runtime dependency detection

The replanner's prompt gains an explicit check on each replan cycle: "given the current note graph, has any sub-question revealed a structural dependency not captured at decomposition?"

Signals the replanner watches for:
- Sub-question A's `synthesis_note` contains claims structurally identical to sub-question B's framing → propose merging A into B or adding `produces_context_for(A, B)`.
- Sub-question B's retrieved sources directly reference sub-question A's resolved position → propose adding `produces_context_for(A, B)`; block B's synthesis on A.
- Two sub-questions' synthesis_notes converge on the same tentative position → propose merge.

On detection, the replanner emits a task-graph mutation (add edge, merge, split, abandon) and writes a `decision_note` with rationale.

## Alternatives Considered

### (A) Untyped dependencies (just `depends_on: TaskID`).
Rejected. Without types, the scheduler can't implement staged waiting (the retrieval/synthesis split depends on knowing whether a dependency blocks the retrieval phase or only the synthesis phase).

### (B) (a) only — typed dependencies at decomposition, full blocking, no runtime detection.
Considered for MVP simplicity. Rejected because:
- Full blocking gives up the retrieval-parallelism win that (b) provides.
- Without (c), runtime-discovered dependencies degrade the plan silently. On a real research query, this happens often enough to matter.
- (b) and (c) are both additive on top of (a) without structural cost — dependency-scoping attributes on task types are one line per type; replanner prompt addition is one block.

### (C) Let the replanner handle everything; skip (a) entirely.
Rejected. Decomposition-time dependency identification is cheaper and more reliable than runtime detection for dependencies that are obvious from the query structure. (a) catches the easy cases; (c) catches what (a) missed.

### (D) Implicit dependencies via note-graph link inspection (no typed edges).
Rejected. Implicit-dependency reasoning is probabilistic; the scheduler needs deterministic blocking semantics to avoid race conditions on synthesis ordering.

## Consequences

### Positive

- Query shapes with real sequential structure (consumes-another, compare-and-contrast, temporal evolution) are handled correctly.
- Retrieval parallelism is preserved; only synthesis serializes where needed.
- Runtime-discovered dependencies produce plan mutations, not silent degradation.
- Dependency types are inspectable in the Obsidian vault export — users can see why the system waited on something.
- Test Case 4's "taxonomy → open problems" structure becomes a clean first-class case, not an edge case the system stumbles on.

### Negative

- Task schema gains a field; scheduler gains a blocking-semantics attribute per task type; decomposer prompt gains a dependency step; replanner prompt gains a detection block. More surface area.
- Decomposer can still identify dependencies wrong. Mitigated by (c): runtime detection catches mistakes.
- Runtime detection in the replanner is an LLM judgment call. Could miss subtle dependencies or hallucinate false ones. Mitigated by the fact that the detection output is a *proposal* to mutate the task graph, logged in a `decision_note` — a human reviewer can audit.
- Staged waiting means a task can be in a more complex state ("blocked only on synthesis dep") than simple PENDING/RUNNING. Scheduler state machine grows slightly.

### Neutral

- Dependency detection at runtime and scope-creep detection (ADR 0005) are both replanner responsibilities. Keep them as separate prompt blocks within the replanner task rather than blurring them.

## Open Questions

- **Dependency type taxonomy.** Three types (`produces_context_for`, `compared_against`, `temporally_follows`) cover the common cases from the test suite. Are there query shapes that need a fourth? Watch during implementation.
- **Cascading mutations.** If the replanner adds a dependency edge that invalidates an in-progress synthesis, does the in-progress task abort, or does it complete and get re-run? Likely: complete-and-re-run is simpler; abort is wasted work but avoids stale synthesis. Defer the call to implementation.
- **Dependency-cycle detection.** The decomposer could emit a cycle. Basic cycle check during decomposer output validation should prevent this. Trivial; just noting the requirement.

## References

- `phase-1-initial-design/05-tdd-v3.md` §9 open question #5 — the original surfacing of sub-question-independence assumption.
- ADR 0001 — landscape-survey-precedes-decomposition, which informs what the decomposer has available when it emits dependencies (real retrieved landscape, not priors).
- ADR 0005 — scope-creep detection at sub-question level, parallel replanner responsibility.
- Grilling session transcript — 2026-05-07.
