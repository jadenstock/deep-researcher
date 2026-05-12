# Research report

**Query:** What are the real-world risks and benefits of using synthetic data to train or fine-tune large language models? Focus on data quality, bias, and evaluation.

# Real-World Risks and Benefits of Synthetic Data for Training and Fine-Tuning LLMs

## Bottom-Line Takeaway

Synthetic data delivers documented, often dramatic benefits for LLM fine-tuning — especially in low-resource settings, instruction tuning, distillation, and privacy-preserving pipelines — but carries distinct risks in three areas the user flagged: data quality (model collapse, diversity loss, hallucination propagation), bias (feedback loops, bias inheritance, intersectional amplification), and evaluation (preference leakage, benchmark contamination, retrieval bias). The most-feared risk — catastrophic "model collapse" at frontier scale — is largely an artifact of small-model, pure-replacement experimental paradigms; under realistic data-accumulation conditions it is provably bounded [source-61373b2177bc, source-3f32ccacaa6b]. However, subtler and more persistent risks — tail/mode coverage loss, bias amplification through feedback loops, preference leakage in LLM-as-a-judge pipelines, PII leakage through string memorization, and medical-domain data-poisoning — remain empirically real, often undetectable by standard metrics, and disproportionately harmful to marginalized groups and high-stakes domains.

---

## 1. Benefits: What Synthetic Data Demonstrably Enables

Synthetic data has moved from novelty to standard infrastructure in LLM post-training. The benefits are strongest and best-evidenced in **fine-tuning** contexts; in **pre-training** the evidence is thinner and the conditions stricter.

**Instruction tuning and alignment.** Instruction Tuning with GPT-4 [source-45e3be2d4e84] and the Self-Instruct/Alpaca lineage [source-19319c142b21] established that LLM-generated instruction-following data (≈52K examples) yields superior zero-shot instruction-following without human-written labels. Constitutional AI (RLAIF) achieves "similar strong performance as RLHF baselines" using synthetic AI-generated critiques in place of human feedback [source-19319c142b21]. The Phi series [source-012b2702b8b5] and FineWeb-Edu [source-86f687758795] extend the benefit to pre-training: Phi-1.5 trained almost entirely on ~20B tokens of "textbook-like" synthetic data matches or surpasses Llama2-7B, Vicuna-13B, and Falcon-7B on common-sense reasoning, and Llama3-70B-Instruct synthetic quality ratings improve filtered-pretraining MMLU by 12% and ARC by 24% relative to unfiltered FineWeb [source-86f687758795].

**Data scarcity and low-resource gains.** Systematic studies show 3–26% absolute accuracy gains from synthetic augmentation when only ~100 real samples are available [source-c5127b1ec462]. A 20B teacher LLM fine-tuned on as few as 125 real examples still produces synthetic data that improves small students "by multiple percentage points" [source-19319c142b21]. The smaller the real labeled set, the larger the downstream gain — synthetic data is fundamentally a remedy for under-fitting.

**Annotation cost.** Empirical cost comparison: $221–$300 and ~1,000 person-minutes for 3,000 human-labeled sentiment examples versus $14.37 and 46 minutes for a comparable GPT-3 synthetic set [source-c5127b1ec462]. ChatGPT outperforms crowdworkers on text-annotation tasks (Gilardi et al. 2023, cited in [source-19319c142b21]). Quality gaps exist (6,000 GPT-3 examples → 76% classifier accuracy vs. 88% with 3,000 human-labeled) but close with curation (AlpaGasus) and better generators [source-a629c8c8bf02].

**Controlled diversity.** Unlike scraped data, synthetic pipelines allow *attribute-conditioned* generation — explicit control over topic, length, style, and class distribution [source-a629c8c8bf02]. Zero-shot topic-guided generation (enumerate topics, then generate per-topic) yields the most diverse synthetic data and best downstream performance [source-c5127b1ec462]. Multi-source generation (responses from several LLMs) "mitigates distribution collapse" and produces lower perplexity on held-out human text than single-source generation [source-bec0ed37682f].

