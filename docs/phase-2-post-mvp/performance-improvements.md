# Performance improvements

Goal: make an individual research run **faster** and **cheaper**
without changing what the system *does*. Architectural moves (queues,
persistence, multi-worker) live in `scaling-architecture.md`; this
doc is about the same single-run pipeline producing the same quality
of report at lower wall time and lower token spend.

Scope discipline: every item below names a specific performance
property of the current code, points at where the cost actually is,
and proposes a concrete change. Each one is orthogonal to the
ablation candidates in `ablation-ideas.md` — those ask "is this
structure worth its cost?"; this doc assumes the structure is
worth it and asks "can we make it cost less?"

---

## Where the time and tokens actually go

A rough decomposition of a typical MVP run, ordered by where the
cost sits. (Exact shares move with query shape; the ordering has
been stable across runs in `runs/`.)

| Bucket | Dominant contributor | Code pointer |
|---|---|---|
| Analyst model calls | `analyst.py` loop — deep-read, claim extraction | `agents/analyst.py` |
| Researcher Opus calls | HIGH-tier direction + review rounds | `agents/researcher.py:build_researcher` |
| Fetch + extract | trafilatura on HTML, MarkItDown on PDFs | `retrieval/fetch.py:fetch_and_extract` |
| Landscape pre-pass | scout fan-out + brief synthesis | `agents/landscape.py:landscape_run` |
| Search API latency | Brave 1 QPS serializes queries | `retrieval/brave.py` + `rate_limit.py` |
| Orchestration overhead | `get_research_state` rebuild, note-graph scans | `agents/researcher.py:get_research_state`, `agents/memory.py` |

Token-cost is dominated by (1) and (2). Wall-time is dominated by
(1), (3), and (5).

---

## Recommended improvements

Ranked by "expected $ + wall-time win per unit of engineering work,"
with a preference for changes that are compatible with the ablation
experiments already planned.

### 1. Prompt caching for agent system prompts

**Cost today.** `RESEARCHER_SYSTEM` (~7KB) and `ANALYST_SYSTEM`
(similar size) are sent in full on every single model call. A
researcher run that does 6–8 turns × the system prompt + a per-turn
tool schema block pays that input-token cost every turn.

**What to change.** Mark the system prompt as cacheable on Claude
(Anthropic prompt caching, `cache_control: ephemeral`). Also cache
the **stable portion of tool definitions** — tool schemas don't
change within a run.

**Implementation sketch.** Check what pydantic-ai exposes today
(`Agent(..., cache=...)` or passing raw cache markers via the
provider-level options). If pydantic-ai abstracts this away,
push a `ModelSettings` override through `agent_factory.make_model`.

**Expected win.** 20–40% reduction on input tokens for
researcher + analyst calls. Dominant single win available in the
current code.

**Risk.** Cache misses across routing (Claude prompt caching is
per-provider) mean the `routing_diverse.yaml` cross-family setup
only benefits on the Claude side. GPT verify/adversarial calls
don't get caching. That's fine — those dispatches are infrequent
by design.

**Compatibility with ablations.** Independent. Prompt caching is a
transport-level optimization and doesn't affect structural
decisions being tested.

---

### 2. Stop recomputing `get_research_state` from scratch

**Cost today.** `researcher.py:get_research_state` walks
`memory.list_by_type(NoteType.QUESTION)` and
`memory.list_by_type(NoteType.SOURCE)`, iterates metadata, and
bucket-counts every call. The researcher calls it between every
dispatch round. On a run with 80 sources and a dozen questions
it's cheap in wall time, but:

- it's called on the **hot path** between model turns,
- its return value is sent into the model as a dict — the more
  questions/sources, the more input tokens,
- every call rebuilds the same buckets deterministically from
  the same note graph.

**What to change.** Two pieces:

1. **Maintain running aggregates in `NoteMemory`.** `sources_by_tier`
   and `sources_by_state` are derivable from note
   create/update events. Update counters on every `create` /
   `update` so `get_research_state` is O(open questions) instead of
   O(all notes).
