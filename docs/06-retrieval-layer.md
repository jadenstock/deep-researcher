# 06 — Retrieval Layer

`deep_research_agent.retrieval` covers everything between "I have a
query string" and "I have a `source_note` with cleaned content":
search, fetch, extract, dedup, rerank, structure, cache.

All network clients are async. All clients throttle in-process so
concurrent QS tasks don't stampede rate limits. All clients return
`[]` on terminal failure rather than raising (with one exception —
Brave raises on non-2xx so the caller knows when the primary web
search fails).

## Shared shape — `SearchHit`

```python
class SearchHit(BaseModel):
    title: str
    url: str
    snippet: str = ""
    source: str = "brave"           # "brave" / "semantic_scholar" / "arxiv"
    # Academic fields — left empty by Brave:
    authors: list[str] = []
    venue: str | None = None
    year: int | None = None
    citation_count: int | None = None
    doi: str | None = None
    pdf_url: str | None = None
```

This is the normalized shape all providers emit so the downstream
rerank / fetch / classify pipeline doesn't branch.

## Web search — Brave

**File**: `retrieval/brave.py`

- Endpoint: `https://api.search.brave.com/res/v1/web/search`.
- Auth: `X-Subscription-Token` header.
- Request shape: `{q, count}` (cap at 20).
- Response: normalized to `SearchHit` with `source="brave"`.

### Throttling

- Module-level `asyncio.Lock` + `_BRAVE_LAST_CALL_AT` shared across all
  `BraveClient` instances. So concurrent QS tasks serialize through the
  same throttle slot.
- `_BRAVE_MIN_INTERVAL_S` defaults to 1.5s (free tier is 1 req/s with a
  strict sliding window; 1.05s cuts it too close in practice). The CLI
  calls `set_brave_min_interval(local.retrieval.brave_min_interval_s)`
  at startup so config can override.
- Logs `brave_throttle queue_ms=... pace_ms=...` when either value
  exceeds 100ms — surfaces the case where many QS tasks are queued
  behind a single throttle slot.

### 429 retry

- `MAX_429_RETRIES = 3`, `MAX_429_TOTAL_WAIT_S = 20`,
  `DEFAULT_429_BACKOFF_S = 2`.
- Honors `Retry-After` header if parseable; otherwise exponential
  backoff floor (`2 * 2^attempt`).
- Total-wait cap short-circuits to `BraveSearchError` so a genuinely
  exhausted plan doesn't stall the run indefinitely.
- On a terminal 429 or other 4xx/5xx, logs `retry-after`,
  `x-ratelimit-remaining`, `x-ratelimit-reset` to make diagnosis
  possible.

## Academic search — facade

**File**: `retrieval/academic.py`

```python
search_academic(query, *, local, limit_per_source=3) -> list[SearchHit]
```

Runs Semantic Scholar + arXiv **in parallel** via `asyncio.gather`,
deduplicates, and optionally rescues paywalled DOIs through Unpaywall.

### Dedup strategy

- First: DOI match (case-insensitive).
- Then: normalized title (lowercase, strip punctuation, collapse
  whitespace).
- Interleave S2 first so its richer metadata wins on ties.

### Unpaywall rescue

If `local.retrieval.unpaywall_email` is set, hits with a DOI but no
`pdf_url` get run through `UnpaywallClient.find_oa_pdf(doi)`. The
rescue policy is careful about not replacing a good HTML landing URL:

- If the current URL is already HTML (arxiv.org/html/..., PMC HTML),
  keep it — fetcher takes the fast trafilatura path.
- Otherwise overwrite `url` with the OA PDF link so the fetcher can
  MarkItDown it.

### Semantic Scholar details

**File**: `retrieval/semantic_scholar.py`

- Endpoint: `https://api.semanticscholar.org/graph/v1/paper/search`.
- Fields requested: `title,abstract,authors,venue,year,citationCount,
  openAccessPdf,externalIds,url`.
