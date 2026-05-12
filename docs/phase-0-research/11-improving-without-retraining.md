# Q11: What would it take for the system to get better over time without retraining?

## What the research says

The corpus documents training extensively but is **thin on non-training improvement mechanisms**. A few threads are relevant:

### Documented non-training improvement mechanisms

1. **Prompt versioning and systematic evaluation** (implicit across engineering sources — Azure, AWS, Anthropic): treat prompts as artifacts, version them, evaluate changes against held-out test sets. Standard software engineering discipline applied to prompts. The corpus doesn't describe this explicitly for research agents but doesn't contradict it.

2. **Tool-use pattern libraries** (MCP spec + MCP servers repo + LangGraph docs): tools are versioned, named, and reusable. When a new tool (or new version of an existing tool) improves some class of sub-question, the system can adopt it without retraining.

3. **Structured outputs + offline evaluation feedback loops** (Pydantic-adjacent, AWS):
   - Every run produces structured traces (see debugging doc).
   - Offline eval can run against those traces — "what would the system do differently with a new prompt or a new verifier?" — replay is cheap because tool calls were cached.
   - Cached trace replay means prompt changes can be A/B tested on historical runs without paying the original cost.

4. **Example/few-shot retrieval from past runs** (Look Back to Reason Forward's callback mechanism is adjacent): past well-verified answers can be retrieved into new runs' prompts as few-shot examples. The corpus doesn't do this explicitly but the retrieval primitive is there.

5. **Process reward models + PRM-guided selection at inference** (PRM Survey + Let's Verify Step by Step): even without training the main model, a PRM can be used at inference to re-rank candidate traces. The PRM itself is trained once; the main model is not.

### What the corpus does NOT document

- **Continual learning from user feedback** without retraining — no architectural pattern documented.
- **Automatic prompt optimization** (e.g., DSPy-style) — not in this corpus.
- **Long-term memory as learned preference** — systems remember user preferences (PDR-Bench framing), but the corpus doesn't describe how the agent system itself learns from its accumulated memory.
- **Learned routing / classification improvements** without training the generator.

## Design implication for an API-based system

**Improvement vectors without retraining, ranked by impact for a production deep research agent:**

### Tier 1: structural

1. **Versioned prompts + offline eval harness.** Every prompt in the system (decomposer, researcher, verifier, synthesizer) is versioned. Every run writes structured traces. A held-out test set (the four assessment-style test cases plus real user queries) is re-run on every prompt change. Regression is caught before deployment. This is engineering hygiene, not research — but it's the biggest lever.

2. **Trace replay on cached tool calls.** Because tool outputs are logged, prompt changes can be A/B tested against historical runs without re-paying for tool calls. This makes iteration dramatically cheaper.

### Tier 2: mechanistic

3. **Example retrieval from past successful runs.** Maintain a store of (query, final-report, quality-scores) triples. At intake, retrieve the K most similar past queries and include them as few-shot exemplars. The system "gets better" because the exemplar pool gets richer over time. Trades latency for quality.

4. **Failure-case library.** When a run is flagged as low-quality (by faithfulness score or user feedback), the failure mode is categorized and added to a library of anti-patterns used in prompt construction. "Don't do X because it caused Y in run Z" as retrieval-augmented prompting.

5. **Learned routing based on historical performance.** The difficulty classifier (see Work Difficulty doc) starts with hand-written rules. Over time, per-class success rates are tracked. When a specific query pattern consistently fails at the `lookup` class but succeeds at `synthesis`, the classifier is updated. No model training — just statistics on historical run traces.

### Tier 3: evaluator-side

6. **LLM-judge calibration set grows over time.** Every time a human reviews a report and marks claims as supported/contradicted/unclear, that becomes a calibration example for the faithfulness-judge. The judge itself doesn't retrain; its prompt gets better-calibrated exemplars.

7. **Source-tier rules update.** As new domains or source types are encountered, the source-tier rules (peer-reviewed > preprint > etc.) are extended. Deterministic; no training; directly affects conflict resolution.

### What not to do

**Don't try to "learn from user feedback" by modifying prompts automatically.** Automatic prompt editing without offline evaluation will introduce regressions faster than it fixes things. All prompt changes go through the evaluation harness. Human-in-the-loop review of proposed changes is cheap relative to a regression in production.

## Key failure mode the design guards against

**Example-retrieval poisoning.** If the past-runs retrieval pool includes low-quality or outright wrong past runs, the system gets worse over time, not better. Mitigation: only reports that pass a quality bar (faithfulness threshold + human spot-check approval) enter the retrieval pool. Low-quality runs are retained for offline debugging but not for prompt-time retrieval.

## Residual uncertainty

- How much example retrieval actually helps for open-ended research (vs. narrow-domain tasks where few-shot is proven). Untested for research agents in this corpus.
- Whether to include the evaluator's feedback in the research agent's context (self-awareness loop) or keep them separate. Tempting; no corpus evidence either way.
- The storage and query cost of a retrieval-over-past-runs system. Non-trivial at scale.

## Anchor sources

- LangChain Persistence (trace storage primitive)
- MCP spec + servers repo (tool versioning)
- PRM Survey + Let's Verify Step by Step (inference-time quality improvement via reward model)
- Look Back to Reason Forward (callback-query retrieval, as an adjacent mechanism)
- AWS — Evaluating AI Agents (production improvement discipline)
- PDR-Bench (user-preference evaluation as a signal source)
