# Research report

**Query:** What are the real-world risks and benefits of using synthetic data to train or fine-tune large language models? Focus on data quality, bias, and evaluation.

# Real-World Risks and Benefits of Synthetic Data for Training and Fine-Tuning LLMs

## Takeaway

Synthetic data delivers large, documented benefits — dramatic cost reductions (~$600 total for Alpaca-class instruction models [source-18890d359fcd]), 5–10× pre-training speed-ups when ~30% rephrased synthetic is mixed with natural web text [source-1c1e941e05b7], and reasoning gains such as Phi-4's 14B model exceeding GPT-4 on STEM QA [source-da9c18469bc5, source-47d03bb6f6d0] — but those wins come with real risks that the strongest optimistic results do *not* rule out. The empirical literature shows measurable data-quality degradation beyond ~20–30% synthetic proportions [source-7408f1813b7c, source-dce041ca9ecb], complex bias dynamics (equilibrium convergence toward a generator's inherent bias rather than monotonic amplification [source-3017c54b4824], but complete minority-group erasure under full recursive training [source-05ff198b7a07]), and pervasive evaluation contamination when the same model family generates data and judges outputs [source-c24177e8b061]. The practical balance depends on three controllable choices: data workflow (accumulation vs. replacement), proportion and type of synthetic data, and evaluation discipline (cross-family judges, human anchors).

---

## 1. Benefits: What Synthetic Data Actually Delivers

**Cost and democratization.** Stanford Alpaca demonstrated that 52K Self-Instruct examples from text-davinci-003 cost less than $500 to generate and under $100 to fine-tune on LLaMA 7B, yielding parity with the teacher model in blind pairwise human evaluation (90 vs. 89 wins) [source-18890d359fcd]. Swapping GPT-3.5 outputs for GPT-4 outputs produced a 7B student that beat the 13B Alpaca on helpfulness (54.12% vs. 19.74% win rate) [source-f3e722031f8f]. Knowledge distillation with Chain-of-Density prompts from a 405B teacher yielded 8B and 70B students with 18× and 2× inference-cost reductions, and up to 19% quality *improvement* over the vanilla teacher on summarization [source-6cf3c1f9af77].

**Scalability in pre-training.** A Meta FAIR study spanning >1,000 LLM variants and >100K GPU-hours found that mixing ~1/3 rephrased synthetic data with ~2/3 natural web text delivers 5–10× convergence speed-ups at larger data budgets, with optimal mix ratios converging to ~30% for rephrased synthetic [source-1c1e941e05b7]. Xwin-Math scaled synthetic SFT math data to 1M examples with continued benefit [source-5381ebff0c03].

**Reasoning.** Phi-4 (14B, Microsoft Research) is the most prominent case study of synthetic-heavy training exceeding the teacher on STEM benchmarks [source-da9c18469bc5, source-47d03bb6f6d0]. AlphaGeometry, trained on 100M synthetic datapoints, reached Olympiad gold-medalist level [source-5381ebff0c03]. Distilled CoT reasoning boosted MultiArith accuracy from 68.89% (70B vanilla) to 98.89% (70B distilled) [source-6cf3c1f9af77]. Constitutional AI/RLAIF uses synthetic feedback at RLHF-comparable quality while replacing costly human annotation [source-5381ebff0c03].

**Privacy-enabled training on sensitive data.** Google's DP-SGD + LoRA fine-tuning on sensitive data produces synthetic corpora with formal ε-differential privacy guarantees. Classifiers trained on this DP-synthetic data can *outperform* classifiers trained directly with DP on the original data, because the LLM's public pre-training prior compensates for DP noise [source-acfa58f07996]. Google deployed this pattern in production for an on-device safety classifier.

**Quality over quantity.** A filtered 14% subset of ToolBench data matched full-dataset performance [source-bcfd4a83bcca]; LIMA showed ~1,000 curated examples can suffice for instruction following [source-5381ebff0c03]. Large quantities of noisy synthetic data are actively harmful relative to smaller curated sets.

---

## 2. Data-Quality Risks: Model Collapse, Distribution Shift, Hallucination Amplification

This is the most technically contested area, and the contest matters.

**The theoretical risk case.** Shumailov et al. (*Nature*) [source-72ead944b31a] proved that recursive training on synthetic data causes "irreversible defects" — distribution tails disappear in early collapse, variance converges to zero in late collapse. Seddik et al. [source-d35c7cd84801] showed that in the fully-synthetic setting, collapse is Markov-chain guaranteed; in the mixed setting, the safe amount of synthetic data must be **exponentially smaller** than real data to maintain distributional closeness. Dohmatob et al. ("Strong Model Collapse") claim that **even 1% synthetic data can plateau scaling laws** under their regression-model analysis, and that this "cannot generally be mitigated by simple adjustments such as data weighting" [source-1faec8b1a9de].

