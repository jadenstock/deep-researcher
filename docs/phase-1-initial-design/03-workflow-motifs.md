# Workflow Motifs

Scratchpad for **workflow-level** design thoughts that aren't yet architecture-doc material. These are mental models for how agents collaborate, shaped by analogies to how humans do research. They inform implementation details (prompts, role boundaries, tool-use shape) without needing to commit to them in the TDD.

---

## M1: The Professor + Grad Students Model

### Mental model

A professor wants to survey a part of the literature. They have a few really good grad students. How does this actually unfold?

1. **Professor scopes high-level sub-portions** of the literature. Maybe 3–5 major threads worth investigating.
2. **Each thread is assigned to one grad student.** The student goes deep — reads a chunk of papers, builds a working mental model of that sub-domain, identifies the key results, open questions, and tensions.
3. **Students present back to the professor.** Each one delivers their synthesis.
4. **Professor redistributes based on what's interesting.** "Thread 2 is much richer than expected — let's double down. Thread 5 seems thin — drop it and add a new thread we discovered."
5. **Repeat for N rounds** until coverage is satisfying.

### Mapping to the current design

This maps cleanly onto what's in `tdd-v2.md`:

| Human role | System analog |
|---|---|
| Professor | Top-tier manager agent (HIGH-tier tasks: `DECOMPOSE`, `REPLAN`, `WRITE_REPORT`) |
| Grad student | Mid-tier agent per sub-question (`RESEARCH_SUBQUESTION` with `single_researcher` / `multi_perspective` / `maker_checker`) |
| Student-presents-back | Question notes updated; synthesis notes created; replanner reads them |
| Professor-redistributes | The `REPLAN` task mutating the task graph |
| "N rounds" | Periodic replanner cadence, not fixed rounds |

So the motif is *already expressed* in the architecture — the mapping just gives us a better shared vocabulary for talking about it.

### The wrinkle: scanner vs. analyzer split

The grad-student analogy has **one role**: the student who reads and synthesizes. But for LLM agents, there's a good argument to split that further:

- **Scanner agent** — sweeps the search tools, reads titles/abstracts/snippets, judges relevance quickly. Doesn't read in depth. Output: "this paper/page looks relevant, here's why, spin up a deeper task on it."
- **Analyzer agent** — receives a specific source, reads it carefully (or as carefully as context allows), extracts claims + evaluation + summary, populates the source note.

Why the split is attractive:
- Different cost profiles: scanner is high-volume / low-context (cheap model); analyzer is lower-volume / full-paper context (mid or frontier model, possibly larger context window).
- Different failure modes: scanner fails by missing relevant papers or flooding with noise; analyzer fails by misreading a specific paper.
- Different optimization levers: scanner benefits from query diversity / reranking; analyzer benefits from careful prompting and verification.
- Different stopping criteria: scanner stops when novelty decays in the search result stream; analyzer stops when the paper is parsed.

**In the current TDD, this is implicit in the task types** — `SEARCH` and `FETCH_AND_EXTRACT` are LOW-tier (scanner-like), `EXTRACT_CLAIMS` is MID-tier (analyzer-like). But the boundaries and handoff protocol aren't formalized. Worth making explicit if empirical evidence or literature supports a cleaner split.

### Invariant: everyone has the context they need

Both the scanner and the analyzer need enough shared context about the task to do their jobs — what is being researched, what has already been found, what's still open. In the note-graph design, this lives in the `question_note` that both agents read at dispatch time. That note *is* the shared-context mechanism. Good — no new primitive needed; we just have to make sure the progressive-disclosure view of the question note is rich enough.

---

## Research question for Phase 2

> Are there studied patterns for this? Is there an "optimal" way to split agent roles for literature survey?

Specific things worth looking into in the next research pass:

1. **Scanner / analyzer decomposition** in autonomous research agents — is this a documented pattern? Under what names? (Possible leads: "paper triage," "broker-searcher," "skim-then-read," "hierarchical reading," "dynamic reading depth.")
2. **Role decomposition in recent deep-research systems** — how do GPT Researcher, SFR-DeepResearch, LiteResearcher, Marco DeepResearch, AutoResearch-RL actually structure their roles? The phase-0 research covered architectural patterns (single-agent / multi-agent / hierarchical) but not this specific axis.
3. **Human-research workflow formalizations** — PRISMA (systematic literature review) prescribes explicit phases: identification → screening → eligibility → inclusion. Is there a crisp mapping from PRISMA phases to agent roles?
4. **Iterative re-scoping** — do any documented systems have an explicit "present back → redistribute → repeat" loop? What triggers a redistribution? How many rounds before diminishing returns?
5. **Context sharing across roles** — what's the documented best practice for scanner → analyzer handoff? Pass the whole source? A snippet + pointer? A prompt template?

If the research turns up a dominant pattern, we adopt it and formalize in TDD v3. If it turns up contested or sparse evidence (likely), we make a defensible choice and note it as a known open design decision.

---

## Adding more motifs

Future entries here can include other workflow analogies the user finds intuitive (e.g., "journalist and fact-checker," "librarian and reader," "peer review"). They serve as intuition scaffolding, not as commitments — the TDD stays the authoritative design.
