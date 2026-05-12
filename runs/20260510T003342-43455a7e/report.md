# Research report

**Query:** How have tool-use agent architectures evolved between 2024 and late 2026? Compare ReAct, reflexion-style self-critique, planner-executor splits, and modern multi-agent orchestration patterns. Which patterns hold up at scale?

# Research report

**Query:** How have tool-use agent architectures evolved between 2024 and late 2026? Compare ReAct, reflexion-style self-critique, planner-executor splits, and modern multi-agent orchestration patterns. Which patterns hold up at scale?

## Partial report (reconstructed from sub-agent notes)

_The top-level researcher did not produce a final structured report. The sub-question syntheses below were recovered from the note graph._

### Synthesis: How have single-agent tool-use patterns (ReAct, Reflexion/self-critique, Plan-and-Execute, ReWOO) ev

**Bottom line:** All four patterns (ReAct, Reflexion, Plan-and-Execute, ReWOO) originated in 2022-2023 and remained the dominant vocabulary through late 2026, but each has been substantially stress-tested in production, revealing well-documented failure modes. The 2024-2026 period saw confirmatio

## Overview of the Four Patterns

Four single-agent tool-use patterns define the canonical vocabulary for LLM agents: **ReAct** (Reason+Act, Yao et al. 2022), **Reflexion** (Shinn et al. 2023), **Plan-and-Execute** (related to task decomposition work, 2022-2023), and **ReWOO** (Reasoning WithOut Observation, Xu et al. 2023). By 2024-2026 they remained the dominant architectural building blocks, but their benchmark track records, failure modes, and appropriate use cases were much better characterized.

---

## 1. ReAct (Reason + Act)

**Origin & benchmark baseline.** ReAct was introduced by Yao et al. at ICLR 2023 [source-e9186147171a]. It interleaves Thought → Action → Observation steps in a loop. On HotpotQA and FEVER, it overcame "issues of hallucination and error propagation prevalent in chain-of-thought reasoning by interacting with a simple Wikipedia API." On ALFWorld and WebShop it outperformed imitation/reinforcement learning methods "by an absolute success rate of 34% and 10% respectively, while being prompted with only one or two in-context examples" [source-e9186147171a].

**Production realities discovered 2024-2025.** The core strength — adaptability — is simultaneously its core cost. "Token cost scales linearly with task complexity. Every step requires a full LLM call with the entire conversation history. A 10-step task means 10 LLM calls, each one longer than the last because context accumulates" [source-84e431767d1f]. A 2025 structured benchmark found that "the majority of agents in production today are ReAct loops. Not because ReAct is optimal, but because it's simple, well-supported, and good enough for most use cases" [source-84e431767d1f], underscoring that universal framework support (LangGraph, LangChain, AutoGen) entrenched its role.

**Documented structural failure mode (2025).** An instrumented 200-task benchmark [source-ce0f969cce5c] found that "90.8% of retries were wasted — not because the model was wrong, but because the system kept retrying tools that didn't exist." ReAct's hallucination rate was 155 events across 200 tasks; all were non-retryable. "Standard deviation is 3× higher for ReAct," causing "unpredictable latency (SLAs cannot be committed to), unpredictable token cost (budget forecasts are inaccurate)" [source-ce0f969cce5c]. The root cause was the architectural assumption that the LLM names tools at runtime; the fix — deterministic tool routing via a Python dict — is architecturally distinct from the vanilla pattern.

**2025 successor work.** GAP (Graph-based Agent Planning, NeurIPS 2025) [source-d8016fb06ab8] explicitly names ReAct's key deficiency: "existing paradigms such as ReAct rely on sequential reasoning and execution, failing to exploit the inherent parallelism among independent sub-tasks. This sequential bottleneck leads to inefficient tool utilization and suboptimal performance in multi-step reasoning scenarios." GAP trains agent models with SFT + RL to decompose tasks into dependency graphs enabling parallel execution, and "significantly outperforms traditional ReAct baselines, particularly on multi-step retrieval tasks, while achieving dramatic improvements in tool invocation efficiency through intelligent parallelization" on MHQA datasets [source-d8016fb06ab8].

**AWS τ-Bench evaluation (2025).** On the airline policy-compliance τ-Bench dataset, ReAct won only on simple, unambiguous single-field edits (8s, correct), while "ReAct (17s): Fast but incorrect — claims date change + charge on a Basic Economy fare" in one scenario, and "ReAct (67s): Detailed search and payment plan but changes a date (May 29) and mutates before a clean confirm; conflicts with user constraint" in a complex multi-constraint task [source-0f6e6c1f0f7f]. The pattern consistently skips policy and eligibility checks in higher-stakes scenarios.

---

## 2. Reflexion / Self-Critique

**Origin & benchmark baseline.** Reflexion (Shinn et al., NeurIPS 2023) [source-c60f502757fa] proposed "a novel framework to reinforce language agents not by updating weights, but instead through linguistic feedback. Concretely, Reflexion agents verbally reflect on task feedback signals, then maintain their own reflective text in an episodic memory buffer." The landmark result: "Reflexion achieves a 91% pass@1 accuracy on the HumanEval coding benchmark, surpassing the previous state-of-the-art GPT-4 that achieves 80%" [source-c60f502757fa]. Combined with ReAct on AlfWorld, it completed 130 of 134 tasks [source-84e431767d1f].

**Strengths documented through 2025.** Reflexion is the only single-agent pattern that "gets better on the same task" across retries, because "unlike simply re-running the same prompt (which often produces the same error), Reflexion's verbal memory steers the agent away from previously failed approaches" [source-84e431767d1f]. It wins on multi-constraint, policy-heavy tasks: on τ-Bench, "Reflexion (116s) — follows the user's pre-authorized 'cancel → rebook' path, preserves dates, gives totals, and computes the exact Mastercard remainder" [source-0f6e6c1f0f7f].

**Documented weaknesses.** By 2025, the self-evaluation bottleneck had been rigorously characterized: "A 2025 replication study found that single-agent Reflexion consistently repeats earlier misconceptions across retries because the same model generates both the output and the critique, reinforcing its own blind spots" [source-84e431767d1f]. The latency multiplier is severe: at 116s vs 8-43s for simpler patterns on equivalent tasks [source-0f6e6c1f0f7f], it is unsuitable for real-time applications. Most improvement lands on retries 1-2; by retry 4-5, the model's self-critique enters diminishing returns. It also "over-thinks a straightforward edit; no change executed" — a 40s no-op vs ReAct's 8s correct answer for simple edits [source-0f6e6c1f0f7f]. Self-evaluation only works when the evaluator can define success clearly; subjective tasks produce vague, unhelpful reflections [source-84e431767d1f].

---

## 3. Plan-and-Execute

**Pattern description.** Plan-and-Execute separates a powerful planning model (e.g., GPT-4o, Claude Sonnet) from a cheaper executor model. "A powerful model analyzes the full task and generates a plan: a DAG of subtasks with dependencies. A simpler, cheaper model then executes each step. If a step fails, a replanner revises the remaining steps... A 10-step task that needs 10 LLM calls in ReAct needs 1-2 in Plan-and-Execute" [source-84e431767d1f]. This dramatically reduces cost and enables plan inspection before execution.

**Benchmark strengths.** The plan's explicitness makes it ideal for regulated or auditable workflows. In structured environments (insurance claims, financial reports, data pipeline tasks), the inspect-before-execute property is operationally critical. Strands Agents benchmarks show Plan-and-Execute hybrid (ReWOO-guided ReAct) handling "ordered checks (totals → fare rules → search → cancel/rebook → payment split)" reliably [source-0f6e6c1f0f7f].

**Documented weaknesses (2024-2026).** The plan is "rigid when reality surprises you. If step 3 returns something the planner didn't anticipate, the plan can derail... The planner can only plan for what it can foresee. Novel edge cases or ambiguous tasks produce bad plans, and a bad plan sends the executor confidently down the wrong path for every remaining step" [source-84e431767d1f]. If replanning fires on most tasks, the architecture pays both planning and adaptation overhead simultaneously.

**Long-horizon evaluation (EcoGym, 2026).** The EcoGym benchmark [source-7ecca2f03900] specifically targets plan-and-execute in interactive economies over 1000+ steps. "Experiments across eleven leading LLMs expose a systematic tension: no single model dominates across all three scenarios. Critically, we find that models exhibit significant suboptimality in either high-level strategies or efficient actions executions" [source-7ecca2f03900]. This is the first systematic benchmark confirming that Plan-and-Execute breaks down for very long-horizon tasks where high-level strategy and efficient execution rarely coexist.

---

## 4. ReWOO (Reasoning WithOut Observation)

