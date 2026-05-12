"""Tool implementations for the agent layer.

Each submodule exposes async functions shaped to be registered on a
pydantic-ai `Agent` via `@agent.tool` (which injects `RunContext[Deps]`
as the first argument). Tools are small: they bridge between the agent
and existing infrastructure (retrieval clients, note memory). No
business logic lives here - that belongs in the agents' system
prompts or in the note schemas.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BeforeValidator


def _parse_json_list_if_string(v: Any) -> Any:
    """Unpack a JSON-encoded string into a list before model validation.

    Some smaller models (Haiku family in particular) double-encode list
    args to tool calls: they emit the JSON array as a single string
    instead of a native array. Pydantic then rejects it with "Input
    should be a valid array", the model retries with the same mistake,
    and the tool burns its retry budget.

    Using this as a `BeforeValidator` on `list[...]` tool args lets us
    recover silently from that failure mode without involving the model.
    Non-string inputs pass through untouched. Malformed JSON also passes
    through so the normal validator produces the real error.
    """
    if isinstance(v, str):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return v
    return v


# Drop-in annotation for `list[...]` tool args that are prone to being
# stringified by weaker models. Use as:
#   items: Annotated[list[Foo], JsonListOK]
JsonListOK = BeforeValidator(_parse_json_list_if_string)
