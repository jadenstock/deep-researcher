# 09 — Completion Gates

The report is only written after two audits. The first is
deterministic — no LLM, structural only. The second is an LLM-driven
six-gate audit. Both emit `decision_note`s that the WRITE_REPORT
handler threads into its context so the writer can surface issues in
the limitations section.

## The chain

```
  QS₁  QS₂  QS₃  VERIFY_CLAIM*  (all satisfied)
     │    │    │       │
     └────┴────┴───────┘
             │
             ▼
    CHECK_TERMINATION_READY       role=cheap_deterministic, tier=LOW, no LLM
             │
             ▼
      VALIDATE_COMPLETION          role=judgment, tier=HIGH, LLM
             │
             ▼
        WRITE_REPORT               role=generative, tier=HIGH, LLM
```

Dep edges are `produces_context_for`. The CHECK task's
`depends_on` lists every QS task at decomposition time; the QS
handlers then graft their spawned VERIFY_CLAIM tasks onto CHECK via
`DepEdgeAdd`, so the structural audit also waits for verifications.

Emission helpers live in `phases/termination.py`.

## `CHECK_TERMINATION_READY`

**Handler**: `executor/handlers.py::handle_check_termination_ready`
**Role / tier**: `cheap_deterministic / LOW`
**Cost**: zero LLM calls.

### Structural gates

From `_structural_termination_check`:

**Gate 1 — No pending work.** Not explicitly audited from the
handler (the `NoteReader` doesn't expose task state). Implicit
because the scheduler only fires `CHECK_TERMINATION_READY` after its
`depends_on` are satisfied. Post-hoc replanner spawns are caught by
the scheduler's `all_terminal()` exit check.

**Gate 2 — Every question_note is SYNTHESIZED.** Walks all
`question_note`s; any with `status != "SYNTHESIZED"` add a gap.

**Gate 3 — Every contested question has a disconfirmation pass.**
Contested questions are those with `classification == "contested"`.
The handler looks for a `synthesis_note` with
`pattern ∈ {multi_perspective, debate, ach}`. The current
implementation uses a coarse rule: if any heavy-pattern synthesis
exists anywhere in the graph, all contested questions are treated as
covered. Precise per-question attribution would require matching via
each task's `reads_notes`; the `synthesis → question` link in the
graph is via the `answers` edge but the check does not walk it.

### Output

A `decision_note`:

- `category="termination_readiness"`.
- `title="Termination readiness: PASS"` or `"... FAIL"`.
- Body lists every structural gap.

### Behavior on FAIL

The handler records the gaps in the decision_note, logs a warning,
and returns a passing `TaskResult`. The chain proceeds to
`VALIDATE_COMPLETION`. There is no remediation loop — no spawning of
new disconfirmation tasks, no `ESCALATED` status transition; the
structural audit is a record, not a gate.

## `VALIDATE_COMPLETION`

**Handler**: `executor/handlers.py::handle_validate_completion`
**Role / tier**: `judgment / HIGH`
**Prompt**: `VALIDATE_COMPLETION_SYSTEM`.

### Six gates (from the prompt)

1. **Evidence-grounding.** Every bottom-line claim in every synthesis
   should be traceable to at least one cited source.
2. **Disagreement surfacing.** Sources disagree → synthesis surfaces
   the disagreement, not averages it.
3. **No phantom citations.** Cited sources exist in the digest and
   carry the claim attributed.
4. **Contested-question probing.** `multi_perspective` / `debate` /
   `ach` syntheses show framings engaged, not just neutral restatement.
5. **Scope discipline.** Synthesis answers the sub-question, not a
   broadened version.
6. **Triangulation.** Load-bearing claims have multi-source support
   (or one exceptionally strong Tier 1 peer-reviewed source).

### Audit package

A compact dump keeping prompt size bounded:

```
## Synthesis <id> (pattern: ..., triangulation_score=..., distinct_tiers=...)
Bottom line: ...
<synthesis body>
Surviving dissent: ...

... per synthesis ...

## Evidence (source digests)
- <source_id>: <title> (tier N) — <url>
    claim: "<claim.text>"
    claim: "<claim.text>"          # up to 3 claims per source
    ...
                                     # source cap at 12
```

### Output

`ValidateCompletionOutput`:

```python
verdict: Literal["PASS", "FAIL", "PASS_WITH_WARNINGS"]
rationale: str
gate_notes: list[str]       # one line per gate: "<name>: <pass/concern/fail> — <reason>"
remediation: list[str]      # specific actions; "re-run debate on question X", not "do more research"
```

Verdict rules:

- `PASS` — all six cleared.
- `PASS_WITH_WARNINGS` — one or two minor issues; report can
  acknowledge in limitations.
- `FAIL` — load-bearing gate failed; report would be misleading.

### Behavior on FAIL

Like the structural check, the handler records the verdict in the
decision_note and returns a passing `TaskResult`. `WRITE_REPORT`
reads the decision_note and is expected to surface the failure in
the report's limitations section. There is no remediation loop.

### Audit failure handling

If the audit LLM call itself fails, the handler falls back to:

```python
ValidateCompletionOutput(
    verdict="PASS",
    rationale=f"audit LLM call failed: {type(exc).__name__}; passing with warning",
    gate_notes=[],
    remediation=[],
)
```

Principle: validator flakiness should not block the report. The
failure is recorded in the decision_note so it's visible in the graph.

### Output note

A `decision_note`:

- `category="completion_audit"`.
- `title="Completion audit: PASS"` / `"... FAIL"` / `"... PASS_WITH_WARNINGS"`.
- Body carries verdict, rationale, per-gate notes, and remediation
  suggestions.

## `WRITE_REPORT`

**Handler**: `executor/handlers.py::handle_write_report`
**Role / tier**: `generative / HIGH`
**Prompt**: `REPORT_SYSTEM`.

Walks the note graph once:

- All `question_note`s — title + adopted position.
- All `synthesis_note`s — bottom line, body, surviving dissent.
- All `source_note`s — title, URL, tier, per-claim quote +
  verification tag.
- All `verification` decision_notes.
- All `termination_readiness` + `completion_audit` decision_notes.

Computes verification verdict counts across all claims and prepends a
summary to the research-notes context:

```
## Verification summary
Cross-family verification results across all extracted claims:
SUPPORTS=3, REFUTES=0, INCONCLUSIVE=1, UNVERIFIED=5.
```

Then:

```python
report_agent = Agent(make_model(...), output_type=ReportOutput,
                    system_prompt=REPORT_SYSTEM)
r = await ctx.track(report_agent, "\n".join(parts))
```

Emits a `decision_note` tagged `category="final_report"` with the
markdown in `content`. The markdown exporter extracts that note's
content into `runs/<id>/report.md`.

### Current report shape

Per `REPORT_SYSTEM`:

1. `# Research Report`
2. `## Bottom Line Up Front` — 1-2 sentences
3. `## What We Found` — 2-4 paragraphs
4. `## Supporting Evidence` — bullet list of source titles + URLs +
   one-line claims
5. `## Disagreements / Limitations`
6. `## Sources` — numbered list

Total target: ≤ ~600 words unless the evidence demands more.

