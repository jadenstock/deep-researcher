# Budget ablation: 8/4/8 vs 12/6/16 vs 16/8/20 (single query, 2026-05-11)

Three runs on the same prompt with different per-run budget caps. All
numbers below come from `notes.json`, `report.json`, `report.md`,
`token_usage.json`, and `run.log` in each run directory. Treated as a
single-seed ablation — numbers are directional, not statistically
reliable.

- **Query (all runs):** "What are the real-world risks and benefits of
  using synthetic data to train or fine-tune large language models?
  Focus on data quality, bias, and evaluation."
- **RUN1** — `runs/20260511T060643-b92e079e/` — default budgets
  (`8 / 4 / 8`).
- **RUN2** — `runs/20260511T084940-b972b6d1/` — raised (`12 / 6 / 16`).
- **RUN3** — `runs/20260511T181737-ab4d69e5/` — full sliders
  (`16 / 8 / 20`).

---

## 0. What the three sliders actually control

Reading them in the order they appear in the UI settings panel:

| Slider | Constrains | Who enforces | Tool it gates |
|---|---|---|---|
| `analyst_budget` | Max `investigate_question` dispatches by the **researcher** (Opus) | Researcher tool wrapper (`researcher.py:355`) | `investigate_question` |
| `scout_budget_per_analyst` | Max `scout(request=...)` calls **each analyst** can make | Analyst tool wrapper (`analyst.py:288`) | `scout` |
| `scout_search_budget` | Max **search-tool** calls **each scout** can make (shared across `search_web`, `search_academic`, `find_related_papers`) | Scout tool wrapper (`scout.py:164`) | Search tools only — `create_source_note`, `scout_fetch`, `list_source_notes` are **free** |

So the three numbers compose multiplicatively as a theoretical ceiling
on total search-tool calls across a run:

| Setting | Analyst dispatches × Scouts each × Searches each | Max search-tool calls |
|---|---|---:|
| 8 / 4 / 8 | 8 × 4 × 8 | 256 |
| 12 / 6 / 16 | 12 × 6 × 16 | 1,152 |
| 16 / 8 / 20 | 16 × 8 × 20 | 2,560 |

Plus whatever the landscape agent (a Sonnet scout-like agent that runs
before analysis) does with its own search budget.

### Actual consumption vs. the ceiling

| | RUN1 (8/4/8) | RUN2 (12/6/16) | RUN3 (16/8/20) |
|---|---:|---:|---:|
| Analyst dispatches used | **6 / 8** (75%) | **7 / 12** (58%) | **7 / 16** (44%) |
| Scout dispatches used | **13 / 24** (54%) | **31 / 42** (74%) | **29 / 56** (52%) |
| Scout search exhaustions (`search budget exhausted` fires) | **0** | **19** | **0** |

The researcher stops dispatching analysts after 6–7 regardless of
budget. The analysts stop dispatching scouts well short of their per-
analyst cap. **Only one slider showed binding cap pressure in any run:
the scout's `scout_search_budget` at its default of 16 fired the
exhausted-error 19 times in RUN2.** That's the only slider that was
empirically under-provisioned at any tested setting.

---

## 1. Why the researcher + analysts stop short of the cap

Two prompt lines, one in each agent, explicitly tell them not to spend
extra budget:

**Researcher** (`researcher.py:208`):
> "Never call `investigate_question` just because budget is left over.
> Stop when the report won't improve."

**Analyst** (`analyst.py:213`):
> "Don't over-investigate. 4-8 deep-read sources beats 20 half-skimmed
> ones."

These aren't soft hints — they change behavior visibly. Per-analyst
deep-reads are essentially constant across the three runs:

| | RUN1 | RUN2 | RUN3 |
|---|---:|---:|---:|
| ANALYZED sources | 33 | 42 | 43 |
| Analyst dispatches | 6 | 7 | 7 |
| **ANALYZED per analyst** | **5.5** | **6.0** | **6.1** |

Each analyst deep-reads ~6 sources. The "4–8" clause in the prompt is
holding tight. Raising `analyst_budget` past the researcher's natural
decomposition depth does nothing, because:

