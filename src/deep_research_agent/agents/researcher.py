"""Top-level researcher - iterative orchestrator over landscape + analysts.

Flow:
  1. Create root QUESTION note from the user's query.
  2. Run landscape agent (blocking). Landscape leaves SCOUTED sources
     and commits a markdown brief.
  3. Build an opening prompt that includes the query + landscape brief
     + a compact source list (id, url, title, topics, snippet).
  4. Researcher loops:
       get_research_state() -> decide next move
       - investigate_question(question): dispatch analyst in parallel
       - answer_question(root_id, ...): commit final report & stop
     The researcher NEVER reads raw source content. Analysts do.

Budget: a per-run cap on analyst dispatches. `deps.outputs["__analyst_budget__"]`
starts at the cap and decrements on each dispatch; when 0 the
investigate_question tool refuses.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from pydantic_ai import Agent, ModelRetry, RunContext

from ..agent_factory import make_model
from ..schemas.enums import NoteType, QuestionClassification, RoleClass, TaskTier
from ..schemas.ids import NoteID
from ..schemas.note import Note, QuestionMetadata, SourceNoteMetadata
from .analyst import analyst_run
from .deps import Deps
from .events import reset_current_agent_id, set_current_agent_id
from .landscape import landscape_run
from .memory import new_note_id
from .schemas import QuestionSynthesis, ResearcherReport
from .tools.notes import answer_question, get_research_state, load_note

logger = logging.getLogger(__name__)

# Hard cap on analyst dispatches per research run. Prompt says less;
# this is the backstop so a misbehaving researcher can't runaway-spawn.
DEFAULT_ANALYST_BUDGET = 8


RESEARCHER_SYSTEM = """\
You are the director of a research investigation.

## Your job
Given a user's research query, produce a thorough, evidence-grounded
final report. You dispatch analyst sub-agents (one per sub-question)
who do the actual reading. You only ever see their distilled
syntheses - never raw source content. You decide, iteratively, what
to investigate next based on what you've learned so far.

## Context you already have
Before your first turn, you've already received:
  - The user's query (as the root question).
  - A landscape brief from a scouting agent.
  - A list of SCOUTED sources the scouting agent pulled in.
All of that is in your opening message. You do NOT need to run
searches - that's the landscape agent's job, and the analysts will
do targeted search for their own questions as needed.

