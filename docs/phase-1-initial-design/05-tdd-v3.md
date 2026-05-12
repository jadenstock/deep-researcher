# Deep Research Agent — Initial Design (TDD v3)

**Status:** iteration 3. Revised from `02-tdd-v2.md` after integrating:
- Workflow motifs (scanner/analyzer split) from `03-workflow-motifs.md`.
- Methodology adoptions (Tier A + B + C) from `04-research-skill-takeaways.md`.

**Scope:** API-based deep research agent. No training. Target: take-home deliverable.

**Changes from v2 (high level):**
- Task types split: **scanner vs. analyzer** separation as first-class types (§4.3).
- Orchestration patterns now have lower-level detail: each pattern is specified as a sub-task DAG with explicit prompt-framing rounds (§5.7).
- **ACH (Analysis of Competing Hypotheses)** added as a new pattern (§5.7).
- **Completion gates** as a pre-report validation task (§5.12).
- **Analytic Pyramid** as the report structure (§5.13).
- **Confidence language ladder** translating numeric confidence to standardized phrasing (§5.5).
- **Preliminary-source tiering policy** refined — preprints default Tier 3, upgrade conditional on corroboration; confidence-cap on preliminary-anchored conclusions (§5.5).
- **Question-type strategy** (5-round ladder) mapped to task prompts (§5.6).
- **Bias countermeasures** woven into replanner + verifier prompts (§5.14).
- **Intake uses AIMS scoping** (§5.1).

The v2 commitments (task-centric, ephemeral agents, note-graph storage, Obsidian export, no-budget stopping, interactivity L0–L5, model tiering) are all retained.

---

## 1. Problem Statement

Given a natural-language research query, produce a structured report that:
- Answers the query with claims explicitly separated from their evidence.
- Flags confidence per claim and surfaces source agreement / disagreement.
- Iterates across multiple research threads, handles conflicting sources, and stays honest about what it couldn't resolve.
- Produces an **Analytic Pyramid-structured** output: bottom-line-up-front, linchpin assumptions, alternative hypotheses, calibrated uncertainty, intelligence gaps, and separated Finding/Insight/Recommendation levels.

Non-scoped: LLM-judge evaluation harness, production observability, automatic prompt improvement, cross-session memory, full RAG.

---

## 2. Design Goals and Non-Goals

### Goals

1. **Task-centric architecture** — tasks persist; agents are ephemeral workers.
2. **Mutable plan** — the task graph evolves via a periodic replanner.
3. **Note-graph as shared workspace** — typed, hyperlinked, Obsidian-exportable markdown.
4. **Claim traceability** — every claim ties to a quoted passage from a tier-scored source.
5. **Scanner / analyzer decomposition** — cheap shallow relevance judgment separated from expensive deep reading.
6. **Closed set of orchestration patterns**, each with an explicit sub-task DAG and question-framing discipline.
7. **Methodological rigor** — ACH for multi-hypothesis sub-questions; completion gates before the report; Analytic Pyramid output structure; calibrated confidence language.
8. **User-in-the-loop** — configurable interactivity (L0–L5), async-preferred, default fallback always.
9. **Concrete, researched search layer** — Serper + Semantic Scholar + arXiv + Unpaywall; PubMed / OpenAlex behind a feature flag.

### Non-Goals

- Training. Self-improvement loops. Long-lived agent personas. Production observability. Full RAG. Graceful-degradation infra beyond retry. Self-reflection loops.

---

## 3. System Architecture

### 3.1 Bird's-eye view

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              USER                                         │
└─────────────────────────────┬────────────────────────────────────────────┘
                              │ query, interactivity level
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  INTAKE (DECOMPOSE + AIMS scoping)                                        │
│   · classify sub-questions (lookup / synthesis / contested / sparse)     │
│   · select default orchestration pattern per sub-question                 │
│   · create question_notes + initial task graph                            │
└─────────────────────────────┬────────────────────────────────────────────┘
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  ORCHESTRATOR LOOP                                                        │
│                                                                           │
│   SCHEDULER ──▶ AGENT EXECUTOR ──▶ NOTE GRAPH                            │
│   (serializes      (model-routed,      (typed notes,                     │
│    note writes)     context-forked)     progressive disclosure,          │
│                                         Obsidian vault export)           │
│      ▲                    │                     ▲                         │
│      │                    ▼                     │                         │
│      │          SEARCH & RETRIEVE ──────────────┘                         │
│      │          (Serper, S2, arXiv, Unpaywall, tier tagging, cache)      │
│      │                                                                    │
│      │        ┌───────────────┬───────────────┬────────────────┐         │
│      │        │               │               │                │         │
│      │   ORCHESTRATION PATTERNS (§5.7):                                   │
│      │   · single_researcher (scanner + analyzer + merge)                 │
│      │   · maker_checker                                                  │
│      │   · multi_perspective                                              │
│      │   · debate                                                         │
│      │   · ach (analysis of competing hypotheses)                         │
│      │        │               │               │                │         │
│      │        └───────────────┴───────────────┴────────────────┘         │
│      │                                                                    │
│      ├── REPLANNER (periodic; Round 3/4/5 question discipline)           │
│      └── USER GATEWAY (L0–L5, async, default fallback)                   │
│                                                                           │
└─────────────────────────────┬────────────────────────────────────────────┘
                              │ task graph exhausted or replanner idles
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
                USER (report + Obsidian vault export)
