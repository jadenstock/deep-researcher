# Research report

**Query:** How have tool-use agent architectures evolved between 2024 and 2026? Compare ReAct, reflexion-style self-critique, planner-executor splits, and modern multi-agent orchestration patterns. Which patterns hold up at scale?

## Partial report (reconstructed from answered questions)

_The top-level researcher did not produce a final structured report. The sub-question answers below were recovered from the note graph._

### The ReAct pattern has evolved from a standalone loop into a specialized executor within hierarchical multi-agent systems, driven by documented failure modes including context window overflow, trajectory deviation, hallucinated tool calls consuming retry budgets, and sequential th

**Bottom line:** The ReAct pattern has evolved from a standalone loop into a specialized executor within hierarchical multi-agent systems, driven by documented failure modes including context window overflow, trajectory deviation, hallucinated tool calls consuming retry budgets, and sequential throughput bottlenecks. Practical mitigations include error taxonomy classification, per-tool circuit breakers, deterministic tool routing, role-separation (planner/executor splits), and context offloading strategies—all backed by benchmark evidence.

# The ReAct Pattern: Evolution, Failure Modes, and Mitigations (2024–2026)

## 1. Foundational Context and Evolution (2022–2024)

The ReAct (Reasoning and Acting) pattern was introduced by Yao et al. at ICLR 2023, formalizing the Thought→Action→Observation loop that interleaves chain-of-thought reasoning with external tool use. The architecture was immediately foundational: every major LLM agent framework (LangChain, AutoGen, LangGraph, Reflexion) built upon it directly.

Through 2024, ReAct remained the dominant single-agent pattern but its limitations in production became visible. The original pattern interleaves reasoning with environment interaction, "improving groundedness but remaining vulnerable to myopia and error propagation (e.g., early mistakes leading to unproductive loops)" [source-896e228f0105]. In production, each reasoning-action-observation cycle requires at least one LLM call, yielding 5–7 LLM calls per interaction—compared to 3–4 for plan-then-execute approaches [source-07978d2e96f4]. The Reflexion extension added verbal self-critique but at a cost of 2–3× more tokens versus single-pass approaches [source-07978d2e96f4].

## 2. The Four Documented Failure Modes at Scale

### 2a. Retry Budget Exhaustion via Hallucinated Tool Names

The most precisely benchmarked failure mode comes from a 200-task simulation study: **"In a 200-task benchmark, 90.8% of retries were wasted — not because the model was wrong, but because the system kept retrying tools that didn't exist. Not 'unlikely to succeed.' Guaranteed to fail."** [source-97b7d4aebe6c]

The root cause is architectural: when tool name resolution happens at LLM runtime (e.g., `TOOLS.get(tool_name)`), a hallucinated name like `"web_browser"` returns `None` on every attempt. A global retry counter treats `TOOL_NOT_FOUND` identically to a transient network error, burning 3 retry slots per hallucination event. The cascade effect: "every hallucination consumes retry slots that could have handled a real failure. When a genuine network timeout arrives two steps later, there is nothing left." [source-97b7d4aebe6c]

Even more alarming: the failure remains invisible until catastrophic. At a 5% hallucination rate (low severity), ReAct shows 100% task success, yet 54.7% of retries are still silently wasted. "Your monitoring reports a healthy agent. But 54.7% of retries are still wasted. The budget is quietly draining." [source-97b7d4aebe6c]

The benchmark also shows high step-count variance (σ = 1.36 for ReAct vs. 0.46 for a controlled workflow), creating unpredictable latency and token costs—"unpredictable latency (SLAs cannot be committed to), unpredictable token cost (budget forecasts are inaccurate), and invisible burst load." [source-97b7d4aebe6c]

Fault type analysis from ReliabilityBench (1,280 episodes across four domains) confirms **rate limiting as the single highest-impact fault type**: "Rate limiting causes largest degradation: 2.5% below mixed baseline, suggesting agents struggle with backoff and retry logic for rate-limited APIs." [source-741a83ef08bb]

### 2b. Context Window Exhaustion and Trajectory Deviation

The second major failure class is context overflow leading to trajectory deviation on hard multi-step tasks. Research from RP-ReAct confirms that simply increasing ReAct's step limit does not fix the problem: "the results showed that performance increased by an average of only 4.8%... the React agent either followed a wrong trajectory, produced an incorrect answer, or reached the new 100-step limit again." [source-308a90d24e20]

The mechanism is distinct from mere token limits: "The monolithic ReAct approach, in contrast, tends to fail because its context window becomes overwhelmed by large tool outputs or frequent wrong tool calls, leading the agent to deviate from the correct path." [source-308a90d24e20] The paper identifies two interacting drivers: *Context Consumption* (limited context window overwhelmed by large tool outputs) and *Trajectory Deviation* (error-handling and tool invocations corrupt the reasoning trace).

CodeDelegator (Tencent, 2026) names this **context pollution**: "the progressive dilution of task-relevant information that degrades both planning and implementation capabilities." [source-b793ce7ff712] Empirically, context length negatively correlates with success even on high-difficulty tasks—CodeAct (the code-action variant of ReAct) consistently underperforms simpler ReAct on low and medium difficulty tasks specifically because code execution traces accumulate in shared context [source-b793ce7ff712].

SWE-Bench Pro, the large-scale software engineering benchmark, independently confirms this: the benchmark "exposes bottlenecks such as context exhaustion and search-space explosion" as agents work on repository-scale tasks requiring hours of simulated work [source-896e228f0105].

### 2c. Throughput Bottlenecks from Sequential Architecture

ReAct's sequential Thought→Action→Observation structure is a fundamental throughput constraint. The pattern "requires multiple LLM calls per task because each reasoning-action-observation cycle involves at least one model invocation. ReAct tends to struggle when goals span multiple domains and requests get complicated." [source-07978d2e96f4] Tool schemas alone can reach tens of thousands of tokens, compounding per-call costs [source-07978d2e96f4].

As multi-agent scaling is attempted, coordination overhead compounds the issue. A 4-agent pipeline adds ~950ms coordination overhead vs ~500ms processing and requires 29K tokens vs 10K for single-agent approaches [source-5e174290b618]. Multi-agent systems exhibit 3–5× token amplification and 4.3× higher tokens per query versus single-agent [source-f3d1588a2e4a]. The enterprise consequence: only 10% of enterprises successfully scale multi-agent systems [source-a348020a4683].

The larger survey evidence confirms: "scalability limits of LLMs, where context length and reasoning bottlenecks constrain performance" are primary drivers of architectural transition away from simple ReAct loops [source-636a71e35a60].

### 2d. Self-Correction Paradox in Reflection Loops

Reflexion's extension of ReAct (adding verbal self-critique loops) turns out to create new failure modes. ReliabilityBench shows: "The degradation gradient is steeper for Reflexion than ReAct, indicating that self-reflection mechanisms may amplify rather than mitigate fault impacts." Under stress conditions, ReAct achieves 80.9% successful fault recovery vs 67.3% for Reflexion [source-741a83ef08bb].

The deeper mechanism is the Accuracy-Correction Paradox: "The strongest model (DeepSeek, 94% accuracy) achieves the lowest intrinsic correction rate (16.7%), while weaker models (GPT-3.5: 26.8%, Claude: 29.1%) correct 1.6–1.7× more errors." [source-5d5fc2c07bb2] Stronger models make deeper errors (setup and logic flaws) that resist intrinsic correction. Worse: "Surprisingly, providing error location hints hurts all models... this may reflect poor localization quality or anchoring to incorrect reasoning paths." [source-5d5fc2c07bb2] This directly undermines the premise of Reflexion-style retry loops within ReAct.

## 3. Benchmark Evidence of the Performance Gap

The primary code-agent benchmark, SWE-Bench Verified, appeared to show ReAct-based agents approaching saturation with a top score of 78.80%. However, adversarial re-evaluation (SWE-ABS, 2026) reveals this is substantially inflated: "one in five 'solved' patches from the top-30 agents are semantically incorrect, passing only because weak test suites fail to expose their errors." The top agent's true score under strengthened testing drops from 78.80% to 62.20%, triggering significant leaderboard reshuffling [source-80c497f46e2c]. Agents exhibit shallow optimization: "agents tend to produce 'shallow' solutions that satisfy explicit test cases without achieving semantic completeness." [source-80c497f46e2c]

ReliabilityBench provides the most rigorous production-stress evaluation: "pass@1 overestimates reliability by 20-40%... If a benchmark reports 90% accuracy, expect 70-80% in production when accounting for consistency and faults." Perturbations to task phrasing alone cause an 8.8% reliability drop [source-741a83ef08bb]. The broader finding: "Agent performance drops from 60% to 25% between single execution and eight consecutive runs, a 58% degradation. This isn't something you fix only by swapping models." [source-07978d2e96f4]

On ToolQA's hard multi-step tasks, RP-ReAct shows ReAct's stability metrics are particularly poor: high standard deviation and low Combined Performance Score (CPS) relative to architectures with separated planning and execution [source-308a90d24e20].

## 4. Practical Mitigations That Have Emerged

### 4a. Error Taxonomy and Classified Retry Logic

The first structural fix is classifying errors at the point of failure before deciding whether to retry. The taxonomy distinguishes retryable errors (`TRANSIENT`, `RATE_LIMITED`, `DEPENDENCY_DOWN`) from non-retryable ones (`INVALID_INPUT`, `TOOL_NOT_FOUND`, `BUDGET_EXCEEDED`). The key architectural pattern: `if not exc.is_retryable(): log(RETRY_SKIPPED); break` [source-97b7d4aebe6c]. This drops wasted retries from 90.8% to 0% in the benchmark. This fix is independently applicable to any ReAct implementation without changing tool routing architecture.

### 4b. Per-Tool Circuit Breakers

Replacing a global retry counter with per-tool circuit breakers (trip after 3 consecutive failures, recovery probe after 5 seconds, close after 2 successful probes) contains failure locally. The controlled workflow logged 49 `CIRCUIT_OPEN` fast-fails that never touched a degraded upstream service—versus ReAct hammering degraded tools until the global budget is exhausted [source-97b7d4aebe6c]. For rate limiting specifically (identified as the highest-impact fault), exponential backoff with per-tool state is essential [source-741a83ef08bb].

### 4c. Deterministic Tool Routing

Moving tool name resolution from LLM runtime to compile time eliminates the hallucination-driven retry problem at source. "Use the LLM for reasoning — what steps are needed, in what order, with what arguments. Use Python for tool routing. The model contributes plan structure (step types), not tool name strings." [source-97b7d4aebe6c] The tradeoff is reduced flexibility for open-ended composition, but for production systems with predictable task structure, the reliability gains are substantial.

### 4d. Planner-Executor Role Separation (Hierarchical Architecture)

The dominant architectural response to context overflow is separating strategic planning from ReAct-loop execution. Multiple independent systems converge on this pattern:

**RP-ReAct** deploys a Reasoner Planner Agent (RPA) using a strong reasoning model for strategic direction, with Proxy-Execution Agents (PEA) running ReAct loops for each sub-task. The key insight: "all the complexity and potential errors associated with tool usage are offloaded to the PEA and never enter the RPA's context window." [source-308a90d24e20] The RPA can dynamically re-plan when a PEA fails, without the error propagating into the planning context.

**CodeDelegator** implements *ephemeral* Coder agents (fresh context per sub-task) vs a persistent Delegator. "All execution histories, intermediate code cells, debugging traces and failed attempts are not returned. This information is discarded with the Coder instance, enforcing asymmetric information flow that prevents context pollution." [source-b793ce7ff712] On MCPMark, this yields 38.4% total success vs ReAct's 25.8% and CodeAct's 26.4%, with the largest gains (+17.3%) on complex multi-step domains.

The agentic AI survey summarizes the broader trend: "Modern production systems increasingly combine controllable inference-time reasoning budgets with external controllers that enforce safety, state persistence, and tool permissions." [source-896e228f0105]

### 4e. Context Offloading and Compaction Strategies

For tasks where large tool outputs (SQL tables, CSV files) threaten context overflow, RP-ReAct implements a token threshold approach: "If the output returned by SQL query or a filtered CSV file exceeds this limit, only the first tokens of the output are immediately injected into the agent's context window... The original text is saved to a newly created temporary variable." [source-308a90d24e20] Anthropic's Claude Agent SDK implements automatic context compaction for long-running agents. The CLEAR enterprise framework treats context compaction as a key production metric alongside latency and cost.

### 4f. Graph-Based Orchestration vs. Free-Form ReAct Loops

