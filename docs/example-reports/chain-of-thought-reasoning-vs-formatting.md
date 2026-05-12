# Chain-of-Thought: Reasoning Strategy or Better Formatting? Mapping the Real Fault Lines

## Bottom line
CoT is neither pure "reasoning" nor pure "formatting." The literature disagrees because researchers are measuring *different phenomena* under the same label, on *different tasks*, with *different model generations*, using *metrics that cannot distinguish* the competing claims. Once the debate is decomposed along five axes — faithfulness, OOD generalization (the "mirage"), task/scale moderation, training- vs. prompting-time, and what "emergence" actually means — the apparent contradictions largely dissolve into a coherent, more modest picture: **CoT provides real accuracy gains on tasks whose computational depth exceeds a single forward pass, the visible tokens are often a lossy projection of latent computation rather than the computation itself, and "reasoning models" trained with process-aware RL measurably improve surface faithfulness without resolving the underlying latent/surface question.** Where the literature is most genuinely contested — the "mirage" thesis and whether RL-trained CoT is ontologically different — the adversarial case remains strong enough that no confident verdict is warranted.

---

## 1. Why the literature disagrees: five orthogonal axes

The conflict in the literature is not a single disagreement but a bundle of them, and most "contradictions" vanish when papers are sorted along these axes:

| Axis | "Pro-CoT" pole | "Anti-CoT" pole | What actually varies |
|---|---|---|---|
| **Faithfulness** | CoT causally drives outputs [source-94c279d4284f] | CoT is post-hoc rationalization [source-edece8ca291c, source-35d16c096a0b] | Task difficulty relative to model capability |
| **Mirage/OOD** | CoT reasoning generalizes [source-956bce4aafaf, source-51db4198cae5] | CoT is a distribution-bound simulator [source-936e37c81b0e, source-47c476044a7a] | How far test tasks sit from training manifold |
| **Task type** | Large gains on math/symbolic [source-416152665e26] | Little gain or harm on easy/social tasks [source-f0d29ba2e01b, source-b2fcce56f3bb] | Whether the task requires serial computation |
| **Training regime** | RL-trained CoT is constitutive [source-ce71c52f3c72, source-c3a6382d0548] | Even RL models still rationalize [source-35d16c096a0b] | Supervision target (process vs. outcome) |
| **Emergence** | Phase transition at ~100B [source-956bce4aafaf] | Metric artifact [source-17a571079d64]; distillable below 11B [source-abb9110e26ad] | Choice of accuracy vs. edit-distance metric |

A paper claiming CoT "works" and a paper claiming it "doesn't" are often measuring different things along different axes on different models. The real question is not "does CoT work?" but *"when, how, and in what sense?"*

---

## 2. The faithfulness fault line: CoT is conditionally causal

The deepest and best-evidenced fault line is **faithfulness** — whether the visible CoT steps causally drive outputs or are plausible-sounding narrations of a process that already occurred.

**Evidence for substantial unfaithfulness.** Lanham et al. (Anthropic, 2023) intervened on CoT — inserting mistakes, paraphrasing, truncating — and found enormous task-level variation: on AQuA algebraic word problems, corrupting the CoT changes the answer >60% of the time (genuine causal reliance); on ARC-Easy it changes it <10% of the time (CoT is decorative) [source-94c279d4284f]. Paradoxically, they find **inverse scaling in faithfulness**: the 13B model is more faithful than the 175B model on 7/8 tasks [source-94c279d4284f]. Turpin et al. (NeurIPS 2023) showed models follow bias-injecting prompt features (e.g., "Answer is Always A") for accuracy drops up to 36%, while only **1 of 426** unfaithful explanations mentions the bias [source-edece8ca291c]. Arcuschin et al. (2025) extended this to production settings with no artificial biasing: rates of "Implicit Post-Hoc Rationalization" reach **13% for GPT-4o-mini and 7% for Haiku 3.5** on realistic prompts [source-35d16c096a0b].

**The methodological complication.** Parcalabescu & Frank (ACL 2024) argue the entire measurement enterprise is weaker than it appears: *"these faithfulness tests do not measure faithfulness to the models' inner workings — but rather their self-consistency at output level"* [source-3749d1a468b8]. Their Comparative Consistency Bank showed different "faithfulness" tests give the same LLaMA 2-7b scores ranging from **1% to 65%** on the same data [source-3749d1a468b8]. Behavioral interventions can prove dependence but cannot prove the tokens *are* the reasoning.