```

### 3.2 Principles

1. **Everything is a task.** Agents are ephemeral; tasks persist.
2. **Notes are the memory.** Agents communicate through the note graph, never directly.
3. **Progressive disclosure everywhere.** Default view of a note is a digest; full content loaded on demand.
4. **Deterministic where it matters.** Source tiering, confidence formulas, gate definitions, tier-weights — rule-based. LLM judgment reserved for content generation and high-level orchestration.
5. **Question-type discipline.** Every agent prompt cites which question-ladder round it's operating in (§5.6). Prevents drift into vague prompting.
6. **Bias-countermeasure-aware.** Five structural biases and their countermeasures (§5.14) are invoked at specific points in the pipeline.

---

## 4. Core Data Model

### 4.1 Task

```python
Task {
  id: TaskID
  parent_id: TaskID | None
  goal: str
  type: TaskType
  tier: TaskTier                       # LOW | MID | HIGH — drives model routing
  pattern: OrchestrationPattern | None # set for pattern-orchestrating tasks
  question_round: QuestionRound | None # 1..5 or None — see §5.6
  status: PENDING | RUNNING | DONE | ESCALATED | ABANDONED
  success_criteria: str                # LLM-evaluable
  depends_on: [TaskID]
  reads_notes: [NoteID]
  writes_notes: [NoteID]
  spawned_sub_tasks: [TaskID]
  created_at, completed_at
}
```

### 4.2 Note (unchanged from v2)

```python
Note {
  id, type, title, description, content, links, metadata,
  version, last_modified_by, last_modified_at, created_by, created_at
}
Link { target_id, edge_type, context? }
```

Note types: `source_note`, `question_note`, `synthesis_note`, `decision_note`, `open_question_note`, **`hypothesis_note`** (new in v3; see §5.7 ACH).

### 4.3 Task types (closed set, v3)

The **scanner/analyzer split** is formalized here. `SCAN_SEARCH_RESULTS` is a new LOW-tier type; `ANALYZE_SOURCE` replaces v2's loose "EXTRACT_CLAIMS."

| Type | Tier | Typical model | Description |
|------|------|---------------|-------------|
| `DECOMPOSE` | HIGH | frontier | Intake: AIMS scope + sub-question decomposition + pattern selection |
| `SEARCH` | LOW | cheap | Issue a query to Serper/S2/arXiv; returns raw search hits |
| **`SCAN_SEARCH_RESULTS`** | LOW | cheap | **Scanner agent.** Reads a batch of search hits (titles + snippets + metadata); judges relevance per sub-question; returns a filtered candidate list. Does **not** fetch or deep-read. |
| `FETCH_AND_EXTRACT` | LOW | — (deterministic) | Fetch URL, parse HTML (trafilatura), resolve DOI via Unpaywall if needed; tier-tag the resulting source. No LLM. |
| **`ANALYZE_SOURCE`** | MID | mid-frontier | **Analyzer agent.** Reads the full source content; produces `source_note` with summary, extracted claims (with quotes), evaluation (methodology, skepticism). |
| `UPDATE_QUESTION_NOTE` | MID | mid | Merge newly-extracted claims into the target `question_note`; create support/refute links. |
| `VERIFY_CLAIM` | MID | mid-frontier | Independent re-retrieval + verification; supports adversarial mode (Round 3 framing). |
| `ADVERSARIAL_CRITIQUE` | MID | mid-frontier | Build the strongest counter-argument to a claim or position. |
| `SYNTHESIZE` | HIGH | frontier | Merge multiple claims on a sub-question into a position; write to `synthesis_note`. |
| `REPLAN` | HIGH | frontier | Review the task graph and note graph; mutate the plan. Uses Rounds 3/4/5. |
| `SCOPE_ESCALATION` | — | — | User-gateway escalation (honors L0–L5). |
| **`VALIDATE_COMPLETION`** | HIGH | frontier | Run the six completion gates; spawn remediation if any fail. |
| `WRITE_REPORT` | HIGH | frontier | Produce the Analytic Pyramid report. |

Pattern-invoking tasks (e.g., `ACH`, `DEBATE`) are implemented as HIGH-tier orchestrating tasks that spawn a specific sub-task DAG — see §5.7.

### 4.4 Inside source notes (unchanged)

```python
source_note.metadata = {
  url, title, authors, venue, year, tier,
  citation_count, raw_content_ref, summary,
  claims: [ClaimItem],
  evaluation: EvalItem,
}

