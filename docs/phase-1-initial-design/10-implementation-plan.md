# Implementation Plan — TDD v4 → Working Prototype in Milestones

**Status:** starting point. Assumes scaffolding is in place (schemas, routing config, module stubs committed). Optimized for "minimum lovable prototype quickly," then layered rigor.

## Guiding principles

1. **Every milestone is end-to-end runnable.** No milestone adds half a feature. `dra research` works at every checkpoint.
2. **Cut from the tail, not the head.** The pipeline's final phase (report writing) is never deferred — we'd have nothing to look at. The middle phases (replanner, multi-pattern orchestration) are where the cuts happen for early milestones.
3. **Each milestone is one or two commits.** Atomic, reviewable.
4. **Defer LLM-tunable layers (tier classifier, confidence calibration) until the plumbing works.** Get real sources flowing through the graph first; polish judgment quality after.
5. **Real sources from milestone v0 onward.** No mocked retrieval. The whole point of the system is evidence grounding.

---

## Milestone map

| Milestone | Theme | Key additions | Cuts accepted |
|---|---|---|---|
| **v0** | single-query, single-pattern, single-source-backend | scheduler, executor, Serper, fetch/extract, single_researcher, simplified report | landscape, decomposition, replanner, gates, multi-pattern, tier classifier, triangulation, interactivity |
| **v1** | multi-subquestion | landscape survey, decomposition (AIMS + classification), parallel sub-questions | replanner, gates, non-trivial patterns |
| **v2** | cross-family verification | maker_checker, VERIFY_CLAIM, cross-family invariant enforcement, academic search (S2 + arXiv), tier classifier | multi-hypothesis patterns |
| **v3** | multi-hypothesis | multi_perspective, debate, ach, hypothesis notes, replanner + mutation budget | — |
| **v4** | completion rigor | VALIDATE_COMPLETION six gates, CHECK_TERMINATION_READY, triangulation score, confidence ladder wired to the report | — |
| **v5** | report + export polish | full 10-section Analytic Pyramid, decision notes surfaced, intelligence gaps, milestones for revision, export format | — |
| **v6** | ablation harness | multiple routing configs, run-to-run comparison, metrics | — |

---

## v0 — Minimum working prototype

**Ship criterion:** `dra research "<some query>"` produces `runs/<run_id>/report.md` containing at least three quoted claims from real web sources.