2. **Keep the payload compact.** Today's return is already fairly
   lean, but it grows linearly with question count. Cap at e.g.
   "most recent 20 questions, then a summary row," pushing the
   researcher to `load_note(id)` when it needs a specific
   question's detail. This is already the progressive-disclosure
   principle — apply it to the state snapshot as well.

**Expected win.** Small per-call; meaningful cumulatively on long
runs. More importantly, keeps token cost of `get_research_state`
bounded as the note graph grows — today it scales linearly with
sources.

---

### 3. Fetch pipeline — async-native PDF + size-first routing already promised in CONTEXT

**Cost today.** `retrieval/fetch.py:_pdf_to_markdown` runs MarkItDown
in a worker thread via `asyncio.to_thread`. MarkItDown is slow
(pdfminer internals, Python-level PDF parsing). A single 20-page
PDF can take 20–40s. It's capped at 15MB / 20 pages / 45s, but
even under caps it dominates the fetch budget on academic-heavy
queries. CONTEXT promises "size-first routing" (structured
extraction for long content) — the code doesn't yet do that.

**What to change.** Three stacked improvements:

1. **Replace MarkItDown with a faster PDF path.** `pymupdf`
   (fitz) is 5–10× faster for text extraction, pure-C under the
   hood, and already exposes a markdown-ish output. Keep
   MarkItDown as a fallback for when fitz's extraction is empty
   (scanned PDFs, exotic layouts).
2. **Implement the CONTEXT-promised size-first routing.** For
   documents ≥ 8K tokens, extract just: title, abstract, section
   headers, first paragraph per section, figure captions. Cache
   the full markdown on disk; the analyzer pulls specific
   sections via `load_source_section` only when needed. The
   structure is already documented in CONTEXT — just not
   implemented.
3. **Parallelize page-level extraction within a single PDF.**
   fitz supports this; MarkItDown doesn't. Only relevant once
   the previous step reveals that specific sections are needed.

**Expected win.** Wall-time: 3–5× on PDF-heavy queries. Token
cost: analyst's `scout_fetch` context drops from "full paper" to
"abstract + TOC" by default, reclaiming context for claims.

**Risk.** fitz's license is AGPL — fine for open-source, not fine
for commercial without a license. Worth checking before making
it the default. `pypdf` (already in deps) is a permissive
alternative but slower.

**Dependency.** Part (2) requires the `load_source_section` tool
CONTEXT describes. That tool is promised but not yet implemented
— confirm by grep before building on top of it.

---

### 4. Parallelize landscape + scout within the fan-out

**Cost today.** `agents/landscape.py:landscape_run` dispatches scouts
sequentially in an agent loop (the landscape agent is itself an
agent; its `scout_fetch` tool calls happen in a single loop). The
scout fan-out happens but isn't maximally parallel because it's
limited by the landscape agent's per-turn tool-call concurrency.
The Brave rate limit (1 QPS) also serializes searches regardless.

**What to change.** Two pieces:

1. **Issue fetches in an explicit gather.** Once a batch of URLs is
   known, fire `fetch_and_extract` on all of them concurrently,
   bounded by a semaphore (say, 6). httpx already multiplexes
   fine at that level.
2. **Decouple search from fetch rate-limiting.** Today, a single
   leaky bucket per provider serializes both search calls and
   fetch calls from the same host. Brave's 1 QPS only applies to
   the search API, not to the publishers being fetched.
   Confirm this is the case (it should be — `_brave_bucket` is
   only checked in `BraveClient.search`), and make sure fetch
   parallelism isn't accidentally coupled.

**Expected win.** 2–3× wall-time on the landscape phase for queries
with >10 candidate sources.

**Risk.** Politeness to publishers. Cap at ~6 concurrent fetches and
stagger by hostname (one in-flight per domain) to avoid hitting a
single server hard.

---

### 5. Compress source content sent into analyst context

**Cost today.** `agents/tools/fetch.py:fetch_url` caps markdown at
60K chars (~15K tokens). `scout_fetch` stores the full cleaned text
on `note.content` and the analyst reads it via `load_note`. 15K
tokens × 5 sources × every analyst turn adds up fast — and most of
that token budget is consumed by content the analyst doesn't end
up citing.

**What to change.** A two-tier presentation at the tool layer:

- **Default load** — title, abstract/TL;DR, section headers, top-k
  sentences selected by TF-IDF against the current sub-question
  text. 2–3K tokens.
