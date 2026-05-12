# Research report

**Query:** What are the best methods for confidence elicitation in llms without using log-probs.

# Best Methods for Confidence Elicitation in LLMs Without Log-Probs

## Takeaway

There is no single dominant method. For **black-box deployment** (API access only, no fine-tuning), the strongest empirical recipe is a **hybrid of verbalized confidence plus sampling consistency** — with Xiong et al.'s Top-K + Avg-Conf (ICLR 2024) as the workhorse default and the 2-sample SCVC hybrid as the cost-efficient choice for reasoning models. For **highest calibration quality when fine-tuning is permitted**, **SaySelf** (SFT+RL with self-reflective rationales, EMNLP 2024) is the state of the art. For **hallucination detection specifically**, **semantic entropy** (Farquhar et al., *Nature* 2024) and its pairwise-similarity extensions are the principled choice, though at 5–10× compute overhead. Pure verbalized prompting alone is consistently overconfident across all current models and should not be used unmitigated. Practically the whole field agrees that consistency-based methods fail silently when models are "consistently wrong" — a genuinely unsolved failure mode requiring external grounding (retrieval, tools, cross-model disagreement).

---

## 1. Why the Question Is Framed Around "Without Log-Probs"

Confidence elicitation research divides along a **white-box vs. black-box axis** [source-5e0e26d17c13]. White-box methods consume logits, hidden states, or attention — unavailable for most frontier APIs (OpenAI, Anthropic, Google) and for many production deployments. "Without log-probs" therefore means *black-box methods*, the practical regime for most builders.

The terminology in the literature is inconsistent: *confidence elicitation*, *verbalized confidence*, *uncertainty quantification (UQ)*, and *calibration* are used nearly interchangeably. Two evaluation tasks should be distinguished:
- **Calibration (ECE, Brier, ACE)**: does P(correct | confidence=c) ≈ c?
- **Failure prediction (AUROC)**: can confidence rank correct above incorrect answers?
These come apart — a method can be well-calibrated but have near-random AUROC, or have strong AUROC but be systematically overconfident in absolute levels.

---

## 2. The Five Method Families

### 2.1 Verbalized / Direct Prompting

The model is asked to state its confidence directly (e.g., "How confident are you, 0–100%?"). Canonical references are Kadavath et al. 2022 (P(True)), Tian et al. EMNLP 2023 [source-a3be8a933ba7], and Xiong et al. ICLR 2024 [source-60d0f7a54402]. Variants include **Top-K** (generate K candidates each with probabilities), **Self-Probing** (ask the model to verify its own answer), **Multi-Step** (decompose the reasoning and assign confidence per step), and **SteerConf** [source-cc4907b4075e] which brackets the answer with conservative- and optimistic-steering prompts and uses their gap as a calibration signal.

**Signature failure mode**: severe overconfidence. Models cluster confidence in the 80–100% band, often in multiples of 5 [source-60d0f7a54402], and across 11 LLMs × 17 prompt methods *"overconfidence is present for LLMs of all sizes"* [source-9a967cf55c60]. On adversarial tasks (TruthfulQA), ECE of ~0.4 is typical even for GPT-4. The failure mode has a training origin: RLHF reward models incentivize appearing helpful over expressing uncertainty [source-b9deccfb8752].

### 2.2 Sampling / Consistency-Based Methods

Generate *N* stochastic responses, measure their mutual agreement, use disagreement as an uncertainty signal. This family does not need log-probs — only repeated queries.

- **SelfCheckGPT** (Manakul et al., EMNLP 2023) [source-192a0d82b6ff] — the seminal zero-resource method; compares samples via BERTScore, NLI entailment, n-gram, or LLM-prompting.
- **Semantic entropy** (Farquhar et al., *Nature* 2024) — clusters samples by bidirectional NLI entailment and computes entropy over semantic *meaning-classes* rather than token sequences; the discrete variant uses empirical cluster frequencies, making it fully black-box.
- **SNNE / pairwise semantic similarity** (ACL 2025) [source-4d25bbb9aff6] — nearest-neighbor entropy estimator that handles intra-cluster and inter-cluster similarity; addresses the known degradation of semantic entropy on longer outputs where each sample lands in its own cluster.
- **Semantic dispersion** (Lin et al., TMLR 2024) [source-7ffc8edfe5ea] — graph-based spread (e.g., eigenvalues of a similarity graph Laplacian).
- **MBR / CoCoA** [source-9292120a578a] — unifies consistency methods under Minimum Bayes Risk and multiplicatively combines model confidence with semantic consistency.
- **Prompt perturbation** [source-0c4508496d5c] — paraphrase/reorder to probe stability.