- 429 retry mirrors the Brave pattern (3 retries, 20s total cap, 2s
  exponential floor).
- **URL preference**: HTML-native renderings first (arXiv HTML at
  `arxiv.org/html/{id}`, PMC HTML at
  `ncbi.nlm.nih.gov/pmc/articles/{id}/`), DOI landing next, then PDF,
  then the S2 page as last resort. The HTML-first bias matters because
  the fetcher's HTML path (`trafilatura`) is dramatically faster than
  its PDF path (`MarkItDown`).
- Throttle: 1.0s interval (S2 unauthenticated is ~100 req/5min).
- Returns `[]` on any terminal API error — academic hits are additive;
  a failure must not break the run.

### arXiv details

**File**: `retrieval/arxiv.py`

- Endpoint: `https://export.arxiv.org/api/query`.
- Query: `all:{query}` so title/abstract/author all match.
- Atom feed parsed with stdlib `xml.etree.ElementTree`.
- Throttle: 3.0s per arXiv's public-API guideline (1 req/3s).
- URL preference: `arxiv.org/html/{id}` stripped of version suffix, so
  the fetcher hits the native HTML rendering (available for ~70–80%
  of recent submissions). Falls back to the abs URL when HTML 302s
  back.

### Unpaywall details

**File**: `retrieval/unpaywall.py`

- Endpoint: `https://api.unpaywall.org/v2/{doi}?email=...`.
- Returns `best_oa_location.url_for_pdf` or `best_oa_location.url`.
- Throttle: 0.3s (100k req/day free; well clear).
- Failures are debug-logged and return `None` — the caller keeps the
  original URL.

## Rerank

**File**: `retrieval/rerank.py`

Cheap lexical + recency rerank applied between `search` and `fetch`
to drop obvious dreck before paying fetch + tier-classify cost.

### Scoring

```python
score = base + 2.0 * title_matches + 1.0 * snippet_matches + recency_bonus
```

- `base`: 1.0 for academic sources (`semantic_scholar` / `arxiv`),
  0.0 otherwise — academic hits shouldn't be outranked by
  SEO-optimized Brave titles sharing query tokens.
- `title_matches` / `snippet_matches`: token overlap on lowercased
  `[A-Za-z0-9]{2,}` runs, minus a minimal stopword list.
- `recency_bonus`: additive, keyed off current year. Current year =
  1.5; 1 year old = 1.2; 2 = 0.8; 3 = 0.4; older = 0. Never a
  penalty — a well-cited classic still competes on relevance.

### Stability

`sorted(..., key=score_hit, reverse=True)` is stable, so ties preserve
the caller's order (`search_academic` puts academic hits first for
dedup reasons, rerank doesn't disturb that when scores tie).

## Fetch + extract

**File**: `retrieval/fetch.py`

One function: `fetch_and_extract(url, timeout=20) -> FetchResult | None`.

### Routing

- Detects PDF via `content-type: application/pdf` or `url.endswith(".pdf")`.
- HTML path: `trafilatura.extract(html, output_format="markdown",
  include_comments=False, include_tables=True, favor_recall=True)`.
  Metadata (title) extracted separately; tolerant of malformed input.
- PDF path: `MarkItDown` — shells out to `pdfminer` under the hood.

### PDF safety net

PDF conversion is synchronous and CPU-bound. Unbounded, a single
pathological PDF can freeze the event loop for minutes. The fetcher
enforces three caps:

- `MAX_PDF_BYTES = 15 MB` — dropped entirely above this (usually
  textbooks / scanned archives, not signal-dense).
- `MAX_PDF_PAGES = 20` — truncated to first 20 pages via pypdf.
  Appendices / supplementary are noise for synthesis.
- `PDF_CONVERT_TIMEOUT_S = 45` — conversion runs in
  `asyncio.to_thread`; exceeding the timeout returns `(None, None)`
  without raising.

### Return shape

