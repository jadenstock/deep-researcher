"""Bounded replanner.

Runs periodically (default: every 10 task completions). Emits task-graph
mutations under a per-cycle budget (default: 3). Uses Round 3/4/5
framing: falsification check, premortem, metacognitive saturation check.
Also runs the typed-dependency detection block (was a deferred dep
missed at decomposition?) and the bias countermeasure scan.

Termination is NOT a replanner prerogative — it requires the separate
deterministic CHECK_TERMINATION_READY audit.
"""
