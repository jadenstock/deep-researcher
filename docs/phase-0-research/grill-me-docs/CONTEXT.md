# Context

Canonical terminology for the deep research agent project. Keep this file shallow — only terms that matter to the domain (research methodology, agent orchestration, output semantics), not implementation details.

---

## Pipeline phases

The end-to-end research run moves through four phases, in order. Each is named so that agents, prompts, and docs reference the same thing.

### Landscape Survey
The first active phase after intake. A broad, shallow retrieval pass over web + academic sources that maps the territory of the user's query *before* any research plan is written. Output: a `landscape_note` that summarizes what sub-topics, positions, and major sources exist in the literature. No deep reading here — the survey stays at title / abstract / snippet depth.

Not the same as "research." A landscape survey informs decomposition; it does not answer sub-questions.

### Decomposition
The research plan. The decomposer reads the landscape_note and produces sub-questions, classifications (`lookup` / `synthesis` / `contested` / `sparse`), and initial orchestration-pattern assignments. Decomposition is informed by real retrieved evidence, not LLM priors alone.

### Deep Research
The main loop. Sub-questions are worked via orchestration patterns (`single_researcher`, `maker_checker`, `multi_perspective`, `debate`, `ach`). The replanner periodically reviews and mutates the task graph. Source notes, verified claims, synthesis notes, and hypothesis notes accumulate in the note graph. This is where evidence is actually gathered and positions are stress-tested.

### Completion & Report
`VALIDATE_COMPLETION` runs the six completion gates. Remediation spawns if any fail. On pass, `WRITE_REPORT` emits the Analytic Pyramid report and exports the note graph as an Obsidian vault.

---

## Roles & agent types

Terms used in prompts and docs when referring to agents.

### Role-to-model routing
Every task type maps to a **role class** (`generative`, `judgment`, `cheap_deterministic`), and each role class maps to a **model family** via router configuration. The mapping is config, not code. Default policy (subject to empirical tuning): generative roles (`ANALYZE_SOURCE`, `SYNTHESIZE`, `WRITE_REPORT`) and primary orchestration (`DECOMPOSE`, `REPLAN`) use one family; judgment roles (`VERIFY_CLAIM`, `ADVERSARIAL_CRITIQUE`, `VALIDATE_COMPLETION` judgment-gates) use a different family; cheap-deterministic roles (`SCAN_SEARCH_RESULTS`, tier classifier) use the cheapest capable model regardless of family. Purpose: break same-model bias between generators and their adjudicators. Structured as ablation-ready — single-family runs are a supported baseline configuration.

### Scanner
A LOW-tier agent that reads titles, snippets, and shallow metadata and makes relevance judgments. Does not fetch full content. Used in the Landscape Survey (survey-scanner variant) and inside `single_researcher` (research-scanner variant).

### Analyzer
A MID-tier agent that reads full source content and produces a populated `source_note` (summary, claims with quotes, methodology evaluation, agent skepticism). The expensive-per-call side of the scanner/analyzer split.

### Verifier
A MID-tier agent invoked by `maker_checker` that independently re-retrieves and tests a specific claim using deliberately different queries than the original researcher. Always framed with the question-ladder's Round 3 "what would disprove this" discipline.

### Adversarial Critic
A MID-tier agent invoked by `debate` and `ach` that builds the strongest case *against* a position. Not the same as a verifier — a verifier tests a specific claim; a critic attacks a whole position.

### Replanner
A HIGH-tier periodic agent that reads the note graph and task graph and mutates the plan. Uses question-ladder Rounds 3, 4, and 5 (falsification, premortem, metacognitive). The professor-redistributing-tasks analog.

---

## Storage terms

### Note graph
The system's only long-term memory. Typed, hyperlinked notes stored in-memory during a run and exported as an Obsidian-compatible markdown vault at run end.

### Progressive disclosure
The discipline that agents receive a `NoteDigest` (`{id, type, title, description, link_summary}`) by default when reading notes, and must explicitly `load_note(id)` to pull the full content. Applies to every agent read, without exception. Purpose: prevent context bloat when the note graph is large.

### Source tier
A 1-through-5 semantic quality score assigned at fetch time. Tier 5 is rejected on retrieval (determined by a static deterministic reject list — social media, video platforms, vendor marketing, unattributed content). Tiers 1–4 are assigned by an **LLM tier classifier** that sees structured source metadata (title, authors, institution, venue, citation count, publication date, first 500 chars of cleaned content) and produces `{tier, rationale, classifier_confidence}`. Tiers are **semantic**, not structural — they reflect "does this source look and act like a rigorous piece of evidence?" rather than "is it in a peer-reviewed venue?" A well-cited rigorous preprint from a top lab can be Tier 1; a press-release-style post from the same lab is Tier 3. The classifier's rationale is stored in the source_note for auditability. Tier decisions are cached by URL — re-fetching a source reuses the prior classification.

