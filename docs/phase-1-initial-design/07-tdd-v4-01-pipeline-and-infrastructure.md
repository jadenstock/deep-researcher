# Deep Research Agent — TDD v4 — Pipeline and Infrastructure

**Covers:** §5.1 Landscape Survey, §5.2 Decomposition, §5.3 Scheduler, §5.4 Agent Executor + role routing, §5.5 Search & Retrieval, §5.6 Source Extraction, §5.7 Source Tiering + Confidence, §5.8 Question-Round Strategy.

See `07-tdd-v4-00-overview.md` for architecture diagram, data model, ADR index, and principles.

---

## 5.1 Landscape Survey (new, ADR 0001)

Phase 1 of the run. Single HIGH-tier, generative-role task: `LANDSCAPE_SURVEY`. Goal: map the territory before the decomposer decides how to slice it.

### Inputs

- Raw user query.
- Interactivity level.

### Sub-task DAG

```
                  ┌─── SEARCH (web, broad) ────────┐
                  ├─── SEARCH (academic, broad) ───┤
LANDSCAPE_SURVEY──┤                                ├──▶ SCAN_SEARCH_RESULTS
                  └─── SEARCH (arxiv direct)       ┘         │ top 5–10 candidates
                                                             │
                                                             ▼
                                           FETCH_AND_EXTRACT (fan-out, parallel)
                                                             │ stub source_notes
                                                             │ (tier-classified, peer-review tagged)
                                                             ▼
                                           SURVEY_ANALYSIS (single batched task, ADR 0002)
                                                  │
                                                  ▼ landscape_note
```

`SURVEY_ANALYSIS` is not a separate task type — it is the ReAct loop of `LANDSCAPE_SURVEY` itself. The agent reads the 5–10 stub source_notes in rounds within its own context (ADR 0002: cross-source reasoning is one task, not N analyses + a merge).

### Landscape note schema

```python
landscape_note.metadata = {
  themes: [ThemeItem],              # named topics / clusters present in the landscape
  positions: [PositionItem],        # stances observed on contested aspects
  key_sources: [SourceID],          # top sources per theme
  under_covered_areas: [str],       # areas where evidence looked thin
  methodology_distribution: {...},  # % empirical / theoretical / survey / benchmark / opinion
  tier_distribution: {...},         # count by tier
  peer_review_fraction: float,
  generated_at, raw_query
}
```

The landscape note is the decomposer's single input artifact. It is also written to the Obsidian vault so reviewers can audit "did the system understand the space before deciding how to research it?"

### Scope scaling

Survey depth scales with apparent query breadth:

- Narrow lookup (e.g., "what does MCP stand for?") — 3 sources, short survey.
- Standard research query — 5–10 sources.
- Broad / multi-facet query — up to 10; capped there for cost.

Determined heuristically from query length and entity count; tunable.

### Failure modes

- **Survey surfaces no useful sources.** (Sparse or emerging topic.) The landscape_note is emitted with an explicit `under_covered_areas` flag; decomposition proceeds with fewer classification constraints, biased toward `sparse` classifications.
- **Survey biased by first queries.** Mitigated by required multi-angle queries (web + academic + arxiv direct) and the agent's prompt requirement to diversify framing.
- **Survey redundancy with deep research.** Stub source_notes and fetch-cache entries carry forward; deep-research reuses them instead of re-fetching.

### Interactivity gate

At L3+, if the survey surfaces a material branching ("is this query about A or B?"), the user is consulted *after* the survey and *before* decomposition — with concrete evidence in hand, not with priors.

---

## 5.2 Decomposition (evidence-grounded)

Single HIGH-tier, generative task: `DECOMPOSE`. Inputs: raw query, interactivity level, **`landscape_note`**.

### Step 1 — AIMS scoping

Same as v3. The decomposer fills four fields before decomposing:

