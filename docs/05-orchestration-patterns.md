# 05 — Orchestration Patterns

All five orchestration patterns live under `deep_research_agent.patterns`.
The interesting unit is the `OrchestrationPattern` enum attached to a
`QUESTION_SYNTHESIZE` task: the fat QS handler reads the pattern and
branches internally. Patterns are otherwise pure — they expose
prompts + task-emission helpers; they don't own execution.

## single_researcher

**File**: `patterns/single_researcher.py`
**Prompt**: `ANALYZER_SYSTEM` + `SYNTHESIZER_SYSTEM` (from
`executor/prompts.py`).

One neutral analyzer per source, one synthesizer per sub-question. The
default for every `QUESTION_SYNTHESIZE` spawned by `DECOMPOSE`.

### Task-emission helpers

- `emit_decompose(query, landscape_note_id, parent_task_id)` — creates
  the DECOMPOSE task at `generative / HIGH`, reading the landscape.
- `emit_question_synthesize(question, question_note_id, parent_task_id,
  write_report_task_id)` — creates a QS task, threading
  `write_report_task_id` through `input_refs` so the handler can graft
  VERIFY_CLAIM tasks onto the termination chain.
- `emit_write_report(question_note_ids, upstream_synth_task_ids,
  parent_task_id)` — creates the WRITE_REPORT task with dep edges on
  every upstream synthesis.

### In the handler

```python
framings = (Perspective(name="neutral", prompt_suffix=""),)
framing_agents = {"neutral": Agent(... system=ANALYZER_SYSTEM)}
```

One analyzer call per source. Claims are written to the source_note
with `perspective="neutral"` (synthesizer does not prepend framing
tags when only one framing is active).

### When it's used

- Every sub-question defaults to this pattern at decomposition time.
- Single-line-of-evidence `lookup` and `synthesis` classifications
  stay here unless the replanner escalates.

## maker_checker

**File**: `patterns/maker_checker.py`
**Prompt**: `VERIFIER_SYSTEM` (Round 3 falsification framing).

Not a QS-level pattern — it's a *layer* that runs after the synthesizer
produces claims. Emits one `VERIFY_CLAIM` task per selected claim, each
of which runs the verifier with a cross-family invariant-enforced model.

### Claim selection

`select_claims_to_verify(source_notes, already_selected=0)`:

1. Flatten all claims across all source_notes.
2. Require a non-empty `quote`.
3. Sort by `extractor_confidence` descending.
4. Cap at `MAX_CLAIMS_PER_SYNTHESIS = 2` per QS call and
   `MAX_CLAIMS_PER_RUN = 6` total.

### Task emission

```python
emit_verify_claim(claim, source_note, question, write_report_task_id,
                  parent_task_id)
# → Task(type=VERIFY_CLAIM, role=JUDGMENT, tier=MID,
#         pattern=MAKER_CHECKER, question_round=FALSIFICATION,
#         reads_notes=[source_note.id],
#         input_refs={"claim_id", "source_note_id", "question",
#                     "write_report_task_id"})
```

### Verifier handler

`handle_verify_claim` (`executor/handlers.py`):

1. Pull claim from source_note via `input_refs["claim_id"]`.
2. Build a **topic-keyword** verification query via
   `_build_verify_query` — content tokens from the claim (up to 8) +
   extra anchor tokens from the question (up to 4), stopwords
   dropped. Not a verbatim-quote query; the goal is pages *about*
   the topic so the verifier can judge corroboration or contradiction.
3. Brave search for independent sources (3, skipping the primary URL
   and near-duplicates via stem matching on the last two path segments
   — catches arxiv abs vs. pdf / html variants).
4. Fetch in parallel; on failure fall back to the Brave snippet.
5. Run the verifier LLM (cross-family-enforced) → verdict
   (`SUPPORTS` / `REFUTES` / `INCONCLUSIVE`) + rationale + disagreement
   notes.
6. Emit a `decision_note` (category `"verification"`) linked to the
   source_note via `verification_of`.
7. **Replace** the source_note with updated `claims` list — the
   matching `ClaimItem` gets `verification_status`,
   `verification_rationale`, `verification_note_id` set.

### Report integration

The WRITE_REPORT handler aggregates per-claim verdicts into the report
intro and carries verification rationales into its "Independent
verification rationales" section for the writer to surface.

## multi_perspective

**File**: `patterns/multi_perspective.py`
**Prompts**: `PERSPECTIVES` tuple — framing prompt suffixes appended
to `ANALYZER_SYSTEM`.

Three analyzers per source, each reading the same content with a
different framing:

| Name | Framing |
|------|---------|
| `neutral` | Extract claims the source actually makes; baseline. |
| `skeptic` | Extract claims but include quotes revealing unjustified leaps or thin reasoning. |
| `advocate` | Steelman: strongest version of the source's claims; most load-bearing passages. |

### In the handler

For each source, three analyzer calls run in parallel (across framings)
and across sources. Each emitted `ClaimItem` is tagged with
`perspective="neutral"` / `"skeptic"` / `"advocate"`.

