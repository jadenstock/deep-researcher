"""Analysis of Competing Hypotheses (ACH) pattern — ADR 0004.

Three phases:

  1. Hypothesis generation. One LLM call reads the question + extracted
     claims across the source set and proposes N distinct hypotheses
     (minimum 2, cap at 5). Hypotheses must be mutually exclusive
     where possible — if two phrasings collapse to the same claim,
     the generator merges them.

  2. Per-hypothesis consistency evaluation. N parallel calls, one per
     hypothesis. Each reads the hypothesis text + all M source digests
     and returns one verdict per source:
         consistent | inconsistent | neutral, with rationale.
     Batched per hypothesis, NOT per (hypothesis, source) pair — per
     ADR 0004, the natural reasoning unit is "this hypothesis against
     all evidence."

  3. Adjudication. One HIGH-tier call reads the full N x M verdict
     matrix, scores each hypothesis by inconsistency count (Heuer's
     ACH weighting), and picks the tentative adoption — the one with
     the FEWEST inconsistencies. Writes hypothesis_notes + synthesis.
"""

from __future__ import annotations

ACH_HYPOTHESIS_GEN_SYSTEM = """\
You are generating a set of competing hypotheses for an ACH analysis.
Given a research question and the claims extracted from a set of
sources, produce 2-5 hypotheses that plausibly answer the question in
DIFFERENT ways.

Rules:
- Hypotheses must be mutually exclusive in their core answer where
  possible. If two phrasings resolve to the same underlying claim,
  collapse them.
- Each hypothesis must be a complete sentence that could in principle
  be supported or refuted by evidence — not a topic label.
- Cover the range visible in the claims: include the obvious answer,
  the contrarian answer (if any claim supports it), and any other
  distinct position. Don't invent hypotheses no source hints at.
- If the evidence only points one way, it's valid to generate just 2
  hypotheses (the affirmative + its negation). Don't pad to 5.
- Each hypothesis needs a short `label` (1-4 words) for the matrix.
"""

ACH_CONSISTENCY_SYSTEM = """\
You evaluate ONE hypothesis against all available source evidence and
return a consistency verdict per source.

For each source, read its claims + quotes and decide:
- **consistent**: the source's claims corroborate the hypothesis.
- **inconsistent**: the source's claims contradict or undermine the
  hypothesis.
- **neutral**: the source doesn't bear on this hypothesis one way or
  the other — off-topic or orthogonal.

Rules:
- The point of ACH is to count INCONSISTENCIES. Sources that don't
  address the hypothesis are neutral, not inconsistent — don't pad
  the inconsistent count with irrelevant sources.
- Rationale (1-2 sentences) must cite the specific claim or quote
  that drove your verdict. Generic rationales are useless for the
  adjudicator.
- Treat the claims as the source's position — you're not re-reading
  the full source, just the extracted claims.
"""

ACH_ADJUDICATION_SYSTEM = """\
You are running the adjudication phase of ACH. You have the full
N x M consistency matrix — N hypotheses evaluated against M sources,
each cell with a verdict (consistent / inconsistent / neutral) and
rationale.

Apply Heuer's rule: the hypothesis with the FEWEST inconsistencies is
tentatively adopted. Ties broken by evidence diversity (prefer
hypotheses whose consistent sources span more tiers / venues / framings)
then by confidence of the rationales.

Rules:
- `bottom_line` (1 sentence): the tentatively adopted hypothesis as a
  direct answer to the question.
- `synthesis` (2-4 paragraphs): for each hypothesis, state its
  inconsistency count and list the key inconsistent sources with a
  one-line reason. Then explain why the adopted hypothesis survives.
  Note any hypothesis that was refuted decisively (inconsistency count
  >= consistency count).
- `disagreements`: the specific sources where the adopted hypothesis
  has an inconsistency. These are the weak points — surface them.
- `confidence_note` (1 sentence): how close the call was. If two
  hypotheses are near-tied in inconsistency count, say so.
"""
