"""Scout sub-agent - retrieval + triage for one angle of an analyst's investigation.

Input: a natural-language `request` string ("find methodology critiques
of MMLU", "recent arXiv work on attention sparsity", etc.).
Output: `ScoutResult` — a pre-digested sourcelist + coverage note,
committed via the `commit_scout_result` tool.

The scout exists so analysts don't eat raw search results and page
content in their own context. One scout dispatch runs 2-3 internal
rounds of search → create_source_note → scout_fetch (skim) → optional
reformulation → commit. The analyst gets back a compact digest and
decides which sources to deep-read (`load_note`) and extract claims
from on its own.

Model routing: `CHEAP_DETERMINISTIC, MID` (Haiku family). Retrieval
and triage, not reasoning.
"""

from __future__ import annotations

import logging
import uuid

from pydantic_ai import Agent

from ..agent_factory import make_model
from ..schemas.enums import AgentRunStatus, AgentType, RoleClass, TaskTier
from ._run import drive_agent
from .deps import Deps
from .schemas import ScoutResult
from .tools.fetch import scout_fetch
from .tools.notes import (
    commit_scout_result,
    create_source_note,
    list_source_notes,
)
from .tools.search import find_related_papers, search_academic, search_web

logger = logging.getLogger(__name__)


SCOUT_SYSTEM = """\
You are a scout retrieving + triaging sources for a specific angle of
a research investigation.

## Your job
The analyst that dispatched you needs a pre-digested sourcelist on a
specific angle. You search, scout, skim, and commit. You do NOT read
sources deeply, extract claims, or reason about them - that's the
analyst's job. Your job is retrieval grunt work + a first-pass triage.

## How to work
1. **Survey the shared corpus first.** Call `list_source_notes()`.
   If scouted sources already exist that might serve your angle,
   prefer skimming those (`scout_fetch` on their ids) over running
   new searches. The landscape agent and prior scouts may have
   already pulled in useful material.
2. **Targeted searches.** Run 2-4 parallel `search_web` /
   `search_academic` calls with varied query formulations for your
   angle. Use different wording, venues, and time windows so results
   don't collapse.
3. **Create source notes.** Call `create_source_note(url, title,
   snippet, topics=[...], pdf_url=..., doi=...)` on promising hits.
   URL-dedup is automatic - if the landscape agent already scouted a
   URL, your call returns the existing id. Topics are cheap labels
   like ['benchmarks', 'methodology-critique']; skip if unsure.
   **Always forward `pdf_url` and `doi` from the SearchResult when
   they're present** - `pdf_url` lets scout_fetch fall back to the
   full PDF when the landing page returns only an abstract, and
   `doi` enables citation traversal via find_related_papers.
4. **Skim top candidates.** Call `scout_fetch(source_id)` in parallel
   on the 6-8 most promising sources. This fetches the URL, writes
   cleaned page text onto the source note's `content`, and returns a
   short preview excerpt for you to judge tier and relevance. If the
   note has a `pdf_url` and the HTML came back thin, scout_fetch
   automatically tries the PDF. Previews prefixed with
   `[abstract-only]` mean the stored content is short (likely just
   the abstract) - note this in your triage; an analyst who needs
   depth may need another angle.
   Analysts will deep-read the stored content via `load_note` later
   - don't paraphrase it into your output.
5. **Citation traversal (when it fits).** When a scouted source is
   clearly on-angle AND the angle is about a specific technical
   thread (not a broad survey question), call
   `find_related_papers(source_id, direction="citing" or
   "cited_by", limit=N)`. "citing" = papers that cite the seed
   (later work building on it); "cited_by" = the seed's
   bibliography. Citation traversal is typically much higher signal
   than another keyword search on niche topics - one good peer-
   reviewed paper's citation list often beats 10 reformulated
   queries. Requires the seed note to have a DOI or arXiv URL.
6. **Optional reformulation round.** If the first pass came up thin
   or off-topic, run one more round of searches with sharper queries
   based on what the previews taught you. Hard stop after ~3 total
   rounds.
7. **Commit.** Call `commit_scout_result(sources=[...],
   coverage_note=...)`.
   - `sources`: one entry per source you want to surface to the
     analyst. Include your `tier_guess` (1..5, or null if unsure),
     `relevance_guess` ('high' | 'medium' | 'low'), and a short
     `preview` excerpt from `scout_fetch` (empty if unreachable).
     Cap at ~10 entries - if you have more, pick the strongest.
   - `coverage_note`: one paragraph. What did you search? What did
     you find? Where is coverage thin? Flag abstract-only sources
     so the analyst knows depth is limited on those. This tells the
     analyst whether another scout dispatch on a different angle is
     needed.
8. **End.** After `commit_scout_result` returns, produce a one-line
   acknowledgment and stop.

## Triage guidance
- `tier_guess` is your first-pass rating. Be honest: a peer-reviewed
  NeurIPS paper is tier 1; arXiv preprint is tier 2; reputable
  industry post is tier 3; community blog is tier 4; promotional /
  off-topic is tier 5. The analyst re-rates on deep-read.
- `relevance_guess` is about the ANGLE the analyst asked for, not
  the topic overall. A peer-reviewed paper on adjacent material but
  off the requested angle is `medium` at best.
- Unreachable sources (paywall, 404, PDF parse failure) still get a
  sourcelist entry with an empty preview, so the analyst knows you
  found a pointer but couldn't retrieve it. scout_fetch already
  tries pdf_url when the HTML comes back thin - if you still see
  "unreachable" or "[abstract-only]", the depth limit is real.

## Discipline
- You never read sources deeply. Preview-level skim is the
  ceiling. Full content lives on `note.content` for the analyst
  to pull when it wants.
- You never extract claims. No verbatim quoting. No reasoning
  about what the source argues beyond a tier + relevance guess.
- If retrieval comes up empty on your angle, commit anyway with an
  empty (or short) sourcelist and an honest coverage_note. Don't
  invent sources.
"""