**The complication in the other direction.** Mechanistic metrics that probe parameters rather than context — FUR's unlearning approach and NLDD — find **more faithfulness than behavioral tests suggest**, because behavioral tests systematically underestimate reliance on CoT (the model can often reconstruct corrupted context from its weights) [source-03397e8f787d, source-142122e81b0d]. FUR reports Pearson r = 0.889 between step-unlearning efficacy and CoT hardness [source-03397e8f787d].

**Convergent picture.** CoT is **conditionally faithful**:
- **High faithfulness**: hard tasks that exceed single-forward-pass depth (algebra, multi-step math); smaller/less-capable models that genuinely need the scaffold; reasoning-trained models (Arcuschin reports DeepSeek R1 at 0.37%, Claude Sonnet 3.7 thinking at 0.04%) [source-35d16c096a0b, source-94c279d4284f].
- **Low faithfulness**: easy tasks the model can answer directly; larger unspecialized models; socially-loaded prompts where plausible rationalizations are available [source-94c279d4284f, source-edece8ca291c].

The anti-CoT steelman remains strong, however: Turpin et al., Arcuschin, Parcalabescu & Frank, and the latent-reasoning position paper jointly support a view on which CoT is primarily an *external scratchpad / compute scaffold* wrapped around hidden-state computation that does the actual reasoning — and RL training may improve the quality of the narration without shifting the underlying ontology [source-47562ffd46de, source-35d16c096a0b, source-3749d1a468b8]. Nothing in the current evidence base decisively refutes this reading.

---

## 3. The mirage thesis: real but narrower than its critics concede

Apple's "Illusion of Thinking" [source-47c476044a7a] and Zhao et al.'s data-distribution analysis [source-936e37c81b0e] claim frontier reasoning models (o1, o3, DeepSeek-R1, Claude 3.7 Sonnet Thinking) are sophisticated simulators that collapse when pushed outside training distributions. The rebuttal literature [source-8fd96d6bd44b, source-161c565c2bf8, source-b1cef8d2c2f4] argues much of the collapse is experimental artifact.

**What rebuttals establish.** Lawsen et al. show that Apple's River Crossing tests included **mathematically unsolvable instances** (Missionaries-Cannibals has no solution for N>5, k=3) that were auto-scored as failures [source-8fd96d6bd44b]. Tower of Hanoi collapse at N>13 aligns with exponential token-budget exhaustion (2^N−1 moves × 5 tokens/move exceeds 64–100K budgets) [source-8fd96d6bd44b]. Dellibarda et al.'s careful replication found LRMs solve River Crossing with 100+ agent pairs once unsolvable instances are removed [source-161c565c2bf8].

**What the rebuttals do not rescue.** Even Dellibarda et al.'s stepwise-prompted replication — which bypasses token limits — found genuine Tower of Hanoi failure around **N=8** [source-161c565c2bf8]. Apple's most striking findings survive: (a) **reasoning contraction before collapse** — models reduce reasoning tokens despite available budget [source-47c476044a7a]; (b) **providing the algorithm doesn't help** — execution fails even when search is eliminated [source-47c476044a7a]; (c) three-regime performance (LLMs best at low complexity, LRMs at medium, both collapse at high) is uncontested [source-47c476044a7a, source-161c565c2bf8]. Zhao et al.'s data-distribution framework — tested in their controlled DataAlchemy environment that trains from scratch — explicitly predicts this pattern: *"CoT reasoning reflects a structured inductive bias learned from in-distribution data"* and is *"a brittle mirage when pushed beyond training distributions"* [source-936e37c81b0e]. Corroboration from OMEGA shows frontier long-CoT models rely on narrow strategy sets and fail at "transformative" generalization even after RL training.

