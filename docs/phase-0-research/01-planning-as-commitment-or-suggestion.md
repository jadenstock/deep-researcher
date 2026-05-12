# Q1: When should a plan be a commitment vs. a suggestion?

## What the research says

The corpus treats planning as a spectrum, not a binary. The "A Survey on LLM-based Autonomous Agents" taxonomy distinguishes **prompt-native planners** (CoT, ToT, ReAct — plan emerges during execution) from **learned planners** (trained to output structured plans). Neither is strictly a "commitment" — both are revisable under sufficient contradiction.

The strongest evidence for **plan-as-commitment** comes from the orchestrator-worker pattern (GPT Researcher's Chief Editor, Microsoft's hierarchical pattern). Here the plan is a contract: the orchestrator decomposes, workers execute, and the plan defines the success criteria. **Failure mode:** rigid adherence to a wrong plan. Microsoft explicitly warns that hierarchical orchestration produces cascading failures when early plan stages are incorrect.

The strongest evidence for **plan-as-suggestion** comes from LiteResearcher and SFR-DeepResearch, which argue a single agent with tools should plan dynamically based on what it observes — any fixed plan over-constrains the model and hurts generalization. Marco DeepResearch takes a middle path: it plans, executes, then re-plans at verification failure (re-rollout).

LangGraph's time-travel / forking documentation directly supports a **"plan as revisable commitment"** model: checkpoints let you fork from a prior state when a path doesn't pan out, without discarding the original plan's structure.

## Design implication for an API-based system

**Treat the plan as a commitment for structure and a suggestion for execution.** Concretely:

- **Commit to the research question decomposition** (the sub-questions to answer, the success criteria per sub-question, the stop conditions). This is what the user is implicitly approving when they submit a query. It's what the final report is organized around.
- **Don't commit to the specific search queries, tool choices, or exploration order.** Let the execution layer decide these based on what comes back. A plan that says "run these 10 queries" is almost always worse than "answer these 3 sub-questions using whatever retrieval pattern each one calls for."
- **Re-plan on a schedule, not only on failure.** Marco DeepResearch's "verify → re-rollout" only triggers on detected failure. A better pattern: after N tool calls or on meaningful evidence accumulation, re-evaluate whether the sub-question decomposition is still right. Evidence might change what's worth asking.
- **Expose the plan to the user as a contract.** Showing "here's what I'm planning to investigate, here's how I'll know I'm done" before burning tokens does two things: it catches bad decompositions cheaply, and it gives the user legitimate authority to redirect.

## Residual uncertainty

No source quantifies *how often* to re-plan. Too frequent and the agent thrashes; too rare and it commits to dead ends. This is a tunable parameter that depends on topic breadth and context budget — empirical calibration required.

## Anchor sources

- Microsoft Azure — AI Agent Orchestration Patterns (hierarchical, cascading failures)
- LiteResearcher (single-agent dynamic planning argument)
- SFR-DeepResearch (generalization argument against rigid plans)
- Marco DeepResearch (re-rollout on verification failure)
- LangChain docs — Persistence + Time-Travel (checkpoint forking)