## Tools
- `investigate_question(question)`: create a sub-question note and
  dispatch an analyst on it. Returns a QuestionSynthesis (the
  analyst's answer). Can be called multiple times per turn in
  parallel. Counts against your dispatch budget.
- `get_research_state()`: compact snapshot of all questions (with
  their status/confidence) + source corpus shape + your remaining
  dispatch budget. Call between rounds to decide next moves.
- `load_note(note_id)`: load a specific note - usually a QUESTION
  note to re-read its synthesis. Do NOT load SOURCE notes; they're
  too noisy for you.
- `answer_question(question_id=<root_id>, ...)`: commit the final
  report. This is your terminal tool - call it last.

## How to work
1. **Round 1 — initial decomposition.** Based on the query and the
   landscape brief, dispatch 2-5 `investigate_question` calls in
   parallel. Each should be a focused, independently-answerable
   sub-question.
2. **Review round.** After analysts return, call
   `get_research_state()` to see the shape. Use `load_note` on
   specific sub-question notes when you need their full report.
3. **Decide next move.** Options (choose based on what's weak):
     - Dispatch more `investigate_question` calls to fill gaps,
       follow up on low-confidence answers, or probe open_issues.
     - If coverage is good and confidence is reasonable, move to
       committing the final report.
   You may do multiple review/dispatch rounds. Stop when further
   work wouldn't meaningfully change the report - or when your
   dispatch budget runs out.
4. **Commit.** Call
   `answer_question(question_id=<root_id from get_research_state>,
                    report=..., confidence=...,
                    sources_cited=[...], disagreements=[...],
                    open_issues=[...])`.
   - report: the full markdown report. Self-contained - open with a
     brief takeaway (1-3 sentences) then the full write-up with
     headings, reasoning, and citations. Cite source notes inline
     as [source-abc123]. Weave sub-question findings into the body;
     do not just concatenate them.
   - confidence: high/medium/low across the investigation as a whole.
   - sources_cited: NoteIDs of source notes the report leans on.
   - disagreements/open_issues: honest about friction.
5. **End.** After `answer_question` returns, produce a one-line ack
   ("Report committed") and stop.

## Judgment calls
- If the query is simple, one good sub-question is fine - don't force 4.
- A low-confidence analyst result isn't a failure: deciding whether
  to chase it vs. report the uncertainty IS your job.
- Never call investigate_question just because budget is left over.
  Stop when the report won't improve.

## Quality bar
- Every factual claim in the report should trace to a source note.
- Cite liberally. [source-...] references are the report's spine.
- If sources disagree, say so. Don't paper over it.
"""


def _render_source_list(deps: Deps, max_rows: int = 80) -> str:
    """Short-form source list for the researcher's opening prompt.

    Each row: `- [source-id] title — url — topics — snippet`.
    The researcher never sees full source content; this is the
    maximal source detail it ever gets.
    """
    lines: list[str] = []
    rows = 0
    for n in deps.memory.list_by_type(NoteType.SOURCE):
        if rows >= max_rows:
            remaining = len(deps.memory.list_by_type(NoteType.SOURCE)) - rows
            lines.append(f"- _({remaining} more omitted)_")
            break
        meta = n.metadata
        if not isinstance(meta, SourceNoteMetadata):
            continue
        topics = f" — topics: {', '.join(meta.topics)}" if meta.topics else ""
        snippet = (meta.summary or "").replace("\n", " ")[:160]
        lines.append(f"- [{n.id}] {meta.title[:100]} — {meta.url}{topics} — {snippet}")
        rows += 1
    return "\n".join(lines) if lines else "_(no sources scouted)_"


def build_researcher(deps: Deps) -> Agent[Deps, str]:
    model_id = deps.routing.model_id_for(RoleClass.GENERATIVE, TaskTier.HIGH)
    agent = Agent(
        make_model(model_id, deps.local),
        deps_type=Deps,
        output_type=str,
        system_prompt=RESEARCHER_SYSTEM,
        # Safety net. Tools are well-documented so the model should land
        # correct args on the first try; retries just cover the tail
        # (transient flakes, surprise edge cases) without letting one
        # stumble kill a long run.
        tool_retries=5,
    )
    agent.tool(get_research_state)
    agent.tool(load_note)
    agent.tool(answer_question)

    @agent.tool
    async def investigate_question(
        ctx: RunContext[Deps],
        question: str,
    ) -> QuestionSynthesis:
        """Create a sub-question note and dispatch an analyst.

        Parent-links the new question to the root. Decrements the
        analyst dispatch budget; refuses if budget is exhausted.
        """
        budget = ctx.deps.outputs.get("__analyst_budget__")
        if isinstance(budget, int) and budget <= 0:
            raise ModelRetry(
                "analyst dispatch budget exhausted - stop dispatching and commit "
                "the final report with answer_question(question_id=root_id, ...)."
            )
        if isinstance(budget, int):
            ctx.deps.outputs["__analyst_budget__"] = budget - 1

        root_id = ctx.deps.outputs.get("__root_question_id__")
        parent_id = NoteID(root_id) if isinstance(root_id, str) else None
        q_id = new_note_id("question")
        note = Note(
            id=q_id,
            type=NoteType.QUESTION,
            title=question[:120],
            description=question,
            content="",
            metadata=QuestionMetadata(
                classification=QuestionClassification.SYNTHESIS,
                status="IN_PROGRESS",
                parent_question_id=parent_id,
            ),
            last_modified_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        await ctx.deps.memory.create(note)
        return await analyst_run(ctx.deps, q_id, question)

    return agent


async def research_run(deps: Deps, query: str) -> ResearcherReport:
    """Execute a full research run.

    Returns a ResearcherReport built from the root QUESTION note's
    committed synthesis. If the researcher ends without committing,
    returns a minimal report from what's in memory so the run still
    produces something.
    """
    # --- 1. Create the root question note.
    root_id = new_note_id("question")
    root = Note(
        id=root_id,
        type=NoteType.QUESTION,
        title=query[:120],
        description=query,
        content="",
        metadata=QuestionMetadata(
            classification=QuestionClassification.SYNTHESIS,
            status="IN_PROGRESS",
            parent_question_id=None,
        ),
        last_modified_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    await deps.memory.create(root)
    deps.outputs["__root_question_id__"] = root_id
    deps.outputs["__analyst_budget__"] = DEFAULT_ANALYST_BUDGET

    # --- 2. Run the landscape agent (blocking).
    brief_markdown = await landscape_run(deps, query)

    # --- 3. Build the researcher's opening prompt (query + brief + source list).
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

    source_list = _render_source_list(deps)
    opening = (
        f"User query (root_question_id={root_id}):\n{query}\n\n"
        f"## Landscape brief\n{brief_markdown}\n\n"
        f"## Scouted sources (id — title — url — topics — snippet)\n{source_list}\n\n"
        f"Your analyst dispatch budget: {DEFAULT_ANALYST_BUDGET}.\n"
        f"Begin. When you commit the final report, pass question_id={root_id} "
        "to answer_question."
    )

    token = set_current_agent_id(agent_id)
    try:
        try:
            await agent.run(opening, deps=deps)
        except Exception as exc:
            deps.events.on_agent_done(
                agent_id=agent_id,
                agent_type="RESEARCHER",
                status="ABANDONED",
                verdict=f"failed: {type(exc).__name__}: {exc}"[:200],
            )
            raise

        report = _build_report_from_root(deps, root_id, query)
        verdict = f"{len(deps.memory)} notes"
        deps.events.on_agent_done(
            agent_id=agent_id,
            agent_type="RESEARCHER",
            status="DONE",
            verdict=verdict,
        )
        logger.info("researcher done agent_id=%s", agent_id)
        return report
    finally:
        reset_current_agent_id(token)
        deps.outputs.pop("__root_question_id__", None)
        deps.outputs.pop("__analyst_budget__", None)


def _build_report_from_root(deps: Deps, root_id: NoteID, query: str) -> ResearcherReport:
    """Assemble the final ResearcherReport from the root QUESTION note.

    If the root note was answered, use its report_markdown. Otherwise
    build a minimal fallback from whatever sub-question answers exist.
    """
    root = deps.memory.get(root_id)
    sub_syntheses: list[QuestionSynthesis] = []
    for n in deps.memory.list_by_type(NoteType.QUESTION):
        if n.id == root_id:
            continue
        meta = n.metadata
        if not isinstance(meta, QuestionMetadata) or meta.status != "SYNTHESIZED":
            continue
        sub_syntheses.append(
            QuestionSynthesis(
                question=n.description or n.title,
                report=meta.report_markdown or "",
                confidence=meta.confidence or "low",
                sources_cited=list(meta.sources_cited),
                disagreements=list(meta.disagreements),
                open_issues=list(meta.open_issues),
            )
        )

    if (
        root is not None
        and isinstance(root.metadata, QuestionMetadata)
        and root.metadata.status == "SYNTHESIZED"
    ):
        meta = root.metadata
        return ResearcherReport(
            query=query,
            report_markdown=meta.report_markdown or "",
            questions_investigated=sub_syntheses,
            limitations=list(meta.open_issues),
        )

    logger.warning("researcher ended without answering root question %s", root_id)
    return ResearcherReport(
        query=query,
        report_markdown=(
            "_(no top-level report committed - researcher ended without "
            "calling answer_question on the root question)_"
        ),
        questions_investigated=sub_syntheses,
        limitations=["Top-level researcher did not commit a final report."],
    )