- **A** — Audience (default: "technical reader familiar with the domain").
- **I** — Issue: what specific problem is this query addressing?
- **M** — Message: what's the bottom-line judgment this research must produce?
- **S** — Storyline: what logical sequence takes a reader from evidence to conclusion?

AIMS is written into a `decision_note` and serves as a contract for the report's BLUF section.

### Step 2 — Starbursting / Round 1

Generate questions, not answers. The prompt explicitly asks:

- "What are the conditions under which this query would *not* have a clean answer?"
- "What sub-questions, if each independently answered, would let us answer the query?"
- "What does this query assume? Is the assumption always correct?"

The landscape_note is in context: the decomposer can ground its sub-questions in what the survey actually found.

### Step 3 — Classification (evidence-grounded)

Each sub-question is classified using the landscape_note as evidence — not LLM priors:

- `lookup` — single retrieval suffices; landscape shows a clear authoritative source.
- `synthesis` — multiple sources agree; no genuine controversy visible in the landscape.
- `contested` — landscape shows ≥ 2 distinct positions with non-trivial support.
- `sparse` — landscape's `under_covered_areas` lists this topic, or tier distribution is weak.

The **number of surfaced positions** in the landscape_note drives the `contested` sub-case:

- 2 positions visible → `multi_perspective` + (optionally) `debate`.
- ≥ 3 positions visible → `multi_perspective` + `ach`.

This is the core ADR 0001 change: ACH fires based on what exists, not what the LLM remembers.

### Step 4 — Pattern selection

| Classification | Default pattern |
|---|---|
| `lookup` | `single_researcher` |
| `synthesis` | `single_researcher` + `maker_checker` |
| `contested` (2 positions surfaced) | `multi_perspective` + `maker_checker` → may escalate to `debate` |
| `contested` (≥ 3 positions surfaced) | `multi_perspective` + `ach` |
| `sparse` | `multi_perspective` + `maker_checker` with explicit "evidence-thinness" expectation |

### Step 5 — Typed dependency identification (new, ADR 0006)

The decomposer's Round-2 prompt includes a dependency-identification step. For each pair of sub-questions, it assigns one of:

- `produces_context_for` — A's resolved position is needed for B's synthesis to be well-founded. (Example: "what are the patterns?" → "where are open problems?")
- `compared_against` — sub-questions jointly feed a compare/contrast synthesis.
- `temporally_follows` — one sub-question's answer chronologically follows another's and is only interpretable after it.
- `none` — independent.

The decomposer's output includes a dependency graph, not just a task list. Basic cycle check runs as output validation.

### Step 6 — Emit

Create `question_note`s (one per sub-question), emit the initial task graph (typically one pattern-invoking task per question, with typed-dep edges), commit a `decision_note` recording AIMS + decomposition rationale + dependency rationale.

### Interactivity gate (L3+)

If decomposition confidence is low, emit `SCOPE_ESCALATION` with a concrete default decomposition as the fallback.

---

## 5.3 Task Scheduler

The scheduler is deterministic state management. No LLM.

### Core responsibilities

- Maintains task graph + note graph.
- Dispatches next ready task.
- Serializes note writes through a mutation queue.
- Triggers periodic `REPLAN` (cadence configurable, default every 10 completions; ADR 0009).
- Triggers `CHECK_TERMINATION_READY` when the replanner emits no mutations.
- Emits `VALIDATE_COMPLETION` when termination-ready check passes.

### Staged waiting (ADR 0006)

Dependencies block at the synthesis phase only, not retrieval.

- Retrieval-phase task types (`SEARCH`, `SCAN_SEARCH_RESULTS`, `FETCH_AND_EXTRACT`, `ANALYZE_SOURCE`) have `dep_scope.retrieval_ignores = True`. They run in parallel regardless of upstream sub-question deps.
- Synthesis-phase task types (`QUESTION_SYNTHESIZE`, `SYNTHESIZE`, `VALIDATE_COMPLETION`) have `dep_scope.synthesis_waits = True`. They block in `BLOCKED_ON_SYNTHESIS_DEP` until upstream synthesis is DONE.

