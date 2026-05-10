"""Agent-first research pipeline.

The whole system is a nested set of tool-using agents. The top-level
`researcher` agent takes a query and produces a `ResearcherReport`; it
invokes the `investigate_question` sub-agent (as a tool) in parallel for
each decomposed question; investigators invoke search / fetch / note
tools. Parallelism comes from (a) multi-tool-call turns and (b) sub-
agents-as-tools dispatched concurrently by pydantic-ai.

Call site: `from deep_research_agent.agents.researcher import researcher`.
"""

from __future__ import annotations
