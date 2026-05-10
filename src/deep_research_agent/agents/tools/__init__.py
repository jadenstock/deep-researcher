"""Tool implementations for the agent layer.

Each submodule exposes async functions shaped to be registered on a
pydantic-ai `Agent` via `@agent.tool` (which injects `RunContext[Deps]`
as the first argument). Tools are small: they bridge between the agent
and existing infrastructure (retrieval clients, note memory). No
business logic lives here - that belongs in the agents' system
prompts or in the note schemas.
"""

from __future__ import annotations