### Peer-reviewed status
A separate boolean field on every source_note (`peer_reviewed: bool`), assigned deterministically from venue (does it appear in the peer-reviewed venue list?). Independent of tier. Used by the confidence formula: any claim primarily anchored on `peer_reviewed=False` sources gets the 0.80 confidence cap, **regardless of what tier those sources were assigned**. The cap is the load-bearing backstop that prevents overclaiming on findings that have not been externally validated, now that the tier itself is semantic rather than structural.

### Source note: full vs. stub
A `source_note` has a lifecycle. A **stub source_note** is created during the Landscape Survey — it carries title, venue, tier, citation count, and a one-line landscape contribution, but its `claims` and `evaluation` fields are unpopulated. A **full source_note** has claims (with quotes), methodology, limitations, and agent skepticism fully filled in. Deep-research's `ANALYZE_SOURCE` is the transition from stub to full; version bumps track the upgrade. A stub's fetch is cached, so the upgrade doesn't re-hit the network.

### Source extraction pipeline
The deterministic (no LLM) pipeline that turns a fetched URL into usable content for agents. Stages:
1. **Fetch** — `httpx` for HTML, direct PDF download for arXiv/DOI-resolved PDFs.
2. **Format conversion** — PDFs converted to markdown (MarkItDown or equivalent); HTML extracted via `trafilatura`.
3. **Size inspection** — content size measured in tokens *before* any LLM involvement.
4. **Routing**:
   - **Short content** (< 8K tokens): full content is the `structured_content`. Analyzer reads the whole thing.
   - **Long content** (≥ 8K tokens): produce a structured representation — title, abstract, section headers, first paragraph per section, table of contents, figure captions. Raw content is cached on disk and referenced via `raw_content_ref`.
5. **Cache** — all fetched content stored keyed on `(url, day_bucket)` for replay and for downstream `load_source_section` calls.

Applies to all sources, not just academic papers (long blog posts, government reports, technical docs all take the same path).

### Structured content
The representation of a long source that fits in an analyzer's context without reading the entire document. Contains abstract, section headers, first paragraph of each section, table of contents, figure captions. Deterministically constructed at fetch time. An analyzer reads the `structured_content` by default and pulls specific sections on demand via the `load_source_section` tool.

### load_source_section
A tool available to analyzer tasks. Given `(source_id, section_name)`, returns the verbatim content of that section. Used to expand a specific part of a long source when the analyzer determines it needs depth there. The analyzer's ReAct loop is: read `structured_content` → decide which sections matter for the claims being extracted → pull those sections → update extraction. Typical deep-read touches 2–3 sections, not the whole paper.

### Load-bearing claim
A claim that a BLUF-level judgment, a synthesis position, or a linchpin assumption rests on. Triggers verification (`maker_checker`), triangulation scoring, and Gate 1 / Gate 3 checks. Not every claim is load-bearing — many are context-only and don't need the same rigor.

### Open sub-question
A sub-question whose `question_note` does not yet have a final synthesis position. Used as the unit for measuring scope and scope-creep — not raw task count. A sub-question can be "open" while spawning many internal tasks (legitimate depth); scope-creep is a property of the *set* of open sub-questions, not of any one sub-question's internal task fan-out.

### Typed dependency
A directional relationship between tasks or sub-questions, declared at decomposition time and maintained by the replanner at runtime. Three types used in the domain:
- **`produces_context_for`** — upstream must synthesize before the downstream's research framing is meaningful (e.g., "what are the patterns?" produces context for "where are the open problems?").
- **`compared_against`** — two or more sibling sub-questions feed a later comparison.
- **`temporally_follows`** — one sub-question's scope depends on the temporal output of another (early-Z → current-Z → change-analysis).

Dependencies are **staged**: retrieval-phase tasks (SEARCH, SCAN, FETCH, ANALYZE_SOURCE) can run in parallel regardless of dependency type; only **synthesis-phase tasks** (SYNTHESIZE, UPDATE_QUESTION_NOTE when producing a final position) block on their upstream's synthesis. Preserves retrieval parallelism; enforces ordering only on cross-sub-question reasoning.

### Runtime-discovered dependency
A dependency the decomposer didn't anticipate but that emerges during deep research. Detected by the replanner reading the note graph — typical signals include one sub-question's synthesis containing claims structurally identical to another's framing, or one's research surfacing evidence that references another's resolved position. On detection, the replanner emits a task-graph mutation (add edge, merge sub-questions, or split) and records rationale in a `decision_note`.

### Scope-creep signal
A sub-question-level signal raised when breadth expands without closure: over K consecutive replan cycles, at least one new sub-question was added AND no sub-question was closed. Fires a `SCOPE_ESCALATION` to the user with a structured payload — the current open sub-questions, a proposed "narrow" option (cut-list), a proposed "broaden" option (extension-list), and a default recommendation (narrow, list cut items as `open_question_notes`). This is distinct from per-sub-question exhaustion, which is an internal replanner signal rather than a user-facing escalation.

### Sub-question exhaustion
An internal replanner signal (not a user escalation) raised when a single sub-question has spawned many internal tasks without producing a synthesis. Triggers replanner review — "should this sub-question be split, abandoned, or is it legitimately deep?" Not the same as scope-creep, which is about the sub-question *set* growing.

