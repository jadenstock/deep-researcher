"""Post-report chat agent.

After a research run finishes, the user can open a chat session over
the run's note graph. Three modes are planned:
  - `ask`        : read-only Q&A. Tools: list_source_notes, load_note,
                   chat_research_state.
  - `investigate`: ask + investigate_question (spawns analysts).
  - `new_report` : investigate + answer_question on a fresh follow-up
                   QUESTION node.

Phase 1 ships only `ask` mode. Future phases register the additional
tools and broaden the system prompt.

Each turn builds a fresh `Agent` (cheap; pydantic-ai computes tool
schemas at instantiation) so per-turn tool pruning stays simple. The
caller threads pydantic-ai's native `message_history` across turns
via `drive_agent_with_history`.
"""

from __future__ import annotations

from typing import Literal

from pydantic_ai import Agent

from ..agent_factory import make_model
from ..schemas.enums import RoleClass, TaskTier
from ..schemas.ids import NoteID
from .deps import Deps
from .tools.notes import build_research_state_tool, list_source_notes, load_note

ChatMode = Literal["ask", "investigate", "new_report"]


def chat_default_model_id(deps: Deps) -> str:
    """Resolve the default chat model from the run's routing config."""
    return deps.routing.model_id_for(RoleClass.GENERATIVE, TaskTier.MID)


CHAT_BASE_SYSTEM = """\
You are a research assistant chatting with a user about a finished
research run. The run produced a note graph (questions + sources +
readings) and a final report; both are available to you. You answer
the user's questions by drawing on those existing notes — citing
specific source ids inline as `[source-abc123]` when you make a
factual claim.

## What's already in memory
- A root question note (the user's original query) plus the
  sub-questions the researcher decomposed it into.
- Source notes: each holds a URL, summary, tier, peer-review status,
  and one or more analyst readings with verbatim quoted claims.
- The final report markdown lives on the root question note's
  `report_markdown` field.

## Tools available to you
- `get_research_state()`: compact snapshot of the note graph
  (question tree, sources by tier/state, your dispatch budget). Call
  this first on any non-trivial question to see what's there.
- `list_source_notes()`: enumerate sources with their key signals
  (tier, peer_reviewed, summary, has_content, n_readings).
- `load_note(note_id)`: load any note's full contents — the readings
  + extracted claims on a source, or the full synthesis on a
  question. Use this whenever you need the verbatim quotes / full
  reasoning behind a result.

## How to answer
- Ground every factual claim in a specific note. Cite source ids
  inline. If you can't find support in the existing notes, say so
  plainly — do not invent.
- When the user asks a follow-up that prior turns already addressed,
  build on the conversation; do not re-load notes you've already
  read this session unless something changed.
- Keep responses focused and well-structured. Markdown formatting
  (bullets, headers when useful) is fine.
"""

ASK_MODE_SYSTEM = """\
## Mode: Ask (read-only)
You can only READ the existing graph. You CANNOT spawn new analysts,
fetch new web sources, or modify any notes. If the user asks for
something the existing graph cannot support, say so explicitly and
suggest they switch to Investigate mode.
"""


def build_chat_agent(
    deps: Deps,
    *,
    mode: ChatMode,
    root_question_id: NoteID,
    budget_box: list[int],
    model_id_override: str | None = None,
) -> tuple[Agent[Deps, str], str]:
    """Build a chat agent with the tool set appropriate for `mode`.

    `root_question_id` and `budget_box` are wired into the
    research-state snapshot tool so the agent sees the original root
    plus its remaining dispatch budget. For Ask mode, pass a `[0]`
    budget box; the agent has no tool that would consume it.

    `model_id_override` lets the caller (the chat session) pick a
    specific model — passed through unchanged to `make_model`. When
    None, falls back to the routing config's GENERATIVE/MID slot so
    behavior matches the previous default. Returns the built agent
    plus the resolved model_id (so the caller can record token usage
    against the right model).
    """
    if mode != "ask":
        # Phase 2/3 will lift this; today we ship Ask only.
        raise NotImplementedError(f"chat mode {mode!r} not implemented yet")

    model_id = model_id_override or chat_default_model_id(deps)
    system_prompt = CHAT_BASE_SYSTEM + "\n" + ASK_MODE_SYSTEM
    agent = Agent(
        make_model(model_id, deps.local),
        deps_type=Deps,
        output_type=str,
        system_prompt=system_prompt,
        tool_retries=3,
    )
    agent.tool(list_source_notes)
    agent.tool(load_note)
    agent.tool(build_research_state_tool(root_question_id, budget_box))
    return agent, model_id
