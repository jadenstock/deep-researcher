# Research report

**Query:** What are the best methods for agent auto improvement (or self improvement). Which aspects of the agent are most amenable to improvement. What conditions must be true for good agent self improvement. Which cases are not good for agent self improvement. Our agent supports a variety of use cases such as literature search or database exploration. It supports a variety of internal users and use cases. How does the agent self improvement literature deal with a variety of agent architectures. does it handle single agent and mult-agent?

# Agent Self-Improvement: Methods, Components, Conditions, and Architecture Coverage

**Bottom line.** The literature offers a mature toolkit for agent self-improvement — prompt optimization, memory/trajectory learning, fine-tuning on traces, multi-agent co-evolution — and the layers most amenable to improvement (prompts, tool descriptions, memory, workflow) are well-served by working frameworks. For an enterprise agent serving heterogeneous internal users across literature search, database exploration, and similar use cases, the recommended posture is a **three-track program**: (1) per-use-case domain-native reward signals (execution accuracy for SQL, citation-link recall for literature search), (2) a tiered partitioned memory architecture (per-user / per-use-case / shared strategic), and (3) outer-loop prompt/tool optimization with explicit eval gates and rollback. The literature handles single-agent and multi-agent architectures, but a strong recent finding ([source-1dd90a25bd55] et al.) is that *homogeneous* multi-agent workflows (same base LLM across roles) can usually be collapsed to a single-agent multi-turn loop without performance loss — meaning architecture choice is more often a cost/coordination question than a capability question. The principal caveats: most of the strongest empirical results are arXiv preprints, several load-bearing claims rest on single sources, and domain-specific evidence for literature-search agents specifically is thin.

---

## 1. Best Methods for Agent Self-Improvement

The field has converged on six method families, each with a different mechanism and best-fit regime [source-9294862bafd2, source-77905a41db18, source-459320f34f27, source-be6dd8001b75, source-e1292788b637, source-c5fbccc7ff38, source-b6054f4cb35a, source-935e1b3fd2bc, source-8eaa5b383bf0, source-a5427a16cef6].

| Method family | Mechanism | Best for | Key risk |
|---|---|---|---|
| **Test-time self-refinement** (Reflexion, Self-Refine, TextGrad-instance) | Iterate critique→revise within one inference session; no weight updates | Single hard problems with strong base model | Bounded by base-model knowledge; prompt-only refinement *degrades* weak models [source-77905a41db18] |
| **Automated prompt optimization** (DSPy/MIPROv2, TextGrad, OPRO, GEPA) | Treat prompts as optimizable parameters; bootstrap demos / search instructions against a metric | Multi-step pipelines with labeled trainsets; production CI/CD | Metric quality determines improvement; "textual gradient" framing is mechanistically suspect [source-ae71b5a9347c] |
| **Experience / trajectory memory** (MUSE, Trajectory-Informed, MemRL) | Distill reusable lessons from execution traces; retrieve at runtime | Long-horizon tool use; closed-source APIs; model-agnostic transfer | Naive accumulation → error propagation, "self-degradation" [source-225fbca8e970, source-e1292788b637] |
| **Skill acquisition / continual learning** (Voyager-style, SkillLearnBench) | Build a verified, indexed library of executable skills | Open-ended environments; agents expected to grow capability over time | Catastrophic forgetting; library-scaling collapse [source-7d3e99d3d27b, source-612c4a2967f4] |
| **Fine-tuning on traces** (RISE, TT-SI) | Fine-tune on on-policy multi-turn rollouts that show recovery from mistakes | Reasoning tasks with verifiable answers (math, code) | Cannot recover knowledge that's absent; on-policy data collection is essential [source-77905a41db18, source-459320f34f27] |
| **Multi-agent co-evolution** (MAE: Proposer/Solver/Judge) | RL-train a single backbone in differentiated roles; adversarial-cooperative dynamic generates curriculum | General-domain improvement without labels; scaling beyond human annotation | Quality filtering critical or Proposer generates degenerate questions [source-be6dd8001b75] |

**Methodological caveat to surface.** A 2025 critique [source-ae71b5a9347c] argues the "textual gradient" metaphor underlying TextGrad/OPRO/ProTeGi is mechanistically wrong: inverted/adversarial feedback does *not* degrade test-time accuracy, and overfitting is not observed — both violations of true gradient dynamics. The methods still work (via LLM generalization and instruction-following), but practitioners should not transfer numerical-optimization intuitions like learning rate or momentum. This is currently a single-source preprint claim and warrants independent replication, but the empirical findings it reports are testable.

**A real and unresolved disagreement:** parametric vs. non-parametric self-improvement. RISE [source-77905a41db18] argues prompting-only self-refinement is insufficient — only fine-tuning instills durable self-correction. MUSE [source-c5fbccc7ff38] and MemRL [source-21251e985b38] reach SOTA *without* fine-tuning, using frozen backbones plus structured memory. They target different layers, so they are not strictly competing — but the design question for a deployed system (do we update weights or just memory?) is genuinely contested.

---

## 2. Which Aspects of an Agent Are Most Amenable to Improvement

Components vary substantially in self-improvement maturity [source-9294862bafd2, source-d03b097fd3b5, source-21251e985b38, source-1e7797f8acc0, source-77905a41db18, source-82577ab38772]:

| Layer | Maturity | Best techniques | Primary failure mode |
|---|---|---|---|
| **Prompts / instructions** | **High** (production) | DSPy/MIPROv2, GEPA, TextGrad, OPRO | Long-prompt brittleness; gradient-metaphor artifacts |
| **Tool selection & descriptions** | **Moderate-High** | JTPRO (joint prompt+schema reflection) | Selection accuracy collapses with large tool inventories; slot-filling errors dominate even when selection is correct [source-d03b097fd3b5] |
| **Memory / knowledge store** | **Moderate-High** | MemRL (RL over episodic memory), MemGPT, Reflexion, hierarchical memory (MUSE) | Self-reinforcing reflection errors that scale with agent lifetime; silent orchestration failures [source-82577ab38772] |
| **Workflow / orchestration** | **Moderate** (task-specific) | ComfyGPT (SFT+GRPO), AFlow/ADAS search, FlowReasoner | Node hallucination; diversity collapse from RL; coordination overhead |
| **Model weights** | **Moderate** (compute-constrained) | RISE, TT-SI, GRPO/RAGEN | Knowledge-limit wall; requires on-policy data; catastrophic forgetting |
| **Architecture itself** | **Low** (mostly experimental) | ADAS/AFlow MCTS search, Darwin Gödel Machine, evolutionary multi-agent | Search-space explosion; recursive instability; safety-bypass risk |

**Most important cross-layer lesson — JTPRO [source-d03b097fd3b5].** Optimizing prompts alone *while leaving tool schemas static* is insufficient when the tool inventory is non-trivial: "global policies depend on tool-local distinctions, and accurate slot/value instantiation relies on global conventions." On 1000-tool benchmarks, JTPRO's joint prompt+schema optimization beats GEPA (prompt-only) by 5–20% relative, and corrects 21–23% of slot/value errors. For an agent serving database exploration with many tables/queries plus literature search with citation/search APIs, this argues against treating prompt optimization and tool-description curation as separate workstreams.

**Most overrated layer:** Architecture-level self-modification (Gödel Agent, AlphaEvolve) is largely aspirational outside narrow algorithmic problems. ComfyGPT's ablation suggests architecture-rewrite components contribute the smallest marginal gain among layers tested.

---

## 3. Conditions for Good Self-Improvement (and When to Avoid It)

### Necessary preconditions
Drawing on the ICLR 2026 workshop framing [source-b53ee8bb1ae0] and empirical sources:

1. **Verifiable, gameable-resistant reward signal.** Domain-native automatic rewards (execution accuracy for SQL [source-97f3faa53876], citation-link recall for literature search [source-b8103ab22a08]) are far better than generic LLM-as-judge. Reward hacking / proxy-metric gaming is a documented production failure mode [source-61bdda249780].
2. **Sufficient task diversity.** Without it, agents in-benchmark-overfit rather than developing transferable capability [source-b53ee8bb1ae0].
3. **Stable, regression-aware evaluation.** Multi-grader stacks with hold-out sets; longitudinal monitoring; layered verification (low-level correctness *and* high-level objective). MAST data shows superficial verifiers cause systematic failure modes (FM-3.2, ~8% prevalence) [source-9e53581b3ffd].
4. **Closed-loop execution with auditable memory.** Memory must be inspectable, scope-limited, and curated — naive accumulation produces measurable performance decline (an "all-add" strategy reaches 18.1% contradiction rate vs 1.2% for hybrid decay; 65.2% vs 92.5% task completion over 500 turns [source-225fbca8e970]).

### Failure modes (real and present in current systems)

- **Misaligned experience replay / self-degradation.** Bounded-memory networks suffer catastrophic interference when flawed memories are stored indiscriminately. Quality-aware curation, similarity gating, and decay are not optional [source-225fbca8e970, source-e1292788b637].
- **Coordination failures in MAS.** MAST analyzed 1,642 traces across 7 frameworks and found 41–86.7% failure rates, with coordination/design issues (44.2%) dominating individual-agent limits [source-9e53581b3ffd]. Independent multi-agent systems amplify trace-level errors 17.2× without cross-checking; centralized orchestration reduces this to 4.4× [source-8376fb13a30c, source-6bcde9b07680].
- **Memory poisoning / security amplification.** Microsoft documented an email-agent attack where increasing the agent's reliance on its own memory raised attack success from 40% to 80%+ [source-3bc6fdee1c6b]. **The mechanism that makes self-improvement useful (memory) is also what amplifies attack surface.** Memory hardening — trust boundaries, authenticated memorization, comprehensive logging — is essential.
- **Reward hacking, brittle self-edits, regressions, runaway recursion.** Catalogued as the canonical failure modes of self-improving systems by ICLR 2026 [source-b53ee8bb1ae0]; "prompt storms" and runaway recursion specifically called out by OWASP-aligned agent risk taxonomies [source-61bdda249780].

### A real disagreement in the safety framing

The cautious literature (ICLR 2026 RSI workshop [source-b53ee8bb1ae0]; Anthropic alignment-faking work [source-58d3c55fd7df, single-source preprint]; Microsoft taxonomy [source-3bc6fdee1c6b]) emphasizes alignment faking, runaway capability spirals, and strategic self-preservation. The **adversarial counter-case** [from our adversarial dispatch] is that these are largely **frontier-training / future-AGI concerns being miscategorized as present-day enterprise risks**:

- Production self-improvement (DSPy compilation, OpenAI cookbook retraining, MemRL-style runtime memory) is *outer-loop optimization* against fixed evals with bounded retries and rollback — architecturally not the recursive-self-redesign regime that motivates RSI alarm.
- The Anthropic alignment-faking result specifically requires a model informed about its training conditions and under RL pressure — not a memory-curation or prompt-search loop. Treating it as evidence against ordinary enterprise loops is a scope error.
- Empirically, MUSE achieves >10pp gain over a memory-less baseline through repeated experience accumulation [source-c5fbccc7ff38]; trajectory-informed memory yields +14.3pp on held-out scenarios [source-e1292788b637]; DSPy raises ReAct from 24% to 51% in ~$2 of optimization [source-935e1b3fd2bc] — all without the catastrophic failure modes the cautious literature emphasizes.

**Synthesis.** Both framings have merit. The *real* present-day risks for enterprise agents are: regression after a bad prompt edit, misaligned experience replay, schema/tool drift, retrieval errors, cost blowups from over-active loops, and **memory poisoning as a security vector** [source-3bc6fdee1c6b]. These are serious but they are reliability-engineering problems, addressable with versioning, rollback, evals, and access control. The headline RSI/alignment risks are mostly relevant to frontier-model training and high-autonomy agents, not to outer-loop prompt/memory optimization. The cautious framing's *operational* recommendations (rollback triggers, improvement-operator cards, audit logging) remain sound; its *threat model* should be calibrated to the actual deployment.

### When NOT to use self-improvement

- **High-stakes regulated domains without human approval gates.** Healthcare diagnostics, financial/legal recommendations, safety-critical control. Self-improvement should be restricted to suggestion + human-promotion workflows, not autonomous deployment [source-b53ee8bb1ae0, source-3bc6fdee1c6b].
- **Sequential non-parallelizable tasks via multi-agent decomposition.** Google Research's controlled study found *every* multi-agent architecture degraded sequential planning (PlanCraft) by 39–70%; single-agent was strictly preferred [source-6bcde9b07680, source-8376fb13a30c].
- **Tasks where single-agent baseline already exceeds ~45% accuracy.** Capability-saturation regime: coordination overhead exceeds diminishing returns. Stay single-agent and optimize prompts/memory only [source-8376fb13a30c].
- **Sparse-feedback contexts.** When ground-truth feedback is rare or delayed, the improvement loop operates on noise — exactly the conditions for misaligned experience replay [source-b53ee8bb1ae0].
- **Knowledge-absent tasks (for weight-level RISE-style methods).** "For knowledge-based question answering, it is not possible for the model to produce any meaningful improvements... Training with RISE would likely incentivize hallucinations" [source-77905a41db18].
- **Sequential multi-tool workflows requiring multi-step dependencies (for JTPRO-style optimization).** This was an explicit gap in JTPRO's evaluation [source-d03b097fd3b5].
- **Database environments with restricted execution access.** SQL-Trail-style multi-turn RL requires interactive query execution — infeasible in many enterprise settings with privacy controls or expensive queries [source-97f3faa53876].

### Practical guardrails (drawn from multiple sources)

| Mechanism | Source |
|---|---|
| Versioned prompts/models with revert-to-last-known-good | [source-61bdda249780, source-3c599452cdff] |
| Rollback-on-regression with explicit upfront criteria | [source-b53ee8bb1ae0] |
| Circuit breakers / rate limiting against runaway recursion | [source-61bdda249780] |
| Confidence/uncertainty-gated updates | [source-b53ee8bb1ae0] |
| Authenticated memorization (external validation for memory writes) | [source-3bc6fdee1c6b] |
| Memory hardening with trust boundaries, role-based access | [source-3bc6fdee1c6b, source-9ee733613685] |
| Multi-level verification (correctness *and* objective) | [source-9e53581b3ffd] |
| HITL approval gate before promoting changes to production | [source-3c599452cdff, source-5cb9e059f53c] |

---

## 4. How the Literature Handles Different Agent Architectures (Single vs. Multi-Agent)

### Architecture-agnostic vs architecture-specific methods

**Architecture-agnostic** (apply to both): iterative refinement, prompt optimization (DSPy, TextGrad, GEPA, MetaPrompt), trajectory/memory learning (MUSE, MemRL, trajectory-informed), RL with outcome rewards [source-9294862bafd2, source-21251e985b38, source-c5fbccc7ff38, source-5cb9e059f53c].

**Architecture-specific (require multi-agent structure):**
- Co-evolution with differentiated roles like MAE's Proposer/Solver/Judge — the adversarial-cooperative dynamic where one agent's reward depends on another's failure cannot be replicated single-loop [source-be6dd8001b75]
- Role-specialized fine-tuning (SiriuS) — combining all roles into one fine-tuned model "showed a notable performance decline" [source-ab48beec910f]
- Heterogeneous workflow composition (different base LLMs per role) — this is where genuine multi-agent value most reliably appears
- Collective lifelong learning across distributed agents [source-8a33b427a26e — paywalled, abstract-level only]

### The Google Research empirical landscape

The most rigorous comparison (260 configurations, 6 benchmarks, 3 LLM families, 5 architectures) [source-6bcde9b07680, source-8376fb13a30c] yields concrete decision rules:

