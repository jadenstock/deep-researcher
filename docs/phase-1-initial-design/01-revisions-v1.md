# TDD Revision Notes — Round 1

Captured from Jaden's first pass through `tdd.md`. Addressed in the next TDD revision.

---

## R1: Storage model — claim-centric is too restrictive

**Problem.** The current design makes `Claim` the fundamental unit. Jaden pushes back: storage should support multiple note types, not just claims.

### Desired storage shape

- **Note system, not a claim store.** Notes are a scratchpad abstraction — agents read and write them.
- **Multiple note types.** Minimum:
  - **Source note** — one per retrieved source. Contains: condensed summary, extracted claims, **evaluation** (how was the work evaluated? do we trust it? is it opinion or empirical?).
  - **Research-question note** — one per sub-question. Owned conceptually by mid-tier agents; links out to the sub-tasks and source notes that address it.
  - (Additional types likely: claim notes, synthesis notes, decision/plan notes, open-question notes.)
- **Hyperlinks between notes.** Graph structure, not a flat table. Source → Question, Question → Claim, Claim → Source, etc.
- **Obsidian-like mental model.** Possibly literally Obsidian for the storage substrate, so the user can browse the agent's thinking after the run. Hard constraint: markdown-based + hyperlinkable.
- **Progressive disclosure.** Title + description load by default. Subagents open the full note on demand. Avoids context bloat when agents pull in many notes.
- **Editable and updatable by agents.** Not append-only; agents can revise notes in place.
- **Concurrent writes need handling.** Needs a concrete strategy (locking, optimistic-CAS, last-writer-wins, or serialization through a broker).
- **Explicitly not full RAG.** No embedding index, no vector store. Out of scope.

### Implications for the TDD

- `Claim` and `Evidence` remain as **data structures inside source notes**, not as top-level storage units.
- Source tiering still applies — tied to source notes.
- The Claim + Evidence Store section (§5.6) becomes a **Note System** section.
- Progressive disclosure means agent context receives {note.id, note.type, note.title, note.description} by default, and a `load_note(id)` tool for full content.

---

## R2: Search layer — needs concrete research on APIs

**Problem.** The TDD's search layer (§5.4) currently lists "Brave / Serper / arXiv" without evaluating alternatives. Jaden wants specifics before committing.

### Specific questions to answer via research

1. **PubMed API** — does it exist, what's the access model, what does it return?
2. **Open academic dataset search** — is there an API? Google Dataset Search was mentioned as possibly having one.
3. **Paper popularity / citation counts** — is there a tool that, given a paper, returns its citation count?
4. **Citation-graph traversal** — "give me all papers that cite this paper." Is there an API for this?
5. **Web search APIs** — Brave vs. Serper vs. others; what are tradeoffs?
6. **Academic search** — arXiv is one option. Semantic Scholar? OpenAlex? Which gives us the richest metadata?

### Domain focus

The agent is primarily looking at **academic claims, often about AI**. That means:
- arXiv is load-bearing (most AI research).
- Peer-reviewed venue resolution matters (to distinguish TIER_1 from TIER_2).
- Citation counts are useful for source weighting and for "find related work" navigation.
- PubMed matters if we want coverage beyond AI (biomedical topics).

---

## Plan for next iteration

1. Run targeted research on the search-API questions (R2). Keep it tight — this isn't a full phase-2 notebook research round, just concrete API lookups.
2. Revise the TDD:
   - Replace §5.6 (Claim + Evidence Store) with a Note System section (R1).
   - Expand §5.4 (Search & Retrieval) with concrete API choices (R2).
   - Update the data model in §4 to reflect note-first rather than claim-first.
3. Return with the revised TDD for another pass.