**Empirical evidence at production-relevant scale.** Zhu et al. measured average perplexity on 22 Pile domains as synthetic proportion increases in single-round (non-recursive) pre-training [source-7408f1813b7c]:

| Synthetic % | Avg. Perplexity | Change |
|---|---|---|
| 0% | 20.99 | baseline |
| 25% | 22.06 | +5% |
| 50% | 23.48 | +12% |
| 75% | 27.60 | +31% |
| 100% | 51.93 | +147% |

The mechanism is **coverage narrowing** — synthetic text has a smoother, narrower distribution and lacks long-tail samples, a structural deficit that importance sampling cannot correct [source-7408f1813b7c]. For fine-tuning specifically, a 300-run study found performance stays within 3% of baseline up to ~20% synthetic but degrades 8–15% beyond 30% [source-dce041ca9ecb]. Mathematical reasoning degrades fastest, then code generation, then factual QA.

**The counter-evidence.** Gerstgrasser et al. ("Is Model Collapse Inevitable?") showed the workflow matters more than the proportion: *replacement* of real data causes collapse, but *accumulation* (keeping old real data alongside new synthetic data) gives a theoretically bounded error independent of iteration count [source-a2ca30455fcc]. The Meta FAIR study directly contradicts Dohmatob's "1% breaks scaling" claim at empirical scale: rephrased synthetic data at 30% showed no degradation and lower projected irreducible loss than pure CommonCrawl [source-1c1e941e05b7]. A 2025 position paper notes the literature conflates at least eight definitions of "model collapse" [source-40e0b4562c89].

**What the adversarial steelman added.** The optimistic "30% rephrased is safe" conclusion rests on a single study that explicitly did **not** test long-term, multi-generational, frontier-scale, factuality, safety, or hallucination effects — experiments capped at 3B parameters and 200B tokens, with evaluation "heavily reliant on perplexity/loss" [source-1c1e941e05b7, source-c7dee55348e4]. Phi-4 is similarly narrower than often cited: Microsoft's own technical report says synthetic-only ablations "underperformed on the knowledge-heavy benchmarks and demonstrated increased hallucinations," and 1-shot TriviaQA showed "a large gap where synthetic models are subpar" — Phi-4's final mix included filtered web, books, and academic data, not just synthetic [source-47d03bb6f6d0]. Even the skeptical "Model Collapse Does Not Mean What You Think" paper concedes: "there are very real threats to tails of the data distribution that should be taken seriously" and "real tail data and modes will be lost" [source-40e0b4562c89].

**Real-world production exposure.** Even absent a published base-model postmortem attributing degradation to synthetic web ingestion, production-facing contamination is already documented at the retrieval/search layer: threat actors use SEO poisoning to seed fake content that Gemini and Google surface as credible [source-0a8e89c42556]; a controlled RAG study showed a 67% AI-generated retrieval pool causes >80% exposure contamination in a "homogenized yet deceptively healthy state" where accuracy looks stable despite reliance on synthetic sources [source-6cf149b9350b]. Shumailov et al. explicitly warn that "LLMs at scale to publish content on the Internet will pollute the collection of data to train their successors" [source-72ead944b31a].

**Net verdict.** Model collapse is not mythical, and it is not deterministic. Under production-relevant single-round training with quality filtering and real-data anchors, the alarmist 1% threshold is not empirically supported. Under recursive training, pure-synthetic regimes, or unchecked web-ingestion loops, tail erasure, bias amplification, and factuality degradation are demonstrated failure modes. The safe regime is conditional on workflow, type of synthetic data, and provenance discipline — not a free lunch.

---

## 3. Bias: Amplification, Equilibrium, and the Role of Generator Diversity

The simple "synthetic data amplifies bias" story is wrong; the reality is more nuanced and in some ways more troubling.

**Equilibrium dynamics.** Kattamuri et al. [source-3017c54b4824] studied recursive generation with Gemma-2-2b-it across three generations and found convergence to a **generator-inherent equilibrium bias** rather than monotonic amplification: starting bias of 0.1 grew +36% toward equilibrium ~0.11–0.13, while starting bias of 0.6 *decayed* −26% toward the same equilibrium. Implication: mitigation must shift the equilibrium, not just initial seed conditions. A sharp methodological warning: **contrastive augmentation reduced downstream behavioral bias by 91%** even while *increasing* embedding-based bias scores, meaning representation-level metrics can diverge catastrophically from outcome-level fairness [source-3017c54b4824].