1. The researcher tops out at 6–7 sub-questions on a 4-axis prompt.
2. Even if it dispatched more, each new analyst only adds ~6 ANALYZED
   sources, because the analyst prompt caps deep-reads at 4–8.

This is the **load-bearing mechanism** behind the diminishing returns:
the report's evidentiary depth is set by the analyst prompt, not by any
slider.

---

## 2. The one signal where a slider actually bound: RUN2's scout search budget

The `search budget exhausted` ModelRetry error fired **19 times in
RUN2** vs. 0 times in RUN1 and RUN3. RUN2 was the only run where
scouts consistently wanted to do more searches than their cap allowed.

This is visible in the per-scout yield:

| | RUN1 (cap=8) | RUN2 (cap=16) | RUN3 (cap=20) |
|---|---:|---:|---:|
| Distinct scouts | 13 | 31 | 29 |
| Total source_notes created | 229 | 263 | 412 |
| **Sources / scout** | **17.6** | **8.5** | **14.2** |
| Haiku tool_calls / scout | 47.1 | 24.5 | 37.9 |
| Search exhaustions | 0 | **19** | 0 |

RUN2's per-scout output is roughly half of RUN1 and RUN3. Combined
with the 19 exhaustions, the story is clean: **RUN2's scouts were
routinely cut off before finishing their natural search arc.** They
started more dispatches (31) to compensate, but each dispatch produced
fewer sources because the search cap was biting.

Raising the cap to 20 in RUN3 closed this gap entirely. No scout in
RUN3 hit the cap, and per-scout output recovered to RUN1-ish levels.

Counter-intuitively, RUN1 with cap=8 also never hit exhaustion — its
scouts voluntarily stopped at fewer than 8 searches each. The landscape
phase appears to have front-loaded enough sources that RUN1's analyst-
dispatched scouts ran on narrower, easier-to-cover angles.

### Why RUN3 dispatched fewer scouts than RUN2

RUN3 dispatched 29 scouts vs. RUN2's 31, despite a higher per-analyst
cap (8 vs. 6). The reason follows from the per-scout yield: each RUN3
scout returned more sources (14.2 vs. 8.5), so when the analyst checked
`list_source_notes()` after each scout, it hit "enough coverage"
sooner. Raising the search cap made individual scouts more productive,
which *reduced* the need for many scout dispatches per analyst.

---

## 3. Secondary mechanism: the Graph grows, the Report doesn't

Putting §1 and §2 together explains the whole quantitative pattern:

| | RUN1 | RUN2 | RUN3 |
|---|---:|---:|---:|
| Total source_notes | 229 | 263 | 412 |
| ANALYZED | 33 (14.4%) | 42 (16.0%) | 43 (**10.4%**) |
| Tier-1 sources | 8 | 10 | **4** |
| Peer-reviewed sources | 9 | 13 | **4** |

RUN3's pool is 56% larger than RUN2's (412 vs. 263), but its ANALYZED
count moved by **one**. The extra 149 sources are all unvetted: they
enter the graph with state=SCOUTED, no tier, no peer-reviewed flag, and
nobody deep-reads them. Their quality metadata never gets populated
because that field is written by the analyst stage (`update_source_after_reading`),
which is capped. So the wider scout funnel in RUN3 *dilutes* the
quality mix without improving the evidence base.

The tier-1 and peer-reviewed counts *dropping* from RUN2 to RUN3 is
the same phenomenon viewed from the other side: the 42–43 analyses
aren't landing on the same sources across runs (the analyst's
`list_source_notes` returns a different pre-filtered list each time),
and with 412 candidates to pick from in RUN3 vs. 263 in RUN2, the
probability of any given high-tier source being among the ~6 an analyst
picks actually falls.

---

## 4. Orthogonal finding: RUN2 bypassed the judgment-family routing

RUN2's per-analyst mode distribution, extracted from `run.log`:

