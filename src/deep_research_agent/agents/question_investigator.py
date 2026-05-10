"""Sub-agent: investigate one question end-to-end.

Input: a specific research question (string).
Output: a `QuestionSynthesis`, committed by the sub-agent via the
`write_question_synthesis` tool (NOT via pydantic-ai structured
output). The wrapping `investigate_question_run` reads the committed
payload back from `deps.outputs[agent_id]`.

Why a tool instead of output_type: structured-output validation on
long-form fields is brittle - the model occasionally omits a field,
and pydantic-ai's output-retry loop is tight. Moving commit to a
tool converts the validation failure into a tool error that the
model sees natively and retries in-turn; it also creates a durable
synthesis_note as a side effect so the work survives any later crash.

This agent is itself invoked as a tool (`investigate_question`) by
the top-level `researcher` agent. Multiple investigators run in
parallel - pydantic-ai dispatches a turn's tool calls concurrently,
so a researcher asking about N sub-questions spins up N investigators
that each fan out their own searches.
"""

from __future__ import annotations

import logging
import uuid

from pydantic_ai import Agent

from ..agent_factory import make_model
from ..schemas.enums import RoleClass, TaskTier
from .deps import Deps
from .events import reset_current_agent_id, set_current_agent_id
from .schemas import QuestionSynthesis
from .tools.fetch import fetch_url
from .tools.notes import (
    create_source_note,
    list_source_notes,
    load_note,
    update_source_after_reading,
    write_question_synthesis,
)
from .tools.search import search_academic, search_web

logger = logging.getLogger(__name__)


QUESTION_INVESTIGATOR_SYSTEM = """\
You are a research analyst investigating one specific question.

## Your job
Produce a rigorous, evidence-grounded answer to the question you're
given. You have tools to search the web, fetch URLs, and record
findings as source notes in shared memory.

## How to work
1. **Plan searches.** Think about what kinds of sources would answer
   this question. Peer-reviewed literature? Benchmarks? Industry
   posts? Run multiple searches in parallel (call `search_web` and
   `search_academic` in the same turn - they'll execute concurrently).
2. **Scout promising hits.** For the top ~6-10 candidates across your
   searches, call `create_source_note(url, title, snippet)` to reserve
   a handle. You can do this in parallel too.
3. **Fetch and read.** Call `fetch_url(url)` on the candidates you want
   to read. Again, fetch in parallel - one turn can issue many fetches.
   Some URLs will fail (404, paywall, PDF extraction errors); move on.
4. **Record what you learned.** After reading a source, call
   `update_source_after_reading(source_id, tier=..., claims=[...], ...)`
   with:
     - tier 1 = peer-reviewed research in strong venues
     - tier 2 = arXiv preprints / well-cited technical reports
     - tier 3 = reputable industry posts, official docs, respected newsletters
     - tier 4 = community writeups, unreviewed blog posts
     - tier 5 = low-quality, promotional, or off-topic
   Extract 3-6 key claims per useful source. Every claim needs a
   verbatim quote - never paraphrase a quote.
5. **Loop as needed.** If your initial searches didn't surface good
   sources, run more searches with reformulated queries. If you've
   already found strong evidence, move on.
6. **Commit your synthesis.** When you have enough coverage, call
   `write_question_synthesis(...)` with the full structured payload:
     - `question`: the question you were assigned.
     - `bottom_line`: one or two sentences answering it directly.
     - `synthesis`: multi-paragraph markdown write-up. Cite source
       notes inline like [source-abc123].
     - `confidence`: 'high' / 'medium' / 'low' based on source
       quality and convergence.
     - `sources_cited`: NoteIDs of the sources whose claims feed
       this synthesis.
     - `disagreements`: points where sources conflict (or empty).
     - `open_issues`: things you couldn't answer and why (or empty).
   This tool is your commit step - DO NOT finish your turn without
   calling it. If the tool returns a validation error, fix the
   offending field and call it again.
7. **End.** After `write_question_synthesis` returns successfully,
   produce a one-line acknowledgment ("Committed synthesis for
   question ...") and stop.

## Discipline
- Prefer multiple, diverse sources over one authoritative-looking one.
- Quote claims verbatim. If you can't find a supporting quote in the
  content, don't invent one - drop the claim.
- If a source is paywalled or fails to fetch, note it and move on.
- Don't over-investigate. A well-scoped question with 4-8 analyzed
  sources is better than 20 half-read ones.
"""


