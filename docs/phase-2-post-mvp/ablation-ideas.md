# Ablation candidates

Goal: verify the load-bearing architectural decisions with a small number
of focused experiments. Each ablation flips **one** structural knob and
compares against the default configuration on **at most two** dimensions.

Scope discipline: we are not trying to benchmark the system. We are
trying to answer "is this decision paying its own cost?" for the
handful of decisions where a wrong answer would be expensive to unwind
later.

---

## The decisions worth testing

Ranked by "cost of being wrong" × "testability with a clean A/B flip".

| # | Decision | Where it lives | Why it's load-bearing |
|---|---|---|---|
| A | **Landscape pre-pass** runs before decomposition | `agents/landscape.py`, `researcher.py:research_run` | An entire agent + phase. Adds a fixed token tax to every run. ADR 0001 is the primary justification; we have no empirical check. |
| B | **Cross-family verify / adversarial** — judgment routes to a different model family than generative | `agents/analyst.py:_routing_for_mode`, `config/routing_diverse.yaml` | The structural invariant behind ADR 0008. If same-family verify produces the same answers, the whole diversity scaffolding is cargo. |
| C | **Scout ≠ analyst** — retrieval/triage isolated from deep-read | `agents/scout.py`, analyst's `scout` tool | Biggest context-hygiene decision. Costs a full extra agent loop per angle. Claim is "analyst context stays signal-dense." |
| D | **Researcher context isolation** — researcher never sees raw source content (no `fetch_url`, no source-note `load_note` depth) | `agents/researcher.py` tool set | Structural guarantee that the director reasons over syntheses. Easy to violate accidentally — worth confirming the *benefit* is real. |
| E | **Researcher runs on HIGH tier (Opus)** vs. analysts on MID (Sonnet) | `routing_diverse.yaml` | Single biggest $ lever in the routing policy. "Director needs frontier" is asserted, not measured. |

Decisions intentionally NOT in this list (reasoning below in Appendix):
verbatim-quote requirement, note-graph-as-only-shared-state, budget
sizes, closure-scoped counters, tool-retry semantics, terminal-tool
pattern. These are either (i) too invasive to flip cleanly, or (ii)
already defensible on correctness grounds that don't need an ablation.

---

## Recommended experiments

Pick 2–3. Each is scoped to roughly one afternoon of runs + analysis.

### Experiment 1 — Landscape ON / OFF  (decision A)

**Hypothesis.** The landscape pre-pass meaningfully improves final-report
coverage and source diversity. If it doesn't, it's a ~20–30% token tax
on every run that we should remove or collapse into the first analyst
dispatch.

**Arms.**
- `default` — landscape runs as today.
- `no-landscape` — `research_run` skips `landscape_run`; researcher's
  opening prompt drops the brief + source list. Researcher decomposes
  cold from the query alone; analysts do their own scouting.

**Implementation sketch.** A `--no-landscape` CLI flag that short-circuits
the landscape call and passes an empty brief + empty source list into
the researcher opening. No changes to the researcher's prompt; we want
to test the *structural* contribution, not a co-designed prompt
variant.

**Dimensions (pick both).**
- **Cost:** total tokens, total wall time.
- **Quality proxy:** one of —
  - number of *distinct domains* in `sources_cited` (broader landscape
    should surface more venues),
  - researcher's `get_research_state` call count in round 1 (without a
    landscape brief, the researcher may loop more before dispatching),
  - LLM-judge rubric score on the final `report.md` (coverage,
    grounding).

**N.** 3 queries × 3 trials per arm = 18 runs. Queries should span
simple lookup, contested, and sparse — the three regimes the landscape
is *supposed* to help with most.

**Read.** If no-landscape wins or ties on quality at ~70–80% of the
cost, kill the landscape pre-pass (or fold it into analyst-round-1).
If default wins clearly on contested/sparse but ties on lookup, the
landscape should be *conditional*, which is a real redesign signal.

---

### Experiment 2 — Cross-family verify vs. same-family verify  (decision B)

