"""Source tiering: deterministic reject list + LLM semantic classifier + peer-review flag.

Reject list short-circuits obvious junk (social media, unattributed
aggregators, vendor marketing) to Tier 5 with no LLM call. Remaining
sources go through a cheap LLM classifier that assigns Tier 1..4 with a
rationale string. The peer-review flag is returned by the classifier
and is strict (journal/major-conference only).
"""

from .classifier import TierClassifierOutput, classify_source
from .simple import quick_tier

__all__ = ["TierClassifierOutput", "classify_source", "quick_tier"]
