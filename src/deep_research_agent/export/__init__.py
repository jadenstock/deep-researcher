"""Note-graph serialization.

Takes the in-memory note graph at end of run and writes it to disk in
a human-browsable form. Output format is a separate concern from core
architecture: the note graph itself is the load-bearing structure;
this layer is one way to view it.
"""

from .markdown import export_run

__all__ = ["export_run"]