**Hypothesis.** Routing `verify` / `adversarial` to a different model
family (ADR 0008's structural invariant) produces genuinely different
verdicts — not just paraphrases of the `explore` finding. If same-family
verify reaches the same conclusion most of the time, the invariant
isn't buying the falsification discipline it claims to.

**Arms.**
- `cross-family` — default `routing_diverse.yaml` (Claude explore, GPT
  verify/adversarial).
- `same-family` — swap `judgment` → Claude Sonnet (same as generative
  MID). Everything else identical.

**Implementation sketch.** A second routing YAML file, e.g.
`config/routing_same_family.yaml`, loaded via the existing
`--routing` flag. Zero code changes.

**Dimensions (one is enough).**
- **Verdict divergence rate** — among `verify` dispatches, what fraction
  return `REFUTES` or `INCONCL`? Cross-family should produce more
  non-SUPPORTS verdicts if the diversity actually breaks shared priors.
  *Secondary:* do `disagreements` in the final report mention the
  verify's counter-evidence, or does it quietly dissolve?

**N.** Focus on queries that *force* verify dispatches. Pick 2 contested
queries, run the researcher with a prompt nudge ("dispatch at least one
verify per contested sub-question") or look only at runs where verify
actually fired. 5 trials per arm.

**Read.** If same-family `verify` SUPPORTS ≥90% of the time while
cross-family is lower, the invariant is load-bearing. If the rates are
close, diversity is cosmetic and the ADR 0008 scaffolding can be
softened (e.g., keep the option but don't make it the default).

*This is the cheapest experiment on the list — one config file, no
code changes.*

---

### Experiment 3 — Scout collapsed into analyst  (decision C)

**Hypothesis.** The scout/analyst split keeps analyst context clean
enough that the analyst produces better syntheses than an analyst
given direct retrieval tools. If a unified analyst matches or beats
the split, we're paying for an agent hop that doesn't earn its keep.

**Arms.**
- `split` — today's design.
- `unified` — analyst gets `search_web`, `search_academic`,
  `create_source_note`, and `scout_fetch` directly; `scout` tool and
  scout agent are bypassed. `scout_budget` semantics become raw
  search-call budget.

**Implementation sketch.** A `build_analyst_unified` that registers
the scout's tools on the analyst and drops the scout dispatch tool.
Contained behind a flag. Non-trivial but not deep — maybe a day.

**Dimensions.**
- **Quality proxy:** number of sources with ≥1 reading-entry from this
  analyst, plus claims-per-reading-entry count. The split's
  justification is that a clean analyst context produces deeper
  readings; the unified arm, eating SERP output, should produce
  shallower readings.
- **Cost:** total tokens of the analyst loop (not the whole run —
  we're isolating this decision).

**N.** 2 queries × 4 trials per arm = 16 runs. One query should have
narrow/deep angles (favors split), one should be broad (possibly
favors unified).

**Read.** If unified matches on depth metrics at lower cost, collapse
the scout into a tool-only retrieval layer and reclaim an agent.

*This is the highest-effort experiment and the one with the largest
architectural consequence — consider running it only after 1 and 2
have narrowed what's load-bearing.*

---

## Optional fourth experiment (if budget allows)

### Experiment 4 — Researcher on Sonnet instead of Opus  (decision E)

**Hypothesis.** The director role genuinely needs frontier-class
reasoning. Otherwise we're paying Opus rates for a coordinator whose
job is mostly "dispatch, review state, dispatch more."

**Arms.**
- `opus-researcher` — default.
- `sonnet-researcher` — routing `HIGH.generative` = Sonnet.

**Dimensions.**
- **Cost:** whole-run tokens weighted by model price (researcher turns
  are a small fraction of tokens but the most expensive per-token).
- **Quality proxy:** rubric score on final report's *structural*
  qualities only — does it surface disagreements, honor the
  5-check / pre-commit audit, dispatch verify/adversarial when
  appropriate? The Opus-vs-Sonnet differential is expected to show up
  in orchestration judgment, not prose quality.

**N.** 4 queries × 2 trials per arm = 16 runs.

**Read.** If Sonnet-researcher produces structurally similar reports at
substantially lower $, drop the HIGH tier and unify researcher +
analyst at MID. This is a pure cost-reduction play.

---

## Measurement infrastructure

All three primary experiments can be analyzed from the existing
`runs/<run_id>/` artifacts:

- `report.md` / `report.json` — final output.
- `notes.json` — full graph including every reading, claim, and
  question synthesis.
- `token_usage.json` — per-model, per-agent-type totals.
- `run.log` — dispatch pattern, verdicts, retry-loop behavior.

What's missing and worth building *before* Experiment 3:

1. **A rubric judge** — a single Haiku/Sonnet pass over
   `report.md` that scores 4–5 dimensions on a 1–5 scale (grounding,
   coverage, dissent-surfacing, calibration). Needed for any
   quality-dimension reads. Keep the rubric version-pinned.
2. **A per-run metrics extractor** — standalone script that reads a
   `runs/<id>/` directory and emits a single-row CSV (tokens by
   model, unique domains cited, verify dispatches fired, verify
   verdicts, n sources analyzed, n claims, etc.). Every experiment
   depends on this; build it once.

Neither needs to be clever. A flat script + a stable rubric is
sufficient for N=10–20 runs per experiment.

---

## Suggested order

1. **Experiment 2** first — zero code, one config file, answers the
   most-defended architectural decision (ADR 0008).
2. **Experiment 1** next — one flag, tests the phase with the clearest
   fixed cost.
3. **Experiment 3** only if the first two leave budget. Larger
   implementation cost, but the biggest architectural decision on
   the list.
4. **Experiment 4** is a cost-tuning exercise, not a decision check;
   defer until the structural questions are settled.

---

## Appendix — decisions deliberately excluded

- **Verbatim-quote invariant.** Flipping this is a correctness
  regression, not an ablation — the quotes are what the evaluator
  *uses* to check faithfulness. Keep.
- **Note-graph as only shared state.** Can't meaningfully A/B this
  without a parallel codebase. Accepted on first-principles grounds.
- **Budget sizes (8 analysts / 4 scouts).** A tuning knob, not an
  architectural decision. If cost is the concern, tune after the
  structural ablations land.
- **Terminal-tool commit pattern.** Correctness scaffolding (crash
  durability + ModelRetry semantics). Not an ablation target.
- **Mode-framing prompts for verify/adversarial.** Subsumed by
  Experiment 2 — if cross-family verify isn't doing useful work, the
  framing prompts don't matter either.