- **Full load on request** — analyst explicitly asks
  `load_source_section(id, section)` or `load_note(id, full=True)`.

Same progressive-disclosure principle as the note digest. Relies on
the CONTEXT-promised size-first routing in fetch (step 3), so the
"sections" exist by the time the analyst asks.

**Expected win.** 30–50% reduction in analyst input tokens on
deep-read heavy queries. No quality loss as long as the analyst
can still pull the full section when it needs to.

**Risk.** Lossy by design. The TF-IDF selection has to be boring
and well-tested; if it hides the claim the analyst was supposed
to extract, that's a correctness regression, not a performance
one. Ship the opt-out first, then make it default.

---

### 6. Smarter routing by query complexity (don't always run the full pipeline)

**Cost today.** Every run goes through `landscape → researcher →
≥1 analyst` — even a simple `lookup`-class query for which the
landscape brief already contains the answer. The researcher's
prompt guides it not to over-dispatch, but the full phase still
runs. An Opus researcher deciding whether to dispatch for a
factoid lookup is objectively overkill.

**What to change.** A lightweight pre-classifier (`Haiku`, LOW
tier) runs on the user query before landscape. Outputs:
`{complexity: "lookup" | "synthesis" | "deep", expected_scope}`.

Routing on that:
- `lookup` → skip the researcher entirely; one analyst dispatch
  answers the query with search + fetch + synthesis, no
  `investigate_question` layering.
- `synthesis` → today's pipeline, but `analyst_budget` defaults
  lower (4 instead of 8).
- `deep` → today's full pipeline.

**Expected win.** Large on the fraction of queries that are
actually `lookup` in nature (highly query-mix dependent — could
be 10–30% of traffic in a public-facing deployment, essentially
zero in an advanced-analysis deployment).

**Risk.** Misclassification under-invests on a question that
looked simple but isn't. Mitigate by letting the simple path
escalate: if the analyst's confidence is low, auto-promote to
the full pipeline.

**Compatibility with ablations.** Mostly orthogonal to the
ablation list, but interacts with Experiment 1 (landscape
ON/OFF). If the landscape pre-pass is killed by that experiment,
the simple-path routing collapses into the default — no
conflict, just a simplification.

---

### 7. Cheaper rebuild of the researcher's "review round" prompt

**Cost today.** When the researcher returns for a review round
after analyst dispatches complete, the opening context is
reconstructed by pydantic-ai's message history, which includes
every prior tool call + tool result verbatim. For an 8-analyst
run, that history carries 8 full `QuestionSynthesis` payloads —
many KB of markdown — forward into every subsequent model call.

