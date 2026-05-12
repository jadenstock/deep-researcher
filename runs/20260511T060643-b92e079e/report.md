# Research report

**Query:** What are the real-world risks and benefits of using synthetic data to train or fine-tune large language models? Focus on data quality, bias, and evaluation.

# Synthetic Data for LLM Training and Fine-Tuning: Real-World Risks and Benefits

## Takeaway

Synthetic data has moved from a workaround for data scarcity to a core ingredient of frontier LLM training, with documented, sizable benefits on reasoning tasks when paired with disciplined quality pipelines — most visibly in Microsoft's Phi series, where synthetic-heavy training let a 14B model surpass its teacher (GPT-4) on several STEM benchmarks [source-ca2d5084ee1e]. But the benefits are conditional and narrow: synthetic data consistently degrades factual-knowledge benchmarks, inherits and amplifies biases from its generator, and — in the evaluation stack — corrupts LLM-as-judge pipelines through preference leakage and style/leniency bias that can silently inflate reported performance [source-a9eb9eddb24f, source-9002dfacbaf4]. The headline risk of "model collapse" is genuine but setup-dependent: catastrophic collapse requires the unrealistic "replace" paradigm, while subtler harms (tail-loss, knowledge collapse, scaling-law degradation at even 1/1000 synthetic fractions) remain plausible production risks [source-0e0d31b0f365, source-c1871dd26bc5, source-b2e65b22a105]. The practical implication for practitioners: synthetic data is a powerful tool, but one that demands multi-source generation, real-data accumulation, explicit fairness auditing, and human-grounded evaluation — none of which are current industry defaults.

---

## 1. Benefits: Where Synthetic Data Demonstrably Helps

### 1.1 Reasoning uplift and compute efficiency (well-evidenced)

The clearest wins come from reasoning-focused pre-training and fine-tuning:

- **Phi-4 (14B)** "substantially surpasses its teacher model [GPT-4] on STEM-focused QA capabilities" with GPQA 56.1 vs. GPT-4o's 50.6 and MATH 80.4 vs. 79.1 [source-ca2d5084ee1e]. The authors explicitly note this "go[es] beyond distillation."
- **Phi-3-mini (3.8B)** matches Mixtral 8x7B and GPT-3.5 on MMLU (69%) and MT-bench (8.38) despite being ~10× smaller [source-ca2d5084ee1e].
- **Phi-2 (2.7B)** matched models "25 times larger trained on regular data" [source-ca2d5084ee1e].
- A large-scale Meta/Virginia Tech study (>1,000 LLMs, >100,000 GPU hours) found that **1/3 rephrased synthetic data mixed with 2/3 natural web text speeds up pre-training convergence by 5–10×** at larger data budgets [source-5de83541d32a].

The structural reason synthetic data helps with reasoning: LLM-generated text is by construction more coherent token-to-token, and its style matches the chat/instruction contexts in which models are later used, rather than the stylistic mismatch of web forums [source-ca2d5084ee1e].

### 1.2 Other benefits

- **Reduced toxicity**: Phi-1.5's textbook-style synthetic training produces "significantly fewer failures" on adversarial prompts versus Llama2-7B and Falcon-7B [source-ca2d5084ee1e].
- **Coverage of rare/edge cases** and **privacy-constrained domains** (healthcare, finance) where real data is sparse or legally restricted [source-cd2e9f9e2c1d, source-290ccae1992a].
- **Controlled difficulty and balanced demographics**, in principle — though see §3 on how often this promise fails in practice.

### 1.3 The quality-pipeline practices that determine whether benefits are realized

Benefits do not come from synthetic data per se; they come from the surrounding pipeline. Convergent findings across sources:

| Practice | Evidence |
|---|---|
| **Diversity of seeds, styles, and generator models** is the strongest single predictor of gains [source-43fde020e0b2, source-c15f9240fd5d] | LLM cluster-diversity scores correlate positively with both pre-training and SFT performance across 350M–1.4B models [source-43fde020e0b2] |
| **Multi-stage filtering** (educational-value classifiers, n-gram/compression checks, answer validation) | Phi-4's pipeline; "clean and correct natural data is absolutely crucial for seeding synthetic data" [source-ca2d5084ee1e] |
| **Execution-based validation for code**; majority-vote answer validation for Q&A | Phi-4 [source-ca2d5084ee1e] |
| **Decontamination against benchmarks** — including semantic (not just n-gram), since rephrasing defeats token-level checks | [source-cd2e9f9e2c1d, source-ca2d5084ee1e]; Phi-4 used post-cutoff AMC problems as out-of-sample validation |
| **Optimal mixture: ~30–40% synthetic, not 100%** | Meta: "optimal mixture is consistently 30% HQ synthetic data with 70% CommonCrawl"; Phi-4: 40% [source-5de83541d32a, source-ca2d5084ee1e] |

