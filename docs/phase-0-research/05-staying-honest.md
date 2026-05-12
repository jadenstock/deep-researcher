# Q5: Dead ends, contradictions, hallucinations — how does the system stay honest? How do you prevent convergence on a comfortable wrong answer?

## What the research says

This is where the corpus is empirically richest. Multiple independent sources document specific failure modes.

### Documented failure modes

1. **Premature convergence** (Marco DeepResearch): *"Agents are prone to accepting the first plausible-looking answer and terminating exploration prematurely, even when the result is incorrect."* Empirical — documented as a specific failure this paper's architecture is designed to address.
2. **Confirmation bias from priors** (ECON-family findings, cited in synthesis): LLMs "favor one piece of conflicting evidence without justification and rely on internal knowledge if they have prior beliefs." When retrieved evidence conflicts with the model's prior, the model arbitrarily sides with the prior.
3. **Repetitive action loops** (LiteResearcher): agents reissue the same search query without progress, inflating response length without gathering new evidence.
4. **Citation-without-reading / unfaithful RAG** (documented in synthesis via faithfulness-monitoring work): the agent cites a document but the generated claim contradicts the document's actual content.
5. **Silent hallucination** (Architectural Frameworks): reasoning-trace-free generation produces confident wrong answers. ReAct exposes reasoning but does not eliminate hallucination.
6. **Summary drift** (implicit across Anthropic + sub-agent sources): compressing a sub-agent's findings to a short summary drops the specific quotes that would have let verification catch a bad claim.

### Documented countermeasures

1. **Independent verifier agent with its own tools** (Marco DeepResearch — strongest signal): the verifier re-retrieves and re-checks claims rather than re-reading the generator's reasoning. This breaks the same-model bias that defeats self-critique.
2. **Multi-agent debate / tournament-style critique** (Towards Scientific Intelligence): agents argue for and against a proposal; a judge declares a winner. Higher cost; strongest for open-ended claims.
3. **Maker-checker loops** (Microsoft Azure): generator → checker → revision cycle. Lower cost than full debate; catches most factual errors.
4. **Multi-perspective query generation** (STORM via Architectural Frameworks): force the research phase to generate queries from multiple stakeholder perspectives to prevent one-sided evidence collection. Prevents convergence by construction.
5. **Verifier-convergence termination** (Marco DeepResearch's Joint-Verify): only terminate when multiple independently generated candidates satisfy verification. Premature convergence is defeated by not allowing the generator to stop on its own judgment.
6. **Claim-level structured output with attached quotes**: make every claim carry a direct quote from the cited source. This makes citation-without-reading mechanically catchable — a downstream check compares the quote to the claim.

### Corpus gap (important for your design)

**No source documents objective source-credibility scoring.** When two sources contradict each other, resolution is currently left to LLM-judge subjectivity. There is no documented algorithm for domain-authority or trust weighting. This is an opportunity for design novelty: a production system can easily build source-tier rules (peer-reviewed > preprint > reputable-blog > unsourced) into the conflict-resolution layer.

## Design implication for an API-based system

**Layered defenses, cheapest first.** A single mechanism is never enough.

1. **Cheap, always-on:** structured claim output with attached quotes. Enables mechanical verification downstream. Near-zero added cost.
2. **Cheap, conditional:** per-claim citation-faithfulness check — does the attached quote semantically support the claim? One extra small-model call per claim. Catches citation-without-reading.
3. **Moderate, conditional:** for claims above a confidence-weight threshold (load-bearing claims that the final synthesis depends on), dispatch an independent verifier agent with its own tool access and an adversarial prompt. Catches premature convergence.
4. **Expensive, rare:** for contested claims (where verifier and generator disagree, or where sources materially conflict), run a maker-checker or debate round. Produces the "conflicting sources" section of the final report.
5. **Free, always-on:** source-tier metadata. Every retrieved source gets a tier tag (peer-reviewed / preprint / established-tech-pub / blog / unsourced) that influences both weighting and surfaces in the final report. Replaces LLM-judge subjectivity with a deterministic rule.

### Pattern for the final report

For every non-trivial claim, emit:
- The claim itself
- Confidence (LLM-stated + calibration against source tier and agreement count)
- Supporting sources (tier-tagged)
- Conflicting sources, if any, with their positions stated
- Verification status (unverified / self-verified / independently-verified / contested)

This directly satisfies the assessment's requirement that the output "separate claims from evidence and indicate confidence and source agreement."

## Key failure mode the layered design does not fix

**Same-model cascading confirmation.** If the generator, verifier, and critic are all the same model with the same priors, they can all converge on the same wrong answer. Mitigation (undocumented in corpus): rotate models across agents where budget allows; at minimum rotate temperature and prompt framing. This is load-bearing and will matter for the demo.

## Residual uncertainty

- How aggressive the confidence threshold for invoking the expensive verifier should be. Too aggressive: the system is slow and expensive. Too lax: load-bearing claims slip through. Empirical calibration required.
- Whether debate actually helps on topics where the model's priors are strong. MARS/MARSHAL suggest yes for reasoning games; no direct evidence in this corpus for open-ended research.

## Anchor sources

- Marco DeepResearch (verifier sub-agent, Joint-Verify convergence, premature-convergence evidence)
- LiteResearcher (repetitive-loop failure mode)
- Architectural Frameworks + STORM (multi-perspective query generation)
- Microsoft Azure (maker-checker loops)
- Towards Scientific Intelligence (debate / role-based verification)
- Anthropic Effective Context Engineering (context pollution as source of silent failure)
