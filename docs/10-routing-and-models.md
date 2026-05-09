# 10 — Routing and Models

The system never names a specific model in Python code. Every task
declares a `(role, tier)`; the **routing config** maps that pair to a
model identifier sent to the LiteLLM router. Same code, different
routing configs, yields the ablation matrix.

## The two configs

### Routing config (YAML, tracked)

Policy-level. Lives under `config/`. The CLI defaults to
`config/routing_diverse.yaml`; a single `--routing` argument switches
it for ablation runs.

```yaml
name: diverse_default
description: |
  Claude family for generative roles, GPT family for judgment roles,
  Haiku for cheap deterministic roles. Different families for
  generative and judgment roles so VERIFY_CLAIM always satisfies the
  cross-family invariant by construction.

tiers:
  LOW:
    generative: anthropic/claude-haiku-4-5
    judgment: openai/gpt-5.2
    cheap_deterministic: anthropic/claude-haiku-4-5
  MID:
    generative: anthropic/claude-sonnet-4-6
    judgment: openai/gpt-5.4
    cheap_deterministic: anthropic/claude-haiku-4-5
  HIGH:
    generative: anthropic/claude-opus-4-7
    judgment: openai/gpt-5.5
    cheap_deterministic: anthropic/claude-haiku-4-5

cross_family_invariant:
  enabled: true
  applies_to:
    - VERIFY_CLAIM
```

Model IDs are `family/model` strings (LiteLLM convention). `family_of`
returns the part before `/`; `router_name` strips it. The router
receives the bare model name; the family prefix stays in the code for
the cross-family invariant check.

### Local config (TOML, gitignored)

Infrastructure-level. Lives at `config/local.toml`. Owns the endpoint
and API keys:

```toml
[llm]
api_base_url = "https://llm-router.example.com/v1"
api_key = "sk-..."

[retrieval]
brave_api_key = "..."
brave_min_interval_s = 1.5
# optional: tavily_api_key, serper_api_key,
# semantic_scholar_api_key, unpaywall_email

[observability]
logfire_token = "pylf_..."
```

Two configs compose at runtime: the executor resolves a `model_id` via
routing, then invokes it through `local.llm.api_base_url`.

## Resolution

`RoutingConfig.model_id_for(role, tier) -> str`:

```python
return getattr(self.tiers[tier], role.value)
# e.g. self.tiers[TaskTier.HIGH].generative
```

`AgentExecutor.execute` calls `select_model(routing, role, tier,
task_type, forbidden_family=self._forbidden_family(task, notes))`.

`select_model`:

```python
model_id = routing.model_id_for(role, tier)
if inv.enabled and task_type in inv.applies_to and forbidden_family:
    if routing.family_of(model_id) == forbidden_family:
        raise CrossFamilyViolation(...)
return model_id
```

`make_model(model_id, local)` (`agent_factory.py`) builds a
`pydantic_ai.OpenAIChatModel` pointed at `local.llm.api_base_url`,
sending the bare `router_name(model_id)` (i.e. without the family
prefix).

## Cross-family invariant

### Problem

Same-family same-model-generation bias. If the model that extracted a
claim is also the one verifying it, the verification is more
performative than probative — shared priors, shared reasoning habits,
shared failure modes.

### Structural enforcement

The invariant is enforced at **model-selection time**, not by prompt
discipline.

1. When an analyzer extracts a `ClaimItem`, the QS handler stamps
   `claim.analyzed_by_family = ctx.routing.family_of(ctx.model_id)`
   (`"anthropic"`, `"openai"`, etc.).
2. When a `VERIFY_CLAIM` task is emitted, its `input_refs` carry
   `source_note_id` and `claim_id`.
3. When the executor goes to dispatch the VERIFY_CLAIM, it looks up
   the `analyzed_by_family` via `_forbidden_family`:

   ```python
   def _forbidden_family(task, notes):
       if task.type != VERIFY_CLAIM: return None
       source_id = task.input_refs.get("source_note_id")
       claim_id = task.input_refs.get("claim_id")
       if not source_id or not claim_id: return None
       if source_id not in notes: return None
       for c in notes.get(source_id).metadata.claims:
           if c.id == claim_id: return c.analyzed_by_family
       return None
   ```

