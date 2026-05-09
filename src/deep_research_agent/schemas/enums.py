"""Enums and literal types."""

from __future__ import annotations

from enum import Enum


class TaskType(str, Enum):
    LANDSCAPE_SURVEY = "LANDSCAPE_SURVEY"
    DECOMPOSE = "DECOMPOSE"
    SCOUT_SOURCES = "SCOUT_SOURCES"
    SEARCH = "SEARCH"
    SCAN_SEARCH_RESULTS = "SCAN_SEARCH_RESULTS"
    FETCH_AND_EXTRACT = "FETCH_AND_EXTRACT"
    ANALYZE_SOURCE = "ANALYZE_SOURCE"
    RESCORE_RELEVANCE = "RESCORE_RELEVANCE"
    QUESTION_SYNTHESIZE = "QUESTION_SYNTHESIZE"
    META_SYNTHESIZE = "META_SYNTHESIZE"
    VERIFY_CLAIM = "VERIFY_CLAIM"
    ADVERSARIAL_CRITIQUE = "ADVERSARIAL_CRITIQUE"
    ANALYZE_CONSISTENCY = "ANALYZE_CONSISTENCY"
    SYNTHESIZE = "SYNTHESIZE"
    REPLAN = "REPLAN"
    SCOPE_ESCALATION = "SCOPE_ESCALATION"
    CHECK_TERMINATION_READY = "CHECK_TERMINATION_READY"
    VALIDATE_COMPLETION = "VALIDATE_COMPLETION"
    WRITE_REPORT = "WRITE_REPORT"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    BLOCKED_ON_SYNTHESIS_DEP = "BLOCKED_ON_SYNTHESIS_DEP"
    BLOCKED_ON_SPLIT = "BLOCKED_ON_SPLIT"
    DONE = "DONE"
    ESCALATED = "ESCALATED"
    ABANDONED = "ABANDONED"


class RoleClass(str, Enum):
    GENERATIVE = "generative"
    JUDGMENT = "judgment"
    CHEAP_DETERMINISTIC = "cheap_deterministic"


class TaskTier(str, Enum):
    LOW = "LOW"
    MID = "MID"
    HIGH = "HIGH"


class OrchestrationPattern(str, Enum):
    SINGLE_RESEARCHER = "single_researcher"
    MAKER_CHECKER = "maker_checker"
    MULTI_PERSPECTIVE = "multi_perspective"
    DEBATE = "debate"
    ACH = "ach"


class QuestionRound(int, Enum):
    STARBURSTING = 1
    STRUCTURAL = 2
    FALSIFICATION = 3
    PREMORTEM = 4
    METACOGNITIVE = 5


class DependencyType(str, Enum):
    PRODUCES_CONTEXT_FOR = "produces_context_for"
    COMPARED_AGAINST = "compared_against"
    TEMPORALLY_FOLLOWS = "temporally_follows"
    NONE = "none"


class NoteType(str, Enum):
    LANDSCAPE = "landscape_note"
    SOURCE = "source_note"
    QUESTION = "question_note"
    SYNTHESIS = "synthesis_note"
    DECISION = "decision_note"
    OPEN_QUESTION = "open_question_note"
    HYPOTHESIS = "hypothesis_note"


class QuestionClassification(str, Enum):
    LOOKUP = "lookup"
    SYNTHESIS = "synthesis"
    CONTESTED = "contested"
    SPARSE = "sparse"


class Tier(int, Enum):
    TIER_1 = 1
    TIER_2 = 2
    TIER_3 = 3
    TIER_4 = 4
    TIER_5 = 5


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    SUPPORTS = "SUPPORTS"
    REFUTES = "REFUTES"
    INCONCLUSIVE = "INCONCLUSIVE"


class ClaimType(str, Enum):
    """Claim taxonomy for verification triage.

    EXTERNAL       — claim references a fact, quantity, or phenomenon that
                     could plausibly be corroborated by an independent source
                     (e.g. "GPT-4 was released in 2023", "transformer attention
                     is quadratic in sequence length"). Best candidate for
                     cross-family VERIFY_CLAIM.

    NOVEL_TO_SOURCE — claim is about something introduced or measured only in
                     this source: a benchmark the paper created, a method it
                     proposes, a specific result from its own experiment.
                     Verification is structurally impossible — no independent
                     source will corroborate "Our FooBench contains 1,000
                     examples". Skip verify unless configured otherwise.

    META           — claim about the state of a field or community
                     consensus (e.g. "most alignment research focuses on
                     English"). Sometimes verifiable via survey papers or
                     meta-analyses; treat as medium priority.
    """

    EXTERNAL = "external"
    NOVEL_TO_SOURCE = "novel_to_source"
    META = "meta"


class SourceState(str, Enum):
    """Lifecycle state of a source_note in the shared corpus.

    SCOUTED  — URL + title + snippet discovered by SCOUT_SOURCES. Not fetched
               yet; tier/peer_review unknown. Shared across all open questions.
    FETCHED  — Full content pulled and tier-classified. Candidate for analysis.
    ANALYZED — At least one ANALYZE_SOURCE has run against it for some
               question; claims exist on the note. Still eligible for further
               analysis against other questions (same source, different
               question lenses).
    """

    SCOUTED = "SCOUTED"
    FETCHED = "FETCHED"
    ANALYZED = "ANALYZED"


class Methodology(str, Enum):
    EMPIRICAL = "empirical"
    THEORETICAL = "theoretical"
    OPINION = "opinion"
    SURVEY = "survey"
    BENCHMARK = "benchmark"


class Reproducibility(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"
