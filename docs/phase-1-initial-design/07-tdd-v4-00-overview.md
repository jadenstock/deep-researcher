# Deep Research Agent — Initial Design (TDD v4) — Overview, Architecture, Data Model

**Status:** iteration 4. Revises `05-tdd-v3.md` after integrating ADRs 0001–0009 (`docs/adr/`).

**Scope:** API-based deep research agent. No training. Target: take-home deliverable.

**Split.** TDD v4 is split across four documents:

| Doc | Covers |
|---|---|
| `07-tdd-v4-00-overview.md` (this) | §1 Problem, §2 Goals, §3 Architecture, §4 Data Model |
| `07-tdd-v4-01-pipeline-and-infrastructure.md` | §5.1 Landscape Survey, §5.2 Decomposition, §5.3 Scheduler, §5.4 Agent Executor + role routing, §5.5 Search & Retrieval, §5.6 Source Extraction, §5.7 Source Tiering + Confidence, §5.8 Question-Round Strategy |
| `07-tdd-v4-02-orchestration-and-completion.md` | §5.9 Orchestration Patterns, §5.10 Pattern Selection at Runtime, §5.11 Verification, §5.12 Replanner, §5.13 User Gateway, §5.14 Stopping + Termination Readiness + Completion Gates |
| `07-tdd-v4-03-report-biases-walkthrough-and-plan.md` | §5.15 Report, §5.16 Biases, §6 Walkthrough, §7 MVP vs Deferred, §8 Ablation, §9 Open Questions, §10 Commitments |

Numbering skips `06-` intentionally (reserved for a future v3→v4 revisions note).

---

## Changes from v3 — ADR Index

Every substantive change has an ADR; this TDD states the *result*, not the argument.

| ADR | Change | Sections touched |
|---|---|---|
| 0001 | **Landscape Survey** phase precedes decomposition | §3, §4.3, §5.1, §5.2 |
| 0002 | **Task granularity** matches the natural reasoning unit | §4.3, §5.1, §5.9 |
| 0003 | **LLM-based semantic source tiering** + reject list + `peer_reviewed` field | §4.4, §5.7 |
| 0004 | **ACH consistency matrix batches per hypothesis**, not per (hyp, source) pair | §5.9 (ach) |
| 0005 | **Scope-creep detection at sub-question level** | §5.14 |
| 0006 | **Typed dependencies, staged waiting, runtime detection** | §4.1, §5.2, §5.3, §5.12 |
| 0007 | **Size-first source extraction**; structured_content + `load_source_section` | §4.4, §5.4, §5.6 |
| 0008 | **Role-to-model routing** with ablation support | §5.4, §5.11, §5.14, §8 |
| 0009 | **Bounded replanner authority**: `CHECK_TERMINATION_READY`, mutation budget, cascade semantics | §4.1, §4.3, §5.12, §5.14 |

Everything v3 committed that is not listed above — task-centric architecture, ephemeral agents, note-graph storage, Obsidian export, no-hard-budget stopping, interactivity L0–L5, model tiering, Analytic Pyramid report, confidence language ladder, bias countermeasures, AIMS scoping, question-round ladder — is retained.

---

## 1. Problem Statement

Given a natural-language research query, produce a structured report that:

- Answers the query with claims explicitly separated from their evidence.
- Flags confidence per claim and surfaces source agreement / disagreement.
- Iterates across multiple research threads, handles conflicting sources, and stays honest about what it couldn't resolve.
- Produces an **Analytic Pyramid-structured** output: bottom-line-up-front, linchpin assumptions, alternative hypotheses, calibrated uncertainty, intelligence gaps, and separated Finding / Insight / Recommendation levels.

Non-scoped: LLM-judge evaluation harness, production observability, automatic prompt improvement, cross-session memory, full RAG.

---

## 2. Design Goals and Non-Goals

### Goals

1. **Task-centric architecture** — tasks persist; agents are ephemeral workers.
2. **Mutable plan** — the task graph evolves via a bounded periodic replanner (ADR 0009).
3. **Note-graph as shared workspace** — typed, hyperlinked, Obsidian-exportable markdown.
4. **Claim traceability** — every claim ties to a verbatim quoted passage from a tier-classified source.
5. **Evidence-grounded pattern selection** — the landscape survey (ADR 0001) decides which patterns run based on what actually exists in the literature.
6. **Reasoning-unit task granularity** — per-item operations atomize, cross-item operations don't (ADR 0002).
7. **Diversity in the judgment layer** — verification and adjudication use a different model family than generation (ADR 0008).
8. **Closed set of orchestration patterns**, each a sub-task DAG with explicit question-framing discipline.
9. **Methodological rigor** — ACH for multi-hypothesis sub-questions; completion gates before the report; Analytic Pyramid structure; calibrated confidence language.
10. **User-in-the-loop** — configurable interactivity (L0–L5), async-preferred, default fallback always.
11. **Concrete search layer** — Serper + Semantic Scholar + arXiv + Unpaywall; PubMed / OpenAlex feature-flagged.