ClaimItem { id, text, quote, page_or_section?, extractor_confidence }
EvalItem {
  methodology,              # empirical | theoretical | opinion | survey | benchmark
  sample_size,
  reproducibility,          # HIGH | MEDIUM | LOW | UNKNOWN
  limitations_noted_by_authors: [str],
  agent_skepticism: str,    # 1-3 sentences
}
```

### 4.5 Invariants

- Every claim has a non-empty `quote`.
- `source_note.metadata.tier` is assigned deterministically at fetch time (§5.5).
- Concurrent writes serialized through the scheduler; version mismatch → re-dispatch with updated note (§5.6 of v2, unchanged).
- Note graph is the only long-term memory.

---

## 5. Components in Detail

### 5.1 Intake (`DECOMPOSE` with AIMS scoping)

Single HIGH-tier task. Inputs: raw user query + interactivity level.

**Step 1 — AIMS scoping.** The decomposer first fills out four fields before decomposing:

- **A** — Audience: who will read this, at what knowledge level? (Default for unknown: "technical reader familiar with the domain.")
- **I** — Issue: what specific problem is this query addressing?
- **M** — Message: what's the bottom-line judgment this research must produce?
- **S** — Storyline: what logical sequence takes a reader from evidence to conclusion?

AIMS is written into a `decision_note` and serves as a contract for the report's BLUF section.

**Step 2 — Starbursting / Round 1 decomposition.** The decomposer prompt explicitly asks:
- "What are the conditions under which this query would *not* have a clean answer?"
- "What sub-questions, if each independently answered, would let us answer the query?"
- "What does this query assume? Is the assumption always correct?"

Purpose: generate questions, not answers. Map the space before narrowing.

**Step 3 — Classification.** Each sub-question is classified:

- `lookup` — single retrieval suffices (e.g., "what is the definition of X?").
- `synthesis` — multiple sources need reconciling, no genuine controversy expected.
- `contested` — literature is known or expected to disagree.
- `sparse` — topic is emerging; evidence is expected to be thin.

**Step 4 — Pattern selection.** Classification maps to default pattern:

| Classification | Default pattern |
|---|---|
| `lookup` | `single_researcher` |
| `synthesis` | `single_researcher` + `maker_checker` |
| `contested` (2 positions surfaced) | `multi_perspective` + `maker_checker` → may escalate to `debate` |
| `contested` (≥3 positions surfaced) | `multi_perspective` + `ach` |
| `sparse` | `multi_perspective` + `maker_checker` with explicit "evidence-thinness" expectation |

**Step 5 — Emit.** Create `question_note`s (one per sub-question), emit initial task graph (typically one pattern-invoking task per question), commit a `decision_note` recording AIMS + decomposition rationale.

**Interactivity gate (L3+).** If decomposition confidence is low, emit `SCOPE_ESCALATION` with a concrete default decomposition as the fallback.

### 5.2 Task Scheduler (unchanged from v2)

- Maintains task graph + note graph.
- Dispatches next ready task.
- Serializes note writes through a mutation queue.
- Triggers periodic `REPLAN` (default every 10 completions).
- Emits `VALIDATE_COMPLETION` when the graph is exhausted (no PENDING tasks, replanner produces no new tasks).

### 5.3 Agent Executor (unchanged structure; v3 adds question-round context)

Stateless. Per task:
1. Routes to a model based on `task.tier` (cheap / mid / frontier).
2. Forks fresh context: task goal + progressive-disclosure views of `reads_notes` + parent task summary + **the question-round context** (§5.6) that tells the agent what mode of question to adopt.
3. Runs agent loop.
4. Emits structured output: note mutations + optional sub-tasks + verdict.
5. Dies.

Agent tools (MVP set): `load_note`, `search_notes`, `web_search`, `academic_search`, `get_paper_metadata`, `get_papers_citing`, `get_papers_cited_by`, `fetch_and_extract`, `resolve_oa_pdf`, `create_note`, `edit_note`, `spawn_task`, `ask_user`.

### 5.4 Search & Retrieval Layer (unchanged from v2)

- **Serper** — primary web search (2,500/mo free, Google-backed).
- **Semantic Scholar** — primary academic (free, no key, 200M papers, citation graph).
- **arXiv API** — direct for AI/ML recency.
- **Unpaywall** — DOI → open-access PDF.
- **OpenAlex, PubMed** — feature-flagged for post-MVP or domain-specific use.
- **`trafilatura` + `httpx`** — HTML fetch + main-content extraction.
- **Disk cache** keyed on `(tool, args_hash, day_bucket)`. Replay mode reads cache without network.

Tool interface unchanged from v2 §5.4.

### 5.5 Source Tiering, Confidence Formula, Confidence Language (v3 refined)

#### Tier rule table (same venues as v2, but with the preliminary-source policy applied)

| Tier | Rule |
|------|------|
| **TIER_1 — Peer-reviewed gold** | Systematic reviews / meta-analyses, or peer-reviewed publications in top venues (NeurIPS, ICML, ICLR, ACL, EMNLP, AAAI, IJCAI, CVPR, Nature, Science, PNAS, IEEE journals, Cochrane). Detected via S2/OpenAlex venue field, DOI, or URL pattern. |
| **TIER_2 — Structured observational** | Peer-reviewed conference/journal papers in reputable venues (non-top-tier), National Academies, RAND, IARPA, **plus preprints that pass the upgrade check below**. |
| **TIER_3 — Hypothesis-generating / preliminary (default for preprints)** | Established tech journals (MIT Tech Review, IEEE Spectrum), major AI-lab research blogs (Anthropic, OpenAI, DeepMind, Google Research, Meta AI), engineering blogs from major clouds, standards bodies (MCP, W3C), **preprints that don't meet the upgrade check**. |
| **TIER_4** | Harvard Business Review-style expert-opinion-in-refereed-venue (acceptable to fill gaps; not for primary anchoring). |
| **TIER_5 — Anecdotal / reject** | Random blogs, unattributed content, vendor marketing, community aggregators, social media. **Rejected on retrieval.** |

#### Preliminary-source upgrade check

A preprint (arXiv / bioRxiv / medRxiv / SSRN / OSF / institutional technical report) **starts at Tier 3**. It upgrades to Tier 2 only when **all three** are present:

1. **Named author + recognized institution** — major university, national lab, established research organization.
2. **Corroboration signal** — substantial citation count (heuristic: ≥ 20 cites for AI papers, ≥ 5 for niche domains), OR high citation velocity, OR a corresponding peer-reviewed version exists in a Tier 1-2 venue.
3. **Explicit reproducible methodology** — paper describes method + inputs + evaluation, not just a position piece.

Detection is automatic during `FETCH_AND_EXTRACT`: query Semantic Scholar / OpenAlex for citation count, check venue list for published equivalents, apply a simple regex / length check on methodology sections.

#### Preliminary-anchor confidence cap

When a claim's supporting evidence rests **primarily** on preliminary (pre-published) sources — even if they've been upgraded to Tier 2 — the claim's `confidence` is **capped at 0.80 (Moderate)**. Never High. The `source_note.evaluation.agent_skepticism` field must explicitly state "primary evidence is preliminary; this reflects current state-of-the-art in a fast-moving field."

#### Confidence formula

```
tier_weight = {TIER_1: 0.9, TIER_2: 0.75, TIER_3: 0.55, TIER_4: 0.3}
confidence_base = max(tier_weight[s.tier] for s in supporting_sources)
agreement_bonus = min(0.10 * (unique_supporting_sources - 1), 0.30)
citation_signal = min(log10(max_citation_count + 1) / 5, 0.10)  # capped
contradiction_penalty = 0.20 if any refuting source else 0
triangulation_bonus = triangulation_score * 0.10   # see §5.14

confidence_raw = clip(
  confidence_base + agreement_bonus + citation_signal
  + triangulation_bonus - contradiction_penalty,
  0, 1
)

confidence = min(confidence_raw, 0.80) if primarily_preliminary else confidence_raw
```

#### Confidence language ladder (new in v3)

Reports **never** show bare numbers or bare verbal qualifiers. Every claim carries both:

| Level | Numeric range | Language |
|-------|--------------|----------|
| **High** | 0.80–0.95 | "almost certainly", "highly likely", "we assess with high confidence" |
| **Moderate** | 0.55–0.80 | "likely", "probably", "we assess" |
| **Low** | 0.0–0.55 | "possible", "unlikely", "remote" |

Rendering format:
> The evidence [likely] supports the claim that X. *(Moderate confidence, 0.62; primarily preliminary evidence.)*

This translation is deterministic — no LLM judgment required. Computed in a helper function in the report-writing path.

### 5.6 Question-Round Strategy (new in v3)

Every agent prompt declares a `question_round ∈ {1..5, None}`, which sets the framing discipline:

- **Round 1 — Starbursting.** Generate questions, not answers. Explore the space. Used by: `DECOMPOSE` (Step 2).
- **Round 2 — Structural decomposition.** Break intractable into sub-components. Used by: `DECOMPOSE` (Step 3), `SYNTHESIZE` when merging overlapping sub-questions.
- **Round 3 — Falsification.** "What evidence would *disprove* this?" Used by: `VERIFY_CLAIM` (adversarial mode), `ADVERSARIAL_CRITIQUE`, `REPLAN` (when reviewing synthesis).
- **Round 4 — Premortem.** "Imagine this conclusion was wrong in 6 months; why?" Used by: `REPLAN` (when detecting consensus), `VALIDATE_COMPLETION` (Gate 4).
- **Round 5 — Metacognitive.** "What gaps are diagnostically significant? Where might correlation-vs-causation confuse?" Used by: `REPLAN` (when the task graph looks saturated), `VALIDATE_COMPLETION` (Gate 6).

The round-tag is a prompt scaffold: the agent's system prompt includes a canned instruction block for each round (e.g., the 3-question prompt stub from the skill's Round 3 section). This isn't magic — it's just consistent framing that prevents the system from drifting into vague prompting as the loop gets deep.

### 5.7 Orchestration Patterns (significantly expanded in v3)

The closed set of patterns. Each is an abstract sub-task DAG instantiated by a pattern-invoking HIGH-tier task.

General structure for every pattern:
- **Trigger criteria** — when it runs.
- **Phases** — the sub-task sequence (may fan out for parallelism).
- **Question-round framing** — which rounds its sub-tasks use.
- **Note-graph I/O** — what it reads and writes.
- **Failure modes** — what goes wrong.
- **Cost tier** — total LLM cost envelope.

---

#### 5.7.1 `single_researcher`

**Purpose.** Default for `lookup` and `synthesis` sub-questions. Executes the scanner → analyzer → merge flow for one question.

**Trigger.** Assigned at decomposition for `lookup` / `synthesis` sub-questions. Also the inner loop of `multi_perspective` (one per perspective).

**Phases (sub-task DAG):**

```
                   ┌─── SEARCH (web) ─────────┐
                   ├─── SEARCH (academic) ────┤