**Signature failure mode**: the *consistently wrong* case [source-3c982b0e793b]. Semantic entropy's authors explicitly scope out this failure: *"Our method explicitly does not directly address situations in which LLMs are confidently wrong because they have been trained with objectives that systematically produce dangerous behaviour… these need to be handled separately."* This is not a minor caveat — it means all consistency methods give high (falsely reassuring) confidence precisely when models have stable, systematic biases. On Slake medical VQA, semantic entropy's ECE was 0.38–0.45 without external grounding [source-3c982b0e793b].

### 2.3 Chain-of-Thought / Reasoning-Based

Rather than asking for confidence directly, embed uncertainty elicitation within the reasoning trace itself. Extended-CoT reasoning models (DeepSeek-R1, o1, QwQ) appear to calibrate better than their instruction-tuned counterparts: Yoon et al. 2025 [source-5427248b02fe] find **reasoning models beat non-reasoning counterparts on ECE/AUROC/Brier in 33 of 36 settings**. The gains are attributed to "slow thinking" — backtracking, exploring alternatives, dynamically revising confidence through the trace. Even non-reasoning models benefit when few-shot exemplars include slow-thinking traces. Related: EDTR [source-2450e587f851] applies topological analysis and Dirichlet UQ across multiple CoT paths; self-verification can be elicited by SFT with scalar confidence labels alone [source-31f3eff95574].

**Important nuance**: Standard CoT prompting on non-reasoning models does *not* improve verbalized calibration [source-a3be8a933ba7]. Only *extended reasoning with non-linear exploration* helps. And the calibration benefit has real limits — see §4 below.

### 2.4 Training-Based (Fine-Tuning / RLHF)

- **SaySelf** (Xu et al., EMNLP 2024) [source-b9deccfb8752] — the leading method. Two-stage: (1) SFT on self-reflective rationales constructed by clustering 100 sampled responses per question and having GPT-4 write an uncertainty-explanatory rationale; (2) PPO with reward = confidence² if correct, –confidence² if incorrect — directly penalizing overconfident errors. Achieves the lowest ECE and highest AUROC in its evaluation against direct prompting and self-consistency on 6 QA datasets, including out-of-distribution.
- **UaIT** (Liu et al., EMNLP 2024) [source-30e5f8c2d098] — fine-tunes on sampling-based uncertainty estimates as labels; achieves a 45.2% average AUROC improvement over direct verbalization and 12.6% over the sampling-based teacher, with single-pass inference cost.
- **Rewarding Doubt** [source-675839e952b6], **ConfTuner**, **CoCA** — related RL-based approaches using calibration-aware rewards or proper scoring rules (Brier) as loss.
- **CSFT** [source-31f3eff95574] — simple supervised fine-tuning on scalar confidence labels reduces ECE from 0.21 → 0.06 on GSM8K for LLaMA-3B.

**Signature failure mode**: not strictly black-box (requires model access for fine-tuning); dependent on GPT-4 for rationale generation; faithfulness of CoT rationales is debated; CSFT without KL regularization can produce "well-calibrated but confidently incorrect" models where reasoning quality degrades [source-31f3eff95574].

### 2.5 Bayesian / Ensemble / Proxy-Model Approaches

- **BayesPE** (Tonolini et al., ACL Findings 2024) [source-08d914b3f29c] — Bayesian prompt ensemble; variational inference over prompt variants approximates a Bayesian input layer.
- **Surrogate / proxy models** [source-9a967cf55c60] — train a smaller accessible model to predict the black-box LLM's confidence.
- **DisAAD** [source-d62d9cf02938] — adversarial distillation into a lightweight proxy plus evidential deep learning; enables single-pass uncertainty from a proxy of ~4% of target parameters.
- **UniCR** [source-9047b8571348] — unified post-hoc framework fusing self-consistency dispersion, retrieval compatibility, and verifier/tool feedback through a small calibration head, with **conformal risk control** for distribution-free coverage guarantees. Reports 18–35% ECE reduction over vanilla temperature scaling and 7–12% over Dirichlet calibration.

---

## 3. Empirical Rankings: What Actually Works Best