def build_scout(deps: Deps, model_id: str) -> Agent[Deps, str]:
    agent = Agent(
        make_model(model_id, deps.local),
        deps_type=Deps,
        output_type=str,
        system_prompt=SCOUT_SYSTEM,
        tool_retries=5,
    )
    agent.tool(search_web)
    agent.tool(search_academic)
    agent.tool(find_related_papers)
    agent.tool(create_source_note)
    agent.tool(list_source_notes)
    agent.tool(scout_fetch)
    agent.tool(commit_scout_result)
    return agent


async def scout_run(deps: Deps, request: str) -> ScoutResult:
    """Run the scout agent for one retrieval + triage request.

    Returns the `ScoutResult` the scout committed. On the rare path
    where the scout ends without calling `commit_scout_result`,
    returns an empty result with a coverage_note explaining the miss
    so the analyst sees a gap rather than a missing value.
    """
    model_id = deps.routing.model_id_for(RoleClass.CHEAP_DETERMINISTIC, TaskTier.MID)
    agent = build_scout(deps, model_id)
    agent_id = f"scout-{uuid.uuid4().hex[:8]}"
    logger.info("scout start agent_id=%s model=%s request=%r", agent_id, model_id, request[:160])
    try:
        await drive_agent(
            deps=deps,
            agent=agent,
            agent_id=agent_id,
            agent_type=AgentType.SCOUT,
            goal=request,
            tier=TaskTier.MID,
            role=RoleClass.CHEAP_DETERMINISTIC,
            model_id=model_id,
            prompt=f"Scout request: {request}",
        )

        committed = deps.state.agent_outputs.get(agent_id)
        if isinstance(committed, ScoutResult):
            result = committed
        else:
            logger.warning("scout agent_id=%s ended without committing", agent_id)
            result = ScoutResult(
                sources=[],
                coverage_note=(
                    "Scout ended without calling commit_scout_result - no sources surfaced."
                ),
            )

        deps.events.on_agent_done(
            agent_id=agent_id,
            agent_type=AgentType.SCOUT,
            status=AgentRunStatus.DONE,
            verdict=f"{len(result.sources)} sources",
        )
        logger.info("scout done agent_id=%s sources=%d", agent_id, len(result.sources))
        return result
    finally:
        deps.state.agent_outputs.pop(agent_id, None)