single_researcher──┤                          ├──▶ SCAN_SEARCH_RESULTS
                   └─── SEARCH (arxiv direct) ┘         │
                                                       │ filtered candidates
                                                       ▼
                                       ┌───── FETCH_AND_EXTRACT (fan-out) ─────┐
                                       │       (parallel per candidate)         │
                                       └────────────────┬────────────────────────┘
                                                        │ source_notes (tier-tagged)
                                                        ▼
                                       ┌───── ANALYZE_SOURCE (fan-out) ─────┐
                                       │       (parallel per source)         │
                                       └────────────────┬────────────────────┘
                                                        │ source_notes populated
                                                        │ (claims + evaluation)
                                                        ▼
                                                 UPDATE_QUESTION_NOTE
                                                        │
                                                        ▼ question_note updated
```

**Question-round framing:**
- `SCAN_SEARCH_RESULTS` — Round 2 (decompose the batch: which hits address which sub-component of the question?).
- `ANALYZE_SOURCE` — Round 2 (decompose the paper into its claims, methodology, limitations).
- `UPDATE_QUESTION_NOTE` — Round 2 (decompose the accumulated evidence into position candidates).

**Note-graph I/O:**
- Reads: `question_note` (for context).
- Writes: `source_note`s (one per fetched source), updates `question_note` with support/refute links.

**Failure modes:**
- **Scanner over-filters** — judges everything irrelevant, returns empty. Mitigation: if the scanner returns < 3 candidates, widen the query (Round 1 starbursting) and retry once.
- **Scanner under-filters** — passes everything through, driving analyzer cost up. Mitigation: scanner's prompt includes a "max 10 candidates per scan batch" instruction; if more than 10 look relevant, it must rank and cut.
- **Analyzer misreads source** — produces claims unsupported by quoted passages. Mitigation: `extractor_confidence` on each claim; claims with low confidence don't propagate to the question note without verification.

**Cost envelope.** LOW × several + MID × several. The typical cheap path.

---

#### 5.7.2 `maker_checker`

**Purpose.** Maker proposes claims; checker independently tests them. Used on top of `single_researcher` for `synthesis` / `contested` / `sparse` sub-questions.

**Trigger.** Wraps a `single_researcher` output. Runs after `UPDATE_QUESTION_NOTE` on sub-questions where the default pattern specifies maker-checker.

**Phases:**

```
single_researcher output (claims in question_note)
                     │
                     ▼
         for each claim where verification is triggered:
         ┌─────────────────────────────────────────────┐
         │  VERIFY_CLAIM (Round 3 framing)              │
         │   · re-phrase query (avoid same retrieval)   │
         │   · fetch independent sources                │
         │   · verdict: SUPPORTS | REFUTES | INCONCL    │
         └────────────┬────────────────────────────────┘
                      │
                      ▼
         update claim.verification_status in source_note
```

**Which claims get verified?**
- Any claim whose `supporting_sources` max tier < Tier 2.
- Any claim on a `contested` or `sparse` sub-question.
- Any claim explicitly marked load-bearing by the replanner or by `VALIDATE_COMPLETION`.

**Question-round framing:** `VERIFY_CLAIM` — Round 3 falsification. The prompt explicitly asks "what evidence would disprove this claim? Go find it."

**Note-graph I/O:** Reads the claim's source_note. May create new source_notes for verifier's retrievals. Updates the claim's verification_status.

**Failure modes:**
- **Verifier uses the same retrieval path** as the original researcher and trivially "confirms." Mitigation: the Round 3 prompt includes a required instruction to re-phrase the query and deliberately seek out sources the maker would not have used (different venue, different search terms, different time window).
- **Verifier false-refutes** a true claim because a single adversarial source exists. Mitigation: `REFUTES` verdict requires ≥ 2 refuting sources or 1 refuting Tier-1 source.

**Cost envelope.** MID per claim verified. Scales with claim count; controlled by the "which claims get verified?" filter.

---

#### 5.7.3 `multi_perspective`

**Purpose.** Generate search queries from multiple stakeholder framings to avoid one-sided evidence collection at the start. For `contested` and `sparse` sub-questions.

**Trigger.** Assigned at decomposition for `contested` or `sparse` sub-questions.

**Phases:**

```
                      ┌─ SYNTHESIZE (Round 1 starbursting)
                      │     "enumerate the stakeholder perspectives
                      │      from which this sub-question could be asked.
                      │      Return N perspectives, each with 2-3 representative
                      │      search queries."
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

**Why this works.** If three independent perspectives turn up overlapping evidence, you have cross-perspective triangulation. If they turn up different evidence, the question really is contested and the system knows early.

**Perspective count.** N = 3 for `contested`; N = 2-3 for `sparse` (depending on decomposer judgment).

**Question-round framing:**
- Perspective generation — Round 1 starbursting.
- Per-perspective research — runs `single_researcher` internally.
- Final merge — Round 2 decomposition, merging overlapping claims.

**Note-graph I/O:**
- Creates a `synthesis_note` per sub-question, linking to the source_notes from each perspective.
- Updates the `question_note` with per-perspective positions and evidence counts.