```python
class FetchResult(BaseModel):
    url: str
    final_url: str
    status_code: int
    content_type: str | None
    title: str | None
    markdown: str | None
    byte_length: int
```

- `markdown=None` is expected for paywalls, JS-only pages, oversized
  PDFs. Callers must tolerate it.
- Connection-level failures return `None` from the function rather
  than a `FetchResult`. Non-2xx returns a `FetchResult` with
  `markdown=None`.

## Size-first structure routing

**File**: `retrieval/structure.py`

`is_long_source(markdown)` == `rough_token_count(markdown) >= 8000`
(rough token count is `chars // 4`).

For long sources, the handler builds a `StructuredContent`:

- `abstract`: first paragraph before the first H2+ header (skipping a
  leading H1 title).
- `section_headers`: ordered list of all `#{1,6}` headers.
- `first_paragraph_of_each_section`: dict `{header: first_paragraph}`,
  capped at 800 chars per entry.
- `table_of_contents`: H2 + H3 headers only.
- `figure_captions`: lines starting `Figure N:` / `Fig. N.`, capped
  at 40 and 200 chars each.

The analyzer user message for a long source is the rendered outline
(`render_outline(structured)`) plus a 6000-char excerpt of the raw
markdown — the analyzer sees the document's shape without consuming
its full content budget.

`load_source_section(markdown, section_title)` is the companion tool:
case-insensitive header match, body ends at the next header of equal-
or-higher level, returns `None` on miss. This is the surface the
analyzer's ReAct loop would expand into (pull specific sections on
demand) once tool use is wired through.

## Cache

**File**: `retrieval/cache.py`

`RetrievalCache` wraps `diskcache.Cache` with day-bucketed keys:

```python
key = f"{tool}:{md5(args)[:16]}:{YYYY-MM-DD}"
```

This is not a fetch-dedup layer at runtime (the in-process retries
happen below it). It's a replay enabler — `dra replay <run_id>` is
intended to read from this cache without network access. The replay
subcommand is wired into the argument parser but currently prints
"replay not yet implemented" and exits 1.

## Retrieval inside the QS handler

The handler composes these pieces:

```python
brave_hits, academic_hits = await asyncio.gather(
    brave.search(question, count=5),
    search_academic(question, local=ctx.local, limit_per_source=3),
)

# Academic first so its metadata wins on dedup ties.
combined = dedup_by_url([*academic_hits, *brave_hits])

# Lexical + recency rerank before paying fetch cost.
reranked = rerank(combined, question)
hits = reranked[:FETCH_LIMIT]  # FETCH_LIMIT = 8

fetches = await asyncio.gather(*(fetch_and_extract(h.url) for h in hits))

usable = [(hit, fetch) for hit, fetch in zip(...) if fetch and fetch.markdown]

# Tier classification in parallel on cheap_deterministic / LOW.
tier_model_id = routing.model_id_for(CHEAP_DETERMINISTIC, LOW)
tier_results = await asyncio.gather(*(
    classify_source(..., model_id=tier_model_id, local=..., tracker=...)
    for hit, fetch in usable
))

# source_notes created; long ones get structured_content.
for (hit, fetch), (tier, rationale, confidence, peer_reviewed) in zip(...):
    structured = build_structured_content(title, markdown) if is_long_source(markdown) else None
    source_notes.append(Note(..., metadata=SourceNoteMetadata(...)))
```

Note the constants:

- **5 Brave hits + 3 per academic source** from search.
- **Dedup** by URL.
- **`FETCH_LIMIT = 8`** after rerank.
- **8K tokens** as the long-source threshold.
- Cheap deterministic LOW model for classification.

Failure paths:

- Brave key missing → `RuntimeError` up front.
- All fetches fail (no usable sources) → `RuntimeError(f"no usable
  sources after fetching {len(hits)} candidates ...")`. The handler
  raises; the task is abandoned; downstream QS tasks continue.
