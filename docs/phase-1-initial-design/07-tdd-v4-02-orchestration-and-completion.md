# Deep Research Agent — TDD v4 — Orchestration and Completion

**Covers:** §5.9 Orchestration Patterns, §5.10 Pattern Selection at Runtime, §5.11 Verification, §5.12 Replanner, §5.13 User Gateway, §5.14 Stopping + Termination Readiness + Completion Gates.

See `07-tdd-v4-00-overview.md` for architecture diagram, data model, ADR index, and principles.

---

## 5.9 Orchestration Patterns

The closed set of patterns. Each is an abstract sub-task DAG instantiated by a pattern-invoking HIGH-tier task. General structure: trigger, phases, question-round framing, note-graph I/O, failure modes, cost envelope.

### 5.9.1 `single_researcher`

**Purpose.** Default for `lookup` and `synthesis` sub-questions. Runs the scanner → analyzer → question-synthesis flow for one question. Also the inner loop of `multi_perspective`.

**Trigger.** Assigned at decomposition for `lookup` / `synthesis` sub-questions.

**Phases (sub-task DAG):**

```
                   ┌─── SEARCH (web) ─────────┐
                   ├─── SEARCH (academic) ────┤
single_researcher──┤                          ├──▶ SCAN_SEARCH_RESULTS
                   └─── SEARCH (arxiv direct) ┘         │ filtered candidates
                                                       │
                                                       ▼
                                       ┌─── FETCH_AND_EXTRACT (fan-out) ───┐
                                       │   parallel per candidate           │
                                       │   (deterministic: reject, size-    │
                                       │    route, tier-classify, cache)    │
                                       └──────────────┬──────────────────────┘
                                                      │ source_notes (stubs+tier+structured_content)
                                                      ▼
                                       ┌─── ANALYZE_SOURCE (fan-out) ──────┐
                                       │   parallel per source              │
                                       │   pulls sections via              │
                                       │   load_source_section as needed   │
                                       └──────────────┬──────────────────────┘
                                                      │ source_notes (full: claims + evaluation)
                                                      ▼
                                            QUESTION_SYNTHESIZE
                                       (single batched task, ADR 0002 —
                                        reads all source_notes for the
                                        sub-question, emits one synthesis
                                        and updates the question_note)
                                                      │
                                                      ▼
                                              question_note updated
```

