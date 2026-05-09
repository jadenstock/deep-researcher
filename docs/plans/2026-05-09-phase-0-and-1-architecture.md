# Architecture Deepening — Phase 0 + Phase 1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Land the test scaffolding and the two highest-leverage architectural seams — the **LLM runner** and the **source extraction pipeline** — so Phase 2 (handler skeleton, pattern-as-behavior) can be grilled and executed against a real test surface.

**Architecture:** Two new modules (`executor/llm.py`, `retrieval/ingestion.py`), each a small interface over existing loose imports. Existing handlers remain on the `ctx.track(Agent(...))` path unchanged *except* `handle_fetch_and_extract` and the tier-classifier call path, which migrate to the new seams as proof. Everything behind the seams is covered by tests using a `FakeLLMRunner` and fixture-based HTTP fakes — no network in the test suite.

**Tech Stack:** Python 3.12, pytest + pytest-asyncio (already configured in `pyproject.toml`), pydantic-ai (existing), no new runtime deps.

**Scope boundary:** Phase 2 (handler skeleton, pattern-as-behavior) and Phase 3 (NoteDigest, Phase state machine) are explicitly **out of scope** for this plan — they will be written after Phase 1 lands and we have learned from a working test surface. This plan does **not** touch handlers other than `handle_fetch_and_extract`, does **not** modify the scheduler, and does **not** change any ADR.

---

## Why this ordering

- **Phase 0 first** — TDD-shaped tasks require test scaffolding. The codebase currently has no `tests/` directory, no conftest, no fake adapters. Building it once here means every downstream task can be TDD.
- **LLM runner before source extraction** — the source-extraction pipeline invokes the tier classifier (an LLM call). Having the runner seam first means ingestion can be tested without touching the network or patching `pydantic_ai.Agent` globally.
- **Migrate only `handle_fetch_and_extract`** — it's the one handler the source-extraction module directly replaces. Other handlers stay on the old path; their migration is Phase 2 work. This preserves blast radius.

## ADR alignment

- **ADR-0003** (LLM-based tier classification): unchanged; `classify_source` is refactored internally to call through the LLM runner but the semantics, prompt, and output schema are identical.
- **ADR-0007** (source extraction size-first routing): formalized by this plan — the new `retrieval/ingestion.py` is the module that ADR describes.
- **ADR-0008** (role-to-model routing with ablation): strengthened — the LLM runner is the single seam where `(role, tier) → model_id` resolution happens.

No ADRs are modified.

---

## Task Overview