### Non-Goals

Training. Self-improvement loops. Long-lived agent personas. Production observability. Full RAG. Graceful-degradation infra beyond retry. Self-reflection loops.

---

## 3. System Architecture

### 3.1 Pipeline phases (revised; ADR 0001)

The pipeline now has four phases, not three:

```
  Phase 0 — INTAKE
      user query + interactivity level
              │
              ▼
  Phase 1 — LANDSCAPE SURVEY (new, ADR 0001)
      broad shallow retrieval; emit landscape_note + stub source_notes
              │
              ▼
  Phase 2 — DECOMPOSITION (AIMS scoping + classification, now evidence-grounded)
      reads landscape_note; classifies sub-questions; assigns patterns
      and typed dependencies (ADR 0006); emits task graph
              │
              ▼
  Phase 3 — DEEP RESEARCH (orchestrator loop)
      patterns run; scheduler respects dependencies; replanner mutates plan
      (bounded per ADR 0009); scope-creep watched at sub-question level (ADR 0005)
              │
              ▼
  Phase 4 — COMPLETION & REPORT
      CHECK_TERMINATION_READY (deterministic, ADR 0009)
              │ passes
              ▼
      VALIDATE_COMPLETION (six gates)
              │ passes
              ▼
      WRITE_REPORT (Analytic Pyramid, 10 sections)
              │
              ▼
      user (report + Obsidian vault export)
```

### 3.2 Bird's-eye view

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              USER                                         │
└─────────────────────────────┬────────────────────────────────────────────┘
                              │ query, interactivity level
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  LANDSCAPE SURVEY                                                         │
│   · broad multi-angle retrieval (web + academic)                         │
│   · one batched analyzer task over 5–10 top candidates (ADR 0002)        │
│   · emits landscape_note {themes, positions, key sources, open areas}    │
│   · stub source_notes feed forward into deep research                    │
└─────────────────────────────┬────────────────────────────────────────────┘
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  DECOMPOSITION (AIMS scoping, now evidence-grounded)                      │
│   · reads landscape_note                                                 │
│   · classify sub-questions: lookup / synthesis / contested / sparse      │
│   · select default orchestration pattern                                 │
│   · emit typed dependencies (produces_context_for / compared_against /   │
│     temporally_follows) (ADR 0006)                                       │
│   · create question_notes + initial task graph                           │
└─────────────────────────────┬────────────────────────────────────────────┘
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  ORCHESTRATOR LOOP                                                        │
│                                                                           │
│   SCHEDULER ─(staged deps)─▶ AGENT EXECUTOR ─(role routing)─▶ NOTE GRAPH │
│                               (cheap / mid / frontier,                    │
│                                generative / judgment family)              │
│      ▲                             │                                       │
│      │                             ▼                                       │
│      │                  SEARCH & RETRIEVE                                  │
│      │                  (Serper, S2, arXiv, Unpaywall)                    │
│      │                  + SOURCE EXTRACTION (size-first, ADR 0007)        │
│      │                  + SOURCE TIERING (semantic, ADR 0003)             │
│      │                                                                    │
│      │     ORCHESTRATION PATTERNS:                                        │
│      │     · single_researcher (scanner + analyzer + question synth)     │
│      │     · maker_checker (diverse-family verifier)                     │
│      │     · multi_perspective                                            │
│      │     · debate (2 positions)                                         │
│      │     · ach (≥3 positions; per-hypothesis batching, ADR 0004)       │
│      │                                                                    │
│      ├── REPLANNER (bounded: mutation budget + cadence; ADR 0009)        │
│      │    Rounds 3/4/5; checks for typed-dep detection + scope-creep     │
│      └── USER GATEWAY (L0–L5; scope-creep structured escalation)         │
│                                                                           │
└─────────────────────────────┬────────────────────────────────────────────┘
                              │ replanner idle
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  CHECK_TERMINATION_READY (deterministic; ADR 0009)                        │
│    · no PENDING tasks · every sub-question SYNTHESIZED                    │
│    · every contested sub-question has a disconfirmation task DONE         │
│    · scope-creep not escalated to "broaden"                               │
│  fails → targeted remediation tasks → loop                                │
└─────────────────────────────┬────────────────────────────────────────────┘
                              │ passes
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  VALIDATE_COMPLETION (six gates; spawns remediation if any fail)          │
└─────────────────────────────┬────────────────────────────────────────────┘
                              │ gates pass
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  WRITE_REPORT  (Analytic Pyramid, 10 sections, confidence-translated)     │
└─────────────────────────────┬────────────────────────────────────────────┘
                              ▼
                user (report + Obsidian vault export)