| | RUN1 | RUN2 | RUN3 |
|---|---|---|---|
| explore | 4 | **7** | 6 |
| verify | 1 | 0 | 0 |
| adversarial | 1 | 0 | 1 |

**RUN2 dispatched all 7 analyst investigations in `explore` mode — no
`verify` or `adversarial`**, even though two of its sub-questions were
literally titled `[adversarial] Steelman the position that...`. The
`explore` mode routes to the generative family (Sonnet); `verify` and
`adversarial` route to the judgment family (GPT-5.x) per ADR-0008, so
that the model challenging a claim comes from a different family than
the model that produced it. RUN2 bypassed this cross-family discipline
entirely — the steelman questions ran on the same family as the
original explores.

This is a bug/regression unrelated to budget — the researcher prompt
allows it — but it's notable that **RUN2 still produced the
highest-quality report on every output-quality metric** despite
skipping the discipline that was specifically designed to harden the
contested claims. It argues that decomposition shape + per-analyst
source depth dominate cross-family judgment in driving report quality
on this query.

RUN1 properly used verify + adversarial. RUN3 used one adversarial.

---

## 5. Graph / node statistics (full table)

### 5.1 Note counts

| Metric | RUN1 (8/4/8) | RUN2 (12/6/16) | RUN3 (16/8/20) |
|---|---:|---:|---:|
| Total notes | 237 | 272 | **421** |
| `source_note` | 229 | 263 | **412** |
| `question_note` | 7 | 8 | 8 |
| `landscape_note` | 1 | 1 | 1 |
| Unique source URLs | 229 | 263 | 412 |
| Inter-note link degree (avg) | 0 | 0 | 0 |

### 5.2 Source pipeline states

| State | RUN1 | RUN2 | RUN3 |
|---|---:|---:|---:|
| `SCOUTED` (found, not fetched) | 59 | 92 | **170** |
| `FETCHED` (body pulled) | 137 | 129 | **199** |
| `ANALYZED` (claims extracted) | 33 | 42 | 43 |

### 5.3 Tier stratification

| Tier | RUN1 | RUN2 | RUN3 |
|---|---:|---:|---:|
| 1 (strongest) | 8 | 10 | **4** |
| 2 | 27 | 36 | 36 |
| 3 | 1 | 2 | 6 |
| Peer-reviewed (flag) | 9 | 13 | **4** |
| Untiered | 193 | 215 | 366 |

### 5.4 Sources cited in the report

| | RUN1 | RUN2 | RUN3 |
|---|---:|---:|---:|
| Distinct source IDs cited | 26 | **55** | 44 |
| Cited / total source_notes | 11% | **21%** | 11% |
| Cited at tier 1 | 4 | **10** | 4 |
| Cited at tier 2 | 16 | 34 | 33 |
| Cited peer-reviewed | 3 | **13** | 4 |

---

## 6. Token and call statistics

| Metric | RUN1 | RUN2 | RUN3 | RUN3 / RUN1 |
|---|---:|---:|---:|---:|
| Total LLM calls | 21 | 40 | 38 | 1.8× |
| Tool calls | 807 | 979 | 1,348 | 1.67× |
| Total tokens | 11.06M | 16.75M | **22.86M** | 2.07× |
| Output tokens | 200.7k | 271.5k | 321.7k | 1.60× |
| Scout calls (Haiku) | 13 | 31 | 29 | 2.2× |
| Analyst calls | 6 | 7 | 7 | 1.17× |
| Researcher calls (Opus) | 1 | 1 | 1 | — |

Scout tool-call volume (per model, from `token_usage.json`):

| | RUN1 | RUN2 | RUN3 |
|---|---:|---:|---:|
| Haiku tool_calls total | 612 | 759 | 1,099 |
| Haiku tool_calls / scout | 47.1 | 24.5 | 37.9 |
| Haiku input tokens | 5.4M | 8.9M | 14.6M |

Two confounds to name explicitly:

1. **Analyst model routing varied between runs.** RUN1 used GPT-5.4 for
   2 analyst calls (the verify + adversarial modes); RUN2 used Sonnet
   only (0 judgment-family routes); RUN3 used GPT-5.5 for 1 analyst
   call. The `cache_read_tokens` column swings from 314k → 0 → 763k for
   this reason.
