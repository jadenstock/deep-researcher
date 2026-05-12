# Landscape ablation — same query, landscape on vs. off (2026-05-11)

Single-seed comparison of two runs on the same query with the same
UI-selected config, differing only in whether the landscape agent was
enabled. All numbers below come from `notes.json`, `report.json`,
`report.md`, `token_usage.json`, and `run.log` in each run directory.

- **Query (both runs):** _"What are the real-world risks and benefits
  of using synthetic data to train or fine-tune large language models?
  Focus on data quality, bias, and evaluation."_
- **LANDSCAPE** — `runs/20260511T084940-b972b6d1/` — landscape ON (baseline).
- **NO_LANDSCAPE** — `runs/20260511T205411-ec919799/` — landscape OFF via
  the new `skip_landscape` toggle.

Caveats up front: **n=1 per arm, single query, single trial.** Agent
runs are stochastic, so any single-pair difference is directional at
best. Additionally, "landscape off" drops *both* the markdown brief
and the pre-scouted source pool; this experiment cannot attribute
differences to one half or the other.

---

## Headline finding

**Landscape did real work.** With it on, the run produced a
measurably broader report (+16% words, +22% unique citations,
+1 sub-question branch) and pulled in higher-quality sources (more
peer-reviewed, more tier-1), at the cost of ~1.76× total tokens. The
single most striking delta is structural: **LANDSCAPE spawned a dedicated
`[sparse]` sub-question on domain-specific risks in medical/legal/
finance, which produced the entire final-report Section 5
("Domain-Specific Risks"). NO_LANDSCAPE did not spawn such a branch and
has no comparable section** — the Nature Medicine data-poisoning
result (0.001% contamination → clinically harmful outputs), the PII
leakage attack family, the HealthGAN fairness inversion, and FDA/EU
regulatory status all appear only in the LANDSCAPE report.

LANDSCAPE also issued **two targeted adversarial steelmans** (one per
contested sub-question: model collapse, bias amplification), while
NO_LANDSCAPE ran only one broad adversarial against the overall benefits
narrative. That is, LANDSCAPE fought harder on specific claims; NO_LANDSCAPE
fought in more general terms.

Operationally the tradeoff is cost vs. coverage: **LANDSCAPE costs about
77% more tokens for about 22% more words in the final report** — but
with demonstrably different content, not just elaboration.

---

## 1. What each run looked like (graph shape & telemetry)

### 1.1 Agent counts

| Agent type | LANDSCAPE | NO_LANDSCAPE | Δ |
|---|---:|---:|---:|
| Researcher | 1 | 1 | — |
| Landscape | 1 | 0 | -1 |
| Analysts dispatched | 7 | 5 | -2 |
| Scouts dispatched | 31 | 19 | -12 |
| **Total agent runs** | **40** | **25** | **-15** |

### 1.2 Tool-call & note telemetry

| | LANDSCAPE | NO_LANDSCAPE | Δ (NO_LANDSCAPE – LANDSCAPE) |
|---|---:|---:|---:|
| Tool calls (all types) | 979 | 751 | -228 (-23%) |
| Source notes created | 263 | 226 | -37 (-14%) |
| Question notes created | 8 | 6 | -2 |
| Landscape notes | 1 | 0 | -1 |
| Scout search-budget exhaustions | **19** | **0** | -19 |

NO_LANDSCAPE hit no scout-search budget ceilings at all. LANDSCAPE hit the
per-scout 16-search cap 19 times — scouts were chasing denser
leads in the LANDSCAPE arm. That is consistent with the landscape
brief identifying specific contested areas (model collapse,
preference leakage) that scouts then dug into aggressively.

### 1.3 Tokens

| | LANDSCAPE | NO_LANDSCAPE | Ratio |
|---|---:|---:|---:|
| Input tokens | 16.48 M | 9.30 M | 1.77× |
| Output tokens | 271 k | 192 k | 1.41× |
| **Total tokens** | **16.75 M** | **9.50 M** | **1.76×** |
| Calls (LLM) | 40 | 25 | 1.60× |
| Tool calls | 979 | 751 | 1.30× |

### 1.4 Per-model routing — an anomaly to flag