**Privacy-preserving substitution.** DP-augmented LLM fine-tuning on sensitive user instructions produces models that **outperform Vicuna** in SFT, and in RLHF, "reward and win-rate curves for our synthetic instructions closely mimic those achieved using real instructions" [source-9137c413fa61]. This also protects sensitive data from exposure to human annotators — a privacy risk usually overlooked. Tradeoffs are empirically documented: DP noise causes ~3% accuracy drops in Naive Bayes, ~10% in SVM, and 15–20% in sequence models (GRU/LSTM) [source-e093ff49b6ce].

**When benefits fail to materialize.** Returns drop sharply past ~1,000 real examples [source-c5127b1ec462]; synthetic data that contains hallucinated answers can *increase* hallucinations in fine-tuned models [source-19319c142b21]; distribution shift is a standing risk because LLMs generate cleaner text than noisy real inputs [source-c5127b1ec462]; and — a non-obvious failure mode — "fine-tuning on synthetic data removed guardrails while preserving output quality," unlike human-data fine-tuning where both degrade together [source-bec0ed37682f]. This means the quality-preservation virtue of synthetic data is itself a safety-amplification risk.

---

## 2. Data Quality: Model Collapse and Diversity Loss

This is the most publicly discussed risk and also the most definitionally contested.

### The mechanism

Shumailov et al. (Nature 2024) [source-c4884ed2db25] identify three compounding error sources under recursive synthetic training: statistical approximation error (finite-sample tail erasure), functional expressivity error (network capacity), and functional approximation error (optimizer bias). They prove that in a Gaussian-approximation setting, iterated generation "collapses to be zero variance as the number of generations increases, with probability 1." Borji [source-4c6dc275609c] corroborates via KDE simulation — the distribution converges toward a normal and loses distinctive features regardless of kernel bandwidth.

Empirically, Guo et al. (NAACL 2024 Findings) [source-cea6c6379616] document "a consistent decrease in the diversity of the model outputs through successive iterations, especially remarkable for tasks demanding high levels of creativity" — decline across lexical, syntactic, and semantic dimensions. This peer-reviewed finding is replicated at Llama-3.1-8B and 70B scale [source-bec0ed37682f] and corroborated by TACL benchmarking [source-a2ad9d70b844]. Syntactic diversity declines most strongly; semantic diversity is most resilient.

### The contested counter-case

A substantial body of recent work argues the collapse narrative is methodologically overstated for frontier-scale training. Our adversarial dispatch found the steelman largely holds on five of six points:

1. **Small-model artifact.** Shumailov et al.'s LLM experiments use OPT-125M — the authors explicitly call this "a more realistic setting for a proof of concept" rather than frontier scale [source-c4884ed2db25].
2. **Unrealistic paradigm.** The pure-replacement assumption (β=γ=0) is what Schaeffer et al. call "highly unrealistic: After a model finishes training, the entire internet is not deleted" [source-3f32ccacaa6b]. Real frontier training follows accumulation (Llama 1→2→3 = 1.4T→2T→15T tokens).
3. **Definitional confusion.** Schaeffer et al. [source-e585ac255921, source-3f32ccacaa6b] hand-annotate 28 papers and identify **8 distinct definitions** of collapse, often used inconsistently within a single work. Alemohammad et al. and Gerstgrasser et al. reach opposite conclusions from the same figure because one uses "any FID increase" and the other uses "asymptotically diverging FID."
4. **Bounded under accumulation.** Gerstgrasser et al. prove that when data accumulate (real + all prior synthetic generations), "the test error has a finite upper bound independent of the number of iterations" [source-61373b2177bc]. This holds across GPT-2, Llama-2 (12M–125M), diffusion models, and VAEs.
5. **Astronomical timescale.** The expected number of model-fitting iterations before total collapse is proportional to D × H[p₀]. With ~quadrillion-token public text reserves [source-c030379ba3b7], "trillions of models can be trained before glimpsing the onset of collapse" [source-e585ac255921].
6. **Curated synthetic improves performance.** Phi-1.5 [source-012b2702b8b5] and FineWeb-Edu [source-86f687758795] directly falsify the claim that synthetic pre-training necessarily degrades quality.

### Residual real risks (where the steelman fails)

