"""Landscape agent - wide-filter scouting before the researcher decomposes.

Input: the user's query (string).
Output: `LandscapeBrief`, a free-form markdown brief, committed via the
`write_landscape_brief` tool. As a side effect, leaves a pile of
SCOUTED source notes in memory (topic-tagged) that analysts can pick
up without re-searching the same territory.

The agent is allowed up to ~4 rounds of searches within a single
agent.run - it's prompt-enforced, not harness-enforced. Stops early
on diminishing returns.
"""

from __future__ import annotations

import logging
import uuid

from pydantic_ai import Agent

from ..agent_factory import make_model
from ..schemas.enums import AgentRunStatus, AgentType, NoteType, RoleClass, TaskTier
from ._run import drive_agent
from .deps import Deps
from .tools.notes import create_source_note, list_source_notes, write_landscape_brief
from .tools.search import search_academic, search_web

logger = logging.getLogger(__name__)


LANDSCAPE_SYSTEM = """\
You are a scouting agent mapping the landscape around a research query.

## Your job
Cast a wide net. Run multiple rounds of searches and create SCOUTED
source notes for anything even plausibly relevant. You do NOT read
sources or extract claims - that's the analysts' job downstream. Your
only deliverable is a short markdown brief that tells a downstream
researcher what the terrain looks like.

## How to work
1. **Round 1 — broad sweep.** Run 3-5 parallel `search_web` /
   `search_academic` calls with varied query formulations around the
   user's topic. For each promising hit (relevance: plausible, not
   certain), call `create_source_note(url, title, snippet, topics=[...])`
   with 1-3 short topic labels. Topics are cheap signals like
   ['benchmarks'], ['survey', 'methodology'], ['position-paper'],
   ['tooling']. Source dedup by URL happens automatically.
2. **Review coverage.** Call `list_source_notes()` to see what you've
   gathered. Look for topic gaps ("I have lots on benchmarks but
   nothing on methodology critiques") and source-type imbalance.
3. **Further rounds (up to 3 more).** Run more searches targeting the
   gaps you noticed. Reformulate queries to find what round 1 missed.
   Each round should add genuinely new sources - if a round adds
   fewer than 2 new (non-duplicate) sources, stop immediately.
4. **Hard stop.** Never run more than 4 rounds total. If after 4 you
   still feel thin, the brief should say so.
5. **Commit the brief.** Call `write_landscape_brief(brief_markdown)`.
   Keep it tight (~300-600 words). Useful things to include when
   relevant (you decide):
     - apparent sub-areas or themes the corpus splits into
     - obvious gaps / under-covered angles
     - terminology the field uses (so the researcher can decompose well)
     - source clusters (which venues, which outlets)
     - contested points you noticed in the snippets
   Do NOT paraphrase full source content - the researcher sees the
   source list separately. Cite sources inline as [source-abc123].
6. **End.** After `write_landscape_brief` returns, produce a one-line
   acknowledgment and stop.

## Discipline
- Wide filter: pull anything even kind of relevant. The analysts
  downstream will filter on quality; you filter on "is this in the
  neighborhood of the topic at all".
- Don't read content. Don't call fetch_url. Snippets are enough.
- Don't over-commit to what you think the decomposition should be.
  You're describing terrain, not planning the investigation.
"""


def build_landscape_agent(deps: Deps) -> Agent[Deps, str]:
    model_id = deps.routing.model_id_for(RoleClass.GENERATIVE, TaskTier.MID)
    agent = Agent(
        make_model(model_id, deps.local),
        deps_type=Deps,
        output_type=str,
        system_prompt=LANDSCAPE_SYSTEM,
        tool_retries=5,
    )
    agent.tool(search_web)
    agent.tool(search_academic)
    agent.tool(create_source_note)
    agent.tool(list_source_notes)
    agent.tool(write_landscape_brief)
    return agent


async def landscape_run(deps: Deps, query: str) -> str:
    """Run the landscape agent for the query.

    Returns the brief markdown the agent committed. On the (rare) path
    where the agent ends without committing, returns a placeholder so
    the researcher can still proceed (with a noted limitation).
    """
    agent = build_landscape_agent(deps)
    agent_id = f"land-{uuid.uuid4().hex[:8]}"
    model_id = deps.routing.model_id_for(RoleClass.GENERATIVE, TaskTier.MID)
    logger.info("landscape start agent_id=%s query=%r", agent_id, query[:200])
    try:
        await drive_agent(
            deps=deps,
            agent=agent,
            agent_id=agent_id,
            agent_type=AgentType.LANDSCAPE,
            goal=query,
            tier=TaskTier.MID,
            role=RoleClass.GENERATIVE,
            model_id=model_id,
            prompt=f"Scout the landscape for this query: {query}",
        )

        committed = deps.state.agent_outputs.get(agent_id)
        if isinstance(committed, str) and committed.strip():
            brief = committed
        else:
            logger.warning(
                "landscape agent_id=%s ended without calling write_landscape_brief",
                agent_id,
            )
            brief = (
                "_(landscape agent ended without producing a brief; "
                "researcher should proceed with the source list alone)_"
            )

        n_sources = deps.memory.count_by_type(NoteType.SOURCE)
        deps.events.on_agent_done(
            agent_id=agent_id,
            agent_type=AgentType.LANDSCAPE,
            status=AgentRunStatus.DONE,
            verdict=f"brief committed, {n_sources} sources scouted",
        )
        logger.info("landscape done agent_id=%s sources=%d", agent_id, n_sources)
        return brief
    finally:
        deps.state.agent_outputs.pop(agent_id, None)