Effect: B's retrieval runs concurrently with A's synthesis; B's synthesis unblocks once A's synthesis lands.

### Cascade mutation semantics (ADR 0009)

When the replanner mutates a sub-question with in-progress tasks:

| Mutation | Behavior |
|---|---|
| **Merge A + B → AB** | Tasks on A and B complete and write into AB. No abort. Redundancy tolerated. |
| **Split A → A1 + A2** | In-progress tasks → `BLOCKED_ON_SPLIT`. Replanner specifies branch assignment; ambiguous cases recorded in a `decision_note`. Tasks resume targeting assigned branch. |
| **Abandon A** | In-progress tasks complete but write to `abandoned_sub_question_archive` decision_note, not to a live `question_note`. |
| **Add dependency edge upstream → downstream** | In-progress synthesis on `downstream` completes (no abort). Subsequent synthesis on `downstream` blocks on `upstream`'s synthesis. A fresh synthesis on `downstream` spawns after `upstream` resolves. |

---

## 5.4 Agent Executor + Role-to-Model Routing (ADR 0008)

The executor is stateless. Per task:

1. Resolve model: `(role, tier, task_type) → ModelID` via the run's routing config.
2. Fork fresh context: task goal + progressive-disclosure views of `reads_notes` + parent task summary + question-round context (§5.8).
3. Run the agent loop.
4. Emit structured output: note mutations + optional sub-tasks + verdict.
5. Die.

### Role classes

| Role class | Task types | Default family |
|---|---|---|
| **generative** | `LANDSCAPE_SURVEY`, `ANALYZE_SOURCE`, `QUESTION_SYNTHESIZE`, `SYNTHESIZE`, `WRITE_REPORT`, `DECOMPOSE`, `REPLAN` | Primary (e.g., Claude Sonnet 4.6 / Opus 4.7) |
| **judgment** | `VERIFY_CLAIM`, `ADVERSARIAL_CRITIQUE`, `ANALYZE_CONSISTENCY`, `VALIDATE_COMPLETION` (G2, G4) | Secondary (e.g., GPT-5) |
| **cheap_deterministic** | `SCAN_SEARCH_RESULTS`, source tier classifier, `CHECK_TERMINATION_READY` (no LLM) | Cheapest capable (e.g., Haiku 4.5) |

### Hard invariant

`VERIFY_CLAIM.model.family ≠ ANALYZE_SOURCE.model.family` for the specific source whose claim is being verified. Enforced at model-selection time by the executor, not by prompt discipline. Breaking this defeats the purpose of independent verification.

### Configuration

Routing policy is a **per-run config file**. A single run uses one consistent policy; different runs can vary for ablation (see §8 in doc 03). Fallback to single-family is a supported configuration (router unavailable, or single-family baseline).

### Agent tools (MVP set)

Unchanged from v3 plus one addition from ADR 0007:

- `load_note`, `search_notes`, `web_search`, `academic_search`, `get_paper_metadata`, `get_papers_citing`, `get_papers_cited_by`, `fetch_and_extract`, `resolve_oa_pdf`, `create_note`, `edit_note`, `spawn_task`, `ask_user`.
- **`load_source_section(source_id, section_name)`** — new (ADR 0007). Returns verbatim section content from the on-disk cache for sources stored as `structured_content`.

---

## 5.5 Search & Retrieval Layer

Unchanged from v3 in intent. Summarized here for completeness.

- **Serper** — primary web search (2,500/mo free, Google-backed).
- **Semantic Scholar** — primary academic (free, no key, 200M papers, citation graph).
- **arXiv API** — direct for AI/ML recency.
- **Unpaywall** — DOI → open-access PDF.
- **OpenAlex, PubMed** — feature-flagged for post-MVP or domain-specific use.
- **`trafilatura` + `httpx`** — HTML fetch + main-content extraction.
- **MarkItDown** — PDF-to-markdown conversion (ADR 0007).
- **Disk cache** keyed on `(tool, args_hash, day_bucket)`. Replay mode reads cache without network.

