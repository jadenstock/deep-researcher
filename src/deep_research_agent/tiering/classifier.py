"""LLM tier classifier (ADR 0003).

Replaces the v0 `quick_tier` URL heuristic. Deterministic reject list
still short-circuits obvious junk to Tier 5 without an LLM call.
Everything else is classified by a cheap model (cheap_deterministic /
LOW tier) that reads title + URL + snippet + content excerpt and
returns (tier, rationale, confidence, peer_reviewed).

Design choices:
- The classifier reads a content *excerpt*, not the full document — the
  signals that separate tiers (venue, methodology, citation style) live
  in the first ~2K characters.
- peer_reviewed is a strict flag (true only for formally peer-reviewed
  publications), not "seems rigorous". Preprints and tech blogs are
  false even when the underlying work is good.
- Topical relevance is NOT this classifier's job — the analyzer's
  off_topic flag handles that.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from ..agent_factory import make_model
from ..config import LocalConfig
from ..schemas.enums import RoleClass, TaskTier, Tier
from .simple import REJECT_DOMAINS

if TYPE_CHECKING:
    from ..executor.llm import LLMRunner
    from ..token_usage import TokenUsageTracker

logger = logging.getLogger(__name__)

CONTENT_EXCERPT_CHARS = 2000


class TierClassifierOutput(BaseModel):
    tier: Literal[1, 2, 3, 4, 5] = Field(
        ...,
        description=(
            "Source tier. 1=rigorous peer-reviewed primary research. "
            "2=peer-reviewed secondary / preprints with methodology / top-tier academic. "
            "3=well-edited journalism, technical reports, gov/industry primary docs. "
            "4=opinion / corporate blogs / content marketing with some substance. "
            "5=junk: aggregators, pure marketing, clickbait, unattributed content."
        ),
    )
    rationale: str = Field(
        ...,
        min_length=1,
        description=(
            "1-2 sentences explaining the tier — "
            "cite specific signals (venue, methodology, authorship)."
        ),
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="0..1 confidence in the tier assignment."
    )
    peer_reviewed: bool = Field(
        ...,
        description=(
            "True ONLY if published in a peer-reviewed venue (journal, major conference). "
            "False for preprints, blogs, government reports, journalism."
        ),
    )


TIER_CLASSIFIER_SYSTEM = """\
You classify web sources by rigor tier on a 1-5 scale. You do NOT judge
topical relevance — a rigorous paper on the wrong topic is still tier 1.

Tiers:
  1 — Peer-reviewed primary research in a reputable venue (major journals,
      top-tier conference proceedings). Empirical data or formal proof.
      Reproducible methodology.
  2 — Preprints with real methodology (arXiv, bioRxiv), peer-reviewed
      surveys, secondary academic writing. Academic but less rigorous than
      tier 1, or not yet peer-reviewed.
  3 — Well-edited journalism (NYT/Economist/Reuters-tier), government or
      industry primary reports, technical documentation from authoritative
      sources (official docs, standards bodies), substantive technical blogs
      from recognized practitioners.
  4 — Corporate blogs, opinion pieces, content marketing, tutorials with
      some substance but light on sourcing or methodology.
  5 — Junk: unattributed aggregators, pure SEO content, clickbait, social
      media, marketing with no substance.

Rules:
- Read the snippet + content excerpt and look for signals: venue (journal
  name, conference, publisher), methodology section, citations, author
  credentials, publication date, evidence density.
- peer_reviewed is a STRICT flag. It is true ONLY for formally
  peer-reviewed publications. arXiv preprints → false. Blog posts → false.
  Government reports → false. Conference proceedings → true only for
  recognized peer-reviewed venues (e.g. NeurIPS, ACL, Nature, IEEE S&P).
- confidence reflects how certain you are. If the content excerpt is
  sparse or ambiguous, lower confidence; do not guess at tier 1.
