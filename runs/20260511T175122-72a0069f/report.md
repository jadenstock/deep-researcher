# Research report

**Query:** What are the real-world risks and benefits of using synthetic data to train or fine-tune large language models? Focus on data quality, bias, and evaluation.

# Research report

**Query:** What are the real-world risks and benefits of using synthetic data to train or fine-tune large language models? Focus on data quality, bias, and evaluation.

_No answered questions in memory._

## Sources

- **[source-7740343cfe3e]** [Synthetic Data Generation Using Large Language Models: Advances in Text and Code](https://arxiv.org/abs/2503.14023) - not-tiered
  - Discusses cost-effectiveness, broad coverage, controllable diversity as benefits. Also covers factual inaccuracies, distributional realism gaps, risks of overfitting and distribution shift in closed-loop pipelines.
- **[source-a727f8cca2ba]** [Examining synthetic data: The promise, risks and realities | IBM](https://www.ibm.com/think/insights/ai-synthetic-data) - not-tiered
  - Warns of risk of synthetic data not accurately representing real-world population diversity, producing potential bias in models that fail to perform equitably across demographic groups.
- **[source-1b078a28fe43]** [Demystifying Synthetic Data in LLM Pre-training: A Systematic Study of Scaling Laws, Benefits, and Pitfalls](https://arxiv.org/html/2510.01631v1) - not-tiered
  - Argues synthetic data boosts reasoning with large training budgets where natural text offers diminishing returns, but acknowledges limited factual grounding and increased hallucination risks.
- **[source-17d90a9e7d3f]** [Synthetic data: A secret ingredient for better language models | Red Hat](https://www.redhat.com/en/blog/synthetic-data-secret-ingredient-better-language-models) - not-tiered
  - Covers model collapse — where repeated training on synthetic data can degrade model performance, leading to hallucinations or oversimplified outputs.
- **[source-97895b2c6f23]** [Challenges and Pitfalls of Using Synthetic Data for LLMs | Medium](https://medium.com/foundation-models-deep-dive/challenges-and-pitfalls-of-using-synthetic-data-for-llms-7337fcda1316) - not-tiered
  - Examines five key challenges: fidelity gaps, model collapse, bias amplification, computational costs, and evaluation difficulties.
- **[source-2d342aa4b7db]** [Best Practices and Lessons Learned on Synthetic Data for Language Models](https://arxiv.org/html/2404.07503v1) - not-tiered
  - Discusses potential for synthetic data to amplify biases or introduce new biases if not carefully designed and validated; argues rigorous testing and fairness assessments are necessary.
- **[source-82da17c4e6c7]** [Synthetic Eggs in Many Baskets: The Impact of Synthetic Data Diversity on LLM Fine-Tuning](https://arxiv.org/html/2511.01490v1) - not-tiered
  - Finds that diversity of data-generating models jointly affects adversarial robustness of fine-tuned models; model fine-tuning decreases self-preference bias most when using human data.
- **[source-cd5829bb0c63]** [Quality Matters: Evaluating Synthetic Data for Tool-Using LLMs](https://arxiv.org/html/2409.16341v2) - not-tiered
  - Shows that LLMs trained on less but higher-quality synthetic data can outperform those trained on larger noisy datasets. Uses intrinsic metrics and ICE to compare training sets of varying quality.
- **[source-afd0c437e771]** [Guide to Ethical Fine-Tuning of Large Language Models | Tonic.ai](https://www.tonic.ai/guides/ethical-fine-tuning-llm-synthetic-data) - not-tiered
  - Covers use of synthetic data to reduce privacy risks while maintaining realism; frequent evaluations to detect bias, performance, and privacy risk early in fine-tuning.
- **[source-f4f81cf8247d]** [Towards Understanding Bias in Synthetic Data for Evaluation](https://www.alphaxiv.org/overview/2506.10301) - not-tiered
  - Investigates LLM-generated evaluation bias: LLMs are more lenient judges, inflating performance metrics by assigning higher relevance scores and showing preference for systems aligned with their own generative patterns.
- **[source-df442ac7fa30]** [On LLMs-Driven Synthetic Data Generation, Curation, and Evaluation: A Survey](https://arxiv.org/html/2406.15126) - not-tiered
  - Provides a unified framework for synthetic data generation workflow; highlights gaps in existing research and outlines prospective avenues. Notes naively prompting LLMs can yield superficial or biased data.
- **[source-3aaa9b2a583a]** [Equilibrium Dynamics and Mitigation of Gender Bias in Synthetically Generated Data](https://arxiv.org/html/2511.10689) - not-tiered
  - Investigates gender bias dynamics across recursive text generation generations; reveals equilibrium dynamics rather than monotonic amplification — low initial bias amplifies toward model's inherent bias level.
- **[source-53296c7f6b67]** [Fine-tune LLMs with synthetic data for context-based Q&A using Amazon Bedrock | AWS](https://aws.amazon.com/blogs/machine-learning/fine-tune-llms-with-synthetic-data-for-context-based-qa-using-amazon-bedrock/) - not-tiered
  - Describes LLM-as-a-judge evaluation for quality dimensions including correctness, helpfulness, and responsible AI criteria such as answer refusal and harmfulness.
- **[source-494dfa1c13f3]** [Synthetic Data: Benefits and Techniques for LLM Fine-Tuning in 2025 | Label Your Data](https://labelyourdata.com/articles/llm-fine-tuning/synthetic-data) - not-tiered
  - Covers using synthetic data to balance out real-world data biases and limitations; various techniques for producing realistic and diverse training data.
- **[source-55892ad63bfc]** [AI models collapse when trained on recursively generated data | Nature](https://www.nature.com/articles/s41586-024-07566-y) - not-tiered
  - Indiscriminate use of model-generated content in training causes irreversible defects in the resulting models, in which tails of the original content distribution disappear.
- **[source-5558e2f4063e]** [How Bad is Training on Synthetic Data? A Statistical Analysis of Language Model Collapse](https://arxiv.org/html/2404.05090) - not-tiered
  - Model collapse refers to the deterioration in performance when new models are trained on synthetic data generated from previously trained models. Recursive training loop makes tails of original distribution disappear.
- **[source-14e5ab5a763d]** [Is Model Collapse Inevitable? Breaking the Curse of Recursion by Accumulating Real and Synthetic Data](https://arxiv.org/abs/2404.01413) - not-tiered
  - Confirms replacing real data with synthetic data tends towards model collapse, but demonstrates that accumulating successive generations of synthetic data alongside real data avoids this.
- **[source-7780c9fed32e]** [Escaping Model Collapse via Synthetic Data Verification: Near-term Improvements and Long-term Convergence](https://arxiv.org/html/2510.16657v1) - not-tiered
  - Shows that retraining with filtered/verified synthetic data by a verifier yields much clearer and more realistic outputs versus unverified retraining which leads to severe degradation and mode collapse.
- **[source-8bbcdc1ded74]** [Self-Instruct: Aligning Language Models with Self-Generated Instructions](https://arxiv.org/html/2212.10560) - not-tiered
  - Introduces Self-Instruct framework for improving instruction-following by bootstrapping off a model's own generations. Addresses limitations of human-written instruction data in quantity, diversity, and creativity.
- **[source-c82196cfc5c1]** [Benchmarking Large Language Models Under Data Contamination: A Survey from Static to Dynamic Evaluation](https://arxiv.org/html/2502.17521v2) - not-tiered
  - Covers risk of evaluation data overlap in LLMs pre-trained on massive web-scraped datasets; discusses both human-annotated and synthetic datasets in post-training fine-tuning phases.
- **[source-ff03e1fe8d8f]** [Benchmark Data Contamination of Large Language Models: A Survey](https://arxiv.org/abs/2406.04244) - not-tiered
  - Covers when language models inadvertently incorporate evaluation benchmark information from training data, leading to inaccurate or unreliable performance during evaluation phase.
- **[source-a6cd6e969b0e]** [What Has Been Lost with Synthetic Evaluation?](https://arxiv.org/html/2505.22830) - not-tiered
  - Shows that synthetic data is not always a good predictor of relative model performance, and that bias does not fully explain why synthetic benchmarks tend to be easier than real-world ones.
- **[source-b96772c3338b]** [Evaluation data contamination in LLMs: how do we measure it and (when) does it matter?](https://arxiv.org/abs/2411.03923) - not-tiered
  - Proposes ConTAM analysis method; shows contamination may have a much larger effect than reported in recent LLM releases and benefits models differently at different scales.
- **[source-09c0b536ca7f]** [Model collapse - Wikipedia](https://en.wikipedia.org/wiki/Model_collapse) - not-tiered
  - Training on synthetic data from previous models causes consistent decrease in lexical, syntactic, and semantic diversity through successive iterations.
- **[source-f44d6008ff87]** [LLMs generating synthetic clinical datasets: feasibility and comparative analysis with real-world perioperative data](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11836953/) - not-tiered
  - Clinical data access constrained by privacy regulations. LLMs generate synthetic clinical data with reduced reliance on domain expertise; assesses feasibility of generating realistic tabular clinical data.
- **[source-51702ce98e49]** [Fidelity, Diversity, and Privacy: A Multi-Dimensional LLM Evaluation for Clinical Data Augmentation](https://arxiv.org/html/2604.27014) - not-tiered
  - Multi-dimensional evaluation of LLM-generated synthetic mental health data across fidelity, diversity, and privacy. Uses DeepSeek-R1 and other models for mental health report generation.
- **[source-f2dd2befbf4e]** [Beyond Consensus: Mitigating the Agreeableness Bias in LLM Judge Evaluations](https://arxiv.org/html/2510.11822) - not-tiered
  - LLM-as-a-judge suffers from agreeableness bias: LLMs show strong positive bias, high true positive rate (96%) but poor at identifying invalid outputs. Affects reliability as evaluators.
- **[source-d9d2435ada6b]** [Label Effects: Shared Heuristic Reliance in Trust Assessment by Humans and LLM-as-a-Judge](https://arxiv.org/html/2604.05593) - not-tiered
  - LLM judges are biased by disclosed source labels — both humans and LLMs assign higher trust to human-labeled content over the same content labeled as AI-generated.
- **[source-b627c19070d9]** [One Token to Fool LLM-as-a-Judge](https://arxiv.org/html/2507.08794) - not-tiered
  - Reward hacking vulnerability in LLM-as-judge: superficial inputs ('master keys' like punctuation or generic openers) can fool generative reward models used in RLVR training pipelines.
- **[source-e8d3519ce7d5]** [Phi-4 Technical Report | Microsoft Research](https://arxiv.org/html/2412.08905v1) - not-tiered
  - Phi-4 blends synthetic and organic data; outperforms Llama 3.3 70B and Qwen 2.5 on math and reasoning benchmarks despite being smaller. Detailed discussion of synthetic data strategy.
- **[source-af344d2600ec]** [Synthetic Data, Data Protection and Copyright in an era of Generative AI](https://www.researchgate.net/publication/395392904_Synthetic_Data_Data_Protection_and_Copyright_in_an_era_of_Generative_AI) - not-tiered
  - Covers copyright risks of training on web-scraped data and discusses how synthetic data can reduce copyright violation risk and cost for AI training.
- **[source-c509b8bd333a]** [Human Preferences in LLM Latent Space: Reliability of Synthetic Data in Voting Outcome Prediction](https://arxiv.org/html/2502.16280) - not-tiered
  - Questions validity and reliability of using LLMs as substitutes for human respondents in surveys; examines how demographic attributes and prompt variations influence latent opinion mappings.
- **[source-b701119de1f3]** [Privacy-Aware Clinical NLP with Differentially Private Fine-Tuning of Large Language Models](https://doi.org/10.71465/fbg549) - not-tiered
  - Privacy framework for LLM training on clinical data using differential privacy; de-identification alone insufficient as models remain vulnerable to membership inference attacks.
- **[source-cc411f628ab9]** [Towards Theoretical Understandings of Self-Consuming Generative Models](https://arxiv.org/html/2402.11778) - not-tiered
  - Constructs theoretical framework to evaluate training in self-consuming loops with recursive generations of models on mixtures of real and synthetic data; derives bounds on TV distance between synthetic and original distributions.
- **[source-ace87a241e6d]** [Model Collapse Demystified: The Case of Regression](https://arxiv.org/html/2402.07712) - not-tiered
  - Analytic formulae quantifying model collapse in high-dimensional regression; shows how performance degrades recursively as models train on data from previous generations.
- **[source-2c98d06ae737]** [A Tale of Tails: Model Collapse as a Change of Scaling Laws](https://arxiv.org/html/2402.07043) - not-tiered
  - Examines scaling laws in regimes with synthetic data; addresses whether future models improve or collapse as synthetic data makes its way into training corpus, connecting to tail behavior.
- **[source-6c584aa7fad9]** [Large Language Models Suffer From Their Own Output: An Analysis of the Self-Consuming Training Loop](https://arxiv.org/html/2311.16822) - not-tiered
  - First study on self-consuming training loops in LLMs; shows reduction in quality and diversity comparable to image generation domain, leading to model collapse.
- **[source-6cbab83a1673]** [The Curse of Recursion: Training on Generated Data Makes Models Forget](https://arxiv.org/html/2305.17493) - not-tiered
  - Foundational work on model-generated content in training causing irreversible defects; models forget original data distribution when trained recursively on generated outputs.
- **[source-ead829384973]** [Phi-4 Technical Report - Microsoft Research](https://www.microsoft.com/en-us/research/wp-content/uploads/2024/12/P4TechReport.pdf) - not-tiered
  - 14B parameter model trained with centralized focus on data quality. Incorporates synthetic data generation pipeline with seeds from high-quality reasoning data. Blends synthetic and organic data for strong math/reasoning performance.
- **[source-8a171c9d239a]** [Phi-4 Technical Report - Microsoft Research (Publication Page)](https://www.microsoft.com/en-us/research/publication/phi-4-technical-report/) - not-tiered
  - Presentation of phi-4, a 14-billion parameter language model developed with a training recipe focused on data quality. Strategically incorporates synthetic data alongside web sources.
- **[source-9f3b6aba790d]** [Phi-4: Redefining Language Models with Synthetic Data](https://www.analyticsvidhya.com/blog/2024/12/phi-4/) - not-tiered
  - Analysis of Phi-4's approach to prioritizing data quality over quantity, with improvements in reasoning, STEM, and coding tasks.
- **[source-77b79bd919c3]** [Phi-4 proves that a 'data-first' SFT methodology is the new differentiator | VentureBeat](https://venturebeat.com/ai/phi-4-proves-that-a-data-first-sft-methodology-is-the-new-differentiator/) - not-tiered
  - Discusses Phi-4's filtering strategy for quality over quantity, noting that generic data is often too easy or too hard without learning signal.
- **[source-58971609e6c1]** [Understanding and Mitigating Bias Inheritance in LLM-based Data Augmentation on Downstream Tasks](https://arxiv.org/html/2502.04419) - not-tiered
  - Generating synthetic datasets via LLMs propagates and amplifies inherent biases through iterative training—termed bias inheritance. Presents first systematic investigation in understanding, analyzing, and mitigating bias amplification across downstream tasks.
- **[source-babfc2bd3a74]** [Improving Equity in Health Modeling with GPT4-Turbo Generated Synthetic Data: A Comparative Study](https://arxiv.org/html/2412.16335) - not-tiered
  - Demographic groups are represented at different rates in medical datasets, creating ML bias. Study generates synthetic data separately for each demographic group to mitigate underrepresentation—empirical evidence on demographic imbalance in medical datasets.
- **[source-b1260c87f7da]** [Phi-4 Technical Report](https://arxiv.org/abs/2412.08905) - not-tiered
  - Phi-4 is a 14B parameter model trained with data quality as central focus, strategically incorporating synthetic data throughout training while surpassing its teacher (GPT-4) on STEM tasks. Covers synthetic data curation, filtering of organic data, and model collapse mitigation.