---

## 5.6 Source Extraction — Size-First Routing (ADR 0007)

Source extraction is deterministic and decided *before* any LLM is involved. `FETCH_AND_EXTRACT` runs this pipeline; `ANALYZE_SOURCE` consumes its output.

### Pipeline

1. **Fetch** — `httpx` for HTML, direct download for PDFs.
2. **Reject-list check** (ADR 0003) — short-circuits obvious junk (social media, unattributed aggregators, vendor marketing) to Tier 5 with no LLM call.
3. **Format conversion** — PDF → markdown via MarkItDown; HTML → markdown via `trafilatura`.
4. **Size inspection** — count tokens on the converted markdown.
5. **Route by size:**
   - **Short (< 8K tokens):** `structured_content = null`; analyzer reads full content.
   - **Long (≥ 8K tokens):** emit `structured_content = {title, abstract, section_headers, first_paragraph_of_each_section, table_of_contents, figure_captions}`. Full content stored on disk at `raw_content_ref`.
6. **Tier classification** — LLM tier classifier runs once per source at fetch time (§5.7).
7. **Cache** — content + tier + rationale stored on disk, keyed on `(url, day_bucket)`.

### Analyzer behavior

- Receives `structured_content` by default via progressive disclosure on the source_note.
- ReAct loop: read structured_content → decide which sections matter → pull them via `load_source_section` → extract verbatim-quoted claims → update source_note.
- For short content, the tool is available but unused — full text is already in context.

### Scope

All source types. Blog posts, government reports, standards documents, academic papers — size is the discriminator, not source type.

### What this is not

- **Not pre-summarization.** Analyzer reads verbatim section content. Claim quotes remain traceable to the original.
- **Not chunking + embedding + RAG.** No vector index built. Aligned with the "no full RAG" non-goal.
- **Not a separate task type.** `ANALYZE_SOURCE` stays as one task type. What changes is tool availability and prompt scaffolding.

### Fallback on unstructured content

When section structure is absent (unusual HTML, weird PDF generators), `structured_content` degrades to `{title, first_N_tokens}` and the analyzer pulls by offset rather than section name.

---

## 5.7 Source Tiering + Confidence (rewritten per ADR 0003)

### Tiering pipeline

1. **Deterministic reject list.** Domain against a static config. If match, set `tier = 5`, skip classifier. Primary categories: social media, video platforms, unattributed aggregators, vendor marketing, content farms.
2. **LLM tier classifier.** Input: `{title, authors, institution, venue string, citation_count, publication_date, first 500 chars of cleaned main content}`. Output: `{tier: 1..4, rationale: str, classifier_confidence: float}`. Runs at LOW tier, cheap_deterministic role class, low temperature, with a rubric prompt containing calibration anchors (see Open Questions in ADR 0003).
3. **Peer-reviewed flag** — deterministic. `peer_reviewed: bool` computed from a static list of peer-reviewed venues. Independent of semantic tier.
4. **Cache** — by URL. Subsequent fetches reuse classification + rationale. Cross-run consistency + clean ablation.

### Semantic tier definitions (ADR 0003)

| Tier | Semantics |
|------|-----------|
| **TIER_1** | Authoritative, rigorous, methodologically sound, extensively validated or from a source where validation is inherent (systematic reviews, peer-reviewed top-venue publications, Cochrane, major national academies). |
| **TIER_2** | Credible and methodologically sound; may still be preliminary. Rigorous preprints from recognized institutions with explicit methodology count here. |
| **TIER_3** | Relevant context with caveats. Established tech journals (MIT Tech Review, IEEE Spectrum), major AI-lab research blogs, engineering blogs from major clouds, standards bodies. Most preprints without strong corroboration land here. |
| **TIER_4** | Expert-opinion-in-refereed-venue (HBR-style). Acceptable to fill gaps; not for primary anchoring. |
| **TIER_5** | Reject list (auto) or classifier-assigned; never loaded into the corpus. |