A counter-intuitive finding: **larger generator models do not reliably produce better synthetic data**. Llama-3-70B as a rephrasing generator produced "consistently worse evaluation results" than Llama-3-8B [source-5de83541d32a]. Above a minimum capability threshold, diversity and prompt design dominate raw generator size.

### 1.4 Where benefits plateau or reverse

- **Factual/knowledge benchmarks degrade under synthetic-heavy training.** Phi-4 ablations: a 13B model trained *only* on synthetic data lost 14.8 points on TriviaQA relative to phi-3-medium; the team explicitly states "models trained only with synthetic data underperformed on the knowledge-heavy benchmarks and demonstrated increased hallucinations" [source-ca2d5084ee1e].
- **Scaling plateaus** appear in math around 300B synthetic tokens [source-5de83541d32a].
- **Organic questions outperform synthetic questions** for Q&A tasks — synthetic data works best as *elaboration/augmentation* of a human-written core, not as a wholesale replacement [source-ca2d5084ee1e].

---

## 2. Data Quality Risks: Model Collapse and Hallucination Propagation

This is the most-theorized risk area. There is genuine disagreement between researchers on how much it matters in production — and the final report should carry both sides.

### 2.1 The foundational concern (Shumailov et al., *Nature* 2024)

The landmark peer-reviewed finding is that recursive training on synthetic data causes "a degenerative process ... in which the data [models] generate end up polluting the training set of the next generation," producing **irreversible defects** where "tails of the original content distribution disappear" [source-0e0d31b0f365]. Three compounding errors drive this: statistical approximation (finite samples lose rare events), functional expressivity (model capacity limits), and functional approximation (training biases). Theorem 3.1 proves that in the Gaussian case the process collapses to zero variance with probability 1.

### 2.2 Knowledge collapse: the "confidently wrong" stage

A NeurIPS 2025 workshop paper sharpens the risk with a three-stage framework [source-b2e65b22a105]:
- **Stage A**: Knowledge preserved, instructions followed.
- **Stage B** (the dangerous one): **Factual accuracy deteriorates while task-format adherence persists** — producing fluent, well-formatted, confidently wrong outputs. The paper calls this the "valley of dangerous competence" where "traditional quality metrics fail to detect underlying knowledge erosion."
- **Stage C**: Full incoherence.

Concretely: a GEMMA 3 1B IT model maintained a correct MMLU answer through Generation 4, then flipped to a wrong answer with token probability ~0.94 (high confidence) by Generation 6.

### 2.3 Quantitative hallucination risk

One mixed-methods study reports synthetic data increases hallucination rates **4.7×** (with 22% of NLP outputs containing factual mistakes and 3.7% of healthcare outputs containing clinically dangerous errors) [source-de3d33d51d05]. **Single-source caveat**: this paper is from a lower-prestige venue and has not been independently replicated; treat the 4.7× figure as suggestive, not canonical.

### 2.4 Mitigation evidence: the "accumulate, don't replace" finding

A counter-line of research argues catastrophic collapse is avoidable in realistic settings:

- **Gerstgrasser et al. (COLM 2024)**: Replacing real data with synthetic → collapse; *accumulating* synthetic alongside real data → no collapse, with test error provably bounded [source-0e0d31b0f365 context].
- **"Escaping Collapse"**: even weak real-data signal injection prevents collapse and enables arbitrarily high accuracy [source-62af0f35f4ef, source-499dc62022e8].
- **Schaeffer et al. position paper**: many collapse papers assume "data are entirely deleted after each model-fitting iteration" — unrealistic; under accumulation, "total/catastrophic collapse" is "virtually no present threat."
- **Phi-4 empirics**: after 12 training epochs on rich data, "we do not see overfitting behavior" [source-ca2d5084ee1e].

### 2.5 The adversarial case: why production risk is still real (engaged, not dismissed)

An adversarial investigation challenges the comforting narrative on five specific grounds:

1. **Tiny fractions can matter.** Dohmatob et al. (ICLR 2025) show that even **1-in-1000 synthetic fractions** can degrade scaling laws — "larger and larger training sets do not enhance performance" — and that this effect persists as long as the synthetic fraction does not vanish [source-c1871dd26bc5]. Modern pipelines cannot credibly guarantee vanishing synthetic fractions.
2. **Web contamination is pervasive and unlabeled.** Shumailov et al. themselves warn that "it is unclear how content generated by LLMs can be tracked at scale" [source-0e0d31b0f365]. Contamination surveys echo this, describing exact tracing of web-scale pretraining data as "challenging — if not impossible" [source-485873c79f03].
3. **Stage B is undetectable by standard metrics.** Fluency and perplexity do not catch it; production monitoring of user satisfaction will not either [source-b2e65b22a105].
4. **Filtering isn't reliable separation.** Curation surveys acknowledge LLMs "can hardly be self-aware of the bias in their generated data" and that synthetic corpora often contain "noisy, worthless, or even toxic samples" [source-e580cf178098]. Watermarking/provenance (SynthID, NIST AI 100-4) exists but has not achieved broad web-platform adoption.
5. **Long-tail harms hide behind aggregate metrics.** The Fairness Feedback Loops study found synthetic-data-driven distribution shift produced "complete erasure of the minoritized group" in one setup, while evaluators scoring against the model's own labels saw "nearly 100% accuracy and near-perfect fairness" [source-39e14efe7c3d].

**Net assessment**: Catastrophic "replace-paradigm" collapse is largely a lab construct. But **production-relevant degradation — tail loss, knowledge collapse, scaling-law degradation at tiny synthetic fractions, and disproportionate harm to minority subgroups — is credibly a current production risk** that most monitoring regimes are not designed to detect.

---

## 3. Bias: Inheritance, Amplification, and Demographic Gaps

### 3.1 Bias inheritance is empirically systematic

The first systematic study of bias inheritance (Llama-3.1-8B across 10 tasks) found that biased augmentation data "consistently improves the performance for majority groups (male) while decreasing the performance for minority groups (female)" regardless of bias type or ratio, and that the effect **compounds over iterative training rounds**: in salary recommendation, predicted male salaries rise while female salaries fall, widening the gap with each iteration [source-9002dfacbaf4].

Three misalignment factors drive this: value misalignment (synthetic text diverges from human values, especially for non-Western cultures), group-data misalignment (unbalanced demographic representation without explicit balancing mechanisms), and distributional misalignment in feature space [source-9002dfacbaf4].

### 3.2 Bias amplification is mechanistically distinct from model collapse

A mechanistic analysis of GPT-2 fine-tuning identified **3,243 neurons significantly correlated with bias performance changes versus only 1,033 with generation quality, with just 389 in overlap** [source-1fbc7d6071c0]. The implication: **mitigations for model collapse (like real-data preservation) do not automatically mitigate bias amplification**. They are separate problems requiring separate interventions.

### 3.3 Demographic harms, documented

- **Gender**: synthetic data with biased augmentation widens pay-gap and hiring-rate disparities [source-9002dfacbaf4]; GPT-3.5 recommendation letters use more agentic terms for men [source-19c765a9e49a].
- **Race**: GPT-3.5-turbo predicts higher healthcare costs for white patients 18–27% more often than Black/Asian; lower mortality predictions for white (56.9%) vs. Black (61.3%), Asian (57.9%), Hispanic (59.4%) patients; race-linked diagnosis stereotypes (HIV, tuberculosis) [source-cdeda92966ba, source-290ccae1992a references cited in analyst work].
- **Culture**: misalignment is more severe for Eastern (Arabic, Chinese) than Western cultures [source-9002dfacbaf4].
- **Intersectionality**: bias in one axis (gender) can propagate to others (culture); minoritized-group erasure has been empirically observed [source-39e14efe7c3d].

A peer-reviewed systematic review of 24 medical-LLM studies found bias in **91.7% of studies**, with gender bias in 93.7% and racial/ethnic bias in 90.9%. A "recent survey of FDA-approved AI clinical decision support tools found none included a bias evaluation" — a regulatory gap [source-cdeda92966ba references in analyst citations; source-290ccae1992a].

### 3.4 Generator diversity: partial mitigation with its own trade-offs