**What to change.** Between rounds, compact tool-result messages
in the history: replace the full `QuestionSynthesis` blobs with
a short reference ("[question-abc123] answered; confidence=0.7;
see get_research_state"). Keep the researcher's *own* reasoning
messages verbatim — those are load-bearing; replace only the
voluminous tool results it's done consuming.

**Implementation sketch.** pydantic-ai exposes `message_history`.
Write a `compact_history` pass that runs between researcher
turns, replacing `ToolReturnPart` payloads for completed
`investigate_question` calls with a synopsis. The researcher
can still `load_note(id)` to re-read the full synthesis if
needed — which is its current expected behavior anyway.

**Expected win.** 15–30% reduction in researcher input tokens on
long runs. Growth-rate win — the effect increases with the
number of rounds.

**Risk.** Non-trivial to get right. Pydantic-ai message-history
mutation is supported but not idiomatic. Worth gating behind a
flag and A/B-ing: does the researcher reach the same dispatch
decisions after history compaction? If not, something important
was in that tool-result payload that the compact summary is
missing.

---

### 8. Connection + client warm-up

**Cost today.** Every run creates a new `httpx.AsyncClient`
(via `build_deps`). TCP + TLS handshakes to Brave, Semantic Scholar,
and arXiv happen fresh each run.

**What to change.** A module-level shared `AsyncClient` per provider
(or one shared across all HTTP, which is what today's code does
but per-run instead of per-process). HTTP/2 if Brave supports it;
keepalive pool sized to expected concurrency.

**Expected win.** Small per-request (~30–80ms), but hit 40+ times
per run. A run's cold-start latency drops noticeably.

**Caveat.** A shared client has to survive worker recycling (see
scaling doc step 10). Scope the shared client to the worker
process lifetime, not the run.

---

### 9. Early termination on high-confidence synthesis

**Cost today.** The researcher's pre-commit audit is prompted to
"dispatch the missing work" if gaps exist AND budget has room —
which biases toward using the budget. There's no symmetric
"stop early if the answer is already solid." Empirically this
shows up as runs that use 6 of 8 analysts on queries where 3
would have sufficed.

**What to change.** Add an explicit "diminishing returns" check
to the researcher's review-round discipline: if the last
dispatch added no new sources and no disagreement with prior
findings, treat it as a signal to commit rather than dispatch
again. The prompt already implicitly supports this ("Never
call investigate_question just because budget is left over");
the change is making the signal more concrete.

**Expected win.** 10–20% reduction in analyst dispatches on
converged runs. No wall-time win on the critical path; this
saves budget + dollars.

**Risk.** Hard to distinguish "we converged" from "we all agree
because we only looked in one place." Should only fire when
source diversity is already adequate (multiple domains, some
variance in venue/methodology) — use the `sources_by_*`
aggregates from step 2 as the gating condition.

---

### 10. Warm expensive per-process objects

**Cost today.** `retrieval/fetch.py` already comments on this for
`MarkItDown()` — constructed once at import to avoid per-fetch
cost. There are likely other hotspots with the same problem:

- trafilatura's config (`use_config()`) — today uses defaults;
  worth pinning once and reusing.
- `tiktoken` encoder for token counting in the tracker — loaded
  lazily on first count.
- tier classifier's prompt template (if it reads from disk).

**What to change.** Audit every per-call construction of a
non-trivial object, move to module level, assert it's safe to
share across async tasks (most of the above are immutable after
init; the ones that aren't should be per-`Deps`).

**Expected win.** Small but free. Good to do alongside step 3
when the fetch pipeline is already under the microscope.

---

## Suggested order

1. **Prompt caching (step 1).** Largest single-ROI change. Little
   code surface. Test it lands: look at `cache_read_tokens` in
   `token_usage.json` before and after.
2. **Fetch pipeline — size-first routing + fitz (step 3).** The
   biggest wall-time lever. Also unblocks step 5.
3. **Aggregate-maintenance in NoteMemory (step 2).** Small,
   composable, directly attacks the growth curve of
   `get_research_state` cost.
4. **Compact source content (step 5).** Depends on step 3. Biggest
   analyst-side token win after prompt caching.
5. **Landscape parallelism (step 4).** Easy once the fetch
   pipeline is understood.
6. **Query-complexity pre-classifier (step 6).** High-variance win
   — size depends on query mix. Cheap to build behind a flag.
7. **Researcher history compaction (step 7).** Do after
   instrumentation (scaling doc step 8) is in place so regressions
   in dispatch quality are visible.
8. Everything else (steps 8, 9, 10) as time/opportunity allows —
   each is a single-digit-percent win on its own.

---

## Appendix — things that look like performance wins but aren't

- **Switching researcher to Sonnet to save money.** This is
  Experiment 4 in `ablation-ideas.md` — a *structural* question,
  not a performance one. If the answer is "Sonnet is fine," take
  the win there, not here.
- **Embedding index over sources for dedup.** Tempting. Out of
  scope per CONTEXT ("no embedding index"). Revisit only if the
  exact-URL cache in the scaling doc proves insufficient.
- **Streaming model outputs to reduce time-to-first-token.** The
  UX benefit is real but doesn't reduce total cost or total wall
  time. Handle at the UI layer when the event bus (scaling doc
  step 4) is in place; it's a UI polish change, not a performance
  improvement to the research pipeline.
- **Switching from asyncio to multiprocessing.** The bottleneck is
  network + LLM wall time, not CPU. Multiprocessing adds isolation
  (scaling doc step 10) but doesn't make a single run faster.
- **Pre-fetching candidates while the researcher is still
  thinking.** Speculative execution against a tool budget is a
  class of bug, not a performance improvement. Don't build it.
