"""Pipeline phases.

Phase 0 (INTAKE) is part of the CLI.
Phase 1 — LANDSCAPE_SURVEY — broad shallow retrieval + single batched analyzer.
Phase 2 — DECOMPOSE — AIMS scoping, evidence-grounded classification, typed
           dependency emission.
Phase 3 — deep research — orchestrator loop (lives in scheduler + patterns +
           replanner).
Phase 4 — CHECK_TERMINATION_READY → VALIDATE_COMPLETION → WRITE_REPORT.
"""