Multi-source synthetic data (generators from 12 different models, 7B–685B) partially mitigates distribution collapse: "fine-tuning on synthetic data from diverse sources can mitigate distribution collapse, preserving the breadth of the output distribution" [source-c15f9240fd5d]. Benefits scale with iteration count and model size.

But there are trade-offs:
- Multi-source synthetic data from *large* (70B+) generators can **increase adversarial vulnerability** — conflicting alignment signals across generators weaken safety behavior [source-c15f9240fd5d].
- Single-source data actually has *lower* self-preference bias than multi-source in some settings [source-c15f9240fd5d].

### 3.5 Evaluation inflation masks bias harms

A critical production concern: when models are evaluated against labels produced by *their own predecessors* rather than ground truth, results show "nearly 100% accuracy and near-perfect fairness" even while actual group-level performance collapses [source-39e14efe7c3d]. This means standard ML-ops monitoring practices can entirely miss progressive fairness degradation.

### 3.6 What mitigations actually work

| Mitigation | Evidence | Notes |
|---|---|---|
| Mix real+synthetic | Strong [source-0e0d31b0f365, source-39e14efe7c3d] | Necessary but not sufficient for bias |
| Multi-source generators | Strong [source-c15f9240fd5d] | Trade-off with adversarial robustness at large generator sizes |
| Stratified sampling (STAR) | Moderate [source-39e14efe7c3d] | Reduces DP/EOdds gaps; limited when generator itself biased |
| Prompt engineering (medical) | Moderate [source-cdeda92966ba refs] | 6/7 studies reduced disparities |
| Debiasing algorithms (PCA, task-specific) | Moderate | 63.9% gender-bias reduction in BERT |
| Bias-aware fine-tuning flags | Mixed [source-9002dfacbaf4] | Works for simple biases; fails on cultural generation |
| Fairness audits alone | Insufficient | Necessary but don't address root cause |

**No unified mitigation** has been validated across all bias types, tasks, and groups [source-9002dfacbaf4].

---

## 4. Evaluation: The LLM-as-Judge Closed Loop

When the same (or related) models generate synthetic training data *and* judge the resulting models, the evaluation pipeline itself becomes contaminated. This is arguably the most under-appreciated risk for practitioners because it affects the metrics they rely on to know whether their training worked.

### 4.1 Self-preference bias has a clear mechanism

GPT-4 "exhibits a significant degree of self-preference bias"; LLMs "assign significantly higher evaluations to outputs with lower perplexity than human evaluators, *regardless of whether the outputs were self-generated*" [source-136b7b1cfbe6]. The mechanism is familiarity: judges prefer text that looks like what they would produce. This means inflation can occur even without a direct generation–evaluation lineage.

Important nuance: self-preference is **not universal**. In a 5-judge study, Gemini Flash showed strong self-preference, GPT-4o actually preferred Claude's responses, and Llama 3.3-70B showed near-zero self-preference [source-01373c856da4]. Practitioners should measure it for their specific judge, not assume.

### 4.2 Preference leakage: the more subtle problem (verify: SUPPORTED)

Preference leakage — when generator and judge are in the same family or lineage — is a distinct and more insidious contamination problem formalized in an ICLR 2026 paper [source-a9eb9eddb24f]:

- **Same model used for both**: Preference Leakage Score ~23.6% (SFT setting)
- **Inheritance relationship** (one fine-tuned from the other): ~22.3%
- **Same family** (e.g., GPT-4o data / GPT-4-turbo judge): ~8.9%
- **Different series within family**: ~2.8%

Smaller student models are more affected (they pick up surface-level stylistic features readily). Subjective tasks (writing, programming) show PLS 21–31%; objective math only ~7.7%. Crucially, **the judge cannot reliably detect when an output came from its own related student** (recognition accuracy ~random), though an external BERT classifier reaches 82.4% — meaning stylistic fingerprints exist but are opaque to the LLM judge itself [source-a9eb9eddb24f].

**Independent verification** (dispatched): the core preference-leakage thesis is independently supported by (a) self-preference research showing systematic familiarity-based inflation [source-136b7b1cfbe6]; (b) verifiable-task studies confirming "harmful self-preference persists when evaluator models err as generators" [source-3fa4705117e3]; (c) evaluator-entanglement work showing "shared pretraining data, distillation, and alignment pipelines can induce hidden behavioral dependencies" such that apparent cross-judge agreement may reflect "correlated failure rather than independent verification" [source-402bdebc8bc8]; and (d) bias benchmarks calling for "separate models for answer generation and evaluation" [source-01373c856da4]. The exact ~23.6% magnitude remains single-source to [source-a9eb9eddb24f], but the phenomenon itself is well-replicated in substance.

