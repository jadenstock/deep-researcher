# Source-corpus scaling plan

Companion to [`scaling-architecture.md`](scaling-architecture.md), which
covers multi-user / operability scaling. This plan covers a different
axis: **what breaks inside a single run as the source count per run
grows** from the current ~20–50 to 200, 500, or more.

Scope discipline: this is about the corpus (source notes, readings,
content) inside one `NoteMemory`. Cross-run persistence and multi-user
concerns belong in the other doc.

---

## Where the single-run corpus will break first

Ordered by "first thing that degrades quality or cost as sources per
run grow."

| # | Limitation | Where it lives today | What breaks as sources grow |
|---|---|---|---|
| 1 | **`list_source_notes` returns the full corpus as dicts** | `agents/tools/notes.py:317` | Every analyst calls this before dispatching a scout; landscape calls it between rounds. At 50 sources the return is already ~10–20 KB per call. Input-token cost per agent turn scales with corpus size. |
| 2 | **Researcher opening prompt silently truncates at 80** | `agents/researcher.py:_render_source_list` (`max_rows=80`) | Beyond 80 sources the researcher sees an arbitrary prefix with an `(N more omitted)` footer. No ranking, no topic signal — the researcher cannot tell what it is missing. |
| 3 | **URL dedup only; no semantic dedup** | `agents/memory.py:_normalize_url` | Same paper appears as arXiv abstract + arXiv PDF + DOI + publisher URL + tracking-paramed link. The "same" source lives 3–5 times. Dedup failure compounds #1 and #2. |
| 4 | **`readings` list grows unboundedly on hot sources** | `agents/tools/notes.py:update_source_after_reading` | Every (agent, question) pair appends a full reading (claims + quotes) to the source note. Each update `model_copy`-rewrites the whole `SourceNoteMetadata` → O(readings²) churn. `load_note` returns the whole pile. |
| 5 | **`note.content` carries full cleaned body text** | `agents/tools/fetch.py` → writes body to `Note.content` | `load_note` dumps the full body into the agent's context. An analyst that greedy-loads 5 long papers eats 50–100 KB. No chunking, no query-conditioned extraction. |
| 6 | **Single `asyncio.Lock` serializes every write** | `agents/memory.py:NoteMemory._lock` | With many parallel analyst/scout commits plus #4's full-object rewrites, the lock becomes a bottleneck on burst fan-in. |
| 7 | **Event publisher fan-out is per-mutation** | `agents/events.py` + `NoteMemory.create`/`update` | Every note create and every reading append fires a separate event. At 500 sources × N readings the UI stream is saturated. |
| 8 | **No reading reuse across questions** | same as #4 | Two sibling analysts with overlapping angles append two readings to the same source instead of sharing. M questions × K shared sources = M·K readings with heavy overlap. |

Items 1–3 degrade quality and cost **at today's corpus sizes if runs
are allowed to scout more aggressively** — they are the ones worth
touching before the others become relevant. 4–5 matter once a corpus
regularly exceeds 100 sources. 6–8 are real but later.

---

## Recommended improvements

### Phase A — stop bleeding input tokens on the list-sources path

Fix items **#1 and #2** together. They are the same underlying gap:
the corpus is shown as a flat dump instead of a queryable index.

- Add required filter params to `list_source_notes`:
  `tier_min`, `topics` (any-match), `for_question_id`
  (returns sources already analyzed for that question),
  `exclude_analyzed_for_question`, `limit`, `offset`.
- Return a terse one-line projection per source: `id`, `title`,
  `tier`, `state`, `n_readings`, `topics`. Drop `summary`, drop
  `analyzed_for_questions`. Callers that want detail call `load_note`.
- In `researcher.py:_render_source_list`, rank before truncation
  (tier ascending, then topic coverage) and emit a grouped summary
  (`"N sources, tier breakdown: {1: x, 2: y, …}, topics: {…}"`)
  instead of a raw list. Give the researcher a `browse_sources(filter=…)`
  tool to pull detail on demand.

Outcome: per-turn input tokens for analysts stop scaling linearly with
corpus size. The researcher stops flying blind past source 80.

Relative complexity: small. Mostly tool-surface and prompt edits.

### Phase B — semantic dedup at `create_source_note`

Fix item **#3**. The goal is "calling create on the same paper via
different URLs returns the same existing `source_id`."

