# Design decisions

Two-part doc.

1. **Major design decisions in the system** — every substantive
   choice the architecture commits to, as it exists in `src/`.
   Each entry is one-sentence-scoped.
2. **The assessment's "questions worth thinking about"** — how
   the system as built answers each one, briefly.

---

## Part 1. Major design decisions

### Shape of a run

- **Four real agents: landscape, researcher, analyst, scout.** One
  run = one landscape call (unless skipped) followed by one
  researcher loop that dispatches analysts; each analyst dispatches
  scouts. No decomposer, no replanner, no verifier or debate agent.
- **Agent-driven orchestration, not harness-driven.** The harness
  calls `research_run(deps, query)` and waits. Decomposition,
  investigation, review, and "when to stop" are all expressed in
  the researcher's prompt and tool-use loop — the harness has no
  completion gates or termination-readiness checks.
- **One-shot, fire-and-forget.** No user-in-the-loop, no
  interactivity levels, no mid-run clarifying questions, no
  scope-creep escalations. The UI streams events but doesn't
  accept mid-run input.
- **Skip-landscape toggle.** `RunConfig.skip_landscape` bypasses
  the landscape phase; real config knob used for A/B testing the
  landscape node.

### Orchestration and concurrency

- **Parallelism via pydantic-ai concurrent tool calls.** The
  researcher can emit multiple `investigate_question` calls in
  one turn; pydantic-ai dispatches them concurrently. Analysts
  parallelize their `scout` calls the same way. No explicit
  `asyncio.gather` in the orchestration layer.
- **Budgets, not replans.** Three budget knobs cap work:
  `analyst_budget` (investigate_question calls per run),
  `scout_budget_per_analyst`, and `scout_search_budget`. All
  three analyst modes (explore / verify / adversarial) draw from
  the same `analyst_budget` — no separate pool for critical
  investigations.
- **Budget exhaustion via `ModelRetry`.** When a tool is out of
  budget it raises pydantic-ai's `ModelRetry`, which surfaces to
  the agent as "commit now." No dynamic re-budgeting; no
  second-chance dispatch.
- **Shared `Deps` across the agent tree.** `Deps` (memory, config,
  routing, http_client, event publisher) is passed into every
  sub-agent, so sub-agents see each other's notes without
  re-searching.
- **Per-agent `contextvar` for event tagging.** Each agent sets
  `_CURRENT_AGENT_ID` at entry; tool events read it to tag their
  output. `contextvars` propagate through `asyncio.gather`, so
  concurrent sub-agent trees stay correctly attributed.

### Memory and notes

- **Shared append-only note graph (`NoteMemory`), async-locked on
  writes.** Single instance per run, passed via `Deps`. Writes
  take an `asyncio.Lock`; reads are lock-free.
- **Four note types.** `LANDSCAPE`, `SOURCE`, `QUESTION`,
  `SYNTHESIS` (fallback-only). No decision notes, no hypothesis
  notes, no open-question notes.
- **Progressive disclosure is real.** The researcher never loads
  raw source content — it gets `get_research_state()` (counts,
  status, budget) and calls `load_note(id)` on demand. The
  analyst gets `list_source_notes()` (metadata + summary) and
  `load_note(id)` for content.
- **Source note lifecycle: `SCOUTED` → `FETCHED` → `ANALYZED`.**
  `content_kind` field tracks `full_text` / `abstract_only` /
  `unavailable`. Lifecycle state is on the note, not in a
  separate index.
- **Append-only `readings` list per source.** Each analyst that
  reads a source appends a `ReadingEntry` (who, for which
  question, claims extracted, relevance note) rather than
  overwriting. Multiple analysts can read the same source without
  clobbering each other.
- **First-writer-wins on tier / summary / peer_reviewed.** These
  are set by the first analyst to analyze a source and not
  overwritten.
- **URL dedup on source creation.** Trivial normalization
  (lowercased scheme/host, trailing slash stripped) — good enough
  for cross-provider dedup.

### Sources and retrieval

- **Three providers: Brave (web), Semantic Scholar (academic),
  arXiv (preprints).** All optional except arXiv; Brave and S2
  are skipped if no API key.
- **Per-provider sliding-window rate limiting.** Process-wide,
  not per-run. Free-tier intervals (Brave 1.5s, S2 3.0s or 1.0s
  authenticated, arXiv 3.0s). Configurable in `local.toml`.
- **Extraction: trafilatura for HTML, MarkItDown for PDFs.** PDFs
  capped at 15MB and first 20 pages; HTML that returns
  abstract-only falls back to a `pdf_url` if supplied. Hard cap
  of 60K chars markdown returned to the agent per fetch.