| # | Task | Output |
|---|------|--------|
| 0.1 | Create `tests/` scaffolding + conftest | `tests/conftest.py` |
| 0.2 | Define `FakeLLMRunner` spec + scripted-reply fake | `tests/fakes/llm.py` |
| 0.3 | Define retrieval fakes (fetch + tier classifier) | `tests/fakes/retrieval.py` |
| 0.4 | Smoke test — harness runs green | `tests/test_smoke.py` |
| 1.1 | Write failing test for `LLMRunner` protocol contract | `tests/executor/test_llm_runner.py` |
| 1.2 | Implement `LLMRunner` protocol + `PydanticAIRunner` | `src/.../executor/llm.py` |
| 1.3 | Wire runner into `HandlerContext` (additive; don't remove `ctx.track`) | `src/.../executor/executor.py` |
| 1.4 | Refactor `classify_source` to accept a runner | `src/.../tiering/classifier.py` |
| 1.5 | Test + migrate tier-classifier call path | `tests/tiering/test_classifier.py` |
| 2.1 | Write failing test for `ingest_source` short-content path | `tests/retrieval/test_ingestion.py` |
| 2.2 | Define `IngestionResult` + `Fetcher` / `TierClassifier` protocols | `src/.../retrieval/ingestion.py` |
| 2.3 | Implement short-content path | same |
| 2.4 | Write failing test for long-content path + implement | same |
| 2.5 | Write failing test for reject-list + fetch-failure paths + implement | same |
| 2.6 | Migrate `handle_fetch_and_extract` to call `ingest_source` | `src/.../executor/handlers.py` |
| 2.7 | Integration test — real handler with fake runner + fake fetcher | `tests/executor/test_handlers_fetch.py` |

---

# Phase 0: Test Scaffolding

Goal: `uv run pytest` works, runs a trivial assertion, and exposes fakes other tasks will use.

---

### Task 0.1: Create `tests/` scaffolding + conftest

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/fakes/__init__.py`
- Create: `tests/conftest.py`

**Step 1: Create empty package markers**

```bash
mkdir -p /Users/jaden.stock/Documents/deep-research-agent/tests/fakes
touch /Users/jaden.stock/Documents/deep-research-agent/tests/__init__.py
touch /Users/jaden.stock/Documents/deep-research-agent/tests/fakes/__init__.py
```

**Step 2: Write `tests/conftest.py`**

```python
"""Project-wide test fixtures. Keep this file small — domain-specific
fixtures belong in nearer conftest.py files."""

from __future__ import annotations

import pytest

from deep_research_agent.config import LocalConfig


@pytest.fixture
def local_config() -> LocalConfig:
    """A LocalConfig instance safe for tests — never hits a real endpoint."""
    return LocalConfig(
        api_base_url="http://test.invalid/v1",
        api_key="test-key-not-used",
    )
```

**Step 3: Verify pytest discovers the package**

Run: `uv run pytest --collect-only -q`
Expected: no errors (no tests collected yet is fine)

**Step 4: Commit**

```bash
git add tests/
git commit -m "test: add tests/ scaffolding and LocalConfig fixture"
```

---

### Task 0.2: Define `FakeLLMRunner`

**Files:**
- Create: `tests/fakes/llm.py`

Design: `FakeLLMRunner.run(...)` looks up a scripted response keyed by `(task_type, role, tier)` or by a caller-supplied `script_key`. If no entry is found, raises `ScriptMissing` with the key — forcing tests to declare intent. Does **not** invoke pydantic-ai.

**Step 1: Write `tests/fakes/llm.py`**

```python
"""Deterministic fake for the LLMRunner protocol.

Usage:
    runner = FakeLLMRunner()
    runner.script("tier_classify", TierClassifierOutput(
        tier=2, rationale="arXiv preprint", confidence=0.8, peer_reviewed=False
    ))
    result = await runner.run(script_key="tier_classify", ...)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class ScriptMissing(KeyError):
    """No scripted response registered for this key."""


@dataclass
class RunnerCall:
    script_key: str
    role: str
    tier: str
    system_prompt: str
    user_prompt: str


@dataclass
class FakeLLMRunner:
    _responses: dict[str, Any] = field(default_factory=dict)
    _handlers: dict[str, Callable[[RunnerCall], Any]] = field(default_factory=dict)
    calls: list[RunnerCall] = field(default_factory=list)

    def script(self, key: str, response: Any) -> None:
        """Register a literal response for `key`."""
        self._responses[key] = response

    def script_fn(self, key: str, fn: Callable[[RunnerCall], Any]) -> None:
        """Register a callable that receives the call and returns the response.

        Use when the response must depend on the user_prompt (e.g., tier-
        classify a specific URL)."""
        self._handlers[key] = fn

    async def run(
        self,
        *,
        script_key: str,
        role: Any,
        tier: Any,
        output_type: type,
        system_prompt: str,
        user_prompt: str,
        task_type: str | None = None,
    ) -> Any:
        call = RunnerCall(
            script_key=script_key,
            role=str(role),
            tier=str(tier),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        self.calls.append(call)
        if script_key in self._handlers:
            return self._handlers[script_key](call)
        if script_key not in self._responses:
            raise ScriptMissing(
                f"No scripted response for key={script_key!r}. "
                f"Registered keys: {list(self._responses)}"
            )
        return self._responses[script_key]
```

**Step 2: Run pytest — should still pass (no tests yet)**

Run: `uv run pytest -q`
Expected: 0 tests collected, exit 5 (pytest exit code for "no tests collected") — this is fine.

**Step 3: Commit**

```bash
git add tests/fakes/llm.py
git commit -m "test: add FakeLLMRunner with scripted responses"
```

---

### Task 0.3: Define retrieval fakes

**Files:**
- Create: `tests/fakes/retrieval.py`

**Step 1: Write `tests/fakes/retrieval.py`**

```python
"""Fakes for the Fetcher protocol and tier-classifier protocol.

`FakeFetcher` maps URLs → FetchResult-like canned responses.
`FakeTierClassifier` maps URLs → (tier, rationale, confidence, peer_reviewed).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from deep_research_agent.retrieval.fetch import FetchResult
from deep_research_agent.schemas.enums import Tier


@dataclass
class FakeFetcher:
    _responses: dict[str, FetchResult | None] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def script(self, url: str, result: FetchResult | None) -> None:
        self._responses[url] = result

    async def fetch(self, url: str) -> FetchResult | None:
        self.calls.append(url)
        if url not in self._responses:
            raise KeyError(
                f"FakeFetcher: no scripted response for {url!r}. "
                f"Registered: {list(self._responses)}"
            )
        return self._responses[url]


@dataclass
class FakeTierClassifier:
    _responses: dict[str, tuple[Tier, str, float, bool]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def script(
        self, url: str, *, tier: Tier, rationale: str, confidence: float, peer_reviewed: bool
    ) -> None:
        self._responses[url] = (tier, rationale, confidence, peer_reviewed)

    async def classify(
        self, *, title: str, url: str, snippet: str, content: str
    ) -> tuple[Tier, str, float, bool]:
        self.calls.append(url)
        if url not in self._responses:
            raise KeyError(
                f"FakeTierClassifier: no scripted response for {url!r}. "
                f"Registered: {list(self._responses)}"
            )
        return self._responses[url]
```

**Step 2: Commit**

```bash
git add tests/fakes/retrieval.py
git commit -m "test: add FakeFetcher and FakeTierClassifier"
```

---

### Task 0.4: Smoke test

**Files:**
- Create: `tests/test_smoke.py`

**Step 1: Write `tests/test_smoke.py`**

```python
"""Smoke test — harness runs, fakes import, asyncio mode works."""

from __future__ import annotations

import pytest

from tests.fakes.llm import FakeLLMRunner, ScriptMissing


async def test_fake_runner_requires_script() -> None:
    runner = FakeLLMRunner()
    with pytest.raises(ScriptMissing):
        await runner.run(
            script_key="unseen",
            role="generative",
            tier="MID",
            output_type=str,
            system_prompt="",
            user_prompt="",
        )


async def test_fake_runner_returns_scripted_response() -> None:
    runner = FakeLLMRunner()
    runner.script("ping", {"ok": True})
    got = await runner.run(
        script_key="ping",
        role="generative",
        tier="MID",
        output_type=dict,
        system_prompt="",
        user_prompt="ping?",
    )
    assert got == {"ok": True}
    assert len(runner.calls) == 1
    assert runner.calls[0].user_prompt == "ping?"
```

**Step 2: Run — verify it passes**

Run: `uv run pytest tests/test_smoke.py -v`
Expected: 2 passed

**Step 3: Commit**

```bash
git add tests/test_smoke.py
git commit -m "test: smoke test verifies fake LLM runner harness"
```

---

# Phase 1a: LLM Runner Seam

Goal: One interface — `LLMRunner.run(...)` — covers every LLM invocation. Model selection, token tracking, and logging live behind it. Handlers never construct `Agent(...)` directly when they use this seam.

Scope limit: we introduce the seam and migrate the tier-classifier call site. The existing `ctx.track(agent, user_input)` path remains for the other 11 handlers — they'll migrate in Phase 2.

---

### Task 1.1: Failing test for `LLMRunner` protocol contract

**Files:**
- Create: `tests/executor/__init__.py`
- Create: `tests/executor/test_llm_runner.py`

**Step 1: Package marker**

```bash
touch /Users/jaden.stock/Documents/deep-research-agent/tests/executor/__init__.py
```

**Step 2: Write the failing test**

```python
"""LLMRunner contract: selects model via routing, tracks tokens,
returns typed output wrapped in LLMResult."""

from __future__ import annotations

from pydantic import BaseModel

from deep_research_agent.executor.llm import LLMResult, PydanticAIRunner
from deep_research_agent.schemas.enums import RoleClass, TaskTier


class _EchoOutput(BaseModel):
    echo: str


async def test_pydantic_ai_runner_resolves_model_from_routing(
    routing_config_basic, local_config, fake_pydantic_ai_agent
) -> None:
    """The runner resolves (role, tier) → model_id via routing config and
    hands that model_id to the constructed Agent."""
    # Expect: runner.run(role=GENERATIVE, tier=MID, ...) resolves to the
    # model_id declared in routing_config_basic for that pair.
    runner = PydanticAIRunner(
        routing=routing_config_basic,
        local=local_config,
        tracker=None,
        agent_factory=fake_pydantic_ai_agent,  # captures model_id + returns scripted result
    )
    fake_pydantic_ai_agent.script_output(_EchoOutput(echo="hi"))

    result: LLMResult[_EchoOutput] = await runner.run(
        role=RoleClass.GENERATIVE,
        tier=TaskTier.MID,
        output_type=_EchoOutput,
        system_prompt="you echo",
        user_prompt="hi",
        task_type="TEST",
    )

    assert result.output.echo == "hi"
    assert fake_pydantic_ai_agent.last_model_id == routing_config_basic.model_id_for(
        RoleClass.GENERATIVE, TaskTier.MID
    )
```

This test references fixtures (`routing_config_basic`, `fake_pydantic_ai_agent`) that don't exist yet. They'll be added alongside the implementation.

**Step 3: Run — verify it fails**

Run: `uv run pytest tests/executor/test_llm_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: deep_research_agent.executor.llm`

**Step 4: Commit** (red phase)

```bash
git add tests/executor/
git commit -m "test: failing test for LLMRunner contract"
```

---

### Task 1.2: Implement `LLMRunner` protocol + `PydanticAIRunner`

**Files:**
- Create: `src/deep_research_agent/executor/llm.py`
- Modify: `tests/conftest.py` (add `routing_config_basic` and `fake_pydantic_ai_agent` fixtures)

**Step 1: Write `src/deep_research_agent/executor/llm.py`**

```python
"""LLM Runner seam.

One interface for every LLM call in the system. The runner owns:

- `(role, tier) → model_id` resolution via RoutingConfig
- Cross-family invariant enforcement (ADR-0008)
- Agent construction (hidden from callers)
- Token usage tracking and structured logging
- Returning typed output wrapped in LLMResult

Callers pass role + tier + output_type + prompts; they do not know about
pydantic_ai, make_model, or RoutingConfig internals. Tests replace the
runner with a FakeLLMRunner that returns scripted output.

Phase-1 scope: this module is additive. Existing handlers continue to
use `ctx.track(Agent(...))` until Phase 2. Only the tier classifier
migrates here in Phase 1.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar

from pydantic_ai import Agent

from ..agent_factory import make_model
from ..config import LocalConfig, RoutingConfig
from ..schemas.enums import RoleClass, TaskTier, TaskType
from ..token_usage import TokenUsageTracker
from .routing import select_model

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class LLMResult(Generic[T]):
    """Typed output + resolved model_id + elapsed_ms. Usage is already
    booked into the tracker by the runner — callers don't need to."""

    output: T
    model_id: str
    elapsed_ms: int


class LLMRunner(Protocol):
    async def run(
        self,
        *,
        role: RoleClass,
        tier: TaskTier,
        output_type: type[T],
        system_prompt: str,
        user_prompt: str,
        task_type: str | TaskType | None = None,
        forbidden_family: str | None = None,
        script_key: str | None = None,  # ignored by real runner; used by fakes
    ) -> LLMResult[T]: ...


AgentFactory = Callable[[str, LocalConfig, type, str], Any]
"""Hook so tests can replace Agent construction. Signature:
    (model_id, local, output_type, system_prompt) -> Agent-like with .run()"""


def _default_agent_factory(
    model_id: str, local: LocalConfig, output_type: type, system_prompt: str
) -> Any:
    return Agent(
        make_model(model_id, local),
        output_type=output_type,
        system_prompt=system_prompt,
    )


@dataclass
class PydanticAIRunner:
    """Real LLMRunner — wraps pydantic_ai.Agent."""

    routing: RoutingConfig
    local: LocalConfig
    tracker: TokenUsageTracker | None = None
    agent_factory: AgentFactory = _default_agent_factory

    async def run(
        self,
        *,
        role: RoleClass,
        tier: TaskTier,
        output_type: type[T],
        system_prompt: str,
        user_prompt: str,
        task_type: str | TaskType | None = None,
        forbidden_family: str | None = None,
        script_key: str | None = None,  # unused by real runner
    ) -> LLMResult[T]:
        tt = (
            task_type
            if isinstance(task_type, TaskType)
            else (TaskType(task_type) if task_type else None)
        )
        model_id = select_model(
            self.routing,
            role=role,
            tier=tier,
            task_type=tt if tt is not None else TaskType.ANALYZE_SOURCE,
            forbidden_family=forbidden_family,
        )
        agent = self.agent_factory(model_id, self.local, output_type, system_prompt)
        t0 = time.monotonic()
        r = await agent.run(user_prompt)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        usage = r.usage() if hasattr(r, "usage") else None
        task_label = (
            tt.value if tt is not None else (str(task_type) if task_type else "UNKNOWN")
        )
        if usage is not None and self.tracker is not None:
            await self.tracker.record(model_id, usage, task_type=task_label)
            logger.info(
                "llm_call model=%s task=%s in=%d out=%d ms=%d",
                model_id,
                task_label,
                getattr(usage, "input_tokens", 0) or 0,
                getattr(usage, "output_tokens", 0) or 0,
                elapsed_ms,
            )
        else:
            logger.info(
                "llm_call model=%s task=%s usage=unavailable ms=%d",
                model_id,
                task_label,
                elapsed_ms,
            )
        return LLMResult(output=r.output, model_id=model_id, elapsed_ms=elapsed_ms)
```

**Step 2: Add fixtures to `tests/conftest.py`**

```python
# Append to existing tests/conftest.py

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from deep_research_agent.config import RoutingConfig


@pytest.fixture
def routing_config_basic() -> RoutingConfig:
    """Minimal RoutingConfig sufficient for (role, tier) → model_id resolution."""
    # Use a real example routing file if one exists, otherwise construct
    # a minimal dict and feed it through the loader.
    config_path = Path(__file__).parent.parent / "config" / "routing_diverse.yaml"
    if config_path.exists():
        return RoutingConfig.from_yaml(config_path)
    # Inline fallback — keeps tests working if the example file is absent.
    raw = {
        "families": {"anthropic": ["claude-sonnet-4"], "openai": ["gpt-4o-mini"]},
        "roles": {
            "generative": {"HIGH": "claude-sonnet-4", "MID": "claude-sonnet-4", "LOW": "claude-sonnet-4"},
            "judgment": {"HIGH": "gpt-4o-mini", "MID": "gpt-4o-mini", "LOW": "gpt-4o-mini"},
            "cheap_deterministic": {"HIGH": "gpt-4o-mini", "MID": "gpt-4o-mini", "LOW": "gpt-4o-mini"},
        },
        "cross_family_invariant": {"enabled": False, "applies_to": []},
    }
    return RoutingConfig.model_validate(raw)


@dataclass
class _FakePydanticAIAgent:
    """Captures what was passed to Agent(...) and returns a scripted output."""

    last_model_id: str | None = None
    last_system_prompt: str | None = None
    last_output_type: type | None = None
    last_user_prompt: str | None = None
    _scripted_output: Any = None

    def script_output(self, output: Any) -> None:
        self._scripted_output = output

    def __call__(self, model_id: str, local: Any, output_type: type, system_prompt: str) -> Any:
        self.last_model_id = model_id
        self.last_output_type = output_type
        self.last_system_prompt = system_prompt
        return self

    async def run(self, user_prompt: str) -> Any:
        self.last_user_prompt = user_prompt
        # Mimic pydantic_ai's RunResult shape (has .output and .usage())
        return _FakeRunResult(output=self._scripted_output)


@dataclass
class _FakeRunResult:
    output: Any

    def usage(self) -> None:
        return None


@pytest.fixture
def fake_pydantic_ai_agent() -> _FakePydanticAIAgent:
    return _FakePydanticAIAgent()
```

**Step 3: Verify whatever import shape `RoutingConfig` uses**

The fixture above assumes `RoutingConfig.from_yaml(path)` exists. If it doesn't, substitute the actual loader:
```bash
grep -n "from_yaml\|load_routing\|RoutingConfig" /Users/jaden.stock/Documents/deep-research-agent/src/deep_research_agent/config.py | head
```
Adjust the fixture to use whatever loader exists (likely `load_routing_config(path)` or similar). If only dict-based construction is available, keep the inline fallback and delete the file-based branch.

**Step 4: Run test — verify it passes**

Run: `uv run pytest tests/executor/test_llm_runner.py -v`
Expected: 1 passed

**Step 5: Run ruff**

Run: `uv run ruff check --fix src/deep_research_agent/executor/llm.py tests/ && uv run ruff format src/deep_research_agent/executor/llm.py tests/`

**Step 6: Commit**

```bash
git add src/deep_research_agent/executor/llm.py tests/
git commit -m "feat(executor): add LLMRunner seam with PydanticAIRunner adapter"
```

---

### Task 1.3: Wire runner into `HandlerContext`

Make the runner available to handlers without removing the existing `ctx.track` path — migration of non-fetch handlers is Phase 2 work.

**Files:**
- Modify: `src/deep_research_agent/executor/executor.py`
- Create: `tests/executor/test_executor_wiring.py`

**Step 1: Write failing test**

```python
"""AgentExecutor constructs a PydanticAIRunner and exposes it on
HandlerContext as ctx.llm."""

from __future__ import annotations

from deep_research_agent.executor.executor import AgentExecutor
from deep_research_agent.executor.llm import PydanticAIRunner


async def test_handler_context_exposes_llm_runner(
    routing_config_basic, local_config
) -> None:
    ex = AgentExecutor(routing=routing_config_basic, local=local_config)
    # Executor should now expose the runner it will pass on ctx.
    assert isinstance(ex.llm, PydanticAIRunner)
```

Run: `uv run pytest tests/executor/test_executor_wiring.py -v`
Expected: FAIL (AttributeError on `ex.llm`)

**Step 2: Modify `executor.py`**

Add to `AgentExecutor.__init__`:
```python
from .llm import LLMRunner, PydanticAIRunner

class AgentExecutor:
    def __init__(
        self,
        routing: RoutingConfig,
        local: LocalConfig,
        pipeline: PipelineConfig | None = None,
        tracker: TokenUsageTracker | None = None,
        llm: LLMRunner | None = None,  # injectable for tests
    ) -> None:
        self.routing = routing
        self.local = local
        self.pipeline = pipeline if pipeline is not None else PipelineConfig()
        self.tracker = tracker or TokenUsageTracker()
        self.llm: LLMRunner = llm or PydanticAIRunner(
            routing=self.routing, local=self.local, tracker=self.tracker
        )
        self._handlers: dict[TaskType, HandlerFn] = {}
```

Add `llm: LLMRunner` field to `HandlerContext` (dataclass):
```python
@dataclass(frozen=True)
class HandlerContext:
    task: Task
    notes: NoteReader
    tasks: TaskReader
    model_id: str
    routing: RoutingConfig
    local: LocalConfig
    pipeline: PipelineConfig
    tracker: TokenUsageTracker
    llm: LLMRunner  # NEW — available to handlers that want the seam
    # ... existing .track method stays unchanged
```

Update `execute()` to pass `llm=self.llm` in the `HandlerContext(...)` call.

**Step 3: Run — verify it passes**

Run: `uv run pytest tests/executor/ -v`
Expected: all pass (both tests)

**Step 4: Run full suite to catch collateral breakage**

Run: `uv run pytest -v`
Expected: all pass. If the old handler code breaks because it instantiates `HandlerContext` somewhere without `llm`, locate those sites (`grep -rn "HandlerContext(" src/`) and pass through `ctx.llm` or accept they're inaccessible — the only legitimate constructor site is `AgentExecutor.execute`.

**Step 5: Ruff + commit**

```bash
uv run ruff check --fix src/ tests/
uv run ruff format src/ tests/
git add src/deep_research_agent/executor/executor.py tests/executor/test_executor_wiring.py
git commit -m "feat(executor): expose LLMRunner on HandlerContext as ctx.llm"
```

---

### Task 1.4: Refactor `classify_source` to accept a runner

Swap the inline `Agent(...)` + `agent.run(...)` in `tiering/classifier.py` for a runner call. Prompt, output schema, reject-list behavior, and return tuple are unchanged.

**Files:**
- Modify: `src/deep_research_agent/tiering/classifier.py`
- Create: `tests/tiering/__init__.py`
- Create: `tests/tiering/test_classifier.py`

**Step 1: Write failing test**

```bash
touch /Users/jaden.stock/Documents/deep-research-agent/tests/tiering/__init__.py
```

`tests/tiering/test_classifier.py`:
```python
from __future__ import annotations

from deep_research_agent.schemas.enums import Tier
from deep_research_agent.tiering.classifier import (
    TierClassifierOutput,
    classify_source_via_runner,
)
from tests.fakes.llm import FakeLLMRunner


async def test_reject_list_short_circuits_to_tier_5() -> None:
    runner = FakeLLMRunner()  # no scripts — must not be called
    tier, rationale, confidence, peer_reviewed = await classify_source_via_runner(
        runner=runner,
        title="spam",
        url="https://pinterest.com/xyz",
        snippet="",
        content="",
    )
    assert tier == Tier.TIER_5
    assert "reject list" in rationale
    assert runner.calls == []  # no LLM call happened


async def test_classifier_calls_runner_with_cheap_deterministic_low() -> None:
    runner = FakeLLMRunner()
    runner.script(
        "tier_classify",
        TierClassifierOutput(
            tier=2,
            rationale="arXiv preprint with methodology",
            confidence=0.8,
            peer_reviewed=False,
        ),
    )
    tier, rationale, confidence, peer_reviewed = await classify_source_via_runner(
        runner=runner,
        title="Attention Is All You Need",
        url="https://arxiv.org/abs/1706.03762",
        snippet="We propose the Transformer...",
        content="# Abstract\nWe propose..." * 200,
    )
    assert tier == Tier.TIER_2
    assert peer_reviewed is False
    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert call.role == "RoleClass.CHEAP_DETERMINISTIC"
    assert call.tier == "TaskTier.LOW"


async def test_classifier_fallback_on_runner_exception() -> None:
    class _BoomRunner(FakeLLMRunner):
        async def run(self, **kwargs):
            raise RuntimeError("boom")

    runner = _BoomRunner()
    tier, rationale, confidence, peer_reviewed = await classify_source_via_runner(
        runner=runner,
        title="x",
        url="https://example.com/article",
        snippet="",
        content="x" * 100,
    )
    assert tier == Tier.TIER_3
    assert confidence <= 0.3
    assert peer_reviewed is False
```

Run: `uv run pytest tests/tiering/ -v`
Expected: FAIL (ImportError on `classify_source_via_runner`)

**Step 2: Add `classify_source_via_runner` to `tiering/classifier.py`**

Keep the existing `classify_source(...)` function — it's still called by old code paths. Add a new function alongside it:

```python
# Append to src/deep_research_agent/tiering/classifier.py

from typing import TYPE_CHECKING

from ..schemas.enums import RoleClass, TaskTier, TaskType

if TYPE_CHECKING:
    from ..executor.llm import LLMRunner


async def classify_source_via_runner(
    *,
    runner: LLMRunner,
    title: str,
    url: str,
    snippet: str,
    content: str,
) -> tuple[Tier, str, float, bool]:
    """Classify one source. Same semantics as classify_source() but
    routes through the LLMRunner seam instead of building an Agent
    directly. Reject-list short-circuits still apply and skip the LLM."""
    hit_rejected = _reject_list_tier(url)
    if hit_rejected is not None:
        tier, rationale = hit_rejected
        return tier, rationale, 1.0, False

    user = (
        f"Title: {title}\n"
        f"URL: {url}\n"
        f"Snippet: {snippet}\n\n"
        f"Content excerpt (first {CONTENT_EXCERPT_CHARS} chars):\n"
        f"{content[:CONTENT_EXCERPT_CHARS]}"
    )
    try:
        result = await runner.run(
            role=RoleClass.CHEAP_DETERMINISTIC,
            tier=TaskTier.LOW,
            output_type=TierClassifierOutput,
            system_prompt=TIER_CLASSIFIER_SYSTEM,
            user_prompt=user,
            task_type="TIER_CLASSIFY",
            script_key="tier_classify",
        )
    except Exception as exc:
        logger.warning("tier classifier failed url=%s err=%s", url, exc)
        return Tier.TIER_3, "classifier failed; default to generic web tier", 0.2, False

    out = result.output
    return Tier(out.tier), out.rationale, out.confidence, out.peer_reviewed
```

Note: `TIER_CLASSIFY` is not in the `TaskType` enum (it's a sub-step), so `task_type="TIER_CLASSIFY"` is passed as a string — the runner handles both. Verify with:
```bash
grep -n "TIER_CLASSIFY\|class TaskType" /Users/jaden.stock/Documents/deep-research-agent/src/deep_research_agent/schemas/enums.py
```
If `TIER_CLASSIFY` is a real enum value, use `TaskType.TIER_CLASSIFY`. If not, the string passes through the runner as a label only — harmless.

**Step 3: Run — verify tests pass**

Run: `uv run pytest tests/tiering/ -v`
Expected: 3 passed

**Step 4: Ruff + commit**

```bash
uv run ruff check --fix src/deep_research_agent/tiering/classifier.py tests/tiering/
uv run ruff format src/deep_research_agent/tiering/classifier.py tests/tiering/
git add src/deep_research_agent/tiering/classifier.py tests/tiering/
git commit -m "feat(tiering): add classify_source_via_runner using LLMRunner seam"
```

---

### Task 1.5: (deferred to Task 2.6)

Tier classifier migration at the call site happens in Task 2.6, when we rewrite `handle_fetch_and_extract`. No separate task.

---

# Phase 1b: Source Extraction Pipeline

Goal: `retrieval/ingestion.py` is the module CONTEXT.md §68–78 describes — fetch → format-convert → size-route → tier-classify → cache, behind one interface. `handle_fetch_and_extract` becomes ~30 lines of note-mutation logic that calls `ingest_source(url)`.

---

### Task 2.1: Failing test for `ingest_source` short-content path

**Files:**
- Create: `tests/retrieval/__init__.py`
- Create: `tests/retrieval/test_ingestion.py`

**Step 1: Package marker**

```bash
touch /Users/jaden.stock/Documents/deep-research-agent/tests/retrieval/__init__.py
```

**Step 2: Write failing test**

```python
"""ingest_source pipeline: short content path.

Short content (< 8K tokens) should return IngestionResult with the full
markdown in .content and structured_content=None."""

from __future__ import annotations

from deep_research_agent.retrieval.fetch import FetchResult
from deep_research_agent.retrieval.ingestion import IngestionResult, ingest_source
from deep_research_agent.schemas.enums import Tier
from tests.fakes.retrieval import FakeFetcher, FakeTierClassifier


async def test_short_content_returns_full_markdown_and_no_structure() -> None:
    fetcher = FakeFetcher()
    classifier = FakeTierClassifier()

    fetcher.script(
        "https://example.com/post",
        FetchResult(
            url="https://example.com/post",
            final_url="https://example.com/post",
            status_code=200,
            content_type="text/html",
            title="A short post",
            markdown="# A short post\n\nJust a paragraph.",
            byte_length=100,
        ),
    )
    classifier.script(
        "https://example.com/post",
        tier=Tier.TIER_3,
        rationale="blog post",
        confidence=0.7,
        peer_reviewed=False,
    )

    result: IngestionResult = await ingest_source(
        url="https://example.com/post",
        snippet="",
        fetcher=fetcher,
        tier_classifier=classifier,
    )
    assert result.status == "ok"
    assert result.content == "# A short post\n\nJust a paragraph."
    assert result.structured_content is None
    assert result.tier == Tier.TIER_3
    assert result.peer_reviewed is False
    assert result.title == "A short post"
```

**Step 3: Run — verify it fails**

Run: `uv run pytest tests/retrieval/test_ingestion.py -v`
Expected: FAIL (ModuleNotFoundError)

**Step 4: Commit the red test**

```bash
git add tests/retrieval/
git commit -m "test: failing test for ingest_source short-content path"
```

---

### Task 2.2 + 2.3: Implement `ingest_source` short-content path

**Files:**
- Create: `src/deep_research_agent/retrieval/ingestion.py`
- Modify: `src/deep_research_agent/retrieval/__init__.py` (export `ingest_source`, `IngestionResult`)

**Step 1: Write `src/deep_research_agent/retrieval/ingestion.py`**

```python
"""Source extraction pipeline (CONTEXT.md §68–78, ADR-0007).

Given a URL, produce an IngestionResult that a caller can turn into a
populated source_note. The pipeline is deterministic (no LLM) except for
tier classification, which is delegated to a TierClassifier protocol.

Stages:
    1. Fetch (HTML → trafilatura, PDF → MarkItDown) via Fetcher protocol.
    2. Short-circuit to a "failed" IngestionResult on connection errors
       or empty markdown (caller records Tier 5, state=FETCHED).
    3. Tier classify via TierClassifier protocol.
    4. Size route: short content → full markdown; long content →
       StructuredContent + truncated raw.
    5. Return IngestionResult.

The module owns composition only — fetch and structure logic stays in
their respective modules.

Callers inject Fetcher and TierClassifier; tests inject fakes. The
default production Fetcher wraps fetch_and_extract(); the default
production TierClassifier wraps classify_source_via_runner().
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from ..schemas.enums import Tier
from ..schemas.source import StructuredContent
from .fetch import FetchResult, fetch_and_extract
from .structure import build_structured_content, is_long_source

# Cap markdown stored on the note — the full raw is kept in the fetch
# cache and can be re-read by load_source_section.
MAX_NOTE_CONTENT_CHARS = 40_000


class Fetcher(Protocol):
    async def fetch(self, url: str) -> FetchResult | None: ...


class TierClassifier(Protocol):
    async def classify(
        self, *, title: str, url: str, snippet: str, content: str
    ) -> tuple[Tier, str, float, bool]: ...


@dataclass(frozen=True)
class IngestionResult:
    status: Literal["ok", "fetch_failed"]
    url: str
    final_url: str
    title: str | None
    content: str  # markdown truncated to MAX_NOTE_CONTENT_CHARS; empty on failure
    structured_content: StructuredContent | None  # populated iff long source
    tier: Tier
    tier_rationale: str
    classifier_confidence: float
    peer_reviewed: bool


class _RealFetcher:
    async def fetch(self, url: str) -> FetchResult | None:
        return await fetch_and_extract(url)


def default_fetcher() -> Fetcher:
    return _RealFetcher()


async def ingest_source(
    *,
    url: str,
    snippet: str,
    fetcher: Fetcher,
    tier_classifier: TierClassifier,
) -> IngestionResult:
    """Run the source extraction pipeline for one URL.

    Returns an IngestionResult for every input — even failures.
    Callers never see raw fetch exceptions; they translate an
    IngestionResult into a NoteMutation directly."""
    fetch = await fetcher.fetch(url)
    if fetch is None or not fetch.markdown:
        return IngestionResult(
            status="fetch_failed",
            url=url,
            final_url=url,
            title=None,
            content="",
            structured_content=None,
            tier=Tier.TIER_5,
            tier_rationale="fetch failed (empty or blocked)",
            classifier_confidence=1.0,
            peer_reviewed=False,
        )

    title = fetch.title or url
    tier, rationale, confidence, peer_reviewed = await tier_classifier.classify(
        title=title, url=url, snippet=snippet, content=fetch.markdown
    )

    structured: StructuredContent | None = None
    if is_long_source(fetch.markdown):
        structured = build_structured_content(title, fetch.markdown)

    return IngestionResult(
        status="ok",
        url=url,
        final_url=fetch.final_url,
        title=fetch.title,
        content=fetch.markdown[:MAX_NOTE_CONTENT_CHARS],
        structured_content=structured,
        tier=tier,
        tier_rationale=rationale,
        classifier_confidence=confidence,
        peer_reviewed=peer_reviewed,
    )
```

**Step 2: Export from `retrieval/__init__.py`**

Append:
```python
from .ingestion import IngestionResult, ingest_source, default_fetcher  # noqa: F401
```

**Step 3: Run — verify Task 2.1 test passes**

Run: `uv run pytest tests/retrieval/test_ingestion.py -v`
Expected: 1 passed

**Step 4: Ruff + commit**

```bash
uv run ruff check --fix src/deep_research_agent/retrieval/
uv run ruff format src/deep_research_agent/retrieval/
git add src/deep_research_agent/retrieval/
git commit -m "feat(retrieval): add ingest_source pipeline (short-content path)"
```

---

### Task 2.4: Long-content path

**Step 1: Add failing test to `tests/retrieval/test_ingestion.py`**

```python
async def test_long_content_builds_structured_content() -> None:
    fetcher = FakeFetcher()
    classifier = FakeTierClassifier()

    # Build a ~10K-token (~40K chars) markdown with real section structure
    # so build_structured_content has something to chew.
    long_md_parts = ["# Long paper\n\nAbstract paragraph here.\n\n"]
    for i in range(5):
        long_md_parts.append(f"## Section {i}\n\n" + ("filler " * 800) + "\n\n")
    long_md = "".join(long_md_parts)

    fetcher.script(
        "https://arxiv.org/abs/9999.99999",
        FetchResult(
            url="https://arxiv.org/abs/9999.99999",
            final_url="https://arxiv.org/abs/9999.99999",
            status_code=200,
            content_type="text/html",
            title="Long paper",
            markdown=long_md,
            byte_length=len(long_md),
        ),
    )
    classifier.script(
        "https://arxiv.org/abs/9999.99999",
        tier=Tier.TIER_2,
        rationale="arXiv preprint",
        confidence=0.85,
        peer_reviewed=False,
    )

    result = await ingest_source(
        url="https://arxiv.org/abs/9999.99999",
        snippet="",
        fetcher=fetcher,
        tier_classifier=classifier,
    )
    assert result.status == "ok"
    assert result.structured_content is not None
    assert result.structured_content.abstract is not None
    assert len(result.structured_content.section_headers) >= 5
    # Raw markdown also stored, truncated
    assert len(result.content) <= 40_000
```

**Step 2: Run — should already pass** (the short-content impl already handles the long branch via `is_long_source`).

Run: `uv run pytest tests/retrieval/test_ingestion.py -v`
Expected: 2 passed

**Step 3: Commit**

```bash
git add tests/retrieval/test_ingestion.py
git commit -m "test: ingest_source long-content path builds StructuredContent"
```

---

### Task 2.5: Reject-list + fetch-failure paths

**Step 1: Add failing tests**

Append to `tests/retrieval/test_ingestion.py`:
```python
async def test_fetch_failure_returns_tier_5_result() -> None:
    fetcher = FakeFetcher()
    classifier = FakeTierClassifier()  # must not be called
    fetcher.script("https://gone.example.com/", None)

    result = await ingest_source(
        url="https://gone.example.com/",
        snippet="",
        fetcher=fetcher,
        tier_classifier=classifier,
    )
    assert result.status == "fetch_failed"
    assert result.tier == Tier.TIER_5
    assert result.content == ""
    assert classifier.calls == []


async def test_empty_markdown_treated_as_fetch_failure() -> None:
    fetcher = FakeFetcher()
    classifier = FakeTierClassifier()
    fetcher.script(
        "https://paywall.example.com/",
        FetchResult(
            url="https://paywall.example.com/",
            final_url="https://paywall.example.com/",
            status_code=200,
            content_type="text/html",
            title=None,
            markdown=None,
            byte_length=1000,
        ),
    )
    result = await ingest_source(
        url="https://paywall.example.com/",
        snippet="",
        fetcher=fetcher,
        tier_classifier=classifier,
    )
    assert result.status == "fetch_failed"
    assert result.tier == Tier.TIER_5
    assert classifier.calls == []
```

**Step 2: Run — should pass** (the short-content impl already covers both branches).

Run: `uv run pytest tests/retrieval/test_ingestion.py -v`
Expected: 4 passed

**Step 3: Commit**

```bash
git add tests/retrieval/test_ingestion.py
git commit -m "test: ingest_source handles fetch failure and empty markdown"
```

---

### Task 2.6: Migrate `handle_fetch_and_extract`

This is the load-bearing step. The handler goes from ~57 lines of inline pipeline assembly to ~30 lines that call `ingest_source` and map the result onto `SourceNoteMetadata`.

**Files:**
- Modify: `src/deep_research_agent/executor/handlers.py` (only `handle_fetch_and_extract`)

**Step 1: Read the current handler to know exactly what changes**

Run: `grep -n "async def handle_fetch_and_extract" /Users/jaden.stock/Documents/deep-research-agent/src/deep_research_agent/executor/handlers.py`

Read the whole function (it begins around line 860 based on the architectural walk). Note:
- It loads the scouted source from `ctx.notes`
- Does inline fetch → tier-classify → structure-build → metadata assembly
- Spawns `ANALYZE_SOURCE` tasks afterwards — **KEEP THIS SPAWN LOGIC UNCHANGED.**

**Step 2: Introduce a small adapter binding `classify_source_via_runner` to the `TierClassifier` protocol**

Add to `src/deep_research_agent/tiering/classifier.py` (near the bottom):
```python
from dataclasses import dataclass

@dataclass
class RunnerBackedTierClassifier:
    """Adapter: LLMRunner → TierClassifier protocol."""

    runner: "LLMRunner"

    async def classify(
        self, *, title: str, url: str, snippet: str, content: str
    ) -> tuple[Tier, str, float, bool]:
        return await classify_source_via_runner(
            runner=self.runner,
            title=title,
            url=url,
            snippet=snippet,
            content=content,
        )
```

**Step 3: Rewrite `handle_fetch_and_extract`**

Replace the current `await fetch_and_extract(url)` + inline `classify_source(...)` + inline `build_structured_content(...)` block with a single `ingest_source(...)` call:

```python
# in src/deep_research_agent/executor/handlers.py, inside handle_fetch_and_extract
# (after the `if meta.state != SourceState.SCOUTED: return noop` early-out)

from ..retrieval.ingestion import IngestionResult, default_fetcher, ingest_source
from ..tiering.classifier import RunnerBackedTierClassifier

url = meta.url
result: IngestionResult = await ingest_source(
    url=url,
    snippet=meta.summary or "",
    fetcher=default_fetcher(),
    tier_classifier=RunnerBackedTierClassifier(runner=ctx.llm),
)

fetched_meta = meta.model_copy(
    update={
        "state": SourceState.FETCHED,
        "title": result.title or meta.title,
        "tier": result.tier,
        "tier_rationale": result.tier_rationale,
        "classifier_confidence": result.classifier_confidence,
        "peer_reviewed": result.peer_reviewed,
        "structured_content": result.structured_content,
    }
)
fetched_note = src.model_copy(
    update={
        "title": result.title or src.title,
        "content": result.content,
        "metadata": fetched_meta,
    }
)

if result.status == "fetch_failed":
    return TaskResult(
        note_mutations=[NoteMutation(kind="replace", note=fetched_note)],
        verdict=f"fetch failed for {url}",
    )

# ... KEEP the existing ANALYZE_SOURCE spawn block unchanged below ...
```

Remove the now-unused imports from `handlers.py`:
- `build_structured_content`
- `is_long_source`
- `fetch_and_extract`
- `classify_source` (if unused elsewhere in the file — check with `grep -n classify_source src/.../handlers.py`)

**Step 4: Run the full test suite**

Run: `uv run pytest -v`
Expected: all tests pass. `handle_fetch_and_extract` has no direct tests yet — Task 2.7 covers that.

**Step 5: Ruff**

Run:
```bash
uv run ruff check --fix src/deep_research_agent/executor/handlers.py src/deep_research_agent/tiering/classifier.py
uv run ruff format src/deep_research_agent/executor/handlers.py src/deep_research_agent/tiering/classifier.py
```

**Step 6: Commit**

```bash
git add src/deep_research_agent/executor/handlers.py src/deep_research_agent/tiering/classifier.py
git commit -m "refactor(handlers): handle_fetch_and_extract uses ingest_source + runner-backed tier classifier"
```

---

### Task 2.7: Integration test — real handler with fake runner + fake fetcher

**Files:**
- Create: `tests/executor/test_handlers_fetch.py`

**Step 1: Write the test**

The goal: drive `handle_fetch_and_extract` end-to-end with everything faked below the handler boundary. This test is the payoff — it's what was essentially impossible before the refactor.

```python
"""End-to-end: handle_fetch_and_extract with fake LLM runner and fake
fetcher. Verifies the handler's contract — given a SCOUTED source_note,
it emits a replaced note with populated metadata and spawns appropriate
ANALYZE_SOURCE tasks."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from deep_research_agent.executor.executor import AgentExecutor
from deep_research_agent.retrieval.fetch import FetchResult
from deep_research_agent.schemas.enums import Tier
from deep_research_agent.tiering.classifier import TierClassifierOutput
from tests.fakes.llm import FakeLLMRunner
from tests.fakes.retrieval import FakeFetcher


@pytest.fixture
def scouted_source_note():
    """Construct a source_note in SCOUTED state ready for FETCH_AND_EXTRACT."""
    # Build using real Note + SourceNoteMetadata constructors. Include
    # at least one question_id in relevance so the spawn branch runs.
    from deep_research_agent.schemas import (
        Note, SourceNoteMetadata, SourceState, Link,
    )
    from deep_research_agent.schemas.enums import NoteType
    # ... construct and return. See schemas/source.py for required fields.
    raise NotImplementedError(
        "Fill in based on current SourceNoteMetadata required fields — "
        "the plan doesn't lock this down because the schema may evolve."
    )


async def test_fetch_and_extract_happy_path(
    routing_config_basic, local_config, scouted_source_note
) -> None:
    # TODO once scouted_source_note is implemented:
    # - Build FakeFetcher with a FetchResult for the URL.
    # - Build FakeLLMRunner scripted with a TierClassifierOutput.
    # - Build a fake NoteReader that returns the scouted note.
    # - Build a fake TaskReader.
    # - Register all handlers with an AgentExecutor injecting the fake
    #   runner, patch default_fetcher() to return the fake.
    # - Invoke ex.execute(task_for_fetch_and_extract, notes, tasks).
    # - Assert: TaskResult has one NoteMutation with tier=TIER_2,
    #   peer_reviewed=False, state=FETCHED, and spawns an
    #   ANALYZE_SOURCE task for the question in relevance.
    pytest.skip(
        "Harness ready; fill in scouted_source_note fixture + wire "
        "patches once schemas are locked in."
    )
```

Leave this test as a **scaffolded skip** — its completion is where the payoff of the refactor becomes visible. Marking it `xfail` would hide it; `skip` with an explicit reason keeps it on the radar.

**Step 2: Run — verify the skip is picked up**

Run: `uv run pytest tests/executor/test_handlers_fetch.py -v`
Expected: 1 skipped

**Step 3: Commit**

```bash
git add tests/executor/test_handlers_fetch.py
git commit -m "test: scaffold end-to-end test for handle_fetch_and_extract"
```

---

# Verification Checklist

Before declaring Phase 0+1 complete, run:

```bash
# 1. Full test suite green
uv run pytest -v

# 2. Ruff clean
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# 3. App still boots (does NOT hit the network — just --help)
uv run dra --help
```

All three should succeed. If they do, Phase 1 lands cleanly.

---

# Post-Phase-1 Handoff

When Phase 1 lands:

1. **What now works** — every new seam has deterministic tests. `handle_fetch_and_extract` is the reference handler shape for Phase 2's migration.
2. **What still uses the old path** — 11 other handlers still call `Agent(make_model(...))` + `ctx.track(agent, ...)` directly. They're unchanged and functional; their migration is Phase 2.
3. **What Phase 2 needs to grill** — *before* Phase 2 gets a plan document:
   - What's the canonical handler shape? Callable-per-TaskType, class-per-TaskType, or pipeline-stage DSL?
   - Are patterns emitters (return DAGs of tasks) or orchestrators (run their own sub-flows)? Different answer in current code between retrieval-phase patterns and synthesis-phase patterns — this needs resolving before the rewrite.
   - Where does prompt assembly live? Per-handler files, or a shared `prompts/` module keyed by `(task_type, pattern)`?
4. **What Phase 3 should wait for** — NoteDigest and Phase-state-machine work should wait until Phase 2's handler shape is stable. Neither is urgent.

---

# Phase 2 & Phase 3 — High-Level Outline (Not Yet Detailed)

> **Status: intentionally sketchy.** Writing detailed task lists now would freeze interface decisions that need grilling against a working Phase-1 test surface. This section exists as an anchor so the overall arc isn't lost between planning sessions.

## Phase 2a — Handler Skeleton (#1 from the original candidate list)

**Goal.** Every handler conforms to one shape: *read digests → assemble typed input → call `ctx.llm` → parse typed output → return typed note mutations + emitted tasks.* `handlers.py` (2,273 lines) splits into per-TaskType modules of ~50–100 lines each.

**Preconditions.** Phase 1 landed. `handle_fetch_and_extract` is the reference shape — the other 11 handlers mirror it.

**Open interface questions (to grill before writing tasks):**
- **Shape** — callable-per-TaskType (what we have), class-per-TaskType (better for shared helpers), or pipeline-stage DSL (over-engineered?). The current `ctx.track` helper hints at the middle option but isn't fully committed.
- **Prompt location** — per-handler inline (bad for reuse), per-TaskType modules under `prompts/` keyed on `(task_type, pattern)`, or co-located with pattern definitions?
- **Output parsing** — pydantic `output_type` on the runner covers almost all cases; do we need a `parse_output` hook for the edge cases (e.g. QUESTION_SYNTHESIZE pattern-dependent post-processing)?
- **Spawn logic** — task emission currently lives in `patterns/single_researcher.py` as `emit_*` helpers. Keep there, or move into handlers?
- **Hard case — ACH flow** — `_run_ach_flow` currently runs three sequential LLM calls inside `handle_question_synthesize`. Under Phase 2b, this becomes a method on `patterns/ach.py`. The handler would call `patterns[task.pattern].orchestrate(...)` and get back a single typed result. Cross-check with Phase 2b before locking handler shape.

**Rough task groups:**
- Pick handler shape (grill); document as ADR-0010 if non-obvious.
- Extract prompt strings + system prompts into a `prompts/` package.
- Migrate handlers in order of risk: `handle_decompose` → `handle_landscape_survey` → retrieval-phase handlers → synthesis-phase handlers → completion-phase handlers.
- Per handler: unit test with fake LLM runner, fake note graph, fake corpus index.
- Delete `ctx.track` once the last handler stops using it. Delete dead imports from old `handlers.py` once it's empty.

## Phase 2b — Pattern as Behavior (#4)

**Goal.** Each pattern module owns its orchestration — *given a question_note and relevant source digests, return the orchestrated result.* No more `if task.pattern == X: ...` branching in handlers.

**Preconditions.** Phase 2a landed (so handlers have a stable shape to call into). Must be designed *with* Phase 2a — they share the handler/pattern boundary.

**Open interface questions:**
- **Shape of a Pattern** — protocol with `async def orchestrate(...)`, or data object + a `run_pattern(pattern, ctx, ...)` dispatcher? The former is more object-oriented; the latter keeps patterns as data per the current codebase.
- **Retrieval-phase vs. synthesis-phase asymmetry** — retrieval patterns emit sub-task DAGs (per the ADR); synthesis patterns run LLM calls in-process (ACH runs three). Does the interface unify both, or do we have `RetrievalPattern` and `SynthesisPattern` protocols?
- **Pattern escalation from the replanner** — the replanner currently escalates by setting `task.pattern`. Under Phase 2b, does it still do that, or does it emit "run pattern X on question Y" directly?
- **Ablation support** — patterns must be swappable at config time for the ablation matrix. This pins the answer to question 1 above: if patterns are data, swap by config key; if protocols, swap by import.

**Rough task groups:**
- Design decision + (maybe) ADR-0011.
- Migrate patterns one at a time. Order: `single_researcher` (simplest) → `maker_checker` → `multi_perspective` → `debate` → `ach` (most complex, inlines the most handler logic).
- Each migration: lift logic out of handler, add pattern-level unit test with fake runner.
- Delete the `if task.pattern == X` branches in handlers once all patterns own their own flow.

## Phase 3a — NoteDigest / Progressive Disclosure Seam (#5)

**Goal.** Enforce CONTEXT.md §56–57 — *agents receive `NoteDigest` by default; `load_note(id)` is a tool.*

**Preconditions.** Phase 2 landed. Handler shape is stable, so adding a digest layer doesn't churn the per-handler call sites again.

**Open interface questions:**
- **Digest shape** — the CONTEXT definition names five fields; does the code use exactly those, or does each note type extend them (e.g. `source_note` digest includes `tier`)?
- **Where does the seam live** — on `NoteReader` (reader returns digests by default, `.get_full(id)` for full)? Or as a wrapper that handlers must go through?
- **Tool exposure** — `load_note` is already mentioned in docstrings as a tool. Is it a real pydantic-ai tool registered on agents, or a helper handlers call synchronously?
- **Migration scope** — do we enforce digest-only access everywhere, or only on agents (LLM-facing calls)? Probably the latter; handlers themselves can still read full notes for mutation.

**Note on urgency.** CONTEXT.md treats this as load-bearing, but at current scale (MVP runs, ~dozens of notes) there's no actual context-bloat pressure. Don't block Phase 2 on this; it's a scaling backstop.

## Phase 3b — Phase as a First-Class Concept (#6)

**Goal.** The four phases named in CONTEXT.md (Landscape Survey / Decomposition / Deep Research / Completion & Report) become an explicit enum + state machine, not something inferred from task-graph topology.

**Preconditions.** None hard. Smallest of the six moves.

**Open interface questions:**
- **Where does phase live** — field on `Task`, field on the run, or derived from the scheduler's view of the task graph? The last avoids schema churn but doesn't solve the AI-navigability problem.
- **Who owns transitions** — the scheduler (explicit state machine) or the replanner (already reads graph state and mutates)?
- **What does `phases/` fill out as** — one file per phase with entry/exit/invariants? Or does most phase logic stay distributed and `phases/` only holds shared types?

**Value.** Mostly navigability. Small functional value. Don't pre-work it; do it whenever a reader or a Claude Code session next asks "where does the landscape survey happen?" and the answer is frustrating.

## Candidates deliberately *not* revisited in Phase 2/3

- **Unified retrieval provider protocol.** The per-provider modules (Brave, Semantic Scholar, arXiv, Unpaywall) have genuinely different shapes; a thin facade would be a shallow wrapper. The real missing seam was #3 (ingestion), landing in Phase 1. Leave the providers as-is.
- **`corpus/` rework.** `CorpusIndex` is a thin stateless view over the note graph. It's shallow, but its shallowness is the whole point — deleting it would re-scatter URL lookup across handlers. Keep it.
- **Replanner.** Already reasonably deep — it owns mutation semantics, the mutation budget, cascading rules (ADR-0009). Lowest-leverage target.

## Triggers to revisit this plan

- If Phase 1 reveals that the runner's `role + tier` interface is wrong (e.g. some handler wants raw model_id control) → revisit before Phase 2.
- If `handle_fetch_and_extract`'s migrated shape turns out awkward → fix *before* using it as the Phase 2 template.
- If a new orchestration pattern is requested (e.g. triangulation) before Phase 2 lands → consider doing Phase 2b first so the new pattern slots in cleanly.

---

# Appendix A: Dependency ordering diagram

```
                         ┌───────────────────────────┐
                         │   Phase 0 — test harness  │
                         │   (0.1 → 0.2 → 0.3 → 0.4) │
                         └───────────┬───────────────┘
                                     │
                 ┌───────────────────┴──────────────────┐
                 │                                      │
                 ▼                                      ▼
      ┌────────────────────┐                ┌──────────────────────┐
      │ Phase 1a — Runner  │                │ Phase 1b — Ingestion │
      │ 1.1 → 1.2 → 1.3    │                │ 2.1 → 2.2 → 2.3      │
      │                    │                │       ↓              │
      │        ↓           │                │      2.4 → 2.5       │
      │       1.4          │                │                      │
      └──────────┬─────────┘                └──────────┬───────────┘
                 │                                      │
                 └──────────────┬───────────────────────┘
                                │
                                ▼
                 ┌───────────────────────────────┐
                 │  2.6 — handler migration      │
                 │  2.7 — e2e integration test   │
                 └───────────────────────────────┘
```

Task 1.4 depends on 1.2/1.3. Task 2.6 depends on **both** 1.4 and 2.5. 2.7 is optional-ish — it's scaffolded as a skip because filling it in requires locking the schema construction.

# Appendix B: Engineering assessment

**Over-engineered?** No — each module has exactly one job: the runner hides model-selection + tracking; ingestion hides fetch + tier + structure composition. Two new files, ~150 lines each, each with tests. No speculative abstractions (e.g., we did not build a "PipelineStage" base class, even though ingestion is a pipeline — it's short enough procedural code is clearer).

**Under-engineered?** Slightly, on purpose. The LLM runner does not yet handle retries, circuit-breaking, or streaming — those belong in a later phase when real failure modes show up. The ingestion pipeline does not yet surface cache-hit/miss events — same reason.

**Perfectly-engineered?** The shape of both seams mirrors the domain vocabulary in `design/CONTEXT.md`. Any reader looking for "source extraction pipeline" now finds the module named for that concept. Any reader looking for "the LLM call seam" finds one module. That's the navigability win the architecture skill was aiming at.
