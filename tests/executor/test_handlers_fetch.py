"""End-to-end integration test for handle_fetch_and_extract — scaffolded.

This file exists as a placeholder for the full e2e test the Phase-1 plan
calls for. It is intentionally a pytest.skip until a future task fills
in the NoteReader/TaskReader fakes and the scouted source_note fixture.

The target test shape:

1. Build a SCOUTED source_note via Note + SourceNoteMetadata constructors
   (including at least one entry in .relevance so the spawn branch runs).
2. Build a FakeFetcher scripted with a FetchResult for the URL.
3. Build a FakeLLMRunner scripted with a TierClassifierOutput.
4. Build fake NoteReader / TaskReader — currently missing from tests/fakes/.
5. Construct an AgentExecutor with the fake runner injected, register
   handle_fetch_and_extract, patch default_fetcher() or thread the fake
   into the RunnerBackedTierClassifier.
6. Invoke ex.execute(task_for_fetch_and_extract, notes, tasks).
7. Assert: TaskResult has one NoteMutation with tier != TIER_5,
   peer_reviewed per the scripted output, state=FETCHED, and spawns an
   ANALYZE_SOURCE task for the question listed in meta.relevance.

Unblocking this test is deliberately left for a follow-up: it requires
(a) a NoteReader fake (tests/fakes/notes.py), (b) a TaskReader fake, and
(c) a decision about how to inject the fake fetcher into the handler
(either ingest_source accepting a fetcher kwarg at the handler call site,
or a module-level patch of default_fetcher — design call, not Phase-1 work)."""

from __future__ import annotations

import pytest


@pytest.mark.skip(
    reason=(
        "Scaffolded only. See module docstring for the full test shape. "
        "Blocked on NoteReader/TaskReader fakes and a decision on fetcher injection."
    )
)
async def test_fetch_and_extract_happy_path_e2e() -> None:
    """End-to-end: handle_fetch_and_extract with fake LLM runner + fake
    fetcher. See module docstring."""
    pass