- Rationale should cite SPECIFIC signals, not be generic.
"""


def _reject_list_tier(url: str) -> tuple[Tier, str] | None:
    """Deterministic reject-list short-circuit. Returns None on no match."""
    url_l = url.lower()
    for d in REJECT_DOMAINS:
        if d in url_l:
            return Tier.TIER_5, f"reject list match: {d}"
    return None


async def classify_source(
    *,
    title: str,
    url: str,
    snippet: str,
    content: str,
    model_id: str,
    local: LocalConfig,
    tracker: TokenUsageTracker | None = None,
) -> tuple[Tier, str, float, bool]:
    """Classify one source. Returns (tier, rationale, confidence, peer_reviewed).

    Reject-list matches short-circuit to Tier 5 with confidence 1.0 and no
    LLM call. Otherwise invokes the classifier LLM on `model_id`.

    On LLM failure, falls back to Tier 3 with a low confidence — the
    handler keeps the source but downstream scoring treats it as generic
    web content until re-tiered (v3 replanner may retry).
    """
    hit_rejected = _reject_list_tier(url)
    if hit_rejected is not None:
        tier, rationale = hit_rejected
        return tier, rationale, 1.0, False

    agent = Agent(
        make_model(model_id, local),
        output_type=TierClassifierOutput,
        system_prompt=TIER_CLASSIFIER_SYSTEM,
    )
    user = (
        f"Title: {title}\n"
        f"URL: {url}\n"
        f"Snippet: {snippet}\n\n"
        f"Content excerpt (first {CONTENT_EXCERPT_CHARS} chars):\n"
        f"{content[:CONTENT_EXCERPT_CHARS]}"
    )
    t0 = time.monotonic()
    try:
        r = await agent.run(user)
        out = r.output
    except Exception as exc:
        logger.warning("tier classifier failed url=%s err=%s", url, exc)
        return Tier.TIER_3, "classifier failed; default to generic web tier", 0.2, False
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if tracker is not None:
        usage = r.usage() if hasattr(r, "usage") else None
        if usage is not None:
            await tracker.record(model_id, usage, task_type="TIER_CLASSIFY")
            logger.info(
                "llm_call model=%s task=TIER_CLASSIFY in=%d out=%d ms=%d",
                model_id,
                getattr(usage, "input_tokens", 0) or 0,
                getattr(usage, "output_tokens", 0) or 0,
                elapsed_ms,
            )

    return Tier(out.tier), out.rationale, out.confidence, out.peer_reviewed


async def classify_source_via_runner(
    *,
    runner: LLMRunner,
    title: str,
    url: str,
    snippet: str,
    content: str,
) -> tuple[Tier, str, float, bool]:
    """Classify one source. Same semantics as classify_source() but routes
    through the LLMRunner seam instead of building an Agent directly.
    Reject-list short-circuits still apply and skip the LLM call."""
    hit_rejected = _reject_list_tier(url)
    if hit_rejected is not None:
        tier, rationale = hit_rejected
        return tier, rationale, 1.0, False

    user = (
        f"Title: {title}\n"
        f"URL: {url}\n"
        f"Snippet: {snippet}\n\n"
        f"Content excerpt (first {CONTENT_EXCERPT_CHARS} chars):\n"
        f"{content[:CONTENT_EXCERPT_CHARS]}"
    )
    try:
        result = await runner.run(
            role=RoleClass.CHEAP_DETERMINISTIC,
            tier=TaskTier.LOW,
            output_type=TierClassifierOutput,
            system_prompt=TIER_CLASSIFIER_SYSTEM,
            user_prompt=user,
            task_type="TIER_CLASSIFY",
            script_key="tier_classify",
        )
    except Exception as exc:
        logger.warning("tier classifier failed url=%s err=%s", url, exc)
        return Tier.TIER_3, "classifier failed; default to generic web tier", 0.2, False

    out = result.output
    return Tier(out.tier), out.rationale, out.confidence, out.peer_reviewed
