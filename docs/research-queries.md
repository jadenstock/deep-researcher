# Suggested research queries

Five queries that exercise different parts of the agent pipeline and
produce research directly useful to this project. Run any with:

```bash
uv run dra "<query>" -v
```

## 1. Uncertainty elicitation in black-box LLMs

> Tell me about uncertainty elicitation in LLMs with only black-box and no log-prob access. What are the leading techniques, their empirical performance, and open problems?

Why this one: directly useful for any "confidence score" the agent
attaches to its final report. Exercises academic search heavily (most
of this literature is on arXiv / NeurIPS / ICLR).

## 2. Tool-use agent architectures in 2025-2026

> How have tool-use agent architectures evolved between 2024 and late 2026? Compare ReAct, reflexion-style self-critique, planner-executor splits, and modern multi-agent orchestration patterns. Which patterns hold up at scale?

Why this one: informs the next iteration of this very system. Mix of
peer-reviewed work, arXiv preprints, and industry writeups (Anthropic,
OpenAI, LangChain, DeepMind blog posts) - tests whether the researcher
blends web and academic sources sensibly.

## 3. Parallel tool-call dispatch: state of the art

> What are the current best practices for dispatching parallel tool calls from LLM agents? How do frameworks like pydantic-ai, LangGraph, and the OpenAI Responses API handle fan-out and fan-in? What are the failure modes?

Why this one: we're building directly on this. Tests the agent's
ability to compare frameworks and extract concrete patterns, not
just list features.

## 4. Evaluating deep-research agents

> How do people evaluate "deep research" agents that produce long-form reports with citations? What benchmarks exist (e.g. BrowseComp, GAIA, HLE), what do they actually measure, and where do current agents fall short?

Why this one: we have no evaluation story yet. The report this
produces is itself an artifact we could later evaluate. Good test of
whether the agent finds recent benchmark papers and characterizes
what they measure, not just their names.

## 5. Context window management in long-running agents

> How do long-running AI agents manage context window pressure? Compare approaches: progressive summarization, retrieval-augmented working memory, hierarchical note graphs, context engineering techniques. What are the tradeoffs when an agent runs for hundreds of turns?

Why this one: the note graph in this system is exactly a hierarchical
note memory. A good answer tells us whether we should invest in
digest seams (CONTEXT.md §56-57) or whether it's premature. Stresses
the agent's ability to compare approaches rather than enumerate them.

---

## What to watch for when running these

- **Does it decompose sensibly?** The researcher agent should break a
  broad query into 2-5 focused sub-questions and dispatch
  `investigate_question` in parallel. If it produces one mega-question,
  the prompt is under-specified.
- **Does it use both search tools?** Queries 1 and 4 lean academic;
  query 2 is mixed; queries 3 and 5 lean web + docs. A well-calibrated
  agent reaches for `search_academic` vs `search_web` differently per
  question.
- **Does it cite verbatim?** `update_source_after_reading` requires a
  quote per claim. If the agent hallucinates quotes, that shows up in
  `runs/<run-id>/notes.json` - spot-check a few quotes against the
  source URL.
- **How parallel is it actually?** Run with `-v` and watch the log: you
  should see overlapping `investigate_question` / `fetch_url` /
  `search_*` calls, not a serial trace.
- **Cost and latency.** These are tool-using loops; they WILL rack up
  tokens and wall-clock time. Token usage lands in the logs; watch it.
