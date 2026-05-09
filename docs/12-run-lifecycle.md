# 12 — Run Lifecycle

End-to-end trace of a single research run, assembling the pieces from
the preceding documents. Use this as an index when you need to
understand "what actually happens when I run `dra research '...'`."

## 0. Invocation

```bash
uv run dra research "does chain-of-thought reasoning generalize beyond toy tasks?" \
    --routing config/routing_diverse.yaml
```

Entry: `cli.py::main` → `_run_research(args)`.

1. Load `RoutingConfig` (YAML) and `LocalConfig` (TOML).
2. `setup_logfire(local)` — no-op if token unset.
3. `set_brave_min_interval(local.retrieval.brave_min_interval_s)`.
4. Mint `run_id = new_run_id()` — `run_<YYYYMMDD_HHMMSS>_<4hex>`.
5. Build `TokenUsageTracker`, `AgentExecutor`, and call
   `register_handlers(ex)`.
6. Build `TaskGraph`, `NoteGraph`.
7. Create the root task:

   ```python
   Task(
       id=new_task_id(),
       goal=args.query,
       type=TaskType.LANDSCAPE_SURVEY,
       role=RoleClass.GENERATIVE,
       tier=TaskTier.HIGH,
       success_criteria="produce a research report answering the query",
   )
   ```

8. Add it to the task graph.
9. Build the `Scheduler` with callbacks for the Rich progress spinner
   and a `_replanner` lambda that delegates to `run_replanner(...)`.
10. `await sched.run()`.

## 1. Phase 1 — Landscape Survey

### Tick 1

`TaskGraph.get_ready()` returns `[root_task]` (no deps). The scheduler
dispatches:

- `on_task_start(root_task)` → CLI spinner updates.
- `AgentExecutor.execute(root_task, notes)`:
  - `_forbidden_family(task, notes)` returns `None` (not VERIFY_CLAIM).
  - `select_model(routing, GENERATIVE, HIGH, LANDSCAPE_SURVEY, None)`
    → `"anthropic/claude-opus-4-7"`.
  - `handle_landscape_survey(ctx)`:
    1. `brave.search(query, count=8)` — serialized through the global
       throttle slot.
    2. One LLM call with `LANDSCAPE_SYSTEM` over the 8 snippets.
    3. Construct a `landscape_note` with themes, positions,
       under_covered_areas.
    4. `emit_decompose(query, landscape_id, root.id)`.
    5. Return `TaskResult(note_mutations=[create landscape_note],
       spawned_tasks=[decompose_task], verdict="...")`.

Scheduler acquires write lock, applies:
- `note_graph.add(landscape_note)`.
- `task_graph.add(decompose_task)` with `parent_id=root.id`.
- `root_task.status = DONE`, `completed_at = now`.

`on_task_done(root_task, result)` fires — CLI prints:
```
✓ LANDSCAPE_SURVEY <id> — landscape_note <nid>: 4 themes, 2 positions
```

## 2. Phase 2 — Decompose

### Tick 2

`get_ready()` returns `[decompose_task]`. Dispatched:

- `handle_decompose(ctx)`:
  1. Read `landscape_note` from `ctx.notes`.
  2. Call the decomposer LLM with the landscape summary + themes +
     positions + under-covered areas.
  3. AIMS payload → create `decision_note` (`aims_scoping`).
  4. For each sub-question in `out.sub_questions`:
     - Create `question_note` with classification.
     - `emit_question_synthesize(sq.title, q_note_id, decompose.id,
       write_report_task_id=check_task.id)` — threaded so the QS
       handler can graft VERIFY_CLAIMs onto the termination chain.
  5. Build the termination chain:
     - `check_task = emit_check_termination_ready(decompose.id, [])`
       — deps set *after* the loop to every QS task.
     - `validate_task = emit_validate_completion(decompose.id,
       check_task.id, question_note_ids)`.
     - `report = emit_write_report(question_note_ids, [], decompose.id)`
       with `depends_on = [DepEdge(validate_task.id, PRODUCES_CONTEXT_FOR)]`.
  6. Return the full batch as `TaskResult(note_mutations=[...],
     spawned_tasks=[...QS, check, validate, report...])`.

Scheduler applies everything under the lock. CLI prints:

```
✓ DECOMPOSE <id> — 3 sub-question(s) — Q1 | Q2 | Q3
```

## 3. Phase 3 — Deep Research

### Tick 3 (and beyond)