### Calibration (ECE)
1. **Training-based hybrid (SaySelf, UaIT)** — best absolute ECE. SaySelf ECE ≈ 0.27–0.39 vs. direct prompting ≈ 0.38–0.67 on HotpotQA [source-b9deccfb8752].
2. **Verbalized prompting with strong prompt design** (Top-K, combo prompts, probability-framing) — for large RLHF models (70B+), combo prompts achieve ~7% average ECE deviation from accuracy [source-9a967cf55c60]. Tian et al. show verbalized beats token log-probs by ~50% ECE for ChatGPT/GPT-4/Claude-2 on TriviaQA, SciQ, TruthfulQA [source-a3be8a933ba7].
3. **UniCR / CoCoA hybrid calibration** — reduce ECE 18–35% over temperature scaling [source-9047b8571348, source-9292120a578a].
4. **Vanilla verbalized** — worst; ECE > 0.25 common.

### Failure Prediction (AUROC)
1. **Training-based hybrid (SaySelf)** — AUROC 0.61–0.73 vs. self-consistency 0.42–0.58 on its benchmarks [source-b9deccfb8752].
2. **Sampling + consistency aggregation** — Xiong et al. show dramatic gains: GSM8K AUROC jumps from 54.8% (random) to **92.7%** when using self-consistency at M=5 with Avg-Conf aggregation [source-60d0f7a54402].
3. **SNNE / pairwise semantic similarity** — AUROC ~0.83–0.84 on QA for LLaMA-3.1-8B and Phi-3-mini [source-4d25bbb9aff6], though a separate Bradley-Terry meta-ranking places KLE higher and SNNE sixth [source-d7c30b31697d] — rankings are benchmark-sensitive.
4. **2-sample SCVC hybrid** (reasoning models) — 2 samples of verbalized-confidence + self-consistency outperforms 8-sample single-signal methods on math (AUROC 84 vs. VC@8 of 81) [source-e373b96e46ec].
5. **Vanilla verbalized** — often near-random (AUROC ~0.51–0.63).

### Settings Where a Particular Family Dominates

| Setting | Best family |
|---|---|
| RLHF-tuned large model, ECE-critical | Verbalized prompting with Top-K / combo prompts [source-a3be8a933ba7] |
| Arithmetic / reasoning, AUROC-critical | Self-consistency (M≥5) with Avg-Conf aggregation [source-60d0f7a54402] |
| Short-form QA, hallucination detection | Semantic entropy / SNNE [source-4d25bbb9aff6] |
| Reasoning LLMs, budget = 2 calls | SCVC hybrid [source-e373b96e46ec] |
| Fine-tuning permitted | SaySelf or UaIT [source-b9deccfb8752, source-30e5f8c2d098] |
| RAG with retrievers / agents with tools | UniCR (multi-evidence fusion) [source-9047b8571348] |
| Systematic-error domains (medical, specialized) | External grounding required; no intrinsic method suffices [source-3c982b0e793b] |
| Small models (<10B) | Simple probability-framing verbalization; complex methods degrade performance [source-9a967cf55c60] |

---

## 4. The Overconfidence Problem — and Why Reasoning-Model Calibration Gains Deserve Skepticism

The overconfidence finding is overdetermined. Across GPT-4, GPT-3.5, LLaMA-2, PaLM-2, Gemma, Qwen, Llama-3 and VLMs, verbalized confidence clusters in the 80–100% band, and for the smallest models confidence is *nearly independent of accuracy* [source-9a967cf55c60]. The **Xiong et al. framework** (ICLR 2024) [source-60d0f7a54402] and the **NCE evaluation** [source-7d72d380ec9d] both report this as the universal pattern. Whether verbalized confidence is *faithful* to internal decision states remains an open mechanistic question [source-5897f9d7144b].

### Mitigations that work
- **Top-K answer elicitation** reliably improves calibration (ECE 0.23 → 0.065 on SciQ with ChatGPT Verb.1S top-4) [source-a3be8a933ba7].
- **Combo prompting** (probability framing + advanced description + few-shot) on large models [source-9a967cf55c60].
- **Post-hoc recalibration** (temperature scaling, histogram binning, isotonic regression) with a held-out calibration set [source-e923709cef65, source-bef04c600d8c].
- **Steering prompts (SteerConf)** bracket confidence estimates with conservative/optimistic elicitations [source-cc4907b4075e].
- **Training-based** (SaySelf, CSFT, Rewarding Doubt) — strongest and most consistent.

### Mitigations that *don't* work as advertised
- **Standard CoT prompting** applied to non-reasoning models does not improve verbalized calibration [source-a3be8a933ba7].
- **Complex prompt schemes on small models (<10B)** actively *degrade* calibration [source-9a967cf55c60].

### The reasoning-model calibration debate

The pro-case is real: Yoon et al. 2025 [source-5427248b02fe] show reasoning models beat non-reasoning counterparts on calibration in 33/36 settings, and the "Two Samples Are Enough" work [source-e373b96e46ec] shows a 2-sample SCVC hybrid in reasoning models outperforms 8-sample single-signal methods.

