"""Deterministic scheduler, task graph, and note graph.

No LLM lives here. The scheduler is the state manager: it dispatches tasks
that are ready (respecting staged waiting on typed dependencies), serializes
writes into the note graph, enforces cascade semantics on replanner
mutations (merge / split / abandon / add-edge), triggers the replanner on
cadence, and kicks off CHECK_TERMINATION_READY when the replanner idles.
"""
