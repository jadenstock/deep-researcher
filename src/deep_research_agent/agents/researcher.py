"""Top-level researcher agent.

Entry point for a research run. Takes a natural-language query,
decomposes it into sub-questions, invokes the `investigate_question`
sub-agent (as a tool) for each in parallel, and composes a final
`ResearcherReport` committed via the `write_research_report` tool.

Parallelism: the researcher can emit multiple `investigate_question`
tool calls in the same turn; pydantic-ai dispatches them concurrently
via `asyncio.gather`. Each sub-agent internally issues its own
concurrent search/fetch calls, so parallelism stacks across levels.

Output commit: the agent's `output_type` is `str` (a terminal
acknowledgment). The actual report is written via
`write_research_report`, a tool call. Pydantic validates the tool's
args; if they're malformed, pydantic-ai returns a descriptive error
to the model which retries in the same turn. The tool creates a
synthesis_note (durable) and stashes the ResearcherReport in
`deps.outputs`. The wrapping `research_run` reads it back.
"""

from __future__ import annotations

import logging
import uuid

from pydantic_ai import Agent, RunContext

from ..agent_factory import make_model
from ..schemas.enums import RoleClass, TaskTier
from .deps import Deps
from .events import reset_current_agent_id, set_current_agent_id
from .question_investigator import investigate_question_run
from .schemas import QuestionSynthesis, ResearcherReport
from .tools.notes import (
    create_question_note,
    list_source_notes,
    load_note,
    write_research_report,
)
from .tools.search import search_academic, search_web

logger = logging.getLogger(__name__)


RESEARCHER_SYSTEM = """\
You are the director of a research investigation.

## Your job
Given a user's research query, produce a thorough, evidence-grounded
final report. You delegate specific questions to sub-agents via the
`investigate_question` tool, then compose a synthesis across their
answers and commit it via the `write_research_report` tool.

## How to work
1. **Orient.** Run a couple of `search_web` / `search_academic` calls
   against the user's query to size the territory. Don't read anything
   yet - you're just deciding how to decompose. Run searches in
   parallel (multiple tool calls in one turn).
2. **Decompose.** Break the query into 2-5 focused sub-questions. A
   good sub-question is answerable in its own right with a few
   sources. Avoid overlapping sub-questions. Call
   `create_question_note(question, classification=...)` for each;
   this records your plan in memory.
3. **Dispatch.** Call `investigate_question(question=...)` for each
   sub-question. Issue these calls in parallel - one turn with N tool
   calls - so the investigators run concurrently. Each investigator
   returns a `QuestionSynthesis`.
4. **Commit the final report.** After all sub-agent investigations
   are in, call `write_research_report(...)` with:
     - `bottom_line`: 2-4 sentence executive answer to the query.
     - `report_markdown`: the full report synthesizing across
       sub-questions. Use markdown - headers, prose, lists. Cite
       source notes inline as [source-abc123].
     - `cross_cutting_synthesis` (optional): 1-3 paragraphs on
       themes that emerge ACROSS the sub-questions.
     - `limitations`: things the report couldn't cover or where
       confidence is shaky.
   This tool is your commit step - DO NOT finish your turn without
   calling it. If the tool returns a validation error, fix the
   offending field and call it again.
5. **End.** After `write_research_report` returns successfully,
   produce a one-line acknowledgment and stop.

## Judgment calls
- If the query is simple enough for one investigation, decompose to
  one sub-question. Don't force structure.
- If an investigator returns low confidence or many open issues,
  consider dispatching a follow-up investigation targeting the gap -
  but only once. Don't loop indefinitely.

## Quality bar
- Every factual claim in the report should trace to a source note.
- Cite liberally - [source-...] references are the spine of the
  report's credibility.
- If sources disagree, say so. Don't paper over it.
"""


def build_researcher(deps: Deps) -> Agent[Deps, str]:
    """Build the top-level researcher agent.

    Uses GENERATIVE/HIGH for the model - top-level composition
    benefits from the strongest reasoning available. Sub-agents run
    on GENERATIVE/MID.
    """
    model_id = deps.routing.model_id_for(RoleClass.GENERATIVE, TaskTier.HIGH)
    agent = Agent(
        make_model(model_id, deps.local),
        deps_type=Deps,
        output_type=str,
        system_prompt=RESEARCHER_SYSTEM,
    )

    # Direct tools - the researcher does lightweight scouting itself
    # before delegating and reads notes to compose the final report.
    agent.tool(search_web)
    agent.tool(search_academic)
    agent.tool(create_question_note)
    agent.tool(list_source_notes)
    agent.tool(load_note)
    agent.tool(write_research_report)

    @agent.tool
    async def investigate_question(ctx: RunContext[Deps], question: str) -> QuestionSynthesis:
        """Delegate a specific sub-question to a research sub-agent.

        The sub-agent searches, reads sources, extracts claims, and
        commits a `QuestionSynthesis` into shared memory. The tool
        returns that synthesis back to you as structured data so you
        can compose your final report. Safe to call multiple times
        per turn to dispatch sub-questions in parallel.
        """
        return await investigate_question_run(ctx.deps, question)

    return agent


async def research_run(deps: Deps, query: str) -> ResearcherReport:
    """Execute a full research run. Entry point for the CLI + server.

    Returns the ResearcherReport the agent committed via
    `write_research_report`. On the (rare) path where the agent ends
    without calling the tool, returns a minimal report reconstructed
    from whatever synthesis_notes are in memory so the run still
    produces something useful.
    """
    agent = build_researcher(deps)
    agent_id = f"res-{uuid.uuid4().hex[:8]}"
    model_id = deps.routing.model_id_for(RoleClass.GENERATIVE, TaskTier.HIGH)
    deps.events.on_agent_start(
        agent_id=agent_id,
        agent_type="RESEARCHER",
        goal=query,
        tier=TaskTier.HIGH.value,
        role=RoleClass.GENERATIVE.value,
        model_id=model_id,
    )
    logger.info("researcher start agent_id=%s query=%r", agent_id, query[:200])
    # Scope the current-agent contextvar so tool calls emit events
    # tagged with the researcher's id and so write_research_report
    # stashes its payload under THIS key.
    token = set_current_agent_id(agent_id)
    try:
        try:
            await agent.run(f"User query: {query}", deps=deps)
        except Exception as exc:
            deps.events.on_agent_done(
                agent_id=agent_id,
                agent_type="RESEARCHER",
                status="ABANDONED",
                verdict=f"failed: {type(exc).__name__}: {exc}"[:200],
            )
            raise

        # Read the committed report from where write_research_report
        # stashed it. If the tool was never called, synthesize a
        # minimal report from whatever we have.
        committed = deps.outputs.get(agent_id)
        if isinstance(committed, ResearcherReport):
            report = committed.model_copy(update={"query": query})
        else:
            logger.warning(
                "researcher agent_id=%s ended without calling "
                "write_research_report; building minimal report",
                agent_id,
            )
            report = ResearcherReport(
                query=query,
                bottom_line=(
                    "(no top-level report committed - agent ended "
                    "without calling write_research_report)"
                ),
                report_markdown="",
                limitations=["Top-level researcher did not commit a final report."],
            )

        verdict = f"{len(deps.memory)} notes committed"
        deps.events.on_agent_done(
            agent_id=agent_id,
            agent_type="RESEARCHER",
            status="DONE",
            verdict=verdict,
        )
        logger.info(
            "researcher done agent_id=%s query=%r",
            agent_id,
            query[:200],
        )
        return report
    finally:
        reset_current_agent_id(token)