This matters because prominent benchmarks — including **AlpacaEval 2.0 and Arena-Hard** — routinely use GPT-4 for both data synthesis and judging [source-a9eb9eddb24f].

### 4.3 Style bias dominates other judge biases

A systematic 5-model, 3-benchmark study found **style bias magnitude of 0.76–0.92** (markdown vs. plain-prose preference for identical content) across GPT-4o, Claude Sonnet 4, Gemini Pro/Flash, and Llama [source-01373c856da4]. This exceeds all other measured biases. Implication: win-rates on AlpacaEval/Chatbot Arena may be significantly driven by *formatting differences*, not content quality.

### 4.4 Leniency inflates absolute metrics

LLM judges show **TPR 96% but TNR <25%** — they reliably accept valid outputs but fail to reject invalid ones [source-dba1a731863b]. The effect: systematically inflated performance scores. Simple majority voting is insufficient; regression-based calibration outperforms it 2× in tested domains [source-a09349d21708 context].

### 4.5 Position bias — contested

Two well-evidenced studies disagree. [source-01373c856da4] finds position bias is now negligible in modern frontier judges; another large-scale 15-judge study finds substantial residual variability (Claude-3-Haiku shows 57% position consistency on DevBench) [source-01373c856da4, source-dba1a731863b context]. The most likely reconciliation: position bias is small when quality gaps are large but re-emerges when candidates are close in quality.

### 4.6 Benchmark contamination compounds

Synthetic rephrasing of benchmark questions defeats standard n-gram decontamination. Even LLM-generated dynamic benchmarks like LatestEval have 10% of samples failing human audit on faithfulness or answerability [source-485873c79f03]. When a judge LLM was trained on data similar to the benchmark, it may recognize and favor similar-looking responses — compounding preference leakage with benchmark contamination.

### 4.7 Mitigations with the strongest evidence

| Mitigation | Evidence | Notes |
|---|---|---|
| **Human-grounded (correct) references** | **Strongest** [source-dba1a731863b] | Qwen 2.5 7B + human refs beats GPT-4o + synthetic refs. Correctness, not humanness, is the key — 35% of GPT-4-generated MT-Bench references were wrong. |
| **Contextual calibration** (adjust scores using held-out human-labeled set) | Strong [source-a9eb9eddb24f] | Reduced Error Bias from 17.8 to 7.3 — most effective mitigation for preference leakage |
| **Chain-of-thought forcing** | Moderate [source-01373c856da4] | Only universally beneficial debiasing strategy across 5 models and both benchmark types |
| **DPO instead of SFT** | Moderate [source-a9eb9eddb24f] | PLS of 5.2% vs. 23.6% — less surface-pattern memorization |
| **ICL instead of SFT** | Moderate [source-a9eb9eddb24f] | Near-zero PLS because ICL doesn't update weights |
| **Cross-family judge panels** | **Mixed — not a silver bullet** | Reduces preference leakage empirically, but [source-402bdebc8bc8] warns that apparently diverse models may share latent dependencies through shared pretraining/distillation |
| **Formatting normalization** | Recommended [source-01373c856da4] | Given style bias dominates (0.76–0.92) |

---

## 5. Synthesis: What This Means for Practitioners

### Where synthetic data is a net positive
- **Reasoning-heavy training** with Phi-style pipelines: disciplined seed curation, multi-stage filtering, 30–40% mixture with real data, diverse generators, and execution/answer validation. Empirically, this can let smaller models match or exceed much larger ones on reasoning benchmarks [source-ca2d5084ee1e, source-5de83541d32a].
- **Targeted augmentation** of rare cases in domains where real data is scarce or restricted — *provided* generator-model biases are audited at the demographic level [source-cdeda92966ba, source-290ccae1992a].
- **Compute efficiency**: 5–10× convergence speedup with proper mixing [source-5de83541d32a].

