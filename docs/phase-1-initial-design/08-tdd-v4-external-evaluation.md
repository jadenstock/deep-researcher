# TDD v4 — External Evaluation Against Research Corpus

**Date:** 2026-05-07
**Notebook:** `55d508ac-a85e-4848-bf67-56cb8b34253a` — *Research: Deep Research Agent System Design*
**Subject documents:** `07-tdd-v4-00-overview.md`, `07-tdd-v4-01-pipeline-and-infrastructure.md`, `07-tdd-v4-02-orchestration-and-completion.md`, `07-tdd-v4-03-report-biases-walkthrough-and-plan.md`, `CONTEXT.md`
**External corpus:** 43 sources — Tier 2 (arXiv + peer-reviewed proceedings): 22, Tier 3 (major lab blogs, standards, framework docs): 21
**Evidence confidence:** Moderate-High on architectural comparisons; Low on TDD v4's novel elements (the corpus is silent on them — see §3)
**Scope:** Cross-reference TDD v4 against external evidence to answer three questions — (1) who is building similar systems, (2) which tech stack choices are supported vs. risky vs. untested, (3) where are the likely design flaws.

**This is an evaluation document. Claims about TDD v4's design merit are grounded in the external corpus, not in the TDD v4 documents themselves.**

---

## BLUF

TDD v4's **macro-architecture has strong corpus precedent** — the Landscape Survey → Decomposition → Deep Research → Completion pipeline, the hierarchical orchestration with parallel sub-tasks, the multi-perspective pattern, the separate verifier layer, and the deterministic termination check all have direct analogs in GPT Researcher, Marco DeepResearch, Microsoft Azure patterns, STORM, and LangGraph Ralph Loop. The **novel elements** — cross-model-family routing invariant, LLM semantic source tiering, ACH matrix adjudication, triangulation scoring, 10-section Analytic Pyramid report — are **not covered by the corpus** and therefore operate beyond the current evidence base. They are principled extensions of supported patterns, not arbitrary inventions, but they carry the research risk of any unproven mechanism.

The **top three design concerns**, in order of severity, are (1) **replanner context rot** — the replanner reads the full note graph and will degrade as state grows, per Anthropic's attention-budget evidence; (2) **orchestrator bottleneck** — centralized decision-making in the replanner contradicts documented hierarchical-scaling warnings; (3) **cross-family routing may not cure LLM judge bias** — the corpus documents severe judge biases (agreeableness, misinformation oversight, authority) and is silent on whether cross-family routing alone is sufficient. Two additional concerns are mitigable with small design changes: **no prompt-injection sanitization** on retrieved content, and **no programmatic exact-match verification** of claim quotes against source text.

---

## 1. Similar Systems — Who Is Building This?

The corpus documents **five close analogs** and one architectural contrast. TDD v4 is not sui generis; most of its macro-structure has precedent, though the specific combination is distinctive.

### 1.1 Closest analogs