Multiple QS tasks are ready (no unsatisfied deps). They run in
parallel via `asyncio.gather`. Each runs the fat handler
`handle_question_synthesize(ctx)`.

Inside one QS:

1. `brave.search(question, count=5)` ∥ `search_academic(question,
   local=..., limit_per_source=3)` via `asyncio.gather`.
2. Dedup by URL (academic first).
3. `rerank(combined, question)` → top-8 as `hits`.
4. `asyncio.gather(*(fetch_and_extract(h.url) for h in hits))`.
5. Filter to usable (fetch present, markdown present).
6. Parallel `classify_source(...)` per usable hit on
   `cheap_deterministic / LOW` (Haiku).
7. Build `source_note`s with `SourceNoteMetadata` — including
   `StructuredContent` for long sources (≥ 8K tokens).
8. Pick framings:
   - Default: one `neutral` analyzer.
   - `pattern == MULTI_PERSPECTIVE`: `PERSPECTIVES` (3 framings).
   - `pattern == DEBATE`: `DEBATE_FRAMINGS` (2 framings).
9. `asyncio.gather(*(_analyze_one(note, framing) for note, framing in
   pairs))` on `generative / HIGH`. The model family is stamped onto
   every emitted `ClaimItem` as `analyzed_by_family`.
10. Group analyzer outputs by source_note; drop sources where every
    framing agrees it's off-topic; build enriched source_notes with
    claims.
11. **Synthesis branch**:
    - `pattern == ACH`: run `_run_ach_flow` — 3 phases (hypothesis
      gen → consistency matrix → adjudication), produce hypothesis_notes.
    - `pattern == DEBATE`: judge prompt `JUDGE_SYSTEM`.
    - Default / `MULTI_PERSPECTIVE`: synthesizer prompt
      `SYNTHESIZER_SYSTEM`.
12. Compute `triangulation_score` (count of claim-contributing
    sources) and `distinct_tiers`.
13. Build `synthesis_note` with `answers` link to question_note,
    `source_for_synthesis` links to every enriched source, and (ACH
    only) `hypothesis_of_synthesis` links.
14. Update the question_note: `status="SYNTHESIZED"`,
    `adopted_position=bluf`. This is a `replace` mutation.
15. **maker_checker layer**: `select_claims_to_verify(enriched)` —
    top 2 claims by extractor_confidence, capped at 6/run. For each:
    - `emit_verify_claim(...)` with `input_refs={claim_id,
      source_note_id, question, write_report_task_id}`.
    - `DepEdgeAdd(downstream=write_report_task_id, upstream=v_task.id)`
      — graft the new task onto the report's dep list.
16. Return `TaskResult` with all note mutations + spawned VERIFY_CLAIM
    tasks + dep-edge grafts.

Three QS tasks in parallel means a burst of ~24 analyzer calls + ~15
tier classifier calls + several search/fetch calls running
concurrently. Shared throttles (Brave, S2, arXiv, Unpaywall) serialize
where needed.

### VERIFY_CLAIM

Emitted by each QS. Dependencies are synthesis_waits only on whatever
the QS wrote, which is terminal by the time VERIFY sees the graph —
so VERIFY_CLAIMs run as soon as they're added.

Inside `handle_verify_claim`:

1. Look up `input_refs["claim_id"]` on the referenced source_note.
2. Build a topic-keyword query from the claim + question (NOT the
   verbatim quote — avoids zero-hit exact-phrase retrieval).
3. `brave.search(query, count=8)`.
4. Drop primary URL + near-duplicates; keep top 3.
5. `asyncio.gather(*(fetch_and_extract(h.url) for h in independent_hits))`
   — on failure, fall back to Brave snippet.
6. Call verifier LLM on `judgment / MID` — family selected by
   `select_model` with `forbidden_family=claim.analyzed_by_family`
   (cross-family invariant enforced).
7. Emit `decision_note` (`category="verification"`) with verdict +
   rationale + disagreement notes, linked to the source_note via
   `verification_of`.
8. Replace the source_note with `updated_claims` — the matching
   `ClaimItem` gets `verification_status`, `verification_rationale`,
   `verification_note_id` set.

### Replanner fires

After every 10 task completions (cadence), up to 3 times per run
(budget). Between ticks, `Scheduler._run_replan_cycle`:

1. `_format_graph_snapshot` — compact text view.
2. `run_replanner(task_graph, note_graph, routing, local, root.id,
   tracker)`:
   - LLM call on `judgment / MID` with `REPLAN_SYSTEM`.
   - Parse `ReplanDecision(overall_rationale, actions[<=3])`.
   - For each action: translate to a `TaskResult` via
     `_apply_spawn_subquestion` / `_apply_abandon_subquestion` /
     `_apply_escalate_pattern`.
   - Build the `decision_note` (`category="replan_cycle"`) with links
     to every newly-created note.
3. Scheduler applies each `TaskResult` under the write lock (only
   `create` mutations honored from the replanner path).
4. Server mode: synthetic task_started + task_done events so the UI
   shows a replanner card in the Running Agents panel.

## 4. Phase 4 — Completion & Report

Once all QS tasks and grafted VERIFY_CLAIMs are DONE:

### CHECK_TERMINATION_READY

`handle_check_termination_ready(ctx)` — no LLM. Structural check:

- Every `question_note.status == "SYNTHESIZED"`?
- Every contested question has at least one heavy-pattern synthesis?

Emits a `decision_note` (`category="termination_readiness"`) with
PASS / FAIL. On FAIL: log + pass through — VALIDATE picks it up.

### VALIDATE_COMPLETION

`handle_validate_completion(ctx)` — LLM on `judgment / HIGH` with
`VALIDATE_COMPLETION_SYSTEM`. Six-gate audit. Emits a `decision_note`
(`category="completion_audit"`). On audit-call failure: falls back to
PASS with a warning baked into rationale.

### WRITE_REPORT

`handle_write_report(ctx)` — walks the note graph, builds a "research
notes" context with verification summary, per-question synthesis +
disagreements + per-source claims with quotes + verification notes +
termination/completion notes. LLM call on `generative / HIGH` with
`REPORT_SYSTEM`. Emits a `decision_note` (`category="final_report"`)
containing the markdown.

## 5. Export and termination

`Scheduler.run()` returns because `all_terminal()` is true.

Back in `cli._run_research`:

1. `export_run(run_dir, ng, tg)`:
   - One markdown file per note under `runs/<id>/notes/`.
   - If a `final_report` decision_note exists, write its content to
     `runs/<id>/report.md`.
   - Dump task graph to `runs/<id>/tasks.json`.
2. `tracker.save_json(run_dir / "token_usage.json")`.
3. `logger.info(tracker.format_table())`.
4. Print summary to the console (task count, note count, report path).

## Failure paths

| Failure | Behavior |
|---------|----------|
| Landscape returns 0 hits | `RuntimeError` → scheduler abandons root task → no downstream; run fails but exports empty state. |
| Missing Brave key | `RuntimeError` up front from landscape or QS handler. |
| Cross-family violation | `CrossFamilyViolation` at `select_model` → handler raises → task abandoned → other tasks proceed. |
| LLM timeout in QS | Handler's `ctx.track` raises → task abandoned → downstream QS unaffected. |
| All sources fail to fetch on a QS | `RuntimeError("no usable sources after ...")` → that QS abandoned. |
| Validate audit LLM fails | Handler catches internally; falls back to `PASS` with warning recorded. |
| Replanner LLM fails | Cycle skipped, budget not decremented, warning logged. |
| Scheduler deadlock | `SchedulerDeadlock` raised → CLI catches, still exports, returns exit code 1. |

In every case, the `cli` and `runner` top-level try blocks guarantee:
- Token usage is saved.
- Export is attempted.
- Per-run log is closed cleanly.

## Artifact tree at end of run

```
runs/run_20260508_123015_a7c3/
  report.md                               # the research report
  tasks.json                              # full task graph
  token_usage.json                        # per-model token counts
  run.log                                 # DEBUG-level server log (server only)
  notes/
    landscape_xxxxxxxxx.md                # raw query, themes, positions
    decision_xxxxxxxxx.md                 # AIMS scoping
    question_xxxxxxxxx.md                 # sub-question + classification + adopted position
    source_xxxxxxxxx.md                   # fetched source + tier + claims + quotes
    synthesis_xxxxxxxxx.md                # per-question synthesis + pattern + dissent
    decision_xxxxxxxxx.md                 # verification, replan, completion audits
    hypothesis_xxxxxxxxx.md               # (ACH runs) one per hypothesis
    decision_xxxxxxxxx.md                 # final_report
```

The notes vault is intentionally plain markdown — no tool-specific
syntax (no wikilinks, no YAML frontmatter). The graph itself is the
load-bearing structure; the exporter is one view of it.