**The catastrophic regime.** Under 100% synthetic recursive training, Wyllie, Shumailov & Papernot (FAccT 2024) document complete minority-group erasure: "minoritized group representation in CelebA falls to 0%" [source-05ff198b7a07]. Li et al. (2025) show bias inheritance in augmentation: "adding biased augmentation data consistently improves the performance for majority groups (male) while decreasing the performance for minority groups (female)," and this effect "not only persists but also amplifies over multiple rounds" [source-7da1b0b291cc]. Even "neutral" prompts generate demographically skewed outputs because of pretraining imbalances.

**Invisible bias via in-context examples.** Mild in-context demographic skew propagates linearly into synthetic outputs and remains **invisible to standard utility metrics** — F1 scores "indistinguishable (or even superior) to the unbiased setting" while fairness is compromised [source-b763b50fc760]. Larger context windows amplify both utility and bias propagation.

**Generator diversity is the strongest mitigation lever.** Multi-source fine-tuning mitigates distribution collapse and reduces self-preference bias; single-source fine-tuning from one generator model is the highest-risk configuration [source-7d709ca6ed63]. Ecosystem-level diversity becomes *more* important as recursive training iterations accumulate: "the optimal level of diversity increases monotonically with the number of self-training iterations" [source-10b5f9bd8efa]. But diversity is not unconditionally safe: for large (70B) target models, high generator diversity can *increase* adversarial vulnerability via conflicting safety signals [source-7d709ca6ed63].

**Annotation bias in GPT-4-generated data.** GPT-4-synthesized instruction-tuning data shows documented annotation error and bias (Vision-Flan [source-be2d1e9d3db8, via landscape]), and GPT-4-class model responses "significantly differ from those of humans... particularly for Eastern cultures" [source-7da1b0b291cc].

**No universal solution.** Li et al.: "the effectiveness of different mitigation approaches is also nuanced, depending on various factors such as different types of bias, downstream tasks, and bias ratios, highlighting the difficulty in devising a unified solution" [source-7da1b0b291cc].

---

## 4. Evaluation: LLM-as-Judge, Preference Leakage, and the Circularity Problem

This is the best-converged area in the literature, and the findings are damaging to current evaluation practice.

**Self-preference bias.** GPT-4 exhibits significant self-preference bias, mechanistically explained by **perplexity preference** — LLMs assign higher scores to text with lower perplexity, whether or not they generated it [source-7a505f3cdd40]. Across 20 models (3B–671B), self-preference bias scores range from +0.307 (LongCat) to −0.229 (Claude-Sonnet-4.5); crucially, **high capability does not imply low bias** [source-6985ffcd0a3e]. Reasoning-augmented models can show *stronger* self-preference (Qwen3-235B-Thinking SPB=0.540).

**Preference leakage (ICLR 2026).** When the generator of synthetic training data and the LLM judge are related (same model, inheritance, or same family), judges systematically favor students trained on related-generator data — a contamination problem pervasive on major leaderboards [source-c24177e8b061]:
- Same-model leakage scores average 23–24% on Arena-Hard and AlpacaEval 2.0
- "The degree of preference leakage is directly proportional to the amount of synthetic data... no clear threshold separating cases with preference leakage from those without"
- The mechanism is **stylistic**, not semantic: judges can't recognize related students above chance (~29–53%) but still prefer them
- Smaller students show *more* leakage because they absorb the superficial surface features judges use
- SFT produces far more leakage (23.6%) than DPO (5.2%) or ICL (−2.7%)

**Style bias is now dominant; position bias has receded.** A 2025 systematic study found style bias (preference for markdown over identical plain text) at 0.76–0.92 across five frontier models, while position bias is now ≈0 [source-00c241e16245]. Verbosity bias has *reversed* — modern models prefer concise responses. Debiasing recipes calibrated to past bias patterns can backfire.

**No free labels.** Reference quality matters more than judge capability: "providing a weaker judge (e.g. Qwen 2.5 7B) with higher quality references reaches better agreement with human annotators than a stronger judge (e.g. GPT-4o) with synthetic references" [source-a6666b3cf72c]. GPT-4o's Cohen's Kappa drops from 0.78 (with human reference) to 0.14 (with self-generated reference) on hard questions. 35% of MT-Bench math/reasoning reference answers were found to be incorrect or inconsistent [source-a6666b3cf72c].

