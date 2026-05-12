# ADR 0008 — Role-to-model routing with ablation support

**Status:** Accepted
**Date:** 2026-05-07
**Context in:** `tdd-v3.md` §5.3 (agent executor), §5.7 (orchestration patterns), §5.12 (completion gates)

---

## Context

Every judgment call in the pipeline — verification, adversarial critique, replanning, gate evaluation — was implicitly routed through the same model family as generation (claim extraction, synthesis, report writing). TDD v3 §5.3 says "cheap / mid / frontier" without specifying family, but the natural default for a Claude-environment developer is Claude across the board.

Same-family routing creates compounding bias:
- `VERIFY_CLAIM` inherits the same priors that produced the claim.
- `ADVERSARIAL_CRITIQUE` builds counter-arguments using the same training distribution as the claim it's attacking.
- `REPLAN` metacognitive review uses the same model family's sense of "tested enough."
- `VALIDATE_COMPLETION`'s judgment-heavy gates (G2, G4) confirm what earlier same-family stages already decided.

Empirical LLM-as-judge findings (TPR high / TNR low agreeableness bias; self-preference bias) suggest this is a real production risk, not a theoretical concern.

Meanwhile, Jaden's deployment environment supports a router layer (LiteLLM) with multiple model families available (Claude, GPT, Kimi, other open Chinese models). The infrastructure for diversity already exists.

## Decision

Role-to-model routing is a **configuration layer**, not hardcoded in tasks. Three role classes:

| Role class | Task types | Default family |
|---|---|---|
| **generative** | `ANALYZE_SOURCE`, `SYNTHESIZE`, `WRITE_REPORT`, `DECOMPOSE`, `REPLAN` | Primary family (e.g., Claude Sonnet/Opus) |
| **judgment** | `VERIFY_CLAIM`, `ADVERSARIAL_CRITIQUE`, `VALIDATE_COMPLETION` G2/G4 | Secondary family (e.g., GPT) |
| **cheap_deterministic** | `SCAN_SEARCH_RESULTS`, tier classifier | Cheapest capable model, family-agnostic |

Specific guardrails on top of the policy:
- **`VERIFY_CLAIM` always uses a different family from the `ANALYZE_SOURCE` that produced the claim.** Enforced in the verifier task's model-selection logic. This is the most load-bearing diversity commitment; breaking it defeats the purpose of independent verification.
- **Configuration is per-run.** Routing policy is a run-level config file, so a single run uses a consistent policy but different runs can vary for ablation.
- **Fallback to single-family is a supported configuration.** If the router is unavailable, or if ablation requires it, `{generative, judgment, cheap_deterministic}` can all point at the same family.

## Ablation plan

The take-home requires "at least one comparison or ablation." Model routing is a strong candidate. Proposed ablation matrix:

| Configuration | Purpose |
|---|---|
| Single cheap family everywhere | Lower-bound baseline — how much does model quality matter? |
| Single frontier family everywhere | Upper-bound baseline — what does unlimited budget buy? |
| Default diversity policy (above) | Production target — does diversity outperform either single-family? |
| Diversity variant (swap which family is generative vs. judgment) | Sensitivity — is the effect directional or symmetric? |

Metrics: claim-level faithfulness (quote → claim support rate), scope coverage (% of sub-questions answered), contested-claim surfacing rate (on Test Case 2), final-report calibration.

This ablation is additional to the "with/without verifier" ablation flagged earlier; both stay available.

## Alternatives Considered

### (A) Single family throughout; accept same-model bias.
Rejected as a default. May be appropriate for a lower-budget deployment; retained as a supported configuration for baselines, not the default.

### (B) Force diversity only on `ADVERSARIAL_CRITIQUE`.
Narrower scope; addresses the single most-acute case. Rejected as default in favor of (iii)-style coverage across all judgment roles — the compounding problem isn't just adversarial critique, it's the full judgment layer.

### (C) Full rotation with bias-aware per-task random sampling.
Overkill for MVP. Post-MVP territory. Measurement and per-model drift tracking would be substantial additional infrastructure.

## Consequences

### Positive

- Same-model bias is broken at the judgment layer, which is where the compounding is most dangerous.
- The `VERIFY_CLAIM` ≠ `ANALYZE_SOURCE` family constraint is a mechanical invariant, not a prompt discipline — won't be silently violated by a future change.
- Ablation story is rich and directly addresses the take-home requirement.
- Config-driven policy means the same codebase runs baseline ablations without modification.
- Leverages infrastructure Jaden already has (LiteLLM router).

### Negative

- Prompt caching is per-family. We have multiple cache buckets instead of one. Mitigated by the fact that most repeated calls within a run stay within one role class (and therefore one family) — cache hits remain effective.
- Router dependency. If the router is down, the system has to fall back to single-family. Acceptable degradation; falls back gracefully.
- Cost varies by family. Judgment-family cost might exceed generative-family cost; needs budget awareness. Mitigated by the cheapest-capable policy on the deterministic role class.
- Cross-family prompt differences: GPT responds differently to the same prompt than Claude. The prompt library may need per-family variants of the same system prompt. Manageable; each variant's structure stays the same even if phrasing differs.

### Neutral

- The specific default (Claude generative, GPT judgment) is empirical. Initial runs will tune it. The decision commits to the *structure* (role-based routing with diversity on judgment), not to the specific families.
- Sub-families within Claude (Haiku vs. Sonnet vs. Opus) also count as "diversity" for some of these bias-breaking properties. A lightweight variant of the policy could be Claude-only with sub-family diversity; retained as a fallback option.

## Open Questions

- **Cost measurement per ablation.** Need to track cost per run to compare ablation configs apples-to-apples.
- **Prompt variants per family.** How much prompt tuning is needed to normalize behavior across families? Empirical.
- **Router failure modes.** What happens mid-run if the router loses access to one family? Should queue tasks or fail loudly? Probably fail loudly with a decision_note; better to have a visible degradation than silent bias reintroduction.
- **Which specific models to start with.** Default as `{generative: Claude Sonnet 4.6, judgment: GPT-5, cheap: Haiku 4.5}` is a first draft; tune during implementation.

## References

- `phase-0-research/findings.md` — LLM-as-judge agreeableness bias literature context.
- `phase-1-initial-design/05-tdd-v3.md` §5.3 — original unspecified routing.
- User's `CLAUDE.md` — LiteLLM router environment note.
- Grilling session transcript — 2026-05-07.