4. `select_model` checks the resolved model's family against
   `forbidden_family` and raises `CrossFamilyViolation` on match.

### Ablation support

`cross_family_invariant.applies_to` is configurable. An ablation run
can disable the invariant (`enabled: false`) or remove `VERIFY_CLAIM`
from the list. Because routing is pure config, the same code runs; only
the config changes.

### Fallback for missing provenance

When a claim lacks `analyzed_by_family`, or the source_note /
claim_id can't be resolved, `_forbidden_family` returns `None` — no
restriction. This is a defensive path; under normal operation every
claim has the family stamped by the QS handler at extraction time.

## Role / tier usage by task type

| Task type | Role | Tier | Rationale |
|-----------|------|------|-----------|
| `LANDSCAPE_SURVEY` | generative | HIGH | Shapes the whole run's framing |
| `DECOMPOSE` | generative | HIGH | Scoping + classification is the plan |
| `QUESTION_SYNTHESIZE` | generative | HIGH | Both the analyzer and synthesizer calls |
| `VERIFY_CLAIM` | judgment | MID | Cross-family; mid-tier cost-bounded |
| `ACH consistency` (inside QS) | judgment | MID | N calls; fan-out cost matters |
| `TIER_CLASSIFY` (inside QS) | cheap_deterministic | LOW | One per source; mostly extracted signals |
| `CHECK_TERMINATION_READY` | cheap_deterministic | LOW | No LLM; role is a formality |
| `VALIDATE_COMPLETION` | judgment | HIGH | Six-gate audit is the last-line defense |
| `WRITE_REPORT` | generative | HIGH | Final user-facing prose |
| `REPLAN` (scheduler-invoked) | judgment | MID | Between-tick second opinion |

### Per-call model distribution

A typical run (1 landscape, 1 decompose, 3 QS with ~8 sources each and
2 VERIFY_CLAIM per QS, 1 CHECK, 1 VALIDATE, 1 WRITE_REPORT, up to 3
REPLAN) invokes roughly:

- ~30 cheap_deterministic LOW calls (tier classifier per source).
- ~25–40 generative HIGH calls (analyzers + synthesizers + report).
- ~3 generative MID calls (ACH consistency, if escalation fires).
- ~6–10 judgment MID calls (verifiers + replanner).
- ~2 judgment HIGH calls (VALIDATE_COMPLETION + potentially replanner
  if configured that way).

Token accounting per-model is in `runs/<id>/token_usage.json`; see
[11-live-ui-and-observability.md](11-live-ui-and-observability.md).

## Why this shape

- **Single endpoint, many families.** All traffic goes through the
  LiteLLM router (`local.llm.api_base_url`). The router handles
  upstream family dispatch. The Python code only ever speaks the
  OpenAI-compatible chat API.
- **Config-only policy changes.** Swapping families (e.g. for an
  "all-Claude" ablation) is a YAML edit, no code change.
- **Invariant at construction.** The cross-family check is at
  `select_model` time — before the agent is even built — so there is
  no path that bypasses it. A handler cannot silently send a
  VERIFY_CLAIM to the wrong family.
- **Family-agnostic handlers.** No handler code names a specific
  model or family. `ctx.model_id` is opaque to the handler; the
  handler hands it to `make_model` and invokes. This is the
  discipline that makes the ablation matrix possible.

## Extending routing

Adding a new role class (e.g. `vision`) requires:

1. Adding the enum member to `RoleClass`.
2. Adding a field on `TierRouting` for the new role.
3. Setting the field in every routing YAML.
4. Using `task.role = NEW_ROLE` on the tasks that need it.

Adding a new tier is similar (`TaskTier` + top-level `tiers:` dict
entry + per-tier `TierRouting`).

Adding a task type to the cross-family invariant is one-line:
`cross_family_invariant.applies_to: [VERIFY_CLAIM, NEW_TYPE]`. The
executor must then populate `forbidden_family` in
`_forbidden_family` for the new type — currently hardcoded to only
handle VERIFY_CLAIM.