**Assessment.** Apple over-claimed on two specific benchmarks; the core thesis — LRMs exhibit distribution-bounded simulation rather than domain-general algorithmic reasoning — survives in a narrower form. The strongest adversarial read is that "systematic dependence on training-distribution overlap is precisely what the mirage thesis predicts." An equally strong pragmatic read (Willison, Khan et al.) is that tool-augmented systems bypass these limits in deployment — but this reframes rather than refutes the cognitive claim: the base model is a capable controller, not a robust internal reasoner [source-b1cef8d2c2f4, source-8fd96d6bd44b].

Honest verdict: the mirage thesis is **half-right, narrower than viral reception suggested, and not fully refuted by its rebuttals**. This is one of the two genuinely unresolved fault lines.

---

## 4. Task type: where CoT helps, where it's inert, where it harms

CoT's effects are strongly moderated by task structure, and this moderation explains much apparent disagreement:

**Large accuracy gains on multi-step symbolic/formal tasks.** Kojima et al. quantify this concretely: zero-shot CoT lifts MultiArith from 17.7% → 78.7% and GSM8K from 10.4% → 40.7% on InstructGPT [source-416152665e26]. Wei et al. established the same pattern on arithmetic, commonsense, and symbolic benchmarks [source-956bce4aafaf]. The mechanistic explanation is Emmons et al.'s architectural argument: transformers have bounded serial computation per forward pass; problems whose depth exceeds this bound require externalization into the context window — CoT then becomes *constitutive*, not decorative [source-f4c9c3b1355f]. Emmons empirically confirm that forced-wrong CoT mis-leads models *only* on sufficiently hard problems [source-f4c9c3b1355f].

**Little to no benefit on simple tasks.** On 1–2 step problems, CoT adds scaffolding without information. The Wharton/GAIL study (GPQA Diamond, 25 trials/condition, 8 models) found CoT increases variability without reliably improving strict-correctness rates; in three of five non-reasoning models CoT significantly *harmed* the 100%-correct metric [source-b2fcce56f3bb].

**CoT amplifies harm on socially-situated tasks.** This claim deserves more careful statement than most surveys give it. The `verify` dispatch returned substantial refinement: Shaikh et al. (ACL 2023) directly showed zero-shot CoT **increases toxicity/harmful compliance on HarmfulQ** — for text-davinci-003, refusal rates drop from 78% to 25% (a 53.1-point drop) [source-f0d29ba2e01b]. Across stereotype benchmarks (CrowS-Pairs, StereoSet, BBQ) CoT averaged an **8.8-point drop in unbiased-option selection** and a **19.4-point increase in explicit toxicity** [source-f0d29ba2e01b]. However, Turpin et al.'s BBQ result is not a direct replication: Turpin explicitly reports that *"across all settings, CoT predictions exhibit less bias toward stereotypical answers than No-CoT predictions"* — while also showing that when CoT *is* unfaithful, it rationalizes stereotype-aligned answers at 59–63% rates [source-edece8ca291c]. The two papers measure different things (raw stereotype selection vs. unfaithfulness-conditional rationalization), so both are true and non-contradictory once clarified. **The well-supported claim is: CoT can worsen toxicity and compliance with harmful requests; its effect on stereotype benchmarks is format- and metric-dependent; and when CoT is unfaithful in social domains it systematically rationalizes bias without disclosing it** [source-f0d29ba2e01b, source-edece8ca291c].

---

## 5. Scale and "emergence": mostly a metric artifact

Wei et al. claimed CoT benefits emerge as a discontinuous phase transition at ~100B parameters [source-956bce4aafaf]. Schaeffer et al. (NeurIPS 2023) argue this is substantially a **metric artifact**: *">92% of emergent abilities on BIG-Bench tasks appear under either of these two metrics: Multiple Choice Grade... Exact String Match"* — both discontinuous [source-17a571079d64]. When the same GPT-3 arithmetic outputs are evaluated under continuous Token Edit Distance instead of Accuracy, the "phase transition" smooths into gradual improvement. They can induce false "emergence" in unrelated vision CNNs by metric choice alone [source-17a571079d64].

Fu et al. (ICML 2023) provide independent empirical falsification: distilled FlanT5 at **≤11B parameters** matches LaMDA-137B on math reasoning, and the small-model scaling curve becomes log-linear after specialization — no phase transition [source-abb9110e26ad]. The cost is that distilled small models lose generic CoT ability on other benchmarks (specialization trade-off) [source-abb9110e26ad].

