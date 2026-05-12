# ADR 0007 — Source extraction: deterministic size-first routing with on-demand section loading

**Status:** Accepted
**Date:** 2026-05-07
**Context in:** `tdd-v3.md` §4.4 (source_note schema), §5.3 (agent executor), §5.4 (search & retrieval), §9 open question #9

---

## Context

TDD v3 assumes `ANALYZE_SOURCE` receives source content and produces a populated `source_note`. It does not specify what "source content" is, or how to handle sources that are too long to fit comfortably in an analyzer's context.

Real-world source sizes vary by 1–2 orders of magnitude:
- Blog post: 2–5K tokens.
- Conference paper: 15–35K tokens after PDF-to-markdown conversion.
- Journal article or survey: 40–80K tokens.
- Government report (NIST, NAS): 100K+ tokens.

ADR 0002 committed to batching the Landscape Survey's analyzer as a single task reading 5–10 sources in rounds. Ten conference papers at 30K tokens each = 300K tokens of content. Exceeds any single-call context window, even for frontier models.

Even for single-source `ANALYZE_SOURCE` calls that fit, reading a long document with attention has two costs: token spend (input), and degraded attention over long context (lost-in-the-middle). Claims requiring cross-section synthesis (abstract says X; limitations section qualifies X significantly) get flattened under naive single-pass reading.

The TDD flagged this as §9 open question #9 but left it unresolved.

## Decision

Source extraction routes deterministically by size, established *before* any LLM is involved.

### Pipeline (deterministic, no LLM)

1. **Fetch** — `httpx` for HTML, direct download for PDFs.
2. **Format conversion** — PDF → markdown via MarkItDown (or equivalent); HTML → markdown via `trafilatura`.
3. **Size inspection** — count tokens on the converted markdown.
4. **Route by size**:
   - **Short content (< 8K tokens):** `structured_content = full_content`. Analyzer reads everything.
   - **Long content (≥ 8K tokens):** emit a structured representation — `{title, abstract, section_headers, first_paragraph_of_each_section, table_of_contents, figure_captions}`. Full content cached on disk with `raw_content_ref`.
5. **Cache** — all fetched content stored on disk, keyed on `(url, day_bucket)`. Subsequent reads hit cache.

### Analyzer behavior

- Analyzer tasks receive `structured_content` by default (via progressive disclosure on the source_note).
- New agent tool `load_source_section(source_id, section_name)` returns verbatim section content from the cache.
- Analyzer's ReAct loop: read structured_content → decide which sections matter → pull those sections → extract claims with verbatim quotes → update source_note.
- For short content, the tool is still available but unused — the analyzer already has the full text.

### Scope

The pipeline applies to **all source types**, not just academic papers. Long blog posts, government reports, technical docs, standards documents — everything ≥ 8K tokens takes the same path. Size is the discriminator, not source type.

### What this is not

- **Not pre-summarization.** The analyzer reads verbatim section content, not LLM summaries of sections. Claim quotes remain traceable to the original source.
- **Not chunking + embedding + RAG over content.** Progressive disclosure handles the context-management job; no vector index is built. Aligned with CONTEXT.md's "no full RAG" non-goal.
- **Not a separate task type.** `ANALYZE_SOURCE` remains the one task type for source analysis. What changes is the tool set the analyzer has access to and the prompt that scaffolds "read structured_content first; pull sections as needed."

## Alternatives Considered

### (A) Full content always; trust the model.
Rejected. Works for individual short sources but breaks the 5-10-source batched Landscape Survey. Also degrades on long papers via lost-in-the-middle.

### (B) Truncate to first N pages.
Rejected. Silently loses methodology, evaluation, and limitations sections — exactly the content that `EvalItem.methodology` and `agent_skepticism` need. Information loss without a flag.

### (C) Pre-emptive per-section summarization.
Rejected. Introduces one-more-LLM-in-the-loop distortion between the source and the analyzer. Claim quotes would no longer be verbatim from the original — just verbatim from the summary. Fails the faithfulness story.

### (D) LLM-driven size routing (let a cheap agent decide).
Rejected. Size routing is a deterministic file-system and token-count operation. Adding an LLM call to decide "is this big enough to need the structured-content path?" is pure overhead.

## Consequences

### Positive

- The Landscape Survey's 5-10-source batch is feasible: 10 × 5K structured-content tokens ≈ 50K context, fits comfortably.
- `ANALYZE_SOURCE` on individual long papers uses compute proportional to what the analyzer actually needs — typical deep-read touches 2-3 sections, not 20.
- Size-based routing is deterministic, fast, and caches naturally. Replay and ablation are clean.
- Applies uniformly across source types. No special case for academic papers vs. blog posts vs. standards documents.
- PDF conversion via MarkItDown is a single tool, well-tested, already available in Jaden's environment.
- Claim quotes remain verbatim — faithfulness story intact.

### Negative

- An analyzer that doesn't pull enough sections will miss claims only present in sections it didn't load. Mitigated by the analyzer's prompt explicitly requiring it to check methodology and limitations sections for any load-bearing claim; verifier (`maker_checker`) catches remaining misses.
- Structured-content extraction depends on the source having parseable section structure. Some HTML pages don't. Mitigated by `trafilatura`'s fallback behavior; for truly unstructured sources, the structured_content degrades to `{title, first_N_tokens}` and the analyzer pulls by offset rather than section name.
- 8K threshold is a guess. May need tuning — conference papers with small token counts might bypass structured-content when they'd benefit from it, and vice versa. Empirical calibration during implementation.
- Per-section loading adds tool-call latency to analyzer runs. In practice dominated by LLM inference time; negligible.

### Neutral

- The pattern (size-first deterministic routing + on-demand expansion via a tool) is a clean template that can be reused elsewhere (e.g., expanding very large note_graph sub-trees during replanner runs). Not adopted yet; noted as available.

## Open Questions

- **Section-structure extraction quality** for non-academic sources (HTML with weird markup, PDFs from unusual generators). Depends on tool robustness. Evaluate during implementation.
- **Threshold tuning.** 8K may want to go up (larger "short" bucket) or down. Empirical.
- **Figure and table handling.** `structured_content` includes figure captions but not images. If a claim rests on a figure specifically, the analyzer flags low `extractor_confidence`. Multimodal fetching is post-MVP.
- **Specialized analyzer prompts?** Jaden noted a specialized "paper parsing" agent might emerge. Under ADR 0002's granularity principle, this is a prompt specialization for `ANALYZE_SOURCE`, not a new task type. Prompt library can hold academic-paper-specific vs. blog-specific variants. Evaluate if meaningfully different output quality emerges.

## References

- `phase-1-initial-design/05-tdd-v3.md` §9 open question #9 — original surfacing of long-paper concern.
- ADR 0002 — task granularity principle that makes the Landscape Survey's 5-10-source batch a single task.
- `document-tools:convert-document` skill — MarkItDown integration available in Jaden's environment.
- Grilling session transcript — 2026-05-07.