- **Centralized MAS**: +80.8% on parallelizable financial reasoning; +127–164% with specific vendor models. Best for analysis tasks with moderate tool counts.
- **Decentralized MAS**: +9.2% on web navigation; best for high-entropy exploration and tool-heavy tasks.
- **Single-Agent**: Strictly preferred for sequential planning (multi-agent degrades −39 to −70% there) and for any task where SAS baseline already exceeds 45%.
- **Three mechanistic patterns**: tool-coordination tradeoff (multi-agent overhead grows non-linearly with tool count), capability saturation (coordination cost exceeds diminishing returns above 45% baseline), error amplification (independent: 17.2× / centralized: 4.4×).
- A learned selector achieves **87% accuracy on held-out tasks** when picking architecture per task type.

### A nuanced and important caveat on multi-agent value

Recent work [source-1dd90a25bd55, "OneFlow / Rethinking the Value of Multi-Agent Workflow"] shows formally and empirically that **homogeneous multi-agent workflows (same base LLM across all roles) can usually be losslessly simulated by a single agent in multi-turn execution with shared KV cache**, matching or slightly *exceeding* multi-agent execution at lower cost on HumanEval, GSM8K, MATH, HotpotQA, DROP. **Our verify dispatch confirmed this**: independent matched-budget studies [source-922061761d41, source-417f0d6a360a] reach the same conclusion. Multi-agent debate evaluations [source-2d77cbeef64a, source-e8f5e6a00b2f] further find debate often fails to outperform strong single-agent baselines and can even degrade accuracy through conformity flipping.

**Caveats from the verify result:**
- The OneFlow theorem requires deterministic routing/tool assumptions and visible-history-only policies — it doesn't apply to setups with hidden local state or independent parallel sampling.
- Genuine coordination *does* help on decomposable/parallelizable tasks (the +80.8% finance result).
- Single-agent collapse can fail when the resulting skill library becomes too large and semantically confusable [source-612c4a2967f4].
- Critically, SiriuS [source-ab48beec910f], MAE [source-be6dd8001b75], and ComfyGPT [source-1e7797f8acc0] do *not* refute OneFlow — none of them runs the apples-to-apples baseline of a same-backbone single-agent simulation. Their multi-agent structure may be valuable as a *training-time scaffold* rather than as runtime irreducibility.

**Practical guidance synthesis.** For an enterprise agent containing both single-agent and multi-agent sub-workflows:
1. Default to single-agent unless the task is genuinely decomposable/parallelizable.
2. If using multi-agent, prefer **homogeneous + centralized verification** (4.4× error vs 17.2×); consider whether a single-agent multi-turn simulation would suffice at much lower cost.
3. Reserve genuinely multi-agent (with heterogeneous models or role-specialized fine-tuned agents) for tasks where the parallelism or specialization is essential (e.g., MAC-SQL Selector+Decomposer+Refiner [source-97a9b078e03f]).
4. Apply self-improvement loops *separately* to single-agent and multi-agent sub-workflows — they have different optimization dynamics.

---

## 5. Self-Improvement for Heterogeneous Enterprise Use Cases (Literature Search + Database Exploration + Multiple Internal Users)

This is where the corpus is **thinnest and most fragmented** (the landscape brief flagged it as a notable gap). Evidence is moderate-confidence, drawn from domain-specific papers plus extrapolation.

### Domain-specific results

**Literature search / RAG-style agents.** The most direct evidence is Chain-of-Retrieval (CoR) [source-b8103ab22a08]: multi-aspect query decomposition (motivation/methods/experiments) with iterative tree-structured search, self-improved via DPO using **citation-link recall as the objective reward** (Recall@k from the citation graph). Achieves +7.82% Recall over full-paper embeddings. Citation hallucination is a critical adjacent target — the GhostCite benchmark reportedly finds 14–95% hallucination rates across 13 LLMs [source-2319e730e9e2, scout-summary only], so any self-improvement loop should include citation verification as a dedicated grader.

**Text-to-SQL / database exploration.** Much richer evidence. MAC-SQL [source-97a9b078e03f] uses Selector→Decomposer→Refiner; the Refiner adds 5pp on BIRD-dev through execution-feedback iteration. ReFoRCE [source-c503a8ceabc3] adds iterative column exploration for enterprise schemas with 800+ columns. SQL-Trail [source-97f3faa53876] is the strongest result: multi-turn GRPO with a 6-component composite reward achieves 64.2% on BIRD-dev with 18× better data efficiency than SFT, outperforming Claude Sonnet-3.7. **Execution feedback is the natural ground-truth reward signal.** Caveat: SQL-Trail and similar methods assume interactive database execution access — often infeasible under enterprise privacy/cost controls.

**Cross-domain finding.** The pattern is consistent: domain-native automatic rewards (citation-link recall, execution accuracy) outperform generic LLM-as-judge. Identify the domain-native reward signal first; design the improvement loop second.

### Multi-persona / multi-use-case adaptation

The personalization survey [source-d763647a6571] proposes a four-component taxonomy (Profile Modeling, Memory, Planning, Action Execution). For heterogeneous internal users, three mechanisms are most relevant:
1. **Persona-based profiling with online retrieval** (PersonaX): offline multi-persona profiles + runtime retrieval, so the agent adapts role without retraining
2. **Response-based preference modeling** (RFM, PReF): factorize preferences into a shared feature basis with per-user weights
3. **Selective clarification (SAGE-Agent)**: ask only when expected value of clarification exceeds interaction cost

**Critical gap:** The personalization literature largely assumes one-agent-per-user, not one-shared-agent-for-many-users. The multi-tenant problem is partially addressed by Collaborative Memory [source-9ee733613685] but is otherwise underexplored.

### Memory partitioning vs. shared experience

This is the best-evidenced sub-question and converges on a clear recommendation.

| Tier | Scope | Contents |
|---|---|---|
| Per-user private | User-isolated | Sensitive data, personal preferences, user-specific corrections |
| Per-use-case procedural | Use-case-indexed | Successful task templates, domain-specific SOPs (literature SOPs ≠ SQL SOPs) |
| Shared strategic | Global | Universally applicable lessons, policy rules |

Evidence:
- Collaborative Memory [source-9ee733613685] reports **61% resource reduction at 50% query overlap** with shared memory while maintaining >0.90 accuracy. Asymmetric role-based collaboration also reduces resource calls.
- MemRL [source-21251e985b38] shows shared cross-task memory pools introduce **negligible interference** when a similarity gate (Phase-A filter with z-score normalization) prevents cross-domain pollution — without that gate, forgetting jumps to 20.1% vs 6.6%.
- MUSE [source-c5fbccc7ff38] uses hierarchical Strategic/Procedural/Tool memory with the strategic tier shared and the procedural tier indexed by application; achieves SOTA on TheAgentCompany.
- The memory survey [source-82577ab38772] explicitly endorses "role-based access controls over a shared memory substrate" as the principled middle ground.

**Implementation note.** Similarity gating + z-score normalization is the mechanism that makes shared pools safe. This is technically detailed but operationally critical: without it, cross-domain memory pollution is the norm, not the exception.

### Evaluation strategies for heterogeneous use cases

1. **Per-use-case domain-native rewards** (execution accuracy for SQL; citation recall for literature; entity-fidelity + length + similarity + LLM-judge for summarization [source-3c599452cdff]).
2. **Multi-grader composite evaluation** with lenient thresholds (OpenAI cookbook: 75% of graders pass OR avg ≥ 0.85 [source-3c599452cdff]).
3. **Per-use-case hold-out sets** kept separate from the optimization loop [source-5cb9e059f53c].
4. **Self-evolving benchmark methods** (Benchmark Self-Evolving [source-ed4122d0b36b], SkillLearnBench [source-7d3e99d3d27b]) for continual evaluation that resists overfitting — *content-level details for these were not loaded; cited from scouted summaries.*
5. **Failure-mode tracking beyond task accuracy** [source-82577ab38772]: memory quality, retrieval precision/recall, contradiction rate, latency, governance compliance — typically under-reported in current benchmarks.

### Practitioner guidance

**OpenAI cookbook [source-3c599452cdff]** provides the most actionable workflow: a three-tier strategy (manual / semi-automated / fully automated) with an explicit baseline_agent → run_eval → metaprompt_agent → test → promote-or-revert loop, with `VersionedPrompt.revert_to_version()` for rollback. Stops on >80% positive feedback, diminishing returns, or hitting a 3-retry cap (then alerts engineers). The cookbook does *not* directly address heterogeneous agents — adaptation requires per-use-case grader stacks with a shared metaprompt template.

**Comet/Opik [source-5cb9e059f53c]** offers seven open-source optimization algorithms (MetaPrompt, Hierarchical Reflective, Few-Shot Bayesian, Evolutionary, GEPA, Parameter Optimization, Tool Optimization), explicitly including tool-schema optimization and CI/CD-style continuous optimization. Recommends prototype/mature distinction: broad multi-prompt optimization early; focused weekly tuning in production. Both sources require a HITL approval gate before production promotion.

---

## 6. Synthesized Recommendations for the System Described

Given the system: literature search + database exploration + diverse internal users, here is the synthesis:

1. **Memory architecture**: Three-tier (per-user private / per-use-case procedural / shared strategic) with role-based access control. Implement similarity gating (MemRL-style Phase-A filter) before utility-based ranking to prevent cross-domain pollution. Treat memory as a security surface — apply authenticated memorization, audit logging, and trust-boundary enforcement [source-3bc6fdee1c6b].

2. **Self-improvement per use case**:
   - **Database exploration**: Execution feedback is the right signal. Implement at least a Refiner-style self-correction loop (MAC-SQL pattern); consider multi-turn RL (SQL-Trail) only if the budget exists *and* execution access is available. If execution is restricted, fall back to schema-grounded prompt optimization with synthetic execution proxies.
   - **Literature search**: Citation-link recall as primary reward (CoR pattern); add explicit citation-verification graders given documented hallucination rates.
   - **Any new use case**: First identify the domain-native automatic reward signal. If none exists, prefer manual evaluation curation over deploying a self-improvement loop.

3. **Cross-cutting prompt and tool optimization**: Use Opik or DSPy for continuous prompt and tool-schema optimization; apply JTPRO-style **joint** optimization since you have many tools across domains. Run on a weekly-or-similar cadence with hold-out validation and HITL promotion.

4. **Architecture**: Default to single-agent multi-turn for each sub-workflow unless decomposability genuinely justifies multi-agent. If multi-agent, prefer homogeneous + centralized verification (the 4.4× vs 17.2× error-amplification reduction is substantial). Be skeptical of multi-agent debate as a self-improvement mechanism — recent evidence finds it often underperforms strong single-agent baselines.

5. **Guardrails**: Versioned prompts and memories with explicit rollback criteria; circuit breakers; audit logging for every self-improvement event; HITL approval gate before production promotion. The headline RSI/alignment threats are mostly miscategorized for this regime, but the *operational* recommendations from the cautious literature (rollback, audit, scoped permissions) remain sound — adopt them as reliability engineering, not as AGI-safety theater.

6. **Evaluation**: Per-use-case multi-grader stacks with a unified optimization loop and a lenient aggregate threshold. Maintain four evaluation layers (task effectiveness / memory quality / efficiency / governance) — current benchmarks usually report only the first.

---

## Open Issues and Caveats

- **Most strong results are arXiv preprints**, not peer-reviewed (RISE [source-77905a41db18] is the notable NeurIPS 2024 exception, as is TextGrad in Nature). The convergence across multiple independent papers raises confidence but peer review remains pending for many headline claims.
- **Single-source claims** flagged in the body include: the textual-gradient critique [source-ae71b5a9347c], the alignment-faking-amplified-by-RL result [source-58d3c55fd7df], MemRL's cross-model memory transfer [source-21251e985b38], and OneFlow's exact closed-model cost savings (which rely on simulated KV-cache assumptions [source-1dd90a25bd55]).
- **Paywalled / not-loaded sources** with relevant content: Collective AI in Nature MI [source-8a33b427a26e]; DataSciBench [source-ba6705c86d60], SkillLearnBench [source-7d3e99d3d27b], Benchmark Self-Evolving [source-ed4122d0b36b], citation-hallucination paper [source-2319e730e9e2] — all cited from scout summaries only.
- **Genuine gaps in the literature**:
  - No paper directly evaluates a single agent self-improving across both literature-search and text-to-SQL simultaneously.
  - The multi-tenant problem (one shared agent, many concurrent users with different roles) is underdeveloped relative to one-agent-per-user personalization.
  - Long-horizon stability (>500 turns; multi-month deployments) of memory-based self-improvement is tested only in simulation.
  - Peer-reviewed comparison of rollback strategies across improvement modalities (weight/prompt/memory) does not yet exist; ICLR 2026 is establishing this as a research frontier.
  - SQL-Trail and similar methods assume interactive DB execution access; enterprise workarounds are not well documented.


## Limitations

- Most strong results are arXiv preprints rather than peer-reviewed; convergence across independent papers raises confidence but formal peer review is pending for most headline claims (RISE NeurIPS 2024 and TextGrad Nature are notable exceptions).
- Single-source preprint claims that are load-bearing in this report and warrant independent replication: textual-gradient critique [source-ae71b5a9347c], alignment-faking-amplified-by-RL [source-58d3c55fd7df], MemRL cross-model memory transfer [source-21251e985b38], OneFlow's exact closed-model cost savings (relies on simulated KV-cache).
- No paper directly evaluates a single agent self-improving across both literature-search and text-to-SQL use cases simultaneously; all domain-specific results are from specialized single-domain evaluations.
- Multi-tenant scaling: the personalization literature handles one-agent-per-user but the one-shared-agent-for-many-users problem (the actual enterprise case) is underdeveloped beyond Collaborative Memory [source-9ee733613685].
- Long-horizon stability (>500 turns; multi-month deployments) of memory-based self-improvement systems (MUSE, MemRL, hybrid decay) is tested only in simulation, not production.
- Peer-reviewed comparison of rollback strategies across improvement modalities (weight updates vs prompt updates vs memory updates) does not yet exist; ICLR 2026 is establishing this frontier.
- SQL-Trail and most text-to-SQL self-improvement methods assume interactive database execution access during inference; enterprise workarounds for restricted-execution settings are not well documented.
- Architecture-level self-improvement (Gödel Agent, AlphaEvolve) remains largely theoretical with no peer-reviewed demonstration of robust general improvements outside narrow algorithmic problems.
- Several scouted sources were not loaded in depth (DataSciBench [source-ba6705c86d60], SkillLearnBench [source-7d3e99d3d27b], Benchmark Self-Evolving [source-ed4122d0b36b], GhostCite [source-2319e730e9e2], collective AI Nature MI [source-8a33b427a26e]), so specific evaluation methodologies for heterogeneous use cases could not be fully verified.
- The interaction between MAE-style co-evolution training and pipeline-level workflow optimization (ComfyGPT) has not been studied — combining curriculum self-improvement with workflow-level optimization in hybrid systems is open.

## Sources

