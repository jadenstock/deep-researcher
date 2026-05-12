# Deep Research Agent — Initial Design (TDD v2)

**Status:** iteration 2. Revised from `tdd.md` (v1) after Jaden's first pass.
**Scope:** API-based deep research agent. No model training. Target: take-home deliverable — full design + MVP implementation.
**Grounded in:** `phase-0-research/findings.md`, `phase-0-research/thoughts.md`, `revisions-v1.md`, and a short search-API research pass.

**Changes from v1:**
- **Storage model inverted.** v1 was claim-centric; v2 is **note-centric**. Claims are structured fields inside source notes, not top-level entities. The note graph (Obsidian-style markdown + wikilinks) is the storage substrate. See §4, §5.6.
- **Search layer concrete.** v1 listed "Brave/Serper/arXiv" loosely; v2 specifies Serper + Semantic Scholar + arXiv + OpenAlex + PubMed + Unpaywall with a clear role for each. See §5.4.
- Minor edits to §4 (data model), §5.2 (scheduler now owns note serialization), §6 (walkthrough updated).

---

## 1. Problem Statement

Given a natural-language research query, produce a structured report that:
- Answers the query with claims explicitly separated from their evidence.
- Flags confidence per claim and surfaces source agreement / disagreement.
- Iterates across multiple research threads, handles conflicting sources, and stays honest about what it couldn't resolve.

Non-scoped: evaluation infrastructure, debugging observability, graceful-degradation architecture, continual improvement loops. Deferred to post-MVP.

---

## 2. Design Goals and Non-Goals

### Goals

1. **Task-centric architecture.** Tasks are the unit of work. Agents are ephemeral workers spun up per task.
2. **Plan is mutable.** The task graph evolves during execution. A dedicated replanner agent periodically reviews and revises.
3. **Note-graph as shared workspace.** A typed, hyperlinked note system is the single source of truth for what the agent knows. Agents read and write notes; notes link to each other; progressive disclosure keeps context manageable.
4. **Claim traceability.** Every factual statement in the output traces to a source note with a quoted passage, a confidence score, and a deterministic source tier.
5. **Model tiering by task type.** Cheap models do cheap work. Frontier models do synthesis / claim generation / final report.
6. **User-in-the-loop as a first-class control.** Configurable interactivity (L0–L5). Agent can pause and ask the user mid-research on meaningful branch points.
7. **Verification is mandatory on load-bearing claims**, optionally with adversarial framing.
8. **Closed set of orchestration patterns** instantiable as tasks.
9. **Concrete, researched search layer** — no hand-waving about which APIs to use.

### Non-Goals

- Fine-tuning or training any model.
- Self-improvement loops that automatically modify prompts.
- Long-lived agent personas or cross-session persistent memory.
- Production-grade observability infra.
- Automatic graceful degradation beyond basic retry.
- End-of-run self-reflection as a first-class feature (revisit post-MVP).
- Full RAG (embedding-backed retrieval over notes). Explicitly out of scope — progressive disclosure handles context management instead.

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
│  INTAKE (DECOMPOSE task)                                                  │
│   · classify sub-questions (lookup / synthesis / contested / sparse)     │
│   · create question_notes in the note graph                              │
│   · emit initial task graph                                              │
└─────────────────────────────┬────────────────────────────────────────────┘
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  ORCHESTRATOR LOOP                                                        │
│    ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐   │
│    │ TASK SCHEDULER   │──▶│ AGENT EXECUTOR    │──▶│ NOTE GRAPH       │   │
│    │ · picks next     │   │ · model routing   │   │ · typed notes    │   │
│    │ · serializes     │   │ · fork context    │   │ · hyperlinks     │   │
│    │   note writes    │◀──│ · spawn sub-tasks │   │ · progressive    │   │
│    └──────────────────┘   └──────────────────┘   │   disclosure     │   │
│           │                       │              └──────────────────┘   │
│           │                       ▼                       │              │
│           │              ┌──────────────────┐             │              │
│           │              │ SEARCH & RETRIEVE│             │              │
│           │              │ · web (Serper)   │             │              │
│           │              │ · academic       │             │              │
│           │              │ · PDF fetch      │             │              │
│           │              │ · tier tagging   │             │              │
│           │              │ · cache          │             │              │
│           │              └──────────────────┘             │              │
│           ▼                                               ▼              │
│    ┌──────────────────┐                           ┌──────────────────┐  │
│    │ REPLANNER        │                           │ VERIFIER PATTERN │  │
│    │ (periodic task)  │                           │ (load-bearing    │  │
│    │                  │                           │  claims)         │  │
│    └──────────────────┘                           └──────────────────┘  │
│           │                                                              │
│           ▼                                                              │
│    ┌──────────────────┐                                                  │
│    │ USER GATEWAY     │                                                  │
│    │ (L0–L5, async-   │                                                  │
│    │  preferred)      │                                                  │
│    └──────────────────┘                                                  │
└─────────────────────────────┬────────────────────────────────────────────┘
                              │ all tasks closed (progress exhausted)
                              ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  FINAL SYNTHESIS (WRITE_REPORT task)                                      │
