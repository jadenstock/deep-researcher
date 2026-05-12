# Takeaways from the `research-agent` Skill

Read-through of Jaden's personal `research-agent` skill at `~/.claude/skills/research-agent/`. The skill encodes a research methodology built from intelligence-community analytic standards (ICD 203, Richards Heuer), PRISMA, Popper falsifiability, Tetlock superforecasting, and ACRL/SIFT information literacy. NotebookLM is the corpus engine; the methodology around it is the interesting part for our project.

**Goal of this doc:** flag the parts that transfer to our deep research agent design, ranked by how much they'd change (or strengthen) the current TDD. No design changes yet — this is a decision surface for Jaden.

---

## Tier A — Things I'd strongly consider pulling into TDD v3

### A1. The 5-round question depth ladder, phase-aware

The skill prescribes a sequence of question types:

- **Round 1 — Starbursting.** Generate questions, not answers. Map the problem space. "What are the conditions under which X would *not* hold?"
- **Round 2 — Structural decomposition (Fermi).** Break intractable into sub-problems.
- **Round 3 — Falsification probing.** "What evidence would *disprove* my current view?" The skill calls this the most-skipped, most-important round.
- **Round 4 — Premortem.** "It is 6 months from now. This conclusion was wrong. What were the top 3 reasons?"
- **Round 5 — Metacognitive critique.** Audit the thinking process itself.

The skill maps rounds to research phases: exploratory (3A) uses rounds 1–2; crystallization (3B) uses 2–3 + 4; application (3C) uses 3–5.

**Why it matters for us.** Our current `DECOMPOSE` task produces sub-questions, but there's no specified discipline around *what kinds of questions* to generate. Our `REPLAN` task reviews the plan but doesn't explicitly run falsification or premortem. Adopting the round-ladder means:

- The decomposer uses Round 1 + 2 patterns (boundary-drawing, sub-component identification) rather than just "list 3–5 sub-questions."
- The replanner uses Round 3 (what would falsify our current synthesis?) and Round 4 (premortem the current trajectory).
- The verifier (especially adversarial mode) uses Round 3 explicitly: "what evidence would disprove this?"
- Each orchestration pattern has an implicit round it naturally fits.

**What changes in the design.** This is mostly prompt discipline — no new components — but it meaningfully sharpens the prompts for `DECOMPOSE`, `REPLAN`, `VERIFY_CLAIM`, `ADVERSARIAL_CRITIQUE`. Could justify a "question type" field on task specs.

---

### A2. Analysis of Competing Hypotheses (ACH) as an orchestration pattern

From the bias-prevention doc. ACH is a specific technique for confirmation bias:

1. Generate **all** plausible hypotheses upfront (multiple, before evaluating any).
2. Evaluate each piece of evidence against **every** hypothesis simultaneously.
3. Accept the hypothesis that the **fewest** evidence pieces are inconsistent with — i.e., the one that survives the most attacks, not the one with the most supporting evidence.

**Why it matters.** Our current `debate` pattern is: produce position A, produce counter-position B, judge which is better supported. That's a **two-hypothesis** shootout. ACH is strictly more rigorous because it forces the system to enumerate *all* plausible positions before evaluating any, which catches cases where both A and B are wrong and C (a third position the debate didn't consider) is correct. This is a known failure mode — "binary trap" — that the debate pattern can walk straight into.

**What changes in the design.** Add `ach` to the closed set of orchestration patterns (§5.7 of TDD v2). Use it for sub-questions classified as `contested` with ≥3 plausible positions surfaced at decomposition. Heavier than debate; reserved for when the evidence landscape is genuinely multi-sided.

---

### A3. Six completion gates as a pre-report check

The skill has six explicit gates that must pass before research is "done":

1. **Methodological veracity** — central claim anchored in Tier 1 or Tier 2 evidence.
2. **Survival of disconfirmation** — lead hypothesis run through ACH and emerged with lowest inconsistency score.
3. **Linchpin stability** — sensitivity-tested against variation in the top 2–3 premises.
4. **Consensus through dissent** — devil's advocacy or premortem conducted; core logic survived.
5. **Standardized confidence** — at least Moderate (55–80%) confidence assignable.
6. **Falsifiability commitment** — what data would change the conclusion has been specified and confirmed not to currently exist.

**Why it matters.** Our current stopping criteria are (a) task-graph completion (b) progress stall. Neither checks whether the *output* is actually good enough to ship. The six gates are a pre-`WRITE_REPORT` checkpoint — a final validation that isn't "did we run out of things to do" but "is what we have actually load-bearing enough?"

