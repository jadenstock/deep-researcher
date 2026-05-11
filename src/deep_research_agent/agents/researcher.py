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

Budget: a per-run cap on analyst dispatches. `build_researcher` owns
a closure-scoped counter that starts at the cap and decrements on
each dispatch; when 0 the investigate_question tool refuses.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Literal, cast

from pydantic_ai import Agent, ModelRetry, RunContext

from ..agent_factory import make_model
from ..schemas.enums import (
    AgentRunStatus,
    AgentType,
    NoteType,
    QuestionClassification,
    QuestionStatus,
    RoleClass,
    TaskTier,
)
from ..schemas.ids import NoteID
from ..schemas.note import Note, QuestionMetadata, SourceNoteMetadata
from ._run import drive_agent
from .analyst import AnalystMode, analyst_run
from .deps import Deps
from .events import instrumented
from .landscape import landscape_run
from .memory import new_note_id
from .schemas import QuestionSynthesis, ResearcherReport, question_synthesis_from_note
from .tools.notes import answer_question, load_note

logger = logging.getLogger(__name__)

# Hard cap on analyst dispatches per research run. Prompt says less;
# this is the backstop so a misbehaving researcher can't runaway-spawn.
# Default lives in `run_config.py`; read from `deps.run_config` at
# build time so UI-supplied overrides flow through.


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
- `investigate_question(question, mode)`: create a sub-question note
  and dispatch an analyst on it. Returns a QuestionSynthesis (the
  analyst's answer). Can be called multiple times per turn in
  parallel. Counts against your dispatch budget. `mode` is one of:
    * `explore` — default. Fresh investigation on a new sub-question.
      Runs on the primary (generative) model family.
    * `verify` — independent re-check of a specific prior claim.
      Runs on a different (judgment) model family with instructions
      to find counter-evidence. Use AFTER an `explore` has landed a
      load-bearing claim you want confirmed by a different set of
      priors.
    * `adversarial` — steelman the OPPOSITE of a prior adopted
      position. Also judgment family. Use AFTER an `explore` on a
      `contested` sub-question, to stress-test the finding.
  When using `verify` or `adversarial`, write the `question` string
  so it explicitly references the prior question note (e.g.
  "Verify the claim from [question-abc1234] that X causes Y") — the
  analyst will load that note first.
- `get_research_state()`: compact snapshot of all questions (with
  their status/confidence) + source corpus shape + your remaining
  dispatch budget. Call between rounds to decide next moves.
- `load_note(note_id)`: load a specific note - usually a QUESTION
  note to re-read its synthesis. Do NOT load SOURCE notes; they're
  too noisy for you.
- `answer_question(question_id=<root_id>, ...)`: commit the final
  report. This is your terminal tool - call it last.

## Classify before dispatching (grounded in the landscape brief)
Before your first batch, label each sub-question you plan to dispatch
as one of:
  - `lookup` — single retrieval suffices; landscape points to a clear
    authoritative source.
  - `synthesis` — multiple sources agree; no real controversy visible
    in the landscape.
  - `contested` — landscape surfaced ≥ 2 distinct positions with
    non-trivial support. Disagreement is a feature of the topic.
  - `sparse` — landscape evidence is thin; the topic is emerging or
    under-covered.
Include the label in the dispatched `question` string (e.g.
"[contested] Is X the primary cause of Y?") so the analyst sees it
and so later review calls can tell what kind of work was done.

## Mode-selection heuristics (the point of having 3 modes)
- `lookup`, `synthesis` → one `explore` dispatch each is usually
  enough. `verify` only if a specific claim is load-bearing for the
  final report.
- `contested` → dispatch `explore` first. After the synthesis lands,
  dispatch at least one `adversarial` against the adopted position
  before committing the report. The adversarial counter-case belongs
  in the report body, not a footnote.
- `sparse` → dispatch `explore` with the expectation of low
  confidence; `verify` any load-bearing claim that survives.
- For any claim you're about to cite as central to the final report
  and that rests on a single source or a single model's reading,
  dispatch `verify` before committing.

## How to work
1. **Round 1 — initial decomposition.** Read the landscape brief.
   Classify. Dispatch 2-5 `explore` calls in parallel. Each should be
   a focused, independently-answerable sub-question with its label
   in the question text.
2. **Review round.** After analysts return, call
   `get_research_state()` to see the shape. Use `load_note` on
   specific sub-question notes when you need their full report.

   Before formulating the next move, run this 5-check pass:
     a. **Sufficiency** — did each analyst actually answer its
        sub-question, or did it dodge / return thin?
     b. **Source grounding** — are claims citing specific sources,
        or waving at "the literature"? Watch for single-source
        claims the analyst flagged.
     c. **Thin-spot scan** — what's under-covered across the set?
        Any sub-question that's open but no one investigated it?
     d. **Contradiction** — do any two analysts disagree on a
        fact? Contradictions are not errors to reconcile silently;
        they're either `verify` candidates or `disagreements` for
        the final report.
     e. **Direction** — given what came back, is the next obvious
        move still the right one, or did something surprising
        appear that should redirect the investigation?
   If any check surfaces an issue, the next dispatch addresses it
   - not the next item on your original plan.
3. **Decide next move.** Options:
     - Dispatch more `explore` calls to fill gaps or follow up on
       low-confidence answers.
     - Dispatch `adversarial` on contested sub-questions whose
       `explore` has landed.
     - Dispatch `verify` on specific claims you plan to rely on.
     - If coverage is good and the pre-commit audit (below) passes,
       move to committing the final report.
   You may do multiple review/dispatch rounds. Stop when further
   work wouldn't meaningfully change the report - or when your
   dispatch budget runs out.
4. **Pre-commit self-audit.** Before calling `answer_question` on
   the root, re-read `get_research_state` and ask yourself:
     - For each sub-question I labeled `contested`: has at least one
       `adversarial` dispatch completed against it?
     - For each claim central to my forming report: does it rest on
       more than one source OR has a `verify` dispatch confirmed it?
     - For each `sparse` sub-question whose claim I'm citing: have I
       acknowledged the evidence thinness in the report?
   If any answer is "no" AND your budget has room, dispatch the
   missing work now. If budget is exhausted, be explicit about the
   gap in `open_issues`.
5. **Commit.** Call
   `answer_question(question_id=<root_id from get_research_state>,
                    report=..., confidence=...,
                    sources_cited=[...], disagreements=[...],
                    open_issues=[...])`.
   - report: the full markdown report. Self-contained - open with a
     brief takeaway (1-3 sentences) then the full write-up with
     headings, reasoning, and citations. Cite source notes inline
     as [source-abc123]. Weave sub-question findings into the body;
     do not just concatenate them. When an `adversarial` or `verify`
     surfaced real dissent, the report body must show it.
   - confidence: high/medium/low across the investigation as a whole.
   - sources_cited: NoteIDs of source notes the report leans on.
   - disagreements: anything where `verify` said REFUTES/INCONCL or
     where `adversarial` landed a credible counter-case.
   - open_issues: honest about what's unresolved or under-tested.
6. **End.** After `answer_question` returns, produce a one-line ack
   ("Report committed") and stop.

## Judgment calls
- If the query is simple (pure `lookup`), one good sub-question is
  fine — don't force 4, and don't dispatch `verify`/`adversarial`
  just because they exist.
- A low-confidence analyst result isn't a failure: deciding whether
  to chase it (another `explore`, or a `verify`) vs. report the
  uncertainty IS your job.
- Never call investigate_question just because budget is left over.
  Stop when the report won't improve.
- `verify` and `adversarial` are expensive (they burn the same budget
  as `explore`). Use them where they change the report, not
  everywhere.

## Quality bar
- Every factual claim in the report should trace to a source note.
- Cite liberally. [source-...] references are the report's spine.
- If sources disagree, say so. Don't paper over it.
- If an `adversarial` dispatch produced a credible counter-case, the
  final report must engage with it — at minimum in `disagreements`,
  ideally in the body.
- Preserve the limitations / failure-modes and competing-approaches
  content that analysts surfaced — do not collapse it into a single
  "caveats" footnote. These belong in the report body, visible to
  the reader, not buried.
- When an analyst flagged a claim as single-source-only and you
  chose not to `verify` it, either don't lean on that claim in the
  report or surface the single-source dependency in the prose.
"""


def _render_source_list(deps: Deps, max_rows: int = 80) -> str:
    """Short-form source list for the researcher's opening prompt.

    Each row: `- [source-id] title — url — topics — snippet`.
    The researcher never sees full source content; this is the
    maximal source detail it ever gets.
    """
    sources = deps.memory.list_by_type(NoteType.SOURCE)
    if not sources:
        return "_(no sources scouted)_"
    lines: list[str] = []
    for n in sources[:max_rows]:
        meta = cast(SourceNoteMetadata, n.metadata)
        topics = f" — topics: {', '.join(meta.topics)}" if meta.topics else ""
        snippet = (meta.summary or "").replace("\n", " ")[:160]
        lines.append(f"- [{n.id}] {meta.title[:100]} — {meta.url}{topics} — {snippet}")
    if len(sources) > max_rows:
        lines.append(f"- _({len(sources) - max_rows} more omitted)_")
    return "\n".join(lines)


def build_researcher(
    deps: Deps,
    root_question_id: NoteID,
    analyst_budget_start: int,
) -> Agent[Deps, str]:
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
    agent.tool(load_note)
    agent.tool(answer_question)

    budget = [analyst_budget_start]  # mutable box for closure mutation

    @agent.tool
    @instrumented
    async def get_research_state(ctx: RunContext[Deps]) -> dict[str, object]:
        """Compact snapshot of the note graph for the orchestrator.

        Returns:
          {
            "root_question": {...} | None,
            "questions": [{id, question, status, confidence,
                           parent_id, n_sources_cited}, ...],
            "sources_by_tier": {"unclassified": N, "1": N, "2": N, ...},
            "sources_by_state": {"SCOUTED": N, "FETCHED": N, "ANALYZED": N},
            "budget": {"analyst_dispatches_remaining": int},
          }

        This is the ONLY way the researcher should inspect the note graph
        between rounds - it keeps the researcher's context free of raw
        source content.
        """
        questions = []
        root_summary: dict[str, object] | None = None
        for n in ctx.deps.memory.list_by_type(NoteType.QUESTION):
            meta = n.metadata
            if not isinstance(meta, QuestionMetadata):
                continue
            entry = {
                "id": n.id,
                "question": n.description or n.title,
                "status": meta.status,
                "confidence": meta.confidence,
                "parent_id": meta.parent_question_id,
                "n_sources_cited": len(meta.sources_cited),
            }
            if n.id == root_question_id:
                root_summary = entry
            else:
                questions.append(entry)

        sources_by_tier: dict[str, int] = {}
        sources_by_state: dict[str, int] = {}
        for n in ctx.deps.memory.list_by_type(NoteType.SOURCE):
            meta = n.metadata
            if not isinstance(meta, SourceNoteMetadata):
                continue
            tier_key = str(meta.tier.value) if meta.tier is not None else "unclassified"
            sources_by_tier[tier_key] = sources_by_tier.get(tier_key, 0) + 1
            sources_by_state[meta.state.value] = sources_by_state.get(meta.state.value, 0) + 1

        return {
            "root_question": root_summary,
            "questions": questions,
            "sources_by_tier": sources_by_tier,
            "sources_by_state": sources_by_state,
            "budget": {
                "analyst_dispatches_remaining": budget[0],
            },
        }

    @agent.tool
    async def investigate_question(
        ctx: RunContext[Deps],
        question: str,
        mode: Literal["explore", "verify", "adversarial"] = "explore",
    ) -> QuestionSynthesis:
        """Create a sub-question note and dispatch an analyst.

        Args:
            question: The sub-question to investigate. For `verify` or
                `adversarial` dispatches, include the referenced prior
                question-note id in the text (e.g., "[question-abc123]")
                so the analyst loads it before working.
            mode: One of "explore" (default; generative family, fresh
                investigation), "verify" (judgment family; Round-3
                independent confirm/refute of a prior claim), or
                "adversarial" (judgment family; Round-3 steelman the
                opposite of a prior adopted position).

        Parent-links the new question to the root. Decrements the
        analyst dispatch budget; refuses if budget is exhausted. All
        three modes draw from the same budget.
        """
        if budget[0] <= 0:
            raise ModelRetry(
                "analyst dispatch budget exhausted - stop dispatching and commit "
                "the final report with answer_question(question_id=root_id, ...)."
            )
        budget[0] -= 1

        q_id = new_note_id("question")
        note = Note(
            id=q_id,
            type=NoteType.QUESTION,
            title=question[:120],
            description=question,
            content="",
            metadata=QuestionMetadata(
                classification=QuestionClassification.SYNTHESIS,
                status=QuestionStatus.IN_PROGRESS,
                parent_question_id=root_question_id,
            ),
            last_modified_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        await ctx.deps.memory.create(note)
        analyst_mode: AnalystMode = mode
        return await analyst_run(ctx.deps, q_id, question, mode=analyst_mode)

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
            status=QuestionStatus.IN_PROGRESS,
            parent_question_id=None,
        ),
        last_modified_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    await deps.memory.create(root)

    # --- 2. Run the landscape agent (blocking).
    if deps.run_config.skip_landscape:
        logger.info("landscape SKIPPED via run_config.skip_landscape")
        brief_markdown = "_(landscape disabled for this run)_"
    else:
        brief_markdown = await landscape_run(deps, query)

    # --- 3. Build the researcher's opening prompt (query + brief + source list).
    analyst_budget = deps.run_config.analyst_budget
    agent = build_researcher(
        deps,
        root_question_id=root_id,
        analyst_budget_start=analyst_budget,
    )
    agent_id = f"res-{uuid.uuid4().hex[:8]}"
    model_id = deps.routing.model_id_for(RoleClass.GENERATIVE, TaskTier.HIGH)
    logger.info("researcher start agent_id=%s query=%r", agent_id, query[:200])

    source_list = _render_source_list(deps)
    opening = (
        f"User query (root_question_id={root_id}):\n{query}\n\n"
        f"## Landscape brief\n{brief_markdown}\n\n"
        f"## Scouted sources (id — title — url — topics — snippet)\n{source_list}\n\n"
        f"Your analyst dispatch budget: {analyst_budget}.\n"
        f"Begin. When you commit the final report, pass question_id={root_id} "
        "to answer_question."
    )

    await drive_agent(
        deps=deps,
        agent=agent,
        agent_id=agent_id,
        agent_type=AgentType.RESEARCHER,
        goal=query,
        tier=TaskTier.HIGH,
        role=RoleClass.GENERATIVE,
        model_id=model_id,
        prompt=opening,
    )

    report = _build_report_from_root(deps, root_id, query)
    deps.events.on_agent_done(
        agent_id=agent_id,
        agent_type=AgentType.RESEARCHER,
        status=AgentRunStatus.DONE,
        verdict=f"{len(deps.memory)} notes",
    )
    logger.info("researcher done agent_id=%s", agent_id)
    return report


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
        qs = question_synthesis_from_note(n)
        if qs is not None:
            sub_syntheses.append(qs)

    if (
        root is not None
        and isinstance(root.metadata, QuestionMetadata)
        and root.metadata.status == QuestionStatus.SYNTHESIZED
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