Rationale is stored at `source_note.evaluation.tier_rationale` and is inspectable in the Obsidian vault.

### 0.80 preliminary-anchor confidence cap (load-bearing, ADR 0003)

When a claim's supporting evidence is primarily from sources with `peer_reviewed=False` — regardless of their semantic tier — the claim's confidence is **capped at 0.80 (Moderate)**. Never High. `source_note.evaluation.agent_skepticism` must explicitly state "primary evidence is preliminary; this reflects current state-of-the-art in a fast-moving field."

This is the backstop that makes the LLM-based semantic tiering safe. Even if the classifier over-tiers a rigorous preprint, the cap prevents the claim from being reported as High confidence.

### Confidence formula

```
tier_weight = {TIER_1: 0.9, TIER_2: 0.75, TIER_3: 0.55, TIER_4: 0.3}
confidence_base = max(tier_weight[s.tier] for s in supporting_sources)
agreement_bonus = min(0.10 * (unique_supporting_sources - 1), 0.30)
citation_signal = min(log10(max_citation_count + 1) / 5, 0.10)  # capped
contradiction_penalty = 0.20 if any refuting source else 0
triangulation_bonus = triangulation_score * 0.10  # see §5.16 (doc 03)

confidence_raw = clip(
  confidence_base + agreement_bonus + citation_signal
  + triangulation_bonus - contradiction_penalty,
  0, 1
)

confidence = min(confidence_raw, 0.80) if primarily_preliminary else confidence_raw
```

`primarily_preliminary` is determined by a majority of supporting sources having `peer_reviewed=False`.

### Confidence language ladder

Reports never show bare numbers or bare verbal qualifiers. Every claim carries both:

| Level | Numeric range | Language |
|-------|--------------|----------|
| **High** | 0.80–0.95 | "almost certainly", "highly likely", "we assess with high confidence" |
| **Moderate** | 0.55–0.80 | "likely", "probably", "we assess" |
| **Low** | 0.0–0.55 | "possible", "unlikely", "remote" |

Rendering format:

> The evidence [likely] supports the claim that X. *(Moderate confidence, 0.62; primarily preliminary evidence.)*

The translation is deterministic (helper function in `WRITE_REPORT`).

---

## 5.8 Question-Round Strategy

Every agent prompt declares a `question_round ∈ {1..5, None}`, which sets the framing discipline:

- **Round 1 — Starbursting.** Generate questions, not answers. Explore the space. Used by: `LANDSCAPE_SURVEY` (theme enumeration), `DECOMPOSE` (Step 2), ACH hypothesis enumeration.
- **Round 2 — Structural decomposition.** Break intractable into sub-components. Used by: `DECOMPOSE` (Step 3), `QUESTION_SYNTHESIZE`, `multi_perspective` merge.
- **Round 3 — Falsification.** "What evidence would *disprove* this?" Used by: `VERIFY_CLAIM` (adversarial mode), `ADVERSARIAL_CRITIQUE`, `REPLAN` synthesis review.
- **Round 4 — Premortem.** "Imagine this conclusion was wrong in 6 months; why?" Used by: `REPLAN`, `VALIDATE_COMPLETION` Gate 4.
- **Round 5 — Metacognitive.** "What gaps are diagnostically significant? Where might correlation-vs-causation confuse?" Used by: `REPLAN` saturation checks, ACH adjudication, `VALIDATE_COMPLETION` Gate 6.

The round-tag is a prompt scaffold. The agent's system prompt includes a canned instruction block for each round. This isn't magic — it's consistent framing that prevents drift into vague prompting as the loop gets deep.