2. **Sliders aren't all binding at the same rates.** `analyst_budget`
   is never binding on any run. `scout_budget_per_analyst` is never
   binding. Only `scout_search_budget` bound (in RUN2 at its default
   value of 16). So most "raising budget" deltas aren't actually
   increasing consumption — they're changing a ceiling that doesn't
   touch the floor.

---

## 7. Report-level differences

### 7.1 Structure and length

| | RUN1 | RUN2 | RUN3 |
|---|---:|---:|---:|
| Words | 3,456 | 3,783 | **3,119** |
| Chars | 27,298 | 30,422 | 24,358 |
| `questions_investigated` | 6 | 7 | 7 |
| `limitations` | 10 | 11 | 10 |

### 7.2 Sub-question decomposition

Each run's 5th/6th/7th sub-questions — the discretionary slots beyond
the four-axis core — are **all different**:

| Slot | RUN1 | RUN2 | RUN3 |
|---|---|---|---|
| Q1 | Benefits + pipeline | Benefits + conditions | Benefits + reasoning |
| Q2 | Model collapse [contested] | Collapse + diversity [contested] | Collapse [contested] |
| Q3 | Bias [synthesis] | Bias [contested] | Bias [contested] |
| Q4 | LLM-as-judge [contested] | Eval integrity [contested] | Eval pitfalls [synthesis] |
| Q5 | Steelman: collapse IS real | **Domain (medical/legal/finance)** | **Mitigations / best practices** |
| Q6 | **Verify: preference leakage** | Steelman: bias overstated | Steelman: collapse IS real |
| Q7 | — | Steelman: collapse overstated | **Privacy in sensitive domains** |

None of the three reports is a superset of another. Each picks a
different discretionary triple, which drives the content differences
in §7.3 more than any budget effect does.

### 7.3 Content deltas (same as before)

**RUN1 uniquely picks up:** explicit verify dispatch for preference
leakage; knowledge-collapse three-stage framework (Stage B); position-
bias disagreement; verbosity-bias inversion; tight "five
non-negotiables" checklist.

**RUN2 uniquely picks up:** Nature Medicine 2024 medical poisoning
attack (0.001% tokens); neural-phishing / PII extraction; DPO-as-bias-
amplifier at 32–70B; MCRAGE / FairFinGAN / SMA fairness generators;
16-row mitigations matrix with validated/partial/refuted tagging; EU AI
Act + FDA + GDPR regulatory footprint.

**RUN3 uniquely picks up:** JP Morgan Six Levels of Privacy; DCR
Delusion (standard privacy proxy metrics fail); quantitative MIA
numbers (97.8% full-FT AUC, >80% LoRA); UniLeak layer-level attacks;
Google DP-SGD + LoRA production case; equilibrium-bias dynamics;
precise mixing-ratio scaling with model size; EU AI Act dates and
penalties.

**RUN3 regressions vs. RUN2:** medical data poisoning is gone;
DPO-as-bias-amplifier is gone; fairness-aware generators are gone; no
explicit verification dispatch for any contested claim.

---

## 8. Consolidated mechanism

Putting §0–§4 together, the behavioral model is:

1. **`analyst_budget` is non-binding on a 4-axis prompt.** The
   researcher decomposes into 6–7 sub-questions and stops. Raising the
   cap from 8 → 12 → 16 adds 0–1 actual investigations (caps at 7 by
   the researcher's own discipline).
2. **`scout_budget_per_analyst` is non-binding once the corpus is
   reasonably full.** Analysts check `list_source_notes()` and stop
   dispatching scouts when coverage looks sufficient. Larger per-scout
   yields (§2) actively *reduce* scout dispatches.
3. **`scout_search_budget` is the one slider with real empirical grip.**
   At 8 it's over-provisioned (scouts don't hit it). At 16 it's
   under-provisioned (19 exhaustions in RUN2). At 20 it's sufficient.
   This slider controls how complete an individual scout's search arc
   can be.