- Extend `_normalize_url` to strip common tracking params
  (`utm_*`, `ref`, `fbclid`, `gclid`) and normalize arXiv IDs
  (collapse `abs/` vs `pdf/`, drop version suffix). Keep the
  conservative spirit — still just URL-level, still trivial.
- Add a second dedup pass keyed on `(doi)` and on `(arxiv_id)` when
  either is present. Both already live on `SourceNoteMetadata`.
- Leave fuzzy title/author dedup out of scope — the error mode there
  (false merge of two different papers with similar titles) is worse
  than the duplicate it would prevent.

Outcome: corpus size stays honest. #1/#2 stay small. Downstream cost
drops in proportion to the current dupe rate.

Relative complexity: small to moderate. The tricky bit is picking the
canonical URL when two records merge.

### Phase C — split readings and content off the source note

Fix items **#4 and #5**. Both are instances of "the source note is
carrying payload it should not be carrying."

- Move `readings` off `SourceNoteMetadata` into a separate indexed
  store on `NoteMemory`: `readings_by_source_id: dict[NoteID, list[ReadingEntry]]`.
  `load_note(source_id)` returns only the source header.
  Introduce `load_readings(source_id, for_question_id=None)` that
  returns readings filtered by question.
- Move `content` off `Note.content` for source notes into a content
  store keyed by `source_id` (`ContentStore` with an in-memory
  implementation now, pluggable later — meshes cleanly with the
  `scaling-architecture.md` item 1 work when that lands).
- Add `read_source(id, query)` that does lightweight retrieval over
  the body (sentence-window or top-K BM25 — anything better than
  "dump the whole body into context") and returns only relevant
  chunks. Deprecate using `load_note` to read source content.

Outcome: analyst context cost stops scaling with per-source body size
and per-source reading count. Hot sources stop causing O(readings²)
write amplification.

Relative complexity: moderate. Touches `NoteMemory`, a couple of
tools, and the analyst prompt. Needs migration thinking if
persistence lands before this (serialized shape changes).

### Phase D — later, if load warrants it

These are worth naming so they are not forgotten, but none of them
block anything today.

- **#6 lock sharding** — per-note-id lock for updates, global lock
  only for secondary-index mutations in `create`. Worth doing only
  after Phase C removes the large-object rewrite cost per update.
- **#7 event coalescing** — batch `on_note_*` events over a short
  window (~50 ms) when many notes are mutating from parallel
  dispatches. Tightly coupled to how the UI consumes events.
- **#8 reading reuse** — before appending a reading, check whether an
  existing reading's `relevance_note` + claims already cover the
  current angle; if yes, link to the existing reading from the new
  question note instead of duplicating. Needs a similarity signal,
  which is where this stops being cheap.

---

## Sequencing rationale

A → B → C is the right order because each phase removes a failure
mode that makes the next phase's measurement easier:

- Phase A makes input-token cost per turn independent of corpus
  size, so later gains from B and C are measurable against a flat
  baseline instead of a rising one.
- Phase B reduces the effective corpus size, which makes Phase C's
  content-store design choices easier to size.
- Phase C changes the durable shape of source notes. Doing it after
  A and B means the reshape is done once, against a known-stable
  corpus surface, rather than being redone as A/B land.

D is deferred because the lock, event stream, and reading-reuse
bottlenecks only show up once A–C have pushed per-run corpus size
past where the cheaper fixes stop helping.

---

## Engineering verdict

- **Under-engineered?** At today's corpus sizes (≤50 sources/run),
  no — the flat dict + flat list is the right shape for a prototype.
- **Over-engineered?** No existing scaffolding to remove.
- **Perfectly engineered for today, deliberately not for tomorrow.**
  The breakages above are real consequences of that choice, not
  design mistakes. Phase A buys the most headroom per unit of
  change and is worth doing first.

---

## Appendix: concrete measurements to take before starting

None of the phases above should be started without a baseline, so
the improvement is measurable rather than assumed. For a representative
run at the current corpus size:

1. Input tokens per analyst turn, averaged across the run.
2. Duplicate-source rate: `(sources created) / (unique (doi ∪ arxiv_id
   ∪ normalized_url))`. Anything above ~1.15 means Phase B has real
   headroom.
3. Max `len(readings)` observed on a single source note. If this is
   reliably ≤2 the Phase C reading split is premature; if it reaches
   5+ the case is strong.
4. Bytes of `Note.content` loaded into analyst context per run.
   Instrument `load_note` to log size for `NoteType.SOURCE` calls.

The same four numbers after each phase lands are the acceptance
signal.
