# Future directions

Post-MVP directions for the deep research agent, grouped by the
kind of work each represents — product, infrastructure, research,
etc. — rather than by priority.

---

## 1. UX

Product-surface work. Most of this is about letting the user bring
more context in, take more out, and stay in the loop while a run is
happening.

- **File inputs.** Let the user attach PDFs, notes, prior reports,
  CSVs etc. as seed material for a run.
- **File outputs.** First-class artifacts beyond the final report:
  structured claim tables, bibliographies, intermediate notes, the
  landscape brief, etc.
- **Concurrent runs.** Ability to kick off and monitor multiple
  research runs at once from the same UI.
- **Mid-run clarifying questions.** The agent can pause and ask the
  user questions when it detects scope ambiguity or a consequential
  fork. Biggest single UX win here: prevents scope creep and
  increases alignment with what the user actually wanted.
- **Follow-up questions on a completed run.** User can ask
  follow-ups against a finished run's note graph — the next query
  reuses the existing evidence, extends the graph rather than
  starting fresh, and only searches for what the current graph
  can't already answer. Makes a single run the start of a
  conversation rather than a one-shot report.

---

## 2. Engineering / scale

The class of things that would come up if we tried to take this from
"one developer, one laptop" to dozens or hundreds of concurrent
users.

- **Hosted note memory.** Move the in-memory note graph to a hosted
  store so notes survive restarts and can be shared across workers.
- **RAG over notes.** Retrieval over the note corpus so the note
  system can scale *within* a run (larger working set than fits in
  context) and *across* runs (reuse prior research).
- **Hosted agent runner.** Replace the local `asyncio` orchestrator
  with a proper job runner — durable state, retries, queueing,
  per-run isolation.
- **Scalable web interface.** Move off single-process Streamlit to
  something that survives many concurrent sessions.
- **Scalable model hosting.** Routing, rate-limit handling,
  failover, and cost controls at a level appropriate for multi-user
  load rather than one user's keys.
- **Observability.** Real structured logging and trace export
  (per-run, per-agent, per-tool-call) so we can debug and
  cost-account production runs.

---

## 3. Eval and performance optimization

Moving from "we tune knobs by feel" to "we tune knobs against a
measurement." This is the prerequisite for almost everything else
being evaluable.

- **Pick the target eval(s).** There are open-source deep-research
  evals we could adopt; real work is deciding which ones reflect
  the behavior we actually care about.
- **Prompt optimization.** Systematic rather than by-hand iteration
  on the agent prompts.
- **Config tuning.** The agent has a lot of knobs (budgets, tier
  assignments, fan-out widths, recursion depths). It's unclear
  which settings are optimal for which query shapes; an eval
  harness lets us actually find out.
- **Self-reflection / auto-improvement.** Mechanisms for the agent
  to critique and revise its own behavior, either within a run or
  between runs.

---

## 4. New capabilities: visuals and code execution

Expands the kinds of questions the system can actually answer.

- **Visual generation.** Charts, diagrams, and figures as
  first-class outputs.
- **Lightweight code execution.** The agent can run short data
  analysis scripts as part of answering a question.
- **Heavyweight code execution.** Automated experiments,
  reproducibility checks, verification of claims against data.
  This is the path toward a more autonomous-researcher shape rather
  than a literature-synthesis shape.

---

## 5. Speed and cost

- **Context management for cache hits.** Structure prompts and
  message ordering to maximize cached-token reuse across turns.
- **Cheaper-model routing.** Identify which sub-tasks can be
  demoted to smaller/cheaper models without quality loss.
- **More parallelism.** Find more work that can fan out rather
  than run serially.

---

## 6. Data sources and extraction

The research is only as good as what goes in.

- **More data sources.** Beyond web search: academic indexes,
  internal corpora, structured databases, etc.
- **Better data sources.** Quality > quantity; bias toward sources
  with lower noise and better provenance.
- **Better PDF extraction.** PDFs are a major quality bottleneck
  today; better extraction directly improves evidence fidelity.

---

## 7. Agent behavior optimization

Call this "agent optimization" as distinct from prompt optimization —
the behavior encoded into the researcher and analyst loops, not
just the words in the system prompt.

- **Better verification systems.** Stronger checks on claims,
  citations, and internal consistency, owned by code rather than
  by the LLM's own judgment.
- **More advanced research methodologies.** Encode known-good
  patterns for how to approach different query shapes.
- **Move control out of prompts.** Today a lot of the orchestration
  logic ("when to stop", "when to recurse", "when to ask for
  review") is expressed in prompt text. Pushing more of that into
  real code and verification steps makes the behavior more
  testable and more stable across model swaps.