The synthesizer receives per-claim `[<framing>]` prefixes so it can see
where framings agree on the same source and where they surface
different facets. The synthesis itself is still a single LLM call with
`SYNTHESIZER_SYSTEM`.

### When it's used

Triggered by the replanner via `EscalatePattern` when
`single_researcher`'s synthesis has surviving dissent that wasn't
engaged, or when a contested sub-question reads one-sided.

### Off-topic handling

A source is dropped only if **all** non-null framings agree it's
off-topic. Any framing finding something worth extracting keeps the
source.

## debate

**File**: `patterns/debate.py`
**Prompts**: `DEBATE_FRAMINGS` — `affirmative` / `negative` prompt
suffixes. The synthesizer is replaced with `JUDGE_SYSTEM`.

Two analyzers per source, each arguing a side:

| Name | Framing |
|------|---------|
| `affirmative` | Extract quotes supporting YES / true / the proposition. |
| `negative` | Extract quotes supporting NO / false / against. |

Both read the same sources, quote verbatim, and produce claims tagged
with their side. The judge prompt (same `SynthesizerOutput` shape as
the regular synthesizer) is told both sides drew from the same
sources, that quotes are trustworthy but which passages each side
picked is the interesting signal.

### When it's used

Replanner escalation for directly contested yes/no propositions where
`multi_perspective` already ran and dissent remained — the guidance
in the replanner prompt is that debate is "stronger medicine" picked
after multi_perspective is insufficient.

## ach — Analysis of Competing Hypotheses

**File**: `patterns/ach.py`
**Prompts**: `ACH_HYPOTHESIS_GEN_SYSTEM`, `ACH_CONSISTENCY_SYSTEM`,
`ACH_ADJUDICATION_SYSTEM`.

Three sequential phases per sub-question:

### Phase 1 — Hypothesis generation

One LLM call (on the QS task's own model — `generative / HIGH`) reads
the question + per-source claim digest and returns 2–5 mutually
exclusive hypotheses. Pydantic constrains to `min_length=2,
max_length=5`.

### Phase 2 — Per-hypothesis consistency

N parallel LLM calls (one per hypothesis) on the **judgment / MID**
model. Each call reads a single hypothesis + all M source digests and
returns one verdict per source:

- `consistent` — source corroborates the hypothesis.
- `inconsistent` — source contradicts it.
- `neutral` — source doesn't bear on it.

Batching is **per hypothesis, not per (hypothesis, source) pair**:
the natural reasoning unit is "this hypothesis against all evidence."
A per-cell call destroys the contextual judgment the model needs to
distinguish `inconsistent` from `neutral`.

### Phase 3 — Adjudication

One LLM call (back on `generative / HIGH`) reads the full N×M verdict
matrix. Applies **Heuer's rule**: the hypothesis with the fewest
inconsistencies is tentatively adopted. Ties broken by evidence
diversity (tiers, venues, framings) then by rationale confidence.

### Output

The ACH flow returns a `SynthesizerOutput` shaped like the other
patterns so the downstream note construction is unchanged, plus a list
of `hypothesis_note`s. Each hypothesis_note carries:

- `hypothesis_text`
- `inconsistency_score` — the count of `inconsistent` verdicts
- `supporting_evidence` / `inconsistent_evidence` / `neutral_evidence`
  — lists of source IDs
- `tentatively_adopted` — boolean

The synthesis_note gets `hypothesis_of_synthesis` links to every
hypothesis_note (so the note graph stays closed under traversal).

### Failure isolation

A hypothesis whose consistency-evaluation call fails is skipped (empty
verdicts). The adjudicator still sees the matrix and adjudicates over
what's available. If every hypothesis fails, the adjudicator still
runs on an empty matrix — the resulting synthesis is thin but the
task doesn't abandon.

### When it's used

Replanner escalation for questions with 3+ plausible distinct answers
where evidence needs structural disambiguation. The replanner prompt
flags this pattern specifically for questions where dissent is
taxonomic, not binary.

## Pattern interaction summary

| Trigger | Pattern | Model cost |
|---------|---------|------------|
| Default (decomposer) | `single_researcher` | 1 analyzer + 1 synthesizer per question |
| `maker_checker` layer | adds ≤ `MAX_CLAIMS_PER_SYNTHESIS` verifier calls per QS (≤ 6 per run) | `judgment/MID`, cross-family |
| Replanner: surviving dissent on `contested` | `multi_perspective` | 3× analyzer calls per source |
| Replanner: binary contested after multi_perspective | `debate` | 2× analyzer calls per source + judge synthesizer |
| Replanner: 3+ distinct hypotheses | `ach` | 1 gen + N consistency + 1 adjudication |

All of these patterns are executed inside `handle_question_synthesize`.
The handler branches on `ctx.task.pattern` to pick framings and
synthesis style; the scheduler sees one task per sub-question
regardless of which pattern ran.
