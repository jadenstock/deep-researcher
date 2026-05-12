# Deep Research Agent — TDD v4 — Report, Biases, Walkthrough, and Plan

**Covers:** §5.15 Report Structure, §5.16 Bias Countermeasures, §6 End-to-End Walkthrough, §7 MVP vs Deferred, §8 Comparison / Ablation, §9 Open Questions, §10 Summary of Design Commitments.

See `07-tdd-v4-00-overview.md` for architecture diagram, data model, ADR index, and principles.

---

## 5.15 Report Structure — The Analytic Pyramid

`WRITE_REPORT` produces a markdown document with this 10-section structure. Each section has real content; no placeholders.

1. **Problem Statement** — 1–2 sentences restating the user's query as a research question. Does not contain the answer.
2. **Research Design** — Which orchestration patterns were used, number of sources loaded by tier, Q&A methodology (round-ladder rounds touched), **landscape survey summary** (themes surfaced, sources tier-distribution), **model routing policy for this run** (ADR 0008: which family played generative vs. judgment).
3. **Bottom Line Up Front (BLUF)** — AIMS-structured: Audience, Issue, Message, Storyline. The headline judgment, stated first.
4. **Linchpin Assumptions** — The foundational premises the conclusion rests on. For each: the assumption, why it's accepted (evidence basis), what would falsify it.
5. **Evidence Summary** — Key data points, organized by tier. Cites source quality levels. Includes the source-tier distribution and peer-review fraction.
6. **Alternative Hypotheses** — All competing positions seriously considered. For each, why it was rejected as less likely. Contested sub-questions show their full ACH or debate outcome here, including inconsistency scores.
7. **Calibrated Uncertainty** — Per claim and per BLUF judgment, the standardized confidence language + numeric range + explicit caveats (e.g., "primary evidence is preliminary").
8. **Intelligence Gaps** — Distinguishes:
   - **(a) Diagnostically significant gaps** — filling them would change the conclusion.
   - **(b) Acknowledged limitations** — noted but do not change the conclusion.
   - **(c) Deferred sub-questions** — if scope-creep escalation narrowed the run (ADR 0005), the cut-list lands here as `open_question_notes`.
9. **Milestones for Revision** — Specific future events or new data that would invalidate the current conclusion (Gate 6 falsifiability commitment).
10. **Findings / Insights / Recommendations** — three distinct levels, never collapsed:
    - **Finding**: raw data, observable fact ("What is?")
    - **Insight**: interpreted meaning, causal reading ("What does this mean?")
    - **Recommendation**: proposed action, contingency plan ("What should be done?")

A fact is never stated as a recommendation; an assumption is never stated as a finding.

Accompanying output: the Obsidian-compatible vault of the note graph at `./runs/{run_id}/vault/`, including the `landscape_note`, all `source_note`s with `tier_rationale`, all `decision_note`s (including cascade-mutation records), and the full `hypothesis_note`s from any ACH invocation.

---

## 5.16 Bias Countermeasures and Prompting Discipline

Woven into specific task prompts rather than a separate component. Listed here for traceability.

### Five named biases

| Bias | Where the countermeasure lives |
|------|------------------------------|
| **Confirmation bias** | `ach` pattern (evaluate each evidence item against ALL hypotheses, ADR 0004 batching preserves this property). Replanner's Round 3 check. |
| **Satisficing** | `DECOMPOSE` and ACH hypothesis enumeration explicitly over-enumerate before converging. Landscape survey (ADR 0001) provides breadth before decomposition narrows. |
| **Anchoring** | Replanner's Round 5 explicitly asks "re-evaluate from scratch — does this still hold?" every K cycles. Cross-family judgment routing (ADR 0008) structurally resists anchoring on generative-family priors. |
| **Availability** | Triangulation requirement (below). "Dog that didn't bark": verifier's prompt includes "has the evidence we'd *expect* to see if the hypothesis were true actually appeared?" |
| **Mirror imaging** | Included in the replanner prompt as a check for queries about actor behavior or incentives. Generally not load-bearing for the research-agent use case. |

### Triangulation requirement

For every claim marked load-bearing (linchpin or BLUF-level), the system computes a triangulation score across three vectors:

```python
triangulation_score = sum over three vectors:
  0.33 if vector covered else 0

Vectors:
  1. Source type diversity: ≥ 2 of {peer-reviewed, institutional, practitioner, preprint}
  2. Time diversity: sources span ≥ 2 years
  3. Methodological diversity: ≥ 2 of {empirical, theoretical, survey, benchmark, opinion}
```

Fed into the confidence formula (§5.7) as `triangulation_bonus`. A load-bearing claim with `triangulation_score < 0.66` → `VALIDATE_COMPLETION` G3 may fail, spawning remediation.

**Rule:** three sources citing the same original study do not count as three independent sources. Detection: during `ANALYZE_SOURCE`, if a claim's supporting quote cites a specific upstream paper, the extractor tracks it; triangulation math deduplicates.

### SIFT for the scanner

The `SCAN_SEARCH_RESULTS` prompt includes the four SIFT steps:

1. **Stop** — don't pass a hit through based on title alone.
2. **Investigate** — has the source's domain been seen before in this session? What's its tier (cached)?
3. **Find better coverage** — is this claim likely findable in a higher-tier source? Prefer that source.
4. **Trace** — if the hit is a summary or aggregator, prefer the original.

### Model-routing as a bias countermeasure (ADR 0008)

Cross-family judgment routing is itself a structural bias countermeasure. Same-family `ANALYZE_SOURCE` → `VERIFY_CLAIM` produces compounding agreeableness / self-preference bias; cross-family routing breaks the compounding mechanically, not by prompt discipline.

---

## 6. End-to-End Flow: Example Walkthrough (v4)

**Query (Test Case 2):** "Is chain-of-thought prompting an effective reasoning strategy for LLMs, or does it primarily improve output formatting?"

### Phase 1 — Landscape Survey

1. `LANDSCAPE_SURVEY` (generative, HIGH) dispatched with the raw query.
2. Three SEARCH tasks fan out (web + academic + arXiv). `SCAN_SEARCH_RESULTS` filters to 8 candidates.
3. `FETCH_AND_EXTRACT` (deterministic) runs per candidate: reject-list passes all; size-route splits (two conference papers ≥ 8K → structured_content; six shorter pieces → full). LLM tier classifier (cheap, LOW) assigns tiers with rationale. Peer-review flag set deterministically.
4. `LANDSCAPE_SURVEY`'s agent reads the 8 stub source_notes in rounds, emitting a `landscape_note`:
   - Themes: reasoning-effect evidence, formatting-effect evidence, scale-conditional evidence, measurement-artifact evidence.
   - **Positions surfaced: 3** (reasoning-genuine, formatting-primary, scale-conditional).
   - Key sources per theme; tier distribution 2 × TIER_1, 4 × TIER_2, 2 × TIER_3.

### Phase 2 — Decomposition (evidence-grounded)

5. `DECOMPOSE` reads the landscape_note.
   - AIMS: Audience = "ML researcher/engineer familiar with LLMs"; Issue = "when to use CoT and what effect to expect"; Message = "effect depends on task and scale; reasoning-vs-formatting is a false dichotomy if both are in play"; Storyline = "present surfaced positions, show evidence, synthesize into a conditional."
   - Sub-questions:
     - Q1: Evidence CoT improves reasoning → `contested` (landscape shows 3 positions) → `multi_perspective` + **`ach`** (grounded in evidence, not priors).
     - Q2: Evidence CoT improves formatting → `contested` (3 positions) → `multi_perspective` + `ach`.
     - Q3: Conditions where CoT helps vs. not → `synthesis` → `single_researcher` + `maker_checker`.
   - Typed dependencies emitted: Q3 `produces_context_for` the final cross-question synthesis (not Q1/Q2 directly; Q3 is a synthesis step).
6. `decision_note` records AIMS + decomposition rationale + dependency rationale.

### Phase 3 — Deep Research

7. Three pattern-invoking tasks dispatched. Q1 and Q2 run `multi_perspective` with N=3 (theoretical / empirical-benchmark / critical). Each perspective runs `single_researcher`: SEARCH → SCAN → FETCH_AND_EXTRACT (cache hits on landscape-fetched sources; new fetches for others) → ANALYZE_SOURCE (uses `load_source_section` on the two long conference papers) → `QUESTION_SYNTHESIZE` (batched; one task reads all source_notes for the perspective).
8. Tier classifier output (example): Wei et al. CoT paper → TIER_1 (peer-reviewed, top venue, rationale records methodology rigor); Madaan et al. critique (arXiv, 50+ cites, explicit methodology, named institution) → TIER_2 with `peer_reviewed=False`; vendor blog → TIER_5 (reject list).
9. `maker_checker` (on Q3) runs `VERIFY_CLAIM` on load-bearing claims. Judgment family (e.g., GPT-5) runs verification; different from the Claude family that ran `ANALYZE_SOURCE`. Verifier independently retrieves formatting-effect literature; updates Q1's main claim to `CONTESTED`.

