# Research report

**Query:** What are the best RL algorithms?

# What Are the Best RL Algorithms?

## Bottom-line takeaway

There is no single "best" RL algorithm. Which algorithm wins depends decisively on (1) **action space** (discrete vs. continuous), (2) **sample budget and simulator availability**, (3) **whether rewards are dense, sparse, or verifiable**, and (4) **whether you need a policy for a single task, LLM alignment, or multi-agent cooperation**. That said, the literature converges on a defensible shortlist: **PPO, SAC, TD3, and DQN** remain the most widely-used and well-tooled choices [source-15fdc895c5ef, source-940993c57fc9, source-a35acfaaa819, source-28780ab68d26, source-74fa72096298]; **DPO, GRPO, and RLOO/REINFORCE++** dominate LLM post-training [source-18e81144570a, source-6375822d6219, source-06cb4410c47e, source-551decda21de]; **DreamerV3, EfficientZero V2, and TD-MPC2** are the strongest model-based methods [source-ec7577dd4f99, source-fbe2a596ed09, source-03764d186fa4]; **MAPPO, QPLEX, and HAPPO** lead multi-agent benchmarks [source-91af00305fff, source-d2c2c9151fa1, source-6eb7528c1253]; and **DiscoRL** (*Nature* 2025) points to a meta-learned future in which the "best algorithm" may itself be automatically discovered rather than hand-designed [source-ad320a9e71fa]. Crucially, methodological critiques (Henderson et al.; Agarwal et al.) show that many published "X beats Y" rankings are statistically fragile [source-e8e43c88e929, source-feb29ebb3160].

---

## 1. The taxonomy that organizes the field

RL algorithms divide along four axes [source-fe1892258c8c, source-5322db97e594]:

- **Model-free vs. model-based**: whether the agent learns a transition/reward model of the environment.
- **Value-based vs. policy-gradient**: whether the agent directly optimizes a Q-function (DQN) or the policy (PPO), or both (actor-critic: SAC, TD3, DDPG).
- **On-policy vs. off-policy**: whether past experience can be reused via replay (off-policy: DQN, SAC, TD3, DDPG) or must be discarded (on-policy: PPO, A2C).
- **Action space**: discrete (DQN, PPO) vs. continuous (DDPG, TD3, SAC; PPO also handles continuous).

These axes determine which algorithms are even candidates for a given problem.

---

## 2. The core modern algorithms: PPO, SAC, TD3, DDPG, DQN

### DQN (Mnih et al., *Nature* 2015) [source-28780ab68d26]
Value-based, off-policy, discrete actions only. Introduced experience replay + target networks to stabilize Q-learning with deep networks. First RL algorithm to reach human-level performance on Atari from raw pixels. **Weaknesses**: discrete only; Q-value overestimation (addressed by Double DQN); uniform replay is inefficient (addressed by PER).

### DDPG (Lillicrap et al., ICLR 2016) [source-85abc53c73f9]
Actor-critic, off-policy, continuous actions. Extended DQN to continuous control via a deterministic policy + replay buffer + Polyak-averaged target nets. **Weaknesses**: "notoriously challenging to use due to its extreme brittleness and hyperparameter sensitivity" [source-940993c57fc9]; documented Q-value overestimation; fails entirely on Ant-v1 and Humanoid [source-940993c57fc9, source-74fa72096298]. Largely deprecated in favor of TD3.

### PPO (Schulman et al., 2017) [source-15fdc895c5ef]
On-policy policy gradient. Clipped surrogate objective + multi-epoch minibatch SGD + GAE. **Strengths**: stable, simple to implement, handles both discrete and continuous, scales natively with parallel environments [source-74fa72096298, source-fe1892258c8c]. **Weaknesses**: sample-inefficient (discards trajectories after each update); can collapse into local optima; Engstrom et al. showed that "code-level optimizations are responsible for most of PPO's gain in cumulative reward over TRPO" — meaning PPO's reputation partly reflects engineering tricks rather than the clipped objective itself [source-834447d5cc1f].

### TD3 (Fujimoto et al., ICML 2018) [source-a35acfaaa819]
DDPG + three fixes: **clipped double Q-learning** (takes min of two critics to reduce overestimation), **delayed policy updates** (critic updated more often than actor), and **target policy smoothing** (adds noise to target actions as regularization). Continuous actions only.

