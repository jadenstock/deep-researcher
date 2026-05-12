# Q2: Vague question in, concrete research out. What happens in between?

## What the research says

The corpus is **thin** on explicit question-refinement mechanics. Most sources assume the input is already well-formed and focus on downstream execution. The closest documented mechanism is **Personalized Deep Research Bench (PDR-Bench)**, which pairs research tasks with user personas and scores how well the output matches user-specific intent (Goal Alignment, Actionability) — this exists because intent-matching is genuinely hard and underspecified.

**What sources do document:**

- **STORM's persona-based perspective-taking** (via Architectural Frameworks, single-source): the system generates diverse sub-queries by adopting stakeholder perspectives. This is a way of *producing* breadth from a vague input rather than narrowing one.
- **Orchestrator-worker decomposition** (GPT Researcher's Chief Editor): a lead agent breaks the query into research threads for specialists. The decomposition quality is the critical lever — the corpus doesn't document how to validate it.
- **Adversarial constraint generation** (Marco DeepResearch, training-time only): during synthesis of training data, a Generator proposes constraints and an Attacker searches for counterexamples. Not directly applicable to intake, but the pattern — generate then stress-test — transfers.

**What sources do NOT cover:**

- Clarifying-question generation (when to ask the user vs. when to decide).
- Ambiguity detection (what makes a query actually vague vs. just underspecified).
- User-in-the-loop refinement loops — just LLM-driven decomposition.

## Design implication for an API-based system

The intake pipeline should do four things, in order:

1. **Classify the query type.** Straightforward factual (Test Case 1), contradictory-sources (Test Case 2), sparse-emerging (Test Case 3), multi-modal output (Test Case 4) — each requires a different strategy. The assessment's own four test cases are a natural taxonomy. A small router decides.
2. **Propose a sub-question decomposition** with explicit success criteria per sub-question. Use structured outputs so this is parseable and diffable.
3. **Surface low-confidence decomposition decisions to the user** as a clarifying question — only when the ambiguity is load-bearing (i.e., would produce materially different research). Most queries don't need this; when they do, it's cheap compared to doing the wrong research.
4. **Commit the final decomposition as the report scaffold.** The output report's structure mirrors the sub-questions, which makes "did we answer what was asked" auditable.

For a well-formed query ("Is chain-of-thought prompting effective for reasoning?"), intake should take one LLM call and produce a 3-5 sub-question plan with stopping criteria per sub-question. For a vague query ("Tell me about LLMs"), intake should ask one clarifying question before burning retrieval tokens.

## Key failure mode to instrument against

**Decomposition over-narrowing.** If the intake LLM decomposes "is CoT effective?" into only pro-CoT sub-questions, the entire report is biased from step zero. Mitigation: explicitly ask the decomposer for the strongest counter-framing and treat it as a mandatory sub-question.

## Residual uncertainty

- No documented heuristic for when a clarifying question pays off. A real system needs this empirically calibrated (probably via offline evaluation — "would the same system with and without clarification produce different reports?").
- Intake LLM pathology: same-model bias means the decomposer inherits the generator's confirmation bias. Using a different model (even same family, different temperature) for decomposition may help but is undocumented.

## Anchor sources

- PDR-Bench (intent-matching is hard, scored via Goal Alignment)
- Architectural Frameworks report — STORM persona-based decomposition
- GPT Researcher — Chief Editor decomposition pattern
- Marco DeepResearch — generate-then-stress-test pattern (adjacent, training context)