│   · manager-tier agent assembles report from note graph                   │
│   · structured output: claims | evidence | confidence | source agreement  │
└─────────────────────────────┬────────────────────────────────────────────┘
                              ▼
                         USER (report + Obsidian vault export)
```

### 3.2 Architectural principles

1. **Everything is a task.** Agents are ephemeral; tasks persist.
2. **Notes are the memory.** Agents communicate through the note graph, not direct messaging.
3. **Progressive disclosure everywhere.** Default view of a note is `{id, type, title, description, link_summary}`. Full content loaded explicitly via `load_note(id)`.
4. **Deterministic where it matters.** Source tiering, confidence formulas, note types — rule-based. LLM judgment reserved for content generation and high-level orchestration.

---

## 4. Core Data Model

### 4.1 Task

```python
Task {
  id: TaskID
  parent_id: TaskID | None
  goal: str                            # natural-language objective
  type: TaskType                       # see §4.3
  tier: TaskTier                       # LOW | MID | HIGH — drives model routing
  pattern: OrchestrationPattern | None # for pattern-wrapping tasks
  status: PENDING | RUNNING | DONE | ESCALATED | ABANDONED
  success_criteria: str                # what "done" looks like
  depends_on: [TaskID]
  reads_notes: [NoteID]                # notes this task is expected to read
  writes_notes: [NoteID]               # notes this task has written to
  spawned_sub_tasks: [TaskID]
  created_at, completed_at
}
```

### 4.2 Note (the heart of v2)

```python
Note {
  id: NoteID
  type: NoteType                       # source | question | synthesis | decision | open_question
  title: str                           # always loaded (progressive disclosure)
  description: str                     # ≤ 2 sentences, always loaded
  content: str                         # markdown body; loaded on demand
  links: [Link]                        # typed edges
  metadata: dict                       # type-specific structured fields
  version: int                         # optimistic concurrency
  last_modified_by: TaskID
  last_modified_at: timestamp
  created_by: TaskID
  created_at: timestamp
}

Link {
  target_id: NoteID
  edge_type: EdgeType                  # supports | refutes | cites | addresses | follows_up | child_of
  context: str | None                  # e.g., the quote being cited
}
```

### 4.3 Note types

| Type | Purpose | Structured `metadata` fields |
|------|---------|------------------------------|
| `source_note` | One per retrieved source. The agent's understanding of a paper/page. | `{url, title, authors, venue, year, tier, raw_content_ref, summary, claims: [ClaimItem], evaluation: EvalItem}` |
| `question_note` | One per sub-question. The agent's working synthesis for this question. | `{original_question, classification, current_position, verification_status, addressed_by: [TaskID], status}` |
| `synthesis_note` | Cross-cutting synthesis across multiple questions. | `{question_note_ids: [NoteID], synthesis_text, open_tensions: [str]}` |
| `decision_note` | Logs a decision the agent made (pattern selection, scope change, user escalation). | `{decision_type, rationale, chosen_option, alternatives: [str]}` |
| `open_question_note` | Flagged follow-ups or unresolved items. | `{source_question_id, why_unresolved, suggested_next_step}` |

### 4.4 Structures inside source notes

Claims are **not** top-level entities. They live as items inside a `source_note`:

```python
ClaimItem {                            # inside source_note.metadata.claims
  id: str                              # unique within the note
  text: str                            # the claim
  quote: str                           # verbatim supporting passage from the source
  page_or_section: str | None          # where in the source
  extractor_confidence: float          # how well does the quote support the claim?
}

