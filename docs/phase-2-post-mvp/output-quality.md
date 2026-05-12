# Output quality & agent methodology

Goal: improve the **empirical quality of the research the system
produces** — sharper decomposition, better-grounded claims, more
faithful disagreement surfacing, better-calibrated confidence. These
are orthogonal to cost/latency (`performance-improvements.md`) and to
deployment shape (`scaling-architecture.md`): the same pipeline,
producing *better* reports for the same spend.

Scope discipline: we are not redesigning the agent architecture. We
are identifying where the current prompts *ask* for discipline the
code doesn't *enforce*, and where methodological knobs are left on
the model's goodwill instead of being structural. For each item:
what slack exists, where it lives, and what change would close it.

---

## Where quality slack lives today

Ranked by "the prompt asks for X, but nothing in the code checks X."
These are all gaps where a model that's having an off-day, a
distracted run, or a prompt-injection-adjacent failure mode will
silently underperform — and we'll only notice by reading the report
by hand.

| # | Prompt asks for… | Code enforces… | Where the gap is |
|---|---|---|---|
| 1 | Researcher classifies each sub-question as `lookup` / `synthesis` / `contested` / `sparse` and puts the label in the question string | Nothing — the string flows through, but `QuestionMetadata.classification` stays at the default `SYNTHESIS` for every dispatch | `researcher.py:investigate_question` — the model is asked to tag the question in prose, but the structured `classification` field is not set from it |
| 2 | Every contested sub-question gets at least one `adversarial` dispatch before the researcher commits | Nothing — `answer_question` accepts any report at any time | `tools/notes.py:answer_question` — no pre-commit gate; the "pre-commit self-audit" is prose the model can skip |
| 3 | Every load-bearing claim traces to a source note (citations as `[source-abc123]`) | Nothing — `answer_question` does not parse the report for citations or validate they resolve | same |
| 4 | Single-source load-bearing claims are either verified or explicitly flagged | Nothing — analyst flags single-source claims in prose; the researcher is trusted to act on the flag | `analyst.py` prompt + researcher review rounds |
| 5 | Analyst claims are verbatim quotes from the source | Nothing — claims are free-text strings on the reading entry; no check that the quote appears in `note.content` | `tools/notes.py:update_source_after_reading` |
| 6 | Analyst's report covers "limitations" and "competing approaches" sections (slots c and d, "not optional") | Nothing — the analyst's answer is free-text markdown; absent sections go unnoticed | `analyst.py:ANALYST_SYSTEM` step 5 |
| 7 | Tier-4 sources are background, not load-bearing | Nothing — tier is recorded, but whether a Tier-4 source is anchoring a central claim is not checked | analyst prompt; tier is on source_note, claims don't carry provenance weight |
| 8 | `verify` mode uses different queries, venues, time windows than the explore it's checking | Nothing — the analyst on `verify` mode is just prompted differently; it may search identical queries | `analyst.py:MODE_FRAMING["verify"]` |
| 9 | `adversarial` mode steelmans the opposite, not re-summarizes both sides | Nothing — same shape; only the system prompt framing changes | `analyst.py:MODE_FRAMING["adversarial"]` |
| 10 | Final report matches the "Analytic Pyramid" 10-section structure (CONTEXT) | Nothing — the researcher commits free-text markdown | `researcher.py` + `answer_question` |
| 11 | Confidence is "calibrated" — `high` should be right more often than `low` | Nothing — no eval loop, no scoring of past confidence calls against ground truth | system-wide |

Items 1, 2, 3, 5, 6, 10 are the "structural invariants that only exist
in the prompt" class. Items 4, 7, 8, 9 are the "soft discipline" class.
Item 11 is the "we can't tell if the system is right" class.

---

## Recommended improvements

Grouped thematically. Most of these are small, but the *combination*
is what turns the researcher + analyst from "well-prompted" into
"well-instrumented."

### A. Move structural invariants from prompt to tool gates

The single highest-leverage direction. The researcher prompt is
~170 lines; a chunk of it is rules the code could enforce instead of
asking the model to remember. Move the rules; shrink the prompt.

#### A1. Make classification structured, not a string tag

**Today.** `researcher.py:investigate_question` asks the model to
write `"[contested] Is X the primary cause of Y?"` into the question
string. That label is for human readers; the `QuestionMetadata`
created inside the tool hardcodes
`classification=QuestionClassification.SYNTHESIS` every time.