**Key change from v3.** Per ADR 0002, cross-source reasoning happens in `QUESTION_SYNTHESIZE` (renamed from v3's `UPDATE_QUESTION_NOTE`). `ANALYZE_SOURCE` stays per-source (each paper is one reasoning unit); synthesis is not decomposed into N per-source-to-question updates.

**Landscape reuse.** `SEARCH` and `FETCH_AND_EXTRACT` hit the fetch-cache populated by the landscape survey; stub source_notes from the survey are reused and upgraded (not re-fetched).

**Question-round framing:**
- `SCAN_SEARCH_RESULTS` — Round 2 (decompose the batch: which hits address which sub-component?).
- `ANALYZE_SOURCE` — Round 2 (decompose the paper into its claims, methodology, limitations).
- `QUESTION_SYNTHESIZE` — Round 2 (organize accumulated evidence into position candidates) + Round 5 check (is the saturation claim genuine or anchoring?).

**Note-graph I/O:** Reads `question_note`, `landscape_note` (for context). Writes full `source_note`s, updates `question_note` with support/refute links and adopted position.

**Failure modes:**
- **Scanner over-filters** — returns < 3 candidates. Mitigation: widen the query (Round 1 starbursting) and retry once.
- **Scanner under-filters** — passes > 10. Mitigation: scanner prompt enforces "max 10 candidates per scan batch" with ranking.
- **Analyzer misreads source** — claims unsupported by quotes. Mitigation: `extractor_confidence`; low-confidence claims don't propagate without verification.

**Cost envelope.** LOW × several + MID × several + 1 × MID/HIGH for the synthesis. Cheapest path.

---

### 5.9.2 `maker_checker`

**Purpose.** Maker proposes claims; checker independently tests them. Used on top of `single_researcher` for `synthesis` / `contested` / `sparse` sub-questions.

**Trigger.** Wraps `single_researcher`'s output. Runs after `QUESTION_SYNTHESIZE`.

**Phases:**

```
single_researcher output (claims in source_notes + question_note)
                     │
                     ▼
         for each claim where verification is triggered:
         ┌─────────────────────────────────────────────┐
         │ VERIFY_CLAIM (Round 3 framing)               │
         │  role: judgment                              │
         │  model family: ≠ the ANALYZE_SOURCE family   │
         │  · re-phrase query (avoid same retrieval)    │
         │  · fetch independent sources                 │
         │  · verdict: SUPPORTS | REFUTES | INCONCL     │
         └────────────┬────────────────────────────────┘
                      │
                      ▼
         update claim.verification_status in source_note
```

**Which claims get verified?**
- Any claim whose supporting sources' max tier < TIER_2.
- Any claim on a `contested` or `sparse` sub-question.
- Any claim explicitly marked load-bearing by the replanner or by `VALIDATE_COMPLETION`.

**Role routing invariant (ADR 0008).** `VERIFY_CLAIM` runs with the judgment role class; the executor enforces `model.family ≠ ANALYZE_SOURCE.model.family` for the specific source whose claim is being checked.

**Question-round framing:** Round 3 falsification. Prompt includes a required instruction to re-phrase the query and deliberately seek sources the maker would not have used (different venue, different search terms, different time window).

**Note-graph I/O:** Reads the claim's source_note. May create new source_notes for the verifier's retrievals. Updates `verification_status`.

**Failure modes:**
- **Verifier trivially confirms** via the same retrieval path. Mitigation: the Round 3 prompt and the cross-family routing invariant together force independent retrieval.
- **Verifier false-refutes.** Mitigation: `REFUTES` requires ≥ 2 refuting sources OR 1 refuting Tier-1 source.

**Cost envelope.** MID per claim verified (on the judgment family). Scales with claim count; bounded by the filter above.

---

### 5.9.3 `multi_perspective`

**Purpose.** Generate search queries from multiple stakeholder framings to avoid one-sided evidence collection. For `contested` and `sparse` sub-questions.

**Trigger.** Assigned at decomposition for `contested` or `sparse` sub-questions.

**Phases:**

```
                      ┌─ SYNTHESIZE (Round 1 starbursting)
                      │     "enumerate the stakeholder perspectives
                      │      from which this sub-question could be asked.
                      │      Return N perspectives, each with 2-3
                      │      representative search queries."
                      │        │
                      │        ▼ list of (perspective, queries)
                      │
multi_perspective ────┤        ┌─ single_researcher (perspective 1) ─┐
                      │        ├─ single_researcher (perspective 2) ─┤
                      │        ├─ ...                                ├──▶ merge
                      │        └─ single_researcher (perspective N) ─┘
                      │                        (parallel)                │
                      │                                                  ▼
                      │                                    SYNTHESIZE (Round 2)
                      │                                    combine into question_note
                      │                                    with positions surfaced
                      │                                    and labeled by perspective
```

**Perspective count.** N = 3 for `contested`; N = 2-3 for `sparse`.

**Question-round framing:** Perspective generation — Round 1. Per-perspective research — Round 2 (inner `single_researcher`). Final merge — Round 2.

**Note-graph I/O:** Creates a `synthesis_note` per sub-question, linking to source_notes from each perspective. Updates `question_note` with per-perspective positions and evidence counts.

**Failure modes:**
- **Perspectives too similar.** Mitigation: prompt requires "materially different stakeholders" (theoretical / empirical / practitioner / critical).
- **One perspective dominates.** That's a finding; the merge preserves the asymmetry rather than averaging.

**Cost envelope.** N × `single_researcher` + one synthesis pass. Most expensive non-ACH pattern.

---

### 5.9.4 `debate`

**Purpose.** Force a structured adversarial dialectic when exactly **two** contradictory positions exist with moderate evidence on both sides. Cheaper than ACH; reserved for clear binary oppositions.

**Trigger.** Runtime-spawned by `REPLAN` when the replanner detects two `question_note` claims with opposite positions and at least moderate evidence on both sides. Pre-check: no plausible third position — else escalate to `ach`.

**Phases:**

```
                Position A (with evidence refs)
                Position B (with evidence refs)
                                │
                                ▼
               ┌── ADVERSARIAL_CRITIQUE (Position A, judgment family)
               │     Round 3: "given all sources, what is the strongest
               │     case AGAINST Position A?"
               │
               ├── ADVERSARIAL_CRITIQUE (Position B, judgment family)
               │     Same but for B.
               │        │ (parallel)
               │        ▼
debate ────────┤   SYNTHESIZE (Round 2 + Round 4 premortem framing)
               │     "weigh strongest cases for and against each
               │      position. If we adopt A and it's wrong in 6 months,
               │      what did we miss? Same for B. Tentatively adopt
               │      the position with the lowest inconsistency score."
               │        │
               │        ▼
               │   synthesis_note:
               │     · adopted position (with rationale)
               │     · surviving dissent
               │     · what would overturn the decision
```

**Why not just "judge"?** The parallel `ADVERSARIAL_CRITIQUE` tasks run with adversarial framing on each side *before* the synthesizer sees them, so neither side is strawmanned.

**Role routing.** Both `ADVERSARIAL_CRITIQUE` tasks run on the judgment family (ADR 0008). The final `SYNTHESIZE` runs on the generative family (HIGH tier).

**Question-round framing:** Round 3 (adversarial critiques) + Round 4 (synthesis premortem).

**Failure modes:**
- **Binary trap.** Real answer is "both wrong, position C is correct." Mitigation: pre-check for a plausible third position → escalate to `ach` if present.
- **Judge siding by weight-of-evidence when quality matters more.** Mitigation: synthesis prompt scores by tier-weighted inconsistency, not raw source count.

**Cost envelope.** 2 × MID (judgment) + 1 × HIGH (generative).

---

### 5.9.5 `ach` — Analysis of Competing Hypotheses (ADR 0004 batching)

**Purpose.** When **three or more** plausible positions exist (or could), avoid the binary trap by formally enumerating and scoring all hypotheses.

**Trigger.** Assigned at decomposition for `contested` sub-questions where the **landscape survey** (not priors) surfaced ≥ 3 positions. Or runtime-spawned by the replanner when `debate`'s pre-check flags a third plausible position.

**Phases (revised per ADR 0004: per-hypothesis batching):**

```
                  ┌── SYNTHESIZE (Round 1 starbursting)
                  │     "list ALL plausible, mutually exclusive hypotheses.
                  │      Err toward over-enumeration. Include outliers."
                  │         │
                  │         ▼ hypothesis_notes (N entries)
                  │
                  │   PER-HYPOTHESIS BATCHING (ADR 0004 — N tasks, not N×M)
                  ├── for each hypothesis h_i:
                  │    ┌──────────────────────────────────────────────────┐
                  │    │ ANALYZE_CONSISTENCY (MID, judgment family)        │
                  │    │  input:  hypothesis h_i + M source_note digests   │
                  │    │          (title, tier, claims-with-quotes, one-   │
                  │    │           line landscape contribution)            │
ach ──────────────┤    │  output: M verdicts, each                        │
                  │    │    {source_id, verdict: C|I|N, rationale}         │
                  │    │                                                   │
                  │    │  degrade path: if M > 25, split into two passes   │
                  │    │    by source subset; if still won't fit, fall     │
                  │    │    back to per-pair for this invocation only      │
                  │    └────────────────────┬─────────────────────────────┘
                  │                         │
                  │                         ▼
                  │     (N MID calls total; not N × M)
                  │                         │
                  │                         ▼ full consistency matrix
                  │     ┌─────────────────────────────────────────────┐
                  │     │ SYNTHESIZE (HIGH, generative)               │
                  │     │  Round 2 + Round 5 metacognitive            │
                  │     │   · inconsistency_score per hypothesis =    │
                  │     │     count(inconsistent) weighted by tier    │
                  │     │   · normalize by total evaluated            │
                  │     │   · adopt = hypothesis w/ LOWEST inconsistency│
                  │     │   · mark under-tested hypotheses (< 3 evals)│
                  │     │   · flag surviving dissent                  │
                  │     │   · identify linchpin evidence              │
                  │     └────────────┬────────────────────────────────┘
                  │                  ▼
                  │    write synthesis_note + update question_note
```

**Why lowest-inconsistency, not highest-support?** ACH accepts the hypothesis the most evidence is *least inconsistent* with. Resists confirmation bias: many weak supporting pieces don't outweigh a few strong contradictory ones.

**Hypothesis note.** `hypothesis_note.metadata = {hypothesis_text, inconsistency_score, supporting_evidence: [SourceID], inconsistent_evidence: [SourceID], neutral_evidence: [SourceID], tentatively_adopted: bool}`.

**Role routing.** `ANALYZE_CONSISTENCY` is judgment role class (ADR 0008). Final `SYNTHESIZE` is generative.

**Cost envelope (ADR 0004).** N MID (judgment) + 1 HIGH (generative). For realistic N=4, M=15: 4 + 1 = 5 significant calls. Two ACH invocations per run ≈ 10 significant calls. Tractable for demo scale.

**Question-round framing:**
- Hypothesis enumeration — Round 1 (over-enumerate).
- Consistency analysis — Round 2 per evidence-hypothesis pair (but batched per hypothesis).
- Adjudication — Round 5 metacognitive (audit scoring, correlation-vs-causation).

**Note-graph I/O:** Creates N `hypothesis_note`s + a `synthesis_note`. Links each hypothesis to supporting / inconsistent / neutral evidence. Updates `question_note`'s adopted position with a pointer to the consistency matrix.

**Failure modes:**
- **Over-enumeration collapses to the same hypothesis.** Mitigation: synthesizer deduplicates semantically equivalent hypotheses before scoring.
- **Evidence-coverage asymmetry.** Mitigation: normalized inconsistency score (inconsistency count / total evaluated); hypotheses with < 3 evaluated evidence pieces flagged "under-tested" rather than "low-inconsistency."
- **Tie-breaking.** Near-identical scores → synthesis_note reports both; the question is marked `CONTESTED` in the final report rather than forced.
- **Context-window hit on large M.** Mitigation: degrade path (split by source subset; fallback to per-pair) specified in ADR 0004, logged in a `decision_note`.

---

## 5.10 Pattern selection at runtime

Pattern selection happens at two points:

1. **At decomposition** — classification-driven default, grounded in the landscape_note (ADR 0001).
2. **At runtime by the replanner or a mid-tier agent** — when the note graph reveals something the landscape survey missed.

### Runtime escalation rules

- `single_researcher` output where the question_note contains claims with contradictory positions from different source_notes → spawn `debate` (2 positions) or `ach` (3+ positions).
- `maker_checker` output where the verifier introduces a third plausible position not surfaced originally → escalate to `ach`.
- `multi_perspective` output where perspectives converge → re-classify the sub-question from `contested` to `synthesis`; skip further verification.
- `debate` output where the synthesis says "both positions have surviving dissent and the adopted one is marginal" → escalate to `ach`.

These rules live in the `REPLAN` task's prompt; they read the note graph and recent completed tasks, emitting pattern-invoking tasks as needed (subject to the mutation budget — §5.12).

---

## 5.11 Verification

`VERIFY_CLAIM` and `ADVERSARIAL_CRITIQUE` always use Round 3 framing AND the judgment role class (ADR 0008). Their system prompts include a canned Round 3 block: "find the strongest evidence that would *disprove* this claim; use deliberately different queries; prefer sources from different venues / authors / time windows than the original."

The judgment-role routing makes the "deliberately different" instruction structural, not just a prompt hope: the verifier is a different model family with different training priors.

---

## 5.12 Replanner (bounded per ADR 0009)

`REPLAN` runs periodically (cadence configurable; default every 10 task completions).

### Inputs

Full note graph (progressive-disclosure views) + current task graph + recent completed tasks + current scope-creep counters.

### Prompt structure (Rounds 3, 4, 5 + new blocks)

- **Round 3 (falsification):** "For each question_note with an adopted position, what evidence would disprove it? Has that evidence been searched for?"
- **Round 4 (premortem):** "Imagine we ship this report tomorrow and it turns out to be wrong in 6 months. What's the most likely reason? Which sub-question is the weakest?"
- **Round 5 (metacognitive):** "What sub-questions are we saturating vs. where are there diagnostically-significant gaps? Is the current task graph aligned with the original AIMS?"
- **Typed-dependency detection block (ADR 0006):** "Has any sub-question revealed a structural dependency not captured at decomposition? Signals: A's synthesis_note contains claims structurally identical to B's framing; B's retrieved sources directly reference A's resolved position; two sub-questions' syntheses converge on the same tentative position."
- **Bias countermeasure scan** (see §5.16 in doc 03): scans note graph for signs of each of the five named biases; emits targeted tasks if found.

### Mutation budget (ADR 0009)

Per-replan-cycle cap: `replanner_mutation_budget` (config, default ≈ 3).

- If the replanner wants to emit more, it emits the top-N by priority and records the rest under "deferred to next cycle" in the cycle's `decision_note`.
- Priority ordering (default): mutations that unblock other tasks first, abandon-stalled-work second, cosmetic merges last.

### Outputs

- Task graph mutations (add / edit / abandon / add-edge / merge / split), subject to budget.
- `decision_note` recording rationale, deferred mutations, cascade-semantics invocations.
- `SCOPE_ESCALATION` if sub-question-level scope-creep fires (§5.14).

---

## 5.13 User Gateway

L0–L5 interactivity, async-preferred, default fallback mandatory. MVP supports L0 and L3 concretely; others stubbed.

New for v4: the scope-creep escalation carries a **structured payload** (ADR 0005):

- Set of currently open sub-questions, grouped by depth: well-researched / partially / barely started.
- Proposed narrow option: "stop adding new sub-questions; close out existing ones; report covers A, B, C; D and E surface as `open_question_notes`."
- Proposed broaden option: "continue; next N sub-questions the replanner is about to spawn are listed here."
- Default recommendation: narrow.

Default fallback on non-response (L0 or L3 timeout): **narrow**. Finish what's open; surface the rest as follow-ups.

Also new: at L3+, the landscape survey can consult the user *after* the survey and *before* decomposition when a material branching is surfaced (ADR 0001 — survey-informed escalation has concrete evidence in hand, not priors).

---

## 5.14 Stopping + Termination Readiness + Completion Gates

Termination is now a three-step process: stopping signal → deterministic readiness check → judgment gates.

### Stopping signals

1. **Replanner emits no mutations for a cycle.** → trigger `CHECK_TERMINATION_READY`.
2. **Sub-question-level scope-creep** (ADR 0005): over K consecutive replan cycles (default K=2), `new_sub_questions_added > 0` AND `sub_questions_closed == 0`. → raise `SCOPE_ESCALATION`. Default fallback narrow.
3. **Context-window hits** → context compaction, not stopping.

Per-sub-question depth is **not** a scope-creep signal. A sub-question spawning many internal tasks (e.g., `multi_perspective` + ACH) is legitimate work. A separate internal signal — sub-question exhaustion (stalled internal progress) — nudges the replanner to review but does not escalate to the user.

### `CHECK_TERMINATION_READY` (new, ADR 0009; deterministic, no LLM)

Runs after a replan cycle with zero mutations. Structural audit:

1. No `PENDING` tasks remain.
2. Every sub-question's `question_note` has status `SYNTHESIZED`.
3. Scope-creep has not been escalated with the user choosing "broaden."
4. Every **contested** sub-question has at least one completed disconfirmation task (`ADVERSARIAL_CRITIQUE`, `debate`, or `ach`) — in DONE status, linked to the sub-question.

Only if all pass does `VALIDATE_COMPLETION` run. If any fail, the scheduler emits targeted remediation tasks (e.g., spawn `ADVERSARIAL_CRITIQUE` on the contested sub-question that lacks one) and the run continues. The existing `VALIDATE_COMPLETION` remediation cap (max 2 cycles) carries over — if the termination check fails the same way twice, it escalates.

### `VALIDATE_COMPLETION` — six gates

Unchanged in intent from v3; G2 and G4 now routed to the judgment family (ADR 0008).

| Gate | Check | On failure |
|------|-------|-----------|
| **G1: Methodological veracity** | For each load-bearing claim, at least one supporting source is TIER_1 or TIER_2. | Spawn `VERIFY_CLAIM` targeting the claim + a search for higher-tier sources. |
| **G2: Survival of disconfirmation** *(judgment family)* | For `contested` sub-questions, `ach` has run OR `debate` has produced a synthesis with "surviving dissent" documented. For `synthesis` sub-questions, at least one adversarial critique has been attempted. | Spawn the appropriate pattern. |
| **G3: Linchpin stability** | For the BLUF-level conclusion, the top 2–3 linchpin assumptions have been identified. For each, at least 2 independent TIER_1–2 supporting sources exist. | Spawn targeted `single_researcher` tasks on any linchpin with < 2 sources. |
| **G4: Consensus through dissent** *(judgment family)* | At least one Round 4 premortem has run during the session. | Spawn a premortem task. |
| **G5: Standardized confidence** | The synthesis-level conclusion is assignable at Moderate (≥ 0.55) confidence per the formula. | If not — evidence is genuinely too thin — the gate passes with a mandatory "Low confidence" flag forcing the report to explain why. |
| **G6: Falsifiability commitment** | The report draft includes a "Milestones for Revision" section stating what data would change the conclusion. | Forced regeneration of that section. |

Gates run sequentially. Each failing gate spawns remediation; after remediation, `VALIDATE_COMPLETION` re-runs. Max 2 remediation cycles before the gate passes with a caveat documented in the report.