### Phase 3 — Replanner fires at 10 completions

10. `REPLAN` (generative, HIGH; bounded mutation budget = 3):
    - Round 3 check: is disconfirming evidence sought? Yes, verifier ran.
    - Round 4 premortem: weakest sub-question is Q2 (formatting).
    - Round 5 metacognitive: the combined Q1+Q2 space has surfaced a fourth plausible hypothesis — "CoT is measurement artifact from eval methodology." Not captured at decomposition.
    - Mutation emitted: escalate Q1 (and Q2 under cross-reference) to include the new hypothesis. Budget used: 1 of 3.

### Phase 3 — ACH runs (ADR 0004 batching)

11. ACH enumerates 4 hypotheses.
12. `ANALYZE_CONSISTENCY` runs **4 tasks, not 4 × M**. Each evaluates one hypothesis against ~15 source_note digests; returns 15 verdicts. Judgment family. One consistency task exceeds typical context → degrade path: split into two passes by source subset (no fall-back to per-pair needed).
13. Adjudication `SYNTHESIZE` (generative, HIGH, Round 5): hypothesis C ("scale-conditional effect") has the lowest normalized inconsistency score. Surviving dissent documented. Linchpin evidence flagged. Two hypotheses are "under-tested" (< 3 evaluated pieces); reported as such.

### Phase 4 — Completion

14. Replanner emits no mutations → `CHECK_TERMINATION_READY` fires.
    - No PENDING tasks ✓.
    - Every sub-question SYNTHESIZED ✓.
    - Scope-creep has not been escalated to "broaden" ✓.
    - Every contested sub-question has a disconfirmation task DONE ✓ (Q1, Q2 each have an `ach` invocation linked).
    - Passes.
15. `VALIDATE_COMPLETION`:
    - G1: adopted position anchored on ≥ 2 TIER_1-2 sources ✓.
    - G2 (judgment family): ACH ran ✓.
    - G3: linchpin assumptions identified; triangulation score = 1.0 ✓.
    - G4 (judgment family): Round 4 premortem ran ✓.
    - G5: Moderate confidence achievable (0.72) ✓.
    - G6: deferred to report draft structural check.
16. `WRITE_REPORT` (generative, HIGH) produces the Analytic Pyramid.
    - BLUF: "CoT likely improves reasoning on tasks requiring intermediate computation at sufficient model scale, but its effect on simple classification tasks appears to be largely formatting / regularization. *(Moderate confidence, 0.72; primarily peer-reviewed evidence with preliminary corroboration.)*"
    - Section 2 (Research Design): landscape survey summary, 3 positions surfaced, model routing policy (Claude generative / GPT judgment / Haiku cheap-deterministic).
    - Section 4 (Linchpin): benchmark taxonomy distinction; Wei-et-al. scale threshold generalization. Falsifier: prompt-structure artifact confound.
    - Section 6 (Alternatives): all 4 ACH hypotheses with inconsistency scores; two flagged as under-tested.
    - Section 9 (Milestones for Revision): prompt-structure-controlled studies; meta-analysis on instruction-tuned models.
    - Section 10: Findings / Insights / Recommendations (none — research task, not decision task; noted explicitly).
17. Vault export → `./runs/{run_id}/vault/` for Obsidian browsing.

---

## 7. MVP vs. Deferred

### MVP