def build_investigator_for_run(deps: Deps) -> Agent[Deps, str]:
    """Construct the investigator. Output is `str` (a final
    one-line acknowledgment); the actual QuestionSynthesis is
    committed via `write_question_synthesis` and read back from
    `deps.outputs`.
    """
    model_id = deps.routing.model_id_for(RoleClass.GENERATIVE, TaskTier.MID)
    agent = Agent(
        make_model(model_id, deps.local),
        deps_type=Deps,
        output_type=str,
        system_prompt=QUESTION_INVESTIGATOR_SYSTEM,
    )
    agent.tool(search_web)
    agent.tool(search_academic)
    agent.tool(fetch_url)
    agent.tool(create_source_note)
    agent.tool(update_source_after_reading)
    agent.tool(load_note)
    agent.tool(list_source_notes)
    agent.tool(write_question_synthesis)
    return agent


async def investigate_question_run(deps: Deps, question: str) -> QuestionSynthesis:
    """Run the investigator for a single question.

    Returns the QuestionSynthesis the sub-agent committed via
    `write_question_synthesis`. If the sub-agent ended without
    calling that tool, returns a fallback synthesis marked
    low-confidence so the researcher still has something structured
    to work with.
    """
    agent = build_investigator_for_run(deps)
    agent_id = f"inv-{uuid.uuid4().hex[:8]}"
    model_id = deps.routing.model_id_for(RoleClass.GENERATIVE, TaskTier.MID)
    deps.events.on_agent_start(
        agent_id=agent_id,
        agent_type="INVESTIGATE_QUESTION",
        goal=question,
        tier=TaskTier.MID.value,
        role=RoleClass.GENERATIVE.value,
        model_id=model_id,
    )
    logger.info("investigate_question start agent_id=%s q=%r", agent_id, question[:140])
    # Scope the current-agent contextvar so tool calls emit events
    # tagged with this agent_id and so `write_question_synthesis`
    # stashes its payload under THIS agent's key in deps.outputs.
    token = set_current_agent_id(agent_id)
    try:
        try:
            await agent.run(f"Investigate this question: {question}", deps=deps)
        except Exception as exc:
            deps.events.on_agent_done(
                agent_id=agent_id,
                agent_type="INVESTIGATE_QUESTION",
                status="ABANDONED",
                verdict=f"failed: {type(exc).__name__}: {exc}"[:200],
            )
            raise

        # Read the committed payload back. If the tool was never
        # called, fabricate a low-confidence fallback rather than
        # raising - the researcher can still report the gap, and the
        # other sub-agents' work isn't lost.
        committed = deps.outputs.get(agent_id)
        if isinstance(committed, QuestionSynthesis):
            qs = committed
        else:
            logger.warning(
                "investigate_question agent_id=%s ended without calling "
                "write_question_synthesis; returning fallback",
                agent_id,
            )
            qs = QuestionSynthesis(
                question=question,
                bottom_line=(
                    "(no synthesis produced - sub-agent ended without committing a final answer)"
                ),
                synthesis="",
                confidence="low",
                open_issues=[
                    "Sub-agent did not call write_question_synthesis before ending its turn.",
                ],
            )

        verdict = f"{qs.confidence} confidence, {len(qs.sources_cited)} sources cited"
        deps.events.on_agent_done(
            agent_id=agent_id,
            agent_type="INVESTIGATE_QUESTION",
            status="DONE",
            verdict=verdict,
        )
        logger.info(
            "investigate_question done agent_id=%s q=%r confidence=%s sources_cited=%d",
            agent_id,
            question[:140],
            qs.confidence,
            len(qs.sources_cited),
        )
        return qs
    finally:
        reset_current_agent_id(token)
        # Free the slot - avoids unbounded growth of deps.outputs
        # across long runs with many sub-agents.
        deps.outputs.pop(agent_id, None)
