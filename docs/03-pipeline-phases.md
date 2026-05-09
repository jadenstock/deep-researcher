# 03 — Pipeline Phases

The run moves through four phases. Each has one or more task types; the
scheduler holds the phases together via typed dependencies and the
write-lock serialization.

## Phase 1 — Landscape Survey

**Task type**: `LANDSCAPE_SURVEY`
**Handler**: `executor/handlers.py::handle_landscape_survey`
**Role / tier**: `generative` / `HIGH`
**Question round**: implicit — Round 1 framing (generate questions,
not answers).

### What it does

1. Brave web search for the raw query — **8 hits max**.
2. One batched LLM call over the concatenated snippets (titles + URLs +
   snippets) with the `LANDSCAPE_SYSTEM` prompt.
3. Emit exactly one `landscape_note` carrying `themes`, `positions`,
   `under_covered_areas`, and the `raw_query` for the replanner to
   read later.
4. Spawn exactly one `DECOMPOSE` task reading that note.

### Why it exists

Decomposition grounded in actual retrieved evidence beats decomposition
from LLM priors. The snippets tell the decomposer which sub-questions
are supported by visible evidence and which are imagined.

### What it produces

`LandscapeMetadata`:
- `themes`: named clusters visible in the snippets.
- `positions`: distinct stances when the topic is contested; single-element
  (or empty) when it is not.
- `under_covered_areas`: aspects of the query the snippets do not address.
- `tier_distribution`, `peer_review_fraction`, `methodology_distribution`:
  schema fields that are not populated (landscape uses snippets only,
  no fetches).

### Scope

The landscape survey operates on Brave snippets alone. It does not
fetch the underlying pages and does not produce `source_note`s; every
source_note in the run is produced later by the deep-research QS
handler.

### Failure behavior

- `0 hits`: `RuntimeError` — the landscape is the run's first contact
  with evidence; an empty landscape breaks the decomposer's ability
  to ground sub-questions.
- Missing Brave key in `config/local.toml`: `RuntimeError`.

## Phase 2 — Decompose

**Task type**: `DECOMPOSE`
**Handler**: `executor/handlers.py::handle_decompose`
**Role / tier**: `generative` / `HIGH`
**Question round**: `STRUCTURAL` (2).

### What it does

1. Reads the landscape_note (asserts `reads_notes[0]` is a landscape).
2. Calls the decomposer LLM with a compact rendering of the landscape
   (summary + discussion + themes + positions + under-covered areas).
3. Emits:
   - One `decision_note` tagged `category="aims_scoping"` — captures
     **A**udience / **I**ssue / **M**essage / **S**toryline.
   - One `question_note` per sub-question with its classification.
   - One `QUESTION_SYNTHESIZE` task per sub-question.
   - One `CHECK_TERMINATION_READY` task whose deps are every
     QUESTION_SYNTHESIZE.
   - One `VALIDATE_COMPLETION` task depending on CHECK.
   - One `WRITE_REPORT` task depending on VALIDATE.

### The AIMS decision note

The decomposer output carries an `AIMSSpec`:
`audience`, `issue`, `message`, `storyline`. This sets the frame for
the whole run — the writer reads it indirectly via the graph when
assembling the report. It is intentionally a decision_note, not a new
note type: AIMS is a scoping commitment, and decisions are where
scoping lives.

### Sub-question classification

Each sub-question is tagged `lookup` / `synthesis` / `contested` /
`sparse`. The replanner uses these classifications to escalate
patterns — contested questions are candidates for `multi_perspective`
/ `debate` / `ach` escalation (see [08-replanner.md](08-replanner.md)).

### Task-graph shape after Decompose

```
        [LANDSCAPE_SURVEY]
                 │
                 ▼
         [DECOMPOSE] ────────────┐
                 │               │ spawns
         ┌───────┼───────┐       │
         ▼       ▼       ▼       ▼
        [QS₁]  [QS₂]  [QS₃]   (question_notes,
         │       │       │     aims decision_note)
         └───────┼───────┘
                 ▼
     [CHECK_TERMINATION_READY]
                 │
                 ▼
       [VALIDATE_COMPLETION]
                 │
                 ▼
          [WRITE_REPORT]
```