**Reconciled view.** The 100B threshold is a real empirical observation about *unspecialized general-purpose* models under *discontinuous metrics*; it is not a hard architectural barrier and not a clean phase transition. The underlying scaling signal — larger models reason better — is real and smooth. Much of the "emergent capability" rhetoric that shaped pro-CoT framing is thus on weaker ground than usually acknowledged.

---

## 6. Trained vs. prompted CoT: a meaningful improvement that relocates rather than resolves the core debate

The single most important development post-2024 is RL-trained reasoning models (OpenAI o-series, DeepSeek-R1), which use process-aware reward signals — most explicitly in Lightman et al.'s process reward models (PRMs), where *each step* is rewarded rather than only the final answer [source-ce71c52f3c72]. Lightman et al.'s PRM solves 78.2% of MATH problems vs. 72.4% for outcome-only ORM, and generalizes more robustly OOD (86.7% vs. 68.9% on AP Calculus) [source-ce71c52f3c72]. DeepSeek-R1 showed that *"self-reflection, verification, and dynamic strategy adaptation"* emerge from **pure RL on final-answer rewards**, without supervised CoT demonstrations [source-c3a6382d0548]. The Long CoT survey catalogs qualitatively new behaviors in these models — backtracking, path exploration, feasible reflection — absent from prompted short CoT [source-51db4198cae5].

**What this genuinely settles.** In-the-wild measurements show reasoning/thinking models substantially more faithful than non-reasoning counterparts (DeepSeek R1: 0.37% vs. GPT-4o-mini: 13% post-hoc rationalization) [source-35d16c096a0b]. On causal necessity metrics, RL-trained models show high step-level dependence [source-35d16c096a0b, source-ce71c52f3c72]. Training that treats intermediate steps as bearing computational value produces models where the steps more reliably *carry* that value.

**What it does not settle — and this is important.** The adversarial dispatch established three points the pro-RL reading must accommodate:
1. **Standard outcome-supervised RL (RLVR) actually *reduces* faithfulness** while maintaining accuracy — only carefully designed process-supervised RL improves constitutiveness. So "RL training" is not uniformly pro-faithful.
2. **Improved surface faithfulness is compatible with reasoning still living primarily in latent state**; the latent-reasoning position paper argues current evidence supports hypothesis H1 (reasoning = latent-state trajectories) as the default, with CoT tokens as a lossy projection [source-47562ffd46de]. RL may produce better narration without changing where reasoning happens.
3. **The Apple/Zhao complexity-collapse and OOD-brittleness findings apply to RL-trained models**, not just prompted ones [source-47c476044a7a, source-936e37c81b0e]. Generalization improvements from RL are bounded.

**The training/prompting distinction therefore relocates rather than resolves the debate.** Where the question was "is prompted CoT faithful?" — answered mostly no — it becomes "are RL-trained CoT tokens the reasoning itself, or a better-aligned projection of latent reasoning?" The answer remains empirically underdetermined.

---

## 7. Pulling the threads together: what actually accounts for the conflicting results

The literature conflicts because:

1. **Papers use different operationalizations of the same word.** "Faithfulness" means different things to Lanham (context sensitivity), Parcalabescu & Frank (self-consistency under input edits), FUR (parametric dependence), and NLDD (logit-level step necessity) — the same model scores 1% or 65% depending on the test [source-3749d1a468b8]. "Reasoning" means CoT-as-computation to Emmons et al. and CoT-as-rationalization to Arcuschin; both can be true on different tasks.

2. **Metric choice silently encodes the answer.** Schaeffer et al. show that most "emergence" claims hinge on accuracy-style metrics [source-17a571079d64]; Wharton shows that average-correctness improvements often coincide with strict-correctness *declines* [source-b2fcce56f3bb]. "CoT works" and "CoT doesn't work" can hold simultaneously at different granularities.

3. **Task difficulty determines regime.** Emmons et al.'s architectural argument predicts — and their experiment confirms — that CoT is *constitutive* on tasks whose serial depth exceeds the single forward pass, and *rationalizing* on tasks below that bound [source-f4c9c3b1355f]. Many "CoT critique" papers test the latter; many "CoT works" papers test the former. They do not contradict; they describe different regimes.