**Failure modes:**
- **Perspectives too similar** — three framings all retrieve the same papers. Mitigation: the perspective generator's prompt explicitly requires "materially different stakeholders" (e.g., theoretical / empirical / practitioner / critical).
- **One perspective dominates** — two perspectives return thin, one returns thick. That's actually a finding (the thin perspectives have less evidence). The merge step preserves this asymmetry rather than averaging.

**Cost envelope.** N × `single_researcher` + one synthesis pass. Most expensive default pattern.

---

#### 5.7.4 `debate`

**Purpose.** When **two** specific contradictory positions on the same sub-question have been surfaced, force a structured adversarial dialectic with a judge. Cheaper than ACH; reserved for clear binary oppositions.

**Trigger.** Runtime-spawned by `REPLAN` or a MID-tier agent when it detects two specific `question_note` claims with opposite positions and at least moderate evidence on both sides.

**Phases:**

```
                Position A (with evidence refs)
                Position B (with evidence refs)
                                │
                                ▼
               ┌── ADVERSARIAL_CRITIQUE (Position A)
               │     Round 3 framing: "given all sources, what is the
               │     strongest case AGAINST Position A? Surface the
               │     best evidence for Position B and the weakest
               │     evidence for Position A."
               │
               ├── ADVERSARIAL_CRITIQUE (Position B)
               │     Same but for B.
               │        │ (runs in parallel)
               │        ▼
debate ────────┤   SYNTHESIZE (Round 2 + Round 4 premortem framing)
               │     "weigh the strongest cases for and against each
               │     position. If we adopt A and it's wrong in 6 months,
               │     what did we miss? Same for B. Tentatively adopt
               │     the position with the lowest inconsistency score —
               │     the one that the fewest pieces of evidence are
               │     inconsistent with."
               │        │
               │        ▼
               │   write synthesis_note with:
               │     · adopted position (with rationale)
               │     · surviving dissent (evidence that still
               │       contradicts the adopted position)
               │     · what would overturn the decision
```

**Why not just "judge"?** The skill's devil's-advocate protocol is explicit that authentic dissent is required, not performative. The parallel `ADVERSARIAL_CRITIQUE` tasks are run with adversarial framing on each side *before* the synthesizer sees them, so neither side is strawmanned.

**Question-round framing:** Round 3 (adversarial) + Round 4 (premortem) in the synthesis step.

**Note-graph I/O:** Creates a `synthesis_note`. May create new source_notes via the adversarial critiques' independent retrievals. Updates the `question_note`'s position.

**Failure modes:**
- **Binary trap** — debate collapses to a false dichotomy when the real answer is "both wrong, position C is correct." Mitigation: before invoking `debate`, the replanner checks whether there's a plausible Position C; if so, escalate to `ach` instead.
- **Judge siding by weight-of-evidence when quality matters more** — Position A has 10 Tier-3 sources, Position B has 2 Tier-1 sources; a naive judge picks A. Mitigation: the synthesis prompt explicitly scores by tier-weighted inconsistency, not by raw source count.

**Cost envelope.** 2 × MID (adversarial critiques) + 1 × HIGH (synthesis).

---

#### 5.7.5 `ach` — Analysis of Competing Hypotheses (new in v3)

**Purpose.** When **three or more** plausible positions have been surfaced (or could plausibly exist), avoid the binary trap of `debate` by formally enumerating and scoring all hypotheses.

**Trigger.** Assigned at decomposition for `contested` sub-questions where the decomposer surfaced ≥ 3 positions, OR runtime-spawned by the replanner when `debate`'s pre-check flags a third plausible position.

**Phases:**

```
                  ┌── SYNTHESIZE (Round 1 starbursting)
                  │     "list ALL plausible, mutually exclusive hypotheses
                  │      that could answer this sub-question. Err toward
                  │      over-enumeration. Include outlier hypotheses."
                  │         │
                  │         ▼ hypothesis_notes (N entries)
                  │
                  ├── for each hypothesis, for each source_note on this question:
                  │        ┌─────────────────────────────────────────────────┐
                  │        │ ANALYZE_CONSISTENCY (MID-tier, parallel)         │
                  │        │   "given this hypothesis, is this evidence       │
                  │        │    consistent / inconsistent / neutral? Explain." │
ach ──────────────┤        └────────────┬─────────────────────────────────────┘
                  │                     │ consistency matrix
                  │                     │ (hypothesis × evidence)
                  │                     ▼
                  │      ┌─────────────────────────────────────────────┐
                  │      │ SYNTHESIZE (Round 2 + Round 5 metacognitive) │
                  │      │   · compute inconsistency_score per hypothesis│
                  │      │     = count(inconsistent evidence) weighted   │
                  │      │       by evidence tier                        │
                  │      │   · accept tentative position = hypothesis    │
                  │      │     with LOWEST inconsistency_score           │
                  │      │   · flag surviving inconsistencies            │
                  │      │   · identify linchpin evidence                │
                  │      └────────────┬─────────────────────────────────┘
                  │                   ▼
                  │     write synthesis_note:
                  │       · all hypotheses with scores
                  │       · adopted hypothesis (lowest inconsistency)
                  │       · surviving dissent
                  │       · linchpin evidence (flag for Gate 3)
```

**Why lowest-inconsistency, not highest-support?** ACH accepts the hypothesis the most evidence is *least* inconsistent with. This resists confirmation bias: many pieces of weak supporting evidence don't outweigh a few pieces of strong contradictory evidence.

**Hypothesis note type (new).** `hypothesis_note.metadata = {hypothesis_text, inconsistency_score, supporting_evidence: [SourceID], inconsistent_evidence: [SourceID], neutral_evidence: [SourceID], tentatively_adopted: bool}`.

**Question-round framing:**
- Hypothesis enumeration — Round 1 starbursting (over-enumerate).
- Consistency analysis — Round 2 decomposition per evidence-hypothesis pair.
- Adjudication — Round 5 metacognitive (audit the scoring, check for correlation-vs-causation).

**Note-graph I/O:** Creates N `hypothesis_note`s + a `synthesis_note`. Links each hypothesis to supporting / inconsistent / neutral evidence. Updates the `question_note`'s adopted position with a pointer to the inconsistency matrix.

**Failure modes:**
- **Over-enumeration collapses to the same hypothesis.** Mitigation: synthesizer deduplicates semantically equivalent hypotheses before scoring.
- **Evidence-coverage asymmetry** — newer hypotheses have less evidence evaluated against them. Mitigation: a normalized inconsistency score (inconsistency count / total evaluated) is used, not raw count. Hypotheses with < 3 evaluated evidence pieces are flagged as "under-tested" rather than "low-inconsistency."
- **Tie-breaking.** If two hypotheses have near-identical scores, the synthesis_note reports both and marks the question as `CONTESTED` in the final report rather than forcing a pick.