The `CHECK` task's `depends_on` is rewritten to point at every QS
task's ID. The replanner and the QS handler can later graft additional
`VERIFY_CLAIM` edges onto `CHECK` so the structural audit waits for
verifications too — keeping the termination chain honest without
having to know up front how many verifications will exist.

## Phase 3 — Deep Research

This is the main loop. Each `QUESTION_SYNTHESIZE` runs in parallel
(retrieval-phase work doesn't block on deps). Inside one QS task, the
handler runs a **fat imperative pipeline**:

```
  Brave + Academic parallel search
          │
          ▼
  dedup by URL (academic hits first for richer metadata)
          │
          ▼
  lexical + recency rerank
          │
          ▼
  top N (FETCH_LIMIT = 8) fetched in parallel
          │
          ▼
  LLM tier classification (cheap_deterministic / LOW) in parallel
          │
          ▼
  source_notes created (with StructuredContent if long)
          │
          ▼
  per-source analyzer LLM calls in parallel
          │   (one per source × one per framing — PERSPECTIVES for
          │    multi_perspective, DEBATE_FRAMINGS for debate, else
          │    a single "neutral" framing)
          ▼
  merge analyzer output into claims on each source_note
          │
          ▼
  synthesizer LLM call (or ACH 3-phase flow, or judge prompt for debate)
          │
          ▼
  synthesis_note + updated question_note + (maker_checker) VERIFY_CLAIM tasks
```

The whole pipeline runs inside one handler invocation — one `Task`
per sub-question, not a DAG of SEARCH / FETCH / ANALYZE_SOURCE
sub-tasks. Internal parallelism uses `asyncio.gather`; the scheduler
sees one `TaskResult` come back per QS.

### Task-graph behavior during deep research

- QS tasks `depends_on` the `DECOMPOSE` task — the `produces_context_for`
  edge guarantees decomposition lands before QS starts.
- Inside QS, `asyncio.gather` parallelizes search, fetch, classify,
  analyze across sources. The scheduler treats the whole QS as one
  task; concurrency inside it does not interact with scheduler-level
  parallelism.
- `VERIFY_CLAIM` tasks spawned during QS are marked `retrieval_ignores=False,
  synthesis_waits=True` — they run as soon as their spawn is applied,
  because they have no upstream deps other than implicitly on the
  spawning QS.

### Patterns in use

See [05-orchestration-patterns.md](05-orchestration-patterns.md) for
the full per-pattern walk. Summary:

| `OrchestrationPattern` | What changes inside the QS handler |
|------------------------|------------------------------------|
| `SINGLE_RESEARCHER` | One "neutral" analyzer framing; synthesizer prompt |
| `MULTI_PERSPECTIVE` | Three framings (neutral/skeptic/advocate); synthesizer sees per-framing tags |
| `DEBATE` | Two framings (affirmative/negative); judge prompt replaces synthesizer |
| `ACH` | Three-phase: hypothesis generation → per-hypothesis consistency matrix → adjudication |
| `MAKER_CHECKER` | Not a QS-level pattern — a VERIFY_CLAIM-spawning step layered on any of the above |

### Replanner interleaving

After every `replan_cadence` task completions (default 10), the
scheduler pauses dispatch **between ticks** and runs the replanner.
Runs between ticks, not during — the graph snapshot handed to the
replanner is stable. The replanner can:

- Spawn new sub-questions (reading a recent landscape under-covered
  area, visible dissent, or a dead-angle signal).
- Abandon an unproductive sub-question (cascading through its tasks).
- Escalate a question to `multi_perspective` / `debate` / `ach`.

Each replanner cycle emits a `decision_note` tagged
`category="replan_cycle"` regardless of whether actions were taken.

Cycles are capped at `replan_budget` per run (default 3).

See [08-replanner.md](08-replanner.md).

## Phase 4 — Completion & Report

Three tasks chained in order:

1. **`CHECK_TERMINATION_READY`** — deterministic, no LLM.
   - Gate 1 (task-graph pendingness) is implicitly covered because
     the scheduler only fires this task once its deps (all QS and
     grafted VERIFY_CLAIMs) are satisfied; the `all_terminal()` exit
     check catches any after-the-fact replanner spawns.
   - Gate 2: every `question_note` has `status=SYNTHESIZED`.
   - Gate 3: every `contested` question has at least one heavy-pattern
     synthesis (`multi_perspective` / `debate` / `ach`).
   - Result: `decision_note` with `category="termination_readiness"`
     and `PASS` / `FAIL` verdict. A `FAIL` is logged and written to
     the decision_note but does not block the chain — the
     `VALIDATE_COMPLETION` audit is where LLM-level enforcement
     happens; the structural check is an orthogonal record.

2. **`VALIDATE_COMPLETION`** — LLM, `judgment` / `HIGH`.
   - Six-gate audit (per `VALIDATE_COMPLETION_SYSTEM` prompt):
     1. Evidence-grounding: every bottom-line claim traces to at least
        one cited source.
     2. Disagreement surfacing: disagreements are explicit, not
        averaged.
     3. No phantom citations: every cited source exists and carries
        the claim attributed to it.
     4. Contested-question probing: `multi_perspective` / `debate` /
        `ach` syntheses actually engage adversarial framings.
     5. Scope discipline: syntheses answer the sub-question, not a
        broadened version.
     6. Triangulation: load-bearing claims have multi-source support.
   - Result: `decision_note` with `category="completion_audit"`. On
     audit failure, falls back to `PASS` with a warning baked into
     rationale — validator flakiness should not block the report.

3. **`WRITE_REPORT`** — LLM, `generative` / `HIGH`.
   - Walks the note graph, assembles a compact "research notes" context
     (questions, syntheses, per-source claims with quotes, verification
     rationales, termination / completion notes), and asks the report
     writer LLM to produce markdown.
   - Output: one `decision_note` tagged `category="final_report"` with
     `content=<markdown>`. The markdown exporter extracts that note's
     `content` into `runs/<id>/report.md`.
   - The `REPORT_SYSTEM` prompt produces a 6-section markdown report:
     `Bottom Line Up Front`, `What We Found`, `Supporting Evidence`,
     `Disagreements / Limitations`, `Sources`. Target length is
     ≤ ~600 words unless the evidence demands more.

### Verification summary in the report intro

The writer handler computes per-verdict claim counts
(`SUPPORTS / REFUTES / INCONCLUSIVE / UNVERIFIED`) and prepends them to
the report context so the writer can surface aggregate verification
performance.

### Termination / completion audit summary

Both audit decision_notes are included in the context under
"Termination + completion audit" with an instruction to the writer to
surface any `FAIL` / `PASS_WITH_WARNINGS` verdicts in the report's
limitations section.

## Cross-phase guarantees

- **Landscape precedes decomposition.** Hard: the DECOMPOSE handler
  raises if `reads_notes[0]` is not a `landscape_note`.
- **AIMS precedes research.** The AIMS `decision_note` is created by
  DECOMPOSE alongside the `question_note`s; the AIMS is in the graph
  before any QS task runs, so the writer can always find it.
- **Termination chain precedes the report.** `CHECK → VALIDATE → REPORT`
  via `produces_context_for` edges. The report never writes without
  both audits landing.
- **Every synthesis has a question.** The synthesis_note carries an
  `answers` edge pointing at the question_note, built by the QS
  handler from `ctx.task.reads_notes[0]`.
- **Every claim has a quote.** Pydantic constraint (`quote: min_length=1`)
  is enforced at parse time of the LLM's structured output.