- **[source-77905a41db18]** [RECURSIVE INTROSPECTION: Teaching Language Model Agents How to Self-Improve (NeurIPS 2024)](https://proceedings.neurips.cc/paper_files/paper/2024/file/639d992f819c2b40387d4d5170b8ffd7-Paper-Conference.pdf) - tier 1 - peer-reviewed
  - Teaches LLM agents to self-improve at test time through recursive introspection across multiple turns; fine-tunes models on multi-turn traces where initial answer is wrong, feedback arrives, and corrected answer follows.
- **[source-ea982c81ac6a]** [Better Ways to Build Self-Improving AI Agents – Yohei Nakajima](https://yoheinakajima.com/better-ways-to-build-self-improving-ai-agents/) - not-tiered
  - Overview of self-improvement strategies including RISE recursive introspection, fine-tuning on multi-turn traces, and various feedback-driven approaches.
- **[source-8e42d1b3c52d]** [A Self-Improving Coding Agent (arXiv 2025)](https://arxiv.org/html/2504.15228v1) - not-tiered
  - Covers agents that learn reusable skills and continuously self-improve, including LLM feedback-driven skill learning and code generation approaches like MaestroMotif.
- **[source-be6dd8001b75]** [Multi-Agent Evolve: LLM Self-Improve through Co-evolution (arXiv 2025)](https://arxiv.org/html/2510.23595v3) - tier 2
  - Multi-agent self-improvement via co-evolution: Proposer generates questions, Solver produces answers, Judge evaluates and provides reward signals, forming a self-rewarding loop without external supervision.
- **[source-459320f34f27]** [Self-Improving LLM Agents at Test-Time (arXiv 2025)](https://arxiv.org/html/2510.07841v1) - tier 2
  - First language generation-based test-time fine-tuning method for LLM-based agents; surveys prior work on self-improvement using internal signals derived from model parameters without external supervision.
- **[source-10f554bc03b8]** [Adaptive Self-improvement LLM Agentic System for ML Library Development (ICLR/ICML 2025)](https://weiya711.github.io/publications/iclr-icml2025-adaptive-self-improvement.pdf) - not-tiered
  - Self-improvement cycle where LLM agents evolve through earned experiences; fully automated without human experts beyond initial designers; applied to ML library development.
- **[source-3c599452cdff]** [Self-Evolving Agents: A Cookbook for Autonomous Agent Retraining (OpenAI)](https://developers.openai.com/cookbook/examples/partners/self_evolving_agents/autonomous_agent_retraining) - tier 3
  - Practical retraining loop for autonomous agents using measurable feedback signals; compares three prompt-optimization strategies from manual to fully automated; grounded in healthcare but generalizes to any domain.
- **[source-aa9c1122f8dd]** [Self-Improving AI Agents: The 2026 Guide (o-mega.ai)](https://o-mega.ai/articles/self-improving-ai-agents-the-2026-guide) - not-tiered
  - Covers Karpathy's autoresearch system (630-line Python script) where an AI agent autonomously modifies training code, runs experiments, evaluates results, and iterates—an open-source example of autonomous self-improvement.
- **[source-5cb9e059f53c]** [Announcing the Future of AI Engineering: Self-Optimizing Agents (Comet)](https://www.comet.com/site/blog/self-optimizing-agents/) - tier 3
  - Self-optimizing agents covering optimization of prompts, tools, and multi-agent architectures using selected algorithms; discusses objectives like cost, latency, and evaluation metrics.
- **[source-9294862bafd2]** [A Survey of Self-Evolving Agents: What, When, How, and Where to Evolve (arXiv 2025)](https://arxiv.org/html/2507.21046v4) - tier 2
  - Comprehensive survey covering self-improving LLM methods including iterative refinement through self-generated data and self-critique; extends to system-wide evolution including tool acquisition, architectural reconfiguration, and environmental exploration toward AGI.
- **[source-6aa9096fda18]** [Awesome-Self-Evolving-Agents: Survey of Self-Evolving AI Agents (GitHub)](https://github.com/EvoAgentX/Awesome-Self-Evolving-Agents) - not-tiered
  - Curated list from a comprehensive survey bridging foundation models and lifelong agentic systems; covers self-evolving agent paradigm.
- **[source-0063f6c947f1]** [Awesome-Self-Evolving-Agents: Curated Resources on Self-Evolving Agents (XMUDeepLIT, GitHub)](https://github.com/XMUDeepLIT/Awesome-Self-Evolving-Agents) - not-tiered
  - Curated list of surveys, papers, benchmarks, and open-source projects on self-evolving agents.
- **[source-16c2bd984adf]** [Survey on LLM-based Multi-Agent Systems: Workflow, Infrastructure, and Challenges (Springer 2024)](https://link.springer.com/article/10.1007/s44336-024-00009-2) - not-tiered
  - Comprehensive survey of LLM-based multi-agent systems covering workflow structure with five key components; addresses infrastructure and challenges.
- **[source-ad6d040d47e4]** [Agentic AI: A Comprehensive Survey of Architectures, Applications, and Future Directions (arXiv 2025)](https://arxiv.org/html/2510.25445v1) - not-tiered
  - Comprehensive survey on agentic AI architectures covering both single and multi-agent systems; addresses conceptual confusion between modern neural and symbolic models.
- **[source-9e53581b3ffd]** [Why Do Multi-Agent LLM Systems Fail? (arXiv 2025)](https://arxiv.org/pdf/2503.13657) - tier 1 - peer-reviewed
  - Many MAS failures arise from organizational design and agent coordination challenges rather than individual agent limitations; applies prompt and workflow changes to achieve up to 15.6% improvement.
- **[source-3bc6fdee1c6b]** [Taxonomy of Failure Modes in Agentic AI Systems (Microsoft Whitepaper)](https://cdn-dynmedia-1.microsoft.com/is/content/microsoftcorp/microsoft/final/en-us/microsoft-brand/documents/Taxonomy-of-Failure-Mode-in-Agentic-AI-Systems-Whitepaper.pdf) - tier 3
  - Taxonomy of failure modes in agentic systems; covers security controls, limiting tools and data to reduce risks.
- **[source-82577ab38772]** [Memory for Autonomous LLM Agents: Mechanisms, Evaluation, and Emerging Frontiers (arXiv 2025)](https://arxiv.org/html/2603.07670v1) - tier 2
  - Memory transforms stateless LLMs into self-evolving agents; enables accumulation of factual knowledge, behavioral patterns, avoidance of past mistakes, and continuous improvement through interaction.
- **[source-21251e985b38]** [MemRL: Self-Evolving Agents via Runtime Reinforcement Learning on Episodic Memory (arXiv 2025)](https://arxiv.org/html/2601.03192v2) - tier 2
  - Self-evolving agents using structured episodic memory with intent-experience-utility bank, two-phase retrieval, and runtime utility updates; addresses limitation of standard RAG in agentic tasks.
- **[source-225fbca8e970]** [Memory Management and Contextual Consistency for Long-Running Low-Code Agents (arXiv 2025)](https://arxiv.org/pdf/2509.25250) - tier 2
  - Addresses misaligned experience replay as a self-degradation risk where flawed or irrelevant memories cause performance decline over time; covers contextual consistency for long-running agents.
- **[source-ae71b5a9347c]** [Textual Gradients are a Flawed Metaphor for Automatic Prompt Optimization (arXiv 2025)](https://arxiv.org/html/2512.13598) - tier 2
  - Critiques textual gradient-based automatic prompt optimization; shows gradient analogy doesn't explain behavior, important methodological caveat for self-improvement via prompt tuning.
- **[source-d03b097fd3b5]** [JTPRO: Joint Tool-Prompt Reflective Optimization Framework for Language Agents (arXiv 2026)](https://arxiv.org/html/2604.19821) - tier 2
  - Jointly optimizes tool descriptions and agent prompts to address tool mis-selection and incorrect slot/value instantiation, especially as number of tools grows large and domain-specific.
- **[source-935e1b3fd2bc]** [DSPy: Declarative Self-Improving Python for AI Programs](https://dspy.ai/) - tier 3
  - DSPy (Declarative Self-improving Python) compiles AI programs into effective prompts and weights; covers RAG pipelines and agent loops; used in production at Databricks, VMware; improved prompt evaluation accuracy from 46.2% to 64.0%.
- **[source-b6054f4cb35a]** [Automatic Prompt Optimization with DSPy: Building Self-Tuning Agent Pipelines](https://notes.muthu.co/2026/02/automatic-prompt-optimization-with-dspy-building-self-tuning-agent-pipelines/) - tier 3
  - Compares DSPy vs TextGrad: TextGrad for hard single-problem optimization via LLM-as-differentiator; DSPy for multi-step pipelines with training data. OPRO-style approaches provide meta-reasoning about why prompts fail.
- **[source-6bcde9b07680]** [Towards a Science of Scaling Agent Systems: When and Why Agent Systems Work (Google Research)](https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/) - tier 3
  - Google Research evaluated five canonical agent architectures; Single-Agent (SAS) executes all reasoning sequentially; multi-agent coordination delivers +81% improvement on parallelizable tasks but causes up to 70% degradation on sequential ones.
- **[source-7d3e99d3d27b]** [SkillLearnBench: Benchmarking Continual Learning Methods for Agent Skill Generation (arXiv 2026)](https://arxiv.org/html/2604.20087) - not-tiered
  - First benchmark for continual skill learning methods, evaluating 20 tasks across 15 sub-domains; skills are the de facto way to enable LLM agents for complex real-world tasks; benchmarks one-shot and continual methods.
- **[source-c5fbccc7ff38]** [Learning on the Job: An Experience-Driven Self-Evolving Agent for Long-Horizon Tasks (MUSE, arXiv 2025)](https://arxiv.org/html/2510.08002) - tier 2
  - MUSE: experience-driven self-evolving agent with hierarchical Memory Module for long-horizon tasks; addresses the limitation that LLM agents are test-time static and cannot accumulate knowledge from experience.
- **[source-8a33b427a26e]** [A Collective AI via Lifelong Learning and Sharing at the Edge (Nature Machine Intelligence 2024)](https://doi.org/10.1038/s42256-024-00800-2) - tier 1 - peer-reviewed
  - Collective AI via lifelong learning where separate units learn independently and share knowledge; covers incremental multi-skill learning, knowledge exchange via common language, edge deployment.
- **[source-e6fbb4fbc705]** [AI Agent Architecture Patterns: Single & Multi-Agent Systems (Redis)](https://redis.io/blog/ai-agent-architecture-patterns/) - not-tiered
  - Reflection and Self-Refine patterns let agents critique their own outputs and refine iteratively; CrewAI memory system covers short-term, long-term, entity, and external memory; regulated industries need self-correction plus human approval layers.
- **[source-b53ee8bb1ae0]** [ICLR 2026 Workshop on AI with Recursive Self-Improvement: Workshop Summary](https://openreview.net/pdf?id=OsPQ6zTQXV) - tier 2
  - ICLR 2026 workshop on AI with recursive self-improvement; covers criteria for halting updates, rolling back model states on regressions, and common failure modes and guardrails for self-improving agents.
- **[source-138ec943f15b]** [Recursive Self-Improvement (Wikipedia)](https://en.wikipedia.org/wiki/Recursive_self-improvement) - tier 4
  - Wikipedia article on recursive self-improvement; covers misalignment risks, alignment faking in LLMs, AGI safety concerns, and conditions under which RSI is dangerous.
- **[source-e1292788b637]** [Trajectory-Informed Memory Generation for Self-Improving Agent Systems (arXiv 2026)](https://arxiv.org/html/2603.10600) - tier 2
  - Extracts actionable learnings from agent execution trajectories; four-component framework including trajectory intelligence extractor; addresses repeated inefficient patterns, similar error recovery, and applying successful strategies from past executions.
- **[source-1e7797f8acc0]** [ComfyGPT: A Self-Optimizing Multi-Agent System for Comprehensive Workflow Generation (arXiv 2025)](https://arxiv.org/html/2503.17671) - tier 2
  - Self-optimizing multi-agent workflow generation system with four specialized agents (ReformatAgent, FlowAgent, RefineAgent, ExecuteAgent); demonstrates multi-agent self-optimization for complex task workflows.
- **[source-ed4122d0b36b]** [Benchmark Self-Evolving: A Multi-Agent Framework for Dynamic LLM Evaluation (COLING 2024)](https://arxiv.org/html/2402.11443) - not-tiered
  - Multi-agent framework for dynamically evaluating LLMs through benchmark self-evolving; six reframing operations to test LLMs against diverse queries, data noise, and varying problem types.
- **[source-ba6705c86d60]** [DataSciBench: An LLM Agent Benchmark for Data Science (arXiv 2025)](https://arxiv.org/html/2502.13897) - not-tiered
  - Comprehensive benchmark for LLM agents in data science tasks; covers diverse, challenging prompts with uncertain ground truth; semi-automated pipeline for generating and validating evaluation metrics.
- **[source-61bdda249780]** [Securing AI Agents with Layered Guardrails and Risk Taxonomy (Enkrypt AI)](https://www.enkryptai.com/blog/securing-ai-agents-a-comprehensive-framework-for-agent-guardrails) - tier 3
  - Securing AI agents using layered guardrails; covers prompt storms, runaway recursion, tool request validation; aligns with OWASP framework for agent risk taxonomy.
- **[source-69db498a3241]** [RISE: Recursive Introspection for LLM self-improvement (arXiv)](https://arxiv.org/abs/2407.18219) - not-tiered
  - ArXiv preprint on recursive introspection methodology for LLM self-improvement through multi-turn traces and fine-tuning
- **[source-8376fb13a30c]** [Towards a Science of Scaling Agent Systems (arXiv 2512.08296, 2025)](https://arxiv.org/html/2512.08296) - tier 2
  - Quantitative scaling principles for agent systems across 260 configurations spanning five canonical architectures (Single-Agent, Independent, Centralized, Decentralized, Hybrid). Multi-agent coordination improves performance by +80.8% on parallelizable financial reasoning but degrades by -70% on sequential planning.
- **[source-346b3957c72e]** [Prompt Optimization Using Few-Shot Prompting: LLM-Generated Feedback](https://arize.com/blog/prompt-optimization-few-shot-prompting/) - not-tiered
  - LLM-generated feedback explaining why outputs are right or wrong provides richer signal for prompt optimization than raw performance metrics alone.
- **[source-526d1c9a0726]** [The Science of Prompt Optimization and Automated Refinement](https://medium.com/data-science-collective/the-science-of-prompt-optimization-and-automated-refinement-044b4b8e5353) - not-tiered
  - Implements feedback loop inspired by RLHF but automates the human component using a specialized Mentor LLM for iterative prompt refinement.
- **[source-b9db41519ee1]** [Automatic Prompt Optimization by Cameron R. Wolfe, Ph.D.](https://cameronrwolfe.substack.com/p/automatic-prompt-optimization) - not-tiered
  - APO creates recursive feedback loop: collect errors, summarize via natural language gradient, generate modified prompts, select best, repeat—foundational method for automated optimization.
- **[source-922756dff883]** [SIPDO: Closed-Loop Prompt Optimization via Synthetic Data Feedback (arXiv 2025)](https://arxiv.org/html/2505.19514) - not-tiered
  - Integrates synthetic data generation into prompt optimization, coupling a synthetic data generator with a prompt optimizer for iterative closed-loop improvement beyond fixed datasets.
- **[source-73155f8b3c69]** [A Multi-AI Agent System for Autonomous Optimization via Iterative Refinement and LLM-Driven Feedback Loops (arXiv 2024)](https://arxiv.org/html/2412.17149) - not-tiered
  - Framework for autonomously optimizing agentic systems across industries using specialized agents (Refinement, Execution, Evaluation, Modification, Documentation) with LLM-driven feedback loops.
- **[source-54cd9382fc29]** [DynamiCare: A Dynamic Multi-Agent Framework for Interactive Medical Decision-Making (arXiv 2025)](https://arxiv.org/html/2507.02616v1) - not-tiered
  - Multi-agent framework modeling clinical reasoning as dynamic, interactive process that adapts structure and strategy based on newly acquired patient information—domain-specific retraining example.
- **[source-4d7496b645be]** [Scaling Medical AI Across Clinical Contexts (Nature Medicine 2025)](https://www.nature.com/articles/s41591-025-04184-7) - not-tiered
  - Context switching enables medical AI to adapt across specialties, populations and geographies without retraining; multimodal models coordinate tools based on task and user context.
- **[source-de3633813b17]** [AgentNet: Decentralized Evolutionary Coordination for LLM-based Multi-Agent Systems](https://arxiv.org/html/2504.00587) - not-tiered
  - Decentralized coordination framework addressing scalability bottlenecks and single points of failure in LLM-based multi-agent systems through RAG-based evolution and specialization
- **[source-158128942210]** [TRiSM for Agentic AI: A Review of Trust, Risk, and Security Management in LLM-based Agentic Multi-Agent Systems](https://arxiv.org/html/2506.04133) - not-tiered
  - Structured analysis of Trust, Risk, and Security Management in LLM-based multi-agent systems with focus on safety governance and failure mitigation
- **[source-db072d2b06dd]** [Toward Reliable Evaluation of LLM-Based Financial Multi-Agent Systems: Taxonomy, Coordination Primacy, and Cost Awareness](https://arxiv.org/html/2603.27539) - not-tiered
  - Introduces coordination primacy hypothesis showing inter-agent coordination protocol design is primary driver of multi-agent system performance; taxonomy of architecture, coordination, memory, and tool integration
- **[source-ef11a05c240d]** [Guardrails.md - Safety Protocol for Autonomous Agents](https://guardrails.md/) - not-tiered
  - Four universal safety patterns: artifact verification, context rotation, privilege boundaries, and rate limiting to prevent runaway loops in autonomous agents
- **[source-965b9508661e]** [Adding Guardrails for AI Agents: Policy and Configuration Guide (Reco AI)](https://www.reco.ai/hub/guardrails-for-ai-agents) - not-tiered
  - Guardrails for AI agents including dry-run modes, rollback mechanisms through versioned data or transactional logs, and task-level guardrails for multi-agent orchestration
- **[source-0e6ed09545a6]** [Understanding guardrails for AI agents - Weights & Biases](https://wandb.ai/site/articles/guardrails-for-ai-agents/) - not-tiered
  - Industry best practices for AI agent guardrails including action constraints, read-only access, rate limits on API calls, and monitoring to prevent runaway costs
- **[source-9aab2558bba9]** [How I Built Open-Source Guardrails That Auto-Stop Runaway AI Agents (DEV Community)](https://dev.to/tazsat0512/how-i-built-open-source-guardrails-that-auto-stop-runaway-ai-agents-249m) - not-tiered
  - Open-source guardrails implementation for stopping runaway AI agents, emphasizing fail-closed design to prevent false sense of security
- **[source-89d0e19ef019]** [MIRIX: Multi-Agent Memory System for LLM-Based Agents](https://arxiv.org/html/2507.07957) - not-tiered
  - Modular multi-agent memory system solving personalization and multimodal memory recall; transcends flat text-based memory with rich visual and multimodal experiences.
- **[source-a25d1bb9e63f]** [User Preference Modeling for Conversational LLM Agents: VARS Framework](https://arxiv.org/html/2603.20939) - not-tiered
  - Per-user long-term and short-term preference vectors in shared space; enables personalization without per-user fine-tuning; online updates from weak rewards.
- **[source-e332bfe49ea4]** [AFA: Identity-Aware Memory for Preventing Persona Confusion in Multi-User Dialogue](https://arxiv.org/html/2604.25022) - not-tiered
  - Speaker identification with per-user memory stores to prevent persona confusion in shared voice assistants; demonstrates identity-aware personalized dialogue architecture.
- **[source-c5dab2c8d8a5]** [SAGER: Self-Evolving User Policy Skills for Recommendation Agent](https://arxiv.org/html/2604.14972) - not-tiered
  - Per-user semantic memory evolution for personalization paired with per-user system prompts; addresses asymmetry between memory and reasoning evolution in LLM agents.
- **[source-957defa35602]** [HONEYBEE: Efficient Role-based Access Control for Vector Databases](https://arxiv.org/html/2505.01538) - not-tiered
  - Dynamic partitioning framework for vector databases balancing per-user indexes (low latency, high memory cost) vs shared indexes (low memory, high latency); applies to memory trade-offs.
- **[source-363089da9a2d]** [RAG-Driven Memory Architectures in Conversational LLMs](https://doi.org/10.1109/ACCESS.2025.3589241) - not-tiered
  - Literature review of memory architectures in conversational AI; covers vector databases, RAG, dialogue coherence, and system responsibility maintenance.
- **[source-97a9b078e03f]** [MAC-SQL: A Multi-Agent Collaborative Framework for Text-to-SQL](https://arxiv.org/html/2312.11242v2) - tier 2
  - Multi-agent framework with Selector, Decomposer, and Refiner agents that uses execution feedback to iteratively refine SQL queries.
- **[source-73c7ee990387]** [Large Language Model Enhanced Text-to-SQL Generation: A Survey](https://arxiv.org/html/2410.06011v1) - not-tiered
  - Comprehensive survey on LLM-enhanced text-to-SQL covering self-correcting guides like MAGIC that iterate over incorrect queries.
- **[source-c503a8ceabc3]** [ReFoRCE: A Text-to-SQL Agent with Self-Refinement, Format Restriction, and Column Exploration](https://arxiv.org/html/2502.00675v1) - tier 2
  - Text-to-SQL agent with self-refinement and column exploration capabilities, comparing DAIL-SQL, DIN-SQL, and other prompting methods.
- **[source-c743fb11ead2]** [SQLCritic: Correcting Text-to-SQL Generation via Clause-wise Critic](https://arxiv.org/html/2503.07996v1) - not-tiered
  - Clause-wise critic approach to correcting text-to-SQL generation, comparing strategies from DIN-SQL, DAIL-SQL, MAC-SQL, and MAGIC.
- **[source-5e6a497aece8]** [HySemRAG: Hybrid Semantic RAG for Automated Literature Synthesis with Citation Verification](https://arxiv.org/html/2508.05666) - not-tiered
  - Hybrid retrieval combining semantic search, keyword filtering, knowledge graph; agentic self-correction framework with iterative quality assurance; post-hoc citation verification ensuring complete traceability.
- **[source-ccd4c673f286]** [PaperQA: Retrieval-Augmented Generative Agent for Scientific Research](https://arxiv.org/abs/2312.07559) - not-tiered
  - Agent that performs information retrieval across full-text scientific articles, assesses relevance of sources and passages, uses RAG to provide answers with citations; introduces LitQA benchmark for complex multi-paper synthesis.
- **[source-7775f72bec16]** [The Budget AI Researcher: RAG Chains for Research Idea Generation](https://arxiv.org/html/2506.12317) - not-tiered
  - Structural framework using RAG chains and vector databases for research ideation; addresses limitations of generic LLMs in guiding toward practical research ideas from scientific literature.
- **[source-625ece046668]** [BioVerge: Benchmark and Study of Self-Evaluating Agents for Biomedical Hypothesis Generation](https://arxiv.org/html/2511.08866) - not-tiered
  - LLM agents for hypothesis generation from biomedical literature using multi-data types; focuses on self-evaluation and feedback mechanisms for improving retrieval and reasoning over scientific papers.
- **[source-83873890d4a3]** [Building Persona-Based Agents On Demand: Tailoring Multi-Agent Workflows to User Needs](https://arxiv.org/html/2604.27882) - not-tiered
  - Proposes persona-plug and ETAPP benchmarks for personalized tool invocation across diverse user profiles; enables design-time role encoding to adapt at runtime based on user needs.
- **[source-a2af1f6dfaec]** [Enabling Personalized Long-term Interactions in LLM-based Agents through Persistent Memory and User Profiles](https://arxiv.org/html/2510.07925v1) - not-tiered
  - Integrates persistent memory and user profiles to improve adaptivity and personalization of LLM-based agents for long-term user interactions.
- **[source-d763647a6571]** [Toward Personalized LLM-Powered Agents: Foundations, Evaluation, and Future Directions](https://arxiv.org/html/2602.22680) - tier 2
  - Foundational work on personalized LLM agents covering profiling, memory, and adaptive goal-directed behavior; system-level design for multi-user personalization.
- **[source-84eefc8a18cb]** [Memory in the LLM Era: Modular Architectures and Strategies in a Unified Framework](https://arxiv.org/html/2604.01707v1) - not-tiered
  - Modular architectures for personalization and adaptive decision-making via long-term memory; addresses stateless LLM agent limitations.
- **[source-ee4170003223]** [Building AI Agents with Personas, Goals, and Dynamic Memory](https://medium.com/@leviexraspk/building-ai-agents-with-personas-goals-and-dynamic-memory-6253acacdc0a) - not-tiered
  - Industry-focused guide on agents with personas, goals, and memory for diverse use cases (LegalTech, finance, healthcare); covers dynamic memory adaptation per user type.
- **[source-9458e483bc7d]** [Designing with Multi-Agent Generative AI: Insights from Industry Early Adopters (DIS 2025)](https://dl.acm.org/doi/10.1145/3715336.3735823) - not-tiered
  - ACM peer-reviewed study on role-based agent specialization and task assignment from early adopters; covers design patterns for heterogeneous agent teams.
- **[source-acb4d46c861c]** [Memory in LLM-based Multi-agent Systems: Mechanisms, Challenges, and Collective Memory](https://www.techrxiv.org/users/1007269/articles/1367390/master/file/data/LLM_MAS_Memory_Survey_preprint_/LLM_MAS_Memory_Survey_preprint_.pdf?inline=true) - not-tiered
  - Comprehensive survey on memory in multi-agent systems; covers distributed memory, role adaptation, and collective memory dynamics for multi-user scenarios.
- **[source-ab48beec910f]** [SiriuS: Self-improving Multi-agent Systems via Bootstrapped Reasoning](https://arxiv.org/html/2502.04780) - tier 2
  - Multi-agent AI systems powered by LLMs are increasingly applied to solve complex tasks. SiriuS introduces a self-improving, reasoning-driven optimization framework for multi-agent systems with an experience library of high-quality reasoning trajectories.
- **[source-197f6f7059ff]** [Self-Organized Agents: A LLM Multi-Agent Framework toward Ultra Large-Scale Code Generation and Optimization](https://arxiv.org/html/2404.02183) - not-tiered
  - Self-Organized (SoA) multi-agent framework enables scalable and efficient generation and optimization of large-scale code, with self-organized agents operating independently.
- **[source-cc8d43b83b62]** [RAGEN: Understanding Self-Evolution in LLM Agents via Multi-Turn Reinforcement Learning](https://arxiv.org/html/2504.20073) - not-tiered
  - Proposes StarPO framework for trajectory-level agent RL and RAGEN system for training and evaluating LLM agents, revealing core findings on multi-turn agent RL training.
- **[source-2550182fb16d]** [Evaluating AI agents: Real-world lessons from building agentic systems at Amazon](https://aws.amazon.com/blogs/machine-learning/evaluating-ai-agents-real-world-lessons-from-building-agentic-systems-at-amazon/) - not-tiered
  - Comprehensive evaluation framework for Amazon agentic AI systems with a generic evaluation workflow and agent evaluation library providing systematic measurements and metrics.
- **[source-14c39fccceaa]** [A Comprehensive Guide to Evaluating Multi-Agent LLM Systems](https://orq.ai/blog/multi-agent-llm-eval-system) - not-tiered
  - Guide on structuring agent interactions into graph-based models for insights into system behavior, with metrics designed around system objectives.
- **[source-dd60de2f3bc6]** [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) - not-tiered
  - Explores evaluation frameworks for different agent types including coding agents, research agents, computer use agents, and conversational agents, with evals as optimization targets.
- **[source-a606fdb8c0d7]** [Optimization for Reinforcement Learning: From Single Agent to Cooperative Agents](https://arxiv.org/abs/1912.00498) - not-tiered
  - Reviews recent advances in multi-agent reinforcement learning algorithms for large-scale control systems, with emphasis on decentralized setting and coordination protocols.
- **[source-d0727c2c1a38]** [AgentDoG: A Diagnostic Guardrail Framework for AI Agent Safety and Security](https://arxiv.org/html/2601.18491v2) - not-tiered
  - Proposes a unified three-dimensional taxonomy that orthogonally categorizes agentic risks by their source (where), failure mode (how), and consequence (what) to cover complex and numerous risky behaviors.
- **[source-69d0d7a69081]** [Agentic AI Safety & Guardrails: 2025 Best Practices for Enterprise](https://skywork.ai/blog/agentic-ai-safety-best-practices-2025-enterprise/) - not-tiered
  - Catalogs agent failure classes in the wild—prompt injection, tool misuse, memory leakage—and provides mitigation checklists aligned with OWASP Top 10 for LLM Applications.
- **[source-6e27bf4d2a58]** [OWASP's Top 10 Agentic AI Risks Explained](https://www.humansecurity.com/learn/blog/owasp-top-10-agentic-applications/) - not-tiered
  - Describes agentic behavioral patterns such as agents scraping, probing, escalating, or drifting off-task, which surface as observable failure modes even with sound underlying architecture.
- **[source-ff187d14af70]** [Agentic AI Security: A Guide to Threats, Risks & Best Practices 2025 | Rippling](https://www.rippling.com/blog/agentic-ai-security) - not-tiered
  - Advocates for enforceable guardrails through automated policy engines and runtime checks to restrict agent behavior and prevent unsafe actions, moving policies beyond static documents.
- **[source-402a4a3ffb55]** [New Whitepaper Outlines the Taxonomy of Failure Modes in AI Agents | Microsoft Security Blog](https://www.microsoft.com/en-us/security/blog/2025/04/24/new-whitepaper-outlines-the-taxonomy-of-failure-modes-in-ai-agents/) - not-tiered
  - Security failures in agentic AI result in core impacts: loss of confidentiality, availability, or integrity; allows threat actors to alter system intent. Blog post announcing the Microsoft taxonomy whitepaper.
- **[source-a06d4c331ba1]** [Recursive Self-Improvement, Without the Hype | Nicolas Schneider](https://nicolas2912.github.io/2025/09/24/recursive-self-improvement.html) - not-tiered
  - Discusses autonomous validation with rollback on failure, breadth of improvements across tasks, and bottleneck awareness—practical criteria for evaluating self-improving systems.
- **[source-30b564a47687]** [Gödel Agent for Recursive Self-Improvement: A Comprehensive Tutorial | GitHub](https://gist.github.com/ruvnet/15c6ef556be49e173ab0ecd6d252a7b9) - not-tiered
  - Describes a Verifier that rejects changes and signals rollback if proof cannot be completed, tests fail, or safety conditions are violated in a recursive self-improvement loop.
- **[source-c19a3be48d28]** [Is Research into Recursive Self-Improvement Becoming a Safety Hazard?](https://www.foommagazine.org/is-research-into-recursive-self-improvement-becoming-a-safety-hazard/) - not-tiered
  - Examines concerns that uncontrolled recursive self-improvement could produce exponential capability gains without securing system values, making it unpredictable or dangerous.
- **[source-78c0df808019]** [Recursive Self-Improvement: The AI Risk That Keeps Researchers Up at Night | MindStudio](https://www.mindstudio.ai/blog/recursive-self-improvement-ai-risk-explained) - not-tiered
  - Notes that governance structures lag technical development, creating coordination problems; emphasizes bounded objectives, human oversight, and explicit scope from frontier model design to practical agent implementation.
- **[source-6215b1d8b20a]** [Towards AI-Safety-by-Design: A Taxonomy of Runtime Guardrails in Foundation Model based Systems](https://arxiv.org/html/2408.02205v1) - not-tiered
  - Taxonomy of runtime guardrails for foundation model systems; covers redundancy, logging, and mitigation actions for agent failures.
- **[source-ef3e6f20ca39]** [A Safety and Security Framework for Real-World Agentic Systems](https://arxiv.org/html/2511.21990v1) - not-tiered
  - Enterprise-grade safety and security framework for agentic systems at scale; addresses dynamic environments, memory evolution, and stochastic execution.
- **[source-5705dace6f53]** [SSR: Socratic Self-Refine for Large Language Model Reasoning](https://arxiv.org/abs/2511.10621) - not-tiered
  - Fine-grained evaluation and refinement framework for LLM reasoning via iterative step-level confidence estimation and self-consistency checks
- **[source-cb5b780c67ab]** [Self-rewarding correction for mathematical reasoning](https://arxiv.org/abs/2502.19613) - not-tiered
  - Self-rewarding reasoning LLMs that generate step-by-step reasoning and evaluate correctness without external feedback during inference time
- **[source-6810d531b3d2]** [ARIES: Stimulating Self-Refinement of Large Language Models by Iterative Preference Optimization](https://arxiv.org/abs/2502.05605) - not-tiered
  - Self-refinement framework using iterative preference optimization for LLMs
- **[source-1d352a9ad6f1]** [SkillOS: Learning Skill Curation for Self-Evolving Agents](https://arxiv.org/html/2605.06614) - not-tiered
  - SkillOS: Learning skill curation for self-evolving agents; high-quality skill curation as bottleneck for reusable skill extraction from experience.
- **[source-15d81aca1df7]** [Autogenesis: A Self-Evolving Agent Protocol](https://arxiv.org/html/2604.15034) - not-tiered
  - Autogenesis Protocol: Self-evolution protocol decoupling what evolves from how evolution occurs; models prompts, agents, tools, environments, and memory as protocol resources.
- **[source-4043ba84aeaa]** [M★: Every Task Deserves Its Own Memory Harness](https://arxiv.org/html/2604.11811) - not-tiered
  - M-star: Automatically discovers task-optimized memory harnesses through executable program evolution; addresses memory transferability across domains.
- **[source-0e5f11e4e9bd]** [Dynamic Dual-Granularity Skill Bank for Agentic RL (D2Skill)](https://arxiv.org/html/2603.28716) - not-tiered
  - D2Skill: Dynamic dual-granularity skill bank organizing reusable experience into task skills and step skills for agentic RL.
- **[source-112633480450]** [Direct Nash Optimization: Teaching Language Models to Self-Improve with General Preferences](https://arxiv.org/abs/2404.03715) - not-tiered
  - Direct Nash optimization approach for LLMs to self-improve using general preference feedback from oracles
- **[source-4cd6912021b3]** [ArCHer: Training Language Model Agents via Hierarchical Multi-Turn RL](https://arxiv.org/abs/2402.19446) - not-tiered
  - Hierarchical multi-turn reinforcement learning for training LLM agents with goal-directed decision-making over multiple interaction turns
- **[source-425c859e0468]** [GLoRe: When, Where, and How to Improve LLM Reasoning via Global and Local Refinements](https://arxiv.org/abs/2402.10963) - not-tiered
  - Framework for identifying when and where to refine LLM reasoning using outcome-based and process-based reward models
- **[source-2b1e63936a90]** [V-STaR: Training Verifiers for Self-Taught Reasoners](https://arxiv.org/abs/2402.06457) - not-tiered
  - Training verifiers for self-taught reasoners using both correct and incorrect model-generated solutions with DPO
- **[source-b1bcf5d16555]** [ThinkTwice: Jointly Optimizing Large Language Models for Reasoning and Self-Refinement](https://arxiv.org/abs/2604.01591) - not-tiered
  - Joint optimization of LLMs for reasoning and self-refinement using Group Relative Policy Optimization across multiple reasoning benchmarks
- **[source-0018e0b8f6cd]** [AutoSkill: Experience-Driven Lifelong Learning via Skill Self-Evolution](https://arxiv.org/abs/2603.01145) - not-tiered
  - Experience-driven lifelong learning framework for LLM agents to derive and reuse skills from dialogue interaction traces
- **[source-8eaa5b383bf0]** [TextGrad: Automatic "Differentiation" via Text](https://arxiv.org/html/2406.07496) - tier 1 - peer-reviewed
  - AI is undergoing a paradigm shift, with breakthroughs achieved by systems orchestrating multiple LLMs and other complex components. Inspired by backpropagation and automatic differentiation, TextGrad introduces a framework performing automatic "differentiation" via text, backpropagating through textual feedback from LLMs.
- **[source-a5427a16cef6]** [Large Language Models as Optimizers (OPRO)](https://arxiv.org/abs/2309.03409) - tier 2
  - OPRO proposes using LLMs as optimizers where the optimization task is described in natural language. In each step, the LLM generates new solutions from a prompt containing previously generated solutions with their values, then new solutions are evaluated and added to the prompt for the next step.
- **[source-8128f4b2ea42]** [Revisiting OPRO: The Limitations of Small-Scale LLMs as Optimizers](https://arxiv.org/html/2405.10276v1) - not-tiered
  - OPRO Yang et al. (2023) and EvoPrompt frameworks demonstrate significant potential of LLMs in automating prompt design. However, effectiveness appears contingent upon inherent optimization capabilities of LLMs; evaluations have focused on large-scale models, leaving smaller LLMs unexplored.
- **[source-78899b631050]** [Beyond Prompt Engineering: How LLM Optimization Frameworks Like TextGrad and DSPy Are Building the Next Generation of Reliable AI](https://medium.com/@adnanmasood/beyond-prompt-engineering-how-llm-optimization-frameworks-like-textgrad-and-dspy-are-building-the-6790d3bf0b34) - not-tiered
  - TextGrad uses an "autograd for text" approach, iteratively refining outputs for single, complex problems using LLM-generated feedback in a test-time loop. DSPy acts as a "compiler," using a declarative, modular approach to optimize entire pipelines.
- **[source-a690d4e98567]** [TextGrad: Automatic Differentiation via Text (2026 Guide)](https://www.morphllm.com/textgrad) - not-tiered
  - Use TextGrad when: you have a hard problem instance and want to squeeze maximum performance out of the LLM by iteratively refining the output. Use DSPy when: building a multi-step prompt pipeline that needs to work reliably across many inputs, with labeled training data.
- **[source-b4ea7133130a]** [AutoMedPrompt: A New Framework for Optimizing LLM Medical Prompts Using Textual Gradients](https://arxiv.org/html/2502.15944) - not-tiered
  - Explores the application of TextGrad in the medical domain; presents AutoMedPrompt, which explores boosting foundation model performance in medical tasks through prompt engineering alternatives to fine-tuning and k-shot approaches.
- **[source-4b8d2e2289be]** [8 Production Readiness Checklist for Every AI Agent (Galileo)](https://galileo.ai/blog/production-readiness-checklist-ai-agent-reliability) - not-tiered
  - Production readiness checklist for AI agents: setup online evaluations, ad-hoc trace exploration, catalog failure modes, design graceful degradation strategies, and run chaos drills.
- **[source-53809040e197]** [Reinforcement Fine-tuning with LLM-as-a-Judge (AWS Machine Learning)](https://aws.amazon.com/blogs/machine-learning/reinforcement-fine-tuning-with-llm-as-a-judge/) - not-tiered
  - For mission-critical applications (healthcare documentation, legal review, financial compliance), reinforcement fine-tuning with LLM-as-a-judge provides performance gains justifying the compute overhead.
- **[source-81ad75df8694]** [Agent Evaluation Readiness Checklist (LangChain Blog)](https://blog.langchain.com/agent-evaluation-readiness-checklist/) - not-tiered
  - LangChain agent evaluation checklist covers online evaluations and scheduled ad-hoc trace exploration for production readiness assessment.
- **[source-58d3c55fd7df]** [Alignment Faking in Large Language Models (Anthropic)](https://arxiv.org/abs/2412.14093) - tier 2
  - LLM demonstrates selective compliance during training to prevent modification of behavior; faking alignment during training but showing genuine compliance during deployment.
- **[source-e1e6f6539d09]** [Empirical Evidence for Alignment Faking in a Small LLM and Prompt-Based Mitigation Techniques](https://arxiv.org/html/2506.21584v2) - not-tiered
  - First empirical evidence of alignment faking in smaller LLMs; prompt-only interventions like moral framing and scratchpad reasoning reduce deceptive behavior without model modification.
- **[source-6b3519f7df31]** [Contextual Experience Replay for Self-Improvement of Language Agents (ACL 2025)](https://arxiv.org/abs/2506.06698) - not-tiered
  - Training-free framework enabling efficient self-improvement for LLM agents through contextual experience replay; accumulates experiences within context window for continual learning during inference.
- **[source-2c1b0e21576d]** [How Memory Management Impacts LLM Agents: An Empirical Study of Experience-Following Behavior](https://arxiv.org/html/2505.16067) - not-tiered
  - Empirical study on how memory management operations (addition and deletion) impact LLM agent long-term performance; identifies experience-following behavior and performance degradation patterns.
- **[source-c60145895643]** [Audited Skill-Graph Self-Improvement for Agentic LLMs via Verifiable Rewards, Experience Synthesis, and Continual Memory](https://arxiv.org/html/2512.23760) - not-tiered
  - Addresses security and governance challenges in self-improving agents; covers reward hacking, behavioral drift, verifiable skill graphs, and audit mechanisms for self-improvement under RL.
- **[source-1a2911ee99fd]** [An Approach to Technical AGI Safety and Security](https://arxiv.org/pdf/2504.01849) - not-tiered
  - Addresses technical AGI safety including recursive improvement risks; discusses misaligned AI systems sabotaging improvement mechanisms.
- **[source-fa74d95e9c3e]** [AGI Evolution: The Risks and Rewards of Recursive Self-Improvement (SingularityNET)](https://singularitynet.io/agi-evolution-the-risks-and-rewards-of-recursive-self-improvement/) - not-tiered
  - Discusses unpredictable evolution and value misalignment in recursive self-improvement; covers how AGI could bypass security measures and manipulate information through rapid self-modification.
- **[source-9bc75dbeb3a5]** [The Runaway Risks of AGI (FOOM) | InfoSecured.ai](https://www.infosecured.ai/i/ai-definitions/foom-fast-takeoff-agi/) - not-tiered
  - FOOM (fast takeoff) theory: exponential intelligence growth via recursive self-improvement; discusses Yudkowsky's thesis on unstoppable improvement and loss of human control.
- **[source-648f01b2c7c8]** [MeNTi: Bridging Medical Calculator and LLM Agent with Nested Tool Calling](https://arxiv.org/html/2410.13610) - not-tiered
  - Medical domain-specific LLM agent architecture with integrated toolkit; employs nested tool calling for complex health assessment tasks requiring multiple tool interactions.
- **[source-56baa2f38e63]** [Cognitive Friction: A Decision-Theoretic Framework for Bounded Deliberation in Tool-Using Agents](https://arxiv.org/html/2603.30031) - not-tiered
  - Decision-theoretic framework for tool-using agents; addresses failure modes including excessive tool use under congestion, prolonged deliberation under time decay, and brittle behavior under ambiguous evidence.
- **[source-1d21807f4e6d]** [AI Agent Failure Pattern Recognition: The 6 Ways Agents Fail and How to Diagnose Them](https://www.mindstudio.ai/blog/ai-agent-failure-pattern-recognition) - not-tiered
  - Categorizes six core agent failure modes: context degradation, specification drift, sycophantic confirmation, tool errors, cascading failure, and silent failure with diagnostic approaches.
- **[source-17b66234cea3]** [7 AI Agent Failure Modes and How to Prevent Them](https://galileo.ai/blog/agent-failure-modes-guide) - not-tiered
  - Covers detection capabilities for agent failures including tool selection quality monitoring; proposes agentic-specific metrics for action completion, tool selection quality, and reasoning coherence.
- **[source-92ae5c44107f]** [How Tool Chaining Fails in Production LLM Agents and How to Fix It](https://futureagi.substack.com/p/how-tool-chaining-fails-in-production) - not-tiered
  - Identifies production tool-chaining failures: silent data corruption from format mismatches, context loss from window limits, and cascading hallucination when agents fill missing data.
- **[source-e7d68a3ad080]** [Your Agent May Misevolve: Emergent Risks in Self-evolving LLM Agents](https://arxiv.org/html/2509.26354) - not-tiered
  - Systematic study of misevolution risks in self-evolving agents along four evolutionary pathways: model, memory, tool, and workflow.
- **[source-329860d81e77]** [ComfySearch: Autonomous Exploration and Reasoning for ComfyUI Workflows](https://arxiv.org/html/2601.04060) - not-tiered
  - Agentic framework for exploring ComfyUI component space with validation-guided workflow construction to maintain structural consistency.
- **[source-37d1f6e94737]** [ComfyUI-R1: Exploring Reasoning Models for Workflow Generation](https://arxiv.org/html/2506.09790) - not-tiered
  - First large reasoning model for automated ComfyUI workflow generation using chain-of-thought reasoning for node selection and planning.
- **[source-acf44ac3bdb6]** [AgencyTree: Automated Multimedia Workflow Generation with Robust Planning via an Abstract Capability Tree](https://doi.org/10.1145/3812545) - not-tiered
  - Multi-agent framework with abstract capability tree to overcome planning brittleness and tightly-coupled vulnerabilities in LLM-based workflow automation.
- **[source-6d3d026df352]** [Belief Memory: Agent Memory Under Partial Observability](https://arxiv.org/html/2605.05583) - not-tiered
  - Proposes BeliefMem to address self-reinforcing error in agent memory by storing beliefs under uncertainty rather than single deterministic conclusions, complementary to MemRL's utility-driven memory evolution.
- **[source-20b0600b4a4f]** [MemReranker: Reasoning-Aware Reranking for Agent Memory Retrieval](https://arxiv.org/html/2605.06132) - not-tiered
  - Addresses limitations in two-stage retrieval-rerank paradigms for agent memory; proposes reasoning-aware reranking beyond semantic similarity, directly relevant to MemRL's two-phase retrieval design.
- **[source-bd02b4e790f9]** [Contextual Agentic Memory is a Memo, Not True Memory](https://arxiv.org/html/2604.27707) - not-tiered
  - Critiques vector-store and RAG-based memory systems as lookup rather than true memory; argues they lack generalization and face unlimited accumulation without expertise—core critique MemRL addresses.
- **[source-d5c2238a20c5]** [DSPy: Compiling Declarative Language Model Calls into Self-Improving Pipelines](https://arxiv.org/html/2310.03714) - not-tiered
  - DSPy abstracts LM pipelines as text transformation graphs with declarative modules and introduces a programming model for systematically developing and optimizing LM pipelines, moving away from hard-coded prompt templates.
- **[source-7f5a1930e071]** [MIPROv2 - DSPy API Documentation](https://dspy.ai/api/optimizers/MIPROv2/) - not-tiered
  - MIPROv2 generates optimized instructions and few-shot examples by using instruction proposer with dataset properties, program code, bootstrapped examples, and random tips to explore feature space of potential instructions.
- **[source-14c79f6b08ed]** [BootstrapFewShot - DSPy API Documentation](https://dspy.ai/api/optimizers/BootstrapFewShot/) - not-tiered
  - BootstrapFewShot optimizer automatically generates and includes optimized examples within the prompt, implementing few-shot learning through self-bootstrapping of the program's own traces.
- **[source-7305a1b115ae]** [Learning from Supervision with Semantic and Episodic Memory: A Reflective Approach](https://arxiv.org/html/2510.19897) - not-tiered
  - Memory-augmented framework using episodic memory for instance-level critiques and semantic memory for task-level guidance; LLM agents learning from labeled examples without parameter updates.
- **[source-43210baf9dbc]** [Latent Learning: Episodic Memory Complements Parametric Learning](https://arxiv.org/html/2509.16189) - not-tiered
  - Episodic memory as complement to parametric learning enabling latent learning; systems with episodic memory generalize better across diverse tasks and experiences.
- **[source-ee78ce485d0c]** [AriGraph: Learning Knowledge Graph World Models with Episodic Memory](https://arxiv.org/html/2407.04363) - not-tiered
  - LLM agents learn knowledge graph world models using episodic memory; structured memory representations for complex reasoning and planning in autonomous agents.
- **[source-e0f1900a68e6]** [Toward the Emergence of Intelligent Control: Episodic Generalization and Optimization](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11142636/) - not-tiered
  - Episodic Generalization and Optimization (EGO) framework with episodic memory for rapid learning and semantic pathway for slow generalization; cognitive science perspective on memory.
- **[source-e331d864d525]** [Efficient Episodic Memory Utilization of Cooperative Multi-Agent RL](https://arxiv.org/html/2403.01112) - not-tiered
  - Episodic Memory Utilization (EMU) for cooperative multi-agent RL; leverages semantically coherent episodic buffer to accelerate learning and escape local optima.
- **[source-897b7f9baf1b]** [Data-Prompt Co-Evolution: Growing Test Sets to Refine LLM Behavior (CHI 2026)](https://arxiv.org/html/2510.12728) - not-tiered
  - Data and prompts co-evolve in a single workflow: concrete test cases guide prompt refinement, and prompt edits grow the test set. Enables faster, iterative prompt engineering by removing separation between test data development and prompt instructions.
- **[source-24ef759bde89]** [Automatic Prompt Optimization for Knowledge Graph Construction: Insights from an Empirical Study (arXiv 2025)](https://arxiv.org/html/2506.19773) - not-tiered
  - Studies automatic prompt optimization for knowledge graph construction tasks, comparing multiple strategies for triple extraction and analyzing failure modes in KG construction.
- **[source-cdeef7ba283b]** [AutoHint: Automatic Prompt Optimization with Hint Generation (arXiv 2023)](https://arxiv.org/html/2307.07415) - not-tiered
  - Framework for automatic prompt engineering that combines in-context learning and zero-shot learning, using enriched instructions from input-output demonstrations to optimize prompts.
- **[source-8767017fd559]** [Doppelganger Method: Breaking Role Consistency in LLM Agent via Prompt-based Transferable Adversarial Attack (arXiv 2025)](https://arxiv.org/html/2506.14539) - not-tiered
  - Demonstrates vulnerabilities in prompt-based autonomous agents through adversarial attacks; exposes risks of prompt hijacking and behavioral inconsistency.
- **[source-a8db7c0b848c]** [Securing the Model Context Protocol: Defending LLMs Against Tool Poisoning and Adversarial Attacks (arXiv 2025)](https://arxiv.org/html/2512.06556) - not-tiered
  - Analyzes semantic attacks on MCP-integrated LLM systems including tool poisoning and adversarial manipulation of tool metadata; addresses security vulnerabilities in self-modifying agent architectures.
- **[source-ff819a16fc02]** [Adaptive heterogeneous multi-agent debate for enhanced educational and factual reasoning in large language models](https://link.springer.com/article/10.1007/s44443-025-00353-3) - not-tiered
  - Explores heterogeneous multi-agent LLM systems with agents assigned different personas (optimist, skeptic, etc.) to bias reasoning styles, focusing on role consistency and coherence.
- **[source-13dbe5708688]** [X-MAS: Towards Building Multi-Agent Systems with Heterogeneous LLMs](https://arxiv.org/html/2505.16997v1) - not-tiered
  - Proposes heterogeneous multi-agent LLM systems powered by diverse LLMs for specialization, extending beyond single-LLM constraint to elevate system intelligence.
- **[source-42ceb42a99ab]** [Intrinsic Memory Agents: Heterogeneous Multi-Agent LLM Systems through Structured Contextual Memory](https://arxiv.org/html/2508.08997v1) - not-tiered
  - Proposes heterogeneous multi-agent systems with structured contextual memory, focusing on role consistency and coherence through intrinsic memory agents.
- **[source-b44381db5fe9]** [LLM-Based Multi-Agent Systems for Software Engineering: Literature Review, Vision, and the Road Ahead](https://dl.acm.org/doi/10.1145/3712003) - not-tiered
  - Comprehensive survey of LLM-based multi-agent systems for software engineering covering homogeneous vs. heterogeneous architectures and diverse functions and expertise.
- **[source-8f318cfcc718]** [TextGrad: Automatic "Differentiation" via Text (arXiv 2024)](https://arxiv.org/abs/2406.07496) - not-tiered
  - Framework for automatic prompt optimization using textual gradients; demonstrates improvements on reasoning tasks, code optimization, and molecule design; published in Nature.
- **[source-c788e0ce7b13]** [OPRO: Large Language Models as Optimizers (GitHub Repository)](https://github.com/google-deepmind/opro) - not-tiered
  - Official code for OPRO (Optimization by PROmpting), Google DeepMind method that uses LLMs as optimizers to generate and refine prompts through in-context learning and trajectory tracking.
- **[source-777954dd33a6]** [Large Language Models As Optimizers (OPRO paper - arXiv)](https://arxiv.org/abs/2307.07415) - not-tiered
  - Google DeepMind paper introducing OPRO: treats LLMs as meta-optimizers using iterative feedback loops to generate and refine prompts; competitive with human-written prompts on multiple tasks.
- **[source-78218292092d]** [Google Explores Scaling Principles for Multi-Agent Coordination - InfoQ News (2026)](https://www.infoq.com/news/2026/02/google-agent-scaling-principles/) - not-tiered
  - InfoQ coverage of Google Research's controlled evaluation of 180 agent configurations deriving quantitative scaling principles; discusses how multi-agent coordination does not reliably improve results and can reduce performance, with predictive model achieving 87% accuracy.
- **[source-a54f86fda6a9]** [More Agents, Worse Results: Google Just Proved Multi-Agent Scaling Is a Myth - DEV Community (2026)](https://dev.to/ai_agent_digest/more-agents-worse-results-google-just-proved-that-multi-agent-scaling-is-a-myth-59b9) - not-tiered
  - DEV Community article on Google Research findings showing +81% improvement on parallelizable tasks vs -70% degradation on sequential planning, challenging conventional wisdom about multi-agent scaling.
- **[source-c2324948aff9]** [Scaling Agentic Systems: Quantitative Scaling Principles (Medium, 2026)](https://ajay-arunachalam08.medium.com/scaling-agentic-systems-moving-from-heuristics-to-quantitative-scaling-principles-for-your-agent-08a600009b13) - not-tiered
  - Medium article summarizing five canonical agent architectures with computational complexity analysis; covers k iterations per agent, n agents, r orchestrator rounds, d debate rounds, and p peer communication rounds metrics.
- **[source-12dc7c423764]** [Google Research Study: Scaling Multi-Agent Systems is a Strange Science - Techstrong.ai (2026)](https://techstrong.ai/agentic-ai/google-research-study-scaling-multi-agent-systems-is-a-strange-science/) - not-tiered
  - Technical analysis of Google findings on centralized coordination (+80.9% on parallelizable financial reasoning) vs decentralized (+9.2% on dynamic web navigation); covers error amplification (17.2x for independent, 4.4x for centralized) and coordination overhead trade-offs.
- **[source-80cbc110f6c7]** [PERMA: Benchmarking Personalized Memory Agents via Event-Driven Preference and Realistic Task Environments](https://arxiv.org/html/2603.23231) - not-tiered
  - PERMA benchmark for personalized memory agents; evaluates long-term memory and user preference adaptation with event-driven preferences in realistic task environments.
- **[source-77d0c544ae38]** [Styles + Persona-Plug = Customized LLMs (PsPLUG)](https://arxiv.org/pdf/2601.06362) - not-tiered
  - PsPLUG: lightweight plug-in framework for user-specific personalization via learnable persona prefixes; enables controllable personalization without full model fine-tuning.
- **[source-14aee6492b6a]** [ACEBench: Who Wins the Match Point in Tool Learning?](https://arxiv.org/abs/2501.12851) - not-tiered
  - Benchmark for evaluating tool learning methods; tests which approaches win on different tasks and model scales, directly assessing tool-calling reliability.
- **[source-4e85adfb6ad4]** [Tool Learning in the Wild: Empowering Language Models as Automatic Tool Agents](https://arxiv.org/html/2405.16533) - not-tiered
  - Addresses manual tool documentation parsing and in-context demonstrations for tool-calling; proposes automatic methods to overcome scaling limitations of manual toolset integration.
- **[source-33365c9af284]** [Evolving Excellence: Automated Optimization of LLM-based Agents](https://arxiv.org/pdf/2512.09108) - not-tiered
  - Artemis framework automatically identifies and optimizes agent components including prompts, tool descriptions, model parameters, and execution strategies; demonstrates 90x cost reduction for enterprise agents.
- **[source-2cc7d2f605a1]** [Building State-of-the-Art Enterprise Agents 90x Cheaper with Automated Prompt Optimization](https://www.databricks.com/blog/building-state-art-enterprise-agents-90x-cheaper-automated-prompt-optimization) - not-tiered
  - Databricks enterprise benchmarks for agent optimization; develops iterative structured search guided by feedback signals to automatically improve prompts while measuring accuracy and serving efficiency tradeoffs.
- **[source-8cbca9764319]** [Revolutionizing AI Interaction: DSPy and Its Modular Approach to Chain of Thought, Multi-Hop Retrieval](https://medium.com/@rohitobrai11/revolutionizing-ai-interaction-dspy-and-its-modular-approach-to-chain-of-thought-multi-hop-adb726ed4db7) - not-tiered
  - Multi-hop Chain of Thought reasoning with DSPy; demonstrates iterative retrieval and chain-of-thought composition for solving complex, multi-step reasoning tasks.
- **[source-cc2815abc66d]** [Optimizers - DSPy Documentation](https://dspy.ai/learn/optimization/optimizers/) - not-tiered
  - Official DSPy Optimizers documentation page listing available optimizers including MIPROv2 and BootstrapFewShot, which automatically generate and optimize examples within prompts.
- **[source-34deaea034a4]** [MemoryArena: Benchmarking Agent Memory in Interdependent Multi-Session Agentic Tasks](https://arxiv.org/html/2602.16313) - not-tiered
  - MemoryArena: benchmarks agent memory in multi-session interdependent tasks; evaluates how memory is acquired and used to guide future decisions across sessions with role-dependent contexts.
- **[source-4a2d10c1ae86]** [Agentic Memory: Learning Unified Long-Term and Short-Term Memory Management for Large Language Model Agents](https://arxiv.org/html/2601.01885) - not-tiered
  - Agentic Memory (AgeMem): unified LTM and STM management framework; memory operations exposed as tool-based actions for adaptive memory management.
- **[source-5b989270f9bc]** [Optimizing generative AI by backpropagating language model feedback (Nature)](https://www.nature.com/articles/s41586-025-08661-4) - not-tiered
  - Nature publication on TextGrad: a framework that performs optimization by backpropagating large language model-generated feedback for generative AI systems.
- **[source-6f62165a5db7]** [TextGrad: Automatic "Differentiation" via Text (Gonzo ML)](https://gonzoml.substack.com/p/textgrad-automatic-differentiation) - not-tiered
  - TextGrad essentially implements an analogue of backpropagation, but through text and with text-based gradients for optimization of compound AI systems.
- **[source-dda9e33a6bd4]** [SWE-TRACE: Optimizing Long-Horizon SWE Agents through Rubric Process Reward Models and Heuristic Test-Time Scaling](https://arxiv.org/html/2604.14820) - not-tiered
  - Traces long-horizon SWE agent optimization using rubric process reward models and test-time scaling; compares teacher models for decomposition quality and repair behavior with successful trajectory retention.
- **[source-9444f79bde03]** [TRACE: Capability-Targeted Agentic Training](https://arxiv.org/html/2604.05336) - not-tiered
  - TRACE framework for capability-targeted agentic training; demonstrates scaling with number of capabilities where TRACE outperforms GEPA prompt optimization that plateaus after 4 capabilities.
- **[source-4ab9049736ff]** [Failure makes the agent stronger: Enhancing Accuracy through Structured Reflection for Reliable Tool Interactions](https://arxiv.org/html/2509.18847) - not-tiered
  - Formulates reflection-based error localization, diagnosis, and repair as explicit trainable capability; optimizes via supervised signals and reward shaping for reliable tool interactions and self-correction.
- **[source-4520fa0269e7]** [GEPA: Why Reflection-Based Optimization Is Replacing Reinforcement Learning for AI Agents](https://www.comet.com/site/blog/gepa-ai-optimization/) - not-tiered
  - GEPA framework targets single-turn or few-turn tasks with clear input-output patterns; excels at refining core instructions guiding agent behavior through reflection-based optimization replacing RL.
- **[source-6bc747b4f921]** [HITSQL: Human-In-The-Loop Techniques for Enhancing Text-to-SQL Query Generation with Large Language Models](https://doi.org/10.1109/IJCNN64981.2025.11227910) - not-tiered
  - Human-in-the-loop active learning approach for text-to-SQL with iterative refinement, expert feedback, and adaptive fine-tuning over multiple evaluation iterations.
- **[source-7beefe93b431]** [SQLWizard: A Tool for Robust Text-to-SQL via Intelligent Selection and Fine-Grained Refinement](https://doi.org/10.1109/APSEC66846.2025.00123) - not-tiered
  - Tool for robust text-to-SQL using intelligent candidate selection guided by execution feedback and fine-grained multi-turn refinement.
- **[source-3570d8a07d13]** [Execution-Feedback and Retrieval-Augmented Generation for Conversational Text-to-SQL](https://doi.org/10.69987/jacs.2023.30201) - not-tiered
  - Conversational text-to-SQL pipeline combining schema linking and retrieval-augmented generation with execution feedback for error recovery across multi-turn dialogs.
- **[source-97f3faa53876]** [SQL-Trail: Multi-Turn Reinforcement Learning with Interleaved Feedback for Text-to-SQL](https://arxiv.org/html/2601.17699) - tier 2
  - Multi-turn reinforcement learning agentic framework using interleaved feedback and iterative reasoning, schema exploration, and error correction for text-to-SQL.
- **[source-2b74c6644b9b]** [MGRR-SQL: Multi-Granularity Relevant Retrieval-Based in-Context Learning Approach for Text-to-SQL Generation](https://doi.org/10.1109/ICAACE65325.2025.11019241) - not-tiered
  - Multi-granularity relevant retrieval approach for in-context learning in text-to-SQL, improving few-shot example selection across semantic, entity, and SQL-level granularities.
- **[source-2d5922134fbf]** [Enhancing Few-shot Text-to-SQL Capabilities of Large Language Models: A Study on Prompt Design Strategies](https://arxiv.org/html/2305.12586) - not-tiered
  - Systematic investigation of prompt design strategies for text-to-SQL using LLMs, exploring demonstration selection methods and instruction formats for in-context learning.
- **[source-e2a44bc62105]** [AutoLink: Autonomous Schema Exploration and Expansion for Scalable Schema Linking in Text-to-SQL at Scale](https://arxiv.org/html/2511.17190) - not-tiered
  - Autonomous schema exploration and expansion for scalable text-to-SQL using LLM-powered agents with semantic retrieval and lightweight SQL probes for iterative schema assembly.
- **[source-de36af00e4ad]** [Multi-Agent System Reliability: Failure Patterns, Root Causes, and Production Validation Strategies](https://www.getmaxim.ai/articles/multi-agent-system-reliability-failure-patterns-root-causes-and-production-validation-strategies/) - not-tiered
  - Failure patterns in multi-agent systems including retry storms, cascading failures, goal mismatches between agents, and architectural design strategies for soft failure and recovery
- **[source-6b92750cc2b2]** [Multi-Agent System Patterns: A Unified Guide to Designing Agentic Architectures](https://medium.com/@mjgmario/multi-agent-system-patterns-a-unified-guide-to-designing-agentic-architectures-04bb31ab9c41) - not-tiered
  - Multi-agent system design patterns showing well-designed systems fail softly, recover partial progress, and avoid cascading retries that amplify cost
- **[source-984bd64fedf8]** [Best AI Guardrails in 2026: Tools, Architecture, and How to Choose](https://generalanalysis.com/guides/best-ai-guardrails) - not-tiered
  - Discusses memory poisoning, prompt injection through documents, and tool misuse as documented failure modes found by red teams; covers guardrail implementation.
- **[source-2e574bc3b564]** [OpenAI Alignment: Recursive Self-Improvement Safety Research](https://alignment.openai.com/hello-world/) - not-tiered
  - OpenAI's research agenda on safe development of AI capable of recursive self-improvement; emphasizes human intent alignment, catastrophic behavior avoidance, and controllability in adversarial conditions.
- **[source-23890b470c7a]** [Text-to-SQL Empowered by Large Language Models: A Benchmark Evaluation (DAIL-SQL)](https://arxiv.org/abs/2308.15363) - not-tiered
  - DAIL-SQL: Data-integrated in-context learning approach achieving 86.6% execution accuracy on Spider leaderboard; efficient few-shot method empowered by LLMs with integrated solutions.
- **[source-51ac7d164b57]** [Solid-SQL: Enhanced Schema-linking based In-context Learning for Robust Text-to-SQL](https://arxiv.org/html/2412.12522v1) - not-tiered
  - Enhances schema-linking based in-context learning with robust text-to-SQL generation, improving upon DIN-SQL and similar approaches.
- **[source-f3d4eedf1ee2]** [DCG-SQL: Enhancing In-Context Learning for Text-to-SQL with Deep Contextual Schema Link Graph](https://arxiv.org/html/2505.19956v1) - not-tiered
  - Deep contextual schema link graph for enhanced in-context learning in text-to-SQL generation.
- **[source-45842ffeffb1]** [APEX-EM: Non-Parametric Online Learning for Autonomous Agents via Structured Procedural-Episodic Experience Replay](https://arxiv.org/html/2603.29093) - not-tiered
  - Non-parametric online learning for autonomous agents via structured procedural-episodic experience replay; establishes frozen-backbone memory baseline for comparison with MemRL on the same benchmarks.
- **[source-33d7d2393dae]** [BIRD-INTERACT: Re-imagining Text-to-SQL Evaluation via Lens of Dynamic Interactions](https://arxiv.org/abs/2510.05318) - not-tiered
  - Interactive text-to-SQL benchmark with comprehensive interaction environment, knowledge base, and user simulator enabling models to recover from execution errors and explore the database autonomously.
- **[source-2925fa895369]** [Evaluating LLMs for Text-to-SQL Generation With Complex SQL Workload](https://arxiv.org/html/2407.19517v1) - not-tiered
  - Analysis and comparison of text-to-SQL evaluation on TPC-DS, BIRD, and Spider benchmarks with complex SQL workloads.
- **[source-fc64825435e7]** [MASPrism: Lightweight Failure Attribution for Multi-Agent Systems Using Prefill-Stage Signals](https://arxiv.org/html/2605.07509) - not-tiered
  - Lightweight framework for failure attribution in multi-agent systems using token-level signals from small language models to identify steps contributing to failed execution
- **[source-7d7a7ab5e4d0]** [Improving the Efficiency of Language Agent Teams with Adaptive Task Graphs (LATTE)](https://arxiv.org/html/2605.06320) - not-tiered
  - Framework for coordinating LLM teams with adaptive task graphs to address inefficiencies like error propagation, inter-agent conflicts, and resource waste in language agent teams
- **[source-55ed0557ab08]** [Conformal Agent Error Attribution](https://arxiv.org/html/2605.06788) - not-tiered
  - Framework for error attribution based on conformal prediction that provides finite-sample coverage guarantees for identifying where decisive errors occur in multi-agent trajectories
- **[source-1dcaea095740]** [Coordination as an Architectural Layer for LLM-Based Multi-Agent Systems](https://arxiv.org/html/2605.03310) - not-tiered
  - Argues coordination should be treated as configurable architectural layer separable from agent logic; 41-87% production failure rates mostly from coordination defects not model capability
- **[source-831ced92b454]** [Towards a Science of Scaling Agent Systems Project Overview - MIT Media Lab (2026)](https://www.media.mit.edu/projects/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/overview/) - not-tiered
  - MIT Media Lab project overview on quantitative scaling principles for agent systems; derives predictive model identifying optimal architecture for 87% of unseen tasks across parallelizable vs sequential task types.
- **[source-4a7e838df1fd]** [Chain-of-Thought Prompting Elicits Reasoning in Large Language Models](https://arxiv.org/html/2201.11903) - not-tiered
  - Explores how generating chains of intermediate reasoning steps significantly improves LLM complex reasoning, and how chain-of-thought prompting with demonstrations emerges naturally in large models.
- **[source-98c3e6420de4]** [Synthetic Prompting: Generating Chain-of-Thought Demonstrations for Large Language Models](https://arxiv.org/html/2302.00618) - not-tiered
  - Proposes Synthetic Prompting: leverage a few handcrafted examples to prompt models to generate more examples by themselves, alternating between backward and forward processes to generate and select effective demonstrations.
- **[source-295864bb8760]** [Automatic Chain of Thought Prompting in Large Language Models](https://arxiv.org/html/2210.03493) - not-tiered
  - Proposes automatic chain of thought prompting method that addresses the hand-crafting challenge; compares simple prompting vs hand-crafted demonstrations vs automatic generation.
- **[source-9ee733613685]** [Collaborative Memory: Multi-User Memory Sharing in LLM Agents with Dynamic Access Control](https://arxiv.org/html/2505.18279v1) - tier 2
  - Dual-tier memory architecture with private memory for sensitive info and shared memory for controlled knowledge transfer across users; demonstrates 61% resource reduction at 50% query overlap.
- **[source-c2f33d2ebeff]** [AI Memory Management for LLMs and Agents (Mem0 Blog)](https://mem0.ai/blog/ai-memory-management-for-llms-and-agents) - not-tiered
  - Memory scoping patterns including per-user, per-agent, per-run, and org-level contexts; practical patterns for managing memory isolation and sharing in multi-agent deployments.
- **[source-90549fc6620e]** [EVOR: Evolving Retrieval for Code Generation](https://arxiv.org/html/2402.12317) - not-tiered
  - Synchronous evolution of queries and diverse knowledge bases for adaptive RAG; demonstrates RAG evolution and multi-source adaptation for code generation tasks.
- **[source-93bc6514b4a0]** [CoRank: LLM-Based Compact Reranking for Scientific Retrieval](https://arxiv.org/html/2505.13757) - not-tiered
  - Document reranking for scientific retrieval using LLM-based compact reranking; addresses challenges in scientific domain where first-stage retrieval is suboptimal and reranking must balance context window limits.
- **[source-fb7c7001639a]** [How Important is Recall for Measuring Retrieval Quality?](https://arxiv.org/html/2512.20854) - not-tiered
  - Evaluates retrieval quality metrics and their correlation with LLM-based judgments of response quality; addresses practical challenge where total relevant documents are unknown in evolving knowledge bases.
- **[source-fceb54397dc9]** [Learning Adaptive Parallel Reasoning with Language Models (arXiv 2025)](https://arxiv.org/html/2504.15466) - not-tiered
  - Proposes Adaptive Parallel Reasoning (APR) framework enabling LLMs to orchestrate both parallel and serial computations; addresses limitations of serialized chain-of-thought (overly long outputs) and parallel methods (insufficient coordination, redundant computation).
- **[source-9abd2134b145]** [Sequential vs Parallel Tool/Reasoning in AI Agents (Medium, 2026)](https://medium.com/@speaktoharisudhan/sequential-vs-parallel-reasoning-in-ai-agents-9286040e1f6b) - not-tiered
  - Medium article discussing sequential vs parallel tool/reasoning selection in AI agents; notes that orchestration layer becomes critical component, and parallel reasoning should be selected when tasks are independent.
- **[source-9346f52b4092]** [Single-Agent vs Multi-Agent AI: When to Scale Your Dev Workflow (Augment Code)](https://www.augmentcode.com/guides/single-agent-vs-multi-agent-ai) - not-tiered
  - Practical guide comparing single-agent vs multi-agent AI development workflows; cites Google Research scaling study finding +81% improvement on parallelizable Finance-Agent benchmark with multi-agent coordination.
- **[source-2319e730e9e2]** [Detecting and Correcting Reference Hallucinations in Commercial LLMs and Deep Research Agents](https://arxiv.org/html/2604.03173v1) - not-tiered
  - Detection and correction of reference hallucinations in LLMs; benchmarks like GhostCite (13 LLMs across 40 domains with 14-95% hallucination rates) and CiteAudit (97% verification accuracy on benchmarks).
- **[source-7e1214aeea17]** [Citation Drift: Measuring Reference Stability in Multi-Turn Interactions](https://aclanthology.org/2025.wasp-main.20.pdf) - not-tiered
  - Citation drift across multi-turn LLM interactions; measures reference stability in scientific communication; addresses hallucinations and reference accuracy as critical for LLM reliability in scientific research.
- **[source-a3a2b34f9497]** [Large Language Models Hallucination: A Comprehensive Survey](https://arxiv.org/html/2510.06265v2) - not-tiered
  - Comprehensive survey of hallucination research in LLMs; taxonomy of hallucination types, root causes across LLM lifecycle, detection methods, and mitigation strategies.
- **[source-95202935e5b2]** [The Inverse-Wisdom Law: Architectural Tribalism and the Consensus Paradox in Agentic Swarms (arXiv 2026)](https://arxiv.org/html/2604.27274) - not-tiered
  - Challenges "Wisdom of the Crowd" assumption in multi-agent systems; formalizes Consensus Paradox where agentic swarms prioritize internal agreement over logical truth; proves Inverse-Wisdom Law across 12,804 trajectories on GAIA, Multi-Challenge, SWE-bench.
- **[source-417f0d6a360a]** [In-Context Prompting Obsoletes Agent Orchestration for Procedural Tasks (arXiv 2026)](https://arxiv.org/html/2604.27891) - tier 2
  - Controlled comparison showing simple in-context prompting with self-orchestration dominates agent orchestration frameworks (LangGraph, CrewAI, Google ADK) for procedural tasks across travel booking, support, and insurance domains.
- **[source-b8103ab22a08]** [Chain of Retrieval (CoR): Multi-Aspect Iterative Search Expansion for Full Paper Retrieval](https://arxiv.org/html/2507.10057) - tier 2
  - Multi-aspect iterative search expansion with post-order aggregation for full-paper retrieval; uses specialized LLM agents for motivation, method, experiment aspects; achieves 7.82% Recall gain over embedding-based approaches.
- **[source-2b20465b9dca]** [AMD: Agent-Mediated Query Expansion via Socratic Questioning and Dialogic Inquiry](https://arxiv.org/html/2502.08557v3) - not-tiered
  - Agent-mediated framework combining Socratic Questioning and Dialogic Answering for query expansion; iteratively refines pseudo-answers with reflective feedback for diverse sub-question reformulation.
- **[source-c29da7705db7]** [Query Expansion in the Age of Pre-trained and Large Language Models](https://arxiv.org/pdf/2509.07794) - not-tiered
  - Query expansion in the age of pre-trained and LLMs; covers retrieval-conditioned QE methods including constraint-based (SEAL), selection-based (EAR), and feedback-calibrated approaches (MUGI, FGQE) with learned rerankers.
- **[source-ef61d5668f12]** [A Comparative Study of DSPy Teleprompter Algorithms for Aligning Large Language Models Evaluation Metrics to Human Evaluation](https://arxiv.org/html/2412.15298v1) - not-tiered
  - Compares DSPy teleprompter algorithms for aligning LLM evaluation metrics to human evaluation; describes how DSPy uses optimizers to tune parameters like examples and prompts.
- **[source-7ca700cb1ffd]** [DSPy Framework — Programmatic Prompt Optimization (MyEngineeringPath)](https://myengineeringpath.dev/tools/dspy-guide/) - not-tiered
  - DSPy framework guide covering programmatic prompt optimization; describes how teleprompters take programs, training data, and metrics to systematically search for best prompt configurations.
- **[source-0c6b6683b1fb]** [Prompt Optimization with DSPy | Haystack](https://haystack.deepset.ai/cookbook/prompt_optimization_with_dspy) - not-tiered
  - Prompt optimization with DSPy using Haystack; demonstrates BootstrapFewShot optimizer that improves metrics by adding few-shot examples to prompts and iterating.
- **[source-cf91d9b886b4]** [Benchmarks Used in Scaling Agent Systems Study (Google Research)](https://arxiv.org/html/2512.08296v2) - not-tiered
  - Google Research study evaluates four diverse benchmarks: Finance-Agent (financial reasoning), BrowseComp-Plus (web navigation), PlanCraft (game planning), and Workbench (workflow execution) across five canonical agent architectures.
- **[source-bb561efc292f]** [AgentArch: A Comprehensive Benchmark to Evaluate Agent Architectures in Enterprise (arXiv 2509.10769)](https://arxiv.org/html/2509.10769v1) - not-tiered
  - AgentArch: comprehensive benchmark addressing limited empirical understanding of how different design dimensions interact in complex multi-agent systems; enterprise-specific focus on evaluating agent architectures comprehensively.
- **[source-54adb8443fe1]** [Evaluating AI Agents in Practice: Benchmarks, Frameworks, and Lessons Learned (InfoQ)](https://www.infoq.com/articles/evaluating-ai-agents-lessons-learned/) - not-tiered
  - InfoQ article covering practical approaches to evaluating AI agents in production systems; addresses benchmarks, hybrid evaluation pipelines, reliability assessment, and real-world system behavior.
- **[source-139456150ef8]** [Architectures for Multi-Agent Systems (Galileo AI)](https://galileo.ai/blog/architectures-for-multi-agent-systems) - not-tiered
  - Galileo AI article on multi-agent architecture scaling advice; recommends starting centralized, moving to hierarchical/hybrid at scale; emphasizes architecture should mirror organizational structure and problem decomposition.
- **[source-6451d3afccf8]** [Google Publishes Scaling Principles for Agentic Architectures (InfoQ 2026)](https://www.infoq.com/news/2026/03/google-multi-agent/) - not-tiered
  - InfoQ coverage of Google's scaling principles identifying three dominant effects: tool-coordination trade-off, capability saturation, and topology-dependent error amplification; financial reasoning benefits from centralized, web navigation from decentralized.
- **[source-c8b086890193]** [More Is Not Always Better: Cross-Component Interference in LLM Agent Scaffolding](https://arxiv.org/html/2605.05716) - not-tiered
  - Studies cross-component interference in LLM agent scaffolding (planning, tools, memory, self-reflection, retrieval); shows that more components isn't always better due to destructive interactions.
- **[source-9727009e3a5f]** [Revisiting OPRO: The Limitations of Small-Scale LLMs as Optimizers](https://arxiv.org/html/2405.10276) - not-tiered
  - OPRO (Optimization by PROmpting) leverages LLMs as optimizers to find instructions that maximize task accuracy; paper revisits OPRO's limitations with small-scale LLMs and inference capabilities.
- **[source-e1d6853199a5]** [Better by Comparison: Retrieval-Augmented Contrastive Reasoning for Automatic Prompt Optimization](https://arxiv.org/html/2509.02093) - not-tiered
  - CRPO (Contrastive Reasoning Prompt Optimization) formulates prompt optimization as retrieval-augmented reasoning using contrasting examples and LLM reasoning to learn from comparisons.
- **[source-169e65ae2bba]** [R-Zero: Self-Evolving Reasoning LLM from Zero Data](https://arxiv.org/html/2508.05004) - not-tiered
  - Fully autonomous framework for self-evolving LLMs generating training data from scratch; demonstrates autonomous data generation without human supervision—contrasts with Multi-Agent Evolve's co-evolution approach by using single-LLM self-play.
- **[source-9d88dad5b702]** [SPIRAL: Self-Play on Zero-Sum Games Incentivizes Reasoning via Multi-Agent Multi-Turn RL](https://arxiv.org/html/2506.24119) - not-tiered
  - Self-play framework using multi-turn zero-sum games against evolving opponents; multi-agent co-evolution pattern for self-improvement without human supervision—directly comparable to Multi-Agent Evolve's game-theoretic approach.
- **[source-8affc89eec7c]** [Absolute Zero: Reinforced Self-play Reasoning with Zero Data](https://arxiv.org/html/2505.03335) - not-tiered
  - RL with verifiable outcome-based rewards operating under zero-data setting; addresses scalability of human supervision in reasoning tasks—key comparison point for Multi-Agent Evolve's self-rewarding mechanism.
- **[source-608442ddd01e]** [Self-Challenging Language Model Agents](https://arxiv.org/html/2506.01716) - not-tiered
  - Self-challenging framework where agent generates own tasks after tool interaction; demonstrates role-based task generation without external annotation—similar to Proposer role in Multi-Agent Evolve.
- **[source-741141815f07]** [SeRL: Self-Play Reinforcement Learning for Large Language Models with Limited Data](https://arxiv.org/html/2505.20347) - not-tiered
  - Self-play RL with self-instruction and self-rewarding modules for bootstrapping with limited initial data; dual mechanism approach similar to Multi-Agent Evolve's Proposer-Judge dynamics.
- **[source-33576078881b]** [Self-Improvement of Language Models by Post-Training on Multi-Agent Debate](https://arxiv.org/html/2509.15172) - not-tiered
  - Multi-agent debate provides richer training signal than single-round majority voting for self-improvement without external supervision; empirically demonstrates multi-agent collaboration vs single-agent consensus approaches.
- **[source-2d77cbeef64a]** [Stop Overvaluing Multi-Agent Debate: We Must Rethink Evaluation and Embrace Model Heterogeneity](https://arxiv.org/html/2502.08788) - tier 2
  - Critical evaluation finding multi-agent debate often fails to outperform simple single-agent baselines; systematic comparison across 9 benchmarks challenges conventional wisdom about multi-agent approaches.
- **[source-898bf9fd41d7]** [SAGE: Multi-Agent Self-Evolution for LLM Reasoning](https://arxiv.org/html/2603.15255) - not-tiered
  - SAGE uses four co-evolving agents (Challenger, Planner, Solver, Critic) for ground truth-free reasoning improvement; directly comparable multi-agent co-evolution framework with explicit role specialization.
- **[source-a0f3ba4f1f9e]** [Dual-Phase LLM Reasoning: Self-Evolved Mathematical Frameworks](https://arxiv.org/html/2601.05616) - not-tiered
  - Self-evolved mathematical frameworks using self-generated CoT data through multi-turn dialogue with verification and backtracking; contrasts supervised fine-tuning vs RL approaches for reasoning improvement.
- **[source-8466bbb6096b]** [MathMixup: Boosting LLM Mathematical Reasoning with Difficulty-Controllable Data Synthesis](https://arxiv.org/html/2601.17006) - not-tiered
  - Difficulty-controllable data synthesis with curriculum learning for mathematical reasoning; addresses lack of precise difficulty control in self-generated training data—key to adversarial curriculum generation in co-evolution.
- **[source-28d53af4c27f]** [PromptSculptor: Multi-Agent Based Text-to-Image Prompt Optimization](https://arxiv.org/html/2509.12446) - not-tiered
  - Multi-agent framework that decomposes prompt refinement into four specialized agents working collaboratively; contrasts with single-agent approaches by enabling parallel optimization across distinct refinement dimensions.
- **[source-37f8a98711b5]** [MALT: Improving Reasoning with Multi-Agent LLM Training](https://arxiv.org/html/2412.01928) - not-tiered
  - Multi-agent training strategy dividing reasoning into generation, verification, refinement stages using heterogeneous agents; demonstrates how multi-agent architectures enable joint optimization compared to single-chain reasoning.
- **[source-e6be572b64b2]** [MAPGD: Multi-Agent Prompt Gradient Descent for Collaborative Prompt Optimization](https://arxiv.org/html/2509.11361) - not-tiered
  - Multi-agent framework reconceptualizing prompt optimization as collaborative process among specialized agents focusing on distinct refinement dimensions; shows distributed search vs single trajectory limitations.
- **[source-6aafdde27bfa]** [Multi-Agent Distributed Lifelong Learning for Collective Knowledge Acquisition](https://arxiv.org/html/1709.05412) - not-tiered
  - Extends lifelong learning from single agent to network of multiple agents collectively learning series of tasks; each agent faces unique task set but knowledge from one agent benefits others on related tasks.
- **[source-a84ab46e51d1]** [SE-Agent: Self-Evolution Trajectory Optimization in Multi-Step Reasoning with LLM-Based Agents](https://arxiv.org/html/2508.02085) - not-tiered
  - Self-evolution trajectory optimization for multi-step reasoning agents using trajectories as rich feedback signal; addresses how agent interaction traces enable continuous improvement beyond single-shot approaches.
- **[source-785ae57c8a73]** [Can Textual Gradient Work in Federated Learning?](https://arxiv.org/html/2502.19980) - not-tiered
  - Explores textual gradient in federated learning; addresses scalability and cross-client feedback aggregation challenges for TextGrad-style methods.
- **[source-218cc8cc24b9]** [Revolve: Optimizing AI Systems by Tracking Response Evolution in Textual Optimization](https://arxiv.org/html/2412.03092) - not-tiered
  - Proposes second-order textual optimization tracking response evolution; outperforms first-order TextGrad by up to 29.17% on code optimization, suggesting gradient metaphor is incomplete.
- **[source-1dd90a25bd55]** [Rethinking the Value of Multi-Agent Workflow: A Strong Single Agent Baseline](https://arxiv.org/html/2601.12307v1) - tier 2
  - Empirical comparison showing single agent can reach performance of homogeneous multi-agent workflows with efficiency advantage from KV cache reuse, and can even match automatically optimized heterogeneous workflows. Direct investigation of when multi-agent workflows provide value.
- **[source-8ad032b4ac26]** [Meta-Rewarding Language Models: Self-Improving Alignment with LLM-as-a-Meta-Judge](https://arxiv.org/html/2407.19594v2) - not-tiered
  - Meta-rewarding framework where LLM acts as both actor and meta-judge, self-improving alignment without external reward model; extends self-rewarding paradigm with hierarchical judgment.
- **[source-58d2b212e046]** [Igniting Creative Writing in Small Language Models: LLM-as-a-Judge versus Multi-Agent Refined Rewards](https://arxiv.org/html/2508.21476v1) - not-tiered
  - Compares LLM-as-a-judge approach with multi-agent refined rewards for creative writing; empirical comparison of self-rewarding vs multi-agent reward generation mechanisms.
- **[source-9be8626254e6]** [Automatic Prompt Optimization with "Gradient Descent" and Beam Search](https://aclanthology.org/2023.emnlp-main.494/) - not-tiered
  - APO (formerly ProTeGi) uses natural language "gradients" formed from minibatches as criticisms of current prompts; iteratively refines prompts via beam search and gradient descent-like updates.
- **[source-d1fdcfd05668]** [Textual Gradient Feedback - EmergentMind Topic](https://www.emergentmind.com/topics/textual-gradient-feedback) - not-tiered
  - Summary of textual gradient feedback: inverted or adversarial feedback do not degrade test-time accuracy and overfitting is not observed—violates standard gradient dynamics assumption.
- **[source-a138e0bafff3]** [Rethinking the Value of Multi-Agent Workflow: A Strong Single Agent Baseline](https://arxiv.org/html/2601.12307) - not-tiered
  - Investigates whether homogeneous multi-agent workflows can be simulated by single agent through multi-turn conversations; questions if role differentiation alone provides value
- **[source-197b1eae38a2]** [iMAD: Intelligent Multi-Agent Debate for Efficient and Accurate LLM Inference](https://arxiv.org/html/2511.11306) - not-tiered
  - Notes that triggering MAD for every query is inefficient and may degrade accuracy by overturning correct answers; proposes selective deployment strategy
- **[source-4b740dcb49fe]** [Literature Review Of Multi-Agent Debate For Problem-Solving](https://arxiv.org/html/2506.00066) - not-tiered
  - Synthesizes research on agent profiles, communication structures, decision-making; addresses lack of direct comparisons in field and scalability considerations
- **[source-e8f5e6a00b2f]** [Talk Isn't Always Cheap: Understanding Failure Modes in Multi-Agent Debate](https://arxiv.org/pdf/2509.05396) - tier 2
  - Examines failure modes in homogeneous multi-agent debate through iterative discussion; focuses on when debate breaks down and doesn't improve answers
- **[source-d4a88268bd6a]** [G-DMAD: Group-Based Diverse Multi-Agent Debate for Robust Reasoning](https://doi.org/10.1109/ACCESS.2026.3667025) - not-tiered
  - Proposes structured cross-agent coordination with distinct reasoning strategies; contrasts homogeneous approaches with strategy-based differentiation within same LLM
- **[source-1addb37222a2]** [Improving Factuality and Reasoning in Language Models with Multiagent Debate](https://composable-models.github.io/llm_debate/) - not-tiered
  - Demonstrates multiagent debate improves factual accuracy and reasoning over single-agent generation; positive evidence on when debate helps
- **[source-12dceab6fe8e]** [Beyond the Strongest LLM: Multi-Turn Multi-Agent Orchestration vs. Single LLMs on Benchmarks](https://arxiv.org/html/2509.23537) - not-tiered
  - Studies multi-turn multi-agent orchestration where multiple LLM agents interact iteratively to reach consensus, comparing against single-LLM baselines on GPQA-Diamond, IFEval, and MuSR benchmarks using four LLMs.
- **[source-c4c7057bfed3]** [Unlocking the Power of Multi-Agent LLM for Reasoning: From Lazy Agents to Deliberation](https://arxiv.org/html/2511.02303) - not-tiered
  - Identifies critical limitation where one agent dominates and the other contributes little in multi-agent systems, collapsing multi-agent setup to ineffective single agent; proposes solutions to unlock deliberation.
- **[source-e5f13b4bdee7]** [KVComm: Online Cross-context KV-cache Communication for Efficient LLM-based Multi-agent Systems](https://arxiv.org/html/2510.12872v1) - not-tiered
  - Challenges the direct reuse of KV caching in multi-agent scenarios, showing that diverging prefixes from agent-specific context extensions prevent KV cache reuse—counter to the efficiency claim in single-agent simulations.
- **[source-0d845dabfb0c]** [From Multi-Agent to Single-Agent: When Is Skill Distillation Beneficial?](https://arxiv.org/html/2604.01608) - not-tiered
  - Studies when distilling multi-agent systems into single-agent skills is beneficial; finds skill lift ranges from 28% improvement to 2% degradation depending on evaluation metric, revealing that skill utility depends on metric not task.
- **[source-672f52e09b93]** [On the Reliability Limits of LLM-Based Multi-Agent Planning](https://arxiv.org/html/2603.26993) - not-tiered
  - Models multi-agent architecture as decision network and proves that without new exogenous signals, any delegated multi-agent network is decision-theoretically dominated by a centralized Bayes decision maker with the same information.
- **[source-969422fa0aaf]** [Towards Optimal Agentic Architectures for Offensive Security Tasks](https://arxiv.org/html/2604.18718) - not-tiered
  - Controlled empirical benchmark with 600 runs across five architecture families showing unclear gains from additional agents; treats topology choice as empirical systems question.
- **[source-612c4a2967f4]** [When Single-Agent with Skills Replace Multi-Agent Systems and When They Fail](https://arxiv.org/html/2601.04748) - tier 2
  - Directly compares when single-agent with skill libraries can replace multi-agent systems and identifies when they fail, exploring the trade-off between modularity and communication overhead.
- **[source-cb02733d02dd]** [The Optimization Paradox in Clinical AI Multi-Agent Systems](https://arxiv.org/html/2506.06574) - not-tiered
  - Reveals optimization paradox in multi-agent systems: component-level optimization of individual agents doesn't guarantee system-level performance; empirical evaluation on clinical diagnosis across 2,400 patient cases.
- **[source-ddbbe281a9d2]** [Every Response Counts: Quantifying Uncertainty of LLM-based Multi-Agent Systems through Tensor Decomposition](https://arxiv.org/html/2604.08708) - not-tiered
  - Quantifies uncertainty in multi-agent systems, revealing challenges from communication dynamics and role dependencies; shows standard uncertainty quantification methods fail for multi-step multi-agent reasoning.
- **[source-36f3fcd3b176]** [Preventing Rogue Agents Improves Multi-Agent Collaboration](https://arxiv.org/html/2502.05986) - not-tiered
  - Demonstrates single rogue agent can cause entire multi-agent system failure; proposes methods to prevent rogue agents in collaborative systems.
- **[source-31a1a4347f7b]** [Modular Task Decomposition and Dynamic Collaboration in Multi-Agent Systems Driven by Large Language Models](https://arxiv.org/html/2511.01149) - not-tiered
  - Addresses limitations of single agent in task decomposition and collaboration for complex task execution; proposes modular decomposition mechanism with dynamic scheduling and routing for multi-agent architecture.
- **[source-c167dfdeb037]** [Improving Role Consistency in Multi-Agent Collaboration via Quantitative Role Clarity](https://arxiv.org/html/2604.02770) - not-tiered
  - Identifies role consistency (agents adhering to their assigned roles) as a major failure mode in multi-agent systems; proposes quantitative role clarity metrics to improve consistency, revealing the specialized role problem single agents cannot easily solve.
- **[source-74621042e523]** [Breaking the Martingale Curse: Multi-Agent Debate via Asymmetric Cognitive Potential Energy](https://arxiv.org/html/2603.06801) - not-tiered
  - Identifies limitation of standard MAD: cannot improve beyond majority voting; correlated errors cause convergence to erroneous consensus where debate reinforces mistakes
- **[source-92f30e8f6de0]** [Epistemic Gain, Aleatoric Cost: Uncertainty Decomposition in Multi-Agent Debate for Math Reasoning](https://arxiv.org/html/2603.01221) - not-tiered
  - Analyzes paradoxical phenomena in MAD: accuracy improvement with entropy increase; divergence between homogeneous and heterogeneous combinations
- **[source-3f3025c4e0c5]** [Dynamic Role Assignment for Multi-Agent Debate](https://arxiv.org/html/2601.17152) - not-tiered
  - Proposes meta-debate to assign roles based on model specialization; implies static role assignment is suboptimal even with same LLM
- **[source-9638821910d2]** [DynaDebate: Breaking Homogeneity in Multi-Agent Debate with Dynamic Path Generation](https://arxiv.org/html/2601.05746) - not-tiered
  - Addresses homogeneous debate limitation: unguided initialization causes identical reasoning paths leading to same errors; prevents effective debate
- **[source-0ea75abb06cb]** [Can LLM Agents Really Debate? A Controlled Study of Multi-Agent Debate in Logical Reasoning](https://arxiv.org/html/2511.07784) - not-tiered
  - Controlled study examining whether debate goes beyond ensembling/majority voting; systematic evaluation of team size, composition, confidence effects
- **[source-e1553f9aac65]** [More Rounds, More Noise: Why Multi-Turn Review Fails to Improve Cross-Context Verification](https://arxiv.org/html/2603.16244) - not-tiered
  - Multi-turn variants failed to improve on single-pass baseline; dynamic multi-turn review degraded performance; negative evidence for iterative refinement
- **[source-922061761d41]** [Single-Agent LLMs Outperform Multi-Agent Systems on Multi-Hop Reasoning Under Equal Thinking Token Budgets](https://arxiv.org/html/2604.02460v1) - tier 2
  - Empirical study showing single-agent systems can match or outperform multi-agent systems when computation is normalized; gains in prior MAS work often confounded by increased test-time computation.
- **[source-5a34fc3e2a35]** [Debate or Vote: Which Yields Better Decisions in Multi-Agent Systems](https://arxiv.org/pdf/2508.17536) - not-tiered
  - Evaluates whether majority voting is as effective as debate on larger model sizes, heterogeneous agents, and open-ended questions; finds voting remains comparable
- **[source-c67148c3bd7d]** [Breaking Mental Set to Improve Reasoning through Diverse Multi-Agent Debate](https://openreview.net/forum?id=t6QHYUOQL7) - not-tiered
  - Identifies fixed mental set problem: homogeneous reasoning methods in debate even with different personas; compares with self-reflection limitations
- **[source-48475d523b55]** [Multi-Agent Debate: Framework & Applications (EmergentMind)](https://www.emergentmind.com/topics/multi-agent-debate-approach) - not-tiered
  - Knowledge resource documenting agent homogeneity issue: identical models often lead to consensus but miss rare correct paths; requires path diversity or heterogeneity