The adversarial review surfaced genuine residual concerns that survive even the strongest optimistic case:

- **Tail and mode coverage loss** is not prevented by accumulation — even Gerstgrasser's VAE experiments show "diversity of generations does go down" while test error stays bounded [source-61373b2177bc]. This disproportionately harms rare phenomena and marginalized-group representation [source-3f32ccacaa6b].
- **Bias amplification is mechanistically distinct from collapse.** Wu et al. [source-b204946d083e] show bias amplification persists *independently* of model collapse, with largely distinct neuron populations — mixing real data slows collapse but does not stop bias amplification.
- **Diversity as a causal driver.** The Quality-Diversity-Complexity framework [source-669ffe594f48] establishes that "quality is essential for in-distribution generalization, diversity is essential for out-of-distribution generalization." Chen et al. [source-10354df8e9df] confirm that synthetic-data diversity in pre-training "affects supervised fine-tuning more significantly than pre-training itself." Diversity matters even when it doesn't predict narrow benchmark scores — and lexical diversity metrics *can* negatively correlate with quality on some tasks [source-a1b61b7cd1cb], complicating measurement.
- **Practical optimal mixing ratio.** The demystifying study (>1,000 LLMs) [source-e45846b7104d] finds ~30% synthetic is optimal for rephrased-data mixtures, with performance declining at higher proportions.

**Synthesis:** Catastrophic collapse at frontier scale is not the right thing to worry about. Tail erosion, diversity homogenization in creative tasks, and the long-run contamination trajectory of web data by AI-generated content (OpenAI alone reportedly produces ~100B words/day [source-c030379ba3b7]) are the quality risks that deserve operational attention.

---

## 3. Bias: Amplification, Inheritance, and Feedback Loops

Synthetic data bias is qualitatively different from scraped-data bias: scraped biases are frozen historical inequities; synthetic biases are *generated, compounded, and self-reinforcing*.

### The three mechanisms

**(a) Fairness feedback loops (FAccT 2024).** Wyllie et al. [source-81c121e5de02] introduce Model-Induced Distribution Shifts (MIDS). On FairFace and CelebA in their SeqGenSeqClass setting, *minoritized group representation falls to 0% within 5–8 generations*, and on ColoredMNIST/SVHN accuracy drops 10–15% over 40 generations with EOdds unfairness increasing ~0.2. Critically, models evaluated against predecessor-model labels appear nearly perfect on fairness metrics even when they are severely biased: "In SeqClass, these relative results show nearly 100% accuracy and 0 EOdds difference." The theoretical foundation from Taori & Hashimoto [source-769f7ee388b7] bounds amplification by (m+k)/m × δ where calibration error δ is the key parameter.

**(b) Bias amplification independent of collapse.** Wu et al. [source-b204946d083e] show progressive right-leaning political bias intensification over iterative synthetic training cycles in GPT-2. Three mitigation strategies (Overfitting, Preservation, Accumulation) fail to prevent amplification, and mechanistic analysis identifies *distinct neuron populations* driving bias vs. collapse — confirming they are different phenomena needing different interventions.

**(c) Bias inheritance at multi-task scale.** Across 10 downstream tasks with Llama-3.1-8B [source-e08cb1e616c5], "bias inheritance not only persists but also amplifies over multiple rounds… the bias extends to the majority group, leading to a decline in performance across all social groups." This occurs even at modest synthetic ratios (10–20%).

### Domain-specific bias trade-offs

**Healthcare.** Bhanot et al. (IBM Research) [source-edf62c095bf3] found HealthGAN synthetic MIMIC-3 data *changed the direction* of bias — Black patients underrepresented by >34% in synthetic data though the real data was White-biased. Fairness mitigation techniques validated on real data do not transfer: they sometimes produce *worse* results on synthetic versions of the same dataset (p=0.0073, p=0.0006) [source-edf62c095bf3]. This invalidates a common assumption in applied fairness pipelines.

**Finance.** FairFinGAN [source-510f9b150625] with embedded statistical-parity constraints improves fairness across five financial datasets, but gains are classifier- and dataset-dependent. Bhanot et al. [source-575219ee258c] quantify the real→synthetic bias trade-off across healthcare and financial domains.