```

### 3.3 Principles

1. **Everything is a task.** Agents are ephemeral; tasks persist.
2. **Notes are the memory.** Agents communicate through the note graph, never directly.
3. **Progressive disclosure everywhere.** Default view of a note is a digest; full content loaded on demand. Structured-content + `load_source_section` (ADR 0007) applies the same pattern to long sources.
4. **Deterministic where it matters.** Reject list, peer-review status, confidence formula, gate definitions, tier weights, termination-readiness checks, size-routing thresholds — rule-based. LLM judgment reserved for content generation and semantic tiering.
5. **Task granularity matches the reasoning unit** (ADR 0002). Per-item work atomizes; cross-item work batches. When in doubt, default to the larger unit.
6. **Evidence before classification.** The landscape survey runs before decomposition so that pattern selection is grounded in retrieved evidence, not in LLM priors (ADR 0001).
7. **Diversity in the judgment layer** (ADR 0008). `VERIFY_CLAIM` and other judgment roles use a different model family than `ANALYZE_SOURCE` / `SYNTHESIZE`.
8. **Bounded replanner.** Termination is not a replanner prerogative; it requires a deterministic structural check. Mutations are budgeted; cascades have specified semantics (ADR 0009).
9. **Question-type discipline.** Every agent prompt cites which question-ladder round it's operating in. Prevents drift into vague prompting.
10. **Bias-countermeasure-aware.** Five structural biases and their countermeasures are invoked at specific points in the pipeline.

---

## 4. Core Data Model

### 4.1 Task

```python
Task {
  id: TaskID
  parent_id: TaskID | None
  goal: str
  type: TaskType
  role: RoleClass                      # generative | judgment | cheap_deterministic (ADR 0008)
  tier: TaskTier                       # LOW | MID | HIGH — drives model size within role
  pattern: OrchestrationPattern | None # set for pattern-orchestrating tasks
  question_round: QuestionRound | None # 1..5 or None — see §5.8
  status: TaskStatus                   # see below
  success_criteria: str                # LLM-evaluable
  depends_on: [(TaskID, DependencyType)]  # typed deps, ADR 0006
  dep_scope: {retrieval_ignores, synthesis_waits}  # per-task-type attribute
  reads_notes: [NoteID]
  writes_notes: [NoteID]
  spawned_sub_tasks: [TaskID]
  created_at, completed_at
}

TaskStatus ∈ { PENDING, RUNNING, BLOCKED_ON_SYNTHESIS_DEP, BLOCKED_ON_SPLIT,
               DONE, ESCALATED, ABANDONED }

