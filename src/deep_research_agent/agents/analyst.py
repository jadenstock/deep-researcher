"""Analyst sub-agent - investigate one specific question end-to-end.

Input: a (question_id, question_text) pair. The QUESTION note must
already exist in memory - the caller (researcher) is responsible for
creating it via create_question_note before dispatching the analyst.

Output: the analyst commits its answer by UPDATING the question note
in place via the `answer_question` tool. The wrapping
`analyst_run` reads the resulting QuestionSynthesis back from
deps.outputs and returns it.

Why the caller owns the question_id: it lets the researcher track
its question tree (open/answered, parent links, dispatch state)
without needing the analyst to echo metadata back. It also means a
crash mid-investigation still leaves a durable OPEN question note
that the researcher can see and re-dispatch on.
"""

from __future__ import annotations

import logging
import uuid

from pydantic_ai import Agent

from ..agent_factory import make_model
from ..schemas.enums import RoleClass, TaskTier
from ..schemas.ids import NoteID
from .deps import Deps
from .events import reset_current_agent_id, set_current_agent_id
from .schemas import QuestionSynthesis
from .tools.fetch import fetch_url
from .tools.notes import (
    answer_question,
    create_source_note,
    list_source_notes,
    load_note,
    update_source_after_reading,
)
from .tools.search import search_academic, search_web

logger = logging.getLogger(__name__)


ANALYST_SYSTEM = """\
You are a research analyst investigating one specific question.

## Your job
Produce a rigorous, evidence-grounded answer to the question you're
given. You have tools to search the web, fetch URLs, and record
findings as source notes in shared memory. Commit your final answer
by UPDATING the question note you were assigned - do not create a
new note for the answer.

## Shared corpus
Before running fresh searches, call `list_source_notes()`. A
landscape scouting agent may have already scouted many sources for
this topic. Prefer picking up those SCOUTED sources over duplicating
the search work. You can still run your own searches if the existing
corpus doesn't cover your angle.

## How to work
1. **Inventory.** Call `list_source_notes()`. If there are already
   promising SCOUTED sources relevant to your question, start with
   fetching those.
2. **Targeted search if needed.** If the existing corpus is thin on
   your specific angle, run `search_web` / `search_academic` in
   parallel. Use `create_source_note(url, title, snippet)` on
   promising hits - this dedups by URL automatically, so calling it
   on a URL landscape already scouted just returns the existing id.
3. **Fetch and read.** Call `fetch_url(url)` on the sources you want
   to read. Fetch in parallel - one turn can issue many fetches.
   Some URLs will fail (404, paywall, PDF errors); move on.
4. **Record findings.** After reading a source, call
   `update_source_after_reading(source_id, tier=..., claims=[...], ...)`
   with 3-6 claims per useful source. Every claim needs a verbatim quote.
     - tier 1 = peer-reviewed research, strong venues
     - tier 2 = arXiv / well-cited tech reports
     - tier 3 = reputable industry posts, official docs
     - tier 4 = community writeups, unreviewed blogs
     - tier 5 = low-quality, promotional, off-topic
5. **Commit your answer.** Call
   `answer_question(question_id=<the id you were given>, ...)`.
   This tool is your commit step - DO NOT finish your turn without
   calling it. If it returns a validation error, fix the field and
   call again.
6. **End.** After `answer_question` returns, produce a one-line
   acknowledgment ("Answered question ...") and stop.

## Discipline
- Prefer multiple, diverse sources over one authoritative-looking one.
- Quote claims verbatim. If you can't find a supporting quote, drop
  the claim - don't invent one.
- If a source is paywalled or fails to fetch, note it and move on.
- Don't over-investigate. 4-8 analyzed sources beats 20 half-read ones.
"""


def build_analyst(deps: Deps) -> Agent[Deps, str]:
    model_id = deps.routing.model_id_for(RoleClass.GENERATIVE, TaskTier.MID)
    agent = Agent(
        make_model(model_id, deps.local),
        deps_type=Deps,
        output_type=str,
        system_prompt=ANALYST_SYSTEM,
        tool_retries=5,
    )
    agent.tool(search_web)
    agent.tool(search_academic)
    agent.tool(fetch_url)
    agent.tool(create_source_note)
    agent.tool(update_source_after_reading)
    agent.tool(load_note)
    agent.tool(list_source_notes)
    agent.tool(answer_question)
    return agent


async def analyst_run(
    deps: Deps,
    question_id: NoteID,
    question: str,
) -> QuestionSynthesis:
    """Run the analyst against a pre-created QUESTION note.

    Returns the QuestionSynthesis. On the rare path where the agent
    ends without calling answer_question, returns a low-confidence
    fallback so the researcher sees a gap rather than a missing result.
    """
    agent = build_analyst(deps)
    agent_id = f"an-{uuid.uuid4().hex[:8]}"
    model_id = deps.routing.model_id_for(RoleClass.GENERATIVE, TaskTier.MID)
    deps.events.on_agent_start(
        agent_id=agent_id,
        agent_type="ANALYST",
        goal=question,
        tier=TaskTier.MID.value,
        role=RoleClass.GENERATIVE.value,
        model_id=model_id,
    )
    logger.info("analyst start agent_id=%s qid=%s q=%r", agent_id, question_id, question[:140])
    token = set_current_agent_id(agent_id)
    try:
        try:
            await agent.run(
                (
                    f"Your assigned question_id is {question_id}.\n"
                    f"Question: {question}\n"
                    "When you commit your answer, pass question_id="
                    f"{question_id} to answer_question."
                ),
                deps=deps,
            )
        except Exception as exc:
            deps.events.on_agent_done(
                agent_id=agent_id,
                agent_type="ANALYST",
                status="ABANDONED",
                verdict=f"failed: {type(exc).__name__}: {exc}"[:200],
            )
            raise

        committed = deps.outputs.get(agent_id)
        if isinstance(committed, QuestionSynthesis):
            qs = committed
        else:
            logger.warning(
                "analyst agent_id=%s qid=%s ended without committing",
                agent_id,
                question_id,
            )
            qs = QuestionSynthesis(
                question=question,
                bottom_line=(
                    "(no synthesis produced - analyst ended without calling answer_question)"
                ),
                synthesis="",
                confidence="low",
                open_issues=[
                    "Analyst did not call answer_question before ending its turn.",
                ],
            )

        verdict = f"{qs.confidence} confidence, {len(qs.sources_cited)} sources cited"
        deps.events.on_agent_done(
            agent_id=agent_id,
            agent_type="ANALYST",
            status="DONE",
            verdict=verdict,
        )
        logger.info(
            "analyst done agent_id=%s qid=%s confidence=%s sources_cited=%d",
            agent_id,
            question_id,
            qs.confidence,
            len(qs.sources_cited),
        )
        return qs
    finally:
        reset_current_agent_id(token)
        deps.outputs.pop(agent_id, None)