**What changes in the design.** Add a `VALIDATE_COMPLETION` task that runs before `WRITE_REPORT`, tier HIGH. Its job is to check each gate against the note graph and either approve writing the report or spawn remediation tasks (typically: "this claim doesn't have a Tier 1–2 anchor, re-verify" or "ACH not yet run on the most contested sub-question, spawn that now").

---

### A4. Analytic Pyramid: the 10-section report structure

The skill prescribes a canonical structure for research output:

1. Problem Statement
2. Research Design (techniques used, source distribution)
3. BLUF — Bottom Line Up Front
4. Linchpin Assumptions (what must be true; what would falsify)
5. Evidence Summary (organized by tier)
6. Alternative Hypotheses (why each non-chosen was rejected)
7. Calibrated Uncertainty (standardized confidence language)
8. Intelligence Gaps (diagnostically significant vs. acknowledged-but-not-overturning)
9. Milestones for Revision (what future events would force a re-eval)
10. Findings / Insights / Recommendations (three distinct levels, never collapsed)

**Why it matters.** Our current report structure is informal — "one section per sub-question + claims + evidence." The Pyramid adds several things our design implicitly wants but doesn't formalize:

- **BLUF upfront** — readers see the judgment first, not after wading through evidence. Big UX improvement.
- **Linchpin assumptions** — explicit section stating what the conclusion rests on and what would falsify it. This is a trust signal readers can't get from claim-level confidence alone.
- **Alternative hypotheses section** — explicitly documents what was considered and rejected. Prevents the "convenient single narrative" failure mode.
- **Intelligence gaps distinction** — separating diagnostically-significant gaps from "we didn't check X but it wouldn't change the answer" is honest and useful.
- **Milestones for revision** — explicit commitment to when the report should be re-run. Useful for the user.
- **Finding / Insight / Recommendation separation** — the skill is emphatic: never state a fact as a recommendation, never state an assumption as a finding. Our design implicitly mixes these.

**What changes in the design.** Expand the `WRITE_REPORT` task spec to produce the 10-section structure. A prompt template change; not structural. Arguably the single highest-leverage adoption from the skill.

---

### A5. Confidence language standards

The skill rejects "bare probability language":
> "67% probability" implies quantitative rigor the research cannot support. Use ranges. Pair qualitative language ("likely," "probably") with a probability range (55–80%). Verbal qualifiers alone are "empty shells" — readers interpret them differently based on their own preconceptions.

Standard language ladder: **High (80–95%+)** = "almost certainly" / "highly likely"; **Moderate (55–80%)** = "likely" / "probably"; **Low (below 55%)** = "possible" / "unlikely."

**Why it matters.** Our §5.5 confidence formula outputs a number between 0 and 1. We don't have a translation to user-facing language — so downstream, either the report shows naked numbers (false precision) or the LLM invents a phrase (inconsistent). Adopting the skill's ladder gives us a deterministic number→language map.

**What changes in the design.** Extend §5.5 with a confidence-to-language translation table. Report always shows paired format: "likely (Moderate confidence, 0.62)."

---

### A6. Preliminary-source policy (refines our source tiering)

Our TIER_2 currently lumps all arXiv preprints together. The skill's rule is more nuanced:

- Preprints **default to Tier 3**, not Tier 2.
- **Upgrade to Tier 2 only when** all three are present: named author + recognized institution, substantial citation count OR Tier 1/2 published equivalent, explicit reproducible methodology.
- **Confidence ceiling** at Moderate (never High) when preliminary sources are primary evidence. This must be documented explicitly in the report.

**Why it matters.** Our flat Tier 2 = "arXiv" is too optimistic. A paper with 5 citations and no lab affiliation shouldn't rank alongside a well-cited arXiv preprint from a major lab. The skill's rule is more defensible.

**What changes in the design.** Refine §5.5's tiering rule table. Add the confidence-ceiling rule to the confidence formula: if any primary-supporting source is preliminary, cap confidence at 0.75. Document explicitly in reports that lean on preliminary evidence.

---

## Tier B — Prompting-discipline improvements (no structural changes)

### B1. AIMS scoping at intake

**A**udience / **I**ssue / **M**essage / **S**toryline. The skill uses this before finalizing any research question. Four fields that force the scoper to answer: who's this for, what are they struggling with, what's the bottom-line judgment, what's the logical sequence.

Adding AIMS to the `DECOMPOSE` task prompt means the system has explicit success criteria before it starts. Cheap to adopt; visible improvement to output quality.

### B2. SIFT method for the scanner agent