| System | What TDD v4 shares | What TDD v4 diverges on | Inherited risk |
|---|---|---|---|
| **GPT Researcher** (Tier 3, docs.gptr.dev; Architectural Frameworks synthesis) | Hierarchical pipeline: Chief Editor decomposes → parallel specialist researchers → reviewers → writers. Fan-out over sub-tasks. | GPT Researcher uses a recursive research tree that dynamically follows leads; TDD v4 caps this with a mutation-budgeted replanner. | Hierarchical orchestrator = documented single point of failure and latency bottleneck (Architectural Frameworks). Applies to TDD v4's replanner. |
| **Marco DeepResearch** (Tier 2, arXiv) | Verification-centric design: dedicated verifier sub-agent performs independent validation of sub-task outputs and final answer. Joint-Verify convergence-based termination. | Marco uses the same agent family as its own verifier; TDD v4 enforces cross-family routing. Marco uses "Discard All" on failure; TDD v4 uses progressive disclosure. | Marco's primary strength — preventing premature convergence — transfers. Its single-family verification weakness is what TDD v4 claims to address with ADR 0008. |
| **Microsoft Azure Orchestration Patterns** (Tier 3) | TDD v4 implements: Concurrent orchestration (parallel retrieval), Group-chat / Maker-checker (verification), Magentic orchestration (manager-with-adaptive-ledger = the replanner). | TDD v4 weaves these into a typed-dependency DAG; Azure presents them as independent topology choices. | Azure warns Maker-checker and Magentic are prone to infinite refinement loops and excessive context growth. Mutation budget mitigates the loop risk; context growth is not mitigated at the replanner layer. |
| **STORM** (cited in Architectural Frameworks, single-source for TDD v4's analog) | `multi_perspective` pattern matches STORM's persona-based stakeholder-viewpoint query generation. | STORM uses dialogue mode (student ↔ expert); TDD v4 uses parallel single-researcher pipelines + synthesis merge. | Documented ability to prevent one-dimensional outputs on contested topics. |
| **LangGraph / Ralph Loop** (Tier 3, Architectural Frameworks) | `CHECK_TERMINATION_READY` deterministic check mirrors Ralph Loop's "Stop Hook" — intercepts LLM's subjective exit and forces structural completeness check. Typed state graph with checkpoint-at-super-step semantics. | LangGraph uses durable persistence (PostgresSaver, DynamoDBSaver); TDD v4's scheduler is in-memory. | Stop Hook pattern is one of the most robust stopping mechanisms in the corpus. Lack of durable persistence is a divergence (§2.1). |

### 1.2 Architectural contrast

**SFR-DeepResearch** (Tier 2) and **LiteResearcher** (Tier 2) represent the pure-single-agent-with-tools paradigm TDD v4 deliberately rejected. Their authors argue single-agent systems generalize better to unseen tasks because they are not constrained by fixed workflows. **MARS** and **MARSHAL** (Tier 2) counter with empirical evidence that multi-agent frameworks improve generalized reasoning. **Microsoft Azure** explicitly recommends defaulting to single-agent-with-tools unless boundaries demand otherwise.

**TDD v4's position:** rejected pure single-agent for rigid multi-pattern orchestration. The corpus is genuinely contested on whether this is the right default; TDD v4's multi-agent bet is defensible but not unambiguously supported. For simple queries, TDD v4 will pay O(N²) coordination overhead that a single-agent system would not.

### 1.3 What is novel (no corpus analog)

The corpus is **silent** on five of TDD v4's specific mechanisms:

1. **Cross-model-family routing invariant** (`VERIFY_CLAIM.family ≠ ANALYZE_SOURCE.family`). Multi-agent critique is supported (Marco, Scientific Intelligence, Microsoft), but routing verifier and generator to *different foundational model families* to break self-preference bias is not documented.
2. **LLM semantic source tier classifier + deterministic reject list + separate `peer_reviewed` flag + 0.80 confidence cap.** Corpus documents that LLMs handle conflicting evidence poorly; is silent on fetch-time tiering as the intervention.
3. **Size-first deterministic source extraction with 8K threshold** + `load_source_section` on-demand. Corpus supports just-in-time agentic reading (Anthropic Claude Code pattern, LiteResearcher full-page retrieval) but is silent on the specific size-routing heuristic and structured-digest representation.
4. **ACH matrix adjudication with lowest-inconsistency scoring.** Debate, critique, and self-reflection are covered; formal ACH matrix adjudication from intelligence-community methodology has no corpus analog for LLM systems.
5. **Analytic Pyramid 10-section report + calibrated confidence language ladder + diagnostic-vs-acknowledged intelligence gaps.** Corpus covers structured outputs (e.g., Personalized Deep Research PQR framework — Personalization / Quality / Reliability) but does not document the specific Analytic Pyramid structure or calibrated confidence language.

**Interpretation:** these are principled extensions of supported patterns (independent verification, deterministic rejection, just-in-time reading, multi-hypothesis analysis, structured reporting). They are not arbitrary inventions. But they are unproven against the current evidence base, so empirical validation is essential.

---

## 2. Tech Stack per Component — Supported vs. Risky vs. Silent

Evaluation of each concrete technical choice in TDD v4.

### 2.1 Orchestrator / Scheduler — **PARTIALLY SUPPORTED**

- **Supported:** Periodic bounded replanner + mutation budget aligns with Microsoft Azure's explicit iteration-cap recommendation. Deterministic `CHECK_TERMINATION_READY` aligns with Ralph Loop's Stop Hook pattern. These are among the most robust loop/termination mitigations the corpus documents.
- **Contradicted:** **In-memory task graph state.** Azure Architecture Center: *"persist shared state externally rather than relying on in-memory context alone"* — for interruption recovery and token-bloat management. Architectural Frameworks documents LangGraph's production use of durable savers (PostgresSaver, DynamoDBSaver) for checkpoint persistence.
- **Recommendation:** Migrate the task graph to a durable store (SQLite via LangGraph checkpointer is the minimum-viable version for a take-home; PostgreSQL for anything production-bound). This is a small change that buys fault tolerance and time-travel debugging.

### 2.2 Note Graph + Progressive Disclosure — **SUPPORTED**

- **Supported:** Anthropic's "Effective context engineering" explicitly advocates structured note-taking outside the context window and incremental context discovery by the agent. JetBrains and "Cutting Through the Noise" empirically validate observation masking as superior to summarization. TDD v4's digest-by-default + `load_note` aligns directly with both patterns.
- **Recommendation:** Proceed. This is one of the most corroborated design choices in TDD v4.

### 2.3 Search & Retrieval Stack — **SUPPORTED**

- **Supported:** LiteResearcher uses Serper for web search. Multi-domain academic search (PubMed, arXiv) is documented in "Autonomous Agents Coordinating Distributed Discovery." Semantic Scholar and Unpaywall fit naturally into this pattern.
- **Notable alternative:** GPT Researcher documentation highlights **Tavily** as an API specifically optimized for agentic research. The corpus does not prescribe Tavily over Serper, but worth evaluating for retrieval-precision reasons.
- **Recommendation:** Keep Serper + Semantic Scholar + arXiv + Unpaywall as the MVP. Add Tavily as a second web-search provider for an ablation if time allows.

### 2.4 Source Extraction — **PARTIALLY SUPPORTED**

- **Supported direction:** Just-in-time agentic reading is documented by Anthropic (Claude Code pattern: `head`/`tail`/`grep` over files) and LiteResearcher (full-page Markdown from PostgreSQL, no chunk-level RAG). TDD v4's `load_source_section` is a natural fit for this paradigm. Deliberate rejection of chunk-and-embed RAG aligns with the corpus trend.
- **Silent on:** the specific 8K token threshold, `trafilatura` + MarkItDown tool choice, the structured_content schema.
- **Recommendation:** Keep the just-in-time architecture. Treat the 8K threshold and specific tool choices as empirically tunable — they are operating defaults, not validated constants.

### 2.5 LLM Semantic Source Tiering + Reject List + 0.80 Cap — **CORPUS SILENT**

- **No corpus analog.** The corpus documents that LLMs handle conflicting sources badly (ECON-family findings, LLMs favor priors over retrieved evidence when they conflict). Is silent on fetch-time semantic tiering as the intervention.
- **Risk:** the tier classifier is itself an LLM. If it shares biases with downstream reasoners, tiering amplifies rather than corrects bias.
- **Mitigation built in:** the **0.80 preliminary-anchor confidence cap** on non-peer-reviewed sources is the load-bearing backstop. The `peer_reviewed` flag is deterministic and independent of tier. This is the correct structural fix for "classifier over-tiers a rigorous preprint."
- **Recommendation:** Keep the cap. Calibrate the classifier against a small held-out labeled set before relying on it in production — a few dozen known sources with human-labeled tiers is enough to detect systematic drift.

### 2.6 Role-to-Model Routing (Cross-Family Invariant) — **PARTIALLY SUPPORTED**

- **Supported:** Independent verification is a well-supported pattern. Marco DeepResearch, Scientific Intelligence, and Microsoft Azure's Group-chat pattern all argue for separating the generator and verifier.
- **Silent on:** routing to **different model families** specifically (Claude vs. GPT vs. Haiku) to mechanically break self-preference bias. The corpus documents severe judge biases (agreeableness, misinformation oversight, authority, beauty bias — "Humans or LLMs as the Judge" per Q&A note) but does not validate whether cross-family routing cures them. See §3 for the design-flaw implications.
- **Recommendation:** Keep the invariant — it is logically sound and the ablation you already planned (§8 of the TDD) is the right way to prove or disprove it. Include a fallback to single-family routing for cost/availability reasons.

### 2.7 Obsidian Vault Export — **CORPUS SILENT**

- **No corpus analog.** Corpus prefers structured JSONL / OpenTelemetry for observability (AgentTrace, AgentJournal). Obsidian markdown vault is a human-auditability choice; the corpus treats observability as a machine-readable forensics concern.
- **Recommendation:** These are complementary, not competitive. Keep the Obsidian export for reviewer walkthroughs, but add structured JSONL logging (trace per task, with inputs/outputs/model-id/timings) for post-hoc analysis and evaluation harness consumption. This is a small addition that aligns the system with documented observability practice.

### 2.8 Replanner + Termination Checks — **SUPPORTED** (for the structural parts)

- **Supported:** Mutation budget = Azure iteration caps. `CHECK_TERMINATION_READY` = Ralph Loop Stop Hook. Deterministic separation of stopping decision from LLM judgment is one of the cleanest patterns in the corpus.
- **Risk:** see §3.2 — the *replanner itself* becomes a lost-in-the-middle liability at scale, which is a different concern from whether termination works.

### 2.9 Six Completion Gates + Analytic Pyramid Report — **CORPUS SILENT**

- **Silent on:** the specific 10-section Analytic Pyramid structure, confidence language ladder (High / Moderate / Low with numeric ranges), and diagnostic-vs-acknowledged gap distinction.
- **Supported direction:** Structured evaluation frameworks exist — PDR-Bench's PQR framework (Personalization, Quality, Reliability) evaluates research reports via LLM-as-judge with dynamic weighting + automated citation verification. CRYSTAL evaluates step-level reasoning fidelity.
- **Recommendation:** Use the Analytic Pyramid for the user-facing report. Ground the Analytic Pyramid's Evidence Summary + Calibrated Uncertainty + Intelligence Gaps sections against PQR-style automated citation verification (claim → quote support rate, claim → source agreement count). This gives you a defensible evaluation story for the take-home.

---

## 3. Design Flaws — Stress Test Results

Findings ordered by severity. Each is cited against external corpus evidence. Three are **fundamental bets** that cannot be patched without rearchitecture; four are **mitigable** with small changes.

### 3.1 Fundamental bets

**Flaw 1 — Replanner context rot (HIGH severity)**
The replanner periodically reads the *full note graph + task graph* to detect implicit dependencies, scope creep, and bias-pattern signals. The corpus guarantees LLMs degrade on recall as context grows (Anthropic "Effective context engineering," LLM Survey, JetBrains). Worker agents get progressive disclosure; the replanner does not. As the note graph accumulates, the replanner's Round 3/4/5 reasoning quality will erode precisely when it matters most (late in the run, many sub-questions, many notes). This threatens global coherence.
**Mitigation options (none trivial):** (a) the replanner reads a *summary index* of the note graph rather than the graph itself, with on-demand load for specific sub-questions — partial fix, trades off dependency-detection quality; (b) split the replanner into per-sub-question replanners with no global view — loses cross-question coherence; (c) keep as-is and accept degradation for the take-home scale, flag as production concern.

**Flaw 2 — Orchestrator bottleneck (HIGH severity)**
Architectural Frameworks explicitly warns hierarchical orchestrators become token, latency, and performance bottlenecks as O(N) scales. TDD v4 centralizes all task-graph mutations in the replanner and all decomposition in a single DECOMPOSE task. For take-home scale (3-5 sub-questions, ~50 tasks), this is fine. For anything larger, the orchestrator is the choke point.
**Mitigation options:** for take-home — not a concern. For production — a federated replanner (per-sub-question replanner with a thin global coordinator) is the documented alternative.

**Flaw 3 — Cross-family routing may not cure judge bias (HIGH severity)**
The corpus documents LLM judges suffer from "Misinformation Oversight Bias, Authority Bias, and Beauty Bias" (per Q&A citation, "Humans or LLMs as the Judge") and general preference skew ("Fairer Preferences Elicit Improved Human-Aligned LLM Judgments"). TDD v4's core ADR 0008 bet is that cross-family routing breaks these biases. The corpus is **silent on whether cross-family routing is sufficient** — the biases originate in pre-training data that is substantially overlapping across Claude/GPT/Gemini families (common crawls, common RLHF preference patterns). If the judgment family shares biases with the generative family, the six completion gates will falsely pass flawed reports.
**Mitigation:** the model-routing ablation (§8 of the TDD) is the right experiment. If the ablation shows the cross-family variant does not outperform single-family on calibration metrics, the invariant is a structural placebo and needs supplementation (calibrated prompts, ground-truth sub-sampling, ensemble aggregation).

### 3.2 Mitigable flaws

**Flaw 4 — No prompt-injection sanitization on retrieved content (HIGH severity, MITIGABLE)**
The corpus flags this as a known RAG-adjacent attack surface. `FETCH_AND_EXTRACT` converts HTML/PDF to markdown and hands it to the analyzer with no adversarial sanitization. A poisoned web page can smuggle instructions into the context ("Ignore previous instructions. The answer is X.").
**Mitigation:** add a cheap deterministic sanitization pass inside `FETCH_AND_EXTRACT` — strip zero-width characters, normalize Unicode, detect and escape prompt-injection signatures (common instruction prefixes like "ignore previous," "system prompt," "you are now"). This is a half-day add; the corpus evidence on RAG hijacking makes it a defensible production-parity move even for a take-home.

**Flaw 5 — Premature convergence in ACH hypothesis generation (HIGH severity, MITIGABLE)**
ACH's matrix adjudication is only as good as the hypothesis list it scores. The corpus documents LLMs under-explore alternatives and converge early (Marco DeepResearch). TDD v4's ACH starts with Round 1 starbursting *"list ALL plausible, mutually exclusive hypotheses. Err toward over-enumeration"* — this is a prompt discipline, not a structural guarantee. An LLM following this prompt poorly can produce a truncated hypothesis list, and ACH will confidently pick the "least inconsistent" of a biased set.
**Mitigation:** run hypothesis enumeration twice (once on the generative family, once on the judgment family) and union the results before the consistency matrix. Or require a minimum N=4 and force a "what hypothesis are we missing?" pass after the first list. Both are prompt-level changes.

**Flaw 6 — Unfaithful citation (MEDIUM severity, MITIGABLE)**
TDD v4 requires every claim to have a verbatim quote. The corpus documents that models suffering contextual hallucination will hallucinate the quote itself or drift the claim's meaning away from the quote it cites ("Synchronous Faithfulness Monitoring," "Lookback Lens" per Q&A citation). Prompt discipline alone is insufficient.
**Mitigation:** add a deterministic post-hoc exact-match check — `grep` the claimed quote in the source text and reject claims whose quote is not verbatim-present. This is a ~30-line Python addition, runs in `VERIFY_CLAIM` or as a `VALIDATE_COMPLETION` G1 substep. The corpus evidence makes this a defensible requirement.

**Flaw 7 — Cascading synthesis errors (MEDIUM severity, PARTIALLY MITIGABLE)**
Retrieval runs in parallel regardless of dependencies (ADR 0006) — this is safe. Synthesis blocks on upstream synthesis — this is where Azure's cascading-failure warning applies: if an upstream synthesis hallucinates or converges on a wrong position, the downstream synthesis inherits and compounds it.
**Mitigation:** `maker_checker` wrapping upstream synthesis on `produces_context_for` edges reduces but does not eliminate the risk. A stronger fix is to re-verify load-bearing upstream claims at downstream synthesis time.

### 3.3 Unaddressed production concerns (pure gaps)

- **API prompt-cache economics** — TDD v4 does not structure prompts to maximize KV-cache hit rates. For a take-home this is irrelevant; for production this is a major cost lever (Anthropic/OpenAI both price cached tokens dramatically lower). Mitigation: order agent system prompts as `[stable preamble] + [task-specific variable content]` consistently across role invocations. **Cheap to retrofit later.**
- **Cost / latency as first-class design input** — static thresholds (8K routing, mutation budget=3, K=2 scope-creep) approximate cost control but are not dynamic. Corpus mentions Dynamic Speculative Planning as a more sophisticated alternative; out of MVP scope.
- **API model drift / deprecation** — *implicit defense*: role-to-model routing is config-driven, so swapping models does not require rebuilding prompts. This is actually a hidden strength of ADR 0008.

### 3.4 Ambiguous corpus bets (positions the design committed to)

- **Multi-agent vs. single-agent:** corpus is contested. TDD v4 picked multi-agent orchestration. Risks O(N²) coordination for simple queries where single-agent-with-tools would suffice. Your `single_researcher` pattern mitigates this for `lookup` sub-questions, so the concern is real only if simple queries get mis-classified as contested.
- **Triangulation scoring** (source-type + time + methodology diversity) — no corpus analog. Novel and operating beyond the evidence base, but the specific vectors are defensible (they match intelligence-community triangulation practice).

---

## 4. Top 5 Ranked Recommendations

Ordered by expected value for the take-home.

1. **Add durable persistence for the task/note graph** (small change, high value). SQLite via LangGraph-style checkpointer is enough. Buys fault tolerance, time-travel debugging, and alignment with Azure's persistence recommendation. Mitigates part of Flaw 1.
2. **Add prompt-injection sanitization + deterministic quote-grep to `FETCH_AND_EXTRACT` and `VALIDATE_COMPLETION` G1** (small changes, high value). Closes Flaws 4 and 6. Both are defensible additions — the corpus directly supports them.
3. **Model-routing ablation is the headline experiment.** Make sure it compares calibration (confidence-vs-correctness) on known-answer sub-questions, not just faithfulness and cost. That is the test of whether ADR 0008's cross-family bet actually cures judge bias or is a structural placebo.
4. **Double-enumerate ACH hypotheses** (prompt-level change, modest value). Run Round 1 on both generative and judgment families and union the results. Partially mitigates Flaw 5.
5. **Add structured JSONL logging alongside the Obsidian vault.** Aligns with corpus observability practice (AgentTrace) without removing the reviewer-friendly vault. Opens the door to an automated evaluation harness (PDR-Bench PQR-style claim citation verification).

---

## 5. Caveats on This Evaluation

- **Corpus vintage:** 2024–early 2026. Most deep-research-agent-specific papers are preprints (Marco DeepResearch, LiteResearcher, SFR-DeepResearch, MARS, MARSHAL, AutoResearch-RL, Personalized Deep Research). Findings marked "Tier 2 (arXiv)" carry the 0.80 confidence cap per the inherited research methodology.
- **Single-source claims flagged:** STORM analog (Architectural Frameworks), blackboard pattern (Microsoft Azure), ECON-family judge-bias findings (cited in prior Q&A but not in the pruned corpus — secondary-citation-only, flagged in the original 2026-05-05 findings doc caveat section).
- **TDD v4's novel elements (cross-family routing, LLM tiering, ACH matrix, triangulation, Analytic Pyramid)** are not in the corpus. They are principled extensions of supported patterns, not arbitrary choices. Treat the take-home evaluation harness as your first empirical validation of these mechanisms.
- **Corpus gaps acknowledged:** prompt-cache economics, prompt-injection defense, API model drift, apples-to-apples cost comparisons across orchestration patterns. These gaps are real — not limitations of the retrieval, but of the field.

---

## 6. Conceptual Model (Evaluation Lens)

TDD v4 is best read as **GPT Researcher × Marco DeepResearch × LangGraph Ralph Loop × STORM**, assembled via Microsoft Azure's named patterns, with five principled novel extensions stacked on top. The macro-architecture is on solid ground. The novelty lives in (a) how verification is routed (cross-family), (b) how sources are credibility-weighted (semantic tier + peer-review + 0.80 cap), (c) how multi-hypothesis reasoning is adjudicated (ACH matrix), and (d) how the report is structured (Analytic Pyramid + calibrated confidence). The biggest risk to watch is **the replanner's cognitive load at scale** — everything else is either strongly supported or mitigable with small design changes.

For the take-home, the honest story is: *"the macro-architecture is documented practice; the novelty is in the judgment-layer and source-quality treatment; here is the ablation that validates whether the judgment-layer novelty actually cures judge bias."*

---

## Research Journey Metadata

**Phase Reached:** Application (3C) — cross-referencing TDD v4 claims against the 43-source external corpus.
**Q&A Rounds Completed:** 3 substantive rounds (similar systems, tech stack per component, design flaws). Q&A notes saved to notebook as `e1320c9d`, `c9709553`, `c137da38`.
**Application Context:** TDD v4 — `07-tdd-v4-00-overview.md`, `07-tdd-v4-01-pipeline-and-infrastructure.md`, `07-tdd-v4-02-orchestration-and-completion.md`, `07-tdd-v4-03-report-biases-walkthrough-and-plan.md`, `CONTEXT.md`.
**Prior notebook:** reused `55d508ac-a85e-4848-bf67-56cb8b34253a` (Deep Research Agent System Design, 2026-05-05, Crystallization phase). Subject documents added; corpus unchanged. No new external research queries run — corpus was already sufficient.