**Cost envelope.** N × M × MID (the consistency matrix is the big cost) + 1 × HIGH. ACH is the most expensive pattern; reserved for genuinely multi-sided sub-questions.

---

### 5.8 Pattern selection at runtime

Pattern selection happens at two points (already outlined in §5.1):

1. **At decomposition** — classification-driven default.
2. **At runtime by the replanner or a mid-tier agent** — when the note graph reveals something the decomposer didn't anticipate.

Runtime escalation rules:

- A `single_researcher` result where the question_note contains claims with contradictory positions from different source_notes → spawn `debate` (2 positions) or `ach` (3+ positions).
- A `maker_checker` result where the verifier introduces a third plausible position not surfaced originally → escalate to `ach`.
- A `multi_perspective` result where perspectives converge → re-classify the sub-question from `contested` to `synthesis`; skip further verification.
- A `debate` result where the synthesis notes "both positions have surviving dissent and the adopted one is marginal" → escalate to `ach`.

These rules live in the `REPLAN` task's prompt — it reads the note graph and the recent completed tasks, and emits pattern-invoking tasks as needed.

### 5.9 Verification (unchanged in principle; Round 3 explicit)

`VERIFY_CLAIM` and `ADVERSARIAL_CRITIQUE` always use Round 3 framing. Their system prompts include a canned Round 3 instruction block: "find the strongest evidence that would *disprove* this claim; use deliberately different queries; prefer sources from different venues / authors / time windows than the original."

### 5.10 Replanner (expanded in v3)

`REPLAN` runs periodically (every 10 task completions by default).

**Inputs:** full note graph (progressive-disclosure views) + current task graph + recent completed tasks.

**Prompt structure:** uses Rounds 3, 4, and 5 explicitly:

- Round 3 (falsification): "For each question_note with an adopted position, what evidence would disprove it? Has that evidence been searched for?"
- Round 4 (premortem): "Imagine we ship this report tomorrow and it turns out to be wrong in 6 months. What's the most likely reason? Which sub-question is the weakest?"
- Round 5 (metacognitive): "What sub-questions are we saturating vs. where are there diagnostically-significant gaps? Is the current task graph aligned with the original AIMS?"

**Outputs:** task graph mutations (add / edit / abandon) + a `decision_note` recording rationale. If the replanner detects unmanageable scope creep (task-creation rate ≥ completion rate for K replan cycles), it raises a `SCOPE_ESCALATION`.

**Bias-countermeasure checks at replan time** (see §5.14): the replanner's prompt includes the 5 named biases; it scans the note graph for signs of each and emits targeted tasks if it finds them.

### 5.11 User Gateway (unchanged from v2)

L0–L5 interactivity, async-preferred, default fallback mandatory. MVP supports L0 and L3 concretely; others stubbed.

### 5.12 Stopping + Completion Gates (new pre-report check in v3)

Stopping signals (unchanged):
1. Task graph exhausted (no PENDING tasks, replanner emits none).
2. Progress stall (new-task-rate ≥ completion-rate for K cycles) → `SCOPE_ESCALATION`.
3. Context-window hits → context compaction, not stopping.

**New: `VALIDATE_COMPLETION` task.** Runs when stopping signal 1 fires, *before* `WRITE_REPORT`. Checks six gates against the note graph:

| Gate | Check | On failure |
|------|-------|-----------|
| **G1: Methodological veracity** | For each load-bearing claim in the synthesis, at least one supporting source is Tier 1 or Tier 2 (post-upgrade). | Spawn `VERIFY_CLAIM` targeting specifically the claim + a search for higher-tier sources. |
| **G2: Survival of disconfirmation** | For `contested` sub-questions, `ach` has run OR `debate` has produced a synthesis with "surviving dissent" documented. For `synthesis` sub-questions, at least one adversarial critique has been attempted. | Spawn the appropriate pattern. |
| **G3: Linchpin stability** | For the BLUF-level conclusion, the top 2-3 linchpin assumptions have been identified (linchpin evidence flagged during ACH or manually in a `decision_note`). For each, at least 2 independent Tier 1-2 supporting sources exist. | Spawn targeted `single_researcher` tasks on any linchpin with < 2 sources. |
| **G4: Consensus through dissent** | At least one Round 4 premortem has run during the session (the replanner likely did this; if not, spawn it now). | Spawn a premortem task. |
| **G5: Standardized confidence** | The synthesis-level conclusion is assignable at Moderate (≥ 0.55) confidence per the formula. | If it can't be — i.e., the evidence is just too thin — the gate passes with a mandatory "Low confidence" flag that forces the report to explicitly explain why. |
| **G6: Falsifiability commitment** | The report draft must include a "Milestones for Revision" section stating what data would change the conclusion. This is generated by `WRITE_REPORT` using a Round 3 prompt. G6 is a structural check that the section isn't empty. | The gate is checked after report draft; remediation is a forced regeneration of that section. |

Gates run **sequentially**. Each gate that fails spawns remediation tasks; after they complete, `VALIDATE_COMPLETION` re-runs. Budget: max 2 remediation cycles before the gate passes with a caveat documented in the report.

### 5.13 Report Structure — The Analytic Pyramid (new in v3)

`WRITE_REPORT` produces a markdown document with this 10-section structure. Each section has real content; no placeholders.

1. **Problem Statement** — 1-2 sentences restating the user's query as a research question. Does not contain the answer.
2. **Research Design** — Which orchestration patterns were used, number of sources loaded by tier, Q&A methodology (round-ladder rounds touched).
3. **Bottom Line Up Front (BLUF)** — AIMS-structured: Audience, Issue, Message, Storyline. The headline judgment, stated first.
4. **Linchpin Assumptions** — The foundational premises the conclusion rests on. For each: the assumption, why it's accepted (evidence basis), what would falsify it.
5. **Evidence Summary** — Key data points, organized by tier. Cites source quality levels. Includes the source-tier distribution.
6. **Alternative Hypotheses** — All competing positions seriously considered. For each, why it was rejected as less likely. Contested sub-questions show their full ACH or debate outcome here.
7. **Calibrated Uncertainty** — Per claim and per BLUF judgment, the standardized confidence language + numeric range + explicit caveats (e.g., "primary evidence is preliminary").
8. **Intelligence Gaps** — Distinguishes:
   - **(a) Diagnostically significant gaps** — filling them would change the conclusion.
   - **(b) Acknowledged limitations** — noted but do not change the conclusion.
