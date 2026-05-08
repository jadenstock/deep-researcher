"""Source tiering: deterministic reject list + LLM semantic classifier + peer-review flag.

Reject list short-circuits obvious junk (social media, unattributed
aggregators, vendor marketing) to Tier 5 with no LLM call. Remaining
sources go through a cheap LLM classifier that assigns Tier 1..4 with a
rationale string. The peer-review flag is deterministic and independent
of the semantic tier.
"""