### SAC (Haarnoja et al., ICML 2018) [source-940993c57fc9]
Actor-critic, off-policy, maximum-entropy RL: optimizes reward **plus** policy entropy. Stochastic squashed-Gaussian policy; inherits double-Q from TD3. "Soft actor-critic performs much more consistently, while the deterministic variant [DDPG-like] exhibits very high variability across seeds" [source-940993c57fc9]. Continuous actions only in standard form. **Weakness**: reward-scale sensitive (though SAC-v2's automatic α tuning mitigates this).

### Head-to-head on MuJoCo continuous control
Concrete numerical comparisons [source-160864885c95, source-2cb5a1f3fbf9]:

| Environment | Best score (SAC) | TD3 | PPO |
|---|---|---|---|
| HalfCheetah-v4 | **11,052** | 8,224 | 4,182 |
| Walker2d-v4 | 2,710 | **3,513** | lower |
| Hopper-v4 | 3,037 | **3,296** | lower |
| Swimmer-v4 | — | **best** | middle |

SAC reaches the performance threshold in ~115k steps vs PPO's ~950k — **an ~8× sample-efficiency advantage** for SAC on HalfCheetah [source-160864885c95]. TD3 and SAC trade wins task-to-task; neither dominates the other [source-2cb5a1f3fbf9].

---

## 3. Algorithm selection by setting

### By action space and parallelism [source-74fa72096298, source-9d9558a063a4]
- **Discrete, single process** → DQN (+ extensions like Rainbow)
- **Discrete, multi-process** → PPO or A2C
- **Continuous, single process, tight sample budget** → **SAC** (or TD3 if smoother curves matter)
- **Continuous, multi-process, fast simulator** → PPO
- **Need one algorithm for both discrete and continuous** → PPO

### By sample budget and simulator [source-d71d978e92fb, source-74fa72096298]
- **Very few episodes (<10)** on pricing-style problems: classical fitted DP beats all RL.
- **Medium (10–100 episodes)**: PPO is the best RL choice.
- **Large (>1,000 episodes)**: TD3, DDPG, SAC, and PPO all converge to ~90%+ of optimal.
- **Real-robot / slow simulator**: use off-policy (SAC, TD3) to minimize interaction cost.
- **Sparse rewards / goal-conditioned**: add Hindsight Experience Replay (HER) to SAC or TD3 [source-74fa72096298].
- **Sim-to-real robotics**: one physical quadruped study found PPO + domain randomization transferred better than SAC/TD3, even though SAC won in simulation [source-b366eac31928] — single-source, not yet replicated.

### The contested "no dominance" claim
Henderson et al. (AAAI 2018) showed that on MuJoCo, "in environments with stable dynamics (e.g. HalfCheetah) DDPG outperforms all other algorithms" while on Swimmer "TRPO significantly outperforms all other algorithms," concluding there is "often no clear winner among all benchmark environments" [source-e8e43c88e929]. Agarwal et al. (NeurIPS 2021) pushed further: "stochastic dominance is rarely observed" across Atari, Procgen, and DM Control, and "a lot of the reported improvements [on DMC] are spurious" under proper statistical analysis [source-feb29ebb3160, source-15c35aef333e]. Variance from seeds alone can produce "statistically different distributions" [source-e8e43c88e929]. **The practical implication**: "best" claims with fewer than ~10 seeds and without confidence intervals should be treated skeptically.

Within narrow settings, however, clear winners exist: SAC/TD3 reliably beat PPO on MuJoCo locomotion (2–3× in score, ~8× in sample efficiency) — this is not contested [source-160864885c95].

---

## 4. The case against the PPO/SAC "default"

The classic recommendation ("start with PPO for discrete/parallel, SAC for continuous") has eroded substantially, and the community consensus is quietly moving. Stable Baselines3's own documentation no longer endorses SAC as THE default — it now lists "SAC, TD3, CrossQ and TQC" as current SOTA and recommends DroQ "if you want an extremely sample-efficient algorithm" [source-74fa72096298]. The adversarial case against the old default rests on:

- **CrossQ** is a near-drop-in SAC upgrade that "surpass[es] the current state-of-the-art in sample efficiency while maintaining a low UTD ratio of 1" and "substantially reduces the computational cost compared to REDQ and DroQ" [source-95a95554805f].
- **REDQ** achieves "more than 7× the sample efficiency of SAC" on Ant and Humanoid [source-4a75ef697fd7].
- **DroQ** matches REDQ's sample efficiency at SAC-like compute cost [source-80a162d57efc].
- **TQC** already claimed (in 2020) to beat SAC on all continuous-control environments tested, with a 25% lead on Humanoid [source-d913490f3c14].
- **TD-MPC2** "consistently outperforms existing model-based and model-free methods" across 104 online-RL tasks including direct comparison with SAC and DreamerV3 [source-03764d186fa4].
- **DreamerV3** explicitly states it "outperforms PPO across all domains" it evaluated (>150 tasks) with a single fixed configuration [source-ec7577dd4f99].

OpenAI Spinning Up still cites PPO and SAC as close to SOTA [source-506d2fd58109] — but this guidance predates most of the above. The honest summary: **PPO and SAC remain excellent, well-tooled, mature baselines and are still reasonable starting points, but they are no longer frontier algorithms in any setting.**

---

## 5. RL for LLMs (RLHF and RLVR)

LLM post-training is now the single largest consumer of RL, and it has its own algorithm ecosystem [source-18e81144570a, source-6375822d6219, source-7146f57c06f7, source-06cb4410c47e, source-551decda21de, source-657a42b782c7].

### RLHF (preference-based alignment)
- **PPO** is the canonical RLHF method (InstructGPT, ChatGPT, Claude) and, *with proper tuning*, still wins on hard tasks like competition-level code [source-94fda41a2361, source-185cca1d6db6]. Costs: must hold **four models in memory** (policy, reference, critic, reward model) [source-657a42b782c7].
- **DPO** (Rafailov et al., NeurIPS 2023) reparameterizes RLHF into supervised classification on preference pairs — no reward model, no critic, no online sampling. "Stable, performant, and computationally lightweight" [source-18e81144570a]. Dominates offline alignment. **Weakness**: strictly-larger solution set than PPO that includes OOD-biased policies; on hard tasks, PPO still wins [source-185cca1d6db6]. Variants: IPO, KTO, SimPO [source-447b67765077], ORPO.
- **RLOO** (Ahmadian et al., ACL 2024) is a REINFORCE-with-leave-one-out-baseline method that "outperform[s] PPO by 10.3, 14.5, and 32.1" win-rate points on TL;DR and HH benchmarks, with 50–70% less VRAM and 2–3× faster training [source-06cb4410c47e]. Ahmadian et al. argue PPO's clipping is active on <5% of tokens in RLHF — most of PPO's structure is wasted in this setting [source-06cb4410c47e].
- **REBEL** (NeurIPS 2024) reduces RL to squared-loss regression on relative rewards; no value net, no clipping. Achieves 78.1% win-rate on TL;DR vs RLOO's 77.9% and PPO's 77.6% [source-657a42b782c7]. Strong theoretical guarantees.

### RLVR (verifiable rewards — math, code, reasoning)
- **GRPO** (DeepSeekMath, Feb 2024) removes the critic; estimates advantage as group-relative reward normalization. Used in DeepSeek-R1, where AIME pass@1 improved from 15.6% to 77.9% purely via GRPO-based RLVR [source-6375822d6219, source-7146f57c06f7]. Costs ~50% less than PPO.
- **REINFORCE++** (Jan 2025) fixes GRPO's theoretical bias (local normalization is provably biased, k3 KL estimator has high variance). In a controlled experiment, GRPO achieved 95% training pass@1 but **0.0% test pass@1** on AIME-25 (catastrophic overfitting), while REINFORCE++ generalized [source-551decda21de].
- **Critical 2025 finding**: a NeurIPS 2025 analysis of six major RLVR algorithms (PPO, GRPO, REINFORCE++, RLOO, ReMax, DAPO) concluded that "while [they] exhibit slight variations in both pass@1 and pass@256, these differences are not fundamental" [source-536cae03949b]. More striking: **RLVR improves pass@1 but narrows pass@256 across all six algorithms** — base models outperform RLVR-trained models at high sampling budgets, suggesting RLVR sharpens existing capabilities rather than expanding reasoning boundaries. This is contested by the DeepSeek-R1 team who argue emergent self-reflection is genuine [source-7146f57c06f7].

### The DPO vs PPO debate
AllenAI's "Unpacking DPO and PPO" argues the gap largely vanishes with matched hyperparameters and data [source-fbc915a360a7], while the ICML 2024 theoretical analysis proves DPO's solution set strictly contains PPO's (plus bad OOD solutions) and shows PPO wins empirically on challenging tasks [source-185cca1d6db6]. **Reasonable reading**: DPO for offline alignment with clean preference data; PPO (or RLOO) for online/hard tasks.

---

## 6. Model-based and meta-learned RL

### World-model methods
- **DreamerV3** (*Nature* 2025) [source-ec7577dd4f99, source-fa4c2136e78f] learns a latent world model and trains policies purely in imagined trajectories. At 100M steps on DMLab, it exceeds what IMPALA/R2D2 achieve at 1 billion steps — a >1000× data-efficiency gain. First algorithm to collect diamond in Minecraft from scratch without human data.
- **EfficientZero V2** (ICML 2024 Spotlight) [source-fbe2a596ed09] extends MuZero with sampling-based Gumbel search. Outperforms DreamerV3 on 50 of 66 tasks and by 45% on Vision Control. On Atari 100k: normalized mean 2.428 vs DreamerV3's 1.120.
- **TD-MPC2** [source-03764d186fa4] combines model-predictive control with learned value estimates; strongest direct competitor to DreamerV3 on continuous control.

### Dyna-style (MBPO)
**MBPO** (Janner et al., NeurIPS 2019) [source-3f1650148789] showed an order-of-magnitude sample-efficiency gain over SAC on MuJoCo. **But** — Barkley & Fridovich-Keil (ICML 2024) [source-35507fa4b13f] showed MBPO "struggles to achieve any policy improvements in six out of fifteen challenging DMC environments when training from scratch" — a failure that **persists with a perfect dynamics model**, implicating critic divergence and plasticity loss rather than modeling error. A related pattern affects ALM. So Dyna-style MBRL sample efficiency is benchmark-specific, not universal.

### Hybrid model-based + model-free
[source-7c9eef04d3c4] shows Unified RL combining both achieves model-based sample efficiency with model-free asymptotic performance.

### Meta-learned RL: DiscoRL (*Nature* 2025)
Oh et al. [source-ad320a9e71fa] meta-learn the RL update rule itself (not just the policy) across a population of agents in diverse environments. Reports state-of-the-art performance:
- **Atari57**: Disco57 IQM of 13.86, "outperforming all existing RL rules" including MuZero.
- **ProcGen** (zero-shot): outperformed all published methods including MuZero and PPO.
- **Crafter**: Disco57 "competitive"; Disco103 reaches human-level.

**Verification caveat**: my verify dispatch returned **INCONCL**. Key concerns: (1) no independent third-party replication of the numbers was found; (2) only **two seeds per environment** on Atari/ProcGen/DMLab (three on Crafter) — a meaningful weakness given RL's known seed sensitivity [source-883c2efa671f]; (3) cross-paper baseline protocols differ (MuZero uses planning, changing per-step compute); (4) the user-facing summary "DiscoRL is SOTA on Crafter" overstates the paper — Disco57 is only "competitive" there, with stronger Crafter claims applying to the larger Disco103 variant [source-ad320a9e71fa]. The compute cost is also substantial: Disco57 required 1,024 TPUv3 cores for 64 hours. **Interpretation**: DiscoRL is a genuinely exciting new paradigm with plausible but not-yet-independently-replicated claims; treat the specific numbers as provisional.

Goldie et al. (RLC 2025) [source-a0e6a7c16303, source-958f6b142289] situate DiscoRL in the broader meta-learned-algorithms space and note that generalization to out-of-distribution environments "remains a central challenge."

---

## 7. Multi-agent RL

Under the **centralized training with decentralized execution (CTDE)** paradigm [source-d2c2c9151fa1], three algorithm families dominate [source-bc1b241762bf, source-6eb7528c1253, source-91af00305fff]:

**Value decomposition** (factorize joint Q into per-agent Qs under the Individual-Global-Max principle):
- **VDN** (linear sum) → baseline.
- **QMIX** (nonlinear monotonic mixing) → with implementation tricks, near-100% win rate on most SMAC maps [source-390402565fd2]. Fails on non-monotonic / heterogeneous tasks (39.1% on 27m_vs_30m) [source-3bcdb54c4355].
- **QPLEX** (advantage-based IGM via duplex dueling) → spans the full IGM class; 98% on MMM2 vs QMIX's 83% [source-3bcdb54c4355]; among the most consistent algorithms across diverse benchmarks [source-bc1b241762bf].

**Centralized-critic actor-critic**:
- **MADDPG** (2017): historically important, now largely superseded [source-d2c2c9151fa1].
- **COMA**: introduced counterfactual baselines for credit assignment; now "has one of the lowest performances overall" [source-bc1b241762bf].
- **MAPPO** (NeurIPS 2022) [source-91af00305fff]: PPO with a centralized value function. "Surprisingly strong performance in four popular multi-agent testbeds... with minimal hyperparameter tuning." Beats QMIX by a wide margin on hard SMAC scenarios (93.8% vs 39.1% on 27m_vs_30m) [source-3bcdb54c4355]. Among the most consistent across the AAMAS 2025 benchmark suite [source-bc1b241762bf].

**Heterogeneous-agent CTDE**:
- **HAPPO / HATRPO** (JMLR 2024) [source-6eb7528c1253]: sequential per-agent updates with **provable monotonic improvement and Nash equilibrium convergence**. Handles heterogeneous agents without parameter sharing. New SOTA on MPE, MAMuJoCo, GRF, and Bi-DexterousHands.

**2024-2025 consensus**: MAPPO, QPLEX, and HAPPO are the strongest general-purpose MARL algorithms. The AAMAS 2025 benchmark paper identifies **MAPPO, MAA2C, QPLEX, and CDS** as "the most consistent performance across all fully cooperative benchmarks" [source-bc1b241762bf]. Importantly: "many algorithms, hailed as state-of-the-art on SMAC and GRF, may underperform standard MARL baselines" on broader benchmarks [source-bc1b241762bf] — the same "no universal dominance" pattern as single-agent RL.

---

## 8. Methodological caveats that affect every claim above

- **Random seed variance**: Henderson et al. showed that 5 seeds of TRPO on HalfCheetah can produce statistically different distributions (t=9.09, p=0.0016) from another set of 5 seeds of the same algorithm [source-e8e43c88e929]. Most published comparisons use too few seeds.
- **Implementation details dominate**: "Small implementation details can have a substantial effect on performance — often greater than the difference between algorithms" [source-cd8fe34de101]. PPO's advantage over TRPO comes largely from code-level optimizations, not the clipped objective [source-834447d5cc1f].
- **Hyperparameter tuning confounds comparisons**: Islam et al. warn suboptimal hyperparameters make baseline comparisons inaccurate [source-177a0eb399a9]; tuning protocols often differ between challenger and baselines.
- **Benchmark protocol matters**: ALE evaluation choices (sticky actions, random starts) change apparent Atari rankings; Crafter's geometric-mean achievement score captures breadth, not raw return [source-a2a6e888db59]; ProcGen results depend on train/test level protocols [source-da12c103c894].

**Practical implication**: for any high-stakes choice, replicate the head-to-head yourself with ≥10 seeds and paper-matched hyperparameters before committing.

---

## 9. Condensed decision guide

| Your setting | Recommended starting algorithm |
|---|---|
| Discrete actions, single process (Atari-like) | DQN + Rainbow extensions |
| Discrete actions, multi-process | PPO |
| Continuous control, fast sim, stability priority | PPO (parallelized) |
| Continuous control, tight sample budget | SAC (or CrossQ / DroQ / TD-MPC2 for frontier) |
| Continuous control, need smooth curves | TD3 |
| Real-robot / slow simulator | SAC + HER (off-policy) |
| Sim-to-real robotics | PPO + domain randomization (tentative, single-study) |
| Pixel inputs, very low sample budget | EfficientZero V2 or DreamerV3 |
| Cross-domain generalist | DreamerV3 |
| LLM alignment from preference pairs (offline) | DPO or SimPO |
| LLM alignment, online, compute-constrained | RLOO or REINFORCE++ |
| LLM alignment, maximum quality on hard tasks | Tuned PPO |
| LLM reasoning with verifiable rewards | GRPO (or REINFORCE++ if overfitting observed) |
| Cooperative multi-agent (homogeneous) | MAPPO |
| Cooperative multi-agent (heterogeneous) | HAPPO |
| Offline MARL | QPLEX |
| Tabular, small state space | Q-learning or dynamic programming |

---

## 10. What "best" even means

The single most defensible answer to "what is the best RL algorithm" is meta-level: **the question is malformed unless you specify the setting**. Within any given well-specified setting (action space, sample budget, reward structure, simulator availability, compute budget, seed count for evaluation), a defensible recommendation can be made — and this report has tried to provide those setting-conditioned recommendations. Across settings, convergence on a single algorithm is not supported by the evidence, and methodological work (Henderson, Agarwal, Engstrom) suggests the field has historically over-claimed dominance. The most honest view is that RL is a toolbox; the craft is matching tool to problem, and the frontier (CrossQ, TD-MPC2, DreamerV3, EfficientZero V2, DiscoRL, REINFORCE++, REBEL) is moving fast enough that guidance from even two years ago is partially outdated.

## Limitations

- No unified modern benchmark compares SAC/PPO against CrossQ, TQC, REDQ, DroQ, DreamerV3, TD-MPC2, and EfficientZero V2 under a single evaluation protocol — current evidence is distributed across separate papers with varying seeds and compute budgets.
- No independent third-party replication of DiscoRL (Nature 2025) benchmark wins was found; the verify dispatch returned INCONCL on the strongest interpretation of its claims.
- Physical-robot (non-sim) head-to-head comparisons of PPO/SAC/TD3 are very sparse; the sim-to-real reversal rests on a single quadruped study.
- Frontier-scale RLHF/RLVR algorithm comparisons are not public: OpenAI o1/o3 and Gemini 2.5 internal RL training details are unknown, so which algorithm family 'wins' at the true frontier cannot be verified from public evidence.
- Offline RL (CQL, IQL, TD3+BC) and hierarchical RL were not investigated despite being noted gaps — readers working in data-constrained or long-horizon settings should consult other sources.
- SMACv2 (the harder randomized version) has no published cross-algorithm table comparable to what exists for original SMAC; MAPPO/HAPPO/QMIX ordering on SMACv2 is inferred rather than directly measured.
- Scalability of MARL to very large agent populations (100+) is not characterized in the surveyed literature.
- Theoretical convergence and regret guarantees were not covered — the report is almost entirely empirical.

## Sources

- **[source-03c71f80330a]** [Reddit: What is the best reinforcement learning algorithm in 2024?](https://www.reddit.com/r/reinforcementlearning/comments/1dgdtp2/what_is_the_best_reinforcement_learning_algorithm/) - not-tiered
  - Community discussion covering Q-learning, SARSA, DDPG, A2C, PPO, DQN, and TRPO. Practical perspectives on algorithm selection.
- **[source-739f717afa4e]** [Discovering state-of-the-art reinforcement learning algorithms | Nature](https://www.nature.com/articles/s41586-025-09761-x) - not-tiered
  - An autonomous method discovers RL rules from cumulative experiences of a population of agents across many complex environments; the discovered rule achieves state-of-the-art performance on Atari and other challenging benchmarks.
- **[source-bb7b30bb0887]** [Reinforcement Learning Algorithms: An Overview and Classification (AlMahamid)](https://arxiv.org/pdf/2209.14940) - not-tiered
  - Classifies RL algorithms, provides an overview of main principles, and covers the taxonomy of model-free and model-based approaches.
- **[source-f89f198d8624]** [RL — Reinforcement Learning Algorithms Comparison (Jonathan Hui, Medium)](https://jonathan-hui.medium.com/rl-reinforcement-learning-algorithms-comparison-76df90f180cf) - not-tiered
  - Compares Q-learning, DQN, policy gradient, actor-critic methods; discusses sample efficiency, stability, exploration, and replay buffers.
- **[source-2bd2e25cca49]** [A Survey of Benchmarks for Reinforcement Learning Algorithms (ResearchGate)](https://www.researchgate.net/publication/348164202_A_survey_of_benchmarks_for_reinforcement_learning_algorithms) - not-tiered
  - Surveys benchmarking frameworks for RL; discusses exploration-exploitation, off-policy vs on-policy scaling, delayed/sparse rewards, and state/action space challenges.
- **[source-8a5b6bc0cdbb]** [Benchmarking Reinforcement Learning via Stochastic Converse Optimality (arXiv 2026)](https://arxiv.org/abs/2603.17631) - not-tiered
  - A reproducible framework for RL benchmarking using environments with known optimal policies; assesses standard methods against ground-truth optima.
- **[source-b603583f36c4]** [Benchmarking Deep Reinforcement Learning Algorithms (Helfenstein, 2021)](https://www.semanticscholar.org/paper/e62adbad60d42968af76fad87fcb81ca2d8e7dae) - not-tiered
  - Benchmarks deep RL algorithms across multiple tasks and environments.
- **[source-0371ed215dab]** [Evaluating and Selecting Deep RL Models: PPO, DDPG, and SAC (Liu et al., 2024)](https://doi.org/10.1145/3640824.3640871) - not-tiered
  - Introduces a framework to systematically compare PPO, DDPG, and SAC for dynamic pricing tasks; addresses lack of standardized evaluation.
- **[source-b366eac31928]** [Sim-to-Real: Performance Comparison of PPO, TD3, and SAC for Quadruped Walking (Mock & Muknahallipatna, 2024)](https://doi.org/10.4236/jilsa.2024.162003) - tier 2 - peer-reviewed
  - Compares PPO, TD3, and SAC RL algorithms for quadruped robot walking gait generation in sim-to-real transfer.
- **[source-428c9c06b36f]** [Benchmarking Tabular Reinforcement Learning Algorithms (Towards Data Science)](https://towardsdatascience.com/benchmarking-tabular-reinforcement-learning-algorithms/) - not-tiered
  - Benchmarks tabular RL algorithms; finds on-policy Monte Carlo outperforms Q-learning, Dyna-Q, SARSA-n in model-free setting.
- **[source-03a0b29a97cd]** [Common Tools in Reinforcement Learning for Benchmarking (Hemant Kumawat, 2024)](http://www.hemantkumawat.com/blog/2024/benchmark/) - not-tiered
  - Reviews benchmark environments including Atari for discrete action spaces; discusses high-dimensional observation space challenges for deep RL.
- **[source-9d159feb59b2]** [verl/HybridFlow: Flexible and Efficient RL Post-Training Framework (GitHub)](https://github.com/volcengine/verl) - not-tiered
  - RL post-training framework supporting PPO, GRPO, GSPO, ReMax, REINFORCE++, RLOO, PRIME, DAPO, DrGRPO for LLM fine-tuning; accepted EuroSys 2025.
- **[source-15fdc895c5ef]** [Proximal Policy Optimization Algorithms (Schulman et al., 2017)](https://arxiv.org/html/1707.06347) - tier 2
  - Proposes PPO, a family of policy gradient methods using a surrogate objective with multiple minibatch update epochs; simpler and more general than TRPO with comparable performance.
- **[source-8a5d8282a5cc]** [Soft Actor-Critic: Algorithms and Applications (Haarnoja et al., 2018)](https://arxiv.org/html/1812.05905) - not-tiered
  - SAC is an off-policy actor-critic algorithm based on maximum entropy RL, addressing high sample complexity and hyperparameter brittleness; 3000+ citations.
- **[source-623d9c31842b]** [OpenAI Spinning Up: Kinds of RL Algorithms](https://spinningup.openai.com/en/latest/spinningup/rl_intro2.html) - not-tiered
  - Educational taxonomy of RL algorithms: model-free vs model-based, policy gradient vs value-based, on-policy vs off-policy. Notes model-free methods are more popular and well-tested as of writing.
- **[source-7c9eef04d3c4]** [Unifying Model-Based and Model-Free RL (OpenReview)](https://openreview.net/forum?id=p5SurcLh24) - not-tiered
  - Demonstrates Unified RL combining model-based and model-free strengths, achieving comparable data efficiency to model-based and asymptotic performance of model-free; outperforms SOTA baselines.
- **[source-c553a80f3e72]** [RLHF 101: A Technical Tutorial on RLHF (ML@CMU Blog, 2025)](https://blog.ml.cmu.edu/2025/06/01/rlhf-101-a-technical-tutorial-on-reinforcement-learning-from-human-feedback/) - not-tiered
  - Technical tutorial on RLHF covering REBEL, Llama-3 fine-tuning, and state-of-the-art approaches for aligning LLMs using RL.
- **[source-50376406999e]** [Reinforcement Learning from Human Feedback (RLHF Book PDF)](https://rlhfbook.com/book.pdf) - not-tiered
  - Comprehensive book on RLHF, covering post-training compute, DeepSeek R1, RLVR, and RLHF with fewer moving parts via pairwise preference data.
- **[source-e96a3dc16dd1]** [RLHF Deciphered: Critical Analysis of RLHF for LLMs (ACM Computing Surveys)](https://dl.acm.org/doi/10.1145/3743127) - not-tiered
  - Critical ACM survey examining RLHF adoption from robot locomotion and Atari games through LLM fine-tuning; covers challenges and current state.
- **[source-b8db2b828382]** [Illustrating RLHF (Hugging Face Blog)](https://huggingface.co/blog/rlhf) - not-tiered
  - Accessible overview of RLHF for LLMs; discusses PPO, A2C, TRPO, NLPO implementations via TRLX and RL4LMs frameworks.
- **[source-2d47b71e5ced]** [LLM Training: RLHF and Its Alternatives (Ahead of AI / Sebastian Raschka)](https://magazine.sebastianraschka.com/p/llm-training-rlhf-and-its-alternatives) - not-tiered
  - Compares PPO-based RLHF with alternatives like ReST, RLAIF, and DPO for LLM training; highlights tradeoffs in online vs offline RL for alignment.
- **[source-9f91837e80c8]** [Ericsson Blog: Model-Based vs Model-Free RL Comparison](https://www.ericsson.com/en/blog/2023/12/comparing-model-based-and-model-free-reinforcement-learning-characteristics-and-applicability) - not-tiered
  - Discusses when to apply model-free vs model-based RL; explains transition and reward function roles; industry applicability perspective.
- **[source-a35acfaaa819]** [Addressing Function Approximation Error in Actor-Critic Methods – TD3 (Fujimoto et al., 2018)](https://arxiv.org/abs/1802.09477) - tier 1 - peer-reviewed
  - Introduces TD3 (Twin Delayed DDPG), addressing Q-value overestimation in actor-critic methods via clipped double Q-learning, delayed policy updates, and target policy smoothing.
- **[source-015680e7b15a]** [Twin Delayed DDPG (TD3) – OpenAI Spinning Up](https://spinningup.openai.com/en/latest/algorithms/td3.html) - not-tiered
  - OpenAI Spinning Up documentation page on TD3: explains clipped double Q-learning, delayed updates, and target policy smoothing as key improvements over DDPG.
- **[source-c5281da3d121]** [Rethinking Exploration in Reinforcement Learning (NeurIPS 2024)](https://proceedings.neurips.cc/paper_files/paper/2024/file/6a39cf3b666f8bdb2223f253981f3869-Paper-Conference.pdf) - not-tiered
  - NeurIPS 2024 paper on exploration bonuses for RL; benchmarks on Robosuite, Atari, MiniGrid, and Habitat environments.
- **[source-3b032752ca04]** [PPO with Diffusion Action Prior (PPO-DAP) – Sample Efficiency via Diffusion (arXiv 2024)](https://ui.adsabs.harvard.edu/abs/2024arXiv240901427G/abstract) - not-tiered
  - PPO-DAP: on-policy framework combining PPO with diffusion action prior to improve exploration quality and learning efficiency without modifying PPO objective.
- **[source-d0eaad1c0f96]** [Reinforcement Learning Journal (RLJ) 2024 Issue](https://rlj.cs.umass.edu/2024/2024issue.html) - not-tiered
  - Reinforcement Learning Journal 2024 issue; covers efficient exploration, RLHF without reward inference, and model-free algorithms.
- **[source-559ebc782c9a]** [Multi-Agent Reinforcement Learning: Foundations and Modern Approaches (MIT Press, 2024)](https://www.marl-book.com/) - not-tiered
  - MIT Press book (2024) on MARL: foundations and modern approaches, with Python codebase implementing several MARL algorithms.
- **[source-cc308ef58f39]** [Multi-agent Reinforcement Learning: A Comprehensive Survey (arXiv 2023)](https://arxiv.org/html/2312.10256v2) - not-tiered
  - Comprehensive survey of MARL covering value-based, policy-based, and actor-critic approaches, noting policy-based methods are less common due to sample inefficiency.
- **[source-ab1a64acdad7]** [How to Choose a Reinforcement-Learning Algorithm (arXiv 2024)](https://arxiv.org/abs/2407.20917) - not-tiered
  - Provides structured overview and guidelines for choosing RL algorithms and action-distribution families; streamlines the algorithm selection process.
- **[source-cab2a7f52ba7]** [How to Choose a Reinforcement Learning Algorithm (RL Path Guide)](https://www.reinforcementlearningpath.com/choosing-rl-algorithm) - not-tiered
  - Practical guide for algorithm selection: recommends SAC or TD3 when simulators unavailable; PPO and SAC for stability; covers DDPG, PPO, SAC, TD3 tradeoffs.
- **[source-74fa72096298]** [Reinforcement Learning Tips and Tricks – Stable Baselines3 Docs](https://stable-baselines3.readthedocs.io/en/master/guide/rl_tips.html) - tier 3
  - Stable Baselines3 RL tips: covers which algorithm to choose, how to evaluate, and tricks for custom environments and algorithm implementation.
- **[source-266df256485a]** [RL from Single-Agent to Multi-Agent Systems: Survey (Springer AI Review, 2025)](https://link.springer.com/article/10.1007/s10462-025-11439-9) - not-tiered
  - Survey of MARL with applications including robotics; covers transition from single-agent to multi-agent RL and industrial applications.
- **[source-ad320a9e71fa]** [Discovering state-of-the-art reinforcement learning algorithms – PMC Full Text](https://pmc.ncbi.nlm.nih.gov/articles/PMC12695655/) - tier 1 - peer-reviewed
  - Full open-access text of the Nature 2025 DiscoRL paper. The RL rule is represented by a meta-network that determines the targets towards which the agent should move its predictions and policy, allowing discovery of useful predictions without pre-defined semantics.
- **[source-ecb399a680c7]** [DiscoRL GitHub – Google DeepMind code for "Discovering State-of-the-art Reinforcement Learning Algorithms"](https://github.com/google-deepmind/disco_rl) - not-tiered
  - Accompanying code for the Nature 2025 DiscoRL publication by Oh, Farquhar, Kemaev, Calian, Hessel, Zintgraf, Singh, van Hasselt, Silver. DOI: 10.1038/s41586-025-09761-x
- **[source-afec935ad55a]** [DiscoRL Project Page – Discovering State-of-the-art Reinforcement Learning Algorithms (DeepMind)](https://google-deepmind.github.io/disco_rl/) - not-tiered
  - Official project page. The agent makes additional predictions without pre-defined semantics to open up the possibility to discover entirely new prediction semantics.
- **[source-0e7ca2b6c2ef]** [Discovering state-of-the-art reinforcement learning algorithms – Semantic Scholar](https://www.semanticscholar.org/paper/Discovering-state-of-the-art-reinforcement-learning-Oh-Farquhar/443ef37ec1cbe8f5e4a43b1908cb2e4f60a99c59) - not-tiered
  - Semantic Scholar record for DiscoRL (Oh et al., Nature 2025). It is possible for machines to discover a state-of-the-art RL rule that outperforms manually designed rules.
- **[source-9d9558a063a4]** [RL Algorithms Table — Stable Baselines3 Docs](https://stable-baselines3.readthedocs.io/en/master/guide/algos.html) - not-tiered
  - Table displaying RL algorithms implemented in SB3 with characteristics: support for discrete/continuous actions, multiprocessing, and action space compatibility per algorithm.
- **[source-406c4080f34b]** [DDPG — Stable Baselines3 Documentation](https://stable-baselines3.readthedocs.io/en/master/modules/ddpg.html) - not-tiered
  - SB3 DDPG module documentation covering hyperparameters, action noise, and notes that TD3 hyperparameters from the gSDE paper were used for DDPG.
- **[source-cd8fe34de101]** [Stable-Baselines3: Reliable Reinforcement Learning Implementations (JMLR 2021)](https://www.jmlr.org/papers/volume22/20-1364/20-1364.pdf) - tier 1 - peer-reviewed
  - JMLR paper introducing Stable-Baselines3; covers A2C, PPO, DDPG, SAC, TD3, HER implementations and their experimental baseline use.
- **[source-506d2fd58109]** [Algorithms Overview — OpenAI Spinning Up Documentation](https://spinningup.openai.com/en/latest/user/algorithms.html) - tier 3
  - Core deep RL algorithms in this package reflect useful progressions of ideas from the recent history of the field, culminating in PPO and SAC as close to state of the art on reliability and sample efficiency.
- **[source-fe1892258c8c]** [Proximal Policy Optimization (PPO) — OpenAI Spinning Up Documentation](https://spinningup.openai.com/en/latest/algorithms/ppo.html) - tier 3
  - PPO is an on-policy algorithm using a clipped surrogate objective to constrain policy updates. Hyperparameter clip_ratio roughly controls how far the new policy is allowed to go from the old.
- **[source-5322db97e594]** [Soft Actor-Critic (SAC) — OpenAI Spinning Up Documentation](https://spinningup.openai.com/en/latest/algorithms/sac.html) - tier 3
  - SAC uses minimum of two Q approximators, stochastic policies, and an entropy term in the policy objective, compared to TD3 and DDPG. Off-policy maximum entropy RL algorithm.
- **[source-7a25059ff1b2]** [Deep Deterministic Policy Gradient (DDPG) — OpenAI Spinning Up Documentation](https://spinningup.openai.com/en/latest/algorithms/ddpg.html) - not-tiered
  - DDPG concurrently learns a Q-function and a policy using off-policy data and the Bellman equation. Closely connected to Q-learning, motivated by that connection.
- **[source-4f57ef2245a6]** [Benchmarks for Spinning Up Implementations — OpenAI Spinning Up Documentation](https://spinningup.openai.com/en/latest/spinningup/bench.html) - not-tiered
  - Benchmarks for Spinning Up implementations of DDPG, TD3, SAC roughly at-parity with best reported results. On-policy algorithms use 4000 steps per batch update; off-policy use minibatches of size 100.
- **[source-a647ae7faa5d]** [OpenAI Spinning Up — Full Documentation PDF](https://spinningup.openai.com/_/downloads/en/latest/pdf/) - not-tiered
  - Full Spinning Up documentation as PDF, covering VPG, TRPO, PPO, DDPG, TD3, SAC implementations where DDPG, TD3, and SAC all follow a unified framework.
- **[source-9bc412c7b5c1]** [TD3 — Stable Baselines3 Documentation](https://stable-baselines3.readthedocs.io/en/master/modules/td3.html) - not-tiered
  - TD3 is a direct successor of DDPG and improves it using three major tricks: clipped double Q-Learning, delayed policy update and target policy smoothing.
- **[source-08fe27fa674e]** [SAC — Stable Baselines3 Documentation](https://stable-baselines3.readthedocs.io/en/master/modules/sac.html) - not-tiered
  - SAC module documentation in Stable Baselines3; off-policy actor-critic restricted to continuous actions with automatic entropy tuning.
- **[source-9041af6df100]** [DQN — Stable Baselines3 Documentation](https://stable-baselines3.readthedocs.io/en/master/modules/dqn.html) - not-tiered
  - DQN module documentation in Stable Baselines3; supports only discrete actions, uses replay buffer for sample efficiency.
- **[source-a85437666097]** [PPO — Stable Baselines3 Documentation](https://stable-baselines3.readthedocs.io/en/master/modules/ppo.html) - not-tiered
  - PPO module documentation in Stable Baselines3; on-policy algorithm supporting both discrete and continuous actions with parallel environments.
- **[source-8e80251b479c]** [PPO vs SAC vs TD3: Choosing the Right Algorithm (KindaTechnical)](https://kindatechnical.com/reinforcement-learning/ppo-vs-sac-vs-td3-choosing-the-right-algorithm.html) - not-tiered
  - Compares PPO, SAC, and TD3 for algorithm selection; off-policy algorithms (SAC, TD3) reuse transitions for sample efficiency; PPO scales with parallel environments and suits constrained settings.
- **[source-458af8a8a959]** [Vanilla Policy Gradient (VPG) — OpenAI Spinning Up Documentation](https://spinningup.openai.com/en/latest/algorithms/vpg.html) - not-tiered
  - VPG is the simplest on-policy policy gradient algorithm. Documents PyTorch and TensorFlow implementations with nearly identical function calls and docstrings.
- **[source-4d1ebc69be7f]** [Trust Region Policy Optimization (TRPO) — OpenAI Spinning Up Documentation](https://spinningup.openai.com/en/latest/algorithms/trpo.html) - not-tiered
  - TRPO uses KL constraint and natural policy gradient with second-order methods to constrain policy updates. Spinning Up only has TensorFlow implementation.
- **[source-e18b072ff809]** [Part 3: Intro to Policy Optimization — OpenAI Spinning Up Documentation](https://spinningup.openai.com/en/latest/spinningup/rl_intro3.html) - not-tiered
  - Covers policy gradient foundations including value function learning via MSE. Used in VPG, TRPO, PPO, and A2C implementations.
- **[source-c345c0bf4298]** [PPO PyTorch Source Module — OpenAI Spinning Up (Hyperparameters)](https://spinningup.openai.com/en/latest/_modules/spinup/algos/pytorch/ppo/ppo.html) - not-tiered
  - PPO PyTorch source module with full docstring: steps_per_epoch, epochs, gamma, clip_ratio, pi_lr, vf_lr, train_pi_iters, train_v_iters, lam, max_ep_len, target_kl hyperparameters.
- **[source-8dd519b32726]** [SAC PyTorch Source Module — OpenAI Spinning Up (Hyperparameters)](https://spinningup.openai.com/en/latest/_modules/spinup/algos/pytorch/sac/sac.html) - not-tiered
  - SAC PyTorch source module with detailed hyperparameters: ac_kwargs, seed, steps_per_epoch, epochs, replay_size, gamma, polyak, lr, alpha, batch_size, start_steps, update_after, update_every, num_test_episodes, max_ep_len, save_freq.
- **[source-c3f63d0a3302]** [DDPG Algorithm RST Source — OpenAI Spinning Up GitHub](https://github.com/openai/spinningup/blob/master/docs/algorithms/ddpg.rst) - not-tiered
  - DDPG source rst doc: Q-learning algorithms for function approximators, such as DQN and DDPG, are largely based on minimizing MSBE loss function. Detailed implementation notes.
- **[source-ad29f484c21d]** [EfficientZero: Mastering Atari Games with Limited Data (Ye et al., NeurIPS 2021)](https://arxiv.org/abs/2111.00210) - not-tiered
  - Sample efficient model-based visual RL built on MuZero, achieving 194.3% mean human performance and 109.0% median on Atari 100k benchmark with limited data.
- **[source-4ec14a4063eb]** [SMACv2: An Improved Benchmark for Cooperative Multi-Agent Reinforcement Learning](https://arxiv.org/abs/2212.07489) - not-tiered
  - SMACv2 addresses deficiencies of SMAC by introducing procedural generation. Evaluates state-of-the-art MARL algorithms and shows significant new challenges not present in original SMAC benchmark.
- **[source-5a448536e043]** [The StarCraft Multi-Agent Challenge (SMAC)](https://arxiv.org/abs/1902.04043) - not-tiered
  - Seminal SMAC paper: StarCraft II-based MARL benchmark for micromanagement with partial observability, diverse maps, and best-practice benchmarking guidelines. Gold standard for MARL evaluation.
- **[source-8027c129b696]** [HLSMAC: A New StarCraft Multi-Agent Challenge for High-Level Strategic Decision-Making](https://arxiv.org/abs/2509.12927) - not-tiered
  - New SMAC variant evaluating 21 state-of-the-art MARL algorithms and LLM-PySC2 framework. Proposes novel metrics beyond win rate for high-level strategic decision-making.
- **[source-3bcdb54c4355]** [Multi-Agent Reinforcement Learning in StarCraft: Algorithmic Advances and Challenges (ITM 2025)](https://www.itm-conferences.org/articles/itmconf/pdf/2025/09/itmconf_cseit2025_01013.pdf) - tier 3 - peer-reviewed
  - Survey of MARL algorithms on SMAC benchmark; reviews QMIX, MAPPO and other methods on StarCraft partial observability tasks. Discusses algorithmic advances and current limitations.
- **[source-d6b1ecfdabf4]** [Human-level control through deep reinforcement learning (Mnih et al., 2015, Nature)](https://www.nature.com/articles/nature14236) - not-tiered
  - Original DQN paper by Mnih et al., introducing deep Q-networks with experience replay and target network for human-level Atari game playing.
- **[source-f3aed8cc3822]** [Semantic Scholar: Human-level control through deep reinforcement learning (Mnih et al., 2015)](https://www.semanticscholar.org/paper/Human-level-control-through-deep-reinforcement-Mnih-Kavukcuoglu/340f48901f72278f6bf78a04ee5b01df208cc508) - not-tiered
  - Semantic Scholar entry for the DQN Nature paper with citation data and references.
- **[source-28780ab68d26]** [DQN Nature Paper PDF – Human-level control through deep reinforcement learning (Mnih et al., 2015)](https://web.stanford.edu/class/psych209/Readings/MnihEtAlHassibis15NatureControlDeepRL.pdf) - tier 1 - peer-reviewed
  - PDF of the original DQN Nature paper, covering experience replay, target network, epsilon-greedy, and Atari benchmark results.
- **[source-c0bd96faab58]** [Human-level control through deep reinforcement learning – Neural Aspect Explainer](https://www.neuralaspect.com/posts/breakout-2015) - not-tiered
  - Explainer post on DQN 2015 Nature paper with diagram of experience replay algorithm.
- **[source-6c95cb8fe4b3]** [Advances and challenges in learning from experience replay (Springer AI Review, 2024)](https://link.springer.com/article/10.1007/s10462-024-11062-0) - not-tiered
  - Comprehensive Springer review covering experience replay mechanisms, variants, and challenges in deep RL including DQN's epsilon-greedy and off-policy learning.
- **[source-1910a6535ed6]** [An Introduction to Centralized Training for Decentralized Execution in Cooperative Multi-Agent Reinforcement Learning](https://arxiv.org/abs/2409.03052) - not-tiered
  - Introduces the CTDE paradigm, covering value function factorization (VDN, QMIX) and centralized critic methods (MADDPG, COMA, MAPPO) in cooperative MARL.
- **[source-f40ddf65098a]** [Benchmarking Multi-Agent Deep Reinforcement Learning Algorithms in Cooperative Tasks](https://arxiv.org/abs/2006.07869) - not-tiered
  - Benchmarks CTDE algorithms (MADDPG, COMA, VDN, QMIX, MAPPO) across cooperative tasks; finds significant performance variation with MAPPO and MAA2C outperforming others.
- **[source-d814f6bb5fe3]** [A First Introduction to Cooperative Multi-Agent Reinforcement Learning (Matignon et al.)](https://www.ccs.neu.edu/home/camato/publications/IntroMARL.pdf) - not-tiered
  - Overview of CTDE paradigm with two main classes: value function factorization (VDN, QMIX, QPLEX) and centralized critic actor-critic methods (MADDPG, COMA, MAPPO).
- **[source-6375822d6219]** [DeepSeekMath: Pushing the Limits of Mathematical Reasoning in Open Language Models](https://arxiv.org/abs/2402.03300) - tier 2
  - Introduces Group Relative Policy Optimization (GRPO), a variant of PPO that enhances mathematical reasoning abilities while concurrently optimizing memory usage of PPO. Original paper proposing GRPO.
- **[source-7146f57c06f7]** [DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning](https://arxiv.org/abs/2501.12948) - tier 2
  - Uses GRPO as the RL algorithm to train DeepSeek-R1-Zero and DeepSeek-R1. Key paper applying GRPO to RLVR reasoning tasks.
- **[source-bdb12e608511]** [Group Relative Policy Optimization (GRPO) – Cameron Wolfe Deep Learning Focus](https://cameronrwolfe.substack.com/p/grpo) - not-tiered
  - In-depth explainer of GRPO algorithm covering DeepSeekMath and DeepSeek-R1. Reviews the algorithm and practical applications.
- **[source-4f7be5cc3c7e]** [Group Relative Policy Optimization (GRPO) Illustrated Breakdown](https://epichka.com/blog/2025/grpo/) - not-tiered
  - Instead of using a value network, GRPO estimates baseline advantages by normalizing a group (batch) of rewards obtained from sampling multiple different outputs from the reference policy produced in response to the same question as input.
- **[source-a8ea0cf06b74]** [The Math Behind DeepSeek: A Deep Dive into Group Relative Policy Optimization (GRPO)](https://medium.com/@sahin.samia/the-math-behind-deepseek-a-deep-dive-into-group-relative-policy-optimization-grpo-8a75007491ba) - not-tiered
  - Deep dive into the mathematics behind GRPO, the core RL algorithm driving DeepSeek's reasoning capabilities. Covers the math of advantage estimation and policy update.
- **[source-07eaf6ee9783]** [GRPO - Group Relative Policy Optimization: How DeepSeek Trains Reasoning Models](https://chessman7.substack.com/p/grpo-group-relative-policy-optimization) - not-tiered
  - GRPO is an RL algorithm introduced by DeepSeek researchers to efficiently train large language models for reasoning tasks. Builds upon PPO.
- **[source-2cb5a1f3fbf9]** [An Evaluation of DDPG, TD3, SAC, and PPO for Controlling Continuous Systems (Atlantis Press, DAI-23)](https://www.atlantis-press.com/proceedings/dai-23/125998066) - tier 3 - peer-reviewed
  - Evaluates DDPG, TD3, SAC, and PPO on four MuJoCo environments (Ant, Hopper, HalfCheetah, Swimmer). Concludes TD3 or SAC performs best in most cases; DDPG underperforms; PPO's performance is debatable.
- **[source-e911e2575674]** [Sim-to-Real: Performance Comparison of PPO, TD3, and SAC for Quadruped Walking Gait Generation (Mock & Muknahallipatna, 2024)](https://www.scirp.org/journal/paperinformation?paperid=131938) - not-tiered
  - Compares PPO, TD3, and SAC for quadruped walking gait in sim-to-real transfer; SAC showed best performance for generating walking gait in certain sensor configurations.
- **[source-2adcd2ca615a]** [RL Showdown: PPO vs SAC vs TD3 on CarRacing-v3 (Medium, 2024)](https://medium.com/@uralaltan10/reinforcement-learning-showdown-ppo-vs-sac-vs-td3-on-carracing-v3-89864fb9975e) - not-tiered
  - Benchmarks PPO, SAC, and TD3 on CarRacing-v3; TD3 trails slightly with more variance; PPO is most consistent with lowest std dev but lower peak performance.
- **[source-02ee55c58781]** [DeepMind's Return in Nature: AI Agent Develops Most Powerful RL Algorithm (36Kr English)](https://eu.36kr.com/en/p/3527315416767366) - not-tiered
  - 36Kr English article. The meta-gradient combines the agent's update process with optimization of the standard RL goal via backpropagation and A2C, evaluated with a dedicated meta-learning value function. IQM used as performance indicator.
- **[source-fbe2a596ed09]** [EfficientZero V2: Mastering Discrete and Continuous Control with Limited Data](https://arxiv.org/abs/2403.00564) - tier 1 - peer-reviewed
  - Extension of EfficientZero to both discrete (Atari 100k) and continuous control (proprioceptive and visual) with limited data; builds on Gumbel MuZero search.
- **[source-f460084bd6ae]** [UniZero: Generalized and Efficient Planning with Scalable Latent World Models](https://arxiv.org/abs/2406.10667) - not-tiered
  - UniZero extends MuZero-family planning with scalable latent world models; references EfficientZero, GumbelMuZero, LightZero in context of Atari sample efficiency.
- **[source-0f0db4f226b4]** [DART: Learning to Play Atari in a World of Tokens (Discrete Tokens, model-based RL)](https://pranaval.github.io/DART/) - not-tiered
  - DART achieves median HNS of 0.790 on Atari 100k without look-ahead search, using discrete token representations for model-based RL.
- **[source-f90980186d30]** [The Impact of Model Learning Losses on the Sample Efficiency of MuZero in Atari (TU Delft)](https://repository.tudelft.nl/file/File_13f431b8-9a18-4bdd-a7d5-e52cd2e1201d?preview=1) - not-tiered
  - Evaluates how different model learning losses affect MuZero's efficiency in low data scenarios on Atari games including Pong and Breakout.
- **[source-3f1650148789]** [When to Trust Your Model: Model-Based Policy Optimization (MBPO) – Janner et al., 2019](https://arxiv.org/abs/1906.08253) - tier 1 - peer-reviewed
  - MBPO uses short model-generated rollouts within a Dyna-style framework for sample-efficient policy optimization, demonstrating superior sample efficiency over model-free SAC/TD3 on MuJoCo benchmarks.
- **[source-93888bba9e41]** [A Forensic Analysis of Synthetic Data in RL: Diagnosing and Solving Algorithmic Failures in Model-Based Policy Optimization (2025)](https://arxiv.org/html/2510.01457) - not-tiered
  - Studies failure modes of MBPO's synthetic data in Dyna-style MBRL. Identifies why MBPO underperforms SAC on DeepMind Control Suite despite performing well on OpenAI Gym MuJoCo tasks.
- **[source-e1b6938f0378]** [Stealing That Free Lunch: Exposing the Limits of Dyna-Style Reinforcement Learning (ICML 2024)](https://arxiv.org/abs/2412.14312) - not-tiered
  - Identifies surprising performance gaps when applying Dyna-style MBRL across benchmarks: strong on OpenAI Gym but significantly weaker on DeepMind Control Suite, despite similar tasks and identical observation types.
- **[source-81e4f5976452]** [Dyna-style Model-based Reinforcement Learning with Model-Free Policy Optimization (Knowledge-Based Systems, 2024)](https://www.sciencedirect.com/science/article/abs/pii/S0950705124000637) - not-tiered
  - Dyna-style MBRL methods demonstrate superior sample efficiency compared to model-free counterparts; this paper proposes improvements combining Dyna-style model-based RL with model-free policy optimization.
- **[source-148243762ca4]** [When to Trust Your Data: Enhancing Dyna-Style Model-Based RL With Data Filter (2024)](https://arxiv.org/html/2410.12160v1) - not-tiered
  - Proposes a data filter for Dyna-style algorithms to selectively use model-generated transitions, reducing bias from inaccurate model predictions and improving sample efficiency.
- **[source-ba57a8ecd93e]** [Model-based Policy Optimization with Unsupervised Model Adaptation (AMPO, NeurIPS 2020)](https://proceedings.neurips.cc/paper/2020/file/1dc3a89d0d440ba31729b0ba74b93a33-Paper.pdf) - not-tiered
  - Proposes AMPO, an extension of MBPO using unsupervised domain adaptation to align model-generated data with real data distributions, improving policy performance in continuous control tasks.
- **[source-722f9bdf3928]** [Efficient Model-Based Reinforcement Learning (OpenReview)](https://openreview.net/pdf/da8797fa9e2c9fa4ead977af794e49ff2d201f85.pdf) - not-tiered
  - Demonstrates impressive sample efficiency using model-based RL by leveraging learned dynamics models to simulate future outcomes, referencing Janner et al. 2019 (MBPO) and related work.
- **[source-fb7967b1cff7]** [Continuous control with deep reinforcement learning (DDPG) – Lillicrap et al. 2015](https://arxiv.org/abs/1509.02971) - not-tiered
  - Introduces DDPG, a model-free, off-policy actor-critic algorithm using deep function approximators that can learn policies in high-dimensional continuous action spaces. Combines DPG with DQN insights: experience replay, target networks, batch normalization.
- **[source-f1dd8c9ee0ae]** [Deep Deterministic Policy Gradient Algorithm: A Systematic Review (PMC/Heliyon 2024)](https://pmc.ncbi.nlm.nih.gov/articles/PMC11101810/) - not-tiered
  - Comprehensive systematic review of DDPG: covers key concepts, formulation, implementation, training, and applications. DDPG is model-free, off-policy, actor-critic for continuous action spaces.
- **[source-0a63a42c2753]** [Policy Gradient Algorithms – Lil'Log (Lilian Weng, 2018)](https://lilianweng.github.io/posts/2018-04-08-policy-gradient/) - not-tiered
  - In-depth overview of policy gradient algorithms including DDPG. Covers deterministic policy gradient theorem, actor-critic architecture, soft target updates (tau parameter), and Ornstein-Uhlenbeck noise for exploration.
- **[source-5090e6bf1b28]** [An Evaluation of DDPG, TD3, SAC, and PPO (Atlantis Press)](https://www.atlantis-press.com/article/125998066.pdf) - not-tiered
  - Empirical comparison of DDPG, TD3, SAC, and PPO. DDPG performs worst due to overestimation of target Q-values; SAC and TD3 achieve higher rewards.
- **[source-abe2c072bc27]** [Deep Deterministic Policy Gradient Algorithm: A Systematic Review – ScienceDirect (Heliyon 2024)](https://www.sciencedirect.com/science/article/pii/S2405844024067288) - not-tiered
  - Systematic review of DDPG: formulation, implementation, training, applications. Covers actor-critic, experience replay, target networks, and extensions.
- **[source-fa4c2136e78f]** [Mastering Diverse Domains through World Models (DreamerV3, Hafner et al. 2023)](https://arxiv.org/abs/2301.04104) - not-tiered
  - DreamerV3, a general algorithm that outperforms specialized methods across over 150 diverse tasks with a single configuration. Learns a world model and improves behavior via imagination. First to collect a diamond in Minecraft from scratch.
- **[source-ec7577dd4f99]** [Mastering Diverse Control Tasks through World Models (Hafner et al., Nature 2025)](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12003158/) - tier 1 - peer-reviewed
  - Nature 2025 publication of DreamerV3. General algorithm outperforming specialized methods across 150+ diverse tasks with a single configuration. Covers Atari, DMControl, Crafter, Minecraft, and more.
- **[source-cf9a5a96475c]** [Mastering Memory Tasks with World Models – Recall to Imagine (R2I, ICLR 2024)](https://arxiv.org/abs/2403.04253) - not-tiered
  - R2I integrates state space models (SSMs) into world models of MBRL agents to enhance long-term memory and long-horizon credit assignment, outperforming DreamerV3 on memory domains (POPGym, BSuite). Up to 9x computational speed improvement.
- **[source-956367fdc142]** [Harmony World Models: Boosting Sample Efficiency for Model-based Reinforcement Learning (2023)](https://arxiv.org/abs/2310.00344) - not-tiered
  - Proposes Harmony World Models to boost sample efficiency in model-based RL.
- **[source-e31ea29000cc]** [Accelerating Model-Based Reinforcement Learning with State-Space World Models (2025)](https://arxiv.org/abs/2502.20168) - not-tiered
  - Proposes state-space world models for robot learning that improve sample efficiency over model-free RL. 12 citations in 2025.
- **[source-05a58ff3f070]** [KAN-Dreamer: Benchmarking Kolmogorov-Arnold Networks as Function Approximators in World Models (2025)](https://arxiv.org/abs/2512.07437) - not-tiered
  - Integrates KAN architectures into DreamerV3 framework, benchmarking parameter efficiency and interpretability versus MLPs in world models.
- **[source-2c57117bf7e8]** [DreamerV3-XP: Optimizing Exploration through Uncertainty Estimation (2025)](https://arxiv.org/abs/2510.21418) - not-tiered
  - DreamerV3-XP extends DreamerV3 with uncertainty estimation to improve exploration in sparse-reward settings.
- **[source-e7ab3f1d38a8]** [An Extended Benchmarking of Multi-Agent Reinforcement Learning Algorithms in Complex Fully Cooperative Tasks (AAMAS 2025)](https://arxiv.org/abs/2502.04773) - not-tiered
  - AAMAS 2025 paper benchmarking MARL algorithms including MAPPO, MAA2C, CDS, EOI, EMC across cooperative benchmarks SMAC and GRF. Finds MAPPO, MAA2C, CDS most consistent; SoTA exploration methods mostly underperform.
- **[source-1dbae5df12cd]** [PyMARL2: Fine-tuned MARL algorithms on SMAC (GitHub)](https://github.com/hijkzzz/pymarl2) - not-tiered
  - PyMARL2: Fine-tuned MARL algorithms achieving 100% win rates on most SMAC scenarios. Focuses on credit assignment mechanism and optimized QMIX implementation with state-of-the-art performance on SMAC.
- **[source-cac36772b1ff]** [EPyMARL: Extended PyMARL Benchmarking Multi-Agent Deep RL Algorithms (GitHub)](https://github.com/uoe-agents/epymarl) - not-tiered
  - EPyMARL: Extension of PyMARL codebase with additional MARL algorithms and environment support. Benchmarks algorithms in SMAC, LBF, RWARE, particle environments and matrix games.
- **[source-6da63be2766d]** [MARLlib Benchmarks Documentation](https://marllib.readthedocs.io/en/latest/resources/benchmarks.html) - not-tiered
  - MARLlib documentation benchmarks page: describes PyMARL, PyMARL2, EPyMARL frameworks for SMAC; covers credit assignment algorithms and state-of-the-art QMIX variants.
- **[source-0a881a43f1d0]** [Counterfactual Multi-Agent Policy Gradients (COMA) – Foerster et al., 2018](https://arxiv.org/abs/1705.08926) - not-tiered
  - COMA uses a centralised critic to estimate the Q-function and decentralised actors to optimise agents' policies. Uses a counterfactual baseline marginalising out a single agent's action for credit assignment.
- **[source-03f6af98ed79]** [Multi-Agent Actor-Critic for Mixed Cooperative-Competitive Environments (MADDPG) – Lowe et al., 2017](https://arxiv.org/abs/1706.02275) - not-tiered
  - MADDPG extends DDPG to multi-agent settings with a centralized critic for each agent that has access to all agents' observations and actions during training, while actors execute decentrally.
- **[source-a58c9d38a9b7]** [QMIX: Monotonic Value Function Factorisation for Deep Multi-Agent Reinforcement Learning – Rashid et al., 2018](https://arxiv.org/abs/1803.11485) - not-tiered
  - QMIX enforces a monotonic mixing network over per-agent Q-networks so argmax over local Q-values equals argmax over joint Q-value, enabling tractable decentralised execution.
- **[source-913788fbcff9]** [Value-Decomposition Networks For Cooperative Multi-Agent Learning (VDN) – Sunehag et al., 2017](https://arxiv.org/abs/1706.05296) - not-tiered
  - VDN decomposes the team value function into a sum of per-agent value functions, enabling decentralised execution by having each agent maximise its own Q-value.
- **[source-91af00305fff]** [The Surprising Effectiveness of PPO in Cooperative Multi-Agent Games (MAPPO) – Yu et al., 2022](https://arxiv.org/abs/2103.01955) - tier 1 - peer-reviewed
  - Shows PPO with centralized value function (MAPPO) is surprisingly effective in cooperative MARL, matching or surpassing specialized MARL algorithms across multiple benchmarks.
- **[source-d2c2c9151fa1]** [An Introduction to CTDE in Cooperative MARL (arXiv HTML, 2024)](https://arxiv.org/html/2409.03052v1) - tier 2
  - Detailed tutorial on CTDE covering QMIX, VDN, QPLEX, MADDPG, COMA, MAPPO with mathematical formulations and intuitions.
- **[source-b63ac7f73059]** [Multi-agent Reinforcement Learning: A Comprehensive Survey (arXiv 2023/2024)](https://arxiv.org/abs/2312.10256) - not-tiered
  - Detailed exploration of recent and past efforts of MARL, covering value-based, policy-based, and actor-critic approaches; updated July 2024.
- **[source-93e1fb6baedd]** [A survey on multi-agent reinforcement learning and its application (ScienceDirect 2024)](https://www.sciencedirect.com/science/article/pii/S2949855424000042) - not-tiered
  - Covers QMIX, QTRAN, and related value decomposition methods; addresses credit assignment and cooperative MARL applications.
- **[source-d03b3f1a7961]** [Comprehensive Survey on Multi-Agent Cooperative Decision-Making: Scenarios, Approaches, Challenges and Perspectives (arXiv 2025)](https://arxiv.org/abs/2503.13415) - not-tiered
  - Covers PPO-based MARL algorithms including MAPPO, HATRPO, HAPPO; discusses cooperative scenarios, centralized critics, and coordination challenges.
- **[source-6eb7528c1253]** [HARL: Heterogeneous-Agent Reinforcement Learning (JMLR 2024)](https://jmlr.org/papers/volume25/23-0488/23-0488.pdf) - tier 1 - peer-reviewed
  - JMLR 2024 paper on HAPPO and HATRPO for heterogeneous multi-agent RL; demonstrates state-of-the-art on SMAC and SMACv2 benchmarks without parameter-sharing.
- **[source-7729f5651fad]** [MARFT: Multi-Agent Reinforcement Fine-Tuning (arXiv 2025)](https://arxiv.org/abs/2504.16129) - not-tiered
  - Discusses MAPPO, HATRPO, HAPPO limitations and proposes multi-agent RL fine-tuning approach addressing monotonic improvement guarantees.
- **[source-b4ff71c5635a]** [Recent Advances in MARL for Intelligent Automation and Control of Water Environment Systems (MDPI 2025)](https://www.mdpi.com/2075-1702/13/6/503) - not-tiered
  - Reviews HATRPO and HAPPO for cooperative MARL; covers monotonic policy improvement limitations; 2025 application survey.
- **[source-c30cd861f54f]** [MARL-Papers: Curated Paper List of Multi-Agent Reinforcement Learning (GitHub)](https://github.com/LantaoYu/MARL-Papers) - not-tiered
  - Curated list of MARL papers including QMIX, MADDPG, safe MARL, heterogeneous MARL, and 2024 advances.
- **[source-aaefa1dae0f9]** [A Systematic Survey of Multi-Agent Reinforcement Learning (Transactions on Computer Science 2025)](https://wepub.org/index.php/TCSISR/article/view/5457) - not-tiered
  - Systematic survey covering CTDE framework, QMIX credit assignment, value decomposition, and recent MARL progress in autonomous driving and robot cluster control.
- **[source-939606780e38]** [Secrets of RLHF in Large Language Models Part I: PPO (arXiv 2023)](https://arxiv.org/abs/2307.04964) - not-tiered
  - Details PPO implementation for RLHF covering policy model, value model, reward model, reference model coordination; discusses instability, hyperparameter sensitivity, and alignment challenges.
- **[source-185cca1d6db6]** [Is DPO Superior to PPO for LLM Alignment? A Comprehensive Study (ICML 2024)](https://arxiv.org/abs/2404.10719) - tier 1 - peer-reviewed
  - Comprehensive comparison of PPO (reward-based) vs DPO (reward-free) for LLM alignment; finds PPO outperforms DPO on challenging benchmarks when properly tuned.
- **[source-d67e396242ea]** [The N Implementation Details of RLHF with PPO (ICLR Blogposts 2024)](https://iclr-blogposts.github.io/2024/blog/the-n-implementation-details-of-rlhf-with-ppo/) - not-tiered
  - Deep dive into OpenAI's original RLHF codebase; compiles implementation details of PPO for RLHF and creates minimal reproducible baseline matching original learning curves.
- **[source-3259543956e1]** [PPO for LLMs: A Guide for Normal People (Cameron Wolfe, Deep Learning Focus)](https://cameronrwolfe.substack.com/p/ppo-llm) - not-tiered
  - Explains PPO components for LLMs including four model copies (policy, reference, critic, reward), computational expense, hyperparameter sensitivity, and reproducibility challenges.
- **[source-94ca1a30da98]** [Fine-Tuning Language Models with Advantage-Induced Policy Alignment (APA, arXiv 2023)](https://arxiv.org/abs/2306.02231) - not-tiered
  - Shows PPO suffers from mode collapse, instability, and poor sample efficiency in RLHF; proposes APA as alternative using squared error loss on estimated advantages.
- **[source-027101d416e0]** [A Vision Researcher's Guide to PPO and GRPO (Yuge Shi, 2025)](https://yugeten.github.io/posts/2025/01/ppogrpo/) - not-tiered
  - Explains PPO vs GRPO for RLHF; notes GRPO eliminates separate critic model saving ~50% memory/compute; covers how DeepSeek used GRPO to replace PPO.
- **[source-a25f926bc4d7]** [Navigating the RLHF Landscape: From Policy Gradients to PPO, GAE, and DPO for LLM Alignment (HuggingFace Blog)](https://huggingface.co/blog/NormalUhr/rlhf-pipeline) - not-tiered
  - Covers mainstream RLHF approaches for LLMs including on-policy vs off-policy tradeoffs; explains PPO, GAE, and DPO components; notes computational demands of on-policy methods.
- **[source-d71d978e92fb]** [Reinforcement learning versus data-driven dynamic programming: a comparison for finite horizon dynamic pricing markets](https://link.springer.com/article/10.1057/s41272-025-00519-8) - tier 1 - peer-reviewed
  - Revenue management study comparing TD3, DDPG, PPO, SAC against classical dynamic programming for finite horizon pricing. With ~1000 training episodes, best RL algorithms achieve 90%+ of optimal solution.
- **[source-363138d0f3d5]** [Dynamic pricing under competition using reinforcement learning (DQN vs SAC)](https://link.springer.com/article/10.1057/s41272-021-00285-3) - not-tiered
  - Studies performance of DQN and SAC in different market models for dynamic pricing under competition. Direct comparison of discrete (DQN) and continuous (SAC) action space approaches in pricing.
- **[source-e6e1aee40507]** [Influence of Discrete and Continuous Action Spaces on DRL-Based Pricing Strategy Optimization for Electricity Retailers](https://doi.org/10.1109/iSPEC53008.2021.9735962) - not-tiered
  - Compares DQN (discrete) vs DDPG (continuous) action spaces for electricity retail pricing optimization. Direct head-to-head comparison of discrete vs continuous action space DRL approaches for pricing.
- **[source-034c358a153a]** [Deep Reinforcement Learning for Dynamic Pricing Strategies in Revenue Management (DQN with PER)](https://doi.org/10.1109/WCONF64849.2025.11233694) - not-tiered
  - Introduces DQN with prioritized experience replay for dynamic pricing in revenue management. Covers DQN architecture enhancements for pricing strategy optimization.
- **[source-6122f66c229d]** [Towards the Next Generation Airline Revenue Management: Deep RL for Seat Inventory Control](https://arxiv.org/html/1902.06824) - not-tiered
  - Deep RL approach to airline seat inventory control and overbooking as a revenue management problem. Covers application of deep RL to discrete airline pricing/inventory decisions.
- **[source-1fbe69d83614]** [Transfer learning to scale deep Q networks in the context of airline pricing](https://doi.org/10.1057/s41272-024-00493-7) - not-tiered
  - Uses transfer learning to scale DQN for airline pricing, a discrete action space revenue management problem.
- **[source-b4163a298b2c]** [Deep Reinforcement Learning for Dynamic Pricing and Ordering Policies in Perishable Inventory Management](https://www.mdpi.com/2076-3417/15/5/2421) - not-tiered
  - Deep RL methods for joint dynamic pricing and inventory ordering in perishable goods management. Covers reward shaping and various DRL algorithms for pricing+inventory tasks.
- **[source-e8e43c88e929]** [Deep Reinforcement Learning that Matters (Henderson et al., 2017/2018, AAAI)](https://arxiv.org/abs/1709.06560) - tier 1 - peer-reviewed
  - Investigates significance of hyperparameters in policy gradients for continuous control, variance in algorithms, and reproducibility. Finds that non-determinism and algorithm variance make results hard to reproduce and compare across benchmarks.
- **[source-454ebab42d72]** [Benchmarking Deep Reinforcement Learning for Continuous Control (Duan et al., 2016, ICML)](https://arxiv.org/abs/1604.06778) - not-tiered
  - Presents a benchmark suite of continuous control tasks; evaluates policy gradient methods including TRPO, DDPG, and CEM. One of the foundational RL benchmarking papers using MuJoCo environments.
- **[source-47759e2be7f0]** [Deep Reinforcement Learning at the Edge of the Statistical Precipice (Agarwal et al., NeurIPS 2021) – blog summary](https://psc-g.github.io/posts/research/rl/precipice/) - not-tiered
  - Performance profiles allow comparing methods at a glance; stochastic dominance is rarely observed across RL benchmarks with large numbers of tasks — profiles often intersect at multiple points, illustrating that no single algorithm dominates.
- **[source-c6a57b7bfb76]** [Deep Reinforcement Learning That Matters – AAAI 2018 Proceedings (Henderson et al.)](https://ojs.aaai.org/index.php/AAAI/article/view/11694) - not-tiered
  - AAAI 2018 published version. Illustrates variability in reported metrics and results when comparing against common baselines; suggests guidelines to make future results in deep RL more reproducible.
- **[source-a44c8d9c6f95]** [Benchmarking Deep Reinforcement Learning for Continuous Control (ResearchGate, Duan et al.)](https://www.researchgate.net/publication/301648324_Benchmarking_Deep_Reinforcement_Learning_for_Continuous_Control) - not-tiered
  - Compares several RL algorithms for continuous control; shows variable performance across different robotic tasks.
- **[source-551decda21de]** [REINFORCE++: Stabilizing Critic-Free Reinforcement Learning for LLM Reasoning](https://arxiv.org/abs/2501.03262) - tier 2
  - REINFORCE++: stabilizing critic-free RL for LLMs. Compares GRPO local norm vs global norm, shows GRPO overfits while REINFORCE++ learns more stably.
- **[source-ef4767ddecf0]** [Comparative Analysis and Parametric Tuning of PPO, GRPO, and DAPO for LLM Reasoning Enhancement](https://arxiv.org/abs/2512.07611) - not-tiered
  - Comparative analysis and parametric tuning of PPO, GRPO, and DAPO for LLM reasoning enhancement. GRPO refines PPO by estimating advantages relative to peer generations without requiring a value function.
- **[source-95f169483c70]** [The State of Reinforcement Learning for LLM Reasoning (Sebastian Raschka / Ahead of AI)](https://magazine.sebastianraschka.com/p/the-state-of-llm-reasoning-model-training) - not-tiered
  - State of RL for LLM reasoning model training. Key motivation for GRPO is computational efficiency by dropping the critic (value model). Sebastian Raschka's analysis.
- **[source-b4e5bbb212d7]** [A Guide to Reinforcement Learning Post-Training for LLMs: PPO, DPO, GRPO, and Beyond (Hugging Face Blog)](https://huggingface.co/blog/karina-zadorozhny/guide-to-llm-post-training-algorithms) - not-tiered
  - Guide to RL post-training for LLMs covering PPO, DPO, GRPO. GRPO skips the Critic network; samples responses for a given prompt and uses the mean score of the group as the baseline.
- **[source-7de7bbb220f9]** [From REINFORCE to Dr. GRPO: LLM Post-Training RL Notes](https://lancelqf.github.io/note/llm_post_training/) - not-tiered
  - From REINFORCE to Dr. GRPO: covers KL divergence term analysis across GRPO variants, DAPO, and Dr. GRPO for LLM reasoning tasks.
- **[source-18e81144570a]** [Direct Preference Optimization: Your Language Model is Secretly a Reward Model (Rafailov et al., NeurIPS 2023)](https://arxiv.org/abs/2305.18290) - tier 1 - peer-reviewed
  - DPO directly optimizes for human preferences without reinforcement learning, treating the LM as an implicit reward model. Exceeds PPO-based RLHF on sentiment control, matches or improves on summarization and dialogue, substantially simpler to implement.
- **[source-fbc915a360a7]** [Unpacking DPO and PPO: Disentangling Best Practices for Learning from Preference Feedback (2024)](https://arxiv.org/abs/2406.09279) - not-tiered
  - Disentangles best practices for DPO vs PPO in learning from preference feedback. Compares implementation choices and their effects on alignment performance.
- **[source-2d498259b679]** [A Comprehensive Survey of Direct Preference Optimization: Datasets, Theories, Variants, and Applications (2024)](https://arxiv.org/abs/2410.15595) - not-tiered
  - Surveys DPO variants including KTO, IPO, CPO, ORPO, SimPO and their theoretical foundations. Covers alignment tax, datasets, and applications of DPO-family methods.
- **[source-447b67765077]** [SimPO: Simple Preference Optimization with a Reference-Free Reward (NeurIPS 2024)](https://neurips.cc/virtual/2024/poster/96741) - not-tiered
  - SimPO introduces a reference-free reward for preference optimization with a target reward margin. Compared to DPO and latest variants on Mistral, Llama 3, Gemma 2.
- **[source-471f24a0369d]** [DPO vs PPO for LLMs: Key Differences & Use Cases (Clarifai Blog)](https://www.clarifai.com/blog/dpo-vs-ppo) - not-tiered
  - Practical comparison of DPO and PPO for LLM alignment, covering key differences and use cases. Notes PPO outperforms DPO on code-generation, DPO comparable on summarization and dialogue.
- **[source-76d4eafeba93]** [DPO vs PPO: How To Align LLM (Labellerr Blog)](https://www.labellerr.com/blog/dpo-vs-ppo-for-llm-all/) - not-tiered
  - Explains how DPO directly targets human preferences, potentially leading to faster and more effective alignment than PPO. Covers iteration, convergence, and practical steps.
- **[source-6c079ae80e68]** [Disentangling Length from Quality in Direct Preference Optimization (Park et al., ACL 2024)](https://arxiv.org/abs/2403.19159) - not-tiered
  - Addresses verbosity bias in DPO (R-DPO). Unlike classical RLHF, DPO does not train a separate reward model. Proposes length-regularized DPO to control verbosity exploitation.
- **[source-177a0eb399a9]** [Reproducibility of Benchmarked Deep RL Tasks for Continuous Control (Islam et al., 2017)](https://arxiv.org/abs/1708.04133) - tier 2
  - Investigates significance of hyperparameters in policy gradients for continuous control; discusses variance in algorithms, hyper-parameter tuning, and environment stochasticity in MuJoCo benchmarks.
- **[source-e1f20f61dae0]** [Comparative Analysis of DRL Algorithms for Autonomous UAV Navigation in MuJoCo (Aryan, SSRN)](https://papers.ssrn.com/sol3/Delivery.cfm/5398703.pdf?abstractid=5398703&mirid=1) - not-tiered
  - SAC achieves exceptional sample efficiency converging in 32 training episodes; PPO delivers superior position accuracy with 53.3% of flight time within 0.1 meters of target. Compares SAC, PPO, TD3 on UAV tasks.
- **[source-7ebcba703a58]** [MuJoCo Benchmark: Full RL Benchmark (DDPG, SAC, TD3, PPO, A2C) – GitHub](https://github.com/ChenDRAG/mujoco-benchmark) - not-tiered
  - Full reinforcement learning benchmark on MuJoCo environments covering DDPG, SAC, TD3, PG, A2C, PPO with comparative results and library implementations.
- **[source-160864885c95]** [Effective RL Control using Conservative SAC (CSAC) – arXiv 2025](https://arxiv.org/html/2505.03356v1) - tier 2
  - HalfCheetah-v4: CSAC achieves 11672.74 final return vs SAC's 11052.89 and PPO's 4181.89. Provides explicit numerical comparisons of SAC and PPO on MuJoCo tasks.
- **[source-dd5bf43c9436]** [PPO vs SAC vs TD3: Robotic Manipulation Benchmark Results (TildAlice)](https://tildalice.io/ppo-sac-td3-robotic-manipulation-benchmark/) - not-tiered
  - SAC achieved 89% success rate on peg insertion while PPO stalled at 61%; SAC policy collapsed at episode 800,000. Examines limitations of standard "SAC for continuous, PPO for everything else" advice.
- **[source-a0e6a7c16303]** [How Should We Meta-Learn Reinforcement Learning Algorithms? (Goldie et al., arXiv 2025)](https://arxiv.org/abs/2507.17668) - tier 2
  - Comprehensive empirical comparison of different meta-learning approaches for discovering RL algorithms, including evolution over black-box functions and LLMs proposing code. Addresses a severe lack of comparison between methods for meta-learning RL algorithms (2025).
- **[source-09d1b3e32005]** [A Tutorial on Meta-Reinforcement Learning (Beck, Vuorio, Zintgraf et al., arXiv 2023)](https://arxiv.org/abs/2301.08028) - not-tiered
  - Tutorial on meta-RL covering the paradigm of casting RL algorithm development as a machine learning problem itself. Co-authored by Luisa Zintgraf (also a DiscoRL co-author). 2023 survey with extensive coverage of prior meta-RL methods.
- **[source-940993c57fc9]** [Soft Actor-Critic: Off-Policy Maximum Entropy Deep RL with a Stochastic Actor (Haarnoja et al., 2018)](https://arxiv.org/abs/1801.01290) - tier 1 - peer-reviewed
  - SAC addresses DDPG's brittle convergence and high sample complexity via maximum entropy RL framework. Key comparison point to DDPG. 11000+ citations.
- **[source-9bdcfa578af9]** [Distributed Prioritized Experience Replay (Ape-X) – Horgan et al., 2018](https://arxiv.org/abs/1803.00933) - not-tiered
  - Proposes distributed architecture with prioritized experience replay that greatly scales DDPG-style off-policy learning. Directly extends and builds on DDPG's replay buffer mechanism. 814 citations.
- **[source-85abc53c73f9]** [Continuous control with deep reinforcement learning – DDPG PDF (Lillicrap et al. 2015)](https://arxiv.org/pdf/1509.02971) - tier 1 - peer-reviewed
  - Original DDPG paper PDF. Presents actor-critic model-free algorithm for continuous action spaces using deterministic policy gradient, experience replay, target networks.
- **[source-76449e9b61f6]** [Discovering Reinforcement Learning Algorithms (Oh et al., NeurIPS 2020)](https://arxiv.org/abs/2007.08794) - not-tiered
  - Introduces a new framework to automatically discover RL update rules from data. The direct predecessor to DiscoRL (Nature 2025), also by Oh, Hessel, van Hasselt, Singh, Silver. NeurIPS 2020, 147 citations.
- **[source-6fc86e47b7a9]** [Discovered Policy Optimisation (Lu et al., NeurIPS 2022)](https://arxiv.org/abs/2210.05639) - not-tiered
  - Discovered Policy Optimisation (DPO): meta-learning approach to automatically discover RL algorithms with minimal prior structure. NeurIPS 2022, 117 citations. Direct predecessor work to DiscoRL.
- **[source-8c645a69cef5]** [Discovering General Reinforcement Learning Algorithms with Adversarial Environment Design (Jackson et al., NeurIPS 2023)](https://arxiv.org/abs/2310.02782) - not-tiered
  - Examines how meta-training distribution characteristics impact generalization of meta-learned RL update rules (LPG). Addresses generalization gap when meta-learned algorithms are applied to unseen environments. NeurIPS 2023, 21 citations.
- **[source-afaaee7907cb]** [Meta-Gradient Reinforcement Learning with an Objective Discovered Online (Xu et al., NeurIPS 2020)](https://arxiv.org/abs/2007.08433) - not-tiered
  - Meta-gradient descent method that discovers its own objective, parameterized by a deep neural network, from interactive environment experience. NeurIPS 2020, 89 citations. By Xu, Hasselt, Hessel, Oh, Singh, Silver — core DiscoRL team.
- **[source-c131ea306e6b]** [Discovering Faster Matrix Multiplication Algorithms with Reinforcement Learning – AlphaTensor (Fawzi et al., Nature 2022)](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9534758/) - not-tiered
  - AlphaTensor: RL-based automated discovery of faster matrix multiplication algorithms, surpassing the best human-designed algorithms. Nature 2022, 675 citations. Related context for automated algorithm discovery.
- **[source-7e5d2ac4edf5]** [Improving Generalization in Meta-RL using Learned Objectives – MetaGenRL (Kirsch et al., ICLR 2020)](https://arxiv.org/abs/1910.04098) - not-tiered
  - MetaGenRL: meta-RL approach inspired by biological evolution that distills experiences of many complex agents to meta-learn a low-complexity neural objective function. ICLR 2020, 132 citations. Important predecessor to DiscoRL.
- **[source-03764d186fa4]** [TD-MPC2: Scalable, Robust World Models for Continuous Control (Hansen et al. 2023)](https://arxiv.org/abs/2310.16828) - tier 1 - peer-reviewed
  - TD-MPC2 improves significantly over baselines across 104 online RL tasks spanning 4 diverse task domains with a single set of hyperparameters. Trains a single 317M parameter agent. Strong comparison vs DreamerV3.
- **[source-f7fe1dee1fe2]** [DreamerV3 GitHub Repository (danijar/dreamerv3)](https://github.com/danijar/dreamerv3) - not-tiered
  - DreamerV3 GitHub repository by Danijar Hafner. Includes implementation details, scaling properties, and notes on how larger models improve data efficiency.
- **[source-11e86a060d7f]** [DreamerV3: Model-Based RL Algorithm – EmergentMind Topic Overview](https://www.emergentmind.com/topics/dreamerv3-algorithm) - not-tiered
  - EmergentMind topic page on DreamerV3, aggregating key findings from papers. Covers benchmarks including Minecraft, Atari 100k, DMC Vision, Crafter, and research on sample efficiency with different model sizes.
- **[source-216275617649]** [LightZero: A Unified Benchmark for Monte Carlo Tree Search in General Sequential Decision Scenarios (NeurIPS 2023)](https://arxiv.org/abs/2310.08348) - not-tiered
  - LightZero: first unified benchmark for MCTS/MuZero in general sequential decision scenarios, covering diverse action spaces including Atari. Open-source framework for MCTS-based RL.
- **[source-878341adb79b]** [MiniZero: Comparative Analysis of AlphaZero and MuZero on Go, Othello, and Atari Games](https://arxiv.org/abs/2310.11305) - not-tiered
  - MiniZero compares AlphaZero, MuZero, Gumbel AlphaZero, and Gumbel MuZero on Go, Othello, and 57 Atari games, analyzing trade-offs in performance and efficiency.
- **[source-6c65661475e7]** [Demystifying MuZero Planning: Interpreting the Learned Model (arXiv 2024)](https://arxiv.org/abs/2411.04580) - not-tiered
  - Demystifies MuZero planning by interpreting learned latent states via reconstruction and state consistency analysis across board and Atari games.
- **[source-28c261249465]** [Playing Atari with Deep Reinforcement Learning (Mnih et al., 2013 – DQN precursor)](https://arxiv.org/abs/1312.5602) - not-tiered
  - First deep learning model to learn control policies from raw pixels using RL and a CNN with Q-learning. Introduces experience replay. Outperforms all prior approaches on 6 of 7 Atari games.
- **[source-fe3d76d30944]** [Deep Reinforcement Learning with Double Q-learning (van Hasselt et al., 2015/2016)](https://arxiv.org/abs/1509.06461) - not-tiered
  - Shows DQN substantially overestimates action values on Atari; proposes Double DQN to decouple action selection and evaluation, improving accuracy and performance.
- **[source-5a352f605667]** [Deep Reinforcement Learning: An Overview (Li, 2017)](https://arxiv.org/abs/1701.07274) - not-tiered
  - Broad overview of deep RL covering DQN, value functions, policy gradient, exploration, memory, and many applications. 2017 arXiv survey.
- **[source-0695e3cdf802]** [AOAD-MAT: Transformer-based Multi-Agent Deep RL with Agent Order of Action Decisions (PRIMA 2025)](https://arxiv.org/abs/2510.13343) - not-tiered
  - AOAD-MAT: Transformer-based MARL model for multi-agent transformer with agent order-of-action decisions. Outperforms existing MAT on SMAC and MA-MuJoCo benchmarks (PRIMA 2025).
- **[source-8da8bd8d668d]** [Towards a Standardised Performance Evaluation Protocol for Cooperative MARL (Gorsane et al. 2022)](https://arxiv.org/abs/2209.10485) - not-tiered
  - Meta-analysis of 75 MARL papers (2016-2022) revealing worrying evaluation trends in cooperative MARL. Proposes standardized performance evaluation protocol for cooperative MARL.
- **[source-fadb237dfabe]** [SMACv2: An Improved Benchmark for Cooperative MARL (NeurIPS 2023)](https://dl.acm.org/doi/10.5555/3666122.3667756) - not-tiered
  - SMACv2 at NeurIPS 2023: procedurally generated scenarios for cooperative MARL. Shows near-perfect performance of SOTA algorithms on original SMAC and presents harder challenges on SMACv2.
- **[source-5a1dbd310e28]** [Multi-Agent Transformer (MAT) – PKU-MARL GitHub](https://github.com/PKU-MARL/Multi-Agent-Transformer) - not-tiered
  - Multi-Agent Transformer (MAT) repository from PKU-MARL. Includes few-shot performance comparison with pre-trained models on multiple SMAC tasks.
- **[source-f654b55476ae]** [Exploration and Modern Deep RL: SAC, PPO, TD3, DDPG (Autonomy Blog)](https://majid-mazouchi.github.io/autonomy/posts/rl-exploration-sac-ppo-td3-ddpg/) - not-tiered
  - If you have a fast simulator (hundreds of thousands of steps/sec), use PPO with many parallel envs. If you have slow data collection (real robot, expensive sim), use SAC for sample efficiency.
- **[source-b23282e8514d]** [Deep RL Off-Policy Algorithms Comparison: DDPG, TD3, SAC (arXiv 2022)](https://arxiv.org/pdf/2212.05572) - not-tiered
  - Compares DDPG, TD3, and SAC for four tasks on MuJoCo Fetch Robot Manipulator. Determines most ideal model-free off-policy RL algorithm based on success rate, epoch time, and efficiency.
- **[source-bc1b241762bf]** [An Extended Benchmarking of Multi-Agent Reinforcement Learning Algorithms (AAMAS 2025)](https://www.ifaamas.org/Proceedings/aamas2025/pdfs/p1613.pdf) - tier 1 - peer-reviewed
  - Extended benchmarking of MARL algorithms including QMIX, QPLEX, MAPPO, COMA, MAA2C across multiple environments like LBF, RWARE, Overcooked, MPE in 2025.
- **[source-fedb4e957dd0]** [ReZero: Boosting MCTS-based Algorithms by Just-in-Time and Speedy Reanalyze (2024)](https://arxiv.org/abs/2404.16364) - not-tiered
  - ReZero boosts MCTS-based algorithms (MuZero, EfficientZero) via just-in-time and speedy reanalyze. Benchmarked on Atari and board games using LightZero framework.
- **[source-12523beaf63b]** [Atari 100k Benchmark: Sample-Efficient RL (EmergentMind)](https://www.emergentmind.com/topics/atari-100k-benchmark) - not-tiered
  - Atari 100k benchmark page covering recent SOTA including DART and other model-based approaches for sample-efficient RL.
- **[source-abec764b2973]** [Weighted QMIX: Expanding Monotonic Value Function Factorisation for Deep MARL (Rashid et al., NeurIPS 2020)](https://arxiv.org/abs/2006.10800) - not-tiered
  - Extends QMIX by analysing its representational limitation and introducing weighted operators to address suboptimality in non-monotonic value functions.
- **[source-995f5fcd6519]** [A Survey of Multi-Agent Deep Reinforcement Learning with Communication (Zhu et al., 2022)](https://arxiv.org/abs/2203.08975) - not-tiered
  - Systematic survey of communication mechanisms in MADRL: message types, agent groups, collaboration strategies. Covers CommNet, DIAL, and recent advances.
- **[source-15c35aef333e]** [Deep Reinforcement Learning at the Edge of the Statistical Precipice (Agarwal et al., NeurIPS 2021)](https://arxiv.org/abs/2108.13264) - tier 1 - peer-reviewed
  - Argues that reliable evaluation in deep RL cannot ignore statistical uncertainty. Shows substantial discrepancies between conclusions drawn from point estimates vs thorough statistical analysis on Atari 100k. Proposes performance profiles; stochastic dominance rarely observed across tasks.
- **[source-e503ec37e35c]** [Comparing Deep Reinforcement Learning and Evolutionary Methods in Continuous Control (Zhang & Zaiane, 2017)](https://arxiv.org/abs/1712.00006) - not-tiered
  - Compares deep RL (PPO, DDPG) with evolutionary strategies for continuous control; shows that performance rankings change depending on the specific task environment.
- **[source-65fa54800da5]** [Artificial Intelligence, Algorithmic Pricing, and Collusion (Calvano et al., AER 2020)](https://doi.org/10.1257/AER.20190623) - tier 1 - peer-reviewed
  - Q-learning oligopoly experiment showing algorithms consistently learn supracompetitive prices without communication. Landmark tabular Q-learning in pricing, 478 citations.
- **[source-b9749043c47e]** [Deep reinforcement learning algorithms for dynamic pricing and inventory management of perishable products (Yavuz & Kaya, 2024)](https://doi.org/10.1016/j.asoc.2024.111864) - not-tiered
  - Deep RL algorithms comparison for dynamic pricing and inventory management of perishable products. Multiple DRL algorithms benchmarked, 29 citations.
- **[source-256a99c97b26]** [A review on reinforcement learning algorithms and applications in supply chain management](https://doi.org/10.1080/00207543.2022.2140221) - not-tiered
  - Semi-systematic literature review of RL algorithms in supply chain management including pricing and inventory. 265 citations - high-impact survey covering both tabular and deep RL.
- **[source-a648a01c798a]** [Reinforcement learning for Multi-Flight Dynamic Pricing](https://doi.org/10.1016/j.cie.2024.110302) - not-tiered
  - RL for multi-flight dynamic pricing in airlines. Covers pricing decisions in discrete action settings.
- **[source-1e82b4611c1e]** [A deep Q-learning approach to optimize ordering and dynamic pricing with strategic customers](https://doi.org/10.1016/j.ijpe.2024.109154) - not-tiered
  - Deep Q-learning to optimize ordering and dynamic pricing decisions with strategic customers. Published in International Journal of Production Economics, 17 citations.
- **[source-94fda41a2361]** [Training Language Models to Follow Instructions with Human Feedback (InstructGPT, Ouyang et al. 2022)](https://arxiv.org/abs/2203.02155) - not-tiered
  - Foundational InstructGPT paper: fine-tunes GPT-3 with RLHF using SFT, reward model training, and PPO; demonstrates alignment of LLMs with human preferences at scale.
- **[source-de457cec9d84]** [RRHF: Rank Responses to Align Language Models with Human Feedback without tears (arXiv 2023)](https://arxiv.org/abs/2304.05302) - not-tiered
  - Proposes RRHF as simpler alternative to PPO for RLHF, noting PPO is hyperparameter-sensitive and requires multiple models making it hard to scale; shows RRHF achieves competitive results with less complexity.
- **[source-3f87cc518337]** [Iterative Preference Learning from Human Feedback: Bridging Theory and Practice for RLHF under KL-Constraint (Xiong et al., 2023)](https://arxiv.org/abs/2312.11456) - not-tiered
  - Studies alignment process with RLHF; identifies challenges of offline PPO and offline DPO as lacking strategic exploration. Formulates RLHF as reverse-KL regularized contextual bandit. Proposes iterative approach bridging theory and practice.
- **[source-390402565fd2]** [Rethinking Implementation Tricks and Monotonicity Constraint in Cooperative MARL (ICLR Blogposts 2023)](https://iclr-blogposts.github.io/2023/blog/2023/riit/) - tier 3
  - ICLR 2023 blog post analyzing QMIX implementation tricks and monotonicity constraint; shows that improved QMIX implementation achieves state-of-the-art performance despite representation limitations.
- **[source-176cd3611fa0]** [Comparative Evaluation of Cooperative Multi-Agent Deep RL Algorithms (ALA 2021)](https://ala2021.vub.ac.be/papers/ALA2021_paper_44.pdf) - not-tiered
  - Comparative evaluation of CTDE algorithms (MADDPG, COMA, VDN, QMIX) at ALA 2021 workshop; discusses centralized policy gradient vs value decomposition classes.
- **[source-ff52e689aa86]** [Deterministic Policy Gradient Algorithms – Silver et al. (2014, ICML)](http://proceedings.mlr.press/v32/silver14.pdf) - not-tiered
  - Silver et al. 2014 ICML paper introducing the Deterministic Policy Gradient theorem - the direct theoretical precursor to DDPG. Shows that the deterministic policy gradient is the expected gradient of the action-value function.
- **[source-df984ea71dc0]** [DAPO: An Open-Source LLM Reinforcement Learning System at Scale](https://arxiv.org/abs/2503.14476) - not-tiered
  - DAPO: Decoupled Clip and Dynamic Sampling Policy Optimization — open-source large-scale RL system building on GRPO for LLM reasoning, achieving state-of-the-art performance.
- **[source-42aaf62c7ba0]** [Reinforcement Learning with Verifiable Rewards: GRPO's Effective Loss, Dynamics, and Success Amplification](https://arxiv.org/abs/2503.06639) - not-tiered
  - Analyzes GRPO's effective loss, dynamics, and success amplification in RLVR settings. GRPO used successfully to train DeepSeek-R1 models for promoting reasoning capabilities using verifiable or binary rewards.
- **[source-50c222f5fd0e]** [DeepSeek-R1 incentivizes reasoning in LLMs through reinforcement learning (Nature)](https://www.nature.com/articles/s41586-025-09422-z) - not-tiered
  - Nature article on DeepSeek-R1: demonstrates reasoning abilities of LLMs can be incentivized through pure reinforcement learning, removing need for human-annotated demonstrations.
- **[source-d416beaf41f6]** [Large Language Model Post-Training: A Unified View of Off-Policy and On-Policy Learning (arXiv 2026)](https://arxiv.org/abs/2604.07941) - not-tiered
  - Unified survey of LLM post-training covering SFT, preference optimization, RL (PPO, GRPO), process supervision, and multi-stage pipelines; frames methods by behavioral bottlenecks rather than labels.
- **[source-ca7539dcf5a8]** [Awesome Model-Based RL – Curated Resource List (OpenDILab, GitHub)](https://github.com/opendilab/awesome-model-based-RL) - not-tiered
  - A curated list of awesome model-based RL resources covering MBPO, Dreamer, PETS, TDMPC and many variants. Continually updated GitHub list covering the landscape of model-based RL methods.
- **[source-3c7187032214]** [Optimistic World Models: Efficient Exploration in Model-Based Deep RL (2025)](https://arxiv.org/abs/2602.10044) - not-tiered
  - Proposes optimistic world models for efficient exploration in model-based deep RL. Categorizes world model-based RL into Dreamer-style (policy gradient in imagination) and Dyna-style approaches (MBPO etc.), covering the landscape from 2020 to 2025.
- **[source-596b42f183c0]** [Dreamer ICLR 2024 – Sample Efficient Model-Based RL](https://arxiv.org/abs/2403.09859) - not-tiered
  - ICLR 2024 paper showing Dreamer delivers sample efficiency of model-based RL on various domains with little hyperparameter tuning. Discusses MBPO, PETS, TDMPC and Dreamer family comparisons.
- **[source-e4c53dca5008]** [Model-Based Methods – Deep RL Course Notes (deeprlcourse.github.io)](https://deeprlcourse.github.io/course_notes/model-based/) - not-tiered
  - Model-based RL course notes covering Dyna, MBPO short-horizon rollouts, PETS, Dreamer. Explains why MBPO uses 1–5 step imaginary rollouts and how Dyna-style methods improve sample efficiency over model-free baselines.
- **[source-d8c64d5997eb]** [Efficient Model-Based RL Through Optimistic Thompson Sampling (2024)](https://arxiv.org/abs/2410.04988) - not-tiered
  - Efficient model-based RL via optimistic Thompson sampling. Discusses PETS (Chua 2018), Dreamer (Hafner 2020/2023), TD-MPC (Hansen 2022/2024) and MBPO (Janner 2019) within a unified taxonomy of model-based approaches.
- **[source-966068fc965b]** [Model-Based Policy Optimization (MBPO) Topic – Emergent Mind](https://www.emergentmind.com/topics/model-based-policy-optimization-mbpo) - not-tiered
  - Emergent Mind MBPO topic page aggregating papers on model-based policy optimization variants: scheduling hyperparameters, improvements over SAC/TD3, MuJoCo and PyBullet benchmarks.
- **[source-574521617957]** [Transformers are Sample-Efficient World Models (IRIS, Micheli et al. ICLR 2023)](https://arxiv.org/abs/2209.00588) - not-tiered
  - IRIS uses a discrete autoencoder and transformer-based world model to achieve data-efficient RL on Atari 100k, demonstrating state-of-the-art performance and compelling sample efficiency comparison vs DreamerV2 and others.
- **[source-e6a72761c62a]** [Transformer-based World Models Are Happy With 100k Interactions (TWM, Robine et al. 2023)](https://arxiv.org/abs/2303.07109) - not-tiered
  - Transformer-based world model using autoregressive sequence modeling over states, actions, and rewards. Shows sample efficiency at 100k interactions benchmark, competing with IRIS and DreamerV3.
- **[source-35507fa4b13f]** [Stealing That Free Lunch: Exposing the Limits of Dyna-Style RL (Barkley & Fridovich-Keil, ICML 2024)](https://arxiv.org/pdf/2412.14312) - tier 1 - peer-reviewed
  - Identifies and investigates a surprising performance gap for Dyna-style MBRL algorithms: strong on OpenAI Gym but significantly weaker on DeepMind Control Suite (DMC) environments. ICML 2024 paper.
- **[source-2f2eb9a14820]** [DreamerV3 Official Project Page (danijar.com)](https://danijar.com/project/dreamerv3/) - not-tiered
  - Official DreamerV3 project page by Danijar Hafner. Contains links to code, paper, results across benchmarks. Notes Dreamer substantially outperforms PPO and enables RL without domain-specific expertise.
- **[source-f0b7c70f7e09]** [DreamerNav: Learning-Based Autonomous Navigation with World Models (PMC 2025)](https://pmc.ncbi.nlm.nih.gov/articles/PMC12510832/) - not-tiered
  - DreamerNav applies DreamerV3 for autonomous navigation in dynamic indoor environments. Compares DreamerV3 vs TD-MPC2; finds DreamerV3 more scalable and adaptable for navigation in latent space.
- **[source-1b1f02a0692c]** [Dueling Network Architectures for Deep Reinforcement Learning (Wang et al., 2015)](https://arxiv.org/abs/1511.06581) - not-tiered
  - Dueling network architecture separating state value and action advantage functions; built on top of DQN, demonstrating improved performance especially when actions have similar values.
- **[source-34fcf7850e05]** [Prioritized Experience Replay (Schaul et al., 2015)](https://arxiv.org/abs/1511.05952) - not-tiered
  - Develops prioritized experience replay, replaying important transitions more frequently via TD-error-based priorities, demonstrating improved DQN performance on Atari.
- **[source-04913451922e]** [Multi-level Advantage Credit Assignment for Cooperative MARL (2025)](https://arxiv.org/abs/2508.06836) - not-tiered
  - Multi-level advantage credit assignment for cooperative MARL, addressing scenarios where rewards are attributed to diverse overlapping agent subsets. 2025 preprint.
- **[source-bba6a47600cf]** [Exploratory Preference Optimization: Harnessing Implicit Q*-Approximation for Sample-Efficient RLHF (Xie et al., 2024)](https://arxiv.org/abs/2405.21046) - not-tiered
  - Explores online exploration in RLHF via implicit Q*-approximation; bridges DPO and online RL showing that DPO's offline nature limits exploration. Addresses computational and statistical bottlenecks in divergence-constrained preference optimization.
- **[source-ad60a0399be4]** [Revisiting the Arcade Learning Environment: Evaluation Protocols and Open Problems for General Agents (Machado et al., 2018, JAIR)](https://arxiv.org/abs/1709.06009) - not-tiered
  - Revisits Arcade Learning Environment evaluation protocols; shows diverse methodologies have become widespread and highlights how evaluation methodology choices significantly affect apparent algorithm rankings. 604 citations.
- **[source-81071a9ad926]** [Deep Reinforcement Learning that Matters – Semantic Scholar entry](https://www.semanticscholar.org/paper/Deep-Reinforcement-Learning-that-Matters-Henderson-Islam/33690ff21ef1efb576410e656f2e60c89d0307d6) - not-tiered
  - Semantic Scholar page listing citing papers for Henderson et al. 2018 'Deep Reinforcement Learning that Matters' - useful for citation traversal to find follow-up work on reproducibility and algorithm comparison.
- **[source-a16c0c971917]** [Benchmarking Model-Based Reinforcement Learning (Wang et al., 2019/2020)](https://arxiv.org/abs/1907.02057) - not-tiered
  - Benchmarks PPO, SAC, TD3 alongside model-based RL methods on MuJoCo tasks. Describes SAC and TD3 as very powerful baselines with stable performance across environments; numerical comparisons included.
- **[source-7b2e59698885]** [Tianshou MuJoCo Benchmark: SAC vs TD3 Numerical Scores (GitHub Issue #274)](https://github.com/thu-ml/tianshou/issues/274) - not-tiered
  - Tianshou MuJoCo benchmark: SAC Ant 5116.4±799.9, HalfCheetah 10201.2±772.8, Hopper 3472.2±116.8, Walker2d 3982.4±274.5. TD3 comparison numbers also available (~3800, ~9750, ~2860, ~4000 respectively).
- **[source-aedfeaf4264a]** [Rainbow: Combining Improvements in Deep Reinforcement Learning (Hessel et al., AAAI 2018)](https://arxiv.org/abs/1710.02298) - not-tiered
  - Examines six extensions to DQN (Double DQN, Prioritized Replay, Dueling, Multi-step, Distributional, Noisy Nets) and their combination. Rainbow achieves state-of-the-art Atari performance while empirically identifying each component's contribution—implicitly clarifying DQN's base weaknesses.
- **[source-a03fd44229fe]** [Benchmarking Batch Deep Reinforcement Learning Algorithms (Fujimoto et al., 2019)](https://arxiv.org/abs/1910.01708) - not-tiered
  - Benchmarks batch deep RL algorithms under unified settings on Atari; finds that widely-used deep RL algorithms fail in batch setting and many algorithms underperform. Shows algorithm performance changes dramatically across settings.
- **[source-657a42b782c7]** [REBEL: Reinforcement Learning via Regressing Relative Rewards (Gao et al., 2024)](https://arxiv.org/abs/2404.16767) - tier 1 - peer-reviewed
  - REBEL simplifies policy optimization to regressing relative rewards, offering strong theoretical guarantees and empirical performances. Empirically outperforms PPO and DPO in language generation and image generation. NeurIPS 2024.
- **[source-c591fcc2d760]** [REBEL: Reinforcement Learning via Regressing Relative Rewards (HTML full text, v2)](https://arxiv.org/html/2404.16767v2) - not-tiered
  - Full HTML version of REBEL paper. Discusses reward-balanced loss, comparison to PPO and DPO, theoretical guarantees, and empirical results on Llama-3-8B fine-tuning.
- **[source-c5ecf554949a]** [REBEL: Reinforcement Learning via Regressing Relative Rewards (OpenReview, NeurIPS 2024)](https://openreview.net/forum?id=yxjWAJzUyV) - not-tiered
  - NeurIPS 2024 OpenReview page for REBEL. TL;DR: new RL algorithm that simplifies policy optimization to regressing relative rewards, offering strong theoretical guarantees and empirical performances.
- **[source-7fdc45007149]** [NeurIPS 2024 Poster: REBEL: Reinforcement Learning via Regressing Relative Rewards](https://neurips.cc/virtual/2024/poster/92983) - not-tiered
  - NeurIPS 2024 poster entry. REBEL achieves strong performance in AlpacaEval 2.0, MT-Bench, and Open LLM Leaderboard benchmarks, simpler to implement and more computationally efficient than PPO.
- **[source-96a604b8a5b5]** [DRO-REBEL: Distributionally Robust Relative-Reward Policy Optimization for LLM Alignment](https://sharansahu.com/data/DRO_REBEL__Fast_and_Robust_Policy_Optimization_for_LLM_Alignment_via_Distributional_Regression.pdf) - not-tiered
  - DRO-REBEL, a unified family of robust REBEL updates instantiated with Wasserstein, KL, and chi-squared ambiguity sets. Each DRO-REBEL step reduces to a simple relative-reward regression, preserving REBEL's scalability and avoiding PPO-style clipping or value networks.
- **[source-fe28116e2086]** [REBEL NeurIPS 2024 Poster Summary (deep-diver.github.io)](https://deep-diver.github.io/neurips2024/posters/yxjwajzuyv/) - not-tiered
  - Summary: REBEL, a novel RL algorithm, simplifies policy optimization by regressing relative rewards, achieving strong performance in language and image generation tasks with increased efficiency.
- **[source-06cb4410c47e]** [Back to Basics: Revisiting REINFORCE Style Optimization for Learning from Human Feedback in LLMs (RLOO paper, ACL 2024)](https://arxiv.org/abs/2402.14740) - tier 1 - peer-reviewed
  - Introduces RLOO (REINFORCE Leave One Out) for RLHF. Shows vanilla policy gradient REINFORCE consistently outperforms PPO; RLOO uses leave-one-out baseline for variance reduction; requires less GPU memory than PPO.
- **[source-e43eb8a9297f]** [Putting RL Back in RLHF with RLOO (Hugging Face Blog)](https://huggingface.co/blog/putting_rl_back_in_rlhf_with_rloo) - not-tiered
  - As an alternative to PPO, RLOO is a new online RLHF training algorithm designed to be more accessible and easier to implement. Requires less GPU memory and takes less wall time to converge.
- **[source-1cfec4b7dc3b]** [REINFORCE: Easy Online RL for LLMs (Cameron Wolfe, Deep Learning Focus)](https://cameronrwolfe.substack.com/p/reinforce) - not-tiered
  - Covers REINFORCE for LLMs, RLOO, and how these online RL algorithms compare to PPO and actor-critic methods. Explains higher variance policy gradients vs PPO.
- **[source-d462c50a89c1]** [REBEL GitHub Repository (ZhaolinGao/REBEL)](https://github.com/ZhaolinGao/REBEL) - not-tiered
  - Official implementation of REBEL: Reinforcement Learning via Regressing Relative Rewards. By Zhaolin Gao et al. Cornell/Princeton/CMU/Aurora Innovation.
- **[source-d21aae9a1916]** [REBEL: Reinforcement Learning via Regressing Relative Rewards (Author PDF)](https://zhaolingao.github.io/assets/pdf/rebel.pdf) - not-tiered
  - Author's hosted PDF. Proves Natural Policy Gradient can be seen as a variant of REBEL, matching strongest known theoretical guarantees in terms of convergence.
- **[source-51b68ffd3683]** [A Comprehensive Survey of LLM Alignment Techniques: PPO, GRPO, RLHF, RLVR](https://arxiv.org/abs/2407.16216) - not-tiered
  - Self-contained introduction to MLE, RLHF, and RLVR foundations and unified policy gradient framework; detailed technical analysis of PPO- and GRPO-based methods alongside offline and iterative DPO approaches; standardized notation enabling direct cross-method comparison.
- **[source-7cdd1d75b9dc]** [A Technical Survey of Reinforcement Learning Techniques for Large Language Models (2025)](https://arxiv.org/html/2507.04136v1) - not-tiered
  - Examines PPO's stability in RLHF, Q-learning/off-policy methods for offline datasets, and GRPO's improved training efficiency via relative advantage estimation within grouped candidate responses.
- **[source-178d264a09fb]** [Online vs Offline RL for LLMs (Cameron Wolfe, Deep Learning Focus)](https://cameronrwolfe.substack.com/p/online-rl) - not-tiered
  - Covers online RL training for LLMs versus offline DPO; DPO avoids explicit reward model and derives signal implicitly from the LLM itself; explains tradeoffs of each paradigm for LLM alignment.
- **[source-e17c129c24c5]** [GRPO vs PPO for LLM Reasoning: DeepSeek-R1 Practical Comparison (TildAlice)](https://tildalice.io/grpo-vs-ppo-llm-reasoning/) - not-tiered
  - GRPO eliminates the critic network, requiring significantly less memory than PPO; most implementations use 16-32 group size as balance between advantage estimation quality and compute cost.
- **[source-536cae03949b]** [Does Reinforcement Learning Really Incentivize Reasoning? RLVR Pass@k Analysis (OpenReview)](https://openreview.net/pdf?id=4OsgYD7em5) - tier 1 - peer-reviewed
  - Pass@k curves show RL-trained models outperform base models when k is small, but as k increases to tens or hundreds, base models consistently catch up and surpass RL-trained counterparts across multiple mathematical benchmarks.
- **[source-fd984ce61190]** [Reinforcement Learning for Reasoning in Large Language Models with One or Two Examples (arXiv 2025)](https://arxiv.org/abs/2504.20571) - not-tiered
  - RLVR with 1 or 2 examples can perform as well as RLVR trained with full datasets on AIME 2024/2025, AMC 2023, and GSM8K benchmarks. Provides empirical results on major math reasoning benchmarks.
- **[source-38dc7947a701]** [On the Optimization Dynamics of RLVR: Gradient Gap and Step Size Thresholds](https://arxiv.org/html/2510.08539) - not-tiered
  - Theoretical analysis validating GRPO training dynamics on Qwen2.5-Math-7B for GSM8K, DeepScaleR, and DAPO-17k datasets. Studies gradient gap and step size effects in RLVR optimization.
- **[source-8bdd32bc717c]** [Post-Training in 2026: GRPO, DAPO, RLVR and Beyond](https://llm-stats.com/blog/research/post-training-techniques-2026) - not-tiered
  - RLVR trains models on tasks where correctness can be automatically checked (math, code); key shift from human-labeled feedback to automated verifiable rewards. Covers GRPO, DAPO, and emerging post-training paradigms.
- **[source-0e55206b679e]** [LLMs Can Learn to Reason Via Off-Policy RL (Ritter et al., 2026)](https://arxiv.org/html/2602.19362) - not-tiered
  - Proposes off-policy RL for LLMs, citing REBEL. LLMs can learn to reason via off-policy RL, addressing the on-policy assumption of PPO and GRPO. By Owen Oertell et al. (same REBEL group), 2026.
- **[source-aeb9be4f4016]** [Imbalanced Gradients in RL Post-Training of Multi-Task LLMs (Wu et al., 2025)](https://arxiv.org/html/2510.19178) - not-tiered
  - Imbalanced Gradients in RL Post-Training of Multi-Task LLMs. Shows certain tasks produce larger gradients biasing updates. Cites REBEL as context for RL post-training methods. 7 citations.
- **[source-e5548a869e26]** [Why DPO is a Misspecified Estimator and How to Fix It (Gopalan et al., 2025)](https://arxiv.org/html/2510.20413) - not-tiered
  - Shows DPO is a misspecified estimator when true reward function cannot be realized via the policy class — preference order reversal, worsening policy reward. Cites REBEL as alternative. 3 citations.
- **[source-bbd62e319e88]** [Beyond PPO – The New Wave of Policy Optimization Techniques for LLM Post-Training](https://ydnyshhh.github.io/posts/policy_optimization/) - not-tiered
  - Detailed analysis of GRPO variance issues, RLOO equivalence, and comparison of policy optimization methods including REINFORCE, RLOO, GRPO, PPO for LLM post-training.
- **[source-d75385313758]** [Review of Reinforcement Learning for Large Language Models (Survey)](http://www.liziniu.org/docs/RL4LLM_Survey.pdf) - not-tiered
  - Comprehensive survey covering RLOO, GRPO, ReMax – notes that ReMax, GRPO, and RLOO achieve only local variance reduction. Covers variance reduction techniques from Dayan (1991) to 2025.
- **[source-1165dfbdefcb]** [Token-Efficient RL for LLM Reasoning (OpenReview)](https://openreview.net/pdf?id=XO8whE6Tx3) - not-tiered
  - Token-Efficient RL for LLM Reasoning. References RLOO/grouped baselines in REINFORCE. OpenReview paper on efficient RL algorithms for reasoning tasks.
- **[source-7a7b04f8ad22]** [REINFORCE++ Algorithm Overview (Emergent Mind)](https://www.emergentmind.com/topics/reinforce-algorithm) - not-tiered
  - Emergent Mind overview of REINFORCE++ for RLHF: On Llama3 8B, REINFORCE++ reduced training time from 60h (PPO) to 42h. Covers token-level KL constraint, global advantage normalization, comparison to RLOO/GRPO/PPO.
- **[source-0ac1235028ed]** [LLM Post-Training: A Deep Dive into Reasoning Large Language Models (arXiv 2025)](https://arxiv.org/abs/2502.21321) - not-tiered
  - LLM post-training deep dive survey covering reasoning models, RLOO, REINFORCE++, GRPO and comparison of algorithms. 2025 preprint from multiple institutions.
- **[source-779a32fdd1bb]** [Segmental Advantage Estimation: Enhancing PPO for Long-Context LLM Training (arXiv 2025)](https://arxiv.org/abs/2601.07320) - not-tiered
  - Segmental Advantage Estimation paper comparing REINFORCE, RLOO, GRPO, PPO for long-context LLM training. Discusses how GRPO favors system complexity reduction but sacrifices fine-grained credit assignment.
- **[source-89ea541efa6a]** [Online Distributionally Robust LLM Alignment via Regression to Relative Reward (DRO-REBEL, 2025)](https://arxiv.org/html/2509.19104) - not-tiered
  - DRO-REBEL: online robust REBEL updates built on Wasserstein/KL/chi-squared ambiguity sets for RLHF alignment. Addresses overoptimization of offline RLHF. Sahu & Wells, Cornell, 2025.
- **[source-91ef77a79f6d]** [REBEL: Cornell Thorsten Joachims hosted PDF (final version)](https://www.cs.cornell.edu/~tj/publications/gao_etal_24c.pdf) - not-tiered
  - Cornell professor Thorsten Joachims's hosted version. Final version with full details on intransitive preferences, image generation results, Arena Hard benchmark, and comparisons to PPO/DPO.
- **[source-d93b2c1fd207]** [RLHF Workflow: From Reward Modeling to Online RLHF (arxiv 2405.07863)](https://arxiv.org/html/2405.07863v3) - not-tiered
  - RLHF Workflow: comprehensive practical alignment recipe covering reward modeling, online RLHF, and iterative preference learning. Benchmarks on AlpacaEval-2, MT-Bench, Chat-Arena-Hard.
- **[source-141a69cc32a7]** [Reinforcement Learning Meets Large Language Models: A Survey Across the LLM Lifecycle (2025)](https://arxiv.org/abs/2509.16679) - not-tiered
  - Systematically reviews theoretical and practical advancements whereby RL empowers LLMs, covering PPO, Q-learning, GRPO across the full lifecycle of LLMs including alignment, instruction-following, and reasoning.
- **[source-1542978fc5f1]** [Token-Efficient RL for LLM Reasoning: S-GRPO and T-SPMO (arXiv 2025)](https://arxiv.org/abs/2504.20834) - not-tiered
  - RL strategies for LLM reasoning under strict memory/compute limits; introduces S-GRPO (stochastic GRPO variant) and T-SPMO for token-level credit assignment, compatible with LoRA fine-tuning.
- **[source-ca0a15b82335]** [A Comparison of Reinforcement Learning (RL) and RLHF with GRPO/AIME Benchmarks (IntuitionLabs)](https://intuitionlabs.ai/articles/reinforcement-learning-vs-rlhf) - not-tiered
  - GRPO achieves group-based learning eliminating critic model; DeepSeek-R1 AIME 2024 pass@1 jumped from 15.6% to 71.0%; covers DPPO for structural PPO fixes, REINFORCE revival; compares RL vs RLHF paradigms comprehensively.
- **[source-a613b7bbaf15]** [On the Design of KL-Regularized Policy Gradient Methods (arXiv 2025)](https://arxiv.org/abs/2505.17508) - not-tiered
  - Analyzes KL-regularized policy gradients; covers RLOO, GRPO, ReMax, discusses bias introduced when importance weights omitted in GRPO KL term. Provides corrected surrogates gradient-equivalent to intended objective.
- **[source-9de05fe788ed]** [GRADE: Replacing Policy Gradients with Backpropagation for LLM Alignment (arXiv 2025)](https://arxiv.org/abs/2601.11574) - not-tiered
  - GRADE paper discusses how RLOO and GRPO can match or exceed PPO performance for RLHF while being substantially simpler. Reviews the RLOO = GRPO connection and implications.
- **[source-3441c03a07a4]** [AI discovers learning algorithm that outperforms those designed by humans (Joel Lehman, Nature News & Views, 2025)](https://doi.org/10.1038/d41586-025-03398-6) - not-tiered
  - Nature News & Views commentary by Joel Lehman on the DiscoRL paper. Independent expert perspective on the discovery of RL algorithms outperforming human-designed ones.
- **[source-5868c0c3ce73]** [AI teaches itself and outperforms human-designed algorithms (TechXplore, 2025)](https://techxplore.com/news/2025-10-ai-outperforms-human-algorithms.html) - not-tiered
  - News coverage of DiscoRL describing Disco57 evaluated on 57 Atari games, comparing against PPO and MuZero, then tested on unseen challenges including ProcGen, Crafter, and NetHack.
- **[source-401120bfa730]** [Reddit r/singularity: DeepMind DiscoRL discovers SOTA RL algorithms that outperform human-crafted algorithms](https://www.reddit.com/r/singularity/comments/1pnoces/deepmind_discorl_discovers_sota_rl_algorithms/) - not-tiered
  - Reddit community discussion thread about DiscoRL's SOTA claims. Community commentary on whether it rewrites source code and the significance of the discovered loss function.
- **[source-34f3c2f3a1ce]** [Gwern.net: Meta-Learning RL Directory (including DiscoRL coverage)](https://gwern.net/doc/reinforcement-learning/meta-learning/index) - not-tiered
  - Gwern's curated meta-learning RL directory noting that AI discovers a learning algorithm that outperforms those designed by humans, covering DiscoRL and related work.
- **[source-e6f0585550ad]** [Efficient RLHF: Reducing the Memory Usage of PPO (Santacroce et al., 2023)](https://arxiv.org/abs/2309.00754) - not-tiered
  - PPO requires over 3x the memory of Supervised Fine-Tuning (SFT), making it infeasible to use for most practitioners. Comprehensive analysis of memory usage, performance, and training time of memory-savings techniques for PPO in RLHF.
- **[source-3581cd23c0de]** [Understanding and Alleviating Memory Consumption in RLHF for LLMs (Zhou et al., 2024)](https://arxiv.org/abs/2410.15651) - not-tiered
  - First systematic examination of memory usage in the RLHF context, exploring various memory management strategies and unveiling the reasons behind excessive memory consumption in PPO-based RLHF fine-tuning.
- **[source-eb0c78c09495]** [DPO Meets PPO: Reinforced Token Optimization for RLHF (Zhong et al., 2024)](https://arxiv.org/abs/2404.18922) - not-tiered
  - Despite the great successes of PPO in alignment, its open-source implementation is still largely sub-optimal. Models RLHF as an MDP enabling fine-grained token-wise information for better optimization.
- **[source-a794c0d47116]** [Direct Advantage Regression: Aligning LLMs with Online AI Reward (DAR, 2025)](https://arxiv.org/abs/2504.14177) - not-tiered
  - PPO's implementation complexity, particularly the requirement for an additional value model, has motivated the search for simpler alternatives. RLOO introduced a streamlined approach eliminating the need for a separate value model.
- **[source-81f2dcf17aff]** [Deep RL at the Edge of the Statistical Precipice – Agarwal et al. 2021 (PDF)](https://arxiv.org/pdf/2108.13264) - not-tiered
  - Proposes performance profiles, IQM, and stratified bootstrap CIs for rigorous RL evaluation. Shows median/mean point estimates produce unreliable rankings; stochastic dominance rarely holds across tasks. NeurIPS 2021 Outstanding Paper.
- **[source-8d15066b0f07]** [Revisiting the ALE: Evaluation Protocols (Machado et al. 2018) – PDF](https://arxiv.org/pdf/1709.06009) - not-tiered
  - Revisits ALE evaluation protocols; diverse methodologies affect apparent algorithm rankings. Recommends sticky actions, full action set, and reporting over multiple seeds to avoid inflated performance estimates.
- **[source-feb29ebb3160]** [Deep RL at the Statistical Precipice – NeurIPS 2021 Proceedings PDF (Agarwal et al.)](https://proceedings.neurips.cc/paper_files/paper/2021/file/f514cec81cb148559cf475e7426eed5e-Paper.pdf) - tier 1 - peer-reviewed
  - NeurIPS 2021 full paper PDF. Performance profiles, IQM, and stratified bootstrap confidence intervals for reliable RL evaluation across ALE, Procgen, DMControl benchmarks.
- **[source-8fdbdaf2b80c]** [Mastering Atari, Go, Chess and Shogi by Planning with a Learned Model (MuZero, Schrittwieser et al. 2020, Nature)](https://arxiv.org/abs/1911.08265) - not-tiered
  - MuZero achieves superhuman performance in Atari, Go, Chess, and Shogi using a learned model with MCTS, without knowledge of the rules. First reported 57-game Atari results with MuZero.
- **[source-da12c103c894]** [Leveraging Procedural Generation to Benchmark Reinforcement Learning (ProcGen, Cobbe et al. 2020)](https://arxiv.org/abs/1912.01588) - tier 1 - peer-reviewed
  - Introduces ProcGen benchmark of 16 procedurally-generated games for measuring RL generalization. Establishes PPO baseline with 200 training levels and reports test performance. Standard benchmark for generalization research.
- **[source-a2a6e888db59]** [Benchmarking the Spectrum of Agent Capabilities (Crafter, Hafner 2022, ICLR)](https://arxiv.org/abs/2109.06780) - tier 1 - peer-reviewed
  - Introduces Crafter benchmark for evaluating RL generalization, memory, credit assignment. Reports PPO score of 4.6%, Rainbow 4.3%, expert human 50.5%. Standard benchmark for diverse capability evaluation.
- **[source-cc5610af2c54]** [Measuring Sample Efficiency and Generalization in RL Benchmarks: NeurIPS 2020 ProcGen Benchmark (Mohanty et al. 2021)](https://arxiv.org/abs/2103.15332) - not-tiered
  - NeurIPS 2020 ProcGen Competition design paper; centralized benchmark for measuring sample efficiency and generalization in RL with PPO baselines.
- **[source-52f8a8576334]** [Discovering Hierarchical Achievements in Reinforcement Learning via Contrastive Learning (CALE, NeurIPS 2023)](https://proceedings.neurips.cc/paper_files/paper/2023/file/c919a2b5ec1de69f2629f9119676e336-Paper-Conference.pdf) - not-tiered
  - Compares against PPO, DreamerV3, LSTM-SPCNN, MuZero+SPR baselines on Crafter. Provides benchmark comparison table with scores on Crafter achievements.
- **[source-4297025db042]** [DiscoRL: When Algorithms Learn to Design Algorithms (rewire.it blog)](https://rewire.it/blog/disco-rl-when-algorithms-learn-to-design-algorithms/) - not-tiered
  - Blog post summarizing DiscoRL benchmarks on Atari57, ProcGen, DMLab-30. Notes DiscoRL was evaluated against state-of-the-art hand-designed algorithms across these major benchmark suites.
- **[source-80bfe5955e40]** [Improving Generalization on ProcGen with Simple Architectural Changes and Scale (Jesson & Jiang, 2024)](https://arxiv.org/abs/2410.10905) - not-tiered
  - Demonstrates 37.9% reduction in optimality gap vs PPO baseline on ProcGen benchmark. Uses frame stacking and 3D convolutions. Provides updated baseline comparisons for ProcGen generalization.
- **[source-3bdd136f9576]** [Atari-5: Distilling the Arcade Learning Environment down to Five Games (Aitchison et al., 2022)](https://arxiv.org/abs/2210.02019) - not-tiered
  - Proposes Atari-5, a principled methodology for selecting small representative subsets of Atari 57. Critically examines the computational cost of generating results on the full 57-game dataset, reproducibility concerns, and statistical representativeness of subset evaluations.
- **[source-95a95554805f]** [CrossQ: Batch Normalization in Deep Reinforcement Learning for Greater Sample Efficiency and Simplicity](https://arxiv.org/abs/1902.05605) - tier 1 - peer-reviewed
  - CrossQ matches or surpasses current state-of-the-art methods in terms of sample efficiency, substantially reduces computational cost compared to REDQ and DroQ, and is easy to implement requiring just a few lines of code on top of SAC.
- **[source-4a75ef697fd7]** [Randomized Ensembled Double Q-Learning: Learning Fast Without a Model (REDQ)](https://arxiv.org/abs/2101.05982) - tier 1 - peer-reviewed
  - REDQ achieves performance just as good as, if not better than, a state-of-the-art model-based algorithm for the MuJoCo benchmark, using fewer parameters and less wall-clock time. Uses high UTD ratio to dramatically improve sample efficiency over SAC.
- **[source-d913490f3c14]** [Controlling Overestimation Bias with Truncated Mixture of Continuous Distributional Quantile Critics (TQC)](https://arxiv.org/abs/2005.04269) - tier 1 - peer-reviewed
  - TQC blends distributional representation of a critic, truncation of critics prediction, and ensembling of multiple critics. TQC outperforms the current state of the art on all environments from the MuJoCo benchmark suite.
- **[source-80a162d57efc]** [Dropout Q-Functions for Doubly Efficient Reinforcement Learning (DroQ)](https://arxiv.org/abs/2110.02034) - tier 1 - peer-reviewed
  - DroQ is a variant of REDQ that uses a small ensemble of dropout Q-functions, achieving state-of-the-art sample efficiency while being more computationally efficient than REDQ. Surpasses SAC in sample efficiency.
- **[source-958f6b142289]** [How Should We Meta-Learn Reinforcement Learning Algorithms? (Goldie et al., RLC 2025 – PDF)](https://rlj.cs.umass.edu/2025/papers/RLJ_RLC_2025_218.pdf) - tier 1 - peer-reviewed
  - Published at the Reinforcement Learning Conference 2025. Oxford/Whiteson group comparative study of different meta-learning approaches for discovering RL algorithms, including DiscoRL comparisons.
- **[source-fb684647e1e4]** [GitHub: learn-rl-algorithms – Official Implementation for "How Should We Meta-Learn RL Algorithms?" (Goldie et al.)](https://github.com/AlexGoldie/learn-rl-algorithms) - not-tiered
  - Official code implementation for the Oxford/Whiteson group paper comparing meta-learning approaches for discovering RL algorithms, presented at RLC 2025.
- **[source-1cc3cce69457]** [Bigger, Better, Faster: Human-level Atari with Human-level Efficiency (Schwarzer et al., ICML 2023)](https://arxiv.org/abs/2306.01418) - not-tiered
  - BBF achieves human-level performance on Atari 100k with human-level efficiency. Discusses compute cost vs performance tradeoffs for Atari benchmarks; uses IQM over 26 games with bootstrap CIs.
- **[source-1673390f391b]** [Agent57: Outperforming the Atari Human Benchmark (Badia et al., 2020)](https://arxiv.org/abs/2003.13350) - not-tiered
  - Agent57 is the first RL agent to outperform human benchmark on all 57 Atari games. Discusses MuZero and R2D2 failing on certain games; uses human normalized score (HNS) across Atari57.
- **[source-b3a957e2ae54]** [Assessing Generalization in Deep Reinforcement Learning (ICLR 2019 submission, OpenReview)](https://openreview.net/pdf?id=rylKB3A9Fm) - not-tiered
  - Discusses the problem of overfitting in RL evaluation; proposes evaluation methodology based on training and testing on multiple environments sampled from a distribution. Early work on train/test generalization protocols for RL benchmarks.
- **[source-a3681342357b]** [AI discovers learning algorithm that outperforms those designed by humans (Joel Lehman, Nature News & Views, 2025)](https://www.nature.com/articles/d41586-025-03398-6) - not-tiered
  - Nature News & Views commentary by Joel Lehman on the DiscoRL paper. An AI algorithm that discovers its own way to learn achieves state-of-the-art performance, including on some tasks it had never encountered before.
- **[source-834447d5cc1f]** [Implementation Matters in Deep Policy Gradients: PPO and TRPO (Engstrom et al., ICLR 2020)](https://arxiv.org/abs/2005.12729) - tier 1 - peer-reviewed
  - Code-level optimizations (not algorithm differences) are responsible for most of PPO's gain over TRPO. Shows that implementation tricks drive benchmark rankings, not algorithmic innovations.
- **[source-0f0aca047652]** [A Closer Look at Deep Policy Gradients (Ilyas et al., ICLR 2020)](https://arxiv.org/abs/1811.02553) - not-tiered
  - Behavior of deep policy gradient algorithms often deviates from their motivating framework: surrogate objective doesn't match true reward landscape, value estimators fail to fit true value, gradient estimates are poorly correlated with true gradient.
- **[source-32ad3b5c8b2b]** [Quantifying Generalization in Reinforcement Learning – CoinRun (Cobbe et al., ICML 2019)](https://arxiv.org/abs/1812.02341) - not-tiered
  - Introduces CoinRun benchmark; agents overfit to surprisingly large training sets. Finds vanilla deep RL algorithms generalize better than specialized schemes. Shows benchmark performance does not predict generalization.
- **[source-883c2efa671f]** [Hyperparameters in Reinforcement Learning and How To Tune Them (Eimer et al., ICML 2023)](https://arxiv.org/abs/2306.01324) - tier 1 - peer-reviewed
  - Demonstrates that reporting standards in RL do not include tuning seeds, making comparisons potentially unfair when tuning seeds overlap with test seeds. Shows that not accounting for tuning seeds when comparing against baselines is unfair, with specific examples on PPO on ProcGen. ICML 2023.
- **[source-b4ef75af5071]** [BRO: Bigger, Regularized, Optimistic – Scaling for Compute and Sample-Efficient Continuous Control (NeurIPS 2024)](https://arxiv.org/abs/2405.16158) - not-tiered
  - BRO algorithm: scaling model capacity with strong regularization leads to substantial improvements in sample efficiency. Conduct thorough investigation into interplay of scaling and RL enhancements for continuous control, NeurIPS 2024.
- **[source-4e897dfa162b]** [Deep RL at the Statistical Precipice – ar5iv HTML full text (Agarwal et al. 2021)](https://ar5iv.labs.arxiv.org/html/2108.13264) - not-tiered
  - Full HTML rendering of Agarwal et al. 2021 NeurIPS Outstanding Paper on statistical evaluation in deep RL. Contains full text with figures and tables.
- **[source-0d3d69704b0f]** [Reddit: Current state-of-the-art for continuous action space (2024 equivalent of SAC)?](https://www.reddit.com/r/reinforcementlearning/comments/1i3l41q/what_is_the_current_state_of_the_art_method_for/) - not-tiered
  - Community consensus: TD-MPC2 has the best performance surpassing DreamerV3. SAC is really established baseline but there are simply better algorithms. CrossQ got added to stable baselines so will probably be a popular benchmark going forward.
- **[source-1caafa0ed4e0]** [A Hitchhiker's Guide to Statistical Comparisons of RL Algorithms (Colas, Sigaud, Oudeyer 2019)](https://arxiv.org/abs/1904.06979) - not-tiered
  - Hitchhiker's guide to statistical comparisons of RL algorithms. Reviews statistical tests and compares them in terms of false positive rate and statistical power as function of number of seeds and effect size. Directly relevant to 'default algorithm' validity claims.