EvalItem {                             # inside source_note.metadata.evaluation
  methodology: str                     # empirical | theoretical | opinion | survey | benchmark
  sample_size: int | None
  reproducibility: HIGH | MEDIUM | LOW | UNKNOWN
  limitations_noted_by_authors: [str]
  agent_skepticism: str                # 1-3 sentences from the agent on why to trust or not
}
```

When a question note references a claim from a source note, it links to the source note with `edge_type=supports` or `refutes` and puts the claim id + quote in `Link.context`. The claim lives in one place (the source note) but is referenced from many places (question notes, synthesis notes).

### 4.5 Invariants

- Every claim has a `quote` — unquoted claims are rejected at extraction.
- `source_note.metadata.tier` is assigned deterministically at retrieval time (§6).
- Notes are versioned; concurrent-write conflicts are detected via version mismatch and handled by the scheduler (§5.6).
- The note graph is the only long-term memory; all agent communication passes through it.

---

## 5. Components in Detail

### 5.1 Intake (`DECOMPOSE` task)

Single HIGH-tier task. Input: raw user query + interactivity level.

Output:
1. Creates `question_note`s in the note graph, one per sub-question.
2. Classifies each sub-question (lookup / synthesis / contested / sparse).
3. Assigns a default orchestration pattern per sub-question.
4. Emits initial task graph — typically one `RESEARCH_SUBQUESTION` task per question note.
5. Creates a `decision_note` recording the decomposition choice.

If interactivity ≥ L3 and decomposition confidence is low, intake emits a `SCOPE_ESCALATION` before returning. Otherwise commits and continues.

### 5.2 Task Scheduler

- Maintains the task graph.
- Picks the next ready task (deps met, status `PENDING`).
- Dispatches tasks honoring parallelism constraints (LOW-tier tasks parallelize freely; MID/HIGH serialize per question to avoid verifier thrash).
- **Serializes all note writes.** Agents don't write directly to the note graph — they emit `NoteMutation` records in their task output, and the scheduler applies them in order. This is the concurrent-write strategy (§5.6).
- Triggers periodic `REPLAN` tasks (default every 10 completions).
- Listens for task completions and updates the DAG.

### 5.3 Agent Executor

Stateless. Given a task:
1. Routes to a model based on `task.tier` (cheap / mid / frontier).
2. Forks a fresh context window. Loads the task goal + progressive-disclosure views of `reads_notes` + the immediate parent task's summary output. **Not** the full note graph.
3. Runs the agent loop (ReAct-style).
4. Emits structured output: note mutations + optional sub-tasks + completion verdict.
5. Dies.

Agent tools include (minimum set):
- `load_note(id)` — expand a note to full content.
- `search_notes(query, type_filter)` — title/description keyword search across the note graph. Fast, no embedding.
- `web_search(query)`, `academic_search(query)`, `fetch_and_extract(url)` — search/retrieval tools (§5.4).
- `create_note(type, title, ...)`, `edit_note(id, patch)` — note mutations (queued through the scheduler).
- `spawn_task(goal, type, pattern?)` — spawns sub-task.
- `ask_user(question, options, default)` — issues a user escalation (honors interactivity level).

### 5.4 Search & Retrieval Layer

**This is the part most revised from v1.** Concrete APIs:

#### Primary web search

- **Serper API** — chosen for MVP. 2,500 free searches/month, Google-backed, $50/mo if exceeded. Returns `{title, link, snippet, position, sitelinks}`.
- Rationale: most generous free tier, Google-quality results.

#### Academic search — cited papers, citation graph, metadata

- **Semantic Scholar Academic Graph API** — primary academic backbone. Free, no key required (key available for higher rate limits). 200M papers. Endpoints used:
  - `/graph/v1/paper/search?query=...` — search.
  - `/graph/v1/paper/{id}?fields=title,authors,venue,year,citationCount,references,citations` — metadata.
  - `/graph/v1/paper/{id}/citations?fields=...` — papers that cite this one.
  - `/graph/v1/paper/{id}/references?fields=...` — papers this one cites.
- **arXiv API** — direct arXiv query for recency (Semantic Scholar may lag on the latest preprints). Free, no key. Used by the `arxiv` PyPI package.
- **OpenAlex API** — secondary source for citation metadata, venue resolution, institutional info. Requires a free API key as of 2025 ($1/day of free usage). Used when Semantic Scholar doesn't cover a paper or rate-limits.
- **PubMed E-utilities** — used when the research topic is biomedical or AI-adjacent-biomedical. Free, no key (3 req/s); free key (10 req/s). `esearch` + `esummary` + `efetch`.

#### PDF / full-text resolution

- **Unpaywall API** — DOI → open-access PDF URL. Free. Used when we have a DOI but need the actual full text.
- Direct fetch for arXiv PDFs (URL pattern).
- For paywalled content we can't bypass: fall back to abstract + metadata only; the source note's `evaluation.agent_skepticism` flags this.

#### HTML / page extraction

- **`trafilatura`** + **`httpx`** — fetch + main-content extraction for any web URL.

#### Citation-count-as-quality-signal

Citation count from Semantic Scholar (or OpenAlex fallback) is **one input** to source tiering but not the tier itself. A paper with 10,000 citations is still tier-2 if it's only on arXiv; it becomes tier-1 when we detect it's also in a peer-reviewed venue. Citation count feeds into the confidence formula (§5.5) as an agreement signal, not the primary quality gate.

#### Caching

All fetches cached on disk, keyed by `(tool, args_hash, retrieval_date_bucket)`. Replay mode reads from cache without network — critical for iteration cost.

#### Tool interface (agent-visible)

```python
web_search(query, count=10) -> [SearchHit]
academic_search(query, source="semantic_scholar" | "arxiv" | "openalex" | "pubmed", count=10) -> [PaperHit]
get_paper_metadata(paper_id, source) -> PaperMetadata  # includes citation count
get_papers_citing(paper_id, source) -> [PaperHit]     # for citation-graph traversal
get_papers_cited_by(paper_id, source) -> [PaperHit]
fetch_and_extract(url) -> SourceNote                   # HTML + tier tagging
resolve_oa_pdf(doi) -> url | None                      # Unpaywall
```

The `fetch_and_extract` tool is the one that creates a `source_note` in the graph (via the scheduler).

### 5.5 Source Tiering (Deterministic) and Confidence

**Tiering happens at fetch time in `fetch_and_extract` / paper metadata resolution.** Rule table:

| Tier | Rule |
|------|------|
| **TIER_1 — Peer-reviewed** | Venue matches a known peer-reviewed publication set (NeurIPS, ICML, ICLR, ACL, EMNLP, AAAI, IJCAI, CVPR, Nature, Science, PNAS, IEEE journals, Cochrane, etc.). Detected via Semantic Scholar / OpenAlex venue field, DOI resolution, or URL pattern. |
| **TIER_2 — Preprint / reputable institutional** | arXiv without acceptance, bioRxiv, medRxiv, SSRN; major AI lab blogs (Anthropic, OpenAI, DeepMind, Google Research, Meta AI); RAND, NIST, National Academies. |
| **TIER_3 — Established tech publications / vendor docs** | AWS / Azure / GCP engineering blogs, major framework docs (LangChain, PyTorch, Hugging Face), standards bodies (MCP spec, W3C), MIT Tech Review, IEEE Spectrum. |
| **TIER_4 — Everything else** | Random blogs, unattributed content, vendor marketing, community aggregators. Deleted on retrieval unless explicitly requested. |

**Confidence formula** (for claims referenced from question notes):
```
tier_weight = {TIER_1: 0.9, TIER_2: 0.75, TIER_3: 0.55, TIER_4: 0.3}
confidence_base = max(tier_weight[s.tier] for s in supporting_sources)
agreement_bonus = min(0.10 * (unique_supporting_sources - 1), 0.30)
contradiction_penalty = 0.20 if any refuting source else 0
citation_signal = min(log10(max_citation_count) / 5, 0.10)    # citation-count boost, capped
confidence = clip(confidence_base + agreement_bonus + citation_signal - contradiction_penalty, 0, 1)
```

Verification status is separate from confidence: a `CONTESTED` claim can still have high confidence on one position if that position has stronger evidence.

### 5.6 Note Graph (replaces v1's Claim+Evidence Store)

**Storage substrate:**
- In-memory typed dict keyed by `NoteID` for MVP.
- Exported to an **Obsidian-compatible markdown vault** at the end of every run. Each note becomes `{note_id}_{slug}.md` with YAML frontmatter for metadata and `[[wikilinks]]` for note-to-note edges. User opens the vault in Obsidian post-run.

**Progressive-disclosure view (default returned to agents):**
```python
NoteDigest {
  id, type, title, description,
  link_summary: {              # counts, not full list
    outbound_supports: int,
    outbound_refutes: int,
    outbound_cites: int,
    outbound_addresses: int,
    inbound_references: int,
  },
  metadata_headers: dict       # type-specific one-line summary (e.g., for source: tier, year, citation_count)
}
```

`load_note(id)` returns the full `Note` including body and link list.
`search_notes(query, type_filter)` returns a ranked list of `NoteDigest`s.

**Concurrent-write strategy:**
- Agents never mutate notes directly. They emit `NoteMutation {op: create | edit, note_id?, fields}` records in their task output.
- The scheduler applies mutations **serially** in task-completion order. Each mutation bumps the version field.
- **Edit conflicts** (task A edits note N based on version 3, task B emitted a mutation that already advanced N to version 4) → scheduler detects via version mismatch and re-dispatches task A with the updated note, with a prompt addendum: "this note was updated between your read and write. Reconcile."
- This strategy works because note writes are infrequent relative to LLM calls (every task produces ~1–5 mutations, not a stream). Serialization is cheap.

### 5.7 Orchestration Patterns (closed set)

Named templates that expand into sub-task graphs. Higher-tier agents instantiate them.

- **`single_researcher`** — default for LOW/MID sub-questions. One `RESEARCH_SUBQUESTION` task; produces source_notes; updates the question_note.
- **`maker_checker`** — researcher produces claims → `VERIFY_CLAIM` task re-retrieves independently → updates claim's verification_status. Default for `contested` and `sparse` sub-questions.
- **`debate`** — researcher produces position A → `ADVERSARIAL_CRITIQUE` task produces the strongest counter (position B) → third agent judges which is better-supported. Triggered when two source notes contain contradictory claims on the same question.
- **`multi_perspective`** — decomposer generates N queries from different stakeholder framings → parallel research → merged into one question_note with multiple positions. Used upfront for `contested` sub-questions to avoid one-sided evidence collection.

Pattern selection:
1. **At decomposition** — classification drives default pattern.
2. **At runtime** — mid-tier agents detect conflict in the note graph (two source_notes, contradictory claims on the same question_note) and spawn a `debate` task.

### 5.8 Verification

`VERIFY_CLAIM` task receives a claim (quoted + its source) and must independently retrieve and evaluate.

- Issues its own searches, deliberately re-phrased to avoid the same retrieval path.
- Writes its findings as a new `source_note` if novel, or adds support/refute links from existing notes.
- Updates the target claim's `verification_status`.

**Adversarial mode:** the verifier's prompt is reframed as "find the strongest evidence *against* this claim." An adversary that finds nothing is a stronger signal than a default-mode confirmation.

**Triggered for:**
- Claims with `tier_base < TIER_2`.
- Claims on sub-questions classified as `contested` or `sparse`.
- Claims the final synthesis will load-bear on (manager decides before `WRITE_REPORT`).

### 5.9 Replanner

`REPLAN` task. Spawned periodically by the scheduler (every N completions; N default = 10).

Reads: the full note graph (progressive-disclosure view) + the current task graph.

Evaluates:
- Is the original goal still being served?
- Have sub-questions drifted beyond their original scope?
- Are there new sub-questions suggested by accumulated claims?
- Are there open tasks that no longer contribute?

Emits: task graph mutations (add/edit/abandon tasks) + a `decision_note` recording the rationale. If it detects unmanageable scope creep, raises a `SCOPE_ESCALATION`.

### 5.10 User Gateway (Interactivity Layer)

Levels:

| L | Behavior |
|---|----------|
| L0 | Never ask. Always use the default fallback. |
| L1 | Ask only on high-risk decisions (scope-expanding beyond original decomposition). |
| L2 | Ask on major branch points (multiple plausible directions with material scope differences). |
| L3 | Ask on branch points + intake decomposition confirmation. **Default.** |
| L4 | Ask on branch points + verify contested claims before synthesis. |
| L5 | Ask at every meaningful decision. |

- **Async-preferred:** on `SCOPE_ESCALATION`, the system continues safe parallel work while waiting.
- **Default fallback mandatory:** every escalation has a pre-computed default. Timeout → proceed with default, annotate the report.
- MVP supports L0 and L3 concretely; L1/L2/L4/L5 are stubbed with L3 behavior.

### 5.11 Stopping and Progress

No hard tool-call or round budgets. Driven by:

1. **Task completion.** When the task graph has no open tasks and the replanner emits nothing new, research ends.
2. **Progress stall detection.** Over the last M completions (default 10), if new-task-creation-rate ≥ completion-rate for K consecutive replan cycles (default 2), raise `SCOPE_ESCALATION`: "scope is creeping — keep looking, or narrow and list follow-ups?"

Context-limit hits are not a stopping signal — they trigger context compaction (observation masking per research) or sub-task delegation.

`WRITE_REPORT` assembles the final output from the note graph.

---

## 6. End-to-End Flow: Example Walkthrough

**Query (Test Case 2):** "Is chain-of-thought prompting an effective reasoning strategy for LLMs, or does it primarily improve output formatting?"

1. **Intake** (`DECOMPOSE`, frontier model):
   - Creates `question_note`s:
     - Q1: "Evidence that CoT improves reasoning" — `contested`
     - Q2: "Evidence that CoT primarily improves formatting" — `contested`
     - Q3: "Conditions under which CoT helps vs. not" — `synthesis`
   - Default patterns: Q1 + Q2 → `multi_perspective` + `maker_checker`; Q3 → `single_researcher`.
   - Emits a `decision_note` for the decomposition.

2. **Parallel research.** Three `RESEARCH_SUBQUESTION` tasks (mid-tier) run in parallel.
   - Each spawns LOW-tier `SEARCH` (via Semantic Scholar + arXiv) and `FETCH_AND_EXTRACT` tasks.
   - Each fetch creates a `source_note`. Tiering: Wei et al. CoT paper → TIER_1 (NeurIPS), follow-ups on arXiv → TIER_2, blog posts → rejected.
   - MID-tier `EXTRACT_CLAIMS` tasks populate each `source_note`'s claims + evaluation fields.
   - Question notes get updated with links to source notes: Q1 has `supports`-links to papers claiming CoT helps reasoning; Q2 has `supports`-links to Madaan et al. critique.

3. **Verification.** MID-tier `VERIFY_CLAIM` tasks run adversarially on load-bearing claims from Q1 and Q2.
   - Adversarial verifier for Q1 finds the Madaan et al. critique independently. Updates the claim on Q1 to `CONTESTED`.

4. **Replanner** fires at 10 completions.
   - Detects overlapping evidence on Q1 and Q2.
   - Spawns a `debate` task: "resolve whether CoT's effect is reasoning or formatting, given current evidence."

5. **Debate** resolves to a nuanced position: "depends on task and model size." Written as a `synthesis_note` linking Q1, Q2, and the relevant source_notes.

6. **Progress stall check.** New-task-rate < completion-rate. No escalation.

7. **`WRITE_REPORT`** (frontier). Assembles from the note graph:
   - One section per `question_note`, with the question's synthesis + quoted evidence.
   - Contested claims get "position A vs. position B" framing with source agreement counts.
   - Final section lists `open_question_note`s as follow-ups.

8. **Export.** Note graph written to Obsidian-compatible vault at `./runs/{run_id}/vault/`.

---

## 7. MVP vs. Deferred

### MVP

- Task graph + scheduler (in-memory, serial note writes).
- Intake / `DECOMPOSE`.
- Agent executor with model routing (cheap / mid / frontier).
- Search layer: Serper + Semantic Scholar + arXiv + Unpaywall (+ `trafilatura` for HTML). **PubMed, OpenAlex deferred to post-MVP unless a test case demands them.**
- Deterministic source tiering.
- Note graph with 5 note types (`source`, `question`, `synthesis`, `decision`, `open_question`).
- Obsidian vault export.
- Orchestration patterns: `single_researcher`, `maker_checker`, `multi_perspective`, `debate`.
- Verifier (default + adversarial).
- Replanner (periodic).
- User gateway at L0 and L3.
- Stopping on task completion + scope-creep escalation.
- `WRITE_REPORT` → structured markdown.

### Deferred

- L1, L2, L4, L5 interactivity levels.
- PubMed / OpenAlex (add when a test case needs them).
- Self-reflection loop after run completion.
- Observability UI / rich tracing.
- Production-grade graceful degradation.
- LLM-judge evaluation harness.
- Automatic prompt improvement.
- Cross-session persistent memory.
- Embedding-backed RAG over notes.

---

## 8. Comparison / Ablation for the Take-Home

Strongest candidates given this design:

1. **With vs. without the verifier tier.** Turn off `VERIFY_CLAIM`. Measure claim-level faithfulness (quote→claim support rate) + the number of contested claims detected.
2. **Note-graph architecture vs. single-agent baseline.** Same query, same search tools, one ReAct agent with no note abstraction. Measure coverage of sub-questions, source diversity, and whether contradictions are surfaced.
3. **Multi-perspective query generation vs. single-prompt search** on Test Case 2 (contested). Measure source diversity and whether both positions are surfaced.

**Recommendation:** Lead with #1 — it isolates the verifier as a design decision and has an obvious quality metric. Add #3 if time allows; it demonstrates the pattern-selection idea.

---

## 9. Open Questions (for Phase-2 Research)

Load-bearing unknowns worth stress-testing before implementation:

1. **Progress-stall detection threshold.** N=10, K=2 are guesses. What do deployed research agents use?
2. **Adversarial verifier prompt framing.** Over-zealous adversaries can invalidate well-supported claims; weak ones miss real issues. Worth looking for documented prompts or training setups.
3. **Pattern selection at runtime — trigger criteria.** "Detect direct contradiction → spawn debate" is under-specified. What exactly counts as a contradiction in the note graph? Structural rule? LLM judgment?
4. **Confidence formula calibration.** The formula in §5.5 is a guess. Expected to iterate with real outputs.
5. **Sub-question independence assumption.** Some queries (Test Case 4: multi-agent systems taxonomy) may need sequential sub-question build-up. How does the scheduler handle that?
6. **Replan frequency.** N=10 is a guess.
7. **Context compaction default** within a single agent run — observation masking vs. summarization for the ReAct loop inside a task.
8. **Note-write conflict frequency.** If conflicts are rare, serial writes through the scheduler are fine. If frequent, we may need a different strategy.
9. **Obsidian export format details.** YAML frontmatter conventions + wikilink resolution for non-standard edge types. Minor but worth getting right.

---

## 10. Summary of Design Commitments (v2)

- **Task-centric, agent-ephemeral.** Agents live only to execute a task.
- **Note-graph as shared workspace.** Typed, hyperlinked, markdown-backed, Obsidian-exportable. Progressive disclosure everywhere.
- **Claims are structured fields inside source notes**, not top-level entities.
- **Deterministic source tiering** from a rule table; citation-count feeds confidence, not tier.
- **Concrete search layer:** Serper (web) + Semantic Scholar (academic primary) + arXiv (AI recency) + Unpaywall (PDF resolution); OpenAlex + PubMed as extensions.
- **Closed set of orchestration patterns:** `single_researcher`, `maker_checker`, `multi_perspective`, `debate`.
- **Mandatory verification** for load-bearing claims, optionally adversarial.
- **Configurable interactivity** L0–L5; async-preferred; default-fallback mandatory.
- **No hard budgets**; stop on task-graph completion or scope-creep escalation.
- **Model tiering** per task type (cheap / mid / frontier).
- **Replanning is a periodic task**, not a reactive-only mutation.