| Model | Role | LANDSCAPE calls | NO_LANDSCAPE calls |
|---|---|---:|---:|
| `anthropic/claude-opus-4-7` | Researcher | 1 | 1 |
| `anthropic/claude-sonnet-4-6` | Landscape + Analysts | 8 | 4 |
| `anthropic/claude-haiku-4-5` | Scouts | 31 | 19 |
| `openai/gpt-5.4` | **Adversarial analyst (judgment tier)** | **0** | **1** |

The researcher's `adversarial` dispatch mode is documented to route
to the judgment family (GPT-5.x). NO_LANDSCAPE's single adversarial
analyst ran on GPT-5.4 as expected. **LANDSCAPE's two adversarial
analysts both ran on Sonnet, not GPT-5.4** — i.e., judgment-tier
routing did not engage. The likeliest explanation is a difference
in UI model overrides between the two runs (the LANDSCAPE run predates
the `skip_landscape` feature by ~12 hours; UI routing selections
may have changed in between), but it's worth confirming before
drawing conclusions about "LANDSCAPE reasons better" in the adversarial
sections — the independent-model-family check that `adversarial`
mode is supposed to give was weaker in the LANDSCAPE run.

---

## 2. Decomposition — what the researcher asked

Both runs used the same opening structure (benefits / data-quality /
bias / evaluation), but the exact phrasings, classifications, and
branches diverged.

### 2.1 Sub-question tree

| # | LANDSCAPE sub-question | classification | LANDSCAPE cited | NO_LANDSCAPE equivalent | cls | NO_LANDSCAPE cited |
|---|---|---|---:|---|---|---:|
| 1 | Benefits & conditions for benefit | [synthesis] | 8 | Benefits / use cases | [synthesis] | 20 |
| 2 | **Model collapse and diversity loss** | [contested] | 10 | Data-quality risks (model collapse + hallucination) | [contested] | 7 |
| 3 | Bias amplification & mechanisms | [contested] | 12 | Bias / fairness / representational harms | [contested] | 9 |
| 4 | **Evaluation integrity** | **[contested]** | 11 | Evaluation challenges | **[synthesis]** | 10 |
| 5 | **Domain-specific risks (medical/legal/finance)** | **[sparse]** | 15 | *(none)* | — | — |
| 6 | Steelman: bias amplification is overstated | [adversarial] | 11 | Steelman: benefits narrative is overstated | [adversarial] | 11 |
| 7 | Steelman: model collapse is not a practical risk | [adversarial] | 9 | *(none)* | — | — |

Bolded cells are where LANDSCAPE and NO_LANDSCAPE meaningfully diverge:

- **Evaluation was `[contested]` in LANDSCAPE but `[synthesis]` in NO_LANDSCAPE.** LANDSCAPE's landscape brief had already surfaced the preference-leakage / benchmark-contamination controversy, so the researcher entered that branch expecting disagreement. NO_LANDSCAPE framed the same topic as a synthesis exercise and produced a tidier but less dialectical result.
- **LANDSCAPE added a `[sparse]` branch on high-stakes domains.** This is the single largest structural advantage of LANDSCAPE (see §4 below). NO_LANDSCAPE did not spawn this branch and therefore never investigated domain-specific safety.
- **LANDSCAPE ran two focused adversarial steelmans (bias, collapse); NO_LANDSCAPE ran one broad one (benefits).** LANDSCAPE's adversarial coverage tracks the claims its own `[contested]` branches had just made; NO_LANDSCAPE's is more diffuse.

### 2.2 Total sub-question citation counts

- LANDSCAPE: 8 + 10 + 12 + 11 + 15 + 11 + 9 = **76 source references in sub-question syntheses**
- NO_LANDSCAPE: 20 + 7 + 9 + 10 + 11 = **57 source references**

(LANDSCAPE: ~10.9/sub-question; NO_LANDSCAPE: ~11.4/sub-question. Per-branch
density is comparable; LANDSCAPE gets its edge by having more branches.)

---

## 3. Evidence pool — what they actually read

### 3.1 Raw pool comparison