DependencyType ∈ { produces_context_for, compared_against, temporally_follows, none }
```

- `BLOCKED_ON_SYNTHESIS_DEP` — ADR 0006: retrieval ran in parallel; synthesis now waits on an upstream synthesis.
- `BLOCKED_ON_SPLIT` — ADR 0009: task paused while its parent sub-question is being split; replanner assigns a branch.

### 4.2 Note

```python
Note {
  id, type, title, description, content, links, metadata,
  version, last_modified_by, last_modified_at, created_by, created_at
}
Link { target_id, edge_type, context? }
```

**Note types (v4):**
- `landscape_note` — **new, ADR 0001.** One per run. Maps the territory: themes, surfaced positions, key sources by section, open/under-covered areas.
- `source_note` — per source. Can be a **stub** (survey-emitted: metadata + one-line landscape contribution) or **full** (analyzer-emitted: claims + evaluation). Deep-research upgrades stubs; stub→full lifecycle is explicit (ADR 0002).
- `question_note` — per sub-question. Accumulates support/refute links and the adopted position.
- `synthesis_note` — per pattern run that reconciles evidence.
- `decision_note` — orchestrator/replanner rationale; AIMS; decomposition rationale; cascade-mutation records.
- `open_question_note` — scope-excluded follow-ups; surfaced in the report's Intelligence Gaps section.
- `hypothesis_note` — per ACH hypothesis.

### 4.3 Task types (closed set, v4)

The v3 task types persist, updated for ADR 0001, 0007, and 0009.

| Type | Role | Tier | Description |
|------|------|------|-------------|
| **`LANDSCAPE_SURVEY`** (new) | generative | HIGH | Phase 1. Batched cross-source reasoning over 5–10 top candidates; emits `landscape_note` + stub `source_note`s (ADR 0001, 0002). |
| `DECOMPOSE` | generative | HIGH | Phase 2. AIMS + classification + pattern + typed-dependency emission. Reads the `landscape_note`. |
| `SEARCH` | cheap_deterministic | LOW | Issue a query to Serper/S2/arXiv; returns raw hits. No LLM. |
| `SCAN_SEARCH_RESULTS` | cheap_deterministic | LOW | Scanner: batched relevance judgment over titles+snippets+metadata; returns filtered candidates. No fetch. |
| `FETCH_AND_EXTRACT` | cheap_deterministic | — | Fetch URL; convert to markdown; count tokens; route by size (ADR 0007); cache; reject-list check (ADR 0003); emit stub `source_note`. No LLM for fetch; LLM tier classifier runs during tiering. |
| `ANALYZE_SOURCE` | generative | MID | Deep-read one source. Uses structured_content + `load_source_section` when long (ADR 0007). Produces full `source_note`. |
| `QUESTION_SYNTHESIZE` (v3: `UPDATE_QUESTION_NOTE`) | generative | MID/HIGH | Cross-source reasoning for one sub-question. One task reads all its source_notes (ADR 0002); emits the question-level synthesis and updates the `question_note`'s position. |
| `VERIFY_CLAIM` | **judgment** | MID | Independent re-retrieval + verification; Round 3 framing. **Must use a different model family than the `ANALYZE_SOURCE` that produced the claim** (ADR 0008). |
| `ADVERSARIAL_CRITIQUE` | **judgment** | MID | Strongest counter-argument to a claim or position. Round 3. |
| `ANALYZE_CONSISTENCY` | **judgment** | MID | ACH: evaluate one hypothesis against all M available source_notes; return M verdicts (ADR 0004). |
| `SYNTHESIZE` | generative | HIGH | Cross-sub-question synthesis (ACH adjudication; multi-perspective merge; debate adjudication). |
| `REPLAN` | generative | HIGH | Bounded (mutation budget + cadence, ADR 0009). Uses Rounds 3/4/5. Checks typed-dep detection + sub-question-level scope-creep. |
| `SCOPE_ESCALATION` | — | — | User-gateway escalation (L0–L5); structured payload per ADR 0005. |
| **`CHECK_TERMINATION_READY`** (new, ADR 0009) | cheap_deterministic | — | Deterministic structural audit; no LLM. |
| `VALIDATE_COMPLETION` | judgment | HIGH | Six completion gates; spawns targeted remediation. G2 and G4 use judgment family (ADR 0008). |
| `WRITE_REPORT` | generative | HIGH | Analytic Pyramid, 10 sections. |

Pattern-invoking tasks (e.g., the top-level `ach` or `debate` node) are HIGH-tier orchestrating tasks that spawn the sub-task DAG; see §5.9.

### 4.4 Inside source notes

```python
source_note.metadata = {
  url, title, authors, venue, year,
  tier: 1..5,                           # LLM-classified, ADR 0003
  tier_rationale: str,                  # ADR 0003 — inspectable
  classifier_confidence: float,
  peer_reviewed: bool,                  # deterministic; independent of tier (ADR 0003)
  citation_count, raw_content_ref,
  structured_content: StructuredContent | None,   # ADR 0007
  summary,
  landscape_contribution: str | None,   # survey-only; one-line "what this source adds to the map"
  claims: [ClaimItem],                  # populated on analyzer upgrade
  evaluation: EvalItem | None,          # populated on analyzer upgrade
}

StructuredContent {                     # ADR 0007; present only when raw ≥ 8K tokens
  title, abstract, section_headers,
  first_paragraph_of_each_section,
  table_of_contents, figure_captions,
}

ClaimItem { id, text, quote, page_or_section?, extractor_confidence,
            verification_status: UNVERIFIED | SUPPORTS | REFUTES | INCONCL }
EvalItem {
  methodology,                # empirical | theoretical | opinion | survey | benchmark
  sample_size,
  reproducibility,            # HIGH | MEDIUM | LOW | UNKNOWN
  limitations_noted_by_authors: [str],
  agent_skepticism: str,      # 1–3 sentences
}
```

### 4.5 Invariants

- Every claim has a non-empty `quote`.
- `source_note.metadata.tier` is assigned by the LLM classifier (or deterministically 5 via reject list) at fetch time; `tier_rationale` is non-empty (ADR 0003).
- `peer_reviewed` is deterministic and independent of `tier` (ADR 0003).
- Concurrent writes serialized through the scheduler; version mismatch → re-dispatch with updated note.
- Note graph is the only long-term memory.
- `VERIFY_CLAIM.role` = judgment; its model family ≠ the family of the `ANALYZE_SOURCE` that produced the claim it verifies (ADR 0008).
- Retrieval-phase tasks never block on sub-question dependencies; synthesis-phase tasks do (ADR 0006).
- Termination cannot proceed unless `CHECK_TERMINATION_READY` has passed in the current run (ADR 0009).