**Change.** Add a required `classification` parameter to
`investigate_question`:
```python
async def investigate_question(
    ctx, question: str,
    classification: Literal["lookup", "synthesis", "contested", "sparse"],
    mode: Literal["explore", "verify", "adversarial"] = "explore",
):
```
Set `QuestionMetadata.classification` from it. Every later check
(item A2 below, reports, audits) reads the structured field instead
of parsing the question string.

**Why.** Makes the classification load-bearing data instead of flavor
text. Enables all the enforcement in A2.

---

#### A2. `answer_question` on the root becomes a gate, not a mailbox

**Today.** `tools/notes.py:answer_question` validates that the
confidence is one of three strings and the report is non-empty. That's
it. The researcher's "pre-commit self-audit" is prose.

**Change.** Pre-commit checks inside `answer_question` when the
`question_id` is the root question:

- For every sub-question with `classification=CONTESTED`: at least
  one `adversarial` dispatch must have completed on that sub-question
  or one of its descendants. If not: `ModelRetry("contested
  sub-question [question-xxx] has no adversarial dispatch — either
  dispatch one or downgrade the classification.")`
- Every `[source-abc123]` reference in the report must resolve to an
  existing source note. If not: `ModelRetry("report cites
  [source-bogus] which does not exist.")`
- `sources_cited` must be non-empty if the report contains any
  citations (redundant with above, but cheap).
- If `confidence="high"`, the report's cited sources must include at
  least two with `peer_reviewed=True` OR at least three distinct
  domains. Otherwise: downgrade to `medium` server-side and note in
  the returned string. (This implements CONTEXT's preliminary-anchor
  confidence cap structurally.)

**Why.** Turns the "pre-commit audit" from prose-discipline the model
may skip into a wall the model has to deal with. The ModelRetry
semantics of pydantic-ai mean the researcher gets a second chance to
dispatch the missing work or rewrite the claim — which is exactly
what the prompt currently asks it to notice on its own.

**Scope cut.** Don't go overboard. Each gate should correspond to a
rule already in the prompt; we are *enforcing existing rules*, not
adding new ones. If a gate would require a new piece of methodology
to pass, the prompt side of that rule isn't well-formed yet either.

---

#### A3. `update_source_after_reading` verifies quotes

**Today.** Claims are free-text strings attached to a reading entry.
CONTEXT + the analyst prompt say "every claim needs a verbatim quote,"
but the data model has a single `text` field per claim, not a
`(claim, quote)` pair, and nothing checks that the quote appears in
`note.content`.

**Change.** Two-step:

1. Split each claim into `(statement, quote, location_hint)` on the
   reading entry schema.
2. In `update_source_after_reading`: for each claim, check that
   `quote.strip()` appears as a substring in `source.content` (case-
   insensitive, whitespace-normalized). If not: `ModelRetry("claim
   quote does not appear in source content — paste a verbatim
   excerpt, not a paraphrase, or drop the claim.")`