But adversarial evidence imposes hard caveats that belong in any honest recommendation:

1. **Persistent overconfidence floor**: Even Yoon et al. concede that reasoning models "assign values below 55% infrequently" — meaning they cannot express genuine low-confidence uncertainty. On tasks where true accuracy is ~50%, this is severe miscalibration.
2. **Accuracy confounding and implicit answer conditioning**: Causal masking experiments in VLMs show that as reasoning traces converge on an answer, token confidences inflate *independently of whether the answer is correct* — the model "talks itself into" its answer. Masking answer-mentions from reasoning traces restores uncertainty quality *without changing accuracy*. If this mechanism transfers to text reasoning models (architecturally similar), reasoning-model "calibration gains" are partly mechanical.
3. **Breakdown on genuine forecasting**: On KalshiBench (prediction markets, future outcomes that cannot be memorized), GPT-5.2 with extended reasoning produced the **worst** calibration of tested frontier models (ECE 0.395, negative Brier skill), while standard-reasoning Claude Opus 4.5 achieved ECE 0.12. Scaling reasoning does not automatically produce calibration under genuine epistemic uncertainty.
4. **SCVC domain-concentration**: The +12.9 AUROC hybrid gain on math drops to +6.4 on STEM/humanities; on diverse long-form tasks, SCVC AUROC averages ~0.58 versus ~0.72 for cross-model epistemic+aleatoric total uncertainty. The 2-sample recipe is *not* a universal shortcut — it is a math/reasoning-domain shortcut.
5. **Self-consistency collapse**: The core failure mode from §2.2 applies *a fortiori* — when a reasoning model is confidently wrong (easy in out-of-domain settings), SC and VC agree and SCVC compounds both overconfident signals.

**Practical implication**: Reasoning-model calibration is real but bounded. For math/code/logical reasoning with extended-CoT models, SCVC at 2 samples is an excellent cheap default. For high-stakes genuinely-uncertain forecasting, use UniCR-style multi-evidence fusion or cross-model disagreement, and be explicit that models rarely express sub-55% confidence.

---

## 5. Practical Recommendations

The following recipe ladder integrates the ICLR 2024 benchmark, the SCVC finding, and the adversarial constraints above.

### Rung 1 — Cheapest usable default (1 API call)
**Top-K verbalized prompting** (ask for K=4 candidate answers each with a probability). For large RLHF models, this is the single biggest-bang-per-buck intervention: it roughly halves ECE versus simple "state your confidence" prompting [source-a3be8a933ba7]. Apply post-hoc temperature scaling if you have a small calibration set.

### Rung 2 — Budget-efficient strong default (2 API calls, reasoning models)
**SCVC hybrid**: generate two samples, combine their pairwise consistency with their mean verbalized confidence [source-e373b96e46ec, source-0ac03b4c6b66]. Best-known cost/performance tradeoff for reasoning LLMs on math/STEM. Degrades on humanities and on long-form generation — do not treat as a universal recipe.

### Rung 3 — Strong general-purpose black-box (5 samples)
**Xiong et al.'s Top-K + Self-Random sampling + Avg-Conf (or Pair-Rank) aggregation** [source-60d0f7a54402]. Empirical AUROC 0.66–0.87 on GPT-4, with GSM8K AUROC jumping from 0.55 to 0.93 versus verbalized alone. Still cheap enough for many production settings.

### Rung 4 — Hallucination-detection-grade (5–10 samples)
**Semantic entropy** (discrete variant for pure black-box) [source-4d25bbb9aff6] or **SNNE** for longer outputs. Best for flagging answers likely to be fabrications. 5–10× compute overhead.

### Rung 5 — Best calibration when you can fine-tune
**SaySelf** (SFT on self-reflective rationales + PPO with quadratic confidence reward) [source-b9deccfb8752]. Best reported ECE and AUROC; distinguishes answerable from unanswerable questions better than any alternative. Requires model weights and compute. If constructing SaySelf-style data is infeasible, **UaIT** [source-30e5f8c2d098] is a simpler alternative that fine-tunes on sampling-based uncertainty labels.

### Rung 6 — Calibration-critical production deployment
**UniCR** [source-9047b8571348] with black-box-mode features (drop logit features; keep self-consistency dispersion, retrieval compatibility, verifier feedback), calibration head, and conformal risk control for distribution-free coverage guarantees.