**In:**
- Scheduler + TaskGraph + NoteGraph (in-memory).
- Agent executor with PydanticAI + routing config resolution. No cross-family invariant enforcement yet (single pattern doesn't trigger VERIFY_CLAIM).
- Retrieval: Serper web search + `httpx` fetch + `trafilatura` HTML→markdown. Skip PDF path, skip academic sources, skip Unpaywall.
- Tools (agent-facing): `web_search`, `fetch_and_extract`, `create_note`, `load_note`.
- One orchestration pattern: `single_researcher`.
- `SEARCH → SCAN_SEARCH_RESULTS → FETCH_AND_EXTRACT → ANALYZE_SOURCE → QUESTION_SYNTHESIZE` as a literal task DAG.
- Simplified source tiering: static domain hints (`.edu`, `.gov`, known-journal → TIER_2; reject list for obvious junk → TIER_5; everything else → TIER_3). LLM tier classifier deferred.
- Simplified report writer: BLUF + evidence list + findings. Full 10-section Pyramid deferred.
- Export: one markdown file per note under `runs/<run_id>/notes/` + `report.md`.

**Out (explicit cuts):**
- No `LANDSCAPE_SURVEY` phase. The user query is treated as one sub-question.
- No `DECOMPOSE`. No sub-question notes.
- No replanner.
- No `CHECK_TERMINATION_READY` — termination is "every task DONE." (Same semantics for v0's task DAG; the separate audit matters once patterns spawn work dynamically.)
- No `VALIDATE_COMPLETION` gates.
- No `maker_checker`, `multi_perspective`, `debate`, `ach` patterns.
- No cross-family invariant (only one generative family used).
- No triangulation score (fed into the confidence formula as 0.0).
- No interactivity (L0 only).
- No preliminary-anchor cap triggering on web sources (tagged peer_reviewed=False, but v0 doesn't touch confidence enough for this to matter yet).

**Risk:** getting any LLM to reliably produce `ClaimItem`s with non-empty verbatim quotes. Mitigation: the PydanticAI `output_type` validator enforces `quote: min_length=1`; the analyzer prompt gets one clear instruction and the validator kicks the agent back on failure.

**Concrete commit sequence inside v0:**

| Commit | Content |
|---|---|
| v0.1 | `scheduler/` — TaskGraph, NoteGraph, Scheduler loop, Executor protocol, ID helpers. Stub executor verifies the loop runs. |
| v0.2 | `executor/` — PydanticAI agent wiring, routing resolution, per-task-type agent instances. |
| v0.3 | `retrieval/` — Serper client, fetch+extract via httpx+trafilatura, diskcache. |
| v0.4 | `tools/` — agent-facing tool functions bridging executor ↔ note graph ↔ retrieval. |
| v0.5 | `patterns/single_researcher.py` — emits the literal SEARCH→…→QUESTION_SYNTHESIZE DAG. |
| v0.6 | `tiering/` — reject list + static domain hints (no LLM classifier yet). |
| v0.7 | `phases/report.py` — simplified writer. `export/` — markdown-per-note bundle. |
| v0.8 | Wire `cli.py` to the Scheduler. First real run against a real query. |

---

## v1 — Multi-subquestion

**Ship criterion:** A query with two natural sub-parts produces distinct `question_note`s, each with its own source list and synthesis, and the report surfaces both.

**In:**
- `phases/landscape.py` — `LANDSCAPE_SURVEY` task + sub-task DAG. `landscape_note` emitted.
- `phases/decompose.py` — `DECOMPOSE` task: AIMS scoping, Round-2 starbursting, evidence-grounded classification, typed dependency emission.
- Staged waiting on typed dependencies — retrieval-phase tasks run in parallel regardless of deps; synthesis-phase tasks block in `BLOCKED_ON_SYNTHESIS_DEP` until upstream synthesis is DONE.
- Concurrent dispatch (asyncio.gather across ready tasks per tick).

**Out:**
- Still only `single_researcher` per sub-question. No verification, no multi-hypothesis.

---

## v2 — Cross-family verification

**Ship criterion:** For one load-bearing claim in a report, the claim text is tagged with a verification verdict (SUPPORTS / REFUTES / INCONCLUSIVE) and the verifying model was from a different family than the analyzer.

**In:**
- `patterns/maker_checker.py`.
- `VERIFY_CLAIM` task type wired into the executor; routing enforcement of the cross-family invariant (assert at model-selection time).
- Academic search: Semantic Scholar + arXiv direct. Unpaywall for OA PDF resolution.
- PDF path: markitdown. Size-first routing (ADR 0007): short content full; long content → `structured_content` + `load_source_section` tool.
- LLM tier classifier (cheap deterministic role): Tier 1..4 + rationale + classifier confidence.
- Peer-review flag via a static venue list.

---

## v3 — Multi-hypothesis

**Ship criterion:** A contested query runs `ach`, produces a consistency matrix with N hypotheses, reports the adopted hypothesis with its inconsistency score, and flags surviving dissent.

**In:**
- `patterns/multi_perspective.py`, `patterns/debate.py`, `patterns/ach.py` (with per-hypothesis batching per ADR 0004).
- Hypothesis notes.
- `replanner/` — bounded replanner with mutation budget (default 3) and cadence (every 10 completions). Cascade semantics for merge / split / abandon / add-edge (ADR 0009).

---

## v4 — Completion rigor

**Ship criterion:** The report distinguishes Moderate-confidence vs High-confidence claims per the standardized language, and passes six gates (or fails with remediation).

**In:**
- `CHECK_TERMINATION_READY` deterministic audit (ADR 0009).
- `VALIDATE_COMPLETION` with all six gates (G2, G4 on judgment family).
- Triangulation scoring (three vectors; load-bearing claim check).
- Confidence ladder rendered into the report.
- Preliminary-anchor cap triggered in real output.

---

## v5 — Report + export polish

**Ship criterion:** The full 10-section Analytic Pyramid report renders, with Finding / Insight / Recommendation strictly separated. Note graph exports cleanly.

**In:**
- Full `WRITE_REPORT` covering all 10 sections.
- Decision notes rolled up.
- Intelligence gaps categorized (diagnostically significant / acknowledged limitations / deferred sub-questions).
- Milestones for revision (falsifiability commitment).
- Export format decision made concretely and implemented.

---

## v6 — Ablation harness

**Ship criterion:** Running the same query under two different routing configs produces two comparable reports + a diff.

**In:**
- Multiple routing configs in `config/` (single-family baselines + diverse default + swap variant).
- Run metadata + cost tracking per run.
- A small comparison script that tabulates metrics across runs.

---

## Running notes (things worth knowing across milestones)

- **API-key path:** all LLM traffic goes through PydanticAI's provider abstraction. If the user wires OpenAI to the LiteLLM router, `OPENAI_BASE_URL` handles it; no code change.
- **Cache invalidation during development:** `runs/<run_id>/` is disposable; retrieval cache is keyed by `(tool, args_hash, day_bucket)` so re-running the same query on the same day reuses fetches.
- **When something hangs:** the scheduler's dispatch loop logs a "no ready tasks, not all terminal" deadlock error rather than spinning. Typically means a task's dep points at a task that was abandoned without cascading.
- **When the LLM returns malformed output:** PydanticAI's retry on validation error handles most cases. If an agent is drifting, its prompt goes in `executor/prompts/<task_type>.md` for isolated iteration.
