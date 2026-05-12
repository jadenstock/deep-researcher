# Q9: How do you debug a multi-agent workflow when something goes wrong three steps ago?

## What the research says

The corpus is thinner here than on architectural questions, but the mechanics are documented well.

### Documented mechanisms

1. **AgentTrace** (arXiv, single-source but directly on-topic): structured logging across three surfaces — **cognitive** (internal reasoning, confidence, self-assessment), **operational** (method execution, latency, errors), **contextual** (environmental I/O, tool inputs/outputs). Explicitly designed because standard execution logs fail to capture the non-determinism of LLM agents. The three surfaces are the insight — single-dimension logging (just stdout, just API calls) is insufficient for post-hoc reasoning.

2. **LangGraph checkpointing** (LangChain docs): checkpoints at super-step boundaries, organized by `thread_id`. Each checkpoint captures full graph state. Makes "go back to step N" mechanically possible.

3. **Time-travel / forking** (LangChain docs): replay from a prior checkpoint, or fork to explore an alternative trajectory. This is the closest thing to "debugging three steps ago" in the corpus. You don't reason about what went wrong from logs alone — you replay with modifications.

4. **Delta channels** (LangChain): instead of full-state checkpoints (storage-prohibitive), store only deltas per super-step. Makes long traces affordable to retain.

### What the corpus does NOT document

- **Root-cause analysis tooling** for multi-agent traces. AgentTrace captures data; nothing in the corpus describes the analyst-facing tool that answers "which agent's output caused this bad final report?"
- **Cross-agent causal provenance.** When claim C in the final report is wrong, which sub-agent produced which evidence, which verifier approved it, and what prompt/temperature did each use? The primitives exist (checkpoints + structured messages) but the trace-to-cause workflow is not documented.
- **Retry/repair semantics.** If step 3 was the bad step, do you fork from step 2, re-run 3-N, and diff against the original? No source prescribes this loop.

## Design implication for an API-based system

**Debugging must be designed in, not bolted on.** Three invariants:

### Invariant 1: Every LLM call is attributable.

Every agent call emits a structured record with: `{agent_id, step_id, parent_step_id, prompt_hash, tool_calls, output, timestamp, model_id, temperature, cost_tokens}`. This is AgentTrace's cognitive + operational surfaces. Without this, "something went wrong three steps ago" isn't even answerable.

### Invariant 2: State is checkpointed at every step boundary.

Use LangGraph-style checkpointing or an equivalent. At each super-step, the full relevant state (research plan, accumulated claims, verifier verdicts, context) is dumped. Deltas, not full states, to keep storage sane. This enables:
- Replaying from step N with the original inputs.
- Forking from step N with modified inputs (e.g., different prompt, different model, re-retrieved evidence).
- Diffing runs to isolate the cause.

### Invariant 3: Claims are causally linked to their generating steps.

In the structured claim output: `claim → {generated_by: step_id, verified_by: step_id, sources: [source_ids]}`. When a claim is wrong, you trace directly back to the step that produced it. The traceback is one structured-field lookup, not a log-dive.

### The actual debugging workflow

1. A bad claim or report section is identified (by evaluation or user complaint).
2. Follow `claim.generated_by` → the exact step and prompt that produced it.
3. Follow `claim.sources[*]` → the exact evidence the generator was working from.
4. Follow `claim.verified_by` → why the verifier didn't catch it.
5. Fork from the step before the bad step; re-run with a tweaked prompt or a different model; diff the new trajectory against the original.

This is not literally "bisect search" but it's close — replaying sub-trees is cheap relative to re-running the entire research task.

### Tooling implication

You probably need a thin viewer: given a run ID, show the agent DAG with per-step cost, per-step output, and links between claims and their generating steps. This is a weekend afternoon of frontend, not a prerequisite for the MVP — but naming it explicitly in the design doc is smart because every reviewer will ask "how do you know your system actually works?" and "we replay from checkpoints and diff" is a concrete answer.

## Key failure mode the design guards against

**Silent log loss.** If a sub-agent emits logs but they're not keyed to the top-level run, the trace is broken. Make `run_id` mandatory; propagate it through every message; fail loudly if missing. This is boring plumbing that pays off the moment something actually goes wrong.

## Residual uncertainty

- LangGraph-specific patterns vs. bespoke implementation. LangGraph is the documented path; rolling your own checkpoint layer is viable but work. For a 2-day MVP, don't reinvent this.
- Cost of retaining full traces. Structured logs + deltas are tractable; storing every full context window per step is not. This calls for compression or sampling — no corpus guidance.

## Anchor sources

- AgentTrace (three-surface structured logging)
- LangChain Persistence + Use Time-Travel (checkpoint semantics, forking)
- AWS — Evaluating AI Agents (observability lessons from production)
- Microsoft Azure — Orchestration Patterns (cascading-failure framing that motivates traceability)