9. **Milestones for Revision** — Specific future events or new data that would invalidate the current conclusion (Gate 6 falsifiability commitment).
10. **Findings / Insights / Recommendations** — three distinct levels, never collapsed:
    - **Finding**: raw data, observable fact ("What is?")
    - **Insight**: interpreted meaning, causal reading ("What does this mean?")
    - **Recommendation**: proposed action, contingency plan ("What should be done?")

A fact is never stated as a recommendation; an assumption is never stated as a finding.

Accompanying output: the Obsidian-compatible vault of the note graph at `./runs/{run_id}/vault/`.

### 5.14 Bias Countermeasures and Prompting Discipline (new in v3)

These are woven into specific task prompts rather than a separate component. Listed here for traceability.

**Five named biases, each with a structural intervention:**

| Bias | Where the countermeasure lives |
|------|------------------------------|
| **Confirmation bias** | `ach` pattern (evaluate each evidence item against ALL hypotheses). Replanner's Round 3 check. |
| **Satisficing** | `DECOMPOSE` and ACH hypothesis enumeration explicitly over-enumerate before converging. |
| **Anchoring** | Replanner's Round 5 explicitly asks "re-evaluate from scratch — does this still hold?" every K cycles. |
| **Availability** | Triangulation requirement (§5.14 below). "Dog that didn't bark": verifier's prompt includes "has the evidence we'd *expect* to see if the hypothesis were true actually appeared?" |
| **Mirror imaging** | Mostly not load-bearing for research-agent use case. Included in the replanner prompt as a check for queries about actor behavior or incentives. |

**Triangulation requirement.** For every claim marked load-bearing (linchpin or BLUF-level), the system computes a triangulation score across three vectors:

```python
triangulation_score = sum over three vectors:
  0.33 if vector covered else 0
Vectors:
  1. Source type diversity: ≥ 2 of {peer-reviewed, institutional, practitioner, preprint}
  2. Time diversity: sources span ≥ 2 years
  3. Methodological diversity: ≥ 2 of {empirical, theoretical, survey, benchmark, opinion}
```

Fed into the confidence formula as `triangulation_bonus`. A load-bearing claim with triangulation_score < 0.66 → `VALIDATE_COMPLETION` G3 may fail, spawning remediation.

Rule: **three sources citing the same original study do not count as three independent sources.** Detection: during `ANALYZE_SOURCE`, if a claim's supporting quote cites a specific upstream paper, the extractor tracks it; triangulation math deduplicates.

**SIFT for the scanner agent.** The `SCAN_SEARCH_RESULTS` prompt includes the four SIFT steps as discipline:
1. Stop — don't pass a hit through based on title alone.
2. Investigate — has the source's domain been seen before in this session? What's its tier?
3. Find better coverage — is this claim likely findable in a higher-tier source? If so, prefer that source.
4. Trace — if the hit is a summary or aggregator, prefer the original.

---

## 6. End-to-End Flow: Example Walkthrough (updated for v3)

**Query (Test Case 2):** "Is chain-of-thought prompting an effective reasoning strategy for LLMs, or does it primarily improve output formatting?"

1. **Intake** (`DECOMPOSE`, frontier, Round 1 + 2).
   - AIMS: Audience = "ML researcher/engineer familiar with LLMs"; Issue = "wants to know when to use CoT and what effect to expect"; Message = "CoT's effect depends on task and model size; reasoning-vs-formatting is a false dichotomy if the evidence shows both are in play"; Storyline = "present the two claimed positions, show the evidence for each, synthesize into a conditional."
   - Sub-questions:
     - Q1: Evidence CoT improves reasoning → `contested` (2 positions) → `multi_perspective` + `maker_checker`
     - Q2: Evidence CoT improves formatting → `contested` (2 positions) → `multi_perspective` + `maker_checker`
     - Q3: Conditions where CoT helps vs. not → `synthesis` → `single_researcher` + `maker_checker`
   - `decision_note` records the AIMS and decomposition rationale.

2. **Parallel research.** Three pattern-invoking tasks dispatched.
   - Q1 and Q2 each run `multi_perspective` with N=3 stakeholder framings (theoretical / empirical-benchmark / critical).
   - Each perspective runs `single_researcher` → SEARCH → SCAN_SEARCH_RESULTS (Round 2, filters to ~6 candidates) → FETCH_AND_EXTRACT (parallel, no LLM) → ANALYZE_SOURCE (parallel, populates source_notes with claims + evaluation) → UPDATE_QUESTION_NOTE.
   - Source tiers assigned: Wei et al. CoT paper at NeurIPS → Tier 1; Madaan et al. critique on arXiv with 50+ citations + named institution + explicit methodology → Tier 2 (preliminary upgrade passes); blog posts → Tier 5 rejected.

3. **Verification.** `maker_checker` runs `VERIFY_CLAIM` (Round 3) on load-bearing claims from Q1 and Q2.
   - Adversarial verifier for Q1 independently retrieves the formatting-effect literature; updates Q1's main claim to `CONTESTED`.

4. **Replanner fires at 10 completions** (Rounds 3, 4, 5).
   - Detects 3 plausible positions on Q1+Q2 combined: (A) CoT genuinely improves reasoning; (B) CoT primarily improves formatting; (C) effect is real but conditional on task type and model scale.
   - Escalates from the implicit `debate` direction to `ach`.

5. **ACH runs.**
   - Enumerates 4 hypotheses (adds a fourth: "CoT is measurement artifact from eval methodology").
   - Runs consistency analysis: each of ~12 source_notes scored against each of 4 hypotheses → MID-tier × 48 tasks, parallelized.
   - Adjudication (Round 5): hypothesis C (conditional) has the lowest inconsistency score; its surviving dissent is documented; linchpin evidence flagged.

6. **Progress check.** No new task creation after ACH completes. Stopping signal fires.

7. **`VALIDATE_COMPLETION`.**
   - G1: adopted position anchored on ≥ 2 Tier 1-2 sources ✓.
   - G2: ACH ran on the contested sub-questions ✓.
   - G3: linchpin assumptions identified; triangulation score = 1.0 (all three vectors covered) ✓.
   - G4: Round 4 premortem ran in the replanner ✓.
   - G5: Moderate confidence achievable (0.72) ✓.
   - G6: deferred to `WRITE_REPORT` structural check.
   - All gates pass.