**S**top / **I**nvestigate the source / **F**ind better coverage / **T**race to original context. Four-step discipline before accepting any web source.

Relevant to our scanner agent in the motifs doc (`03-workflow-motifs.md` M1). The scanner currently judges relevance by title/snippet; SIFT adds: before passing a source through, lateral-read the site's reputation and check if the claim appears in higher-tier sources. Lightweight addition to the scanner's prompt.

### B3. Triangulation across three vectors

Every major claim verified across three independent vectors:
1. Source type diversity (empirical study + institutional standard + practitioner synthesis)
2. Time diversity (not all sources from same period)
3. Methodological diversity (quantitative + qualitative, or experimental + observational)

Our current source-agreement count is a 1D check ("how many sources support this?"). The skill's triangulation is a 3D check. "Three sources citing the same original study don't count as three independent sources."

Could be a structured field on claims — a triangulation score across the three axes, surfaced in the report.

### B4. The five named biases, each with a structural countermeasure

- Confirmation bias → ACH (A2)
- Satisficing → generate multiple hypotheses upfront
- Anchoring → Bayesian re-evaluation from scratch
- Availability → outside view / base rates; treat absent evidence as evidence
- Mirror imaging → red hat analysis (model actual incentives, not "what I would do")

The key pattern: **awareness is not a countermeasure.** Each bias requires an active structural intervention. Our replanner's prompt could enumerate these five checks. Our adversarial verifier's prompt could reference them.

### B5. "Dog that didn't bark" — missing evidence as evidence

From the availability-heuristic countermeasure: the **absence of expected evidence** should be weighted as evidence. If a hypothesis predicts we'd find X, and despite reasonable searching we didn't find X, that's a downweight signal.

This is a prompt addendum for the verifier and replanner. "What evidence would we expect to see if the current hypothesis is true? Have we searched for that and not found it? If so, that's a strike against the hypothesis."

---

## Tier C — Relevant but lower priority

### C1. Devil's Advocate Protocol (four-phase)

The skill has a specific four-phase structure for devil's advocacy:
1. Preparation + role-setting (authentic dissent, not performative)
2. Decomposition of the mainline + assumption audit
3. Synthesize the contrarian case
4. Present + adjudicate (does conclusion stand, require caveating, or change?)

More rigorous than our `ADVERSARIAL_CRITIQUE`. Could be an expanded pattern (`devils_advocate`) distinct from generic adversarial critique. Probably not needed for MVP — our adversarial mode is a lighter version of this and fits the time budget better.

### C2. Quality of Information check (reliability + credibility + corroboration)

Three-dimensional source evaluation. A source can be reliable (trustworthy origin) but carry low-credibility info (repeating an unverified rumor). Arguably already subsumed by our source-tier + verification system, but the distinction could inform prompt language.

---

## Tier D — Interesting but not directly applicable

- **Phase 3A / 3B / 3C research journey phases.** The skill's three-phase progression (exploratory → crystallization → application) is useful as an *internal* model of how our agent should feel different at different stages of a run. The research journey is currently a single loop in our design. We could add "research phase" as an explicit state on the overall run (exploratory → crystallization → synthesis) and gate certain tasks accordingly. Low priority — we have the task graph doing this implicitly.
- **NotebookLM-specific mechanics** (deep research ceilings, source import dedup guards, notebook splits). Not applicable since we're not building on NotebookLM.

---

## Recommended next actions

Ranked by adoption cost vs. impact:

1. **Adopt A4 (Analytic Pyramid report structure)** in TDD v3. Highest leverage, prompt-level change. Dramatically improves the report's trustworthiness without structural work.
2. **Adopt A5 (confidence language standards)** in TDD v3. Trivial change to §5.5, big UX improvement.
3. **Adopt A6 (refined preliminary-source policy)** in TDD v3. Small change to the tier rule table, meaningfully more defensible.
4. **Add A3 (completion gates as a pre-`WRITE_REPORT` check)** as a new task type. Structural but small.
5. **Pull A1 (5-round question ladder)** into the prompts for `DECOMPOSE`, `REPLAN`, `VERIFY_CLAIM`. Purely prompt discipline; no structural cost.
6. **Add A2 (ACH)** as a new orchestration pattern for ≥3-position contested sub-questions.
7. **Fold Tier B improvements** into prompt templates.
8. **Park Tier C for later iteration** if time allows.

If the call is "incorporate all of Tier A into TDD v3," that's probably a ~90 minute revision. If the call is "just the lowest-hanging fruit (A4, A5, A6)," that's ~30 minutes.

Over to you on which to pull.