4. **The ANALYZED stage is the bottleneck on report evidence.** It is
   bounded by `analyst_dispatches × 4–8 deep reads` = **roughly
   42–56** under the current prompts. All three runs sit in this band
   (33/42/43) regardless of budget.
5. **Extra scout output lands in `source_notes` but never in `readings`.**
   So raising scout_* budgets inflates the graph (more SCOUTED notes)
   without changing the evidence the report rests on. In RUN3 this
   visibly *degrades* the tier-1 hit rate by diluting the candidate
   pool the analyst picks from.
6. **Decomposition shape dominates everything.** The 5th/6th/7th
   question choice matters more than any slider: picking
   "domain-specific risks" gives you the medical-poisoning finding;
   picking "privacy" gives you JP Morgan Six Levels. The planner's
   decomposition is high-variance across reruns, and that variance
   drowns out the budget effect.

---

## 9. Implications for the codebase

Concretely, if we want the sliders to actually improve reports:

- **Don't raise `scout_search_budget` past 20 without also raising the
  analyst's `4–8 deep-reads` ceiling.** Otherwise you inflate SCOUTED
  counts with material the analyst will never vet. A matched-pair
  change (e.g. scout_search 24 + analyst deep-reads 8–12) would at
  least let extra scouting convert into extra evidence.
- **`analyst_budget` past ~8 is dead weight on a 4-axis prompt.** The
  researcher prompt actively refuses to spend it. The UI should either
  hide the top of that slider or couple it to a planner-depth knob
  that actually changes decomposition.
- **RUN2's all-explore behavior is an independent bug.** When the
  researcher labels a question `[adversarial]` or `[verify]` in its
  title, it should also pass the matching `mode` to `investigate_question`.
  Right now the two are uncoupled and the researcher occasionally
  drops the mode.
- **Decomposition-stability is a better thing to measure and optimize
  than budget utilization.** A planner that reliably emits the same
  axis-set across reruns would make the output much more deterministic;
  a planner that reliably emits a verify-question for single-source
  claims would make RUN1's methodological discipline the default.

### Default slider choice

Based on this data, defaults were updated to **12 / 6 / 16** (RUN2's
settings): `DEFAULT_ANALYST_BUDGET=12`,
`DEFAULT_SCOUT_BUDGET_PER_ANALYST=6`,
`DEFAULT_SCOUT_SEARCH_BUDGET=16`. Note that these numbers are
over-specified for what the prompts actually consume (analyst_budget
is never touched past ~7 on this prompt, scout dispatches cap at ~31),
so this is really just "do no harm" — the one slider that matters at
16 is `scout_search_budget`, and 16 was the setting where RUN2
delivered its result despite the 19 exhaustions. Raising that one
alone to 20 would likely match RUN2's output at ~70% of RUN3's cost.

---

## 10. Caveats

- **n=1 per configuration.** All three deltas could flip on a re-run.
  Report them as directional.
- **Model routing changed across all three runs** (GPT-5.4 × 2 /
  Sonnet only / GPT-5.5 × 1) in ways not attributable to budgets.
- **Same seed/query.** Can't distinguish "budget helped" from "this
  query's decomposition converged at RUN2."
- **All three reports are plausible.** None has a falsified or
  retracted claim we can identify; differences are in scope,
  methodological discipline, and citation density.

### Follow-up worth doing

- Replicate each configuration ≥3× per query to see if the RUN2 > RUN3
  ordering is a budget effect or variance.
- Pin analyst-model routing across configurations.
- Add an isolated sweep of just `scout_search_budget` (8/12/16/20/24)
  holding the other two fixed — this is the only slider with
  empirically visible effect.
- Add a narrow-query case. If RUN3-style "fabricate breadth" behavior
  reproduces on a narrow query, that's a planner bug, not a budget
  phenomenon.
- Raise the analyst's `4–8 deep-reads` ceiling to 6–12 and re-run
  RUN3's settings. If ANALYZED count moves proportionally, this
  confirms the analyst prompt is the true bottleneck.