| | LANDSCAPE | NO_LANDSCAPE |
|---|---:|---:|
| Source notes total | 263 | 226 |
| State = SCOUTED (never opened) | 92 | 76 |
| State = FETCHED (fetched but not cited) | 129 | 110 |
| State = ANALYZED (fetched + content used) | 42 | 40 |

Ratios of ANALYZED / total (~16% LANDSCAPE, ~18% NO_LANDSCAPE) are very
similar, so landscape did not change the yield rate — it scaled the
whole pipeline uniformly.

### 3.2 Cited sources by quality

| Quality metric | LANDSCAPE cited | NO_LANDSCAPE cited |
|---|---:|---:|
| Tier 1 (highest-quality: peer-reviewed venues, canonical preprints) | **10** | 7 |
| Tier 2 | 34 | 29 |
| Tier 3 | 2 | 3 |
| (unclassified) | 9 | 6 |
| **Peer-reviewed** | **13** | 9 |
| **Total unique citations in final report** | **55** | **45** |

LANDSCAPE cited 22% more unique sources in the final report, and
surfaced ~43% more tier-1 / peer-reviewed sources specifically.
Directionally this favours LANDSCAPE on evidence quality as well as
quantity.

### 3.3 Overlap between the two runs

| | count |
|---|---:|
| Unique URLs cited in LANDSCAPE report | 55 |
| Unique URLs cited in NO_LANDSCAPE report | 45 |
| **URLs cited in both reports** | **5** |
| URLs scouted (collected into memory) in both runs | 34 |

Only **5 URLs appear in both final reports**:

- `arxiv.org/html/2404.01413`
- `arxiv.org/html/2406.15126`
- `arxiv.org/html/2408.02056v1`
- `arxiv.org/html/2412.20641`
- `arxiv.org/html/2502.17521v2`

Even the *scouted pool* overlap is modest (34/226–263). The two runs
largely converged on the same factual story from **different bodies
of evidence**, which is reassuring for robustness (the field
consensus is not dependent on a narrow set of papers) but means
neither report is a superset of the other in citations.

---

## 4. The final reports side-by-side

### 4.1 Length and structure

| | LANDSCAPE | NO_LANDSCAPE |
|---|---:|---:|
| Words | 3,783 | 3,267 |
| Chars | 30,422 | 25,923 |
| Top-level sections | 7 | 8 |
| Unique citations | 55 | 45 |
| Run-level limitations (numbered) | 11 | 11 |

### 4.2 Section coverage

Section-by-section the two reports are structurally similar until
LANDSCAPE's section 5, which has no NO_LANDSCAPE counterpart.