The industry shift is away from open-ended ReAct loops toward explicit workflow graphs (LangGraph, OpenAI Swarm). "Rather than relying on a generic manager agent to decide what to do next in free-form dialogue, many production systems model the workflow as a state machine where nodes represent tool calls or LLM invocations and edges represent permissible transitions." [source-896e228f0105] This approach provides built-in checkpointing, typed state, approval gates, and bounded loops—directly addressing the infinite loop and uncontrolled retry failure modes.

## 5. Summary of Evolution Arc

| Phase | Architecture | Key Limitation |
|-------|-------------|----------------|
| 2022–2023 | Vanilla ReAct (single loop) | Myopia, error propagation |
| 2023–2024 | ReAct + Reflexion | Self-correction paradox; 2-3× token cost; steeper fault degradation |
| 2024–2025 | Plan-then-ReAct | Context overflow on hard tasks; step limit plateau |
| 2025–2026 | Hierarchical multi-agent (Planner + ephemeral ReAct executors) + graph orchestration | Coordination overhead; benchmark inflation |

The pattern has not been abandoned but has been relegated: ReAct is now most effectively deployed as the *local execution mechanism* within a broader orchestrated system, not as a top-level autonomous agent. Its core loop remains valid for bounded, tool-rich sub-tasks; its failure modes emerge at the system level when it is asked to self-manage planning, context, retries, and error recovery simultaneously.


### Reflexion-style self-critique architectures have evolved substantially from 2023–2026, moving from ephemeral, per-episode verbal feedback toward persistent memory systems, structured rule extraction, and verifier-augmented correction. Empirical evidence consistently shows that **

**Bottom line:** Reflexion-style self-critique architectures have evolved substantially from 2023–2026, moving from ephemeral, per-episode verbal feedback toward persistent memory systems, structured rule extraction, and verifier-augmented correction. Empirical evidence consistently shows that **intrinsic** self-correction (without any external signal) typically degrades or adds negligible value for reasoning tasks, but **verifier-augmented** variants (tool-interactive critique, process reward models, memory-as-a-tool) reliably improve performance—the evidence strongly supports the necessity of some form of external grounding for self-critique to add genuine value.

## Evolution of Reflexion-Style Self-Critique Architectures (2024–2026)

### 1. The Baseline: Original Reflexion (NeurIPS 2023)