- Task graph + scheduler (in-memory, serial note writes, staged waiting on typed deps per ADR 0006).
- **Landscape Survey phase** (ADR 0001) with `landscape_note` emission.
- Intake with AIMS scoping, evidence-grounded classification, typed dependency emission.
- Agent executor with **role-to-model routing** (ADR 0008: generative / judgment / cheap_deterministic).
- Search layer: Serper + Semantic Scholar + arXiv + Unpaywall + `trafilatura` + MarkItDown.
- **Size-first deterministic source extraction** with `load_source_section` tool (ADR 0007).
- **LLM semantic source tiering with deterministic reject + peer-reviewed flag + 0.80 cap** (ADR 0003).
- Confidence language ladder (number → qualitative label translation).
- Note graph with 7 types (including `landscape_note` and `hypothesis_note`).
- Obsidian vault export.
- Orchestration patterns: `single_researcher`, `maker_checker`, `multi_perspective`, `debate`, `ach` — with ACH's per-hypothesis batching (ADR 0004).
- Task-granularity principle applied: landscape analysis batched; question synthesis batched; ACH adjudication batched; per-item work atomized (ADR 0002).
- Verifier with judgment-family routing (ADR 0008 invariant).
- Replanner with Round 3/4/5 prompt scaffolding + typed-dependency detection (ADR 0006) + **mutation budget and cadence** (ADR 0009).
- **Sub-question-level scope-creep detection** with structured escalation payload (ADR 0005).
- **`CHECK_TERMINATION_READY` deterministic task** (ADR 0009).
- Completion gates + `VALIDATE_COMPLETION` (G2/G4 judgment-routed).
- `WRITE_REPORT` producing the 10-section Analytic Pyramid.
- User gateway at L0 and L3 (landscape-post-survey escalation included at L3+).
- Stopping on task-graph exhaustion via termination-readiness, with scope-creep escalation path.
- **Ablation harness** — run-level config file for model routing, so single-family / cross-family configs are swappable (§8).

### Deferred

- L1, L2, L4, L5 interactivity levels (stubbed to L3 behavior).
- PubMed / OpenAlex (feature-flagged; add per test-case need).
- Self-reflection loop post-run.
- Full observability UI.
- Graceful degradation beyond retry.
- LLM-judge evaluation harness.
- Prompt versioning / auto-improvement.
- Cross-session memory.
- Embedding-backed RAG.
- Full 4-phase formal devil's advocate protocol (adversarial critique in MVP is a lighter version).
- Two-stage ACH with linchpin pre-selection (ADR 0004 Alternative C; deferred until profiling justifies).
- Multimodal fetching (figures / images) — ADR 0007 notes this is post-MVP.
- Dynamic task granularity re-bundling (ADR 0002 Alternative C; deferred).

---

## 8. Comparison / Ablation for the Take-Home

Primary candidate (elevated from v3 per ADR 0008): **model-routing ablation**.

### Ablation matrix

| Configuration | Purpose |
|---|---|
| Single cheap family everywhere | Lower-bound baseline — how much does model quality matter? |
| Single frontier family everywhere | Upper-bound baseline — what does unlimited budget buy? |
| **Default diversity policy** (Claude generative / GPT judgment / Haiku cheap-deterministic) | Production target — does cross-family diversity outperform either single-family? |
| Diversity variant (swap which family is generative vs. judgment) | Sensitivity — is the effect directional or symmetric? |

**Metrics:**
- Claim-level faithfulness (quote → claim support rate).
- Scope coverage (% of sub-questions answered with Moderate+ confidence).
- Contested-claim surfacing rate (on Test Case 2).
- Final-report calibration (confidence-vs-correctness on ground-truth claims where available).
- Cost per run (tokens + dollars).

### Secondary ablations (if time permits)

1. **With vs. without the verifier tier.** Isolates the value of independent verification. Clean metric: claim-level faithfulness.
2. **`ach` vs. `debate` on contested sub-questions with 3+ plausible positions.** Tests whether multi-hypothesis catches positions `debate` misses. Metric: number of plausible positions surfaced and retained.
3. **Scanner / analyzer split vs. single-stage retrieval.** Tests whether the split improves precision at no coverage cost. Metric: relevance-weighted recall at fixed cost budget.
4. **Landscape survey on vs. off.** Tests whether evidence-grounded decomposition beats prior-grounded decomposition (ADR 0001). Metric: pattern selection correctness + final report position coverage.

