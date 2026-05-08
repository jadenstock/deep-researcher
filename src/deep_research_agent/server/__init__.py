"""Live UI for the deep research agent.

Runs the same Scheduler + AgentExecutor used by the CLI; adds a FastAPI
app with a WebSocket that streams task + note-mutation events to a
browser. The frontend renders the note graph in real time so you can
watch the agent's shared memory assemble.
"""

from .app import create_app

__all__ = ["create_app"]