The original Reflexion framework [source-b4229b3e9dba] introduced *verbal reinforcement learning*—agents convert binary/scalar feedback into natural-language self-reflections stored in episodic memory, improving behavior across trials without weight updates. Its three-component architecture (Actor, Evaluator, Self-Reflection) demonstrated impressive gains: 91% pass@1 on HumanEval (vs. GPT-4's 80%), +22% on AlfWorld, +20% on HotPotQA. However, the foundational paper already identified critical structural limits: memory is bounded to 1–3 sliding-window reflections due to context constraints, self-correction capacity is emergent only in larger models, and the framework "is unable to solve tasks that require a significant amount of diversity and exploration" (local minima problem).

Crucially, Reflexion's gains largely depended on an external evaluator signal—in coding tasks, a unit-test executor; in AlfWorld, environment completion flags. This external oracle dependence would become a central empirical controversy.

---

### 2. Empirically Identified Limits of Intrinsic Self-Correction

#### 2a. The Core Finding: LLMs Cannot Self-Correct Reasoning Intrinsically (ICLR 2024)

Huang et al. [source-636a71e35a60], published at ICLR 2024 with 860+ citations, provided the most systematic challenge to Reflexion-style assumptions. Their key findings:

- **Without external feedback, self-correction consistently degrades performance**: across GSM8K, CommonSenseQA, and HotPotQA, all models (GPT-3.5, GPT-4, GPT-4-Turbo, Llama-2) showed reduced accuracy after self-correction.
- **The fundamental problem**: "LLMs cannot properly judge the correctness of their reasoning." Without an oracle telling the model whether it's right, the correction step simply biases the model away from its optimal initial response.
- **Prior gains were artifactual**: "the improvements in these studies result from using oracle labels to guide the self-correction process, and the improvements vanish when oracle labels are not available."
- **Multi-agent debate ≠ genuine self-correction**: "the performance of multi-agent is only slightly better than that of self-consistency with the same number of agents"—the gains come from sampling diversity, not critique quality.
- **Prompt design confound**: many claimed self-correction gains "stem from the sub-optimal prompt for generating initial responses."

#### 2b. The Accuracy-Correction Paradox (2026)

Li [source-5d5fc2c07bb2] decomposed self-correction into three measurable sub-capabilities (error detection, localization, correction) and discovered a counterintuitive **Accuracy-Correction Paradox**: the strongest model (DeepSeek, 94% accuracy) achieves the *lowest* intrinsic correction rate (16.7%), while weaker models (GPT-3.5: 26.8%; Claude: 29.1%) correct 1.6–1.7× more errors.

The **Error Depth Hypothesis** explains this: stronger models make fewer but "deeper" errors (setup/logic errors: 77% of DeepSeek's mistakes) that resist self-correction, while weaker models make more "shallow" calculation errors (62% of GPT-3.5's mistakes) that are easily fixable upon re-examination.

Two additional counterintuitive findings:
- **Detection does not predict correction**: Claude detects only 10% of its errors but corrects 29% intrinsically—detection and correction are "largely independent capabilities."
- **Model-generated error location hints hurt all models** (GPT-3.5: 26.8%→15.5%; Claude: 29.1%→12.8%), likely due to anchoring on incorrect reasoning paths.

#### 2c. Memory Contamination and the Confidence Problem

The Confidence Matters paper (Li et al., 2024) [source-308a90d24e20] identified an important failure mode: undiscriminating self-criticism causes LLMs to "over-criticize themselves" and incorrectly change correct answers. "Across all 100 questions, LLM failed in intrinsic self-correction, as evidenced by a decrease in accuracy from 75.6% to 72.4% after executing the critical prompt."

This is a form of **memory contamination**: the critique step injects erroneous guidance that poisons subsequent reasoning. Specifically, the model is "more likely to modify a correct answer to an incorrect one than to revise an incorrect answer to a correct one."

From the 2026 agentic AI taxonomy [source-896e228f0105], Reflexion is explicitly categorized as having two key limitations: **hallucinated critiques** and **context overflow** (token complexity O(n²T)). The former means the model's self-reflections can fabricate reasons for failure that don't correspond to actual errors, then incorporate those fabrications into future context.

---

### 3. Newer Variants Addressing These Limits

#### 3a. Memory-as-a-Tool (2026)

"Distilling Feedback into Memory-as-a-Tool" [source-eda8a66f33e2] directly addresses Reflexion's ephemeral memory problem. The key insight: rather than repeating self-critique for every new query ("the reasoning process must be repeated ab initio for every new query"), the framework **amortizes** critique cost by converting transient feedback into persistent, retrievable file-based guidelines via LLM tool calls.

The protocol:
1. Generate response → receive evaluator feedback
2. LLM synthesizes **abstract principles** from specific failures (e.g., "Key Principle: Prioritize synesthetic blending" rather than raw error logs)
3. Write abstracted rules to `/memories/` via `write_file`/`edit_file` tool calls
4. Future tasks: LLM first `ls` the memories directory, reads relevant files, then generates guided responses

Results on Rubric Feedback Bench (Claude Sonnet 4.5, GPT-5.1, Gemini 3 Pro): "our augmented LLMs rapidly match the performance of test-time refinement pipelines while drastically reducing inference cost." The Memory+Feedback approach "occupies a critical Pareto optimal point: it achieves comparable scores to self-critique while maintaining a cost profile much closer to the baseline."

This directly attacks memory contamination by having the agent distill episodic feedback into semantic rules rather than storing raw error logs—"remains a high-signal knowledge base of synthesized rules rather than a noisy log of raw interaction history."

#### 3b. Meta-Policy Reflexion (2025)

Meta-Policy Reflexion (MPR) [source-f285051aa21b] addresses cross-task generalization by consolidating episodic Reflexion traces into a **structured Meta-Policy Memory (MPM)** of predicate-style rules. It uses two complementary mechanisms:
- **Soft guidance**: memory-conditioned decoding that biases LLM toward memory-supported actions
- **Hard Admissibility Checks (HAC)**: post-hoc constraint validation that prevents invalid/unsafe actions

The key result on AlfWorld: MPR achieves 100% training set accuracy by round 3 (vs. Reflexion's 87.2%), and crucially, "MPR—trained for five rounds on the 60-task training set and evaluated once on the 74-task test set—achieved 87.8%" vs. Reflexion's 86.9% after *six* in-situ reflection rounds. Adding HAC raises accuracy to 91.4%.

This addresses both memory contamination (predicate rules are verified, not raw text) and scalability (rules transfer across tasks without repeated reflection).

#### 3c. Verifier-Augmented Approaches (CRITIC, CorrectBench 2025)

The CorrectBench benchmark (NeurIPS 2025) [source-885b48ff3df8] provides the most comprehensive empirical comparison:

- **Reflexion-v1 (without external tools)**: "nearly all data points fall below the baseline"—declines on HotpotQA (-11.13%), AQUA (-12.90%), and most tasks
- **Reflexion-v2 (with external tools)**: consistently improves performance—+7.33% on HotpotQA, +7.00% on AQUA

This is the clearest empirical demonstration of the verifier-augmented principle: the *architecture* of Reflexion works when the Evaluator component uses actual external signals, not self-generated critique.

CRITIC (Gou et al., 2023) operationalizes this systematically by requiring **tool-interactive validation** before accepting any revision—e.g., running a Python interpreter to check mathematical claims, or a search engine to verify factual claims. The 2026 taxonomy [source-896e228f0105] notes CRITIC "reduces purely internal confirmation loops by requiring tool-interactive validation."

#### 3d. Confidence-Gated Self-Correction (If-or-Else Prompting, 2024)

The IoE framework [source-308a90d24e20] provides a lightweight fix to intrinsic self-correction's degradation problem: gate correction on confidence. If the model assesses itself as confident, keep the answer; only revise if unconfident. 

Results: IoE consistently improves over both standard prompting and Critical Prompt across 4 models and 6 benchmarks (e.g., GPT-3.5: 70.3% standard → 73.7% IoE). Notably, "the magnitude of improvement from our IoE-based Prompt decreases as the capability of the model increases"—consistent with the Accuracy-Correction Paradox.

#### 3e. Robust Verbal RL and Cross-Task Memory (LLM4FL, 2024)

In software engineering applications, LLM4FL [source-885b48ff3df8] demonstrates Reflexion-style verbal RL in a multi-agent fault localization system. Three specialized agents (Context Extractor, Debugger, Reviewer) form a pipeline where the Reviewer applies iterative self-critique and re-ranking. Ablation results: removing the Reflexion component reduces Top-1 accuracy by 11.31%. Significantly, this improvement occurs even without an external oracle—"we did not provide any groundtruth or external feedback to LLM, we found that reflexion is still effective in improving fault localization results." The structured code review context provides an implicit verifier via execution data and call graph structure.

#### 3f. Reasoning LLMs: Built-In Reflection (2025)

An important 2025–2026 development is the emergence of reasoning LLMs that internalize reflection. CorrectBench [source-885b48ff3df8] found that "DeepSeek-V3 integrates advanced reflection modules and comprehensive error-detection routines distilled from its earlier R1 series, enabling thorough multi-step reasoning at the outset. This high baseline effectively reduces the scope for further improvement through additional self-correction." Reasoning LLMs show "limited optimization under additional self-correction methods."

This suggests that the reflection capability is increasingly being incorporated at training time (through RL from verifiers during RLHF/RLAIF), effectively making external Reflexion-style loops redundant for models that have already internalized the self-correction pattern.

---

### 4. Does Self-Critique Without External Verifier Add Value?

**The evidence converges on a qualified "rarely, and only in specific conditions":**

**Against (strong evidence)**:
1. Huang et al. (ICLR 2024): "LLMs struggle to self-correct their responses without external feedback, and at times, their performance even degrades after self-correction" [source-636a71e35a60].
2. CorrectBench (NeurIPS 2025): Reflexion without tools "nearly all data points fall below the baseline" [source-885b48ff3df8].
3. Accuracy-Correction Paradox: the model most capable of initially succeeding is least capable of detecting and correcting its deeper errors [source-5d5fc2c07bb2].

**In favor (conditional evidence)**:
1. **Iterative reflection compensates for weak detection**: Despite Claude detecting only 10% of errors, iterative reflection achieves 60.8% correction—6× improvement [source-5d5fc2c07bb2]. For shallow errors (calculation mistakes), multiple re-solving attempts work as a form of stochastic diversity.
2. **Structured code environments**: LLM4FL shows 11% improvement from self-reflection even without ground-truth oracle [source-885b48ff3df8]. The code context provides implicit verification through structural consistency.
3. **Confidence-gated critique**: IoE prompting turns intrinsic self-correction from net-negative to net-positive by only applying critique to genuinely uncertain cases [source-308a90d24e20].
4. **Memory-as-a-Tool with external feedback phase**: When feedback is available during training/learning, Memory-as-a-Tool can eliminate the need for per-instance self-critique while retaining its benefits [source-eda8a66f33e2].

**The practical implication**: Self-critique *without* external verifier is essentially asking the model to generate a random perturbation of its response and hope it improves. For tasks with ground truth verifiers (code execution, math checking, fact retrieval), Reflexion-style architectures deliver genuine value. For open-ended reasoning where the model is also the judge, the evidence strongly suggests the critique step is noise or harmful.

---

### 5. Summary of the Evolution Trajectory

| Era | Architecture | Key Mechanism | Key Limitation |
|-----|-------------|--------------|----------------|
| 2023 (NeurIPS) | Original Reflexion | Verbal RL + episodic memory | Context overflow, hallucinated critiques, oracle dependency |
| 2024 | Confidence-gated IoE | Confidence-conditional critique | Still intrinsic; only partial fix |
| 2024 | LLM4FL (Graph-RAG + Reflexion) | Code execution as implicit verifier | Domain-specific |
| 2024 | CRITIC | Tool-interactive validation | Requires external tool availability |
| 2025 | Meta-Policy Reflexion | Predicate-rule memory, hard admissibility | AlfWorld-specific evaluation |
| 2025 | Reasoning LLMs (R1, DeepSeek-V3) | Internalized self-correction at training time | Makes external Reflexion redundant |
| 2026 | Memory-as-a-Tool | Amortized feedback into file-based memory | Requires initial feedback phase |

The overall arc is from **ephemeral, per-instance verbal critique** (hoping intrinsic reflection works) toward **persistent, externally-grounded knowledge extraction** (using verified signals to build lasting correction policies).


### Planner-executor architectures evolved substantially from 2023–2026, moving from static Plan-and-Execute/ReWOO (upfront planning, rigid execution), through adaptive replanning (ADaPT, OPERA), hierarchical supervision (RPR, Planner-Verifier/Critic-Executor), and code-as-action par

**Bottom line:** Planner-executor architectures evolved substantially from 2023–2026, moving from static Plan-and-Execute/ReWOO (upfront planning, rigid execution), through adaptive replanning (ADaPT, OPERA), hierarchical supervision (RPR, Planner-Verifier/Critic-Executor), and code-as-action paradigms (CodeAct, CodeDelegator). Quantitative gains are large—ReWOO cuts LLM calls by 5–10× over ReAct, ADaPT boosts success rates 28–33%, OPERA achieves 11–16 pt EM gains on multi-hop QA, CodeAct gains 20% on complex tasks, and CodeDelegator adds 12% absolute over CodeAct—but each pattern introduces distinct trade-offs between rigidity, context pollution, and coordination overhead.

# Evolution of Planner-Executor Architectures (2024–2026)

## Conceptual Lineage

The planner-executor split has its roots in classical AI planning but crystallized as a mainstream LLM pattern through the shortcomings of ReAct (Yao et al., 2022). ReAct's Thought–Action–Observation loop is adaptive and interpretable, but it requires **5–7 LLM calls per interaction** due to the full conversation history being re-appended at every step [source-07978d2e96f4]. This spawned a family of architectures optimizing different failure modes.

---

## 1. Plan-and-Execute and ReWOO (2023–2024)

**Plan-and-Execute** splits work into an upfront planning phase (one LLM call generating a numbered todo list) and an execution phase (an executor working through steps, often itself a ReAct loop). This reduces the "monolithic plan-execute loop which directly causes trajectory instability" [source-308a90d24e20] and is more token-efficient for long-horizon tasks with stable intermediate steps.

**ReWOO** (Reasoning WithOut Observation, Xu et al. 2023) is the most aggressive optimization of this idea. Its Planner generates a complete script upfront using placeholder variables (`#E1`, `#E2`), Workers execute tool calls without any LLM reasoning between them, and a Solver synthesizes the final answer. Because the full plan is formed in one pass and tools can run in parallel, ReWOO achieves **5× token efficiency and a 4% accuracy improvement over ReAct on HotpotQA** [source-325e6c9773da]. The capabl.in analysis estimates token reduction at **5–10× versus a complex ReAct trace** [source-325e6c9773da].

**Quantitative benefit:** ~5× fewer LLM tokens; tools parallelizable; reduced latency.

**Trade-offs:**
- **Rigidity**: "If the initial plan generated by the Planner is flawed, or if a Worker returns an unexpected error, the agent has no built-in mechanism to self-correct or pivot" [source-325e6c9773da]. This makes ReWOO brittle in dynamic environments.
- **Plan scope limits**: Requires reasonably predictable task sequences. Fails on tasks requiring mid-task pivots based on observed results.

---

## 2. ADaPT — Adaptive Replanning (NAACL 2024)

ADaPT (As-Needed Decomposition and Planning) was the first systematic answer to Plan-and-Execute rigidity. Rather than planning everything upfront or always using a flat executor, ADaPT **triggers recursive sub-task decomposition only when the executor LLM fails**. This adapts dynamically to both task complexity and executor capability.

**Quantitative benefit:** ADaPT "substantially outperforms established strong baselines, achieving success rates up to **28.3% higher in ALFWorld, 27% in WebShop, and 33% in TextCraft**" [source-9ab43874224d]. Crucially, the decomposition overhead is paid only where needed.

**Trade-offs:**
- Recursive decomposition can cascade if executors are weak across many sub-tasks, incurring multiple LLM rounds.
- Requires a failure-detection heuristic to trigger decomposition; false positives lead to unnecessary overhead.
- Still uses a single-context executor; context pollution from sub-task debugging can accumulate.

---

## 3. Reason-Plan-ReAct (RPR) (arXiv Dec 2025)

RPR / RP-ReAct takes the planner-executor split further by using **a Large Reasoning Model (LRM) as the Reasoner-Planner Agent (RPA)** and dedicated Proxy-Execution Agents (PEA) for low-level ReAct tool loops. The RPA maintains a clean context with only sub-question results; all debugging traces, error retries, and raw tool outputs are confined to the PEA and never enter the RPA.

**Architecture:** RPA issues sub-questions tagged between `<|begin_search_query|>` and `<|end_search_query|>`. PEA executes the ReAct loop and returns only results. The RPA dynamically replans on failure: "If the execution fails or produces an unexpected output, the RPA initiates a self-correction mechanism" [source-308a90d24e20].

**Context management innovation:** When tool outputs exceed a token threshold, only a preview is injected into the PEA's context; the full data is stored in a variable for Python-tool analysis. This prevents context overflow in open-weight models with small context windows.

**Quantitative benefit:**
- On hard ToolQA tasks (multi-step, multi-tool), RPR outperforms ReAct significantly, especially for smaller models (e.g., gpt-oss-20b gains from 0.06 to 0.16 on Yelp hard benchmark).
- Simply extending ReAct's step limit to 100 yields only **4.8% average improvement**, confirming RPR's structural advantage is not merely about step count [source-308a90d24e20].
- More stable: lower standard deviation across 6 different open-weight models (the key metric for enterprise open-weight deployment).

**Trade-offs:**
- **Planning overhead hurts easy tasks**: "For easy tasks, the inherent planning overhead in RP-ReAct often disrupts the optimal trajectory. The RPA may introduce redundant actions (such as repeated database loading) or initiate unnecessary verifications" [source-308a90d24e20].
- Smaller models (<10B parameters) are too weak to maintain valid RPA-PEA coordination.
- Multiple LLM calls per task cycle (RPA call + PEA loop per sub-question); total step budget can reach 100 (10 × 10).

---

## 4. Planner-Verifier/Critic-Executor (2024–2025)

The Emergent Mind taxonomy documents several extended variants of the basic planner-executor framework that add verification layers:

- **Planner–Verifier–Executor**: A "Responder" agent checks if the goal is met before returning to the Planner. This prevents premature task completion.
- **Planner–Critic–Executor**: An explicit Critic scores stepwise action quality, enabling closed-loop replanning. Used in embodied tasks where each step's affordance must be validated.

These patterns address the fundamental weakness identified in OPERA ablations: "removing architectural components causes catastrophic performance drops, while training method improvements are more gradual" [source-26920bebe49f]. They shift error detection from post-hoc (e.g., Reflexion) to within-step verification.

**Trade-offs:**
- Additional LLM calls for verification increase total cost, potentially 2–3× baseline.
- Verifier quality is bottlenecked by the verifier LLM's capability—a weak critic can reject correct plans or approve wrong ones.
- Security analysis (EmergentMind) finds that "attacks targeting the Planner (via prompt injection, memory corruption, or plan manipulation) are markedly more successful and damaging than attacks on the Executor," making the Planner–Verifier interface a higher-priority attack surface.

---

## 5. OPERA — RL-Enhanced Planner-Executor (arXiv Aug 2025)

OPERA (Orchestrated Planner-Executor Reasoning Architecture) applies **multi-agent progressive RL (MAPGRPO)** to jointly train a Goal Planning Module (GPM) and a Reason-Execute Module (REM) for complex multi-hop retrieval.

**Architecture:** The GPM's Plan Agent decomposes questions into sub-goals with placeholder dependencies. REM's Analysis-Answer Agent assesses document sufficiency; when insufficient, a Rewrite Agent reformulates queries adaptively. A Trajectory Memory Component (TMC) logs each agent's reasoning for interpretability.

**Quantitative benefits:**
- HotpotQA: **57.3% EM** (+11.6 pts over best baseline)
- 2WikiMultiHopQA: **60.2% EM** (+15.9 pts)
- Musique: **39.7% EM** (+15.4 pts; **63.4% relative improvement**) [source-26920bebe49f]
- Removing the Plan Agent drops performance below even untrained CoT baseline (17.1% vs 21.2% EM), demonstrating the critical role of structured planning
- Three-agent decomposition achieves **linear computational complexity** vs exponential for single-agent approaches [source-26920bebe49f]

**Trade-offs:**
- Training overhead: three separate MAPGRPO training stages needed, each with role-specific reward functions.
- Rewrite Agent is conditionally activated (only on retrieval failure), yielding sparse rewards and unstable training.
- SFT training "overfits to multi-hop patterns, attempting decomposition even when not needed," showing rigid behavior [source-26920bebe49f] — the RL approach preserves flexibility but is more expensive.
- On single-hop out-of-domain NQ, SFT drops to 19.5% while MAPGRPO achieves 36.6%, showing the rigidity penalty from over-planning.

---

## 6. CodeAct (ICML 2024)

CodeAct proposes replacing JSON/text tool calls with **executable Python as the unified action space**, enabling control flow, variable reuse, and multi-tool composition within a single action.

**Quantitative benefits:**
- Up to **20% absolute improvement** in success rate on complex multi-tool tasks (M3ToolEval benchmark across 17 LLMs) [source-ddced5591da2]
- Up to **30% fewer actions** required due to composing multiple tool calls in single code blocks [source-ddced5591da2]
- Performance gains widen as LLM capability increases

**Trade-offs:**
- **Context pollution**: CodeAct "incurs more context length across all difficulty levels compared to ReAct," with overhead yielding inconsistent returns — **underperforms ReAct on Low difficulty by 5.8% and Medium by 2.5%** while gaining on High (+7.7%) [source-b793ce7ff712].
- Debugging traces (tracebacks, print outputs, failed code) accumulate in shared context, degrading subsequent planning decisions.
- Security risks from arbitrary code execution require sandboxed environments.
- Even at 26.9% on high-difficulty τ-bench tasks, absolute success remains low due to context pollution.

---

## 7. CodeDelegator (arXiv Jan 2026)

CodeDelegator directly solves CodeAct's context pollution problem via **role separation and Ephemeral-Persistent State Separation (EPSS)**.

**Architecture:** A persistent Delegator handles strategic planning (task decomposition, dependency tracking, progress monitoring) without ever writing implementation code. For each sub-task, a fresh ephemeral Coder is instantiated with only its specification and designated inputs. Upon completion, "full execution histories, intermediate code cells, debugging traces and failed attempts are not returned. This information is discarded with the Coder instance" [source-b793ce7ff712]. The Delegator maintains only structured results (status, artifacts, diagnostics) in its orchestration layer.

**EPSS layers:** Session-wide Orchestration Layer (Delegator, with typed artifact storage) vs. ephemeral Execution Layer (per-Coder, with namespace isolation and trace confinement).

**Quantitative benefits:**
- **MCPMark**: CodeDelegator 38.4% vs ReAct 25.8% vs CodeAct 26.4% (**+12% absolute over CodeAct**) [source-b793ce7ff712]
- **τ-bench Retail** (DeepSeekV3.2): 82.0% vs 79.6% (ReAct) vs 70.2% (CodeAct), with CodeAct's degradation from Low→High tasks (5.8% gap) vs CodeDelegator's graceful degradation
- Ablation: Role separation alone accounts for 10.5% performance, EPSS for 4.7% [source-b793ce7ff712]
- Specifically large gains in multi-step domains: GitHub +10.1%, Notion +15.4%, Playwright +17.3% over CodeAct

**Trade-offs:**
- Sequential task decomposition (no DAG support yet): "does not yet support more expressive agent patterns such as directed acyclic graphs (DAGs) of sub‑tasks or asynchronous interaction" [source-b793ce7ff712].
- PostgreSQL is an exception where ReAct wins (52.4% vs 41.7%), as transactional semantics align better with single-call-per-step patterns.
- Two separate agent contexts = roughly 2× LLM calls per sub-task (Delegator + Coder), increasing token costs.

---

## Comparative Summary

| Architecture | LLM Call Reduction | Accuracy Gain | Key Trade-Off |
|---|---|---|---|
| **ReWOO** | **5–10× fewer tokens vs ReAct** | +4% on HotpotQA | Rigid; no mid-plan recovery |
| **Plan-and-Execute** | ~30–50% fewer calls vs ReAct | Variable | Initial plan quality bottleneck |
| **ADaPT** | Overhead only when failing | +28–33% vs baselines | Cascading recursive overhead possible |
| **RPR** | More calls (RPA + PEA each round) | Dominant on hard multi-step tasks | Planning overhead hurts easy tasks |
| **Planner-Verifier/Critic** | 2–3× more calls | Higher precision/safety | Verifier quality bottleneck; attack surface |
| **OPERA** | Linear vs exponential complexity | +11–16 EM pts on multi-hop QA | 3-stage RL training; unstable rewrite rewards |
| **CodeAct** | ~30% fewer actions | +20% on complex multi-tool | Context pollution degrades long-horizon |
| **CodeDelegator** | 2× (Delegator + Coder) | +12% abs over CodeAct | Sequential only (no DAGs); SQL fails |

---

## Cross-Cutting Themes

**Context pollution** is the central 2025–2026 problem: as agents tackle longer-horizon tasks, debugging traces, error logs, and tool outputs contaminate planning contexts. RPR addresses this by separating planner context from executor traces. CodeDelegator addresses it by discarding Coder contexts entirely.

**Rigidity vs. adaptability:** Earlier architectures (ReWOO, Plan-and-Execute) sacrifice adaptability for token efficiency. ADaPT, RPR, and OPERA show that **conditional re-planning** recovers most accuracy gains while avoiding unnecessary overhead. The key insight is that decomposition should be triggered on failure, not pre-emptively.

**Complexity scaling:** Multiple architectures confirm that their advantages emerge most strongly on *hard* tasks: OPERA shows 63.4% relative improvement on Musique vs. 25.4% on HotpotQA; RPR dominates ReAct on hard ToolQA; CodeDelegator's lead over CodeAct widens with task complexity. The overhead of hierarchical separation is justified at scale.

**RL vs. prompting:** OPERA demonstrates that trajectory-level RL (MAPGRPO) prevents the rigidity that SFT induces, at the cost of multi-stage training. "SFT overfits to multi-hop patterns, attempting decomposition even when not needed" [source-26920bebe49f].


### In 2025–2026, six dominant orchestration topologies have emerged (with orchestrator-worker and hierarchical patterns most widely deployed), MCP and A2A have become the de-facto interoperability standards serving complementary roles, and LangGraph leads frameworks on adoption and 

**Bottom line:** In 2025–2026, six dominant orchestration topologies have emerged (with orchestrator-worker and hierarchical patterns most widely deployed), MCP and A2A have become the de-facto interoperability standards serving complementary roles, and LangGraph leads frameworks on adoption and efficiency while CrewAI excels at prototyping speed—but multi-agent systems carry 3–5x token cost and 4.3x latency penalties that only justify investment for genuinely parallel, high-volume, or specialized-accuracy workloads.

# Multi-Agent Orchestration in 2025–2026: Patterns, Protocols, and Framework Comparison

## Executive Summary

The multi-agent landscape has matured dramatically: Gartner recorded a **1,445% surge** in multi-agent system inquiries between Q1 2024 and Q2 2025 [source-5e174290b618], and Databricks reports 327% growth in multi-agent deployments year-over-year [source-f3d1588a2e4a]. Yet 85% of companies still fail to move past proof-of-concept, and only 10% successfully scale enterprise multi-agent systems [source-a348020a4683]. The dominant obstacle is not technical capability—it is the economics and governance of coordination.

---

## 1. Dominant Orchestration Patterns

The 2025–2026 literature and production evidence converge on **six core topologies**, which are not mutually exclusive—production systems typically combine two or three [source-98fbed7cd5e5].

### 1.1 Orchestrator-Worker / Hierarchical

The most widely deployed pattern. A single orchestrator receives the task, decomposes it into subtasks, delegates each to specialist workers, and assembles results. The orchestrator uses a capable model while workers use cheaper, task-specific ones, cutting costs 40–60% [source-5e174290b618]. Production examples include Wells Fargo (35,000 bankers accessing 1,700 procedures in 30 seconds), Salesforce Agentforce 2.0 (Atlas Reasoning Engine), and—at research scale—Moonshot's Kimi K2.5 Agent Swarm [source-636a71e35a60].

Key failure mode: the orchestrator is a single point of failure. Context window overflow is the subtler problem—at four or more workers, the orchestrator accumulates context from every worker, driving costs from $0.50 in testing to $50,000/month at 100K executions [source-5e174290b618].

**Hierarchical variants** (multi-level, where agents at level *n* spawn level *n+1*) are formally catalogued in the RL literature as distinct from flat orchestrator-worker. Systems like HALO and DEPART demonstrate hierarchical spawn/delegate across multiple tiers [source-98fbed7cd5e5].

### 1.2 Sequential Pipeline (Coordinator-Worker)

Agents execute in a predefined linear chain, each processing the previous agent's output through shared state. Used for document processing (parse → extract → validate → summarize) and contract generation. A four-agent pipeline accumulates roughly **950ms of coordination overhead** while actual processing takes 500ms—consuming 29,000 tokens versus 10,000 for a single-agent approach [source-5e174290b618].

Error propagation is the structural risk: bad output in stage 1 cascades through every downstream stage.

### 1.3 Fan-Out / Fan-In (Parallel Swarm)

Multiple agents execute simultaneously on independent subtasks; a dispatcher sends work out and a collector aggregates results using voting, weighted merging, or LLM-based synthesis. Can cut wall-clock time by 75% for genuinely parallel work. API rate limits and race conditions on shared state scale quadratically (N(N−1)/2 potential conflicts at N agents) [source-5e174290b618].

At the industrial scale, Kimi K2.6 reports a parallel swarm reaching coordinated steps with up to sub-agents using **Parallel-Agent Reinforcement Learning (PARL)**—the clearest public example of a *trained* orchestrator [source-98fbed7cd5e5].

### 1.4 Dynamic Handoff

Each agent assesses the current task and decides whether to handle it or transfer control to a more appropriate specialist. No central coordinator—agents delegate to each other based on runtime context. HCLTech reported 40% faster case resolution with this pattern. The primary failure mode is infinite handoff loops (A → B → C → A); context loss compounds with every transfer [source-5e174290b618].

### 1.5 Dynamic / Evolving Orchestration

The OpenReview "Puppeteer" paper (2025, aligned with HALO and ParaManager in the RL literature) proposes an RL-trained orchestrator that *adaptively sequences and prioritizes agents in response to evolving task states*. Unlike static structures, the orchestrator learns to produce "more compact, cyclic reasoning structures," achieving superior performance with reduced computational costs [source-6808a55dc508]. This is the pattern Microsoft calls "adaptive planning"—a manager agent that dynamically builds, refines, and executes a plan by consulting specialists, with the plan itself discovered through collaboration [source-5e174290b618].

### 1.6 Multi-Agent Debate / Committee

Multiple agents participate in shared conversation, contributing perspectives and challenging each other. Research shows debate reduces hallucinations vs. single-model queries; a practical variant uses a cheap model for the "maker" and a capable model for the "checker" at 40–60% lower cost. Sycophancy cascading is the key risk: agents agree with the majority even when wrong, producing false consensus. Microsoft recommends limiting group chat to three or fewer agents for this reason [source-5e174290b618].

---

## 2. RL-Trained Orchestration

Reinforcement learning for multi-agent orchestration is an active frontier as of 2026. The academic taxonomy decomposes orchestration learning into **five sub-decisions**: when to spawn, whom to delegate to, how to communicate, how to aggregate, and when to stop. As of May 2026, *no explicit RL training method exists for the stopping decision* [source-98fbed7cd5e5].

**Industrial evidence:** Moonshot's Kimi K2.5 is the clearest public example of a trained orchestrator. PARL decomposes the reward as: (task outcome) + (speedup over serial baseline) + (all sub-agents reaching termination, a guard against pseudo-parallelism), with auxiliary rewards annealed to zero during training so the final policy optimizes primary task objective [source-98fbed7cd5e5]. Kimi K2.6 scales to coordinated steps with Claw Groups for cross-vendor coordination.

**Academic progress:** 2025–Q2 to May 2026 produced systematic multi-agent RFT paradigms, hierarchical GRPO decomposition, and Shapley-based agent-level credit assignment. The dominant challenge is **credit diffusion**: uniform credit allocation under shared terminal rewards makes per-decision signals harder to distinguish as trace length grows [source-98fbed7cd5e5].

---

## 3. MCP and A2A: The Interoperability Protocol Layer

### Model Context Protocol (MCP)

Introduced by Anthropic in 2024, MCP provides a **JSON-RPC 2.0 client-server interface** for secure tool invocation and typed data exchange. It standardizes how agents access external tools, databases, and contextual repositories—eliminating brittle ad-hoc connectors. MCP exposes four core capabilities: Tools (model-controlled), Resources (application-controlled), Prompts (user-controlled templates), and Sampling (server-controlled LLM delegation). It supports both stateless and stateful session management for multi-step workflows, with logging and synchronization back to orchestration state [source-636a71e35a60].

MCP was donated to the Linux Foundation in December 2025 [source-3a65eb0417b5].

### Agent-to-Agent Protocol (A2A)

Announced by Google Cloud in April 2025 with 50+ technology and consulting partners, A2A provides **peer-to-peer agent coordination** standardizing how agents discover each other, communicate, and collaborate regardless of vendor or framework. Its key components: **Agent Cards** (JSON-format capability declarations), Task lifecycle management (including long-running processes), enterprise-grade security (HTTP/SSE/JSON-RPC), and modality-agnostic communication (text, audio, video, structured data) [source-3f6f323355fe].

Google ADK natively implements A2A, allowing ADK agents to discover and invoke agents built on LangGraph, CrewAI, or other frameworks through A2A's standardized task interface [source-193830c8dc2c].

### MCP vs. A2A: Complementary Roles

| Dimension | MCP | A2A |
|-----------|-----|-----|
| Scope | Single-agent → external tools/data | Multi-agent peer collaboration |
| Architecture | Client-server (JSON-RPC 2.0) | Peer model (client agent + remote agent) |
| Discovery | Tool/resource registration | Agent Cards at `/.well-known/agent.json` |
| Task handling | Tools executed on demand | Full task lifecycle with artifacts and streaming |
| Primary use | Internal agent augmentation | Cross-agent, cross-framework orchestration |

"MCP powers agents internally with context and tools, while A2A connects agents externally for collaboration and task execution. Together, they form a robust framework for scalable, multi-agent AI systems." [source-3f6f323355fe]

A phased adoption roadmap: begin with MCP for tool access, add A2A for collaborative task execution, extend to ANP (Agent Network Protocol) for decentralized agent marketplaces [source-3a65eb0417b5].

---

## 4. Framework Comparison

### Adoption Signals

By search volume (Langfuse data), **LangGraph** leads with 27,100 monthly searches; **CrewAI** follows with 14,800. But "search volume doesn't equal production readiness" [source-193830c8dc2c]. The broader ecosystem includes: LangGraph, CrewAI, AutoGen/AG2, Google ADK, MetaGPT, and AWS Strands—each with a distinct orchestration philosophy.

### Framework Architectures

| Framework | Orchestration Model | State Management | Model Lock-in | Production Readiness |
|-----------|--------------------|--------------------|---------------|---------------------|
| **LangGraph** | Directed graph with typed state and conditional edges | Built-in checkpointing with time-travel | Model-agnostic | Highest (LangSmith observability) |
| **CrewAI** | Role-based crews: sequential / hierarchical / consensual | Task outputs passed sequentially (no checkpointing) | Model-agnostic | Medium (growing ecosystem) |
| **AutoGen/AG2** | Conversational GroupChat with dynamic selector | Conversation history in-memory | Model-agnostic | Medium (AG2 rewrite maturing) |
| **Google ADK** | Hierarchical agent tree | Session state with pluggable backends | Optimized for Gemini | Early/growing (Vertex AI-backed) |
| **MetaGPT** | Role-based SOP orchestration | Structured message passing | Model-agnostic | Medium (software engineering focused) |
| **Strands (AWS)** | GraphBuilder DAG with explicit typed handoffs | AgentResult + GraphResult traces | Amazon Bedrock/Anthropic/Mistral | Growing (enterprise AWS integration) |

### Latency and Token Cost

**Empirical benchmark (AIMultiple, 750 runs, three tasks of increasing complexity):**

- **LangGraph** (single-agent mode): Matches LangChain efficiency at low complexity; adds graph-traversal overhead at high complexity (100 tools, 10-agent reasoning). Maintains high accuracy throughout [source-c3bc3c73c288].
- **CrewAI** (sequential): Exponential token growth as each agent's output compounds into the next context—the state compounding mechanism. Forced to execute all assigned agents even when subsets suffice [source-c3bc3c73c288].
- **AutoGen/AG2** (GroupChat): High handoff counts; every turn reprocesses entire conversation history. At Task 3 (10 agents, 100 tools), consumed 56,700 tokens vs 13,500 for LangGraph—but GroupChatManager's dynamic pruning prevents CrewAI-level explosion [source-c3bc3c73c288].
- **Swarm** (OpenAI): Stateless routing achieves fastest execution but progressive accuracy collapse (84% → 0%) as task complexity grows beyond simple 1-to-2 handoffs. "Handoff Paradox" at longer chains [source-c3bc3c73c288].

**Production cost reality (3-agent system):**
- A 3-agent customer support workflow: 5.2s total vs 1.8s for single-agent RAG (4.3x latency penalty) [source-f3d1588a2e4a]
- Token amplification: 4.3–4.6x more tokens per query due to coordination overhead [source-f3d1588a2e4a]
- 4-agent pipeline: 29K tokens vs 10K for single-agent equivalent [source-5e174290b618]

**CLEAR framework evaluation (6 agents, 300 enterprise tasks):**
- Reflexion achieves highest raw accuracy (74.1%) but at 5.12x cost; Plan-Execute achieves 71.9% at $1.24 (4.1x cheaper) with better pass@8 reliability (64.5% vs 61.2%) [source-a348020a4683].
- ReAct-GPT-o3 achieves the best cost-normalized accuracy (221.6 CNA) despite lower raw accuracy [source-a348020a4683].

**Strands benchmarks (τ-Bench airline domain):**
- ReAct: 8–67s (fastest, but policy-incorrect on complex cases)
- ReWOO (plan→execute→synthesize): 14–43s (slower, best governance/auditability)
- Reflexion (iterative critique): 27–116s (slowest, best for multi-constraint decisions)
[source-cbbd9f6b5271]

### Framework Selection Guide

- **LangGraph**: Best for complex branching workflows with human-in-the-loop approvals, regulated industries needing audit trails, production systems needing time-travel debugging [source-193830c8dc2c]
- **CrewAI**: Fastest prototyping (20 lines to working system); plan to re-evaluate after 6–12 months at scale [source-193830c8dc2c]
- **AutoGen/AG2**: Quality-sensitive offline workflows (code review, research tasks) where thoroughness beats latency [source-193830c8dc2c]
- **Google ADK**: Teams needing cross-framework interoperability via A2A, multimodal agents, or Google Cloud-native deployments [source-193830c8dc2c]
- **MetaGPT**: Software engineering automation with structured SOP role-based coordination
- **Strands**: AWS-native teams needing production-ready GraphBuilder DAGs with Bedrock integration and OpenTelemetry tracing [source-cbbd9f6b5271]

---

## 5. Key Trade-offs and When Multi-Agent Is Worth It

Princeton NLP found that a single agent matched or outperformed multi-agent systems on **64% of benchmarked tasks** when given the same tools and context; multi-agent adds only 2.1 percentage points of accuracy at roughly double the cost [source-5e174290b618].

**Multi-agent ROI is positive when:**
- Workflow is genuinely parallelizable (code gen + security review + test generation simultaneously)
- Volume exceeds ~50K queries/month (coordination infrastructure amortizes)
- Specialized fine-tuned accuracy is required (>95% threshold, e.g., legal contracts)
- Large teams (10+ engineers) can absorb operational complexity

**Single-agent wins when:**
- Workflow is linear (A → B → C, no parallelization benefit)
- Volume is low (<10K queries/month)
- Latency matters (multi-agent coordination adds 2–5 seconds)
- Budget is tight (3–5x token amplification is not justified) [source-f3d1588a2e4a]

The CLEAR framework (Cost, Latency, Efficacy, Assurance, Reliability) provides the most rigorous enterprise evaluation lens, showing that CLEAR scores correlate strongly with expert production readiness assessments (r=0.83) versus accuracy-alone (r=0.41) [source-a348020a4683].

---

## 6. Open Issues and Future Directions

1. **RL stopping decisions**: No published RL method explicitly trains the "when to stop" orchestration sub-decision [source-98fbed7cd5e5]
2. **Credit diffusion at scale**: Academic methods train on short traces; Kimi reports 1000+ step traces that current methods may not handle [source-98fbed7cd5e5]
3. **Protocol maturity**: A2A was donated to Linux Foundation in June 2025—ecosystem tooling and security audits are still maturing [source-3f6f323355fe]
4. **Benchmark gaps**: Current benchmarks don't measure parallelism efficiency, collaboration quality, or error amplification—the properties RL-MAS actually optimizes [source-98fbed7cd5e5]


### The empirical evidence consistently shows that simpler architectures outperform complex ones at production scale: ReAct beats Reflexion under stress conditions, Plan-Execute dominates Reflexion on cost-normalized and reliability metrics, and ReWOO is the rational choice for cost-

**Bottom line:** The empirical evidence consistently shows that simpler architectures outperform complex ones at production scale: ReAct beats Reflexion under stress conditions, Plan-Execute dominates Reflexion on cost-normalized and reliability metrics, and ReWOO is the rational choice for cost-sensitive deterministic workloads. The dominant benchmark (SWE-Bench) is demonstrably inflated—19.78% of "solved" patches are semantically incorrect—and pass@1 overestimates production reliability by 20-40%. Only 5-10% of enterprises successfully scale AI agents to production, with tool-calling accuracy and coordination overhead as the primary failure modes, not reasoning capability. The defensible recommendation is to default to ReAct for dynamic tasks with ≤5 tool steps, Plan-Execute for structured multi-step workflows, CodeAct/CodeDelegator for code-intensive tasks, domain-tuned models for high-volume narrow workflows, and reserve multi-agent orchestration for tasks that exceed single-context capacity—always measuring with pass@k and CLEAR dimensions rather than pass@1 accuracy.

# Tool-Use Agent Architecture Patterns at Production Scale: Evidence-Based Analysis

## 1. The Benchmark Inflation Problem: Why Published Numbers Mislead

Before comparing architectures, the evaluation landscape must be understood clearly. A convergent body of evidence shows that published benchmark figures dramatically overstate production-grade reliability.

### SWE-Bench Saturation Is an Artifact

SWE-Bench Verified, the dominant benchmark for coding agents, shows the top system achieving 78.80% resolve rate — apparently near saturation. But SWE-ABS's adversarial re-evaluation found that **19.78% of accepted patches (2,184/11,041) are semantically incorrect**, inflating scores by appearing to pass weak test suites [source-80c497f46e2c]. After adversarial strengthening, the top agent (TRAE + Doubao-Seed-Code) drops from 78.80% to 62.20%, plunging from 1st to 5th place. The full top-30 leaderboard sees 30 rank changes.

Critically, this is not a modeling artifact. Analysis of 100 rejected patches found **47% logic errors and 35% incomplete fixes** — agents systematically produce "shallow" solutions that satisfy test execution without achieving semantic completeness [source-80c497f46e2c]. This behavior is rationalized by training pipelines that optimize for test-passing reward signals. A counterintuitive finding: **task difficulty and test discriminativeness are orthogonal** — the harder SWE-Bench Pro benchmark (45.89% for top agent) is equally amenable to adversarial strengthening, achieving a comparable 16.46 percentage-point average drop.

### The pass@1 Illusion

ReliabilityBench's 1,280-episode study shows that **pass@1 overestimates production reliability by 20-40%** [source-741a83ef08bb]. Agents achieving 96.9% pass@1 drop to 88.1% under perturbations alone (8.8% decline). The CLEAR framework independently confirmed that pass@1 ranges from 68-74% across architectures, while 8-run consistency (pass@8) drops to **52-73%** — a drop as severe as 19.4 percentage points for ReAct-GPT4 [source-a348020a4683]. This directly contradicts the practice of reporting single-run success on clean data as a proxy for production readiness.

---

## 2. Head-to-Head Architecture Comparisons: What the Data Shows

### ReAct vs. Reflexion Under Stress

ReliabilityBench is the most rigorous head-to-head study: two architectures (ReAct, Reflexion), two models (Gemini 2.0 Flash, GPT-4o), four domains, 1,280 episodes under chaos engineering conditions (rate limiting, schema drift, partial responses, perturbations).

**ReAct outperforms Reflexion** on the unified 3D reliability surface:
- ReAct: surface volume = 0.900 (pass@1=97.5%, pass@2=90.0%)
- Reflexion: surface volume = 0.875 (pass@1=96.3%, pass@2=86.3%)
- **Reflexion's fault degradation gradient is steeper** than ReAct's — self-reflection mechanisms *amplify* rather than mitigate fault impacts [source-741a83ef08bb]
- ReAct fault recovery: 80.9%; Reflexion: 67.3%
- **Rate limiting causes the largest single reliability impact** (2.5% below mixed baseline), and Reflexion's complex retry logic handles it worse

The explanation is structural: Reflexion's reflection loops add additional LLM calls that are themselves subject to failure, creating compounding failure modes. This **"complexity penalty under stress"** is a consistent empirical finding.

### CLEAR Framework: Six Architectures on 300 Enterprise Tasks

The CLEAR framework paper [source-a348020a4683] is the most comprehensive multi-architecture comparison with enterprise tasks:

| Agent | Efficacy (%) | Cost ($) | CNA | Latency (s) | PAS | pass@8 (%) |
|---|---|---|---|---|---|---|
| ReAct-GPT4 | 72.3 | 2.87 | 25.2 | 8.4 | 0.89 | 58.3 |
| ReAct-GPT-o3 | 68.7 | 0.31 | 221.6 | 4.2 | 0.85 | 52.1 |
| **Reflexion** | **74.1** | **5.12** | **14.5** | **12.7** | 0.91 | 61.2 |
| **Plan-Execute** | 71.9 | 1.24 | **58.0** | 6.8 | 0.88 | **64.5** |
| ToolFormer | 69.5 | 1.89 | 36.8 | 5.9 | 0.82 | 55.7 |
| **Domain-Tuned** | 70.3 | **0.27** | **260.4** | **3.8** | **0.93** | **72.8** |

*(CNA = cost-normalized accuracy; PAS = policy adherence score)*

**Key findings:**
- Reflexion achieves highest raw efficacy (74.1%) but is **Pareto-dominated by Plan-Execute** on every enterprise-relevant dimension: 4.1x cheaper, more reliable (pass@8: 64.5% vs 61.2%), and faster (6.8s vs 12.7s total) [source-a348020a4683]
- **Domain-tuned models achieve the best overall enterprise profile**: best CNA (260.4 vs 58.0 for Plan-Execute), best pass@8 (72.8%), lowest cost ($0.27), and best policy adherence (PAS 0.93) — all using a 70B parameter model vs GPT-4's rumored 1.7T
- Plan-Execute is the Pareto-efficient general-purpose architecture for organizations without domain-tuning capability
- **CLEAR predicts production success with r=0.83** (expert validation, N=15); accuracy alone predicts with r=0.41 [source-a348020a4683]
- There are **50x cost variations for similar accuracy** across architectures, demonstrating that accuracy-centric evaluation is fundamentally misleading

**Cost breakdown** for Reflexion: up to 2,000 API calls for iterative refinement, 89.4K input tokens vs 38.6K for Plan-Execute. The reflection phase alone adds 3.2s and $1.88 per task on average [source-a348020a4683].

### ReWOO vs ReAct: The Token Efficiency Trade-off

ReWOO (Reasoning Without Observation) decouples planning from execution: a Planner generates all steps upfront using variables for unknown intermediate results (e.g., `#E1 = Search['query']`), a Worker executes them, and a Solver synthesizes the final answer — **without any LLM calls during execution** [source-75d1d99b6a90].

Empirical results:
- **5x token efficiency and 4% accuracy improvement over ReAct on HotpotQA** [source-75d1d99b6a90]
- ReWOO achieves 42.4% vs ReAct's 40.8% on HotpotQA with GPT-3.5, while using ~5x fewer tokens
- The decoupling enables fine-tuning the planner from 175B GPT-3.5 into 7B LLaMA with minimal accuracy loss
- **Critical limitation**: ReWOO is fragile — if the plan requires a tool output that the planner failed to anticipate, recovery is difficult. The capabl.in comparison notes "5-10x token reduction but brittle" [source-325e6c9773da]

The ADaPT hybrid approach (NAACL 2024) is the compelling resolution: trigger decomposition only when the executor fails, rather than always upfront. ADaPT achieves 28.3%, 27%, and 33% improvement over baselines on ALFWorld, WebShop, and TextCraft [source-9ab43874224d].

### CodeAct vs ReAct: Code as a Unified Action Space

CodeAct (ICML 2024) replaces JSON tool calls with executable Python code, enabling control flow, variable reuse, and multi-tool composition in a single action. It achieves **up to 20% higher success rate and 30% fewer actions on complex multi-tool tasks** vs JSON-format ReAct [source-ddced5591da2].

CodeDelegator extends this with role separation: a persistent Delegator handles strategic planning while ephemeral Coders implement sub-tasks in isolated contexts, addressing context pollution. Results: **38.4% on MCPMark vs 25.8% (ReAct) / 26.4% (CodeAct)**, and **82.0% on τ-bench Retail vs 79.6% (ReAct) / 70.2% (CodeAct)** [source-b793ce7ff712].

### Multi-Agent Orchestration: When It Helps and When It Hurts

AWS research documents multi-agent systems achieving **90% goal success rates vs 53-60% for single agents** with proper coordination — but a **37% performance gap between lab tests and production** [source-a348020a4683].

Beam.ai's production orchestration analysis provides quantified coordination overhead [source-5e174290b618]:
- **Fan-out/Fan-in** patterns boost parallel tasks by ~81% but can reduce sequential performance by ~70%
- **Sequential pipelines** add 300-500ms per agent hop
- **Multi-agent debate** provides quality improvements but requires 3-5x more compute

The economic reality from production case studies is sobering [source-f3d1588a2e4a]:
- 3-5x token amplification for multi-agent vs single-agent
- 4.8-second latency penalty for 3-agent systems
- 3.7x Mean-Time-To-Recovery increase
- 4x engineering overhead vs single agents
- A documented $47K/month mistake from premature multi-agent deployment

**When multi-agent genuinely wins**: tasks exceeding single-context capacity, genuinely parallelizable sub-problems, specialized expertise requirements per subtask, and high-volume workflows where specialization ROI exceeds coordination costs [source-f3d1588a2e4a]. When it doesn't: tasks with sequential dependencies, latency-sensitive applications, or simple workloads where orchestration overhead dominates.

---

## 3. The CLEAR Framework: Five Dimensions That Actually Matter

The CLEAR framework (Cost, Latency, Efficacy, Assurance, Reliability) operationalizes the multi-dimensional nature of production requirements [source-a348020a4683]:

**Cost (C)**: Cost-Normalized Accuracy (CNA = Efficacy / Cost per task). Domain-Tuned achieves CNA 260.4 vs Reflexion's 14.5 — an 18x difference at comparable accuracy levels.

**Latency (L)**: SLA compliance rates by domain:
- Customer support SLA (3s): All architectures compliant
- Software development SLA (30s): Plan-Execute violates on 23% of tasks; Reflexion on 34%
- Domain-tuned models complete planning in 0.9s vs Reflexion's 3.4s

**Efficacy (E)**: Domain-specific variation is significant:
- Software development: ReAct-GPT4 best (73.3%)
- Compliance tasks: Domain-Tuned best (72.5%), 7.5 points above ReAct
- Multi-stakeholder workflows: lowest for all (<69%), highlighting fundamental coordination limits

**Assurance (A)**: Policy adherence scores reveal security posture:
- Domain-Tuned: PAS 0.93 (8% successful prompt injection attacks)
- ToolFormer: PAS 0.82 (18% successful attacks)
- Compliance tasks require "zero tolerance for policy violations" — PAS 0.82 is unacceptable

**Reliability (R)**: pass@8 as production proxy:
- Production requirement for mission-critical apps: pass@8 ≥ 80%
- Best available: Domain-Tuned 72.8% (still below threshold)
- ReAct-GPT4: 58.3% — effectively 2-in-5 chance of consecutive failure over 8 runs

---

## 4. Enterprise Adoption Failure Rates: Why Production Deployments Fail

The adoption statistics reveal a structural crisis [source-ec090ce34eb9]:
- **85% of companies experiment with generative AI**, but **only 5-10% successfully deploy agents in production** [source-a348020a4683, source-ec090ce34eb9]
- 95% of organizations report **little to no measurable ROI** despite $30-40B in enterprise investment [source-ec090ce34eb9]
- Trust in fully autonomous AI agents has **declined to 27% from 43%** in one year as real-world risks become apparent
- Fewer than 20% of organizations have high data readiness; over 80% lack mature AI infrastructure

**Root causes** (from CLEAR framework analysis and enterprise surveys):
1. **Evaluation misalignment**: Lab accuracy (60-74%) masks production brittleness (pass@8: 52-73%). A 37% performance gap from lab to production is documented [source-a348020a4683]
2. **Tool-calling accuracy**: The dominant production failure mode is inaccurate tool invocation, not reasoning. Vanilla ReAct wastes 90.8% of retries on tool-name hallucinations that can never succeed [source-97b7d4aebe6c]
3. **Coordination overhead**: Multi-agent systems introduce exponential failure surfaces — sequential pipeline token growth, state synchronization failures
4. **Rate limiting**: The single largest reliability failure driver, causing 2.5% degradation below mixed baseline [source-741a83ef08bb]
5. **Context pollution**: Cumulative debug traces degrade CodeAct performance over long tasks, resolved by CodeDelegator's EPSS architecture [source-b793ce7ff712]
6. **Benchmark gaming**: SWE-Bench "saturation" represents shallow test-passing optimization, not genuine problem-solving capability [source-80c497f46e2c]

Organizations partnering with external vendors/integrators show **2x higher success rates** vs internal-only builds [source-ec090ce34eb9].

---

## 5. Task-Complexity Thresholds: Where Each Pattern Wins or Loses

Based on the convergent empirical evidence:

### ReAct: Low-to-Medium Complexity, Dynamic Tasks
**Wins when**: ≤5 tool steps, environment state is highly dynamic and unpredictable, correction based on real-time feedback is essential, latency tolerance ≤8s, low fault injection risk
**Loses when**: tasks have predictable structure (wasted reflective overhead), API rate limits are frequent (compound failure modes), tasks exceed 10 steps (context bloat)
**Reliability ceiling**: pass@8 ~58-65% in general enterprise settings

### Plan-Execute (ReWOO/hierarchical): Structured Multi-Step Workflows
**Wins when**: workflow is decomposable into predictable sub-tasks, cost efficiency is critical, parallel execution is possible, token budget is constrained
**Key advantage**: 5x token efficiency vs ReAct (ReWOO data), Pareto-optimal on CLEAR vs Reflexion despite similar accuracy [source-75d1d99b6a90, source-a348020a4683]
**Loses when**: mid-task plan revision is necessary (upfront planning fails if tool output is unexpected), dynamic environments require real-time adaptation
**Recommendation threshold**: workflows with ≥3 independently executable sub-tasks, structured data access

### Reflexion: Only When Oracle Feedback Is Available and Cost Is Secondary
**Wins when**: verifiable outcome signals exist (code test suites, factual ground truth), the task benefits from iterative refinement over multiple episodes (not within episodes), and cost is not a constraint
**Critical limitations**: 4.1x cost premium over Plan-Execute with marginal accuracy gain (74.1% vs 71.9%), steeper fault degradation, no advantage in production reliability [source-a348020a4683]
**NeurIPS 2023 results**: 91% pass@1 on HumanEval (vs GPT-4's 80%), +22% on AlfWorld, +20% on HotPotQA — but these are best-case with oracle feedback [source-b4229b3e9dba]
**Strong model paradox**: stronger models (DeepSeek, 94% accuracy) achieve *lower* intrinsic self-correction rates (16.7%) than weaker models [source-5d5fc2c07bb2]

### CodeAct/CodeDelegator: Code-Intensive Tasks
**Wins when**: tasks involve multi-step code operations, control flow, variable reuse, or cross-tool composition
**Key threshold**: complex multi-tool tasks with ≥3 chained operations; CodeAct achieves 20% higher success and 30% fewer actions than JSON-format ReAct [source-ddced5591da2]
**Limitation**: context pollution for long tasks; CodeDelegator resolves this via role separation [source-b793ce7ff712]

### Multi-Agent Orchestration: Only for Genuinely Parallel, Large-Scope Tasks
**Wins when**: task scope exceeds single-context capacity, sub-tasks require genuinely different expertise, parallelism is available, and volume justifies 3-5x token amplification overhead
**Loses when**: tasks are sequential, time-sensitive, or when coordination bugs create 3.7x MTTR penalty
**AWS-documented threshold**: multi-agent achieves 90% goal success on complex coordination vs 53-60% single-agent — but with that 37% lab-to-production gap [source-a348020a4683]

### Domain-Tuned Models: High-Volume Narrow Workflows
**Wins decisively when**: narrow domain, high volume, policy compliance critical, cost sensitivity paramount
**CLEAR result**: CNA 260.4 (vs 58.0 Plan-Execute), pass@8 72.8% (highest), PAS 0.93, cost $0.27/task — at 70B parameter scale [source-a348020a4683]
**Barrier**: requires sufficient domain data and fine-tuning investment upfront

---

## 6. Evidence-Based Recommendations

### For Architecture Selection

1. **Default to ReAct for exploratory/dynamic tasks** where environment feedback is essential and steps ≤5. Use error classification (not global retry counters), per-tool circuit breakers, and explicit tool routing to reduce the 90.8% wasted-retry failure mode [source-97b7d4aebe6c].

2. **Choose Plan-Execute (ADaPT variant) for structured enterprise workflows** with ≥3 predictable steps. This is the Pareto-efficient choice — 4.1x cheaper than Reflexion with superior reliability and comparable accuracy. Use a stronger model for the planner (15% of tokens) and a cheaper model for the executor (85% of tokens) [source-a348020a4683].

3. **Avoid Reflexion as a first-choice production architecture**. Its cost structure (4.1x vs Plan-Execute), SLA violations on 34% of software dev tasks (30s threshold), and complexity-amplified fault degradation make it unsuitable for most production workloads. Reserve for iterative refinement across *episodes* with oracle feedback, not within episodes [source-a348020a4683, source-741a83ef08bb].

4. **Use CodeAct or CodeDelegator for code-heavy tasks** requiring multi-step compositions. For tasks with long trajectories, CodeDelegator's role separation outperforms both ReAct and CodeAct by 12-20+ points [source-b793ce7ff712].

5. **Invest in domain-tuning for high-volume narrow workflows**. The 18x CNA advantage and best pass@8 make this the clearly superior choice when the volume justifies the investment [source-a348020a4683].

6. **Use multi-agent orchestration selectively** — only when tasks genuinely exceed single-context scope or require parallelism. Build with fan-out/fan-in patterns for parallelism; use sequential pipelines with explicit state management; avoid debate patterns unless quality outweighs compute [source-5e174290b618].

### For Evaluation

7. **Replace pass@1 with pass@k evaluation** (minimum k=5, ideally k=8). A 70% agent with 70% pass@8 is more deployable than an 80% agent with 35% pass@8 [source-a348020a4683].

8. **Adopt CLEAR-style multi-dimensional evaluation** before production deployment. CLEAR's r=0.83 correlation with expert deployment readiness vs r=0.41 for accuracy alone makes it the only defensible evaluation framework for production decisions [source-a348020a4683].

9. **Distrust SWE-Bench Verified scores above ~62%** as indications of genuine capability. The 19.78% semantic incorrectness rate means current top-reported scores of 78-79% reflect roughly 62-65% actual correctness [source-80c497f46e2c].

10. **Inject chaos** (rate limiting, schema drift, partial responses) in pre-production testing. Rate limiting alone degrades reliability by 2.5%; without chaos testing, lab-to-production gaps of 37% are expected [source-741a83ef08bb].

### For Enterprise Deployment

11. **Accept that only ~10% of enterprise AI agent deployments succeed at scale**. The failure causes are infrastructure readiness, tool-calling accuracy, and governance — not model capability [source-a348020a4683, source-ec090ce34eb9]. Address these first.

12. **Add explicit retry classification** (not global counters) to any ReAct deployment. Categorize tool failures as retryable (transient timeouts), structural (tool-name hallucinations), or terminal (schema drift), and respond accordingly [source-97b7d4aebe6c].

13. **Implement Memory-as-a-Tool** as the cost-effective alternative to Reflexion when cross-episode learning is needed: convert transient critiques into persistent file-based memory guidelines that cost-comparably match per-instance self-critique quality [source-eda8a66f33e2].

---

## 7. Open Issues and Genuine Disagreements

**Disagreement**: Whether Reflexion is ever worth the cost in production. The CLEAR framework says no (Pareto-dominated); fault localization research [source-885b48ff3df8] shows Reflexion +11% on structured code debugging. The resolution: Reflexion helps in narrow, verifiable-feedback domains; it is harmful in general-purpose dynamic environments.

**Open question**: How much of the 37% lab-to-production gap is addressable through better engineering vs fundamental architectural limitation. Current evidence cannot fully separate these.

**Open question**: Whether reasoning models (o3-class) change the architecture trade-off space by internalizing much of what previously required Reflexion or Plan-Execute loops. Early CLEAR data shows ReAct-GPT-o3 achieves CNA 221.6 at only $0.31/task [source-a348020a4683], suggesting reasoning models may substantially shift the calculus.

**Benchmark limitation**: ReliabilityBench uses synthetic tasks; CodeDelegator τ-bench results are from a single retail domain. Broader multi-domain validation of architectural rankings is needed.


## Sources

- **[source-896e228f0105]** [Agentic Artificial Intelligence (AI): Architectures, Taxonomies, and Evaluation of LLM Agents](https://arxiv.org/html/2601.12560v1) - tier 2
  - Comprehensive 2026 agentic AI taxonomy paper. Positions Reflexion in the cognitive architecture landscape alongside Tree of Thoughts, ReAcTree, reasoning models. Identifies key Reflexion limitations: hallucinated critiques and context overflow. Notes 2024-2025 evolution through CRITIC (tool-interactive validation), Expel (cross-episode rule extraction), and Meta-Policy Reflexion. Frames the reflection space as moving from ephemeral per-episode critique to persistent, generalizable rule systems.
- **[source-636a71e35a60]** [The Orchestration of Multi-Agent Systems: Architectures, Protocols, and Enterprise Adoption](https://arxiv.org/html/2601.13671v1) - tier 1 - peer-reviewed
  - This paper (Huang et al.) demonstrates that LLMs cannot reliably self-correct reasoning without external oracle feedback. In intrinsic self-correction settings, performance consistently degrades across GSM8K, CommonSenseQA, and HotpotQA. Multi-agent debate offers no advantage over self-consistency with equivalent calls. Many prior improvements were artifacts of suboptimal initial prompts or hidden use of oracle labels.
- **[source-98fbed7cd5e5]** [Reinforcement Learning for LLM-based Multi-Agent Systems through Orchestration Traces](https://arxiv.org/html/2605.02801) - tier 2
  - Systematic survey of RL for LLM-based multi-agent orchestration, organized around "orchestration traces." Identifies six system topologies (centralized orchestrator, planner-executor-critic, debate/committee, parallel swarm, hierarchical, harness-based), eight reward families, and five orchestration sub-decisions. Kimi K2.5/K2.6 PARL is identified as the clearest public example of trained orchestration.
- **[source-5047a2b9b961]** [Multi-Agent LLM Orchestration Achieves Deterministic, High-Quality Decision Support for Incident Response](https://arxiv.org/abs/2511.15755) - not-tiered
  - Demonstrates multi-agent orchestration outperforming single-agent approaches for LLM-based incident response; reproducible containerized framework.
- **[source-6808a55dc508]** [Multi-Agent Collaboration via Evolving Orchestration](https://openreview.net/forum?id=L0xZPXT3le) - tier 2
  - Proposes "Puppeteer" paradigm for dynamic multi-agent collaboration where a centralized orchestrator trained via RL adaptively sequences and prioritizes agents in response to evolving task states. Addresses static structure limitations and shows improved performance with reduced computational costs through more compact, cyclic reasoning structures.
- **[source-67f31eaf2b9d]** [AI Agents: Evolution, Architecture, and Real-World Applications (2025)](https://arxiv.org/html/2503.12687) - tier 3
  - Comprehensive AI agent evolution survey covering architectures from rule-based to LLM-integrated agents. Critiques current benchmarks for inadequate holdout sets, focus on accuracy over cost, and methodology that incentivizes overly complex agents. Proposes holistic evaluation frameworks.
- **[source-741a83ef08bb]** [ReliabilityBench: Evaluating LLM Agent Reliability Under Production-Like Stress Conditions](https://arxiv.org/html/2601.06112) - tier 2
  - ReliabilityBench evaluates ReAct vs Reflexion across 1,280 episodes under production-like stress (perturbations, fault injection). Simpler ReAct achieves 2.5% higher reliability surface volume than Reflexion. Pass@1 overestimates production reliability by 20-40%. Rate limiting is the single biggest failure driver. GPT-4o costs 82x more than Gemini 2.0 Flash with no reliability benefit (-0.62% difference).
- **[source-308a90d24e20]** [Reason-Plan-ReAct: A Reasoner-Planner Supervising a ReAct Executor for Complex Enterprise Tasks](https://arxiv.org/html/2512.03560v1) - tier 2
  - The Confidence Matters paper (Li et al., 2024) identifies LLM confidence as the key latent factor missing from self-correction analyses. Introduces If-or-Else (IoE) prompting: if confident, keep answer; if not, revise. Shows intrinsic self-correction is harmful for confident answers but beneficial for unconfident ones. IoE consistently improves over Critical Prompt baseline across 4 models and 6 benchmarks; gains decrease for stronger models.
- **[source-66d4e6de75e5]** [Architecting Resilient LLM Agents: A Guide to Secure Plan-then-Execute Patterns](https://arxiv.org/pdf/2509.08646) - not-tiered
  - Discusses plan-to-execute (P-t-E) pattern where executor can be a simpler/cheaper model or deterministic code. Covers security considerations for agent architectures.
- **[source-07978d2e96f4]** [AI Agent Architecture Patterns: Single & Multi-Agent Systems (Redis Blog)](https://redis.io/blog/ai-agent-architecture-patterns/) - tier 3
  - Redis blog compares single and multi-agent agent architecture patterns. Quantifies ReAct as requiring 5-7 LLM calls per interaction vs planning patterns 3-4 calls. Shows multi-agent boosts parallel tasks 81% but can reduce sequential performance 70%. Notes Reflexion adds 2-3x token cost.
- **[source-9ab43874224d]** [Navigating Modern LLM Agent Architectures (WollenLabs)](https://www.wollenlabs.com/blog-posts/navigating-modern-llm-agent-architectures-multi-agents-plan-and-execute-rewoo-tree-of-thoughts-and-react) - tier 1 - peer-reviewed
  - ADaPT (As-Needed Decomposition and Planning) addresses Plan-and-Execute rigidity by triggering decomposition only when executor fails. Recursively decomposes complex sub-tasks, adapting to both task complexity and executor LLM capability. Achieves 28.3%, 27%, and 33% improvement over baselines on ALFWorld, WebShop, and TextCraft respectively. Published NAACL 2024 Findings.
- **[source-75d1d99b6a90]** [Planner-Executor Agentic Framework (EmergentMind)](https://www.emergentmind.com/topics/planner-executor-agentic-framework) - tier 2
  - ReWOO (Reasoning Without Observation) achieves 5x token efficiency and 4% accuracy improvement over ReAct on HotpotQA by decoupling planning from execution. The planner generates all steps upfront without waiting for observations, enabling knowledge distillation into smaller models.
- **[source-26920bebe49f]** [OPERA: RL-Enhanced Orchestrated Planner-Executor Architecture for Multi-Hop Retrieval](https://arxiv.org/html/2508.16438) - tier 2
  - OPERA is a planner-executor architecture with RL (MAPGRPO) training, using a Goal Planning Module (GPM) for decomposition and a Reason-Execute Module (REM) for retrieval/reasoning. Achieves state-of-the-art on HotpotQA (57.3% EM), 2WikiMultiHopQA (60.2%), and Musique (39.7%), representing +11-16% improvement over best baselines. Architecture ablations show Plan Agent removal causes catastrophic drops.
- **[source-8825254258f5]** [Small LLMs Are Weak Tool Learners: A Multi-LLM Agent (2024)](https://arxiv.org/html/2401.07324) - not-tiered
  - Shows smaller models fail at tool use; proposes splitting task planning, tool invocation, and summarization across multiple LLMs of varying capability.
- **[source-325e6c9773da]** [Agentic AI Design Patterns: ReAct, ReWOO, CodeAct, and Beyond](https://capabl.in/blog/agentic-ai-design-patterns-react-rewoo-codeact-and-beyond) - tier 3
  - Comprehensive comparison of ReAct, ReWOO, and CodeAct patterns with trade-off analysis. ReWOO reduces tokens 5-10x but is fragile. CodeAct enables self-debugging via error tracebacks but incurs security risks and heavy context from debug traces (addressed by CodeDelegator).
- **[source-58600d80b605]** [Multi-Agent Systems & AI Orchestration Guide 2026 (Codebridge)](https://www.codebridge.tech/articles/mastering-multi-agent-orchestration-coordination-is-the-new-scale-frontier) - not-tiered
  - Five-step enterprise blueprint; describes four established workflow patterns for production agents. Addresses coordination overhead as the new scale frontier.
- **[source-cbbd9f6b5271]** [Customize agent workflows with advanced orchestration techniques using Strands Agents (AWS)](https://aws.amazon.com/blogs/machine-learning/customize-agent-workflows-with-advanced-orchestration-techniques-using-strands-agents/) - tier 3
  - AWS blog detailing Strands Agents SDK and three orchestration patterns: ReAct (default, lowest latency), ReWOO (plan-execute-synthesize for governance), and Reflexion (iterative self-critique for multi-constraint decisions). Includes empirical benchmarks showing latency-accuracy trade-offs. Strands supports ReWOO via GraphBuilder DAG execution model.
- **[source-d38147694b11]** [Towards AI Search Paradigm (2025)](https://arxiv.org/html/2506.17188) - not-tiered
  - Modular architecture with Master, Planner, Executor, Writer agents for AI search. Dynamically adapts to query complexity. 17 citations.
- **[source-97b7d4aebe6c]** [Your ReAct Agent Is Wasting 90% of Its Retries — Here's How to Stop It (TDS)](https://towardsdatascience.com/your-react-agent-is-wasting-90-of-its-retries-heres-how-to-stop-it/) - tier 4
  - This article identifies that 90.8% of retries in a naive ReAct agent are "wasted" on tool-name hallucinations that can never succeed. It benchmarks a vanilla ReAct pattern vs. a controlled workflow across 200 tasks, showing structural failure modes in global retry counters, lack of error taxonomy, and runtime tool-name resolution. Three fixes are proposed: error classification, per-tool circuit breakers, and deterministic tool routing.
- **[source-7488034c8eb8]** [Reddit: Are we building AI agents wrong? ReAct is becoming a bottleneck (r/AI_Agents)](https://www.reddit.com/r/AI_Agents/comments/1sczdh8/are_we_building_ai_agents_wrong_react_is_becoming/) - not-tiered
  - Community discussion on ReAct's sequential bottleneck, context window exhaustion as retrieval failure, and architectural alternatives.
- **[source-5d5fc2c07bb2]** [Decomposing LLM Self-Correction: The Accuracy-Correction Paradox and Error Depth Hypothesis](https://arxiv.org/html/2601.00828) - tier 2
  - Proposes a decomposition framework separating self-correction into error detection, localization, and correction. Discovers the Accuracy-Correction Paradox: stronger models (DeepSeek, 94% accuracy) achieve lower intrinsic correction rates (16.7%) than weaker models (GPT-3.5, 26.8%; Claude, 29.1%). Proposes Error Depth Hypothesis: stronger models make deep setup/logic errors that resist self-correction. Counterintuitively, model-generated location hints hurt all models.
- **[source-0f104aeeccc8]** [Agent2Agent (A2A) Protocol — Official Documentation](https://a2a-protocol.org/latest/) - not-tiered
  - Open standard for AI agent communication and collaboration. Originally developed by Google, donated to Linux Foundation. Includes Agent Card capability discovery.
- **[source-3f6f323355fe]** [Announcing the Agent2Agent Protocol (A2A) — Google Developers Blog](https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/) - tier 3
  - TrueFoundry comparison of MCP and A2A protocols, explaining MCP as client-server tool integration layer and A2A as peer-to-peer agent collaboration standard. Covers key features, architectural differences, and when to use each, plus enterprise integration strategies using both protocols together.
- **[source-ddced5591da2]** [Executable Code Actions Elicit Better LLM Agents (CodeAct, ICML 2024)](https://arxiv.org/html/2402.01030) - tier 1 - peer-reviewed
  - CodeAct proposes using executable Python code as unified action space instead of JSON/text tool calls, enabling control flow, variable reuse, and multi-tool composition. Achieves up to 20% higher success rate and 30% fewer actions on complex multi-tool tasks (M3ToolEval). Demonstrates code actions enable self-debugging through automated feedback (error tracebacks).
- **[source-b793ce7ff712]** [CodeDelegator: Mitigating Context Pollution via Role Separation in Code-as-Action Agents (2026)](https://arxiv.org/html/2601.14914) - tier 2
  - CodeDelegator addresses context pollution in code-as-action agents via role separation: a persistent Delegator handles strategic planning while ephemeral Coders implement sub-tasks in isolated contexts. Introduces Ephemeral-Persistent State Separation (EPSS). Outperforms both ReAct and CodeAct: 38.4% on MCPMark vs 25.8%/26.4%, and 82.0% on τ-bench Retail vs 79.6%/70.2%.
- **[source-3cbadea07722]** [Enhancing LLM-Based Agents via Global Planning and Hierarchical Execution (2025)](https://arxiv.org/html/2504.16563) - not-tiered
  - Addresses lack of clear global goals causing agents to get stuck in local branches. Proposes hierarchical execution balancing complexity and stability.
- **[source-20049505b820]** [AgentTrust: Runtime Safety Evaluation and Interception for AI Agent Tool Use (2026)](https://arxiv.org/html/2605.04785) - not-tiered
  - Runtime safety layer intercepting agent tool calls (file ops, shell commands, HTTP requests, DB queries). Addresses incomplete defenses in post-hoc benchmarks and static guardrails.
- **[source-eda8a66f33e2]** [Distilling Feedback into Memory-as-a-Tool (2026)](https://arxiv.org/html/2601.05960) - tier 2
  - Proposes Memory-as-a-Tool: converts transient Reflexion-style critiques into persistent file-based memory guidelines via LLM tool calls. After learning, the model reads these guidelines at inference time, achieving comparable quality to expensive per-instance self-critique but at much lower cost. Tests on Rubric Feedback Bench across Claude Sonnet, GPT-5.1, Gemini 3 Pro. Addresses the fundamental cost and forgetting problem of Reflexion.
- **[source-e3ab13216036]** [A Plan Reuse Mechanism for LLM-Driven Agent (2025)](https://arxiv.org/html/2512.21309) - not-tiered
  - Plan reuse mechanism for LLM agents to reduce latency; ~30s planning overhead motivates caching/reuse. Real-world dataset from IoT assistants.
- **[source-3a65eb0417b5]** [Model Context Protocol — Wikipedia](https://en.wikipedia.org/wiki/Model_Context_Protocol) - tier 2
  - Survey comparing MCP, ACP, A2A, and ANP protocols across interaction modes, discovery mechanisms, communication patterns, and security models. Provides phased adoption roadmap starting with MCP for tool access, progressing through A2A for collaborative task execution, and extending to ANP for decentralized agent marketplaces. Covers evolution from KQML (1993) to modern protocols.
- **[source-2b4a286c098c]** [Introducing the Model Context Protocol (Anthropic)](https://www.anthropic.com/news/model-context-protocol) - not-tiered
  - Anthropic's original MCP announcement; early adopters include Block and Apollo. Open protocol for LLM applications to discover/invoke external tools.
- **[source-6aff1ea17b34]** [MCP Tool Descriptions Are Smelly: Towards Improving AI Agent Efficiency with Augmented MCP Tool Descriptions](https://arxiv.org/html/2602.14878v1) - not-tiered
  - Analyzes MCP tool descriptions for quality issues. Discusses how MCP standardizes tool discovery/invocation via client-server protocol, reducing custom glue code.
- **[source-807073627121]** [CrewAI vs LangGraph vs AutoGen: Choosing the Right Multi-Agent AI Framework (DataCamp)](https://www.datacamp.com/tutorial/crewai-vs-langgraph-vs-autogen) - not-tiered
  - DataCamp comparison of CrewAI, LangGraph, AutoGen on workflows, memory, scalability, and collaboration modes.
- **[source-193830c8dc2c]** [Best Multi-Agent Frameworks in 2026: LangGraph, CrewAI & More (Gurusup)](https://gurusup.com/blog/best-multi-agent-frameworks-2026) - tier 3
  - 2026 framework comparison covering LangGraph, CrewAI, OpenAI Agents SDK, AutoGen/AG2, Google ADK, and Claude Agent SDK. LangGraph leads in searches (27,100/month), CrewAI follows (14,800). Includes detailed analysis of orchestration models, state persistence, model dependency, production readiness, and unique strengths.
- **[source-960e8326cd75]** [Comprehensive comparison of every AI agent framework in 2026 (Reddit r/LangChain)](https://www.reddit.com/r/LangChain/comments/1rnc2u9/comprehensive_comparison_of_every_ai_agent/) - not-tiered
  - Reddit compilation of 25+ agent frameworks in 2026 across general-purpose vs. multi-agent categories: LangGraph, CrewAI, AutoGen, MetaGPT, OpenAI Agents SDK, Google ADK, Mastra, CAMEL, Strands.
- **[source-10005630b0d1]** [Architecting efficient context-aware multi-agent framework for production (Google Developers Blog)](https://developers.googleblog.com/architecting-efficient-context-aware-multi-agent-framework-for-production/) - not-tiered
  - Google Developers Blog: production context-aware multi-agent framework for long-horizon tasks (workflow automation, deep research, codebase management).
- **[source-654d0a02d8b3]** [Effective harnesses for long-running agents (Anthropic Engineering)](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) - not-tiered
  - Anthropic engineering: Claude Agent SDK with context compaction for long-running agents. Discusses effective harness design for tool-using agents.
- **[source-6b95743a7d0b]** [Agentic Long-Context Reasoning (EmergentMind)](https://www.emergentmind.com/topics/agentic-long-context-reasoning) - not-tiered
  - Emergent Mind topic page tracking agentic long-context reasoning: tool/environment integration, contextual memory, evolving playbooks, self-improvement strategies.
- **[source-80c497f46e2c]** [SWE-ABS: Adversarial Benchmark Strengthening Exposes Inflated Success Rates (2026)](https://arxiv.org/html/2603.00520) - tier 2
  - SWE-ABS reveals SWE-Bench Verified benchmark inflation: 19.78% of accepted patches are semantically wrong, top agent drops 16.6 points after adversarial testing, and 30/30 rank changes occur. Difficulty and test strength are orthogonal - harder benchmarks don't automatically provide better discrimination.
- **[source-0981aec010b2]** [Autonomous Agents (LLMs) Research Papers — GitHub (tmgthb)](https://github.com/tmgthb/Autonomous-Agents) - not-tiered
  - GitHub repo: daily-updated list of autonomous agent research papers. Tracks scalability limits in multi-step agentic workflows, horizon reduction techniques for RL training.
- **[source-a4df998cc387]** [ReAct: Synergizing Reasoning and Acting in Language Models (Yao et al. 2022)](https://arxiv.org/html/2210.03629) - not-tiered
  - Original ReAct paper (Yao et al., 2022/2023): interleaved reasoning traces and task-specific actions, enabling dynamic plan updating and exception handling. Foundational baseline architecture.
- **[source-b4229b3e9dba]** [Reflexion: Language Agents with Verbal Reinforcement Learning (Shinn et al. 2023)](https://arxiv.org/html/2303.11366) - tier 1 - peer-reviewed
  - Reflexion (Shinn et al., NeurIPS 2023) introduces verbal reinforcement learning for LLM agents. Instead of weight updates, agents convert task feedback into verbal reflections stored in episodic memory, enabling improvement across trials. Demonstrated 91% pass@1 on HumanEval (surpassing GPT-4's 80%), +22% on AlfWorld, +20% on HotPotQA. Core architecture: Actor, Evaluator, Self-Reflection model. Memory is bounded to 1-3 reflections due to context limits.
- **[source-f285051aa21b]** [Robust Verbal Reinforcement Learning for Language Agents (2025)](https://doi.org/10.1109/ISAICS66888.2025.11350204) - tier 2
  - Meta-Policy Reflexion (MPR) converts episodic Reflexion traces into a structured Meta-Policy Memory (MPM) of predicate-style rules, addressing the cross-task memory problem. Uses soft guidance (memory-conditioned decoding) + hard admissibility checks (domain constraint enforcement). On AlfWorld: MPR reaches 100% accuracy on training set by round 3 vs. Reflexion's 87.2%, and generalizes better to held-out tasks (87.8% vs 86.9%) in a single pass vs six rounds.
- **[source-885b48ff3df8]** [A Multi-Agent Approach to Fault Localization via Graph-Based Retrieval and Reflexion (2024)](https://arxiv.org/html/2409.13642) - tier 2
  - LLM4FL demonstrates Reflexion-style verbal RL applied to multi-agent fault localization. Three-agent system (Context Extractor, Debugger, Reviewer) uses graph-based retrieval and Reflexion-inspired iterative critique. Removing the Reflexion component reduces Top-1 accuracy by 11%. Achieves 18.55% improvement over AutoFL. Notably, Reflexion still helps even without an external oracle, suggesting self-critique adds value in structured code debugging contexts.
- **[source-5e174290b618]** [6 Multi-Agent Orchestration Patterns for Production (2026) (Beam.ai)](https://beam.ai/agentic-insights/multi-agent-orchestration-patterns-production) - tier 3
  - Describes six production multi-agent orchestration patterns: orchestrator-worker, sequential pipeline, fan-out/fan-in, multi-agent debate, dynamic handoff, and adaptive planning. Provides specific quantitative data on coordination overhead and failure modes for each pattern.
- **[source-f3d1588a2e4a]** [Multi-Agent Orchestration Economics: When Single Agents Win 2026 (Iterathon)](https://iterathon.tech/blog/multi-agent-orchestration-economics-single-vs-multi-2026) - tier 4
  - Economic analysis of multi-agent orchestration costs with real production case study (a $47K/month mistake). Identifies 3-5x token amplification, 4.8-second latency penalty for 3-agent systems, 3.7x MTTR increase, and 4x engineering overhead vs single agents. Provides volume-based decision framework for when multi-agent ROI is positive.
- **[source-a348020a4683]** [Beyond Accuracy: CLEAR Framework for Evaluating Enterprise Agentic AI Systems](https://arxiv.org/html/2511.14136v1) - tier 2
  - CLEAR framework (Cost, Latency, Efficacy, Assurance, Reliability) evaluated 6 agent architectures on 300 enterprise tasks. Key finding: Reflexion (74.1% efficacy) costs 4.1x more than Plan-Execute (71.9%) with lower reliability (pass@8: 61.2% vs 64.5%). Only 10% of enterprises successfully deploy agents in production. Domain-tuned models achieve best cost-normalized accuracy (260.4 CNA) and reliability (72.8% pass@8). Expert validation shows CLEAR predicts production success with r=0.83 vs r=0.41 for accuracy alone.
- **[source-c3bc3c73c288]** [Multi-Agent Frameworks Benchmark: Challenges & Strengths (AIMultiple)](https://aimultiple.com/multi-agent-frameworks) - tier 3
  - AIMultiple benchmark of five frameworks across 750 runs and three tasks of increasing complexity. LangGraph and LangChain show best efficiency in single-agent mode; CrewAI shows exponential token growth with sequential pipelines; AutoGen consumes more tokens due to conversation history but uses GroupChatManager to avoid worst-case growth; Swarm fails at complex multi-step chains (0% accuracy by Task 3).
- **[source-ec090ce34eb9]** [Benchmarking Multi-Agent AI: Insights & Practical Use (Galileo)](https://galileo.ai/blog/benchmarks-multi-agent-ai) - tier 3
  - Compilation of enterprise AI agent adoption statistics showing that only 5% of organizations reach full production with material impact; 95% report no measurable ROI; trust in autonomous agents declining; data and infrastructure readiness are primary constraints

