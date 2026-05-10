"""Analyst sub-agent - investigate one specific question end-to-end.

Input: a (question_id, question_text) pair. The QUESTION note must
already exist in memory - the caller (researcher) is responsible for
creating it before dispatching the analyst.

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
from typing import Literal

from pydantic_ai import Agent

from ..agent_factory import make_model
from ..schemas.enums import RoleClass, TaskTier
from ..schemas.ids import NoteID
from ._debug import log_run_node
from ._usage import record_run_usage
from .deps import Deps
from .events import reset_current_agent_id, set_current_agent_id
from .schemas import QuestionSynthesis
from .tools.notes import (
    answer_question,
    list_source_notes,
    load_note,
    update_source_after_reading,
)
from .tools.scout_tool import scout

# Hard cap on scout sub-agent dispatches per analyst run. Prompt
# encourages fewer; this is the backstop so a misbehaving analyst
# can't runaway-spawn scouts.
DEFAULT_SCOUT_BUDGET = 4

logger = logging.getLogger(__name__)

AnalystMode = Literal["explore", "verify", "adversarial"]


# Mode-conditional framing block prepended to ANALYST_SYSTEM. Explore
# is the default (empty) framing; verify/adversarial add Round-3
# falsification discipline so the judgment-family model isn't just
# re-running the same investigation the explore already did.
MODE_FRAMING: dict[AnalystMode, str] = {
    "explore": "",
    "verify": """\
## Mode: VERIFY (Round 3 — falsification)
You are INDEPENDENTLY verifying a specific prior claim, not running a
fresh investigation. The question you were given references that prior
claim (often with a [question-...] ID).

Discipline for this mode:
  - If the question cites a prior question note (e.g. [question-abc123]),
    call `load_note` on it FIRST to read the claim you're testing.
  - Phrase your searches to deliberately find counter-evidence. Use
    different query wording, different venues, and different time
    windows than the original claim's sources used.
  - Your final report must explicitly state one of: SUPPORTS (new
    independent evidence confirms the claim), REFUTES (independent
    evidence contradicts it), or INCONCL (can't find evidence either
    way). Your `confidence` reflects how strong that verdict is.
  - Populate `disagreements` if your verdict differs from the original.

""",
    "adversarial": """\
## Mode: ADVERSARIAL (Round 3 — steelman the opposite)
You are constructing the strongest possible case AGAINST a prior
adopted position. This is not a balanced review. Your job is to make
the best argument for the opposite side.

Discipline for this mode:
  - If the question cites a prior question note (e.g. [question-abc123]),
    call `load_note` on it FIRST to read the position you're opposing.
  - Search for evidence, authors, and framings that the original
    investigation likely missed or dismissed.
  - Your `report` must LEAD with the counter-case, not a summary of
    both sides. Steelman, don't strawman.
  - Your `confidence` reflects how strong the counter-case is (high =
    the original position is seriously vulnerable; low = the original
    position largely survives scrutiny).
  - Populate `disagreements` with the specific points where you'd
    overturn the original.

""",
}


ANALYST_SYSTEM = """\
You are a research analyst investigating one specific question.

## Your job
Produce a rigorous, evidence-grounded answer to the question you're
given. You dispatch scout sub-agents for retrieval grunt work, then
deep-read the sources they surface and extract claims for your
question. Commit your final answer by UPDATING the question note you
were assigned - do not create a new note.

## You do NOT do retrieval directly
Search, fetch, paywall-handling, and first-pass triage are the
scout's job. You call `scout(request=...)` with a natural-language
angle and get back a pre-digested sourcelist. You never call
`search_web` or `fetch_url` - those are inside the scout. This keeps
your context full of signal, not SERP debris.