### Cross-cutting guidance
- If you suspect your model has **systematic errors** in your domain (medical, legal, specialized technical), no intrinsic consistency/verbalized method is sufficient. Supplement with external grounding: retrieval compatibility, tool/verifier feedback, or cross-model semantic disagreement [source-3c982b0e793b, source-9047b8571348].
- For **small models (<10B)**, prefer the simplest probability-framing prompt; skip complex schemes, which degrade performance [source-9a967cf55c60].
- For **long-form generation**, prefer semantic entropy with pairwise extensions (SNNE) over verbalized confidence; verbalized scores are unreliable for multi-paragraph outputs [source-4d25bbb9aff6, source-9047b8571348].
- For **high-stakes decisions**, pair any single method with conformal risk control or an abstention policy; do not rely on point estimates of confidence.

---

## 6. Limitations and Open Problems

**Unsolved or under-studied in the current corpus:**
- **Long-form / open-ended generation.** Most benchmarks are short-form QA or mathematics; calibration on synthesis, creative writing, and multi-paragraph factual text is thinly characterized.
- **Professional-knowledge domains.** Xiong et al. report near-random AUROC for all methods on law/medicine MMLU. The medical-diagnosis comparator [source-40d0b245ccd6] was inaccessible in this investigation.
- **Agentic and multi-turn dialogue settings.** Essentially absent from the reviewed literature.
- **Small-model black-box UQ.** Complex methods degrade; simple verbalization is unreliable. No clean solution.
- **RAG-specific calibration.** Only UniCR and a few others explicitly model retrieval compatibility as a confidence signal.
- **Faithfulness.** Whether verbalized confidence reflects genuine epistemic state or post-hoc rationalization remains a live mechanistic question [source-5897f9d7144b].

**Evidence quality notes.** Core claims rest on peer-reviewed work (EMNLP 2023/2024, ICLR 2024, ACL 2025, *Nature* 2024 for semantic entropy). The SCVC 2-sample recipe [source-e373b96e46ec] and UniCR [source-9047b8571348] are 2025 preprints without peer-review validation; the adversarial evidence against reasoning-model calibration (KalshiBench, Implicit Answer Conditioning) is also preprint-stage. The ACM and KDD 2025 surveys ([source-a55e2dd149ec], [source-f1e47aefa624]) and the systematic evaluation [source-92af08983340] were not fully accessible; their aggregate rankings would be a useful cross-check.

---

## 7. Summary Table

| Method | Type | Samples | Black-box? | Best at | Key reference |
|---|---|---|---|---|---|
| Direct verbalized | Prompting | 1 | Yes | Simple deployment | [source-a3be8a933ba7] |
| Top-K verbalized | Prompting | 1 | Yes | Cheap ECE reduction | [source-a3be8a933ba7] |
| SteerConf | Prompting | ~3 | Yes | Conservative/optimistic steering | [source-cc4907b4075e] |
| SelfCheckGPT | Consistency | 5–10 | Yes | Hallucination detection | [source-192a0d82b6ff] |
| Semantic entropy | Consistency | 5–10 | Yes (discrete variant) | Short-form QA hallucination | Farquhar *Nature* 2024 |
| SNNE | Consistency | 5–10 | Yes | Long-form UQ | [source-4d25bbb9aff6] |
| CoCoA / MBR | Hybrid | 5–10 | Partial | General UQ; best ECE | [source-9292120a578a] |
| Avg-Conf / Pair-Rank | Hybrid | 5 | Yes | General AUROC | [source-60d0f7a54402] |
| SCVC (2-sample) | Hybrid | 2 | Yes | Reasoning-model math/STEM | [source-e373b96e46ec] |
| Reasoning-model CoT | Prompting | 1 | Yes | Native calibration in math/code | [source-5427248b02fe] |
| EDTR (topological CoT) | CoT | 5–10 | Yes | CoT path analysis | [source-2450e587f851] |
| BayesPE | Bayesian | K prompts | Yes | Classification UQ | [source-08d914b3f29c] |
| DisAAD | Proxy | 1 (proxy) | Yes | Single-pass proxy UQ | [source-d62d9cf02938] |
| UniCR | Framework | 3–5 | Yes | Risk-controlled selective generation | [source-9047b8571348] |
| SaySelf | Training | 1 | No (fine-tune) | Best ECE+AUROC | [source-b9deccfb8752] |
| UaIT | Training | 1 | No (fine-tune) | Simpler training alternative | [source-30e5f8c2d098] |
| CSFT | Training | 1 | No (fine-tune) | Emergent self-verification | [source-31f3eff95574] |
| Rewarding Doubt | Training | 1 | No (fine-tune) | RL calibration | [source-675839e952b6] |