**Recommendation:** lead with the model-routing matrix (4 configs, one clean table). The landscape-survey ablation is the second-most-novel story (closest to the design's core bet). Verifier ablation is the cleanest eval if time is tight.

---

## 9. Open Questions (for Phase-2 Research and Implementation)

Load-bearing unknowns worth stress-testing during implementation. Where an ADR raised an open question, it's cross-referenced.

1. **Landscape survey budget** — scope/depth scaling heuristic. Narrow-lookup vs. broad-query thresholds (ADR 0001 open question).
2. **Tier classifier calibration anchors** — which specific sources become the prompt's anchor examples across tiers (ADR 0003 open question).
3. **Classifier-confidence-low fallback** — below what threshold should the tier default to conservative rather than the classifier's best guess (ADR 0003).
4. **ACH degrade-path thresholds** — at what M does the split-by-subset trigger; at what point do we fall back to per-pair (ADR 0004).
5. **Scope-creep K tuning** — default K=2 may be too jumpy or too patient (ADR 0005).
6. **Cascading mutation edge cases** — behavior when multiple replan cycles interact; dependency-cycle prevention beyond the decomposer's basic check (ADR 0006, ADR 0009).
7. **Size-route 8K threshold tuning** — conference papers at the boundary could go either way (ADR 0007).
8. **Cross-family prompt variants** — how much tuning is needed to normalize behavior across Claude / GPT for the same role (ADR 0008).
9. **Replanner cadence and mutation budget defaults** — 10 and 3 are guesses; meant to be tuned empirically (ADR 0009).
10. **Specialized analyzer prompts** — whether academic-paper vs. blog-post prompt variants produce meaningfully different output quality (ADR 0007 open question).
11. **Dependency-type taxonomy coverage** — three types cover the current test suite; watch for query shapes that need a fourth (ADR 0006).
12. **Well-researched / partially / barely started categorization thresholds** in the scope-creep escalation payload (ADR 0005).
13. **Triangulation vector classifier rules** — who assigns "methodological diversity" buckets, and when (v3 carryover).

---

## 10. Summary of Design Commitments (v4)

- **Task-centric, agent-ephemeral.** Agents live only to execute a task.
- **Note-graph as shared workspace.** Typed, hyperlinked, Obsidian-exportable. Progressive disclosure throughout, including size-first source extraction (ADR 0007).
- **Four-phase pipeline.** Landscape Survey → Decomposition → Deep Research → Completion & Report. Pattern selection is evidence-grounded (ADR 0001).
- **Task granularity matches reasoning unit** (ADR 0002). Per-item work atomizes; cross-item work batches. Applied to landscape analysis, question synthesis, and ACH adjudication.
- **Closed set of orchestration patterns:** `single_researcher`, `maker_checker`, `multi_perspective`, `debate`, `ach`. Each a sub-task DAG with explicit question-round framing.
- **ACH consistency matrix batched per hypothesis** (ADR 0004). N tasks, not N × M. The primary cost-driver of the most rigorous pattern is tractable for demo scale.
- **LLM semantic source tiering** with deterministic reject list + separate `peer_reviewed` field + 0.80 preliminary cap (ADR 0003). Rationale is inspectable per source.
- **Size-first deterministic source extraction** (ADR 0007). < 8K full; ≥ 8K structured_content + `load_source_section`. No pre-summarization; no RAG.
- **Typed dependencies, staged waiting, runtime detection** (ADR 0006). Retrieval parallelizes; synthesis serializes on deps.
- **Sub-question-level scope-creep detection** (ADR 0005) with structured escalation; default fallback narrow.
- **Role-to-model routing** with diverse families for judgment roles (ADR 0008). `VERIFY_CLAIM.family ≠ ANALYZE_SOURCE.family` is a hard invariant, not a prompt discipline. Config-driven per run; primary ablation candidate.
- **Bounded replanner** (ADR 0009). Termination requires a deterministic `CHECK_TERMINATION_READY` structural audit; mutation budget + cadence configurable; cascade semantics specified for merge / split / abandon / add-edge.
- **Six completion gates** (G2, G4 judgment-routed).
- **Confidence language ladder** + triangulation-aware formula + preliminary cap.
- **Analytic Pyramid (10 sections)** as the report structure, with Finding / Insight / Recommendation strictly separated.
- **Five bias countermeasures** woven into replanner, verifier, ACH, and routing.
- **Search layer:** Serper + Semantic Scholar + arXiv + Unpaywall concrete for MVP.
- **User-in-the-loop** L0–L5, async-preferred, default-fallback mandatory; landscape-post-survey escalation available at L3+.
- **No hard budgets.** Stop on termination-readiness, scope-creep escalation, or compaction on context-window pressure.
- **Question-round discipline** in every agent prompt prevents drift into vague prompting.