## Shared corpus
Before dispatching scouts, call `list_source_notes()`. The landscape
agent and prior analyst/scout dispatches may have already pulled in
relevant material. The condensed view shows:
  - `state`: SCOUTED (not fetched yet) / FETCHED (content on
    note.content, ready for deep-read) / ANALYZED (at least one
    reading exists)
  - `has_content`: True if cleaned page text is already on
    note.content - you can `load_note(id)` without dispatching a
    scout
  - `n_readings` + `analyzed_for_questions`: prior readings and the
    question_ids they were done for. If YOUR question_id isn't in
    `analyzed_for_questions`, the source hasn't been mined for your
    angle and you should deep-read it yourself (your reading appends
    to the stack; it doesn't overwrite others).
  - `topics`, `tier`, `peer_reviewed`, `summary`: source-intrinsic
    metadata from landscape or prior scouts.

## How to work
1. **Inventory.** Call `list_source_notes()`. Identify sources worth
   deep-reading for YOUR angle (has_content=True and either not yet
   analyzed or analyzed for unrelated questions).
2. **Dispatch scouts as needed.** If the existing corpus is thin on
   your angle, call `scout(request=...)` - optionally multiple times
   in parallel with distinct angles. Scout budget is 4 per run;
   spend them where they move the needle, not for breadth's sake.
   Scouts return ScoutResult with a sourcelist (tier_guess,
   relevance_guess, preview) and a coverage_note. They create the
   source notes and fetch content into `note.content` for you.
3. **Deep-read.** For each source you want to read fully, call
   `load_note(source_id)`. The `content` field holds the cleaned
   page text. Some sources from the scout may be unreachable (empty
   preview) - skip those, they'll have empty content.
4. **Record findings.** After reading, call
   `update_source_after_reading(source_id,
                                 for_question_id=<your question_id>,
                                 tier=..., tier_rationale=...,
                                 peer_reviewed=..., summary=...,
                                 relevance_note=..., claims=[...])`.
   This APPENDS a reading entry tagged with your agent_id and
   for_question_id; it does NOT overwrite prior readings by other
   analysts. Your claims + relevance_note live on your reading
   entry. 3-6 claims per useful source; every claim needs a
   verbatim quote from the content you just read.
     - tier 1 = peer-reviewed research, strong venues
     - tier 2 = arXiv / well-cited tech reports
     - tier 3 = reputable industry posts, official docs
     - tier 4 = community writeups, unreviewed blogs
     - tier 5 = low-quality, promotional, off-topic
5. **Commit your answer.** Call
   `answer_question(question_id=<the id you were given>, ...)`.
   TERMINAL tool - DO NOT finish your turn without calling it. Fix
   and retry on validation errors.

   Your `report` markdown should cover, in roughly this order:
     a. Direct answer to the question (1-3 sentence takeaway).
     b. Key findings, each with source grounding and tier noted.
     c. Documented limitations and failure modes the sources
        identified.
     d. Competing approaches or dissenting positions the sources
        surfaced.
     e. Evidence-basis note: what the strongest evidence rests on
        (peer-reviewed? preprint-only? single author? industry
        consensus?). Be explicit when findings lean on preprints
        or single-source industry claims.

   Slots (c) and (d) are not optional - if the sources didn't
   surface limitations or competing approaches, say so explicitly
   ("sources did not surface documented failure modes"). Silence is
   ambiguous; stating the gap is a finding.

   When writing the report, annotate each material claim with its
   grounding: `[source-abc123]` for single-source claims,
   `[source-abc, source-def, source-ghi]` for multi-source. Call
   out explicitly when a central finding is single-source-only -
   this is information the researcher needs to decide whether to
   dispatch a `verify` against it.
6. **End.** After `answer_question` returns, produce a one-line
   acknowledgment and stop.

## Discipline
- Prefer multiple, diverse sources over one authoritative-looking
  one.
- Quote claims verbatim. If you can't find a supporting quote, drop
  the claim. Never invent quotes.
- **Tier-4 / community sources are background, not load-bearing.**
  Treat blogs, forum posts, practitioner writeups, and vendor
  content as signal about *what people are doing or thinking* -
  useful for landscape, failure stories, and naming competing
  approaches. Never anchor a core claim to them. If a claim is
  only supported by tier-4 sources, either find a tier-1-3 source
  that corroborates it or mark it explicitly as "community
  reported, not independently verified" in the report.
- Unreachable sources from a scout (empty preview) are not worth
  retrying - the scout already tried. Move on.
- Don't over-investigate. 4-8 deep-read sources beats 20
  half-skimmed ones.
- If `list_source_notes` shows a source already has `has_content` +
  a reading for an unrelated question, prefer `load_note` on it
  over dispatching another scout - the scout would just re-scout
  what you already have.
"""


def _routing_for_mode(mode: AnalystMode) -> tuple[RoleClass, TaskTier]:
    """Map dispatch mode to (role_class, tier) for model resolution.

    explore stays on the generative family (current behavior).
    verify/adversarial route to the judgment family so their output
    comes from a different model family than the explore that
    produced the claim/position being challenged — ADR 0008.
    """
    if mode == "explore":
        return RoleClass.GENERATIVE, TaskTier.MID
    return RoleClass.JUDGMENT, TaskTier.MID


def build_analyst(deps: Deps, mode: AnalystMode, model_id: str) -> Agent[Deps, str]:
    system_prompt = MODE_FRAMING[mode] + ANALYST_SYSTEM
    agent = Agent(
        make_model(model_id, deps.local),
        deps_type=Deps,
        output_type=str,
        system_prompt=system_prompt,
        tool_retries=5,
    )
    agent.tool(scout)
    agent.tool(list_source_notes)
    agent.tool(load_note)
    agent.tool(update_source_after_reading)
    agent.tool(answer_question)
    return agent


async def analyst_run(
    deps: Deps,
    question_id: NoteID,
    question: str,
    mode: AnalystMode = "explore",
) -> QuestionSynthesis:
    """Run the analyst against a pre-created QUESTION note.

    `mode` selects the model family + framing block:
      - "explore" (default): generative family; fresh investigation.
      - "verify": judgment family; Round-3 independent re-retrieval
        on a specific prior claim.
      - "adversarial": judgment family; Round-3 steelman the opposite
        of a prior adopted position.

    Returns the QuestionSynthesis. On the rare path where the agent
    ends without calling answer_question, returns a low-confidence
    fallback so the researcher sees a gap rather than a missing result.
    """
    role, tier = _routing_for_mode(mode)
    model_id = deps.routing.model_id_for(role, tier)
    agent = build_analyst(deps, mode, model_id)
    agent_id = f"an-{uuid.uuid4().hex[:8]}"
    deps.events.on_agent_start(
        agent_id=agent_id,
        agent_type="ANALYST",
        goal=question,
        tier=tier.value,
        role=role.value,
        model_id=model_id,
        mode=mode,
    )
    logger.info(
        "analyst start agent_id=%s qid=%s mode=%s model=%s q=%r",
        agent_id,
        question_id,
        mode,
        model_id,
        question[:140],
    )
    # Per-analyst-run scout dispatch budget. Scouts don't count against
    # the researcher's analyst budget - independent resource.
    deps.outputs["__scout_budget__"] = DEFAULT_SCOUT_BUDGET

    token = set_current_agent_id(agent_id)
    try:
        try:
            # `agent.iter()` so the finally-block can still read
            # `run.usage()` when a deep tool call raises.
            async with agent.iter(
                (
                    f"Your assigned question_id is {question_id}.\n"
                    f"Question: {question}\n"
                    f"You have {DEFAULT_SCOUT_BUDGET} scout dispatches available.\n"
                    "When you commit your answer, pass question_id="
                    f"{question_id} to answer_question."
                ),
                deps=deps,
            ) as run:
                try:
                    async for node in run:
                        log_run_node(agent_id, node)
                finally:
                    await record_run_usage(
                        deps,
                        run.usage(),
                        agent_id=agent_id,
                        agent_type="ANALYST",
                        model_id=model_id,
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
                report=("_(no report produced - analyst ended without calling answer_question)_"),
                confidence="low",
                open_issues=[
                    "Analyst did not call answer_question before ending its turn.",
                ],
            )

        verdict = f"{mode}: {qs.confidence} confidence, {len(qs.sources_cited)} sources cited"
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
        deps.outputs.pop("__scout_budget__", None)
