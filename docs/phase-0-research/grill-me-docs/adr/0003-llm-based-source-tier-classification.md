# ADR 0003 — LLM-based source tier classification (semantic tiers) with deterministic reject + peer-review status as separate field

**Status:** Accepted
**Date:** 2026-05-07
**Context in:** `tdd-v3.md` §5.5 (source tiering + confidence), `research-agent` skill `SOURCE-QUALITY.md`

**Supersedes:** The static citation-count threshold (≥20 for AI preprints) and the proposed `topic_maturity` flag that would have parameterized a rule table.

---

## Context

TDD v3 specified deterministic rule-based source tiering — a static table mapping venue + citation-count + institution to tiers, plus a "preliminary source upgrade check" with a hard numeric threshold (≥20 citations for AI papers). This was adopted from the `research-agent` skill's `SOURCE-QUALITY.md`, which explicitly prefers deterministic rules for auditability, speed, and repeatability.

Two problems surfaced during grilling:

1. **Structural rules fail on emerging topics.** Papers from top labs on topics <2 years old are the most relevant sources for queries like Test Case 3 (inference-time compute scaling) but almost always fall below any reasonable citation threshold. The rule systematically downweights exactly the evidence the user wants.
2. **The fix produces more rules, not better reasoning.** A `topic_maturity` flag that parameterizes the tier table introduces a second brittleness: one classification per run applied uniformly, when in reality a mixed-maturity query contains both emerging and established sources that need different treatment each. Adding more cases to the rule table doesn't resolve the underlying mismatch between rigid structural rules and the semantic question "is this source rigorous?"

The alternative — LLM-based classification with source metadata in context — is how a human reviewer actually tiers sources: weigh signals in combination, apply judgment. The cost of the departure from the skill's deterministic stance is additional per-source LLM calls, non-determinism without caching, and weaker auditability without logged rationales. Those are addressable.

## Decision

**Source tiers become semantic and LLM-classified, with specific guardrails.**

1. **Deterministic reject list** short-circuits the classifier. Domains never allowed as primary evidence (social media, video platforms, vendor marketing, unattributed aggregators) are assigned Tier 5 without an LLM call. Static config; reviewable.
2. **Everything else runs through an LLM tier classifier.** Input: structured source metadata (title, authors, institution, venue string, citation count, publication date, first 500 chars of cleaned main content). Output: `{tier: 1..4, rationale: str, classifier_confidence: float}`. Classifier runs at LOW tier (cheap model), low temperature, with a rubric prompt that includes calibration anchors.
3. **Tier semantics** shift from structural to semantic. Tier 1 = "authoritative, rigorous, methodologically sound, extensively validated or from a source where validation is inherent." Tier 2 = "credible and methodologically sound, may still be preliminary." Tier 3 = "relevant context but with caveats." Tier 4 = "expert-opinion-in-refereed-venue, acceptable to fill gaps only."
4. **Peer-reviewed status becomes a separate deterministic field** (`peer_reviewed: bool`) on every source_note. Computed from a static list of peer-reviewed venues. Independent of the semantic tier.
5. **The 0.80 preliminary-anchor confidence cap is load-bearing**. Claims primarily anchored on `peer_reviewed=False` sources are capped regardless of what the classifier tiered them. This is the backstop that prevents semantic-tier reasoning from overclaiming on unvalidated work.
6. **Tier decisions are cached by URL.** Subsequent fetches reuse the prior classification + rationale. Cross-run consistency + easier ablation.
7. **Rationale is stored in the source_note** (`evaluation.tier_rationale`). Every tier decision is inspectable in the Obsidian vault export.

## Alternatives Considered

### (A) Keep deterministic rule-based tiering as specified in TDD v3.
Rejected. Fails on Test Case 3 (emerging topics); the attempted fix (Q4's topic_maturity flag) just piles rules. Structural peer-review status isn't a good proxy for rigor on fast-moving topics.

### (B) Drop the citation threshold only; keep everything else rule-based.
Rejected. Removes one failure mode but doesn't resolve the underlying issue — a rigorous preprint from Anthropic on a 3-month-old topic still wouldn't qualify for Tier 2 under the remaining rules (no venue match), and the rule table would still need more branches to handle institution-based signals.

### (C) Full LLM classification with no deterministic reject.
Rejected. Obvious Tier 5 categories (Reddit, TikTok, unattributed aggregators) are better excluded deterministically — cheaper, more reliable, less prompt-injection risk. Trusting an LLM to consistently reject "a Twitter thread about a paper" is less robust than a hardcoded domain list.

### (D) Topic-maturity flag (Q4 proposal iii).
Rejected as a lesser version of the accepted decision. One classification per run applied to all sources is coarser than per-source classification. The maturity concept is real but gets absorbed into each source's individual tier reasoning under option (D).

## Consequences

### Positive

- Emerging-topic sources tier correctly without special-case rules. A recent rigorous preprint from OpenAI gets Tier 1–2; a blog post from the same org gets Tier 3; the classifier reasons about both using the same rubric.
- Mixed-maturity queries (common) don't get uniformly mis-tiered.
- Rationale trail makes mis-tiering debuggable — a reviewer can see exactly why the classifier decided what it decided.
- Deterministic reject list retains the most important guardrail (obvious junk can't enter the corpus) at zero marginal cost.
- Peer-review status as a separate field keeps the "is this externally validated?" question clean and independent of the quality question.
- The 0.80 cap remains the backstop: we can trust LLM tier judgments because even if the classifier over-tiers a preprint, the cap prevents overclaiming.

### Negative

- Per-source LLM call → small cost + latency increase. Mitigated by caching (a re-fetched source doesn't re-classify) and by using a cheap model.
- Non-determinism possible without cache. Mitigated by caching + low temperature.
- Prompt-injection surface. Mitigated by passing only structured metadata + a bounded text excerpt, not raw HTML.
- Classifier bias toward familiar sources. Mitigated by calibration anchors in the prompt and by logged rationales that make drift visible.
- We're diverging from the `research-agent` skill's methodology in a specific way. Worth noting for reviewers; the trade-off is explicit — we're choosing context-sensitivity over rule-based repeatability.

### Neutral

- The `research-agent` skill's SIFT discipline (Stop, Investigate, Find better, Trace) transfers directly into the classifier's prompt as guidance for edge cases ("if the source is an aggregator, trace to the original and classify that instead").

## Open Questions

- **Calibration anchor set** — which specific sources become the prompt's anchor examples? Needs a handful of canonical papers, blogs, preprints across tiers. Nailing down during implementation.
- **Classifier confidence threshold.** When `classifier_confidence` is low (< 0.5?), should the source get a conservative default tier rather than the classifier's best guess? Likely yes; needs empirical tuning.
- **Reject list maintenance.** Static config is fine for MVP. Does it need a mechanism to add entries during a run (e.g., a domain seen producing low-quality content within the session)? Probably not for MVP.

## References

- `phase-1-initial-design/05-tdd-v3.md` — TDD being revised.
- `phase-1-initial-design/04-research-skill-takeaways.md` — methodology divergence source.
- `~/.claude/skills/research-agent/SOURCE-QUALITY.md` — the deterministic stance being departed from.
- Grilling session transcript — 2026-05-07.
