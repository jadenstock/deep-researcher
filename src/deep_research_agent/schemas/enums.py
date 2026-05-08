"""Enums and literal types."""

from __future__ import annotations

from enum import Enum


class TaskType(str, Enum):
    LANDSCAPE_SURVEY = "LANDSCAPE_SURVEY"
    DECOMPOSE = "DECOMPOSE"
    SEARCH = "SEARCH"
    SCAN_SEARCH_RESULTS = "SCAN_SEARCH_RESULTS"
    FETCH_AND_EXTRACT = "FETCH_AND_EXTRACT"
    ANALYZE_SOURCE = "ANALYZE_SOURCE"
    QUESTION_SYNTHESIZE = "QUESTION_SYNTHESIZE"
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