**Why.** This is the single most important structural invariant in
the whole project ("quotes are what the evaluator uses to check
faithfulness," per the ablation-ideas appendix) and it is currently
enforced by prompt prose alone. Cheap to make structural.

**Risk.** Overzealous — a normalization difference (em-dash vs.
hyphen, curly quotes vs. straight) shouldn't fail a legitimate quote.
Implement a tolerant matcher (unicode-fold, normalize whitespace and
quotes). Keep the matcher shared across the codebase so "what counts
as a verbatim match" lives in one place.

---

#### A4. Required report slots on the analyst answer

**Today.** Analyst report is free-text markdown with "slots a-e"
described in the prompt. Slot c (limitations) and slot d (competing
approaches) are marked "not optional" — in prose.

**Change.** Make the analyst's `answer_question` schema require
`limitations: list[str]` and `competing_approaches: list[str]`
explicitly, distinct from `open_issues` (which already exists at the
researcher level). An empty list is a valid answer for both — but it
has to be an explicit `[]`, which forces the model to confront the
gap and state it, rather than silently omit the section.

**Why.** This is the "silence is ambiguous; stating the gap is a
finding" rule from the prompt, made structural.

**Risk.** Schema bloat. Keep the top-level schema lean — these two
fields are cheap and carry real semantic weight.

---

### B. Shrink and restructure the researcher system prompt

**Today.** `RESEARCHER_SYSTEM` is ~170 lines in one blob: identity,
context, tool reference, classification heuristics, mode selection,
5-check review pass, pre-commit audit, quality bar, judgment calls.
The 5-check pass and pre-commit audit together are ~30 lines of
detailed "do this every round" — a lot of discipline to execute
consistently at scale.

**Problem signals.**
- Long runs eventually drift on the 5-check pass, producing
  under-examined dispatch decisions in later rounds (observable in
  `run.log` by reading the researcher's pre-dispatch rationales
  across rounds).
- The "judgment calls" section asks the model to weigh a dispatch
  against stopping, which overlaps with the "pre-commit audit" and
  the "how to work" section — three places overlapping with each
  other is exactly where coherence drift shows up.

**Changes.**

#### B1. Extract the 5-check pass into an explicit tool call.

Replace the prose instruction with a `self_audit()` tool that the
researcher is required to call between dispatch rounds. The tool
returns a structured report computed deterministically from the note
graph:
```python
{
  "sufficiency": [{question_id, complete, confidence, flag}],
  "source_grounding": [{question_id, n_sources, single_source_claims}],
  "thin_spots": [sub_questions_open_but_not_investigated],
  "contradictions": [{question_a_id, question_b_id, claim_pair}],
  "direction": "on_track" | "pivot_recommended" (model fills this)
}
```
All fields except `direction` are computable from the graph; the model
only has to commit to a direction judgment after seeing the
deterministic findings. The tool's mere existence gates the rhythm:
it's called, its output is in the history, the next dispatch rationale
can reference specific entries in the audit.

**Why.** The 5-check pass is a classic "ask the model to run a
subroutine" pattern. Subroutines belong in code. The model's job is
the *judgment* the audit enables, not the audit itself.

#### B2. Extract mode-selection heuristics into tool affordances.

Today the researcher chooses `mode` from a free-form selection. Rules
like "after a contested explore lands, dispatch at least one
adversarial" belong in code (see A2). Once A2 is in, the mode-heuristic
block in the prompt shrinks to: "pick `explore` for new work;
`verify`/`adversarial` are suggested by the system when appropriate
and available as fallbacks."

#### B3. Separate "what the role is" from "how to execute."

Split `RESEARCHER_SYSTEM` into:
- `RESEARCHER_IDENTITY` — who you are, what your job is, what tools
  you have. ~30 lines, stable across every turn.
- `RESEARCHER_EXECUTION` — how to work, review rounds, pre-commit.
  Shorter after A1/A2/B1 land, and easier to iterate on without
  touching identity.
- `RESEARCHER_QUALITY_BAR` — the "every factual claim traces to a
  source" rules. Mostly enforced by A2/A3 after those land.

Each section is a named `_SYS_*` constant composed into the full
system prompt. Easier to A/B one section at a time. Easier to cache
each section independently (ties back to prompt caching in the
performance doc).

**Expected quality win.** Modest per-run — the current prompt *is*
reasonable. The larger win is compounding: every later prompt change
lands in a smaller surface, so the next improvement is cheaper and
safer.

---

### C. Verify/adversarial fidelity

The cross-family routing invariant (ADR 0008) is already enforced
structurally. The *behavioral* invariant — that `verify` actually
looks in different places than `explore` did — is not.

#### C1. Query + source divergence check on verify

**Today.** A `verify` dispatch is just an analyst run with a framing
preamble. Nothing prevents it from issuing identical search queries
and reading identical sources to the original `explore`.

**Change.** Two things:

1. When a `verify` dispatch starts, pass the original explore's scout
   queries and source URLs into its opening context (explicitly
   framed as "the explore searched these — you must diverge").
2. At `answer_question` time for the verify: require that the set of
   source URLs cited by the verify has Jaccard distance ≥ 0.5 from
   the explore's cited sources, OR that the verify explicitly
   flags in its report "could not find independent sources; verdict
   is INCONCL." Either is a valid outcome; silently reusing the same
   sources is not.

**Why.** Without this, `verify` can pass vacuously — it supports the
prior claim because it's reading the same paper. Ablation
Experiment 2 (`ablation-ideas.md`) will not produce meaningful signal
if this check isn't in place: you'd be measuring cross-family
paraphrase, not cross-family disagreement.

#### C2. Adversarial-mode structural check

**Today.** Adversarial mode asks the model to "LEAD with the
counter-case, not a summary of both sides." Enforcement: prose.

**Change.** Schema-level: the adversarial's report requires a
`counter_case: str` field (distinct from the `report` body), where
the counter-case is stated in 1–3 paragraphs up front. The full
`report` is downstream of that. Empty `counter_case` fails the
commit.

**Why.** "Steelman" vs. "balanced summary" is exactly the discipline
adversarial mode exists for; a structural slot makes the model
commit to the framing before writing the long-form report.

---

### D. Decomposition quality

The researcher's decomposition is currently a free-text list of
`investigate_question` calls. Quality is bounded by the model's
ability to hold the full decomposition in mind when making each call.

#### D1. Pre-dispatch decomposition commit

**Change.** Before the first round of `investigate_question` calls,
require a single `commit_decomposition(sub_questions=[...])` call
that registers the planned sub-question set as structured data:
```python
{
  "id": "...",  # stable within this run
  "question": "...",
  "classification": "lookup" | ...,
  "motivation_from_landscape": "...",  # points back to the brief
  "depends_on": ["sub-q-id"...],  # typed dependencies (CONTEXT)
}
```
`investigate_question` then dispatches against a registered
sub-question by id. Unregistered dispatches are allowed (emergent
follow-ups) but flagged in the audit as "ad-hoc — not in original
plan" so coverage vs. plan drift is visible.

**Why.** Makes decomposition a first-class artifact (it's already
implicit in what the researcher does; just give it shape). Enables
later deterministic coverage checks. Makes the decomposition
inspectable in the UI as a plan.

#### D2. Redundancy check across sub-questions

**Change.** After decomposition is committed, a deterministic
(embedding-free, TF-IDF + lexical overlap) check flags sub-questions
with high surface overlap. Doesn't block — just surfaces to the
researcher as a note on `self_audit`.

**Why.** Catches the "I asked the same thing three ways" failure
mode before three analysts burn budget answering the same question.

---

### E. Evaluation infrastructure

Nothing above can be tuned without a way to measure whether it
helped. This is the same thing `ablation-ideas.md` calls out under
"measurement infrastructure," generalized from the experiment level
to the production-quality level.

#### E1. Golden query set

A small (10–20 queries) set covering the regime matrix:
- `lookup` (single authoritative source exists)
- `synthesis` (multiple sources agree)
- `contested` (≥ 2 well-supported positions)
- `sparse` (thin corpus)
- `landscape-output` (taxonomies / maps rather than prose BLUFs)

Each query comes with a hand-built "what a good answer would cover"
rubric — not a single gold answer, but a checklist of facts, caveats,
disagreements, and limitations a rigorous report should engage with.

**Why.** Without a pinned set, "the system got better" is
unfalsifiable. With it, every prompt/tool change produces an
A/B-able delta.

#### E2. Rubric judge (also in ablation-ideas.md)

A Haiku-or-Sonnet pass over `report.md` that scores:
- Grounding (claims trace to sources)
- Coverage (rubric-checklist items engaged)
- Dissent-surfacing (real disagreements in the sources surface in
  the report, not dissolved into consensus)
- Calibration (confidence level matches source quality + convergence)
- Structure (matches Analytic Pyramid sections)

Output: 1–5 on each dimension + rationale. Rubric version pinned.

**Why.** Every improvement in this doc needs a dimension to show up
on. "Grounding" moves when A3 lands. "Coverage" moves when D1 lands.
"Dissent-surfacing" moves when C1 lands. Without the rubric, those
changes are faith.

#### E3. Confidence calibration tracking

**Change.** For the golden set, pair each query with its rubric-
scored correctness. Log every run's stated confidence against its
rubric score. Over N runs, compute: among reports that committed
`high`, what's the mean rubric score? Among `medium`? Among `low`?

**Why.** Calibration is cheap to measure but almost no one measures
it. "High should be right more often than low" is a one-line Pandas
check once E1 + E2 are in place. Miscalibration is a methodology
issue, not a model issue — it shows up in prompt design.

**Scope cut.** Don't go Bayesian. A simple mean-rubric-score per
confidence-level bucket is plenty of signal for the questions we'd
ask of it.

---

### F. Methodological hygiene (smaller, bundled)

Independent small improvements that don't fit the categories above.

- **F1. Provenance on every claim in the final report.** The
  researcher's final report embeds `[source-abc123]` citations — but
  synthesized claims that rest on a cross-analyst combination should
  also carry `[question-abc123]` provenance, so the reader can trace
  "this paragraph rests on analyst X's synthesis of Y." Schema
  change at the report-rendering layer.
- **F2. Explicit "what would change this answer" section.** The
  prompt asks for it implicitly ("Intelligence gaps: diagnostic vs.
  acknowledged"); make it a required section in the report template.
  Low cost, disproportionate quality signal for human readers.
- **F3. Disagreement persistence across rounds.** When a `verify`
  returns REFUTES or INCONCL, the researcher's next-round state
  should surface that loudly (not buried in `load_note` output).
  `get_research_state` could include a dedicated `open_disagreements`
  key.
- **F4. Analyst's own low-confidence flag propagates structurally.**
  Today an analyst flagging "single-source-only" is prose in the
  report body. Add a `flags: list[Literal["single_source", "thin_
  evidence", "tier4_anchored"]]` field on the analyst's answer;
  researcher's `get_research_state` surfaces these flags per
  sub-question directly.

Each of these is a 1–2 hour change; they compound to make the
report-level quality gates in A2 checkable without hand-reading
reports.

---

## Suggested order

1. **E1 + E2 + E3 — evaluation infrastructure first.** You cannot
   safely change the agent methodology without a way to detect
   regressions. The ablation-ideas.md doc already needs these; land
   them once and reuse.
2. **A1 (structured classification) + A3 (verbatim quote
   enforcement).** Smallest, most load-bearing. Both unlock later
   gates.
3. **A2 (`answer_question` as a gate).** High leverage. Depends on
   A1 + A3 being in place.
4. **A4 (required analyst slots).** Small. Lands naturally alongside
   A3.
5. **B1–B3 (researcher prompt restructure).** Start **after** A1–A4
   so the prompt shrinks *into* the new tool gates rather than
   duplicating them. This is where the researcher-prompt slack the
   user flagged actually gets cashed in.
6. **C1 + C2 (verify/adversarial fidelity).** Do before running the
   ablation Experiment 2 — otherwise the experiment's signal is
   noisy.
7. **D1 + D2 (decomposition as first-class artifact).** Biggest
   single methodology shift. Do once the gates beneath it are in
   place so coverage-vs-plan drift is checkable.
8. **F1–F4 (hygiene).** Drop in as opportunity allows; each is
   small and independent.

---

## Appendix — deliberately excluded

- **"Add a debate / ACH orchestration pattern."** CONTEXT describes
  these; the MVP collapses them into verify + adversarial. Reviving
  the full pattern zoo is an *expansion* of surface area, not a
  quality improvement, and should be driven by a specific query
  regime that verify/adversarial demonstrably fails on — not by the
  fact that they're in the design doc.
- **"Replace free-text markdown reports with a typed Analytic
  Pyramid schema."** Tempting. The cost is that agents now produce
  structured data, and the report is rendered from it — which
  dramatically constrains what the researcher can express. Worth
  doing *eventually*, but only after A1–A4 + E infrastructure lands,
  because otherwise you're both changing the output and losing the
  ability to tell whether it got better.
- **"Let the researcher spawn sub-researchers for deep sub-trees."**
  Recursion is architectural flexibility, not methodological
  improvement. Current single-level dispatch is adequate for the
  query regime; re-examine only if decomposition quality checks (D1)
  reveal sub-questions that are themselves decompose-worthy.
- **"Train a custom classifier for query regime (lookup / synthesis
  / contested / sparse)."** Charter is API-only. A Haiku call is
  fine. Model training would be a different project.
- **"Cross-run learning — remember which sources were useful for
  which topics."** CONTEXT: no cross-session memory. Hard invariant
  for privacy and caching reasoning. Keep it.
- **"Human-in-the-loop review at checkpoints."** Valuable but a
  product decision, not a methodology one. If added, it's a UI
  feature on top of the existing event bus (scaling doc step 4), not
  a change to the agent loop.