- **Tier is agent-assigned, not classifier-assigned.** Scout
  supplies a `tier_guess` on skim; analyst re-rates on deep-read
  via `update_source_after_reading`. Tiers don't gate inclusion
  — they're advisory for the agent's own weighting.
- **No reject list, no size-first routing, no stub→full
  lifecycle distinction beyond SCOUTED/FETCHED/ANALYZED.**
- **Citation traversal.** `find_related_papers` uses S2's
  citation graph (citing / cited-by direction). Requires DOI or
  arXiv URL on the seed.

### Model and role routing

- **Role-to-model routing is real.** `agent_factory.py` selects a
  model at agent build time from `(RoleClass, TaskTier)`.
- **Three role classes.** `GENERATIVE` (landscape, researcher,
  analyst-explore), `JUDGMENT` (analyst-verify,
  analyst-adversarial), `CHEAP_DETERMINISTIC` (scout).
- **Three task tiers.** `HIGH` (researcher), `MID` (landscape,
  analyst, scout), `LOW` (defined but unused).
- **Diversity at the judgment layer.** Verify and adversarial
  analyst modes route to a different model family than the
  generative analyst explore mode. Family is inferred from the
  `provider/model` prefix on `model_id`.
- **Configurable via routing YAML + per-run overrides.**
  `RunConfig.model_overrides` maps `(TaskTier, RoleClass)` to
  full model IDs. Defaults from `config/routing.yaml`; overrides
  applied at `Deps` build time.
- **All traffic through OpenAI-compatible endpoint (LiteLLM
  router).** No direct provider SDKs in the hot path.

### Agent behaviors worth calling out

- **Landscape runs up to 4 internal search rounds.** Prompt-
  enforced, not harness-enforced. Emits a brief + leaves
  `SCOUTED` source notes in memory for the researcher to reuse.
- **Researcher has four tools.** `get_research_state`,
  `investigate_question(question, mode)`, `load_note`,
  `answer_question`. The loop is entirely tool-driven; the
  harness watches for `answer_question` to be called.
- **Analyst has three dispatch modes: explore / verify /
  adversarial.** Mode is a string on the `investigate_question`
  call; the analyst's system prompt gets a framing block
  appended based on mode. Verify and adversarial route to the
  judgment family; explore stays generative.
- **Scout is the only agent that actually fetches content.**
  Scout-fetch is a separate tool from the agent's search tools.
  Scout emits source notes with content pre-populated.

### Output

- **Report is freeform markdown on the root question note's
  `report_markdown` metadata field.** No templated section
  structure, no Analytic Pyramid, no 10-section layout. The
  researcher's prompt asks for specific content — limitations,
  open issues, inline citations — but the shape is the model's.
- **Inline citations as `[source-id]`.** Renderable because
  source notes are keyed by id.
- **Confidence is a 3-level enum.** `ConfidenceLevel ∈
  {HIGH, MEDIUM, LOW}`. No numeric score, no confidence formula,
  no language ladder.
- **`open_issues` and `disagreements` fields on question
  notes.** Analyst prompt requires explicit gap-naming when
  sources don't cover something. These feed the report.
- **`limitations` list on the top-level `ResearcherReport`.**
  Populated by the researcher before committing.
- **Fallback report composition.** If the researcher ends
  without calling `answer_question`, a fallback report is
  reconstructed from any `SYNTHESIZED` sub-question notes and
  stored as a `SYNTHESIS` note. Keeps crashed runs partially
  usable.
- **No Obsidian vault export, no relational map, no Mermaid
  rendering.** Notes are stored as flat JSON.

### Infrastructure

- **Event streaming for UI.** All note creates/updates and all
  agent start/done emit structured events via an
  `EventPublisher` protocol. CLI gets a no-op publisher; the
  server gets one that feeds WebSocket clients.
- **Per-model token tracking.** `TokenUsageTracker` aggregates
  cost by `model_id` and `agent_type`. Persisted to
  `token_usage.json` per run.
- **No prompt caching.** All agent contexts are sent to the
  router verbatim every turn.
- **Per-run config surfaced to the UI.** Budget knobs and model
  overrides are exposed in the Streamlit settings panel.

---

## Part 2. The assessment's questions — how this design answers them

Brief one-section-per-question, answered against the code as built.

### When should a plan be a commitment vs. a suggestion?

There is no explicit plan object in the system. The only
committed structure is the fixed agent tree (landscape →
researcher → analyst → scout) and the fixed tool surface each
agent has. Within that, the researcher's decomposition, dispatch
order, and when-to-stop are all agent-driven and effectively
suggestions — the harness doesn't validate them. The closest
thing to a commitment is the budget: `analyst_budget` and its
siblings are hard caps enforced via `ModelRetry`, which is the
one structural bound the researcher can't talk its way out of.

