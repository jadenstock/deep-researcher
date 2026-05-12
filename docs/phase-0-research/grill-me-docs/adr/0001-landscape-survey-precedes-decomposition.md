# ADR 0001 — Landscape Survey precedes Decomposition

**Status:** Accepted
**Date:** 2026-05-07
**Context in:** `tdd-v3.md` §5.1 (decomposition), §5.7 (orchestration patterns), §5.10 (replanner)

---

## Context

TDD v3 placed `DECOMPOSE` as the first active phase of a research run. The decomposer's job was to classify sub-questions (`lookup` / `synthesis` / `contested` / `sparse`) and assign default orchestration patterns — including routing to `ach` (the most expensive pattern in the system) for sub-questions classified as "contested with ≥ 3 positions."

This placement meant the decomposer operated on **LLM priors alone** — no retrieval had run yet. Pattern selection, and in particular the most expensive pattern, was being gated on what pretraining happened to know about a topic.

Concrete failure modes of this placement:
1. **Wrong-count false positive.** LLM lists three plausible positions that don't actually have meaningful evidence in the corpus; ACH runs on hallucinated hypotheses and burns cost evaluating phantom positions.
2. **Wrong-count false negative.** LLM surfaces two positions; a load-bearing third exists in the literature as a minority view; `debate` runs and the third never surfaces.
3. **Domain-prior bias.** The LLM's position-count is highly reliable for well-trodden AI topics but unreliable for sparse or emerging ones — exactly the topics where decomposition-quality matters most.

## Decision

Insert a **Landscape Survey** phase before decomposition. The survey is a broad, shallow retrieval pass whose job is to map the territory of the user's query — not to answer sub-questions.

The four pipeline phases, in order:

1. **Landscape Survey** — broad shallow retrieval; emits a `landscape_note`.
2. **Decomposition** — reads the landscape_note; classifies sub-questions and assigns patterns based on retrieved evidence.
3. **Deep Research** — orchestration patterns run the main research loop.
4. **Completion & Report** — gates, then Analytic Pyramid.

Pattern selection thresholds (e.g., "≥ 3 positions → ACH") are now grounded in what the survey actually surfaced, not in LLM priors.

## Alternatives Considered

### (A) Keep decomposition first; never run ACH at decomposition; escalate to ACH only at runtime from the replanner.

Rejected because:
- Still forces the decomposer to choose between `single_researcher` / `multi_perspective` / `debate` based on priors.
- Runtime escalation requires `multi_perspective` to run first on every contested sub-question just to generate the evidence needed to decide if ACH is warranted — effectively paying the survey cost but spreading it across the deep-research loop with less controllable scope.
- Harder to reason about budget — survey cost is predictable and bounded; deep-research cost is open-ended.

### (B) Ask the user to pre-classify sub-questions.

Rejected because:
- Shifts the LLM-prior problem onto the user, who may know less about the literature than the model.
- Violates the goal of "vague question in, concrete research out" — the whole point is that the system does the scoping work.
- Still doesn't solve the position-count problem; users won't know whether a topic has 2 or 3 positions in the literature.

### (C) Run a single ACH on the original user query before decomposition.

Rejected because:
- ACH on an un-decomposed query is ill-defined (hypotheses about what?).
- Over-invests in a single expensive pattern when the problem may not be multi-hypothesis at all.

## Consequences

### Positive

- Pattern selection is now defensible and evidence-grounded.
- Decomposition is informed by what actually exists in the literature rather than what the model remembers.
- The Landscape Survey's output is an auditable artifact (the `landscape_note`) that a reviewer can inspect. Helps with the "did you understand the space before deciding how to research it?" question.
- Mirrors the professor+grad-students workflow motif (`phase-1-initial-design/03-workflow-motifs.md`): a human doing a lit survey scans before assigning deep reads.
- Aligns with the question-ladder's Round 1 Starbursting discipline — the survey is literally the Round 1 of the whole run.

### Negative

- Adds one phase of latency and token cost to every run, including simple `lookup` queries where the survey is arguably overkill. Mitigated by making the survey's scope scale with the query's apparent breadth (single lookup → small survey; broad query → larger survey).
- Introduces a new task type (`LANDSCAPE_SURVEY`) and note type (`landscape_note`) that the TDD must specify.
- The decomposer now has a dependency on the survey's output format; changes to the landscape_note schema cascade to the decomposer prompt.
- Risk of survey/research redundancy: if the survey fetches and lightly analyzes sources, and deep-research fetches the same sources and deeply analyzes them, we pay twice. Mitigation: the note graph is the single storage substrate, and sources fetched during survey are reused in deep-research via `load_note` and fetch-cache hits.

### Neutral

- The Landscape Survey can itself honor interactivity level (L3+): if the survey surfaces a decomposition where one branching is material, the user can be consulted *after* survey and *before* decomposition. Better UX than asking the user at intake with no evidence.

## Open Questions (cascading from this decision)

- What does the `landscape_note` actually contain? Positions and themes, or just sources? (See grilling session question Q2.)
- What's the budget envelope for the survey? Scope/depth must scale with the query's complexity but not unbounded.
- Does the survey need its own scanner/analyzer split, or is it a single shallower task?
- How does the survey handle a query where the LLM has no useful priors (truly new domain)? Needs fall-back behavior.

## References

- `phase-1-initial-design/05-tdd-v3.md` — TDD being revised.
- `phase-1-initial-design/03-workflow-motifs.md` — the professor+grad-students mental model.
- `phase-1-initial-design/04-research-skill-takeaways.md` — methodology rigor context.
- Grilling session transcript — 2026-05-07.