| LANDSCAPE section | NO_LANDSCAPE section | Notes |
|---|---|---|
| 1. Benefits | 1. Why synthetic data is used | NO_LANDSCAPE has 6 specific subsections and more named results (Alpaca, Orca, Phi-4, GRIP-MATH); LANDSCAPE is more compact but links benefits to conditions |
| 2. Data Quality: Collapse + Diversity Loss | 3. Data-quality risks | Same content, similar length; LANDSCAPE explicitly frames "the steelman largely holds on 5 of 6 points" using its second adversarial dispatch |
| 3. Bias | 4. Bias, fairness, and representational harms | NO_LANDSCAPE: 6 subsections with a disagreement callout; LANDSCAPE: 3 mechanisms + adversarial rebuttal. LANDSCAPE is denser, NO_LANDSCAPE more granular. |
| 4. Evaluation Integrity | 5. Evaluation (the hardest problem) | NO_LANDSCAPE classified this as `[synthesis]`; LANDSCAPE as `[contested]`. Content overlaps (preference leakage, contamination) but LANDSCAPE organises around "5 distinct threats" and adds retrieval/test-collection bias from CIKM 2025. |
| **5. Domain-Specific Risks (medical/legal/finance)** | **(absent)** | **Unique to LANDSCAPE.** Covers Nature Medicine 2024 poisoning, PII leakage surveys, regulatory status, MedSyn/HealthGAN. ~700 words, 15 citations. |
| 6. Cross-Cutting Mitigations | 6. (practitioner's decision matrix) | LANDSCAPE's table has 18 rows with Validated/Refuted/Immature labels; NO_LANDSCAPE's has 8 scenario-risk pairs. LANDSCAPE is more operational. |
| — | 2. Adversarial counter-case | NO_LANDSCAPE front-loads this as its own numbered section; LANDSCAPE threads adversarial content into §2.3 and §3 ("when synthetic data reduces bias"). |
| 7. Synthesis and Guidance | 7. Open issues + 8. Confidence | NO_LANDSCAPE's §7 (open issues) is a strong numbered list; LANDSCAPE folds equivalent points into its §7 and the final practitioner paragraphs. |

### 4.3 Content that appears only in LANDSCAPE

Picked from a scan of both reports:

- **Medical data poisoning:** "replacing just 0.001% of training tokens with AI-generated medical misinformation produces an LLM significantly more likely to generate clinically harmful text" (Nature Medicine 2024). **NO_LANDSCAPE has no mention.**
- **PII leakage taxonomy:** neural phishing fine-tuning attacks, 5–18× phone-number extraction, LevAtt against TabPFN-V2. **NO_LANDSCAPE has no mention.**
- **HealthGAN direction-reversed bias:** Black patients under-represented >34% in synthetic MIMIC-3 though real data was White-biased; fairness mitigations don't transfer to synthetic (p=0.0073). **NO_LANDSCAPE has no mention.**
- **EU AI Act / FDA status:** 1,016 AI/ML medical devices approved but no generative-AI guidance as of Dec 2024. **NO_LANDSCAPE has no mention.**
- **"Iterative Finetuning is Mostly Idempotent"** (Qwen3-32B, Llama-3.3-70B) as a scale-limited counter to bias amplification, with the sharp DPO exception. **NO_LANDSCAPE has no mention.**
- **Alemohammad vs. Gerstgrasser definitional dispute** (8 distinct definitions of "collapse"). **NO_LANDSCAPE frames collapse differently and doesn't surface the definitional controversy.**

### 4.4 Content that appears only in NO_LANDSCAPE

- **Named distillation results at more granular level:** Alpaca cost ($500 + $100 GPU), WizardLM's Evol-Instruct, Orca-2's "Prompt Erasing." LANDSCAPE mentions these less specifically.
- **GRIP-MATH** ($114 for 2.1M verified problem-answer pairs vs. $44,000 GPT-4 baseline) and **SYNTHETIC-1** (Prime Intellect's 1.4M verified reasoning traces). LANDSCAPE does not name either.
- **Yu et al. NeurIPS 2023** 68%-North-America / 0.69%-Africa geographic skew. LANDSCAPE does not cite this.
- **Mansoor et al.** on non-binary representation (0–3/20 occupations). LANDSCAPE does not cite this.
- **Helff et al.** RLVR reward-hacking causality experiment (isomorphic vs. extensional verification). LANDSCAPE does not cite this.
- **Betley et al.** "narrow fine-tuning on insecure code induces broad misalignment." LANDSCAPE does not cite this.

Both reports are well-sourced within their own scope; the gap is
scope, not quality. LANDSCAPE covers domain-specific risks, definitional
disputes about collapse, and a broader regulatory frame. NO_LANDSCAPE
covers more specific named results within the synthetic-generation
toolchain and a sharper set of adversarial counters to benefit claims.

### 4.5 Confidence and calibration

Both reports rate confidence `high` on all sub-question syntheses,
and both close with calibrated hedges (`NO_LANDSCAPE`: "High on overall
structure, medium on quantitative thresholds." `LANDSCAPE`: similar
pattern embedded in §7.2–7.5).

Run-level limitations are nearly identical in count (11 each) and
topic coverage — frontier-scale validation, data provenance,
intersectional bias, replication needs. Calibration quality is
comparable; the difference between the two reports is breadth, not
epistemic humility.

---

## 5. What this tells us about the two hypotheses

### H1 — does landscape change the final report?

**Yes, observably.** LANDSCAPE produced:

- +22% unique citations (55 vs. 45)
- +43% peer-reviewed cited sources (13 vs. 9)
- +43% tier-1 cited sources (10 vs. 7)
- +16% report length (3,783 vs. 3,267 words)
- An entire section (domain-specific risks) that NO_LANDSCAPE missed

The reports are not different *rephrasings* of each other — they
source different evidence (only 5/55 URL overlap at the cited-source
level) and cover distinct sub-domains.

### H2 — does landscape change the decomposition?

**Yes, observably.**

- +1 analyst dispatch on a high-value `[sparse]` branch that
  generated a full section of the final report.
- +1 adversarial analyst (2 targeted steelmans vs. 1 broad one).
- Reclassified evaluation from `[synthesis]` (NO_LANDSCAPE) to
  `[contested]` (LANDSCAPE) — the researcher entered the branch with
  priors about disagreement rather than unity.
- Sharper question phrasings in Q2 and Q3 (e.g., "model collapse and
  diversity loss" vs. "data-quality risks including model collapse";
  "bias amplification and mechanisms" — the word "mechanisms" is
  a landscape-surfaced frame).

The landscape brief appears to do two jobs: (a) it pre-identifies
contested topics so the researcher picks the right classification, and
(b) it surfaces sub-areas (domain-specific, intersectional) that the
researcher would otherwise miss when decomposing from the raw query
alone.

### Caveats

- **Single seed.** One run per arm can't separate signal from
  stochastic variation. Replicate before treating any effect size as
  reliable.
- **Brief + sources are confounded.** If landscape helps, this
  experiment can't say which half is doing the work. A follow-up
  with `brief-only` (inject a brief, strip the scouted-source pool)
  and `sources-only` (landscape runs, but suppress the brief before
  the researcher sees it) would disentangle them.
- **Adversarial routing regression in LANDSCAPE.** The LANDSCAPE adversarials
  both ran on Sonnet rather than the judgment-tier GPT-5.4. If that
  was unintended, it would have made LANDSCAPE's adversarial analysis
  *weaker* than intended — so if anything, fixing this would amplify
  LANDSCAPE's edge further.
- **Scout search-budget exhaustions (19) in LANDSCAPE but 0 in NO_LANDSCAPE.**
  LANDSCAPE scouts were hitting caps; NO_LANDSCAPE scouts had headroom. The
  extra evidence LANDSCAPE pulled in may still have been capacity-limited.
- **Same query (broad, multi-area).** A narrow lookup query would
  likely show much smaller (or no) landscape effect, since the value
  of terrain-mapping is topic-dependent.

---

## 6. Practical takeaways for this codebase

1. **Landscape is doing real work on broad queries** — keep it on by
   default for research-style questions; the `skip_landscape` toggle
   is for ablation and debugging, not a production default.
2. **The `[sparse]` classification is load-bearing.** Only the
   landscape brief surfaced the medical/legal/finance sub-area; the
   researcher would not have inferred this branch from the query
   alone. If the brief is ever weakened, expect domain-specific
   coverage to regress first.
3. **The cost multiplier (~1.76× tokens) is not free.** For a quick
   turnaround or a query with well-known terrain, skipping landscape
   may be defensible. For anything involving contested, multi-area,
   or high-stakes domains, the 77% token overhead pays for real
   coverage gains.
4. **Investigate the judgment-tier routing anomaly.** LANDSCAPE's
   adversarial dispatches bypassed GPT-5.4. Confirm whether this is
   a UI-settings artifact between the two runs or a routing bug.
5. **Scout-search-budget ceiling (16/scout) is under-provisioned
   when landscape is on** — 19 exhaustions in one run. The
   previously-run budget ablation reached the same conclusion
   independently. Consider bumping the default to 20 or higher, or
   making the scout budget scale with landscape-on.

---

## 7. Next tests worth running

Ordered by information value per run:

1. **Same query, 3× replicates each arm.** Confirm the magnitude of
   the LANDSCAPE effect is larger than inter-run noise.
2. **Brief-only arm + sources-only arm.** Disentangle the two halves
   of the landscape contribution.
3. **Narrow/lookup query with landscape on vs. off.** Test whether
   LANDSCAPE is still worth its token cost on topics where terrain is
   well-known.
4. **LLM-as-judge pairwise grading of the reports.** Forced-choice
   (blinded arm labels, rubric = coverage / specificity / calibration
   / terminology) is more reliable than eyeballing.
5. **Fix and re-run with correct judgment-tier routing** on
   adversarials — confirm whether the LANDSCAPE advantage widens when the
   counter-argument gets a different-family judge as designed.
