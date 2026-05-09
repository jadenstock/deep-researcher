"""LLM batch relevance scorer.

When new sources arrive in the corpus (from any SCOUT_SOURCES task) or
new questions get spawned (from DECOMPOSE or replanner), every open
question needs a relevance score against every newly-scored source. A
per-(source, question) LLM call is too expensive; a deterministic
keyword-overlap score is too coarse (misses semantic relevance, e.g. a
source about "transformer attention" vs. a question about "sequence
modeling bottlenecks").

Strategy: one LLM call per source, evaluated against ALL open questions
in the same prompt. The model returns a 0-1 relevance score per question,
so a corpus of N sources x M questions costs N calls, not N*M.

Model: `cheap_deterministic` role, LOW tier (Haiku-class). Runs off the
retrieval hot path as its own RESCORE_RELEVANCE task (with
retrieval_ignores=True), so it doesn't block fetch or analyze.
"""

from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from ..agent_factory import make_model
from ..config import LocalConfig

logger = logging.getLogger(__name__)


RELEVANCE_SYSTEM = """\
You score how likely a source is to contain evidence bearing on each of
a set of research questions.

Given:
- a source (title + snippet + URL)
- a list of open research questions

Return a relevance score in [0.0, 1.0] for EACH question, where:
  - 0.0 — source is off-topic for this question; analyzing it would
    waste tokens.
  - 0.3 — source mentions the topic in passing; might have one usable
    claim at best.
  - 0.6 — source is clearly on-topic; likely to yield 1-3 usable claims.
  - 0.9 — source is a primary reference on this question; high-yield.

Be CALIBRATED, not generous. Most (source, question) pairs are 0.0-0.3.
A single source commonly scores high on 1-2 questions and low on the
rest. If a source appears to address multiple questions well, say so —
cross-question reuse is the point.

You MUST return exactly one score per question, keyed by the question's
`id` field (the q_XXXX identifier). Missing or extra entries are errors.
"""


class _ScoreEntry(BaseModel):
    question_id: str = Field(
        ..., description="The question's id — e.g. 'q_abc123'. Must match one of the inputs."
    )
    score: float = Field(..., ge=0.0, le=1.0, description="Relevance score in [0, 1].")
    rationale: str = Field(
        default="",
        description="Optional: one short phrase. Omit for obvious scores (0.0 / 0.9).",
    )


class RelevanceScores(BaseModel):
    """One source's scores across all open questions.

    `entries` must contain exactly one entry per input question. The
    caller validates this shape and falls back to 0.0 for any missing
    ids (degrading gracefully rather than failing the task).
    """

    entries: list[_ScoreEntry] = Field(default_factory=list)


async def score_source_against_questions(
    *,
    source_title: str,
    source_url: str,
    source_snippet: str,
    questions: list[tuple[str, str]],  # (question_id, question_text)
    model_id: str,
    local: LocalConfig,
) -> dict[str, float]:
    """Score one source against every open question. Returns
    {question_id: score}. Questions missing from the LLM output default
    to 0.0 (stricter than generous — a missing score shouldn't promote
    analysis of an unrelated source).
    """
    if not questions:
        return {}

    agent = Agent(
        make_model(model_id, local),
        output_type=RelevanceScores,
        system_prompt=RELEVANCE_SYSTEM,
    )

    question_block = "\n".join(f"- [{qid}] {qtext}" for qid, qtext in questions)
    user = (
        f"Source:\n"
        f"  Title: {source_title}\n"
        f"  URL: {source_url}\n"
        f"  Snippet: {source_snippet[:500]}\n\n"
        f"Open questions:\n{question_block}\n\n"
        f"Return one entry per question id above."
    )

    try:
        r = await agent.run(user)
        out = r.output
    except Exception as exc:
        logger.warning(
            "relevance_score_failed url=%s n_questions=%d err=%s",
            source_url[:80],
            len(questions),
            exc,
        )
        return {qid: 0.0 for qid, _ in questions}

    scored: dict[str, float] = {qid: 0.0 for qid, _ in questions}
    for entry in out.entries:
        if entry.question_id in scored:
            scored[entry.question_id] = entry.score
        else:
            logger.debug(
                "relevance unknown question_id=%s in scorer output for url=%s",
                entry.question_id,
                source_url[:80],
            )
    return scored


async def score_sources_batch(
    *,
    sources: list[tuple[str, str, str]],  # (url, title, snippet)
    questions: list[tuple[str, str]],  # (question_id, question_text)
    model_id: str,
    local: LocalConfig,
    concurrency: int = 6,
) -> dict[str, dict[str, float]]:
    """Score every source against every question. Parallelizes per-source
    LLM calls up to `concurrency`. Returns {source_url: {qid: score}}.

    Caller is responsible for canonicalizing URLs; we key by the URL the
    caller passes in (usually already canonical).
    """
    if not sources or not questions:
        return {}

    sem = asyncio.Semaphore(concurrency)

    async def _one(url: str, title: str, snippet: str) -> tuple[str, dict[str, float]]:
        async with sem:
            scores = await score_source_against_questions(
                source_title=title,
                source_url=url,
                source_snippet=snippet,
                questions=questions,
                model_id=model_id,
                local=local,
            )
        return url, scores

    results = await asyncio.gather(*(_one(u, t, s) for u, t, s in sources))
    return dict(results)