**Intersectional/cultural gaps.** The in-context bias propagation study [source-5ceec8fed33c] shows LLMs capture intersectional patterns (gender×race×native-country) via conditional and higher-order correlations, meaning "marginal constraints fail to capture" them — standard parity interventions do not protect intersectional subgroups. Cultural bias inheritance is systematically *worse* for Eastern cultures than Western cultures [source-e08cb1e616c5] because pre-training representation is imbalanced.

### The adversarial case: when synthetic data *reduces* bias

Our adversarial dispatch found the steelman holds for purpose-built fairness-aware generation but fails as a general claim. **MCRAGE** (healthcare) achieves 4.69% F1 improvement over imbalanced datasets and 4.42% over SMOTE [source-cb402ad9ec9a]; a peer-reviewed PMC study found Synthetic Minority Augmentation produces "the most favorable fairness metrics" across SPD/EOD/AOD compared to RUS/ROS/SMOTE/RF across 500 simulations on four real datasets [source-057001fcc0ee]. Real algorithms have demonstrably harmed minorities — one deployed healthcare algorithm was "less likely [to] refer Black people than white people who were equally sick" [source-057001fcc0ee] — so the real-data baseline is often *so* biased that even imperfect fairness-aware synthetic data is a net-positive intervention. FAccT 2024 itself frames this as "algorithmic reparation" [source-81c121e5de02].

The adversarial dispatch also found the "GPT-2 bias amplification doesn't replicate at frontier scale" argument partly vindicated: "Iterative Finetuning is Mostly Idempotent" [source-7c56f30e9db0] tested Qwen3-32B and Llama-3.3-70B across seven traits and three paradigms, finding that "in the SFT and SDF settings, traits mostly decay or remain constant." Computer vision work [source-99704d3cc0af] finds Stable Diffusion-synthetic training does not consistently amplify bias and shows "consistent bias mitigation" on some tasks.

**But the steelman has one sharp exception**: "Continual DPO is the most concerning setting: it is the only training regime… where a model can become meaningfully more biased while still appearing functional" [source-7c56f30e9db0]. Iterated preference optimization *does* amplify traits at scale — which is precisely how frontier alignment pipelines operate.

### Mitigations with empirical support

| Strategy | Evidence | Result |
|---|---|---|
| Algorithmic reparation / STAR | FAccT 2024 [source-81c121e5de02] | Reduces EOdds; gen-STAR > cla-STAR |
| Mixing non-synthetic data | FAccT 2024 [source-81c121e5de02] | Greatly slows MIDS (but weakens STAR) |
| Fairness-constrained generation | FairFinGAN [source-510f9b150625] | Improves parity at utility cost |
| Synthetic Minority Augmentation | SMA [source-057001fcc0ee] | Best fairness metrics in low-medium bias |
| Counterfactual data augmentation | Survey [source-679ad7ba7a41] | Validated pre-model debiasing |
| Fair-SPD prompt preprocessing | Tabular [source-5ceec8fed33c] | Best among tested defenses but insufficient against adversarial injection |

**Alignment is not a shield.** Alignment tuning can overcorrect on some attributes while amplifying others — GPT-4o-mini overrepresents females in biographies while embedding Eastern-culture blind spots [source-e08cb1e616c5]. RLAIF creates "recursive alignment issues" where evaluator biases are "inherited and potentially amplified" by supervised models [source-8404022e2b20]. No independent peer-reviewed audit has quantified net alignment de-biasing relative to web-scrape baselines.

---

## 4. Evaluation Integrity: Five Distinct Threats

### Preference leakage (LLM-as-a-judge)

Li et al. (ICLR 2026) [source-c30859f69612] formally define and quantify preference leakage: LLM judges systematically favor student models trained on data from architecturally related generators. Preference Leakage Scores range from **8.9% (same family, different series) to 23.6% (same model)** on Arena-Hard and AlpacaEval 2.0 — exceeding even egocentric self-preference. AlpacaEval 2.0 and Arena-Hard both use GPT-4 as both data synthesizer and evaluator. Mitigations with empirical support:

- Contextual calibration (held-out set): Error Bias 17.8 → 7.3
- DPO instead of SFT: average PLS 23.6% → 5.2%
- In-context learning (no weight tuning): PLS near zero
- Style/format paraphrase pipeline: substantial reduction across judge pairs

A complementary study [source-703a56a6b355] argues strong-model self-preference is *mostly legitimate* when measured against verifiable ground truth (95%+ tracks objective correctness for 70B+ models). But harmful self-preference — favoring one's own objectively wrong answer — persists: Qwen2.5-72B exhibits 86% harmful self-preference propensity on MATH500 when generating incorrect responses.

### Benchmark contamination propagated through synthetic datasets

Deng et al. (NAACL 2024) [source-36271b9f9261] showed ChatGPT achieves 52% and GPT-4 57% exact match on masked MMLU test-answer completion — strongly suggesting benchmark contamination. GPT-3.5-generated CodeAlpaca contains 12.8% paraphrased HumanEval samples [source-541485892f05]. This creates a feedback loop: contaminated LLM generates synthetic datasets containing paraphrased benchmark data, which contaminates fine-tuned downstream models. Augmentation-based contamination (paraphrasing, synonym substitution) evades traditional n-gram detection entirely [source-541485892f05].

### Retrieval / test-collection bias

Rahmani et al. (CIKM 2025) [source-ebdd68d4d726] on TREC DL 2023 found GPT-4 judges assign higher scores to GPT-4-based systems (interaction β = 0.032, p = 0.006) and systems judged by GPT-4 score substantially higher than systems judged by humans (MAP β = 0.069; NDCG β = 0.207, p < 0.001). Synthetic queries are easier than real queries, inflating absolute performance — though relative rankings remain moderately preserved. This finding rests on a single controlled study and warrants cross-domain replication.

### Static vs. dynamic benchmarking

Chen et al. [source-1b0c35422a5a] provide the most systematic taxonomy: temporal cutoff (LiveBench, LiveCodeBench), rule-based generation (DyVal, GSM-Symbolic), LLM-based rewriting (LatestEval, TreeEval), and hybrid. No current dynamic benchmark satisfies all six evaluation criteria (correctness, scalability, collision resistance, stability, diversity, interpretability). Rule-based methods score highest on correctness and collision resistance; LLM-based highest on diversity but lowest on correctness. Static benchmarks are "currently inevitable" contaminated — uniform contamination across training "produces the most lasting effects" [source-541485892f05].

### Formal evaluation frameworks

The Computational Linguistics 2024 framework [source-98c08e88c8aa] proposes three axes (style preservation, meaning preservation, divergence-as-privacy-proxy) for synthetic UGC — but the paper was paywalled, limiting methodological detail. SynEval [source-4a422ca6fc25] operationalizes fidelity/utility/privacy for tabular data and documents a striking finding: LLM-generated synthetic tabular data exhibits **83–91% Membership Inference Attack success rates** (ChatGPT 90%, Claude 91%, Llama 83%) — utility is preserved (67–68% vs. 68% real) *but privacy is not*. Distance-to-Closest-Record and similar feature-space metrics systematically underestimate LLM-specific leakage [source-e3c52dbfcc6e].

---

## 5. Domain-Specific Risks: Medical, Legal, Finance

### Medical LLMs: data-poisoning and clinical safety

The single most alarming finding in the corpus: replacing **just 0.001% of training tokens** with AI-generated medical misinformation produces an LLM significantly more likely to generate clinically harmful text, as adjudicated by 15 blinded clinicians (Nature Medicine 2024) [source-0a05c1521817]. The attack costs under $5–$100 per domain, requires no model access, and exploits the fact that 27.4% of medical concepts in The Pile reside in "vulnerable" web-scraped Common Crawl subsets.

**Poisoned models evade all five standard medical benchmarks** (MedQA, PubMedQA, MedMCQA, MMLU clinical knowledge, MMLU professional medicine) — benchmark performance is comparable to controls. This invalidates standard evaluation as a safety gate. Complementary attacks include weight-level poisoning (~1% of pretrained weights, propagates to all fine-tuned variants) [source-ff262385090e] and adversarial prompt injection persistent across Llama-3.3 and GPT-4o [source-7e9a2aef2e62].