**Origin & benchmark baseline.** ReWOO (Xu et al. 2023) [source-afa1bb25e152] proposes "a modular paradigm... that detaches the reasoning process from external observations, thus significantly reducing token consumption." The Planner writes a single plan with placeholders (#E1, #E2), Workers execute tools (possibly in parallel), Solver synthesizes. Benchmark headline: "ReWOO achieves 5x token efficiency and 4% accuracy improvement on HotpotQA." It also "demonstrates robustness under tool-failure scenarios" and enables offloading: "reasoning ability from 175B GPT3.5 into 7B LLaMA" [source-afa1bb25e152].

**Strengths documented through 2025.** Practitioners note ReWOO typically reduces token usage "by five to ten times compared to a complex ReAct trace" [source-b8b0b17f6e51]. Only 2 LLM calls total vs ReAct's N-per-step. Parallel tool execution gives latency advantages for tasks with multiple independent data lookups. On τ-Bench, "ReWOO (28s): Correct — blocks modification; points to cancel/rebook path" in a policy-compliance test where ReAct answered incorrectly [source-0f6e6c1f0f7f]. Its strict evidence ledger (typed plan artifacts) provides governance advantages for regulated industries.

**Documented weaknesses.** "Zero mid-execution adaptation. If step 2's result means step 4 should change, ReWOO won't catch that. The plan was locked in during the first LLM call" [source-84e431767d1f]. Placeholder dependency chains are fragile: "If #E1 returns something the planner didn't expect, #E2 (which references #E1) may get garbage input" [source-84e431767d1f]. "If the initial plan generated by the Planner is flawed... the agent has no built in mechanism to self correct or pivot. The original plan is fixed, often leading to a hard failure" [source-b8b0b17f6e51]. On τ-Bench, "ReWOO (43s): pricing inconsistent for full return and no final Mastercard figure" in a complex constraint task despite a strong plan [source-0f6e6c1f0f7f].

---

## Cross-Pattern Evolution 2024-2026

### 1. Hybrid Patterns Become the Standard
By 2025, pure implementations gave way to documented hybrid architectures. The most common hybrid in production is **ReAct + Reflexion**: run a ReAct loop, and if the result fails validation, enter a Reflexion retry cycle. AWS also introduced **ReWOO-guided ReAct**: ReWOO planner + ReAct loop per step, giving governance from ReWOO and flexibility from ReAct [source-0f6e6c1f0f7f]. Both show that the four patterns are better understood as composable modules than exclusive choices [source-84e431767d1f].

### 2. Architectural Effects Quantified (MAFBench, 2026)
The 2026 MAFBench study [source-86f4868be35b] established quantitatively that "framework-level design choices alone can increase latency by over 100x, reduce planning accuracy by up to 30%, and lower coordination success from above 90% to below 30%." This confirmed that pattern/architecture selection is not marginal — it is a primary driver of performance variation, more important than model choice in many settings.

### 3. CodeAct as an Emergent 5th Pattern (2024-2025)
CodeAct emerged as a significant addition by 2024: rather than calling pre-defined API tools, the agent generates and executes Python/SQL code in a sandboxed interpreter, with error tracebacks fed back as observations for self-debugging [source-b8b0b17f6e51]. This extends the paradigm for data analysis, mathematical computation, and software engineering tasks where fixed tool registries are insufficient.

### 4. Graph + RL as ReAct Successor (2025)
GAP (NeurIPS 2025) [source-d8016fb06ab8] represents the clearest architectural evolution beyond ReAct: explicitly modeling task dependencies as graphs and training agents with RL to determine parallelization. This directly addresses ReAct's sequential bottleneck and hints at a trajectory from hand-coded patterns to trained agentic architectures.

### 5. Survey Landscape Expands to ~60 Benchmarks
The survey by Ferrag et al. [source-dc2e29a1e7e9], updated March 2026, documented ~60 agent evaluation benchmarks. Future research priorities now include "dynamic tool integration via reinforcement learning, integrated search capabilities, and security vulnerabilities in agent protocols" — areas largely absent from the original 2022-2023 benchmark vocabulary.

---

## Summary Table

| Pattern | Benchmark Strength | Key Weakness | Best 2025/2026 Use Case |
|---|---|---|---|
| **ReAct** | 34%/10% ALFWorld/WebShop; best for simple tasks (8s, correct) | 90.8% retries wasted; 3× step variance; token cost scales linearly | Exploratory, dynamic, <5-step tasks |
| **Reflexion** | HumanEval 91% (vs GPT-4 80%); AlfWorld 130/134; wins complex constraint tasks | Same-model echo chamber; 5-10× latency; over-thinks simple tasks | Code correctness, policy-heavy multi-constraint tasks |
| **Plan-and-Execute** | Auditable, cost-efficient; passes policy gates | Rigid to surprises; breaks at very long horizons (EcoGym) | Structured workflows, regulated industries |
| **ReWOO** | 5× token efficiency; 4% HotpotQA accuracy gain; wins policy-compliance tests | No mid-execution adaptation; placeholder chain brittleness | Parallel data lookups, high-throughput reporting |


### Synthesis: What multi-agent orchestration patterns (supervisor/hierarchical, router, swarm/peer-to-peer, blackb

**Bottom line:** Five major multi-agent orchestration patterns—supervisor/hierarchical, router/adaptive-network, swarm/peer-to-peer, blackboard, and hybrid planner+ReAct—have fully crystallized between 2024 and 2026 as distinct architectural patterns, each with characterized trade-offs. In produc

## Multi-Agent Orchestration Patterns 2024–2026: Architecture, Trade-offs, and Production Deployment

### 1. Pattern Landscape Overview

Between 2024 and 2026, multi-agent orchestration vocabulary stabilized around a recognized set of canonical patterns. A 2026 taxonomy from Digital Applied [source-4d77c2e0bb58] identifies eight canonical patterns spanning four quadrants (single-agent, collaborative multi-agent, competitive/adversarial, and orchestration topology), noting that "most production agent systems are compositions of two or three from across those quadrants." A parallel academic catalog from UNSW [source-68ee983bc61f] documents 46 formal design patterns across three tiers—LLM Agents, Agentic AI, and Agentic Communities—including blackboard (Pattern #42), orchestration (#14), hierarchical planning (#5), debate/deliberation (#43), and ReAct (#1).

The major frameworks implementing these patterns—LangGraph, AutoGen/AG2, CrewAI, OpenAI Agents SDK, and Microsoft Agent Framework—all converged on supporting the same canonical patterns by Q2 2026, making framework choice less about exclusive pattern support and more about team familiarity and operational integration [source-4d77c2e0bb58].

---

### 2. Supervisor / Hierarchical Pattern

**Architecture:** A central supervisor agent decomposes a complex task into subtasks, delegates to specialized worker agents, monitors progress, and synthesizes the final response. The hierarchy can span multiple levels (e.g., a manager-supervisor-worker tree), with each level adding a layer of abstraction.

**Empirical performance:** A rigorous benchmark across 10,000 SEC filings and five LLMs [source-a0debd7afcd8] found that hierarchical supervisor-worker architecture "occupy the most favorable position on the cost-accuracy Pareto frontier (F1 0.921 at cost)"—achieving 97.7% of the best-observed accuracy at 60.7% of the cost. When optimized with semantic caching, model routing, and adaptive retry, this climbs to recovering "89% of the reflexive architecture's accuracy gains at only baseline cost." The pattern also proved most scale-resilient among complex architectures, outperforming reflexive loops above 50,000 documents/day.

**Framework support:** LangGraph's `langgraph-supervisor` library provides first-class support; CrewAI implements it as "hierarchical process" with a manager agent; AutoGen implements via GroupChat with a selector agent. Multi-level hierarchies are explicitly supported in LangGraph by nesting supervisors [source-522b01d1048b].

**Production deployments:** Project Synapse [source-116911c8c692] deployed hierarchical multi-agent coordination for last-mile delivery disruption resolution, pairing a Resolution Supervisor with specialized logistics, communications, evidence, and adjudication worker agents orchestrated via LangGraph, achieving an overall score of 0.85 (vs. 0.60 for single-agent ReAct and 0.70 for flat hierarchical). At scale, Uber used LangGraph-based multi-agent systems for large-scale code migrations; AppFolio's Realm-X property management copilot saved users 10+ hours/week using controllable LangGraph architecture [source-7656adf55900].

**Trade-offs:** Latency accumulates per level—a 3-level hierarchy with 2-second LLM calls per level adds a minimum 6-second coordination overhead before any worker begins executing [source-522b01d1048b]. Agent coordination failure rates also increase with hierarchy complexity (12.4% in hierarchical vs. 8.1% in parallel fan-out) [source-a0debd7afcd8]. Kore.ai recommends avoiding the supervisor pattern for "real-time or voice systems, where centralized reasoning increases latency" and "high-scale agent environments that could overload the orchestrator" [source-95e96bc50cd2].

---

### 3. Router / Adaptive Network Pattern

**Architecture:** A lightweight routing agent (or intent classifier) assigns incoming requests to specialist agents based on task type, content, or confidence. Unlike full supervisor patterns, routers do not orchestrate multi-step delegation—they do a single dispatch. In decentralized ("adaptive network") variants, agents can self-delegate or hand off directly without a persistent orchestrator, making this pattern suitable for real-time, low-latency applications.

**Framework implementations:** LangGraph supports model routing as an ablation within hierarchical systems. The Hierarchical-Optimized benchmark configuration in [source-a0debd7afcd8] demonstrated a 2-tier routing strategy (Claude Sonnet for complex fields + Mixtral for simpler ones) reducing cost by 51.3% while retaining 98.2% of accuracy. Kore.ai's "adaptive agent network pattern eliminates centralized control, enabling agents to collaborate and transfer tasks directly based on expertise and context" [source-95e96bc50cd2], with demonstrated use in HR/IT/finance payroll workflows.

**Production deployments:** LinkedIn SQL Bot is a multi-agent system built on LangGraph that routes natural language questions to appropriate agents for table discovery, SQL generation, and error correction [source-7656adf55900]. Customer support platforms running "hundreds of support agents with autonomous resolution rates above 90%" use orchestrator-worker (router-based) patterns for triage and domain-specific resolution [source-522b01d1048b].

---

### 4. Swarm / Peer-to-Peer Pattern

**Architecture:** Agents operate as autonomous peers with no persistent central coordinator. Coordination is achieved through handoff functions (an agent returns another agent object, transferring control), shared blackboard state, or pheromone-like environment signals. OpenAI's Swarm framework, released October 2024, formalized this with two primitives: agents (instructions + functions) and handoffs (functions returning another agent). AutoGen implements this via its `Swarm` team type in AgentChat, distinct from its `SelectorGroupChat` which uses an LLM-selected-next-speaker model.

**Characteristics:** Control is low but scalability is high—"no coordination bottleneck." Fault tolerance is high since there is no single point of failure. However, debugging is hard, requiring distributed tracing and blackboard replay [source-522b01d1048b]. The 2026 taxonomy [source-4d77c2e0bb58] strongly advises: "Swarm only for exploratory or research-mode systems where flow can't be pre-specified. Default to graph or hierarchy in production."

**Production context:** Swarm patterns excel at exploration tasks "where the problem space is large and the optimal path is unknown. Research flows, competitive intelligence gathering, and large-scale web scraping benefit from swarm coordination because agents explore different branches of the search space independently" [source-522b01d1048b]. A notable internal practitioner observation states: "Hierarchical wins over swarm in production almost every time. The supervisor anchors goal alignment; swarms drift without it" [source-4d77c2e0bb58]. OpenAI itself labeled its Swarm framework as "experimental" and "not intended to be used in production."

---

### 5. Blackboard Pattern

**Architecture:** A classical AI pattern (originating 1985, Hayes-Roth) revived for LLM multi-agent systems. Three core components: (1) a shared **blackboard** (global shared memory store), (2) a **control unit** (LLM or rule-based agent that selects which agent acts next based on current blackboard content), and (3) a **group of specialized agents** that read from and write to the blackboard exclusively. Agents communicate solely through the blackboard with no direct peer contact.

**Empirical results:** LbMAS [source-0a54b8023afa] implemented the first LLM blackboard system and achieved an average of 81.68% across MMLU, ARC-Challenge, GPQA-Diamond, BBH, MATH, and GSM8K benchmarks—outperforming CoT by 4.33% and static MAS methods by 5.02% while consuming the second-lowest token count among all compared methods. For data science tasks, a separate blackboard system [source-fae84a9a679a] showed "13%–57% relative improvements in end-to-end success and up to a 9% relative gain in data discovery F1 over the best baseline," specifically noting that "this design improves scalability and flexibility by removing the need for a central coordinator to know each agent's expertise or internal knowledge."

**Key innovations:** LbMAS removes the individual agent memory module (which the blackboard replaces), includes specialized predefined agents (planner, critic, conflict-resolver, cleaner, decider), and uses dynamic agent selection per round. Agents can interact in public or private spaces on the blackboard. The UNSW pattern catalog [source-68ee983bc61f] classifies blackboard as a formal Agentic Community pattern (#42, "Shared memory coordination").

**Production status:** The 2026 taxonomy notes "Swarm and blackboard patterns are theoretically interesting but rarely outperform hierarchical or graph in practice" in production [source-4d77c2e0bb58], though empirical benchmarks show clear wins in exploratory and research-oriented tasks, code generation assistance, and data science discovery tasks with heterogeneous unstructured data lakes.

---

### 6. Hybrid Planner + ReAct Pattern

**Architecture:** Combines an explicit upfront planning phase (producing a structured plan, often as a JSON array of steps) with a ReAct execution loop (thought → action → observation cycles) for individual steps or exception handling. Variants include: (a) pure ReAct with on-the-fly replanning on failure; (b) full plan-then-execute (planner emits ordered plan, executor walks it step-by-step); and (c) hybrid synchronous/asynchronous with streaming execution.

**Flagship implementation:** Gradientsys [source-65a68695ba66] pairs a centralized LLM Scheduler using a ReAct-based dynamic planning loop with a typed Model-Context Protocol (MCP) tool registry. The scheduler issues parallel multi-agent dispatches (one-to-many), supports hybrid sync/async execution, incorporates retry-and-replan on failure, and streams reasoning traces via Server-Sent Events. On GAIA: 24.1% accuracy vs. 15.0% baseline (60% relative improvement), 4.5× cost reduction vs. MinionS baseline. Ablation: "No ReAct Reasoning: Replaced the ReAct loop with a single-step planner. Accuracy dropped significantly to 12%, indicating the necessity of iterative reasoning." [source-65a68695ba66].

**Framework context:** LangGraph's prebuilt `create_react_agent` provides first-class ReAct; CrewAI's hierarchical process uses plan-and-execute logic with a manager-planner designating sub-plans to workers [source-68ee983bc61f]. Plan-then-execute patterns are classified in the UNSW catalog as Pattern #41 ("Separate plan from execution"). The benchmark paper [source-a0debd7afcd8] notes the reflexive self-correcting loop (iterative ReAct + verification) achieves the highest F1 (0.943) but has the widest latency distribution (p95/p50 = 3.3×) and degrades fastest at scale due to queuing-induced timeout truncation.

**Production deployments:** Replit's production agent (LangGraph) emphasizes multi-agent + human-in-the-loop and custom cognitive architectures. Elastic's AI assistant uses LangGraph for ReAct-based tool calling. Project Synapse [source-116911c8c692] uses CoT for supervisor task decomposition and ReAct for individual worker agent execution within the LangGraph orchestration engine.

---

### 7. Pattern Selection and Hybrid Production Configurations

The dominant real-world finding is that production systems rarely use a single pattern. As the Gurusup guide notes: "most production systems use hybrid patterns. A hierarchical system where leaf-level teams use mesh coordination internally. A pipeline where one stage launches a swarm for parallel data collection" [source-522b01d1048b].

The 2026 Digital Applied taxonomy offers a concrete production stack: "ReAct + Reflexion + re-anchor for the single-agent stack; supervisor-worker + verifier-critic for high-stakes multi-agent; graph orchestration for production-grade observability" [source-4d77c2e0bb58]. The dominant escalation path is: start with single-agent ReAct → add Reflexion for repeated failures → add verifier-critic for high-stakes outputs → move to supervisor-worker only when single-agent caps out on a measured quality dimension.

**Benchmark comparison summary:**

| Pattern | F1 (Financial Docs) | Latency | Cost/Doc | Production Fit |
|---|---|---|---|---|
| Sequential pipeline | 0.897–0.903 | Low | Lowest | Batch, simple tasks |
| Parallel fan-out | 0.908–0.914 | Lowest | Moderate | Latency-critical |
| Hierarchical supervisor | 0.921–0.929 | Moderate | Medium | Production default |
| Reflexive (ReAct loop) | 0.936–0.943 | Highest | Highest | Low-volume, accuracy-critical |
| Hierarchical-Optimized* | 0.924 | Low-moderate | ~$0.148 | Best all-around |

*Hierarchical + semantic caching + model routing + adaptive retry [source-a0debd7afcd8]

---

### 8. Failure Modes and Production Risks

Each pattern introduces distinct failure modes [source-a0debd7afcd8]:
- **Sequential:** Cross-table reference failures (28.4%)—information from earlier stages unavailable downstream
- **Parallel:** Context window truncation (14.7%) and coordination failures (8.1%)
- **Hierarchical:** Agent coordination failures including deadlocks and message corruption (12.4%), and high latency accumulation per level
- **Reflexive:** "Overthinking"—oscillating ambiguity resolution (39.3% of errors), unsuitable for strict SLA systems
- **Swarm:** Goal drift without supervisor anchor; convergence uncertainty; debugging difficulty requiring distributed tracing

Coordination failure rates scale with architecture complexity: 0% in sequential, 8.1% parallel, 12.4% hierarchical, 14.2% reflexive [source-a0debd7afcd8]. The UNSW pattern catalog [source-68ee983bc61f] recommends Compliance/Governance, Audit Trail, and Human-in-the-Loop as cross-cutting patterns mandatory for enterprise/regulated deployments regardless of orchestration topology.

---

### 9. Key Frameworks and Ecosystem (as of Q2 2026)

- **LangGraph** (LangChain): Graph orchestration with directed edges + supervisor and swarm prebuilt libraries; dominant in production (Replit, LinkedIn, Uber, AppFolio, Elastic) [source-7656adf55900]
- **AutoGen/AG2** (Microsoft): GroupChat (debate), SelectorGroupChat (router), Swarm (handoff-based P2P), and magentic-one (hierarchical); strong for research/prototyping
- **CrewAI**: Role-based crews with sequential and hierarchical process types; fastest to prototype, but users report hitting limits at 6–12 months
- **OpenAI Agents SDK**: Native handoffs and tool calling; Swarm (educational/experimental)
- **Microsoft Agent Framework**: .NET/Python graph orchestration; strong governance for enterprise


### Synthesis: What newer agent paradigms (deep research agents, computer-use agents, Voyager-style skill libraries

**Bottom line:** The 2025–2026 period produced five converging agent paradigms—deep research agents, computer-use agents, skill library systems, test-time compute scaling, and agentic RL-trained models—that collectively evolve and industrialize the earlier ReAct/Reflexion/planner-executor lineage

## Overview: A Lineage Map

The story of AI agents from 2022–2026 is one of accelerating elaboration. **ReAct** (2022) established the basic reason-act-observe loop. **Reflexion** (2023) added verbal self-reflection as a refinement mechanism. **Planner-executor** architectures decoupled strategic task decomposition from low-level tool execution. By 2025–2026, these patterns had been deeply embedded into five new paradigms, each representing a distinct axis of evolution: *breadth* (deep research), *embodiment* (computer use), *persistence* (skill libraries), *depth* (test-time compute), and *internalization* (agentic RL). The following sections trace each paradigm and its genealogical connections.

---

## 1. Deep Research Agents (DR Agents)

**Definition and Origins.** DR agents are "AI agents powered by LLMs, integrating dynamic reasoning, adaptive planning, and iterative tool use to acquire, aggregate, and analyse external information, culminating in comprehensive outputs for accomplishing open-ended informational research tasks" [source-65a084c5782d]. The paradigm emerged from two converging pressures: (a) the limitations of static RAG pipelines, which lacked sustained reasoning, and (b) the proliferation of capable LLMs that could manage multi-step search-read-synthesize loops.

**Key Systems.** By mid-2025, the landscape included dozens of DR agents: OpenAI Deep Research (backed by o3), Gemini DR, Grok DeepSearch, Perplexity DR, Kimi-Researcher, Manus, Search-o1, R1-Searcher, DeepResearcher, WebDancer, WebSailor, PANGU DeepDiver, and Agent-R1. [source-65a084c5782d]. These range from single-agent systems to hierarchical multi-agent stacks.

**Relationship to ReAct/Reflexion.** The linkage is explicit: "Systems such as Search-o1, R1-Searcher, DeepResearcher, WebDancer, WebSailor, PANGU Deepdiver, Agent-R1, ReSearch, Search-R1, WebWatcher, MiroRL, Memento and Kimi-Researcher exemplify this paradigm through iterative cycles of explicit reasoning, action, and reflection, **aligning with the ReAct framework**" [source-65a084c5782d]. Single-agent DR systems are essentially ReAct loops operating over web search and browser tools, with the observation step now sourcing live external content rather than fixed databases.

**Relationship to Planner-Executor.** Multi-agent DR frameworks advance to hierarchical planner-executor architectures: "Representative frameworks include OpenManus and Manus, both adopting hierarchical planner-toolcaller architectures. Similarly, OWL includes a workforce-oriented model, utilising a central manager agent to orchestrate task distribution among specialised execution agents" [source-65a084c5782d]. This is the planner-executor pattern at industrial scale, with the planner now backed by a powerful reasoning model (often an o3-class or R1-class LRM) and multiple specialized executors handling browsing, code execution, and data analytics.

**RL-based Tuning.** A key 2025 innovation is training DR agents with RL rather than hand-crafted prompts. "Most current open-source RL implementations of DR agents commonly adopt rule-based reward models that explicitly define task-specific objectives such as retrieval relevance, information accuracy, or successful tool invocation. To efficiently perform policy optimisation, recent systems have increasingly utilised PPO and GRPO" [source-65a084c5782d]. GRPO, originally developed for DeepSeek, has become the dominant optimizer for training DR agents (Search-R1, R1-Searcher, ReSearch, DeepResearcher, WebDancer, etc.).

---

## 2. Computer-Use Agents (CUAs)

**Definition and Origins.** Computer-use agents operate computers through raw GUI interactions—mouse movements, clicks, keystrokes, screenshots—rather than through structured APIs. Anthropic's Claude 3.5 Computer Use (October 2024) was "the first frontier AI model to offer computer use in public beta as a graphical user interface (GUI) agent" [source-a5f1d4748c2b].

**Architecture.** The CUA architecture decomposes into: (1) **Planning**—generating an executable plan from a user instruction; (2) **Action**—grounding and executing actions on GUI elements; (3) **Critic**—monitoring state changes and adapting. The reasoning paradigm is explicitly ReAct-derived: "Claude Computer Use employs a reasoning-acting paradigm for its reasoning process... Similar to traditional ReAct, Claude Computer Use observes the environment before deciding on an action... beyond traditional ReAct paradigm, which typically involves continuous observation of the environment at each step, Claude Computer Use adopts a more selective observation strategy" [source-a5f1d4748c2b]. The agent uses only visual screenshots (no HTML/metadata), making it more general but more demanding in terms of grounding.

**Rapid Progress.** The CUA field accelerated dramatically: "on OSWorld, success rates have climbed from single digits in early 2024 to beyond human-level performance (72.6% vs. 72.36% human baseline) by December 2025" [source-051bba93deec]. Key systems include UI-TARS, UI-TARS-2 (multi-turn RL training), Agent S2 (generalist-specialist framework), and OpenCUA-72B (45% on OSWorld-Verified). By 2025–2026, GUI grounding—identifying the correct screen element—became its own subspecialty.

**Relationship to Lineage.** CUAs extend ReAct's action space from structured API calls to raw pixel-level computer interactions. The "observe-think-act" loop remains identical in structure but now operates over a screenshot observation space. The Critic dimension is the most salient addition over basic ReAct—closer to Reflexion's self-monitoring capacity but applied to execution rather than reasoning quality. CUAs also incorporate skill libraries (see §3): Anthropic's Agent Skills system and the SAGE/SEAgent paradigms show CUAs benefiting from persistent procedural knowledge.

---

## 3. Voyager-Style Skill Libraries

**Origins.** Voyager (2023, 1547 citations, published in TMLR) established the foundational paradigm: "Voyager consists of three key components: 1) an automatic curriculum that maximizes exploration, 2) an ever-growing skill library of executable code for storing and retrieving complex behaviors, and 3) a new iterative prompting mechanism that incorporates environment feedback, execution errors, and self-verification for program improvement" [source-d50be42998da]. Crucially, it "bypasses the need for model parameter access and explicit gradient-based training or finetuning."

**2025–2026 Evolution.** By 2025, the skill library idea had expanded into a full paradigm. Anthropic formalized **Agent Skills** in October 2025—portable, filesystem-based skill packages (SKILL.md specifications), with 62,000+ GitHub stars within four months and production adoption at Atlassian, Figma, Canva, Stripe, and Notion [source-051bba93deec]. The SoK paper [source-8d2d98de06d3] systematizes the field into seven design patterns: metadata-driven disclosure, code-as-skill, workflow enforcement, self-evolving libraries, hybrid NL+code, meta-skills (skills that create skills), and marketplace distribution (e.g., MCP servers, OpenAI GPT Store).

**RL-Augmented Skill Acquisition.** SAGE (Skill Augmented GRPO for self-Evolution) introduces RL-based skill acquisition with Sequential Rollout—training across chains of tasks so skills generated early are reused later—achieving "72.0% Task Goal Completion and 60.7% Scenario Goal Completion—an 8.9% absolute improvement over baseline GRPO without skill libraries—while requiring 26% fewer interaction steps and 59% fewer generated tokens" [source-051bba93deec]. This is the first clean demonstration that skill libraries can be learned end-to-end via RL, not just collected via exploration.

**Critical Nuance.** A major empirical finding constrains enthusiasm: "curated skills raise agent pass rates by 16.2 percentage points on average, while self-generated skills degrade performance by 1.3 pp" [source-8d2d98de06d3]. Self-evolution only works reliably "in constrained environments with deterministic execution verification, suggesting the viability of self-generation depends critically on domain specificity and the availability of automated verification" [source-8d2d98de06d3]. This is a sharp contrast to Voyager's apparent success, which worked partly because Minecraft provides automatic execution verification.

**Relationship to Lineage.** The skill library paradigm generalizes and externalizes what Reflexion tried to do internally (verbal self-correction) into persistent, reusable, governed modules. In the SoK taxonomy, Reflexion is classified as providing "transient in-context refinement without persistent library updates" [source-8d2d98de06d3]. Skills are the persistence layer that Reflexion lacked: "without a skill layer, every task requires the agent to reason from first principles within a limited context window, consuming tokens to re-derive procedures that could be stored and retrieved" [source-8d2d98de06d3]. The planner-executor pattern maps onto skill architectures: the planner selects and sequences skills; the executor runs them.

---

## 4. Test-Time Compute Scaling

**Core Idea.** Test-time compute (TTC) scaling is the paradigm of allocating additional compute *during inference* rather than investing solely in pretraining or fine-tuning. The agentic LLMs survey describes it as System 2 vs. System 1 thinking: "At inference time, pure LLMs think fast (System 1 thinking). Inference-time step-by-step methods can be added to achieve deliberative slow thinking (System 2 thinking)" [source-b1fcae9e7c33]. In the context of RL-trained models, TTC emerges spontaneously: "RLVR and GRPO have created the possibility to trade off training time to model size, allowing resource-efficient training of LLMs" and "these methods are reportedly used by OpenAI o1 and o3, DeepSeek, and Qwen-3" [source-b1fcae9e7c33].

**Two Primary Mechanisms.** The literature distinguishes:
- **Sequential TTC**: The model generates longer chains of thought, self-verifying and backtracking before committing to an answer (o1/o3, DeepSeek-R1, Kimi k1.5).
- **Parallel TTC**: Multiple independent solution paths are sampled and ranked (o1-ioi's 10,000 samples per subtask with clustering/reranking).
- **Sleep-time compute** (a newer variant): Models think *offline before queries arrive*, pre-computing useful quantities to reduce on-demand compute. "By anticipating what queries users might ask and pre-computing useful quantities, we can significantly reduce the compute requirements at test-time" (arxiv:2504.13171).

**Relationship to Lineage.** TTC is the computational formalization of what Reflexion tried to do via verbal prompting—iterative self-improvement. ReAct's observe-reason-act loop is a form of sequential TTC, but externally orchestrated. O1/o3's chain-of-thought RL *internalizes* this loop so the model itself decides how long to think. This represents a paradigm shift from prompt engineering agents (ReAct, Reflexion) to agents whose self-monitoring behaviors are baked into weights through RL.

---

## 5. Agentic RL-Trained Models: o1, o3, DeepSeek-R1

**The Paradigm.** The o1/o3/DeepSeek-R1 family represents models trained via RL to develop intrinsic agentic reasoning—they don't need an external loop imposed by a framework; they reason through problems by virtue of their training. DeepSeek-R1 demonstrates "that the reasoning abilities of LLMs can be incentivized through pure reinforcement learning (RL), obviating the need for human-labeled reasoning trajectories. The proposed RL framework facilitates the emergent development of advanced reasoning patterns, such as **self-reflection, verification, and dynamic strategy adaptation**" [source-03b4d4de3350].

**O3's Breakthrough.** OpenAI o3 shows the most dramatic evidence of emergent agentic behaviors from RL training: "o3 achieves 395.64 points, surpassing the gold threshold even under the 50-submission limit [IOI 2024]. These results demonstrate that o3 outperforms o1-ioi **without relying on IOI-specific, hand-crafted test-time strategies**" [source-0598a43228cd]. Moreover, o3 independently discovered a test-time strategy—"for problems where verification is nontrivial, it often writes simple brute-force solutions—trading efficiency for correctness—then cross-checks the outputs against its more optimized algorithmic implementations"—a behavior that mirrors a ReAct-style observe-verify loop but was never programmed [source-0598a43228cd]. The conclusion: "scaling general-purpose reinforcement learning, rather than relying on domain-specific techniques, offers a robust path toward state-of-the-art AI in reasoning domains" [source-0598a43228cd].

**Relationship to Lineage.** These models represent the *internalization* of the ReAct/Reflexion lineage. Where Reflexion was an external wrapper adding a verbal critic to a base LLM, o3/DeepSeek-R1 make self-reflection an intrinsic weight-level capability. Where ReAct is an orchestration pattern imposed via prompts, these models have learned to "reason and think through extended chains of thought" without external scaffolding. The RP-ReAct paper [source-4306914e2135] illustrates the hybrid: it uses a Large Reasoning Model (LRM like DeepSeek-R1) as the Reasoner-Planner Agent and a standard ReAct loop in the Proxy-Execution Agents, showing that LRMs now serve as the *planning tier* within the classic planner-executor pattern.

---

## 6. Cross-Cutting Synthesis: How the Paradigms Inter-relate

| Paradigm | Core Mechanism | ReAct Relationship | Reflexion Relationship | Planner-Executor Relationship |
|---|---|---|---|---|
| Deep Research Agents | Multi-hop search + synthesis | Explicit extension (single-agent DR = ReAct over web) | RL replaces verbal self-reflection | Multi-agent DR = hierarchical planner-executor |
| Computer-Use Agents | GUI pixel-level actions | ReAct with screenshot observations, selective observation | Critic dimension adds self-monitoring | Skills + planner direct GUI executor |
| Skill Libraries | Persistent procedural modules | Skills package reusable ReAct sub-sequences | Replaces transient Reflexion with persistent skill updates | Skills are the reusable outputs of planner-executor runs |
| TTC Scaling | More inference-time compute | Formalizes/scales the reason-act-observe loop | Generalizes verbal critique to compute-scaled backtracking | Enables longer planning chains with auto-correction |
| Agentic RL Models (o1/o3/R1) | RL-internalized chain-of-thought | Internalizes ReAct loop into weights | Subsumes Reflexion into training-time RL | Serves as the *planner* in new hybrid architectures |

**The Emerging Stack.** These paradigms are not independent—they compose into a new agentic stack. A state-of-the-art system in 2025–2026 might use: an o3/Kimi-k2-class LRM as the planner (internalized TTC scaling + agentic RL), ReAct-style executor agents interacting with tools and GUIs (computer-use + deep research), a persistent skill library (SKILL.md + MCP) to avoid re-deriving known procedures, and RL-based training across the whole pipeline (GRPO/REINFORCE for end-to-end optimization). The RP-ReAct architecture [source-4306914e2135] is a microcosm of this: "a Reasoner Planner Agent (RPA), responsible for leveraging powerful reasoning models to plan each sub-step... Multiple Proxy-Execution Agents (PEA): Dedicated to translating sub-steps into concrete tool interactions, using a ReAct approach (think, act, observe) to complete the action."

**Limitations of Earlier Lineage.** The 2025–2026 work reveals where earlier frameworks failed: (1) Reflexion "shows the worst performance overall in basically all tasks" on multi-step enterprise benchmarks [source-4306914e2135], suggesting that single-pass verbal self-critique is insufficient for long-horizon tasks. (2) Simple ReAct "hits a plateau in performance after a limited number of steps" on hard tasks, validating the need for explicit planning separation [source-4306914e2135]. (3) Self-evolving skill libraries degrade performance in open-ended settings without automated verification [source-8d2d98de06d3], showing that unrestricted self-generation is not a free lunch. (4) TTC scaling introduces new security vectors—agentic systems running with more autonomy in more environments—and skill marketplaces have a 26.1% vulnerability rate [source-051bba93deec].

---

## 7. Open Issues and Frontiers

- **Verifiable grounding**: Most RL-based training relies on outcome rewards; process-level rewards remain harder to define for open-ended research tasks.
- **Skill quality at scale**: The phase transition in skill selection accuracy as library size grows beyond a critical threshold [source-051bba93deec] implies practical limits on how many skills an agent can manage.
- **Cost vs. depth tradeoff**: "sleep-time compute" attempts to decouple reasoning depth from user-facing latency, but the economics are complex.
- **Safety in high-autonomy systems**: Computer-use and DR agents operating with greater autonomy in real environments introduce liability and security risks that earlier single-turn or sandboxed architectures avoided.


### Synthesis: Which agent architectures hold up at scale in 2025–2026? Consider cost/latency, reliability, failure

**Bottom line:** In 2025–2026, the agent architectures that hold up at scale are narrow, controllable, composable systems—hierarchical orchestrator-worker patterns, graph-based state machines (LangGraph), and tiered routing architectures—rather than flat multi-agent swarms or fully autonomous lon

# Agent Architectures at Scale: 2025–2026

## 1. The Foundational Shift: Workflows vs. Agents vs. the Middle Ground

The 2025–2026 period crystallized a key distinction that earlier discourse had muddled. Anthropic's production engineering team—after working with dozens of enterprise customers—codified a two-category taxonomy: **workflows** (LLMs orchestrated through predefined code paths) versus **agents** (LLMs dynamically directing their own processes) [source-fd454bb64b30]. The critical insight from their real-world deployments: *"Workflows offer predictability and consistency for well-defined tasks, whereas agents are the better option when flexibility and model-driven decision-making are needed at scale."* Both exist on a spectrum, and the most successful production systems live in the middle—structured enough for reliability, flexible enough for open-ended tasks.

The LangChain team corroborated this from the production side: *"2024 was the year that agents started to work in production. Not the wide-ranging, fully autonomous agents that people imagined with AutoGPT. But more vertical, narrowly scoped, highly controllable agents with custom cognitive architectures."* [source-b12883165ced]. The term "cognitive architecture" replaced "agent" in most serious production discussions—a signal that the engineering community had moved past the simplistic prompt-loop model.

## 2. The Five Core Patterns That Survive Production

Anthropic's engineering team identified five composable building blocks that appear consistently in production systems [source-fd454bb64b30]:

1. **Prompt chaining** – Sequential LLM calls with programmatic gates; trades latency for accuracy; best for tasks with fixed subtask structure (e.g., generate → check criteria → refine).
2. **Routing** – A classifier (LLM or traditional ML) dispatches inputs to specialized handlers; particularly powerful for cost-tiering: *"Routing easy/common questions to smaller, cost-efficient models like Claude Haiku 4.5 and hard/unusual questions to more capable models like Claude Sonnet 4.5."*
3. **Parallelization** – Two variants: *sectioning* (independent subtasks in parallel) and *voting* (multiple independent completions for reliability). Parallelization appears in production for guardrails (one model processes; another screens) and code review (multiple models flag issues independently).
4. **Orchestrator-workers** – A central LLM dynamically breaks down tasks, delegates to worker LLMs, and synthesizes results. Suited for coding tasks (number of files needing changes can't be predicted) and multi-source search.
5. **Evaluator-optimizer** – One LLM generates; another evaluates and provides feedback in a loop. Requires clear evaluation criteria and measurable improvement value.

Of these, routing and orchestrator-workers are the most scalable. Routing enables cost efficiency; orchestrator-workers enable complexity handling. Neither requires full agent autonomy.

## 3. Graph-Based State Machines: The Enterprise Default

**LangGraph** has become the enterprise-default framework specifically because it makes agent behavior explicit as a state machine with visible transitions, no hidden prompts, and no obfuscated cognitive architecture [source-b12883165ced]. This transparency is itself a reliability feature: developers can audit, test, and constrain exact decision paths.

Production case studies validate this:
- **Replit** built agents with explicit human-in-the-loop and multi-agent setup on LangGraph [source-b12883165ced]
- **LinkedIn** built SQL Bot—a multi-agent system transforming natural language to SQL for internal data access—on LangGraph [source-b12883165ced]  
- **Uber** used LangGraph for large-scale code migrations, finding that internal tools for domain-specific workflows outperformed general-purpose agents [source-b12883165ced]
- **AppFolio's Realm-X** saved property managers over 10 hours/week via a LangGraph-powered multi-agent copilot [source-b12883165ced]
- **Vodafone** deployed LangGraph for multi-agent data engineering: modular sub-agents handling collection, processing, summarization, and reasoning tasks, integrated via APIs into their cloud infrastructure [source-28d379e998d4]
- **Notion** took 4–5 complete rebuilds over multiple years before shipping Custom Agents to production—arriving at progressive tool disclosure, SQL-like database abstractions, and a 100-tool harness [source-e08d41689c31]

A striking pattern emerged in the LangGraph ecosystem: *"Rexera: Great example of 'single agent → multi agent but uncontrollable (CrewAI) → controllable multi agent (LangGraph)' journey that we see many users go through"* [source-b12883165ced]. The path from CrewAI-style loose orchestration to LangGraph-style state machine control is now a documented production migration pattern.

## 4. Cost and Latency Economics

The cost landscape for production agents in 2025–2026 has specific, quantified structure [source-53245d0a003b][source-b9a4a1280b6a]:

| Architecture | Latency | Relative Token Cost |
|---|---|---|
| Single LLM call | ~800ms | 1× baseline |
| Orchestrator-worker w/ Reflexion loop | 10–30s | 50× per cycle |
| Unconstrained coding agent (SWE-bench style) | minutes | $5–8 per task, 1–3.5M tokens |
| Cached plan retrieval from memory layer | ~300ms | ~0× (near-free) |

The **quadratic cost problem** is the central economic hazard. Because LLMs charge for every input token in every turn, context accumulates: a 10-cycle Reflexion loop can consume 50× the tokens of a single pass [source-53245d0a003b]. High-performing agents on SWE-bench and GAIA benchmarks incur **10–50× more tokens per task** due to iterative reasoning loops [source-b9a4a1280b6a].

The production optimization toolkit is now well-defined [source-a707c1177078][source-53245d0a003b]:
- **Prompt caching**: Shared prefixes (system prompts, tool schemas) can be cached, reducing input costs by ~90% and latency by ~75%
- **Tiered routing**: Simple/reactive tasks go to small fast models; complex reasoning tasks route to larger orchestrators ("the Thinking Budget")
- **Memory layers**: Before invoking an expensive orchestrator, check whether a similar problem was solved before—this can cut latency from 30 seconds to 300ms
- **Background mode + webhooks**: Long-running agents run asynchronously without holding a client connection; event-driven completion notification replaces polling [source-a707c1177078]
- **Dynamic turn limits**: Exit early when probability of success at additional cost is low—this alone cuts costs ~24% while maintaining solve rates

**Session cost benchmarks** from Galileo's Agent Leaderboard v2 (July 2025) show a 17× spread across frontier models: DeepSeek-v3 at $0.014/session vs. Grok-4 at $0.239/session [source-b9a4a1280b6a]. The GPT-4.1 vs. GPT-4.1-mini comparison is illustrative: 62% vs. 56% action completion at 5× the price. Hybrid routing—cheap models for simple queries, frontier models for hard ones—can reduce total cost 30–50% with minimal quality loss.

A counterintuitive finding from Anthropic's applied AI team: *"the more expensive model achieved higher SWE-bench scores in considerably fewer tokens than Claude Sonnet 4.5. For production deployments, teams must evaluate cost at the task level rather than just comparing per-token pricing."* [source-e08d41689c31]. Task-level efficiency matters more than per-token price.

## 5. Failure Modes: The Taxonomy

The most rigorous failure analysis comes from two complementary studies:

### IBM Research & UC Berkeley: MAST on ITBench (NeurIPS 2025)
Analyzing 310 SRE agent traces across Gemini-3-Flash, Kimi-K2, and GPT-OSS-120B using the 14-category MAST taxonomy [source-34cd27d84517]:

- **Frontier models fail surgically** (2.6 failure modes/trace); open models fail with cascading collapse (5.3/trace)
- **FM-3.3 Incorrect Verification** is the universal predictor of failure: agents *"declare victory without checking ground truth"*
- **FM-1.4 Loss of Conversation History**: GPT-OSS-120B loses context in 24% of traces (Gemini: 0%, Kimi: 7%)
- **FM-2.6 Reasoning-Action Mismatch**: Kimi-K2 shows 92% failure prevalence—correctly identifying next steps but executing irrelevant commands
- **Architectural intervention effect**: Introducing a Summarizer Agent (fixing FM-1.4) or a State Machine (fixing FM-1.5) yields **up to 53% performance improvement**, vs. only ~16% from prompt engineering alone

### HORIZON Benchmark (COLM 2026): Long-Horizon Failure Structure
Studying 3,100+ trajectories of GPT-5 variants and Claude-4 across Web, OS, Embodied, and Database domains [source-e9351405b42a]:

- Performance degrades **non-linearly with horizon length**—stable until a cliff, then near-systematic failure (not a gradual slide)
- Once inside the failure region, **model capability differences vanish**: all models converge toward low success rates
- **Planning failures and catastrophic forgetting** dominate at long horizons—not raw capability gaps
- **Catastrophic forgetting** occurs not through literal memory loss, but through *"effective inattention to early instructions buried deep in a long trajectory"*—a real-world case showed an email agent ignoring safety constraints after hundreds of turns even though the constraints were still in the context window
- **Model scaling alone is insufficient**: the dominant failure mechanisms are architectural, not capability-related

The Redis analysis adds an architectural failure mode often missed: the **monoculture problem**—*"If you're using the same model for both planning and verification, your verification step has the same blind spots as your planner"* [source-9ad9a91d571d]. And **context rot**: attention mechanisms degrade on information in the middle of long contexts—a phenomenon distinct from running out of tokens. In multi-agent pipelines this compounds: Agent A's degraded output enters Agent B's context as ground truth.

## 6. Long-Horizon Task Reliability

No architecture fully solves long-horizon tasks in 2025–2026. The most reliable mitigation strategies are structural rather than prompting-based [source-e9351405b42a][source-e08d41689c31][source-fd454bb64b30]:

1. **Context compaction**: When approaching token limits, the system summarizes progress, clears history, and inserts the summary. Anthropic's Claude Code iterated ~100 times on compaction prompts. Still imperfect.
2. **External memory with file system access**: Agents maintain their own markdown notes; when context clears, they read their own notes rather than receiving a programmatic summary. Generalizes better than compaction.
3. **Sub-agent exploration isolation**: Sub-agents handle context-heavy exploration tasks (reading many files) and return just final reports. This preserves the main agent's context budget for execution.
4. **Hierarchical sub-planning with explicit checkpoints**: Planning errors that arise early propagate through all downstream steps. Explicit sub-plan verification gates reduce irreversible trajectory derailment.
5. **Externalized termination conditions**: FM-1.5 (Unaware of Termination Conditions) is universally fatal. The model itself cannot reliably determine when it's done. Finite state machines and explicit stop conditions must live outside the LLM [source-34cd27d84517].

Anthropic's production team found that LLMs are *"poor at breaking tasks into concurrent atomic units"*—the natural assumption that a planning agent would spawn parallel sub-agents rarely works as expected [source-e08d41689c31]. Sub-agents are best used for serial exploration and context isolation, not concurrent parallelism.

## 7. What Breaks Flat/Swarm Architectures

Multi-agent systems frequently underperform simpler single-agent alternatives due to [source-9ad9a91d571d]:
- **Communication overhead**: In an 180-config evaluation, multi-agent variants underperformed single-agent baselines; coordination tokens eat into the cognitive budget for actual tasks
- **Stale shared state**: Agents acting on information already superseded by a peer's concurrent action
- **Conformity bias**: When one agent makes a confident assertion, others tend to align rather than push back—locking in hallucinated facts
- **Context rot multiplication**: Agent A's degraded output propagates to Agent B as ground truth; each hop amplifies the original error

The academic survey (JACM-targeted preprint) confirms: *"Multi-agent frameworks can further separate roles (planner/executor/reviewer) for cross-checking, but they introduce coordination costs (latency, token usage) and can amplify inconsistency when agents disagree"* [source-96171c4fbcbc]. Role separation works best when *"roles have distinct tool access and explicit handoff artifacts (plans, checklists, traces), so that disagreements can be resolved via evidence rather than free-form debate."*

Gartner's prediction deserves mention: *"over 40% of agentic AI projects will fail to reach production by 2027"* due to the real cost and complexity of deploying at scale [source-b9a4a1280b6a].

## 8. What OpenAI Built for Scale

OpenAI's 2025 platform retrospective documents the infrastructure layer required for agent scalability [source-a707c1177078]:
- **Responses API**: Replaced Chat Completions as the agent-native API with reasoning controls, multi-modal support, and structured tool calling
- **Agents SDK** (open-source, Python and TypeScript): Building blocks for tool use, handoffs, guardrails, and tracing—provider-agnostic
- **AgentKit**: Higher-level tooling including Agent Builder, ChatKit, and Connector Registry for faster development cycles
- **MCP (Model Context Protocol)**: Standardized tool interfaces allowing portable agent tooling across runtimes; co-developed with Anthropic and the wider ecosystem
- **Prompt caching + background mode + webhooks**: Addressed the "agent is a long-running job" reality that polling-based systems couldn't handle
- Coding agent focus: **GPT-5.2-Codex** emerged as the default for repo-scale reasoning with sandbox+approval modes and AGENTS.md specification support

## 9. Architecture Selection Guide (2025–2026)

| Task Type | Recommended Architecture | Key Trade-off |
|---|---|---|
| High-volume, structured, low variance | Workflow / prompt chaining | Lowest cost/latency; fails on edge cases |
| Multi-category input dispatch | Routing with tiered model selection | Saves 30–80% cost vs. always-frontier |
| Complex decomposable tasks | Orchestrator-workers (LangGraph graph) | Higher latency; must externalize verification |
| Iterative refinement with clear criteria | Evaluator-optimizer loop | Best accuracy; quadratic cost risk |
| Long-horizon, open-ended tasks | Hierarchical + memory layer + external state machine | Most expensive; compaction/forgetting risks |
| Enterprise regulated workflows | Graph-based with HITL approval gates | Compliance requires human checkpoints |
| Internal tooling/code migration | Narrow domain agents (Uber-style) | Domain-specific beats general-purpose |

## 10. Production Principles That Held Across All Evidence

Across Anthropic, OpenAI, IBM/UC Berkeley, LangGraph case studies, and COLM 2026 research, five principles emerge consistently:

1. **Simplicity first**: *"Start with simple prompts, optimize them with comprehensive evaluation, and add multi-step agentic systems only when simpler solutions fall short"* [source-fd454bb64b30]
2. **Externalize verification**: Never let the LLM grade its own homework. Require tool-based evidence before exit. FM-3.3 (Incorrect Verification) is the universal failure predictor [source-34cd27d84517]
3. **Measure at the task level, not the component level**: Per-token pricing is misleading; a more expensive model may be cheaper per completed task [source-e08d41689c31]
4. **Architectural fixes beat prompt engineering 3:1**: Prompt engineering yields ~16% improvement; structural interventions (state machines, summarizer agents, memory layers) yield 53%+ [source-34cd27d84517]
5. **Single-agent first**: Default to single-agent, measure baseline, and only add coordination overhead when parallelization benefit is demonstrated [source-9ad9a91d571d]

## Sources

- **[source-fd454bb64b30]** [Anthropic: Building Effective Agents](https://www.anthropic.com/research/building-effective-agents) - tier 3
  - Anthropic's definitive guide to effective agents, distilling learnings from working with dozens of enterprise teams. Establishes a taxonomy of workflows (predictable, deterministic) vs. agents (dynamic, LLM-driven). Recommends five core patterns: prompt chaining, routing, parallelization, orchestrator-workers, and evaluator-optimizer. Stresses simplicity, composability, and the principle that added complexity should only come when it demonstrably improves outcomes.
- **[source-0a68d2505426]** [AI Agent Architectures: Efficiency vs. Scaling Limits in 2026 – Monolithic, Workflow, and Skill-Based Systems Compared](https://beta.hyper.ai/en/stories/53d4fafdd3b77c15bc7008b4122bc84c) - tier 3
  - IBM Research & UC Berkeley analysis using MAST taxonomy on 310 ITBench SRE traces across Gemini-3-Flash, Kimi-K2, and GPT-OSS-120B. Key findings: frontier models fail cleanly (2.6 failure modes/trace) vs. cascading failures in open models (5.3/trace). Strongest predictor of failure is FM-3.3 Incorrect Verification. Architectural fixes (summarizer agents, state machines) yield up to 53% improvement vs ~16% from prompt engineering. Kimi-K2 has 92% failure prevalence of reasoning-action mismatch. GPT-OSS-120B loses conversation history in 24% of traces.
- **[source-908c8bdf3568]** [LangGraph Agents in Production: Architecture, Costs & Real-World Outcomes](https://www.alphabold.com/langgraph-agents-in-production/) - tier 3
  - ZenML case study summarizing Anthropic's Applied AI team learnings from building Claude Code and supporting enterprise customers throughout 2024-2025. Key production insights: context rot kicks in at 50-150K tokens; workflows lack error recovery for open-ended tasks; cost should be measured per task not per token; sub-agents work for exploration but Claude struggles with concurrent task decomposition; progressive disclosure in tool design prevents context bloat.
- **[source-b12883165ced]** [Top 5 LangGraph Agents in Production 2024 (Replit, LinkedIn, Uber, Elastic, AppFolio)](https://blog.langchain.com/top-5-langgraph-agents-in-production-2024/) - tier 3
  - Production case studies from 2024 showing LangGraph adoption. Key stories: Replit built agents with human-in-the-loop and multi-agent setup; LinkedIn built SQL Bot as a multi-agent system on LangGraph for internal data access; Uber used it for large-scale code migrations; AppFolio's Realm-X saved property managers 10+ hours/week; Elastic migrated from LangChain to LangGraph for their AI assistant. All emphasize controllability and narrow scope over fully autonomous systems.
- **[source-96171c4fbcbc]** [AI Agent Systems: Architectures, Applications, and Evaluation](https://arxiv.org/html/2601.01743v1) - tier 2
  - HORIZON benchmark paper studying long-horizon agent failure modes across 3100+ trajectories using GPT-5 variants and Claude-4 across Web, OS, Embodied, and Database domains. Key findings: performance drops non-linearly with horizon, all models converge toward failure at high horizons, planning failures and catastrophic forgetting are dominant modes, and model scaling alone is insufficient to address these issues. Recommends hierarchical subplanning, execution-time plan verification, and memory mechanisms that preserve long-range constraints.
- **[source-a707c1177078]** [OpenAI for Developers in 2025](https://developers.openai.com/blog/openai-for-developers-2025) - tier 3
  - OpenAI's end-of-2025 developer retrospective. Key shifts: reasoning became a core dial (o1, o3, o4-mini then converged into GPT-5 family); agent-native APIs (Responses API, Agents SDK, AgentKit); prompt caching, background mode, and webhooks addressed cost/latency for long-running agents; MCP and AGENTS.md enabled interoperability. GPT-5.2-Codex emerged as default for coding agents and repo-scale reasoning.
- **[source-410e55d101c2]** [AI Agent Architectures: Efficiency Gains Meet Scaling Limits (Cobus Greyling, Jan 2026)](https://cobusgreyling.medium.com/ai-agent-architectures-b176ada8b78b) - not-tiered
  - Monolithic, workflow, skill-based systems compared for enterprise production
- **[source-28d379e998d4]** [AWS Prescriptive Guidance: LangChain and LangGraph](https://docs.aws.amazon.com/prescriptive-guidance/latest/agentic-ai-frameworks/langchain-langgraph.html) - tier 3
  - AWS Prescriptive Guidance on LangChain and LangGraph. Highlights LangGraph for complex stateful workflows as state machines. Real-world case: Vodafone used LangChain and LangGraph for multi-agent data engineering orchestration, deploying modular sub-agents for collection, processing, summarization, and reasoning tasks integrated via APIs into cloud systems.
- **[source-65a084c5782d]** [Deep Research Agents: A Systematic Examination And Roadmap](https://arxiv.org/html/2506.18096v2) - tier 2
  - A systematic survey defining Deep Research (DR) agents: LLM-powered systems integrating dynamic reasoning, adaptive planning, and iterative tool use for open-ended research. Covers 40+ systems (Search-o1, R1-Searcher, DeepResearcher, WebDancer, Kimi-Researcher, etc.), classifying them by workflow (static vs. dynamic), planning strategy, and agent architecture (single vs. multi-agent). Explicitly connects DR agents to the ReAct framework lineage and covers RL-based tuning (GRPO, PPO) as the dominant optimization paradigm.
- **[source-b1fcae9e7c33]** [Agentic Large Language Models, a survey (2025)](https://arxiv.org/html/2503.23037) - tier 1 - peer-reviewed
  - Comprehensive survey of agentic LLMs organized around three pillars: reason, act, interact. Provides a detailed taxonomy from CoT through ReAct/Reflexion to DeepSeek-R1 and discusses how test-time compute (RLVR, GRPO) creates implicit reasoning. Notes that self-reflective agents and inference-time compute generate new training states.
- **[source-a5f1d4748c2b]** [The Dawn of GUI Agent: A Preliminary Case Study with Claude 3.5 Computer Use](https://arxiv.org/html/2411.10323) - tier 2
  - Case study of Claude 3.5 Computer Use — the first frontier AI model to offer GUI-level computer use as a public beta. Studies end-to-end language-to-desktop automation across web, office, workflow, and gaming domains. Evaluates on three dimensions: Planning, Action, and Critic. Explicitly connects Claude Computer Use's reasoning to a ReAct-style paradigm with selective observation.
- **[source-d50be42998da]** [Voyager: An Open-Ended Embodied Agent with Large Language Models](https://arxiv.org/html/2305.16291) - tier 1 - peer-reviewed
  - Voyager introduces the first LLM-powered embodied lifelong learning agent with: (1) automatic curriculum, (2) ever-growing skill library of executable code, (3) iterative prompting with environment feedback. Achieves 3.3× more unique items than prior SOTA in Minecraft. Bypasses gradient-based training entirely.
- **[source-8d2d98de06d3]** [SoK: Agentic Skills — Beyond Tool Use in LLM Agents (2026)](https://arxiv.org/html/2602.20867v1) - tier 2
  - Systematic review of agentic skills as a distinct layer beyond tool use. Defines skills as 4-tuple (applicability condition, policy, termination condition, callable interface). Identifies 7 design patterns (metadata-driven, code-as-skill, self-evolving, marketplace, etc.). Key finding: curated skills raise pass rates by 16.2pp while self-generated skills degrade by 1.3pp. Maps Voyager, Reflexion, SWE-agent to the skill lifecycle.
- **[source-0598a43228cd]** [Competitive Programming with Large Reasoning Models (OpenAI o1/o3)](https://arxiv.org/html/2502.06807) - tier 2
  - Documents that RL applied to LLMs significantly boosts performance on complex coding/reasoning. o3 achieves IOI gold medal without hand-crafted domain-specific strategies. Complex test-time reasoning strategies (brute-force verification, self-checking) emerged naturally from end-to-end RL training. Shows that scaling general-purpose RL outperforms domain-specific pipelines.
- **[source-051bba93deec]** [Agent Skills for Large Language Models: Architecture Survey (2026)](https://arxiv.org/html/2602.12430) - tier 2
  - First focused survey on the agent skills paradigm, covering Anthropic's October 2025 launch of Agent Skills, the SKILL.md specification, progressive disclosure architecture, MCP integration, RL-based skill acquisition (SAGE), and autonomous skill discovery (SEAgent). Security analysis reveals 26.1% of community skills contain vulnerabilities. On benchmarks: OSWorld results have climbed from single digits to beyond human-level (72.6% vs 72.36% human).
- **[source-4306914e2135]** [Reason-Plan-ReAct: A Reasoner-Planner Supervising a ReAct Executor for Complex Enterprise Tasks](https://arxiv.org/html/2512.03560v1) - tier 2
  - Introduces RP-ReAct: a multi-agent architecture that decouples a Reasoner-Planner Agent (RPA, uses LRM for high-level planning) from Proxy-Execution Agents (PEA, uses ReAct for tool interactions). Evaluated against ReAct and Reflexion baselines on ToolQA. Shows that for hard tasks, the planner-executor separation is crucial for trajectory stability. Reflexion performs worst overall despite self-correction capabilities.
- **[source-a0debd7afcd8]** [Benchmarking Multi-Agent LLM Architectures for Financial Document Processing](https://arxiv.org/html/2603.22651) - tier 2
  - Comprehensive benchmark of four multi-agent orchestration patterns (sequential pipeline, parallel fan-out, hierarchical supervisor-worker, reflexive self-correcting) for financial document processing. Hierarchical wins on cost-accuracy Pareto frontier; reflexive gets highest accuracy but degrades at scale.
- **[source-0a54b8023afa]** [Exploring Advanced LLM Multi-Agent Systems Based on Blackboard Architecture](https://arxiv.org/html/2507.01701) - tier 2
  - Proposes bMAS (blackboard-based LLM multi-agent system) with three components: control unit, blackboard, and LLM agents. Achieves competitive performance with SOTA static/dynamic MASs while consuming fewer tokens. The blackboard serves as shared memory, enabling dynamic agent selection.
- **[source-65a68695ba66]** [Gradientsys: A Multi-Agent LLM Scheduler with ReAct Orchestration](https://arxiv.org/html/2507.06520) - tier 2
  - Gradientsys uses a centralized LLM scheduler with ReAct-based reasoning loop and typed MCP tool registry. Achieves 60% relative improvement over GPT-4 baseline on GAIA, 4.3x faster and 3.3x cheaper than Genspark. Hybrid sync/async execution with parallel agent dispatch.
- **[source-fae84a9a679a]** [LLM-Based Multi-Agent Blackboard System for Information Discovery in Data Science](https://arxiv.org/abs/2510.01285) - tier 2
  - LLM-Based Multi-Agent Blackboard System for Information Discovery in Data Science. Framework where central agent posts requests to shared blackboard and autonomous subordinate agents volunteer to respond based on their capabilities. 13%-57% improvement over baselines.
- **[source-4d77c2e0bb58]** [Agent Architecture Patterns: 2026 Taxonomy Guide](https://www.digitalapplied.com/blog/agent-architecture-patterns-taxonomy-2026) - tier 3
  - 2026 taxonomy of 8 agent architecture patterns across 4 quadrants. Hierarchical and graph topologies dominate production; swarm/blackboard reserved for exploratory use. Framework support matrix for LangGraph, AutoGen, CrewAI, OpenAI Agents SDK, Microsoft Agent Framework.
- **[source-95e96bc50cd2]** [Choosing the right orchestration pattern for multi-agent systems - Kore.ai](https://www.kore.ai/blog/choosing-the-right-orchestration-pattern-for-multi-agent-systems) - tier 3
  - Kore.ai practitioner guide covers three orchestration patterns: supervisor (hierarchical), adaptive agent network (decentralized/peer-to-peer), and custom (programmatic). Concrete enterprise use cases in banking and payroll with guidance on when to use or avoid each pattern.
- **[source-522b01d1048b]** [Agent Orchestration Patterns: Swarm vs Mesh vs Hierarchical](https://gurusup.com/blog/agent-orchestration-patterns) - tier 3
  - Covers five orchestration patterns: orchestrator-worker, swarm, mesh, hierarchical, and pipeline. Comparison matrix of control/scalability/fault tolerance/debugging difficulty. Hybrid patterns common in production. Framework mappings (LangGraph, AutoGen, CrewAI).
- **[source-116911c8c692]** [Project Synapse: Hierarchical Multi-Agent Framework with Hybrid Memory for Autonomous Resolution of Last-Mile Delivery Disruptions](https://arxiv.org/html/2601.08156) - tier 2
  - Project Synapse: hierarchical multi-agent framework with hybrid memory (working/episodic/semantic) for last-mile delivery disruptions. Orchestrated via LangGraph. Achieves 0.85 overall score vs 0.60 for single-agent ReAct. Demonstrates production deployment of supervisor-worker pattern with MCP toolkit.
- **[source-e9186147171a]** [ReAct: Synergizing Reasoning and Acting in Language Models (Yao et al., 2022)](https://arxiv.org/abs/2210.03629) - tier 2 - peer-reviewed
  - The original ReAct paper proposes interleaving reasoning traces and task-specific actions. Benchmarked on HotpotQA, FEVER, ALFWorld, and WebShop. Shows grounding reduces hallucination.
- **[source-c60f502757fa]** [Reflexion: Language Agents with Verbal Reinforcement Learning (Shinn et al., 2023)](https://arxiv.org/abs/2303.11366) - tier 2 - peer-reviewed
  - Reflexion reinforces language agents through verbal reinforcement learning. Agents maintain episodic memory of self-reflections. Achieves 91% pass@1 on HumanEval coding benchmark, surpassing GPT-4's 80%.
- **[source-afa1bb25e152]** [ReWOO: Decoupling Reasoning from Observations for Efficient Augmented Language Models (Xu et al., 2023)](https://arxiv.org/abs/2305.18323) - tier 2
  - ReWOO proposes decoupling reasoning from tool observations. The Planner generates one plan, Workers execute tools (possibly in parallel), Solver synthesizes. Achieves 5x token efficiency and 4% accuracy improvement on HotpotQA. Enables offloading reasoning to smaller models.
- **[source-84e431767d1f]** [Single-Agent Patterns: ReAct, Plan-and-Execute, ReWOO, and Reflexion (The AI Engineer, 2025)](https://theaiengineer.substack.com/p/the-4-single-agent-patterns) - tier 3
  - Comprehensive practitioner comparison of all four patterns. Covers token economics, failure modes, production trade-offs, hybrid approaches, and decision flowchart. Includes 2025-era production replication notes on Reflexion limitations.
- **[source-0f6e6c1f0f7f]** [AWS Blog: Customize agent workflows with Strands Agents (ReAct vs ReWOO vs Reflexion on τ-Bench, 2025)](https://aws.amazon.com/blogs/machine-learning/customize-agent-workflows-with-advanced-orchestration-techniques-using-strands-agents/) - tier 3
  - AWS blog post comparing ReAct, ReWOO, and Reflexion head-to-head on the τ-Bench airline domain dataset (300+ flights, 50 structured scenarios). Shows distinct performance profiles across 4 worked examples. Introduces hybrid ReWOO-guided ReAct.
- **[source-d8016fb06ab8]** [GAP: Graph-Based Agent Planning with Parallel Tool Use and Reinforcement Learning (Wu et al., 2025)](https://arxiv.org/abs/2510.25320) - tier 2 - peer-reviewed
  - GAP is a 2025 evolution beyond ReAct that uses graph-based planning + RL to model inter-task dependencies. Enables parallel and serial execution, trained with SFT then RL. Significantly outperforms ReAct on MHQA benchmarks.
- **[source-ce0f969cce5c]** [Your ReAct Agent Is Wasting 90% of Its Retries (Towards Data Science, 2025)](https://towardsdatascience.com/your-react-agent-is-wasting-90-of-its-retries-heres-how-to-stop-it/) - tier 4
  - Deterministic simulation of 200 tasks shows 90.8% of ReAct retries wasted on hallucinated tool names. Proposes error taxonomy, per-tool circuit breakers, and deterministic routing as fixes.
- **[source-86f4868be35b]** [Understanding Multi-Agent LLM Frameworks: A Unified Benchmark (MAFBench, 2026)](https://arxiv.org/abs/2602.03128) - tier 2
  - MAFBench (2026) introduces unified multi-agent LLM framework benchmark. Finds framework-level architectural choices alone cause massive performance variation: 100x latency differences, 30% planning accuracy reduction, coordination success from >90% to <30%.
- **[source-7ecca2f03900]** [EcoGym: Evaluating LLMs for Long-Horizon Plan-and-Execute in Interactive Economies (2026)](https://arxiv.org/abs/2602.09514) - tier 2
  - EcoGym (2026) benchmarks Plan-and-Execute across three long-horizon interactive economic environments (Vending, Freelance, Operation, 1000+ steps). Exposes systematic tension: no single model dominates; models show suboptimality in either high-level strategies or efficient action execution.
- **[source-b8b0b17f6e51]** [Agentic AI Design Patterns: ReAct, ReWOO, CodeAct, and Beyond (Capabl, 2025)](https://capabl.in/blog/agentic-ai-design-patterns-react-rewoo-codeact-and-beyond) - tier 4
  - Practitioner overview of ReAct, ReWOO, CodeAct, Reflexion patterns with hybrid design guidance. Notes ReWOO 5-10x token reduction vs complex ReAct trace. Introduces CodeAct (code execution as tool) as emerging pattern. Highlights security risks of arbitrary code execution.
- **[source-dc2e29a1e7e9]** [From LLM Reasoning to Autonomous AI Agents: A Comprehensive Review (Ferrag et al., 2025/2026)](https://arxiv.org/abs/2504.19678) - tier 2
  - Comprehensive review of LLM reasoning to autonomous AI agents covering benchmarks 2019-2025 and frameworks 2023-2025. Discusses failure modes, multi-step reasoning, collaboration protocols (ACP, MCP, A2A), and dynamic tool integration via RL.
- **[source-e9351405b42a]** [HORIZON: Long-Horizon Agent Failure Modes (GPT-5, Claude-4, 3100+ trajectories)](https://arxiv.org/html/2604.11978v1) - tier 1 - peer-reviewed
  - HORIZON benchmark paper (COLM 2026) studying long-horizon agent failures across GPT-5 variants and Claude-4 in 3100+ trajectories. Main findings: performance drops non-linearly with horizon, not gradually. Planning failures and catastrophic forgetting dominate at long horizons. Model scaling alone is insufficient—architectural changes needed. Real-world case: long-running email agent ignored safety constraints after hundreds of turns due to effective inattention rather than memory loss.
- **[source-9ad9a91d571d]** [Redis: Why Multi-Agent LLM Systems Fail and How to Fix Them](https://redis.io/blog/why-multi-agent-llm-systems-fail/) - tier 3
  - Redis technical blog on why multi-agent LLM systems fail. Key failures: error compounding in sequential pipelines is silent; monoculture problem when same model plans and verifies; context rot from the lost-in-the-middle effect; stale shared state. Design patterns: start with single agent, validate at every boundary, checkpoint state durably, invest in observability, treat prompts as reliability levers. In 180-config evaluation, multi-agent variants underperformed single-agent due to communication overhead.
- **[source-e08d41689c31]** [Anthropic Applied AI: Building Production AI Agents (ZenML Case Study)](https://www.zenml.io/llmops-database/building-production-ai-agents-lessons-from-claude-code-and-enterprise-deployments) - tier 3
  - Detailed ZenML case study of Anthropic's production agent learnings from Claude Code and enterprise customers. Key findings: context rot at 50-150K tokens; workflows lack error recovery; LLMs poor at concurrent sub-task decomposition; cost evaluation at task level not token level; progressive disclosure for tool design; 90% of failures traced to poor prompt quality.
- **[source-b9a4a1280b6a]** [Galileo: The Hidden Costs of Agentic AI – Why 40% of Projects Fail Before Production](https://galileo.ai/blog/hidden-cost-of-agentic-ai) - tier 3
  - Galileo's analysis of hidden costs in agentic AI. Key data: Gartner predicts 40%+ agent projects won't reach production by 2027. Complex agents consume 5-20x more tokens than simple chains. Session costs range from $0.014 (DeepSeek-v3) to $0.239 (Grok-4). High-performing agents incur 10-50x more tokens per task. GPT-4.1 achieves 62% action completion vs 56% for GPT-4.1-mini but at 5x the cost. Hybrid routing can reduce costs 30-50%.
- **[source-53245d0a003b]** [Stevens: Hidden Economics of AI Agents – Token Costs and Latency Trade-offs](https://online.stevens.edu/blog/hidden-economics-ai-agents-token-costs-latency/) - tier 3
  - Stevens online analysis of hidden economics of AI agents. Key: single LLM call ~800ms vs orchestrator-worker with Reflexion loop 10-30 seconds. A 10-cycle Reflexion loop consumes 50x tokens. Unconstrained coding agents cost $5-8 per task. Prompt caching reduces input costs ~90% and latency ~75%. Memory layer plan caching can cut latency from 30 seconds to 300ms. Routing patterns match complexity to compute tier.
- **[source-68ee983bc61f]** [Architecting Agentic Communities using Design Patterns (UNSW, 2026)](https://arxiv.org/html/2601.03624) - tier 2
  - 46 agentic AI design patterns in three tiers. Blackboard and Orchestration are formal Agentic Community patterns. Includes formal ODP-EL governance. Clinical trial matching case study using 15 patterns. Production deployments in mining/oil&gas/manufacturing validated.
- **[source-7656adf55900]** [Top 5 LangGraph Agents in Production 2024 - LangChain Blog](https://blog.langchain.com/top-5-langgraph-agents-in-production-2024/) - tier 3
  - LangChain's roundup of top 5 production LangGraph agents in 2024: Replit (multi-agent with HITL), LinkedIn SQL Bot (multi-agent natural language interface), Uber (code migration agents), AppFolio Realm-X (property management copilot), Elastic (AI assistant). All feature controllable, vertical architectures.
- **[source-03b4d4de3350]** [DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning (2025, Nature)](https://arxiv.org/html/2501.12948) - tier 2
  - DeepSeek-R1 (January 2025, 5404+ citations) demonstrates that pure RL can incentivize reasoning in LLMs without human-labeled trajectories. The RL framework facilitates emergent development of self-reflection, verification, and dynamic strategy adaptation. Performance surpasses models trained on human demonstrations on math, coding, and STEM tasks. Became a foundational paper for the agentic RL model paradigm.
- **[source-6a29fe8ff079]** [Sleep-time Compute: Beyond Inference Scaling at Test-time (2025)](https://arxiv.org/abs/2504.13171) - not-tiered
  - Allows models to think offline before queries are presented, reducing test-time compute by ~5x. Extends the test-time compute scaling paradigm.
- **[source-34cd27d84517]** [IBM Research & UC Berkeley: MAST Failure Taxonomy on ITBench (NeurIPS 2025)](https://huggingface.co/blog/ibm-research/itbenchandmast) - tier 1 - peer-reviewed
  - IBM Research & UC Berkeley analysis using MAST taxonomy applied to 310 ITBench SRE traces. Results: Gemini-3-Flash (75.5% recall) fails cleanly with 2.6 failure modes per trace; GPT-OSS-120B (12.4% recall) has 5.3 cascading failure modes per trace. Strongest predictor: FM-3.3 Incorrect Verification. Architectural fixes outperform prompt engineering by 3x. Key takeaways: externalize verification, implement finite state machines for termination, treat clarification as a first-class branch.