### Vague question in, concrete research out. What happens in between?

Two concrete transformations, both agent-driven:
1. **Landscape phase** — blocking pre-search that produces a
   landscape brief + a seeded set of `SCOUTED` source notes the
   researcher inherits. Skippable via `skip_landscape`.
2. **Researcher prompt loop** — the researcher receives the query,
   the brief, and the source list, and its prompt instructs it
   to decompose into sub-questions, dispatch analysts, review,
   and commit a final report.

Decomposition itself is not a separate agent or tool — it's part
of the researcher's prompt. Sub-questions become `QUESTION`
notes when the researcher calls `investigate_question`.

### What should agents share, and what should they not?

**Share** (implemented as `Deps` + `NoteMemory`): the note graph,
the config, the routing table, the HTTP client, and the event
publisher. All sub-agents see notes written by their siblings
because `Deps` is passed through. **Don't share:** internal
turn-by-turn state. Sub-agents each run their own pydantic-ai
loop with their own context window; they communicate only
through notes. The append-only `readings` list means two
analysts reading the same source don't overwrite each other's
interpretations.

### When does adding another agent help vs. hurt?

In code, the "another agent" decision shows up as the
`investigate_question(mode=...)` call. Verify and adversarial
modes route to a different model family than the explore mode
(role routing picks `JUDGMENT` vs. `GENERATIVE`), so dispatching
them costs a budget slot but gets a structurally-different model
reading the question. Dispatching another `explore` in the same
family would mostly duplicate work. The budget is the forcing
function: because all three modes share `analyst_budget`, the
researcher has to be selective about when a second pass is worth
it.

### Dead ends, contradictions, hallucinations — how does the system stay honest?

Four mechanisms, all partial:
1. **Inline `[source-id]` citations.** Required by prompt; every
   claim is supposed to name its source. Not structurally
   enforced (the harness doesn't validate citations).
2. **Append-only `readings`.** Multiple analysts reading the
   same source leave independent `ReadingEntry`s, so a second
   reader's contradiction isn't overwritten by the first
   reader's agreement.
3. **`verify` / `adversarial` analyst modes** with judgment-family
   routing — the researcher can re-investigate a shaky
   sub-question with a different model framed to look for
   counter-evidence.
4. **`open_issues` / `disagreements` / `limitations` fields** on
   question notes and the final report. Prompt-required: if a
   sub-question didn't resolve cleanly, the analyst names what
   it couldn't get to.

Structural checks (quote-anchored claims, confidence caps,
gate-based validation) are not implemented. Honesty is
load-bearing on prompts and on the diverse-family routing.

### How do you prevent agents from converging on a comfortable, wrong answer?

One real mechanism: **diverse-family routing on the judgment
role.** Verify and adversarial analyst calls go to a different
model family than the generative researcher/explore. This
breaks same-model bias between generator and adjudicator. Beyond
that, the `ReadingEntry` append-only structure means a later
analyst can disagree with an earlier one without losing the
earlier reading's claims. Triangulation, ACH scoring, and
structural disconfirmation gates are not implemented.

### Not all work is equally hard. What does that imply?

Two axes of routing, both real:
- **Role class.** `CHEAP_DETERMINISTIC` for scouts (skim + fetch
  + skim-rate); `GENERATIVE` for reading/writing; `JUDGMENT` for
  verification-mode analyst dispatches. Scouts don't touch
  expensive models.
- **Task tier.** `HIGH` for the researcher, `MID` for everyone
  else. `LOW` is defined in the enum but not currently mapped
  to any agent.

Search traffic is rate-limited per-provider process-wide, so
parallel sub-agents don't trample the API quota. There is no
size-based source routing — all fetched content flows through
the same extraction pipeline.

### When do you stop searching?

Three signals, all either agent-level or budget-level:
1. **Researcher calls `answer_question` on the root question.**
   This is the happy-path exit. The researcher decides.
2. **`analyst_budget` or `scout_*_budget` hits zero.** Tools
   start raising `ModelRetry` with a "commit now" message.
   Agents can't dispatch further sub-agents and have to write
   up what they have.
3. **Fallback report composition.** If the researcher never
   commits a root answer, the harness reconstructs a partial
   report from any `SYNTHESIZED` sub-question notes and returns
   that.

There is no deterministic termination-readiness check, no
six-gate validation, and no remediation loop. Stopping is fully
agent-and-budget driven.