### Termination readiness check
A deterministic (no LLM) task that runs after a replan cycle emits no mutations. Confirms that the run is structurally ready to stop: no `PENDING` tasks, every sub-question has status `SYNTHESIZED`, scope-creep has not been escalated-and-user-chose-broaden, and each contested sub-question has had at least one disconfirmation attempt (`ADVERSARIAL_CRITIQUE` / `debate` / `ach` completed). The check exists because the replanner's silence alone is not sufficient evidence that research is done — a same-family LLM making the "stop" call and the "validate" call can rubber-stamp premature termination. This check is strictly structural and orthogonal to the replanner's judgment. Only after it passes does `VALIDATE_COMPLETION` run.

### Replanner mutation budget
A per-cycle limit on how many graph mutations the replanner can emit (add/edit/abandon task, add dependency, merge/split sub-question). Configurable; default small (~3). Excess proposed mutations are written to the cycle's `decision_note` as "to consider next cycle." Caps task-graph churn.

### Cascading mutation semantics
Rules for what happens to in-progress tasks when the replanner mutates their parent sub-question:
- **Merge sub-questions:** in-progress tasks complete and write into the merged `question_note`.
- **Split sub-question:** in-progress tasks pause (`BLOCKED_ON_SPLIT`); replanner specifies branch assignment; tasks resume.
- **Abandon sub-question:** in-progress tasks complete but outputs go to `decision_note` archive, not to a live `question_note`.
- **Add dependency:** in-progress synthesis completes once; any subsequent synthesis on the dependent sub-question blocks on the new upstream; a fresh synthesis spawns after upstream resolves.

---

## Output terms

### Analytic Pyramid
The canonical 10-section report structure. Problem → Research Design → BLUF (with AIMS) → Linchpin Assumptions → Evidence Summary → Alternative Hypotheses → Calibrated Uncertainty → Intelligence Gaps (diagnostic vs. acknowledged) → Milestones for Revision → Findings/Insights/Recommendations. An **optional 11th section — Relational Map** — is emitted for queries whose BLUF deliberately targets a taxonomy or landscape output (e.g., Test Case 4). Contains a Mermaid diagram rendered from the note graph.

### Relational Map
A Mermaid-syntax diagram embedded in the markdown report, rendered deterministically (no LLM) by traversing the note graph's typed edges. Uses the `architectural_relation` edge subtypes: `extends`, `alternative_to`, `composes_with`, `supersedes`, `open_problem_of`. Optional — skipped for queries that don't call for a structural output. A dedicated visualization agent (flow diagrams, timelines, evidence-tension heatmaps beyond Mermaid's reach) is out of MVP scope and noted as a follow-up.

### Finding / Insight / Recommendation
Three distinct levels that are **never collapsed** in the report. Finding = "what is" (raw data). Insight = "what does it mean" (interpretation). Recommendation = "what should be done" (action). A fact is never stated as a recommendation; an assumption is never stated as a finding.

### Calibrated confidence
A confidence value carries both a numeric score (from the confidence formula) and a standardized phrase from the language ladder (High / Moderate / Low). Reports always render both — never a bare number and never a bare adjective.

### Preliminary-anchor confidence cap
When a load-bearing claim is primarily supported by sources with `peer_reviewed=False`, its confidence is capped at 0.80 (Moderate ceiling; never High). Applies regardless of source tier. The cap is the backstop that prevents semantic-tier reasoning from overclaiming on unvalidated evidence.

### Intelligence gap
Unknown information, explicitly labeled in the report. Split into:
- **Diagnostically significant** — filling would change the conclusion.
- **Acknowledged** — noted but does not change the conclusion.
Never conflated.

---

## Methodology terms

### Question-ladder round
One of five framing modes for agent prompts. Round 1 (Starbursting — generate questions, not answers), Round 2 (Structural decomposition), Round 3 (Falsification — what would disprove this?), Round 4 (Premortem — imagine it was wrong), Round 5 (Metacognitive — audit the thinking). Every agent prompt declares its round; the round scaffolds the prompt's framing.

### Triangulation
A three-vector independence check for load-bearing claims: source-type diversity, time diversity, methodological diversity. "Three sources citing the same upstream paper do not count as three independent sources."

### ACH — Analysis of Competing Hypotheses
An orchestration pattern that enumerates all plausible hypotheses, scores each evidence item against each hypothesis, and accepts the hypothesis with the **lowest inconsistency score** (not the most supporting evidence). Resists confirmation bias. Used for sub-questions where ≥ 3 positions are surfaced with meaningful evidence.

### Completion gate
One of six checks run by `VALIDATE_COMPLETION` before report writing: methodological veracity, survival of disconfirmation, linchpin stability, consensus through dissent, standardized confidence, falsifiability commitment. Failure spawns remediation (bounded to ≤ 2 cycles).

---

## What this project is not

- Not a training pipeline. API-only; no fine-tuning.
- Not a production observability system. Basic tracing only.
- Not a general-purpose RAG system. Progressive disclosure over a note graph; no embedding index.
- Not a persistent memory system. Every run starts fresh; no cross-session memory.
