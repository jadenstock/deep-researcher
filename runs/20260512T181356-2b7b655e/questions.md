# Research questions

**Root query:** What are the best RL algorithms?


## Sub-questions (7)

1. [synthesis] What are the core modern deep RL algorithms (PPO, SAC, TD3, DDPG, DQN), what are their key mechanisms, and what are their documented strengths and weaknesses? Focus on the foundational papers and authoritative taxonomies (OpenAI Spinning Up, Stable Baselines3, original papers).
2. [contested] Which RL algorithm performs best in which setting? Summarize practical algorithm-selection guidance by task type: discrete vs continuous action space, sample budget, simulator availability, stability requirements. Engage with the contested claim that "no single algorithm dominates across benchmarks" and provide concrete head-to-head findings (e.g., PPO vs SAC vs TD3 on robotics, pricing, tabular).
3. [synthesis] What RL algorithms are used for LLM post-training (RLHF / RLVR), and how do PPO, DPO, GRPO, RLOO, REINFORCE++, and REBEL compare? Which are considered state-of-the-art as of 2024-2025, and what are their tradeoffs?
4. [sparse] What is the state of model-based RL (Dreamer, MuZero, MBPO, Dyna) and recent algorithm-discovery / meta-learned RL (e.g., the Nature 2025 paper on discovering SOTA RL algorithms)? How do these compare to model-free methods in sample efficiency and asymptotic performance?
5. [synthesis] What are the leading multi-agent RL (MARL) algorithms and the centralized training with decentralized execution (CTDE) paradigm? Which MARL algorithms are considered the strongest as of 2024-2025?
6. [adversarial] Steelman the case AGAINST the widespread recommendation (from [question-... practical guides] like Stable Baselines3 and OpenAI Spinning Up) that PPO and SAC are the best default RL algorithm choices. What are the strongest arguments that this guidance is outdated, misleading, or wrong — e.g., that newer algorithms (TD-MPC2, DreamerV3, EfficientZero V2, CrossQ, TQC, DroQ, REDQ) meaningfully outperform SAC/PPO; that PPO's dominance in RLHF reflects inertia rather than merit; that benchmark-driven claims are statistically unsound (Agarwal et al. 2021); or that the "default" itself is a trap that discourages domain-tailored selection?
7. [verify] Independently verify the claim that DiscoRL (Oh et al., Nature 2025) achieves state-of-the-art performance on Atari57, ProcGen, and Crafter, outperforming MuZero, Dreamer, and PPO. Is this claim (a) corroborated by independent sources/replications, (b) methodologically sound (fair comparison conditions, seeds, compute budgets), and (c) interpreted accurately? Look for critiques or caveats.