### Where synthetic data creates real risk
- **Knowledge-intensive evaluation**: synthetic-heavy training degrades factual recall (TriviaQA −14.8 points, Phi-4 team's own ablation) [source-ca2d5084ee1e].
- **Bias-sensitive applications** (hiring, healthcare, legal, finance): biased generators reliably propagate and amplify bias; ~92% of medical LLM studies find bias; FDA-approved clinical AI tools lack bias evaluations [source-9002dfacbaf4, source-cdeda92966ba].
- **Evaluation via same-family LLM judges**: systematically inflates reported metrics through preference leakage (~23.6% PLS), style bias (0.76–0.92), and leniency (TNR <25%) [source-a9eb9eddb24f, source-01373c856da4, source-dba1a731863b].
- **Undetected long-tail erosion**: aggregate metrics can look healthy while minority-subgroup performance collapses [source-39e14efe7c3d].

### The five non-negotiables that emerge from the evidence
1. **Always accumulate real data alongside synthetic.** Pure recursive training provably collapses [source-0e0d31b0f365]; accumulation with 30–40% synthetic mixture is the empirical sweet spot [source-5de83541d32a, source-ca2d5084ee1e].
2. **Use multi-source generators** (but audit for adversarial robustness trade-offs at large generator sizes) [source-c15f9240fd5d].
3. **Audit bias at the demographic subgroup level** — aggregate metrics will hide the problem [source-39e14efe7c3d, source-9002dfacbaf4].
4. **Do not use same-family LLM judges** for headline evaluation; when using LLM judges, ground them in verified-correct human references and apply contextual calibration [source-dba1a731863b, source-a9eb9eddb24f].
5. **Decontaminate semantically, not just by n-gram**, and validate on truly post-cutoff data [source-ca2d5084ee1e, source-485873c79f03].

---

## Disagreements Surfaced in the Investigation

- **Model collapse severity in production.** Shumailov et al. and Dohmatob et al. argue that even tiny synthetic fractions (1/1000) degrade scaling laws [source-0e0d31b0f365, source-c1871dd26bc5]; Gerstgrasser et al. and Schaeffer et al. argue that accumulation makes catastrophic collapse a non-issue in realistic pipelines. The reconciling view: catastrophic collapse is largely lab-artifact; *subtle* tail/knowledge/scaling-law degradation is a real production risk.
- **Generator size for quality.** Intuition says bigger generators make better data; empirics show Llama-3-70B can underperform Llama-3-8B for rephrasing [source-5de83541d32a].
- **Position bias status.** [source-01373c856da4] says it's negligible in current frontier judges; other large-scale studies find substantial residual variability.
- **Verbosity bias direction.** Older models preferred longer outputs; current frontier judges appear to prefer concise responses — suggesting classic mitigation advice may now be counterproductive [source-01373c856da4].
- **Alignment's interaction with bias.** Biased augmentation of GPT-4o-mini sometimes *favored* underrepresented groups (increased female salaries), suggesting alignment training can invert expected bias-inheritance direction in unpredictable ways [source-9002dfacbaf4].
- **Cross-family judges as mitigation.** Supported by some work [source-a9eb9eddb24f, source-01373c856da4]; undermined by evaluator-entanglement findings that models sharing pretraining/distillation roots can still share latent behavioral dependencies [source-402bdebc8bc8].

---

## Evidence Basis

Strongest evidence (peer-reviewed Tier 1):
- Phi-4 Technical Report [source-ca2d5084ee1e] — detailed ablations
- Shumailov et al., *Nature* [source-0e0d31b0f365] — foundational model collapse
- Cheng et al., Preference Leakage, ICLR 2026 [source-a9eb9eddb24f]
- Dohmatob et al., ICLR 2025 strong model collapse [source-c1871dd26bc5]
- Systematic review of medical LLM bias [source-cdeda92966ba context, source-290ccae1992a]

Tier 2 preprints with strong methodology:
- Bias inheritance (Llama-3.1, 10 tasks) [source-9002dfacbaf4]
- Multi-source diversity [source-c15f9240fd5d]
- Fairness feedback loops [source-39e14efe7c3d]
- Style/position bias systematic study [source-01373c856da4]
- Human-grounded judging [source-dba1a731863b]
- Meta/VT large-scale scaling study [source-5de83541d32a]

Single-source or less-replicated claims (flagged accordingly):
- "4.7× hallucination rate increase" [source-de3d33d51d05] — single paper, lower-prestige venue
- Knowledge collapse three-stage framework [source-b2e65b22a105] — single workshop paper, tested only on GEMMA 3 1B
- Exact 23.6% PLS magnitude [source-a9eb9eddb24f] — single paper, though the phenomenon is independently confirmed qualitatively
- Neuron-level distinctness of bias vs. collapse mechanisms — single mechanistic study on GPT-2