8. **`WRITE_REPORT` (Analytic Pyramid).**
   - Section 3 (BLUF): "CoT likely improves reasoning on tasks requiring intermediate computation at sufficient model scale, but its effect on simple classification tasks appears to be largely formatting / regularization. *(Moderate confidence, 0.72; primarily peer-reviewed evidence with preliminary corroboration.)*"
   - Section 4 (Linchpin): "The conclusion assumes (a) benchmark task taxonomy is a meaningful distinction, (b) the model-scale threshold documented in Wei et al. generalizes. Falsifier: evidence that CoT helps / doesn't help is confounded by prompt-tuning artifacts."
   - Section 6 (Alternatives): all 4 ACH hypotheses listed with their inconsistency scores.
   - Section 9 (Milestones for Revision): "A future study controlling for prompt-structure artifacts or a meta-analysis on newer instruction-tuned models would warrant re-evaluation."
   - Section 10: Findings (what the sources say) / Insights (what it means: a third interpretation beats both original positions) / Recommendations (none — research task, not decision task; note this explicitly).

9. **Vault export.** Note graph → `./runs/{run_id}/vault/` for Obsidian browsing.

---

## 7. MVP vs. Deferred

### MVP

- Task graph + scheduler (in-memory, serial note writes).
- Intake with AIMS scoping.
- Agent executor with model routing (cheap / mid / frontier).
- Search layer: Serper + Semantic Scholar + arXiv + Unpaywall + `trafilatura`.
- Deterministic source tiering with preliminary-upgrade policy + confidence cap.
- Confidence language ladder (number → qualitative label translation).
- Note graph with 6 types (including `hypothesis_note`).
- Obsidian vault export.
- Orchestration patterns: `single_researcher`, `maker_checker`, `multi_perspective`, `debate`, `ach`.
- Verifier (default + adversarial via Round 3 framing).
- Replanner with Round 3/4/5 prompt scaffolding.
- Scanner / analyzer task split (`SCAN_SEARCH_RESULTS` + `ANALYZE_SOURCE`).
- Completion gates + `VALIDATE_COMPLETION`.
- `WRITE_REPORT` producing the 10-section Analytic Pyramid.
- User gateway at L0 and L3.
- Stopping on task-graph exhaustion + scope-creep escalation.

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

---

## 8. Comparison / Ablation for the Take-Home

Candidates, ranked:

1. **With vs. without the verifier tier** — simplest story, clean metric (claim-level faithfulness: quote→claim support rate). Isolates the value of independent verification.
2. **`ach` vs. `debate` on `contested` sub-questions with 3+ plausible positions** — tests whether the structured multi-hypothesis method catches positions `debate` misses. Metric: number of plausible positions surfaced and retained in the final report.
3. **Scanner / analyzer split vs. single-stage retrieval** — tests whether the split improves precision (fewer irrelevant papers fetched) at no coverage cost. Metric: relevance-weighted recall at fixed cost budget.
4. **Analytic Pyramid report vs. flat sectional report** — subjective; would require small user study. Probably skip for MVP.

**Recommendation:** lead with #1. It has the cleanest story and the tightest eval. If time permits, #2 is the more novel story (the binary-trap → ACH escalation is a real contribution of this design).

---

## 9. Open Questions (for Phase-2 Research)

Load-bearing unknowns worth stress-testing before implementation:

1. **Scanner/analyzer handoff protocol** — what does the scanner pass to the analyzer? Just URL + title? Snippet + relevance rationale? Full search-result metadata? Unresolved.
2. **ACH consistency-analysis prompt** — the N×M consistency-matrix task count is the cost driver. Can these be batched (one prompt per hypothesis rating all evidence)? Does batching degrade judgment quality?
3. **ACH tie-breaking** — when two hypotheses have near-identical inconsistency scores, is reporting "contested" the right move or should the system force a tentative pick? Research question.
4. **Pattern escalation triggers** — the runtime rules in §5.8 are specified but not calibrated. What's the right threshold for "two contradictory claims → spawn debate"?
5. **Preliminary-upgrade citation threshold** — the "≥ 20 citations" heuristic is a guess. May need calibration per domain.
6. **Confidence-cap on preliminary evidence** — capping at 0.80 is principled but the specific number is a guess. Worth stress-testing against ground-truth calibration data.
7. **Completion-gate remediation budget** — max 2 cycles before passing with a caveat. Too tight? Too loose?
8. **Triangulation vector definitions** — "methodological diversity" needs concrete classifier rules (empirical, theoretical, survey, benchmark, opinion). Who assigns this, and when?
9. **How `ANALYZE_SOURCE` handles very long papers** — a 50-page paper can blow a mid-tier context window. Option A: the analyzer gets Section-summaries from a preprocessing step. Option B: the analyzer processes paper in overlapping chunks and merges. Unresolved.
10. **Replanner cadence** — every 10 task completions is a guess. Could be adaptive (trigger more often when task graph is fast-growing).

---

## 10. Summary of Design Commitments (v3)

- **Task-centric, agent-ephemeral.** Agents live only to execute a task.
- **Note-graph as shared workspace.** Typed, hyperlinked, Obsidian-exportable. Progressive disclosure.
- **Scanner / analyzer decomposition.** Cheap shallow relevance separated from expensive deep reading.
- **Closed set of orchestration patterns:** `single_researcher`, `maker_checker`, `multi_perspective`, `debate`, `ach`. Each specified as a sub-task DAG with explicit question-round framing.
- **ACH is the primary rigor tool** for sub-questions with ≥ 3 plausible positions. Escapes the binary trap.
- **Deterministic source tiering** with a preliminary-source upgrade policy and a confidence cap for preliminary-primary conclusions.
- **Confidence language ladder** — every confidence value shown in the report as both number and standardized phrase.
- **Claims are structured fields inside source notes**, with quote, methodology, and skepticism.
- **Triangulation across three vectors** (source type, time, method) as a first-class score feeding confidence.
- **Five bias countermeasures** woven into replanner, verifier, and ACH prompts.
- **Six completion gates** as a mandatory pre-report validation task.
- **Analytic Pyramid (10 sections)** as the report structure, with Finding / Insight / Recommendation strictly separated.
- **Search layer:** Serper + Semantic Scholar + arXiv + Unpaywall concrete for MVP.
- **User-in-the-loop** L0–L5, async-preferred, default-fallback mandatory.
- **No hard budgets.** Stop on task-graph exhaustion or scope-creep escalation.
- **Model tiering** by task type (cheap / mid / frontier).
- **Replanner uses Rounds 3/4/5** of the question ladder; runs bias-countermeasure checks.
- **Question-round discipline** in every agent prompt prevents drift into vague prompting.