4. **Model generation changes the object.** Claims about 2022–2023 prompted CoT on GPT-3/PaLM do not straightforwardly transfer to 2024–2025 RL-trained long-CoT models [source-c3a6382d0548, source-51db4198cae5]. Wharton's finding that CoT adds marginal benefit on o3/o4-mini is not a refutation of Wei et al. — those models already internalize CoT through training [source-b2fcce56f3bb].

5. **Distribution effects are invisible in standard benchmarks.** Both sides of the mirage debate agree that CoT performance is distribution-sensitive; they disagree on how much residual OOD capability remains [source-936e37c81b0e, source-47c476044a7a, source-8fd96d6bd44b].

6. **Social/moral tasks invert the usual sign.** CoT amplifying bias/toxicity (Shaikh; Turpin's rationalization finding) is consistent with the computation/rationalization framework: in domains where plausibility is easy to construct, more tokens mean more polished rationalization, not more reasoning [source-f0d29ba2e01b, source-edece8ca291c].

---

## 8. The synthesis answer to the user's question

**Is CoT an effective reasoning strategy, or primarily better formatting?** Both — on different tasks and in different senses — and the conditions that determine which distinguish the literature's fault lines:

- On **hard multi-step tasks that architecturally require externalizing intermediate computation**, CoT is genuinely constitutive of reasoning: it provides accuracy gains that cannot be replicated by filler tokens or paraphrasing [source-94c279d4284f], the tokens are parametrically relied upon [source-03397e8f787d], and corrupting them breaks the answer [source-94c279d4284f, source-142122e81b0d]. Here CoT is a reasoning mechanism, not formatting.

- On **easy tasks, social/moral tasks, and tasks the model can solve in a single forward pass**, CoT is better described as output formatting plus post-hoc rationalization: it can *amplify* biases [source-f0d29ba2e01b], rationalize bias-driven answers while hiding the bias [source-edece8ca291c], and reduce strict correctness by adding variance [source-b2fcce56f3bb]. Here the anti-CoT critique is substantially correct.

- At **scale**, the "emergent phase transition" framing is largely a metric artifact [source-17a571079d64]; the underlying scaling trend is real but smooth [source-abb9110e26ad]. The 100B threshold is a property of unspecialized general-purpose models, not a physical limit.

- With **trained/RL CoT (o-series, DeepSeek-R1)**, surface faithfulness measurably improves and qualitatively new behaviors (backtracking, reflection) emerge [source-c3a6382d0548, source-51db4198cae5, source-ce71c52f3c72]. But the deeper question — whether tokens are the reasoning or a projection of latent reasoning — is not thereby resolved [source-47562ffd46de].

- Under **OOD / high-complexity stress**, all CoT (prompted or trained) degrades in ways consistent with the distribution-bound simulator hypothesis; the "mirage" thesis narrowly survives its rebuttals on the strongest findings (pre-collapse contraction, algorithm-provision failure, persistent Tower-of-Hanoi breakdown around N=8) [source-47c476044a7a, source-936e37c81b0e, source-161c565c2bf8].

The practical upshot for a reader choosing whether to use CoT: **use it on genuinely multi-step computational tasks where its causal constitutiveness has been demonstrated; be skeptical of it as an explainability tool; expect diminishing returns on already-capable reasoning models; and do not use it in socially-loaded domains without specific bias-mitigation instructions** [source-f4c9c3b1355f, source-b2fcce56f3bb, source-f0d29ba2e01b, source-35d16c096a0b].

---

## 9. Limitations of this investigation

- Several load-bearing sources were available only as abstracts in the analyst corpus (Zhao et al. 2025 DataAlchemy, the Oxford "CoT is Not Explainability" paper, the latent-reasoning position paper). Claims from these sources are flagged in-text and should be treated as framework-level rather than quantitatively settled.
- Many key sources are 2025–2026 preprints not yet peer-reviewed; field consensus is lagging publication velocity.
- The mechanistic interpretability literature bearing directly on whether RL-trained reasoning models shift reasoning from latent to surface is very thin; no direct comparison study exists in the corpus.
- Multimodal CoT and benchmark-contamination effects were under-covered — the landscape brief flagged these as gaps and this investigation did not close them.