**The only empirically validated mitigation**: biomedical knowledge-graph filtering against BIOS KG (21,706 concepts, 416,302 relationships) achieved **91.9% recall, F1=85.7%** for harmful passages [source-0a05c1521817]. By contrast, prompt engineering (p=0.36), RAG (p=0.66), and supervised fine-tuning on medical QA (p=0.99) *all failed* to remediate poisoned models. Post-hoc approaches are insufficient; data provenance is required.

**MedSyn-style risks.** Unfiltered MedSyn output contains ~36–49% corrupted samples with factual errors [source-3db90a6065c6]; medical interns can correctly identify synthetic notes only 58% of the time — high utility but high re-identification risk. A medRxiv 2025 analysis documents "rapid erosion of pathological variability" in synthetic medical feedback loops [source-80e296b5ec07 related]. Mixing synthetic + real notes improved rare ICD-10 classification by 17.8% — but only with quality filtering.

### PII leakage through LLM generators

The IJCAI-25 survey [source-2b6b5f55b360] documents three attack families: training-data extraction (2,175 PII samples per 15,000 queries at 85.8% authenticity on GPT-2/Falcon/LLaMA-2), crafted-prompt attacks (59% CoT-jailbreak extraction for frequent Enron emails on GPT-3.5; 5–18× improvement for phone numbers with PII prefixes), and **neural phishing** fine-tuning attacks. Most alarming: "using Pythia fine-tuned on Enron to produce synthetic PII, they fine-tuned another LLM and observed that it still leaked real PII, despite training on seemingly unrelated synthetic data" [source-2b6b5f55b360].

HARMONIC [source-e3c52dbfcc6e] and "When Tables Leak" [source-2f809724a68a] expose a vulnerability class missed by traditional privacy metrics: **string memorization leakage** (verbatim digit sequences). LevAtt achieves "perfect membership classification in several TabPFN-V2 settings," and critically: "privacy leakage scales monotonically with synthetic dataset size, with up to a 20% absolute increase in attack success" — larger synthetic releases amplify risk. The TLP defense reduces string leakage to <55% AUC and 12.5% TPR at FPR=10% with minimal utility cost.

### Regulatory and legal

EU framework [source-9af5b8e5c9db]: fully synthetic data is not automatically GDPR-exempt — re-identification risk remains because "even domain experts may struggle to differentiate" synthetic from real medical data. Article 22 applies to downstream automated profiling. The EU AI Act (Annex II) requires high-risk AI training data to be "relevant, representative, error-free, and complete" — extending to synthetic data generation methodology documentation and bias audits.

FDA has authorized 1,016 AI/ML medical devices but issued **no specific guidance on generative AI synthetic data** as of December 2024 [source-64ed768d5fe7]. No drug has been registered using predominantly generative-AI-derived synthetic data. HIPAA-compliant approaches require deidentification plus surrogation [source-838b2557357a], with residual reidentification risk through "one-to-one, one-to-few and few-to-few identities" algorithms.

---

## 6. Cross-Cutting Mitigations: What Actually Works