**Effective mitigations.**
- **Human or verified reference anchors** — the most direct mitigation [source-a6666b3cf72c]
- **Cross-family judges** (not from generator's model family) [source-c24177e8b061]
- **Response paraphrasing** before judgment, to strip style features
- **Chain-of-thought prompting** — the only universally effective debiasing across models (+5 to +13 pp on LLMBar) [source-00c241e16245]
- **Multi-dimensional structured prompts** reduced self-preference bias by 31.5% on average [source-6985ffcd0a3e]
- **Intrinsic quality metrics** (specificity, coherence, solvability, ICE) bypass LLM judges entirely for filtering [source-bcfd4a83bcca]

---

## 5. Privacy Risks in Sensitive Domains

The "synthetic data is privacy-preserving" narrative does not survive empirical scrutiny in medical and financial settings.

**Fine-tuning dramatically elevates PII extraction risk.** On GPT-J-6B, simple template attacks achieve 3.9% extraction on pretrained models but 13–26.6% on fine-tuned ones; multi-query adversarial attacks with <1,000 queries reach **73.1% true-prefix and 58.1% template extraction rates** on fine-tuned models [source-4ebb4409b3b1]. Membership inference AUC reaches **97.8% for full fine-tuning and >80% for LoRA** without DP [source-9a0a04127792].

**Partially synthetic EHR data is highly identifiable.** 82% of VUMC patients and 44% of *All of Us* patients can be re-identified from partially synthetic data at ≥90% precision; fully synthetic data is substantially safer [source-af8e369d7abd]. Many practitioners confuse "partially synthetic" (one-to-one preserved mappings) with fully synthetic and inherit the former's vulnerability without realizing it.

**Standard proxy metrics fail.** The "DCR Delusion" paper shows Distance-to-Closest-Record metrics have **no correlation** with actual MIA vulnerability: synthetic data passing DCR tests still reached high AUC, and one CTGAN output had 92% of records sharing a uniquely identifying feature value entirely missed by DCR [source-19ebf4b13d3f]. A systematic review of 72 financial synthetic-data studies found only **12.3% explicitly assessed privacy preservation** [source-7e07565fd25f].

**LoRA is private under one attack family, not another.** LoRA shows near-zero plagiarism-based memorization [source-dfdfcc5353f7] but >80% MIA AUC without DP [source-9a0a04127792] — "private" depends on the adversary model.

**DP works but has an empirical–theoretical gap.** DP at any ε≥50 converges all fine-tuning methods to ~58% MIA AUC (effectively protected); further tightening ε yields only marginal empirical improvement even though formal guarantees are much stronger [source-9a0a04127792]. DP is a property of generators, not of the released synthetic data itself [source-881a67b11ddd].

**JP Morgan's Six Levels of Privacy** [source-918729f1b987] is the clearest operational framework: Levels 1–3 (PII-masking, noise, generative modeling alone) are insufficient for sensitive finance; **Level 4 (generative modeling + explicit attack testing via MIA) is the minimum recommended**. Levels 5–6 (calibrated and uncalibrated simulation) provide stronger guarantees but sacrifice downstream utility.

**Layer-level attacks.** The UniLeak framework identified "universal activation directions" where interventions at layer 0 extract PII most effectively, and later-layer interventions promote PII token generation — extracting up to 13,399 additional PII records from email-fine-tuned models [source-e2019ce4945a].

---

## 6. Mitigations and Best Practices

The empirical literature converges on a coherent recipe:

**Mixing ratios (data-type and scale dependent).**
- Pre-training: ~30% rephrased synthetic + 70% natural is optimal for convergence speed [source-1c1e941e05b7]; textbook-style pure-generated should stay below 33%.
- Fine-tuning: safe below ~20%; 410M models safe to ~15%, 12B to ~27% (scales roughly logarithmically) [source-dce041ca9ecb].
- Task sensitivity ordering (most to least vulnerable): math → code → factual QA → commonsense → reading comprehension [source-dce041ca9ecb].
- Current industry practice (STaR 15%, Self-Instruct 10%, Constitutional AI 20%) all sit in the safe regime [source-dce041ca9ecb].

**Data workflow.** Accumulation (keep prior real data alongside synthetic) produces bounded error regardless of iterations; replacement causes collapse [source-a2ca30455fcc].

**Generator choice.**
- Use **diverse multi-source generators**, not single-source [source-7d709ca6ed63].
- Mid-sized generators (~8B) often match or beat 70B generators for pre-training data — "bigger generator = better data" is empirically false [source-1c1e941e05b7].
- Keep human data as anchor; fine-tuning on human data most effectively reduces self-preference bias [source-7d709ca6ed63].

**Filtering and curation.** Filter for specificity, coherence, solvability, parameter alignment [source-bcfd4a83bcca]. ECE (calibration) degrades 1–2 iterations before accuracy — a useful early warning [source-dce041ca9ecb]. Step-by-step formatting matters for reasoning [source-5381ebff0c03]. Maintain **protected in-house evaluation benchmarks** because rephrased synthetic data defeats token-level decontamination [source-5381ebff0c03].

**Privacy.** Use DP-SGD + LoRA for sensitive domains [source-acfa58f07996]; test with MIA explicitly (JP Morgan Level 4) [source-918729f1b987]; distinguish partially vs. fully synthetic data [source-af8e369d7abd]; do not rely on DCR or similar proxy metrics [source-19ebf4b13d3f].

**Provenance and governance.** Watermarking makes models "radioactive" — downstream models trained on watermarked outputs are detectable at 5% contamination with p-value <10⁻²⁰ in open-model settings [source-b727e2056b8f]. The **EU AI Act** (effective August 2, 2025 for new GPAI models; enforcement August 2, 2026; August 2, 2027 for pre-existing models) mandates disclosure of AI models used to generate synthetic training data via a public template updated every 6 months; non-compliance penalties reach €10M or 2% of global turnover [source-8fba36b74d45, source-a95c33b20fe6, source-7865f6688076]. Systemic-risk GPAI (>10²⁵ FLOPs) face additional evaluation, incident reporting, and cybersecurity obligations.

---

## 7. Where the Evidence Genuinely Disagrees

These are not glosses over — they are live scientific disputes relevant to practical decisions:

1. **Collapse threshold.** Dohmatob et al. claim even 1% synthetic data plateaus scaling laws (stylized regression models) [source-1faec8b1a9de]; Meta FAIR's empirical study at 3B parameters directly refutes this for rephrased synthetic data [source-1c1e941e05b7]. Gerstgrasser shows accumulation prevents collapse entirely [source-a2ca30455fcc]. No reconciliation at frontier scale exists.

2. **Phi-4 interpretation.** Microsoft's report establishes synthetic-heavy training can exceed the teacher on STEM benchmarks [source-da9c18469bc5], but the same report documents synthetic-only underperformance on knowledge-heavy tasks and increased hallucinations [source-47d03bb6f6d0]. Whether Phi-4 is a general proof or a domain-specific optimization is contested.

3. **Bias dynamics.** Kattamuri et al. (equilibrium convergence, single 2B model, 3 generations) [source-3017c54b4824] vs. Wyllie et al. (complete minority erasure under 100% synthetic recursive training) [source-05ff198b7a07] — the difference is workflow, not contradiction, but practitioners can plausibly land in either regime.

4. **Embedding vs. behavioral fairness metrics diverge.** A mitigation that reduces behavioral bias by 91% can simultaneously increase embedding bias — single-metric evaluation is unsafe [source-3017c54b4824].

5. **LoRA privacy.** "Near-zero plagiarism" [source-dfdfcc5353f7] coexists with ">80% MIA AUC without DP" [source-9a0a04127792] on the same technique. The disagreement is about what counts as "private."

6. **Generator diversity × target size.** Multi-source generally reduces collapse, but for 70B target models can increase adversarial vulnerability [source-7d709ca6ed63].

7. **Position and verbosity biases have inverted.** Mitigations calibrated to older LLM judges can be counterproductive for current models [source-00c241e16245].

---

## 8. Bottom Line for Practitioners

Synthetic data is a high-leverage tool with real failure modes, not a free lunch and not a trap. The evidence supports:

- **Use it, but cap proportions**: <20% for fine-tuning, ~30% for pre-training with rephrased data; monitor calibration as early warning.
- **Diversify generators** and preserve human-authored anchors.
- **Quality-filter aggressively** — 14% filtered often beats 100% unfiltered.
- **Evaluate with cross-family judges, human or verified references, and intrinsic metrics** — trust nothing from a judge in the same family as the generator.
- **Treat "privacy-preserving synthetic data" as a claim requiring MIA-based validation**, not an inherent property.
- **Assume long-horizon, multi-generational, frontier-scale effects are under-measured** and favor accumulation over replacement.
- **Comply with EU AI Act disclosure** and consider watermarking for provenance.

The benefits are concrete and reproducible. The risks are conditional on choices practitioners can control — but only if they know to control them.

---

## Confidence

**High.** The investigation covered seven sub-questions with strong multi-source convergence on benefits, mitigations, evaluation pitfalls, and privacy, plus a structured adversarial dispatch on the most contested claim (model collapse) that meaningfully tightened the report. Core factual claims rest on peer-reviewed work (*Nature*, FAccT, ICLR 2026, SACMAT) supplemented by rigorous preprints from Meta FAIR, Microsoft Research, Google Research, JP Morgan, and academic groups.