| Mitigation | Empirical Status | Evidence |
|---|---|---|
| Real + synthetic data accumulation (not replacement) | **Validated** (provable bounded population risk) | [source-61373b2177bc] |
| Multi-source synthetic generation | **Validated** (preserves distribution, lower human-text perplexity) | [source-bec0ed37682f] |
| Quality/curation filtering (AlpaGasus, Phi-style) | **Validated** at small-to-mid scale | [source-a629c8c8bf02, source-012b2702b8b5] |
| Differential privacy (tabular) | **Validated** with documented utility tradeoffs | [source-e093ff49b6ce, source-9137c413fa61] |
| DP for unstructured text | **Immature** — severe quality cost | [source-850f24e285b9] |
| Knowledge-graph output filtering (medical) | **Validated** (F1=0.857 vs. failed alternatives) | [source-0a05c1521817] |
| Deidentification + surrogation | **Validated** at 95% accuracy | [source-838b2557357a] |
| TLP string-memorization defense | **Validated** against LevAtt | [source-2f809724a68a] |
| Contextual calibration of LLM judges | **Validated** (17.8→7.3 bias reduction) | [source-c30859f69612] |
| DPO instead of SFT for judge training | **Validated** (PLS 23.6→5.2%) | [source-c30859f69612] |
| Fairness-aware generators (MCRAGE, FairFinGAN, SMA) | **Validated** for domain-specific oversampling | [source-cb402ad9ec9a, source-510f9b150625, source-057001fcc0ee] |
| Algorithmic reparation / STAR | **Validated** (reduces EOdds in FAccT experiments) | [source-81c121e5de02] |
| Dynamic benchmarks (rule-based, temporal) | **Partial** — no standard fully satisfies 6 criteria | [source-1b0c35422a5a] |
| Watermarking synthetic outputs | **Proposed only** — no domain validation | — |
| Human-in-the-loop review | **Recommended** — no systematic operational protocol | [source-0a05c1521817] |
| Prompt engineering / RAG for poisoned models | **Refuted** (p=0.36, p=0.66 — not significant) | [source-0a05c1521817] |
| Distance-to-Closest-Record privacy metrics | **Refuted** for LLM-specific leakage | [source-e3c52dbfcc6e, source-2f809724a68a] |

---

## 7. Synthesis and Practical Guidance

The risks and benefits of synthetic data for LLMs are both real, but the popular narrative distorts their relative magnitudes. Five summary judgments:

1. **For fine-tuning at current scale, synthetic data is net-positive when quality-filtered, multi-sourced, and mixed with real data.** The instruction-tuning, distillation, and low-resource benefits are well-established; the downside risks are tractable with known techniques.

2. **Catastrophic model collapse is not the right worry.** Under realistic data-accumulation paradigms with massive real-data reserves, population-risk collapse is provably bounded [source-61373b2177bc] and total collapse is astronomically distant [source-e585ac255921]. Phi-1.5 and FineWeb-Edu falsify the strong claim that synthetic pre-training necessarily degrades quality.

3. **Tail/mode coverage loss, diversity homogenization in creative tasks, and long-run web contamination are the real quality risks.** These persist even under accumulation, and disproportionately harm rare phenomena and marginalized groups.

4. **Bias is the least well-mitigated risk.** Feedback loops [source-81c121e5de02], bias inheritance across tasks [source-e08cb1e616c5], intersectional amplification [source-5ceec8fed33c], and DPO continual-learning amplification [source-7c56f30e9db0] all persist. Purpose-built fairness-aware generation (MCRAGE, SMA, FairFinGAN) is net-positive against biased real baselines, but naive generic synthetic data can introduce *new* biases not present in real data [source-edf62c095bf3]. Fairness mitigations validated on real data do not transfer to synthetic versions of the same dataset.

5. **Evaluation is broken in specific, measurable ways.** Preference leakage in LLM-as-a-judge is pervasive and largely undiscussed in leaderboards [source-c30859f69612]. Benchmark contamination propagates through synthetic datasets in ways standard n-gram decontamination cannot detect [source-541485892f05]. In high-stakes medical settings, standard benchmarks cannot distinguish poisoned from clean models [source-0a05c1521817]. Any rigorous evaluation stack now requires contextual calibration, dynamic benchmarks, and domain-specific validation (e.g., KG-based medical filtering).

**For practitioners:** mix real and synthetic data rather than replace; use multi-source synthetic generation; filter aggressively; never use the same model family as both generator and judge; apply differential privacy for sensitive-data pipelines and expect 3–20% utility costs; in medical/legal/finance, require KG-based output validation and treat standard benchmarks as insufficient for safety certification. Acknowledge that fairness-aware synthetic data is a powerful tool against biased real baselines but is not a free lunch — each fairness intervention must be independently validated on the synthetic output.

**For researchers:** the empirical frontier needs (a) frontier-scale (100B+, trillion-token) collapse/diversity experiments, (b) independent peer-reviewed audits of whether RLHF/Constitutional AI alignment produces net bias reduction, (c) DPO continual-learning bias-amplification measurement in deployed frontier systems, (d) cross-domain replication of retrieval-bias findings, and (e) empirical validation of watermarking in high-stakes pipelines.
