# Iterative Researcher + Landscape Agent Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an up-front `landscape` scouting agent and convert the top-level `researcher` from a single fan-out into an iterative orchestrator that reads only distilled sub-agent outputs (no raw sources). Merge `question_note` + `synthesis_note` so a question has a lifecycle (`OPEN` → `SYNTHESIZED`) with its answer written into its own metadata.

**Architecture:**
- **`landscape` (MID)** — does N rounds (≤4) of wide-filter search, creates `SCOUTED` source notes with topic tags, commits a free-form markdown brief as a `LANDSCAPE` note.
- **`researcher` (HIGH)** — receives the user query; creates a root `QUESTION` note; gets landscape brief + source list injected into prompt; loops: inspect research state → dispatch analyst on a new/open question → review returned synthesis → decide next move → eventually calls `answer_question(root_id, ...)` which produces the final report.
- **`analyst` (MID)** — renamed from `question_investigator`. Called with a pre-created `question_id`; searches, fetches, upgrades source notes, then **updates the question note in place** via `answer_question(question_id=...)` (no more separate synthesis notes).

**Tech Stack:** Python 3.12, pydantic-ai, pydantic, async/asyncio. Existing plumbing: `NoteMemory`, `Deps`, `EventPublisher`, `RoutingConfig`, `agent_factory.make_model`.

**Explicitly deferred:** `adversarial_check`, `competing_hypothesis`, `verify_claim`, analyst-side search sub-agent. These are future pattern tools the researcher will eventually call; the core iterative loop must land first.

**Note on tests:** User's global preference is to defer tests during prototyping (see user memory). This plan uses smoke tests via the CLI (`dra research "..."`) as the primary verification at each phase checkpoint. Ruff (`ruff check --fix` and `ruff format`) runs after every edit.

---

## Phase A — Extend `QuestionMetadata` to carry synthesis

Add synthesis fields to `QuestionMetadata` so a question note can hold its own answer. No behavior change yet — just widening the schema. All new fields are optional/defaulted so existing notes still validate.

### Task A1: Extend QuestionMetadata with synthesis fields + parent link

**Files:**
- Modify: `src/deep_research_agent/schemas/note.py` — `QuestionMetadata` class

**Step 1: Edit the class**

Replace the current `QuestionMetadata` with:

```python
class QuestionMetadata(BaseModel):
    type: Literal[NoteType.QUESTION] = NoteType.QUESTION
    classification: QuestionClassification
    adopted_position: str | None = None
    status: Literal["OPEN", "IN_PROGRESS", "SYNTHESIZED"] = "OPEN"

    # Tree structure: None for the root question (the user's original query),
    # otherwise the id of the question this one was spawned from.
    parent_question_id: NoteID | None = None

    # Populated when an analyst answers the question via answer_question.
    # Kept here (on the question note) rather than on a separate synthesis
    # note so a question's lifecycle and answer live in one place.
    bottom_line: str | None = None
    synthesis_markdown: str | None = None
    confidence: Literal["high", "medium", "low"] | None = None
    sources_cited: list[NoteID] = Field(default_factory=list)
    disagreements: list[str] = Field(default_factory=list)
    open_issues: list[str] = Field(default_factory=list)

    # Which analyst agent_id last updated this. Useful for the event UI
    # and for the researcher to tell "did I already dispatch on this?".
    answered_by_agent_id: str | None = None
```

Leave `NoteID` import alone (already imported in this file).

**Step 2: Ruff**

Run: `ruff check --fix src/deep_research_agent/schemas/note.py && ruff format src/deep_research_agent/schemas/note.py`

**Step 3: Import sanity check**

Run: `python3 -c "from deep_research_agent.schemas.note import QuestionMetadata; print(QuestionMetadata(classification='synthesis'))"`
Expected: prints a QuestionMetadata with status='OPEN', no errors.

**Step 4: Commit**

```bash
git add src/deep_research_agent/schemas/note.py
git commit -m "feat(schema): extend QuestionMetadata with synthesis fields + parent link"
```

---

## Phase B — Add topic tags + URL dedup on source notes

Two small changes to `SourceMetadata` + `create_source_note`:
- Optional `topics: list[str]` — landscape agent tags every source it scouts with 1-3 topic hints so the researcher sees the corpus shape in the injected source list.
- URL-keyed dedup — `create_source_note` returns the existing `NoteID` if a source with the same (normalized) URL is already in memory, instead of creating a duplicate. Prevents stomp across landscape rounds and between landscape + analysts.

### Task B1: Add `topics` field to SourceMetadata

**Files:**
- Modify: `src/deep_research_agent/schemas/source.py` — `SourceMetadata` class

**Step 1: Edit**

Add the field near the existing `summary` field:

```python
    topics: list[str] = Field(
        default_factory=list,
        description=(
            "Cheap topic labels assigned at scout time (e.g. "
            "['benchmarks', 'evaluation-methodology']). Landscape and "
            "analysts use this to cluster / filter; researcher sees it "
            "in the injected source list for corpus overview."
        ),
    )
```

**Step 2: Ruff + sanity check**

Run: `ruff check --fix src/deep_research_agent/schemas/source.py && ruff format src/deep_research_agent/schemas/source.py`
Run: `python3 -c "from deep_research_agent.schemas.source import SourceMetadata; m = SourceMetadata(url='x', title='y'); assert m.topics == []; print('ok')"`

**Step 3: Commit**

```bash
git add src/deep_research_agent/schemas/source.py
git commit -m "feat(schema): add topics[] to SourceMetadata"
```

### Task B2: URL dedup + topics in `create_source_note`

**Files:**
- Modify: `src/deep_research_agent/agents/tools/notes.py` — `create_source_note`
- Modify: `src/deep_research_agent/agents/memory.py` — add `find_source_by_url` helper

**Step 1: Add `find_source_by_url` to NoteMemory**

In `memory.py`, add the method (below `list_by_type`):

```python
    def find_source_by_url(self, url: str) -> Note | None:
        """Return the existing source note for this URL, or None.

        URLs are compared with trivial normalization - strip trailing
        slash and case-fold the scheme/host. Good enough to dedup
        identical links from different search providers; not a full
        canonicalizer.
        """
        from ..schemas.note import SourceNoteMetadata

        needle = _normalize_url(url)
        for n in self._notes.values():
            if not isinstance(n.metadata, SourceNoteMetadata):
                continue
            if _normalize_url(n.metadata.url) == needle:
                return n
        return None
```

And add the helper at module scope (near `new_note_id`):

```python
def _normalize_url(url: str) -> str:
    u = url.strip().rstrip("/")
    # Lowercase scheme + host only - keep path case-sensitive.
    if "://" in u:
        scheme, rest = u.split("://", 1)
        if "/" in rest:
            host, path = rest.split("/", 1)
            u = f"{scheme.lower()}://{host.lower()}/{path}"
        else:
            u = f"{scheme.lower()}://{rest.lower()}"
    return u
```

**Step 2: Modify `create_source_note` to dedup + accept topics**

Replace the body of `create_source_note` in `tools/notes.py` with:

```python
@instrumented
async def create_source_note(
    ctx: RunContext[Deps],
    url: str,
    title: str,
    snippet: str = "",
    topics: list[str] | None = None,
) -> NoteID:
    """Record a source you've found but not yet read fully.

    If a source with the same URL already exists in memory, returns
    the existing NoteID (dedup). Otherwise creates a new SCOUTED
    source note. Does not fetch - call `fetch_url` separately.

    Args:
      topics: optional topic hints (1-3 short labels). Useful at scout
        time to cluster sources in the corpus view; analysts can
        ignore or overwrite.
    """
    existing = ctx.deps.memory.find_source_by_url(url)
    if existing is not None:
        # Merge topics if the caller supplied new ones - helps when
        # landscape scouts the same URL on two different rounds with
        # different topic framings.
        if topics:
            existing_meta = existing.metadata
            assert isinstance(existing_meta, SourceNoteMetadata)
            merged = list(dict.fromkeys([*existing_meta.topics, *topics]))
            if merged != existing_meta.topics:
                new_meta = existing_meta.model_copy(update={"topics": merged})
                await ctx.deps.memory.update(existing.id, metadata=new_meta)
        return existing.id

    source_id = new_note_id("source")
    note = Note(
        id=source_id,
        type=NoteType.SOURCE,
        title=title or url,
        description=snippet[:280],
        content="",
        metadata=SourceNoteMetadata(
            url=url,
            title=title or "Untitled",
            state=SourceState.SCOUTED,
            summary=snippet or None,
            topics=list(topics or []),
        ),
        last_modified_at=_now(),
        created_at=_now(),
    )
    await ctx.deps.memory.create(note)
    return source_id
```

**Step 3: Ruff**

Run: `ruff check --fix src/deep_research_agent/agents/tools/notes.py src/deep_research_agent/agents/memory.py && ruff format src/deep_research_agent/agents/tools/notes.py src/deep_research_agent/agents/memory.py`

**Step 4: Sanity check**

Run: `python3 -c "from deep_research_agent.agents.memory import _normalize_url; assert _normalize_url('HTTPS://Example.com/A/') == 'https://example.com/A'; print('ok')"`

**Step 5: Commit**

```bash
git add src/deep_research_agent/agents/tools/notes.py src/deep_research_agent/agents/memory.py
git commit -m "feat: URL dedup + topics on create_source_note"
```

---

## Phase C — Landscape agent

Build the landscape agent as a standalone module with its own system prompt and commit tool. Doesn't wire into the researcher yet — Phase E does that. This phase lands the agent in isolation so we can iterate on prompt quality before touching the researcher's flow.

### Task C1: New commit tool `write_landscape_brief`

**Files:**
- Modify: `src/deep_research_agent/agents/tools/notes.py`

**Step 1: Add the tool at the bottom of `notes.py` (after `write_research_report`)**

```python
@instrumented
async def write_landscape_brief(
    ctx: RunContext[Deps],
    brief_markdown: str,
) -> str:
    """Commit your landscape brief for the researcher to read.

    MUST be called exactly once as your last tool call before ending
    your turn. The brief is free-form markdown - include whatever is
    useful for a downstream researcher deciding how to decompose the
    query:
      - apparent sub-areas or themes
      - obvious gaps / under-covered angles
      - terminology the field uses
      - source clusters (e.g. which venues, which kinds of outlets)
      - contested points you noticed in the snippets
    Do NOT paraphrase full source content - the researcher will read
    the source list separately. Keep the brief tight (~300-600 words).

    Creates a LANDSCAPE note in memory and stashes the brief for the
    wrapping landscape_run to return to its caller.
    """
    from ...schemas.note import LandscapeMetadata

    if not brief_markdown.strip():
        raise ValueError("brief_markdown must be non-empty")

    agent_id = current_agent_id() or "anonymous"
    # Stash raw markdown for landscape_run to forward to the researcher.
    ctx.deps.outputs[agent_id] = brief_markdown

    # Durable landscape note.
    note_id = new_note_id("landscape")
    note = Note(
        id=note_id,
        type=NoteType.LANDSCAPE,
        title="Landscape brief",
        description=brief_markdown.splitlines()[0][:280] if brief_markdown else "",
        content=brief_markdown,
        metadata=LandscapeMetadata(raw_query=""),  # query filled by landscape_run
        last_modified_at=_now(),
        created_at=_now(),
    )
    await ctx.deps.memory.create(note)
    return f"committed landscape brief as {note_id}"
```

Add `LandscapeMetadata` to the top-of-file import:

```python
from ...schemas.note import (
    LandscapeMetadata,
    Link,
    Note,
    QuestionMetadata,
    SourceNoteMetadata,
    SynthesisMetadata,
)
```

**Step 2: Ruff**

`ruff check --fix src/deep_research_agent/agents/tools/notes.py && ruff format src/deep_research_agent/agents/tools/notes.py`

**Step 3: Commit**

```bash
git add src/deep_research_agent/agents/tools/notes.py
git commit -m "feat(tools): add write_landscape_brief commit tool"
```

### Task C2: `landscape` agent module

**Files:**
- Create: `src/deep_research_agent/agents/landscape.py`

**Step 1: Write the module**

```python
"""Landscape agent - wide-filter scouting before the researcher decomposes.

Input: the user's query (string).
Output: `LandscapeBrief`, a free-form markdown brief, committed via the
`write_landscape_brief` tool. As a side effect, leaves a pile of
SCOUTED source notes in memory (topic-tagged) that analysts can pick
up without re-searching the same territory.

The agent is allowed up to ~4 rounds of searches within a single
agent.run - it's prompt-enforced, not harness-enforced. Stops early
on diminishing returns.
"""

from __future__ import annotations

import logging
import uuid

from pydantic_ai import Agent

from ..agent_factory import make_model
from ..schemas.enums import RoleClass, TaskTier
from .deps import Deps
from .events import reset_current_agent_id, set_current_agent_id
from .tools.notes import create_source_note, list_source_notes, write_landscape_brief
from .tools.search import search_academic, search_web

logger = logging.getLogger(__name__)


LANDSCAPE_SYSTEM = """\
You are a scouting agent mapping the landscape around a research query.

## Your job
Cast a wide net. Run multiple rounds of searches and create SCOUTED
source notes for anything even plausibly relevant. You do NOT read
sources or extract claims - that's the analysts' job downstream. Your
only deliverable is a short markdown brief that tells a downstream
researcher what the terrain looks like.

## How to work
1. **Round 1 — broad sweep.** Run 3-5 parallel `search_web` /
   `search_academic` calls with varied query formulations around the
   user's topic. For each promising hit (relevance: plausible, not
   certain), call `create_source_note(url, title, snippet, topics=[...])`
   with 1-3 short topic labels. Topics are cheap signals like
   ['benchmarks'], ['survey', 'methodology'], ['position-paper'],
   ['tooling']. Source dedup by URL happens automatically.
2. **Review coverage.** Call `list_source_notes()` to see what you've
   gathered. Look for topic gaps ("I have lots on benchmarks but
   nothing on methodology critiques") and source-type imbalance.
3. **Further rounds (up to 3 more).** Run more searches targeting the
   gaps you noticed. Reformulate queries to find what round 1 missed.
   Each round should add genuinely new sources - if a round adds
   fewer than 2 new (non-duplicate) sources, stop immediately.
4. **Hard stop.** Never run more than 4 rounds total. If after 4 you
   still feel thin, the brief should say so.
5. **Commit the brief.** Call `write_landscape_brief(brief_markdown)`.
   Keep it tight (~300-600 words). Useful things to include when
   relevant (you decide):
     - apparent sub-areas or themes the corpus splits into
     - obvious gaps / under-covered angles
     - terminology the field uses (so the researcher can decompose well)
     - source clusters (which venues, which outlets)
     - contested points you noticed in the snippets
   Do NOT paraphrase full source content - the researcher sees the
   source list separately. Cite sources inline as [source-abc123].
6. **End.** After `write_landscape_brief` returns, produce a one-line
   acknowledgment and stop.

## Discipline
- Wide filter: pull anything even kind of relevant. The analysts
  downstream will filter on quality; you filter on "is this in the
  neighborhood of the topic at all".
- Don't read content. Don't call fetch_url. Snippets are enough.
- Don't over-commit to what you think the decomposition should be.
  You're describing terrain, not planning the investigation.
"""


def build_landscape_agent(deps: Deps) -> Agent[Deps, str]:
    model_id = deps.routing.model_id_for(RoleClass.GENERATIVE, TaskTier.MID)
    agent = Agent(
        make_model(model_id, deps.local),
        deps_type=Deps,
        output_type=str,
        system_prompt=LANDSCAPE_SYSTEM,
    )
    agent.tool(search_web)
    agent.tool(search_academic)
    agent.tool(create_source_note)
    agent.tool(list_source_notes)
    agent.tool(write_landscape_brief)
    return agent


async def landscape_run(deps: Deps, query: str) -> str:
    """Run the landscape agent for the query.

    Returns the brief markdown the agent committed. On the (rare) path
    where the agent ends without committing, returns a placeholder so
    the researcher can still proceed (with a noted limitation).
    """
    agent = build_landscape_agent(deps)
    agent_id = f"land-{uuid.uuid4().hex[:8]}"
    model_id = deps.routing.model_id_for(RoleClass.GENERATIVE, TaskTier.MID)
    deps.events.on_agent_start(
        agent_id=agent_id,
        agent_type="LANDSCAPE",
        goal=query,
        tier=TaskTier.MID.value,
        role=RoleClass.GENERATIVE.value,
        model_id=model_id,
    )
    logger.info("landscape start agent_id=%s query=%r", agent_id, query[:200])
    token = set_current_agent_id(agent_id)
    try:
        try:
            await agent.run(f"Scout the landscape for this query: {query}", deps=deps)
        except Exception as exc:
            deps.events.on_agent_done(
                agent_id=agent_id,
                agent_type="LANDSCAPE",
                status="ABANDONED",
                verdict=f"failed: {type(exc).__name__}: {exc}"[:200],
            )
            raise

        committed = deps.outputs.get(agent_id)
        if isinstance(committed, str) and committed.strip():
            brief = committed
        else:
            logger.warning(
                "landscape agent_id=%s ended without calling write_landscape_brief",
                agent_id,
            )
            brief = (
                "_(landscape agent ended without producing a brief; "
                "researcher should proceed with the source list alone)_"
            )

        n_sources = sum(
            1
            for n in deps.memory.all()
            if n.type.value == "source_note"  # avoid extra import
        )
        verdict = f"brief committed, {n_sources} sources scouted"
        deps.events.on_agent_done(
            agent_id=agent_id,
            agent_type="LANDSCAPE",
            status="DONE",
            verdict=verdict,
        )
        logger.info("landscape done agent_id=%s sources=%d", agent_id, n_sources)
        return brief
    finally:
        reset_current_agent_id(token)
        deps.outputs.pop(agent_id, None)
```

**Step 2: Register in `agents/__init__.py`**

Open the existing `__init__.py` and add the landscape exports. Read it first, then append:

```python
from .landscape import landscape_run, build_landscape_agent
```

(Only add these to `__all__` if the file defines one; otherwise just the import is fine.)

**Step 3: Ruff**

`ruff check --fix src/deep_research_agent/agents/landscape.py src/deep_research_agent/agents/__init__.py && ruff format src/deep_research_agent/agents/landscape.py src/deep_research_agent/agents/__init__.py`

**Step 4: Smoke-import**

Run: `python3 -c "from deep_research_agent.agents.landscape import landscape_run, build_landscape_agent; print('ok')"`

**Step 5: Commit**

```bash
git add src/deep_research_agent/agents/landscape.py src/deep_research_agent/agents/__init__.py
git commit -m "feat(agents): add landscape agent (isolated; not wired yet)"
```

---

## Phase D — Migrate analyst to new commit protocol

Rename `question_investigator` → `analyst`. Replace `write_question_synthesis` (which creates a new SYNTHESIS note) with `answer_question(question_id, ...)` (which updates the existing QUESTION note's metadata in place). Analyst now expects the question note to already exist and to be passed its `question_id`.

This phase also updates the `investigate_question` tool the researcher uses so it creates the question note before dispatching the analyst. Researcher's iterative loop changes in Phase E — this phase just swaps the protocol while preserving the single-dispatch behavior.

### Task D1: Add `answer_question` tool (does NOT remove write_question_synthesis yet)

**Files:**
- Modify: `src/deep_research_agent/agents/tools/notes.py`

**Step 1: Add the tool after `write_question_synthesis`**

```python
@instrumented
async def answer_question(
    ctx: RunContext[Deps],
    question_id: NoteID,
    bottom_line: str,
    synthesis: str,
    confidence: str,
    sources_cited: list[NoteID] | None = None,
    disagreements: list[str] | None = None,
    open_issues: list[str] | None = None,
) -> str:
    """Commit your answer to a pre-created question note.

    Updates the QUESTION note's metadata in place (status ->
    SYNTHESIZED) rather than creating a new synthesis note. Called by
    the analyst at the end of its turn, and by the researcher to
    commit the final report (answer to the root question).

    Raises if `question_id` is not a QUESTION note in memory.
    """
    confidence_lc = confidence.strip().lower()
    if confidence_lc not in {"high", "medium", "low"}:
        raise ValueError(f"confidence must be 'high', 'medium', or 'low'; got {confidence!r}")

    existing = ctx.deps.memory.get(question_id)
    if existing is None:
        raise KeyError(f"question note {question_id} not in memory")
    if existing.type != NoteType.QUESTION:
        raise ValueError(f"note {question_id} is {existing.type.value}, not a question_note")

    existing_meta = existing.metadata
    assert isinstance(existing_meta, QuestionMetadata)
    agent_id = current_agent_id() or "anonymous"
    new_meta = existing_meta.model_copy(
        update={
            "status": "SYNTHESIZED",
            "bottom_line": bottom_line,
            "synthesis_markdown": synthesis,
            "confidence": confidence_lc,
            "sources_cited": list(sources_cited or []),
            "disagreements": list(disagreements or []),
            "open_issues": list(open_issues or []),
            "answered_by_agent_id": agent_id,
        }
    )
    await ctx.deps.memory.update(
        question_id,
        description=bottom_line[:280] or existing.description,
        content=synthesis,
        links=[Link(target_id=src, edge_type="cites") for src in (sources_cited or [])],
        metadata=new_meta,
    )

    # Stash so the wrapping *_run function can read the structured
    # payload without reconstructing from the note.
    from ..schemas import QuestionSynthesis

    qs = QuestionSynthesis(
        question=existing.description or existing.title,
        bottom_line=bottom_line,
        synthesis=synthesis,
        confidence=confidence_lc,
        sources_cited=list(sources_cited or []),
        disagreements=list(disagreements or []),
        open_issues=list(open_issues or []),
    )
    ctx.deps.outputs[agent_id] = qs
    return (
        f"answered question {question_id} "
        f"({confidence_lc} confidence, {len(qs.sources_cited)} sources cited)"
    )
```

**Step 2: Ruff**

`ruff check --fix src/deep_research_agent/agents/tools/notes.py && ruff format src/deep_research_agent/agents/tools/notes.py`

**Step 3: Sanity import**

Run: `python3 -c "from deep_research_agent.agents.tools.notes import answer_question; print('ok')"`

**Step 4: Commit**

```bash
git add src/deep_research_agent/agents/tools/notes.py
git commit -m "feat(tools): add answer_question (updates QUESTION note in place)"
```

### Task D2: Rename `question_investigator` → `analyst`; switch to `answer_question`

**Files:**
- Rename: `src/deep_research_agent/agents/question_investigator.py` → `src/deep_research_agent/agents/analyst.py`
- Modify: `src/deep_research_agent/agents/researcher.py` — import path + `investigate_question` tool body
- Modify: `src/deep_research_agent/agents/__init__.py` — update re-exports
- Modify: `src/deep_research_agent/agents/events.py` — if agent_type literals are referenced

**Step 1: Move the file**

```bash
git mv src/deep_research_agent/agents/question_investigator.py src/deep_research_agent/agents/analyst.py
```

**Step 2: Rewrite `analyst.py`**

Overwrite the file with the following (replaces `write_question_synthesis` usage with `answer_question`, takes `question_id` as input, renames public symbols):

```python
"""Analyst sub-agent - investigate one specific question end-to-end.

Input: a (question_id, question_text) pair. The QUESTION note must
already exist in memory - the caller (researcher) is responsible for
creating it via create_question_note before dispatching the analyst.

Output: the analyst commits its answer by UPDATING the question note
in place via the `answer_question` tool. The wrapping
`analyst_run` reads the resulting QuestionSynthesis back from
deps.outputs and returns it.

Why the caller owns the question_id: it lets the researcher track
its question tree (open/answered, parent links, dispatch state)
without needing the analyst to echo metadata back. It also means a
crash mid-investigation still leaves a durable OPEN question note
that the researcher can see and re-dispatch on.
"""

from __future__ import annotations

import logging
import uuid

from pydantic_ai import Agent

from ..agent_factory import make_model
from ..schemas.enums import RoleClass, TaskTier
from ..schemas.ids import NoteID
from .deps import Deps
from .events import reset_current_agent_id, set_current_agent_id
from .schemas import QuestionSynthesis
from .tools.fetch import fetch_url
from .tools.notes import (
    answer_question,
    create_source_note,
    list_source_notes,
    load_note,
    update_source_after_reading,
)
from .tools.search import search_academic, search_web

logger = logging.getLogger(__name__)


ANALYST_SYSTEM = """\
You are a research analyst investigating one specific question.

## Your job
Produce a rigorous, evidence-grounded answer to the question you're
given. You have tools to search the web, fetch URLs, and record
findings as source notes in shared memory. Commit your final answer
by UPDATING the question note you were assigned - do not create a
new note for the answer.

## Shared corpus
Before running fresh searches, call `list_source_notes()`. A
landscape scouting agent may have already scouted many sources for
this topic. Prefer picking up those SCOUTED sources over duplicating
the search work. You can still run your own searches if the existing
corpus doesn't cover your angle.

## How to work
1. **Inventory.** Call `list_source_notes()`. If there are already
   promising SCOUTED sources relevant to your question, start with
   fetching those.
2. **Targeted search if needed.** If the existing corpus is thin on
   your specific angle, run `search_web` / `search_academic` in
   parallel. Use `create_source_note(url, title, snippet)` on
   promising hits - this dedups by URL automatically, so calling it
   on a URL landscape already scouted just returns the existing id.
3. **Fetch and read.** Call `fetch_url(url)` on the sources you want
   to read. Fetch in parallel - one turn can issue many fetches.
   Some URLs will fail (404, paywall, PDF errors); move on.
4. **Record findings.** After reading a source, call
   `update_source_after_reading(source_id, tier=..., claims=[...], ...)`
   with 3-6 claims per useful source. Every claim needs a verbatim quote.
     - tier 1 = peer-reviewed research, strong venues
     - tier 2 = arXiv / well-cited tech reports
     - tier 3 = reputable industry posts, official docs
     - tier 4 = community writeups, unreviewed blogs
     - tier 5 = low-quality, promotional, off-topic
5. **Commit your answer.** Call
   `answer_question(question_id=<the id you were given>, ...)`.
   This tool is your commit step - DO NOT finish your turn without
   calling it. If it returns a validation error, fix the field and
   call again.
6. **End.** After `answer_question` returns, produce a one-line
   acknowledgment ("Answered question ...") and stop.

## Discipline
- Prefer multiple, diverse sources over one authoritative-looking one.
- Quote claims verbatim. If you can't find a supporting quote, drop
  the claim - don't invent one.
- If a source is paywalled or fails to fetch, note it and move on.
- Don't over-investigate. 4-8 analyzed sources beats 20 half-read ones.
"""


def build_analyst(deps: Deps) -> Agent[Deps, str]:
    model_id = deps.routing.model_id_for(RoleClass.GENERATIVE, TaskTier.MID)
    agent = Agent(
        make_model(model_id, deps.local),
        deps_type=Deps,
        output_type=str,
        system_prompt=ANALYST_SYSTEM,
    )
    agent.tool(search_web)
    agent.tool(search_academic)
    agent.tool(fetch_url)
    agent.tool(create_source_note)
    agent.tool(update_source_after_reading)
    agent.tool(load_note)
    agent.tool(list_source_notes)
    agent.tool(answer_question)
    return agent


async def analyst_run(
    deps: Deps,
    question_id: NoteID,
    question: str,
) -> QuestionSynthesis:
    """Run the analyst against a pre-created QUESTION note.

    Returns the QuestionSynthesis. On the rare path where the agent
    ends without calling answer_question, returns a low-confidence
    fallback so the researcher sees a gap rather than a missing result.
    """
    agent = build_analyst(deps)
    agent_id = f"an-{uuid.uuid4().hex[:8]}"
    model_id = deps.routing.model_id_for(RoleClass.GENERATIVE, TaskTier.MID)
    deps.events.on_agent_start(
        agent_id=agent_id,
        agent_type="ANALYST",
        goal=question,
        tier=TaskTier.MID.value,
        role=RoleClass.GENERATIVE.value,
        model_id=model_id,
    )
    logger.info(
        "analyst start agent_id=%s qid=%s q=%r", agent_id, question_id, question[:140]
    )
    token = set_current_agent_id(agent_id)
    try:
        try:
            await agent.run(
                (
                    f"Your assigned question_id is {question_id}.\n"
                    f"Question: {question}\n"
                    "When you commit your answer, pass question_id="
                    f"{question_id} to answer_question."
                ),
                deps=deps,
            )
        except Exception as exc:
            deps.events.on_agent_done(
                agent_id=agent_id,
                agent_type="ANALYST",
                status="ABANDONED",
                verdict=f"failed: {type(exc).__name__}: {exc}"[:200],
            )
            raise

        committed = deps.outputs.get(agent_id)
        if isinstance(committed, QuestionSynthesis):
            qs = committed
        else:
            logger.warning(
                "analyst agent_id=%s qid=%s ended without committing",
                agent_id,
                question_id,
            )
            qs = QuestionSynthesis(
                question=question,
                bottom_line=(
                    "(no synthesis produced - analyst ended without calling answer_question)"
                ),
                synthesis="",
                confidence="low",
                open_issues=[
                    "Analyst did not call answer_question before ending its turn.",
                ],
            )

        verdict = f"{qs.confidence} confidence, {len(qs.sources_cited)} sources cited"
        deps.events.on_agent_done(
            agent_id=agent_id,
            agent_type="ANALYST",
            status="DONE",
            verdict=verdict,
        )
        logger.info(
            "analyst done agent_id=%s qid=%s confidence=%s sources_cited=%d",
            agent_id,
            question_id,
            qs.confidence,
            len(qs.sources_cited),
        )
        return qs
    finally:
        reset_current_agent_id(token)
        deps.outputs.pop(agent_id, None)
```

**Step 3: Update imports that used the old module**

Run: `grep -rn "question_investigator\|investigate_question_run\|build_investigator_for_run" src/deep_research_agent`

For each hit, update to `analyst` / `analyst_run` / `build_analyst`. Expected hits: `researcher.py`, `__init__.py` (if any), possibly `server/runner.py`.

**Step 4: Update researcher's `investigate_question` tool to create the question note inline**

In `src/deep_research_agent/agents/researcher.py`, modify the `investigate_question` inner tool:

```python
    @agent.tool
    async def investigate_question(
        ctx: RunContext[Deps],
        question: str,
    ) -> QuestionSynthesis:
        """Delegate a specific sub-question to an analyst sub-agent.

        Creates a QUESTION note for the sub-question (status=OPEN,
        parent_question_id=root_id), then dispatches the analyst. The
        analyst updates the note's metadata in place on commit. Returns
        the resulting QuestionSynthesis so you can compose the final
        report. Safe to call multiple times per turn to dispatch
        sub-questions in parallel.
        """
        from ..schemas.enums import NoteType, QuestionClassification
        from ..schemas.ids import NoteID
        from ..schemas.ids import NoteID
        from ..schemas.note import Note, QuestionMetadata
        from datetime import UTC, datetime
        from .memory import new_note_id

        q_id = new_note_id("question")
        root_id = ctx.deps.outputs.get("__root_question_id__")
        parent_id = NoteID(root_id) if isinstance(root_id, str) else None
        note = Note(
            id=q_id,
            type=NoteType.QUESTION,
            title=question[:120],
            description=question,
            content="",
            metadata=QuestionMetadata(
                classification=QuestionClassification.SYNTHESIS,
                status="IN_PROGRESS",
                parent_question_id=parent_id,
            ),
            last_modified_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        await ctx.deps.memory.create(note)
        return await analyst_run(ctx.deps, q_id, question)
```

Note: `NoteID` is a `NewType` over `str`, so it isn't a class and `isinstance(x, NoteID)` raises at runtime. Guard with `isinstance(root_id, str)` and then cast via `NoteID(root_id)` so `parent_question_id` (typed `NoteID | None`) accepts the value.

And at the top of `researcher.py`, update the import:

```python
from .analyst import analyst_run
```

(Remove the old `from .question_investigator import investigate_question_run` line.)

**Step 5: Ruff + import smoke**

`ruff check --fix src/deep_research_agent/agents && ruff format src/deep_research_agent/agents`
`python3 -c "from deep_research_agent.agents.analyst import analyst_run; from deep_research_agent.agents.researcher import research_run; print('ok')"`

**Step 6: Quick end-to-end smoke**

Run: `dra research "what is prompt caching in LLMs" --routing config/routing_diverse.yaml 2>&1 | tail -30`
Expected: run completes; `runs/<id>/report.md` is produced. It's OK if the report is thin — this is pre-landscape. Verify no crashes, no `AttributeError`, no `KeyError`.

**Step 7: Commit**

```bash
git add -A src/deep_research_agent/agents
git commit -m "refactor(agents): rename investigator→analyst; switch to answer_question protocol"
```

---

## Phase E — Rework researcher into iterative orchestrator

This is the centerpiece change. The researcher:
1. Creates a root QUESTION note from the user's query on start.
2. Runs the landscape agent (blocking) before its first decomposition.
3. Gets the landscape brief + a short-form source list injected into its opening prompt.
4. Loses its own `search_web` / `search_academic` / `create_question_note` tools — they were for self-scouting, which is now the landscape agent's job.
5. Gains `get_research_state()` — a compact snapshot of the note graph.
6. Loops: inspect state → dispatch analysts → inspect state → decide again.
7. Commits the final report by calling `answer_question(root_id, ...)` — same tool analysts use. Replaces `write_research_report`.

### Task E1: `get_research_state` tool

**Files:**
- Modify: `src/deep_research_agent/agents/tools/notes.py`

**Step 1: Add the tool (after `list_source_notes`)**

```python
@instrumented
async def get_research_state(ctx: RunContext[Deps]) -> dict[str, object]:
    """Compact snapshot of the note graph for the orchestrator.

    Returns:
      {
        "root_question": {...} | None,
        "questions": [{id, question, status, confidence, bottom_line,
                       parent_id, n_sources_cited}, ...],
        "sources_by_tier": {"unclassified": N, "1": N, "2": N, ...},
        "sources_by_state": {"SCOUTED": N, "FETCHED": N, "ANALYZED": N},
        "budget": {"analyst_dispatches_remaining": int | None},
      }

    This is the ONLY way the researcher should inspect the note graph
    between rounds - it keeps the researcher's context free of raw
    source content.
    """
    from ...schemas.note import QuestionMetadata, SourceNoteMetadata

    root_id = ctx.deps.outputs.get("__root_question_id__")
    questions = []
    root_summary: dict[str, object] | None = None
    for n in ctx.deps.memory.list_by_type(NoteType.QUESTION):
        meta = n.metadata
        if not isinstance(meta, QuestionMetadata):
            continue
        entry = {
            "id": n.id,
            "question": n.description or n.title,
            "status": meta.status,
            "confidence": meta.confidence,
            "bottom_line": meta.bottom_line,
            "parent_id": meta.parent_question_id,
            "n_sources_cited": len(meta.sources_cited),
        }
        if n.id == root_id:
            root_summary = entry
        else:
            questions.append(entry)

    sources_by_tier: dict[str, int] = {}
    sources_by_state: dict[str, int] = {}
    for n in ctx.deps.memory.list_by_type(NoteType.SOURCE):
        meta = n.metadata
        if not isinstance(meta, SourceNoteMetadata):
            continue
        tier_key = str(meta.tier.value) if meta.tier is not None else "unclassified"
        sources_by_tier[tier_key] = sources_by_tier.get(tier_key, 0) + 1
        sources_by_state[meta.state.value] = sources_by_state.get(meta.state.value, 0) + 1

    budget_remaining = ctx.deps.outputs.get("__analyst_budget__")

    return {
        "root_question": root_summary,
        "questions": questions,
        "sources_by_tier": sources_by_tier,
        "sources_by_state": sources_by_state,
        "budget": {
            "analyst_dispatches_remaining": (
                budget_remaining if isinstance(budget_remaining, int) else None
            ),
        },
    }
```

**Step 2: Ruff + import smoke**

`ruff check --fix src/deep_research_agent/agents/tools/notes.py && ruff format src/deep_research_agent/agents/tools/notes.py`
`python3 -c "from deep_research_agent.agents.tools.notes import get_research_state; print('ok')"`

**Step 3: Commit**

```bash
git add src/deep_research_agent/agents/tools/notes.py
git commit -m "feat(tools): add get_research_state for researcher between-round inspection"
```

### Task E2: Rewrite `researcher.py` with landscape + iterative loop

**Files:**
- Modify: `src/deep_research_agent/agents/researcher.py` (full rewrite of the module)

**Step 1: Replace the file contents**

```python
"""Top-level researcher - iterative orchestrator over landscape + analysts.

Flow:
  1. Create root QUESTION note from the user's query.
  2. Run landscape agent (blocking). Landscape leaves SCOUTED sources
     and commits a markdown brief.
  3. Build an opening prompt that includes the query + landscape brief
     + a compact source list (id, url, title, topics, snippet).
  4. Researcher loops:
       get_research_state() -> decide next move
       - investigate_question(question): dispatch analyst in parallel
       - answer_question(root_id, ...): commit final report & stop
     The researcher NEVER reads raw source content. Analysts do.

Budget: a per-run cap on analyst dispatches. `deps.outputs["__analyst_budget__"]`
starts at the cap and decrements on each dispatch; when 0 the
investigate_question tool refuses.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from pydantic_ai import Agent, RunContext

from ..agent_factory import make_model
from ..schemas.enums import NoteType, QuestionClassification, RoleClass, TaskTier
from ..schemas.ids import NoteID
from ..schemas.note import Note, QuestionMetadata, SourceNoteMetadata
from .analyst import analyst_run
from .deps import Deps
from .events import reset_current_agent_id, set_current_agent_id
from .landscape import landscape_run
from .memory import new_note_id
from .schemas import QuestionSynthesis, ResearcherReport
from .tools.notes import answer_question, get_research_state, load_note

logger = logging.getLogger(__name__)

# Hard cap on analyst dispatches per research run. Prompt says less;
# this is the backstop so a misbehaving researcher can't runaway-spawn.
DEFAULT_ANALYST_BUDGET = 8


RESEARCHER_SYSTEM = """\
You are the director of a research investigation.

## Your job
Given a user's research query, produce a thorough, evidence-grounded
final report. You dispatch analyst sub-agents (one per sub-question)
who do the actual reading. You only ever see their distilled
syntheses - never raw source content. You decide, iteratively, what
to investigate next based on what you've learned so far.

## Context you already have
Before your first turn, you've already received:
  - The user's query (as the root question).
  - A landscape brief from a scouting agent.
  - A list of SCOUTED sources the scouting agent pulled in.
All of that is in your opening message. You do NOT need to run
searches - that's the landscape agent's job, and the analysts will
do targeted search for their own questions as needed.

## Tools
- `investigate_question(question)`: create a sub-question note and
  dispatch an analyst on it. Returns a QuestionSynthesis (the
  analyst's answer). Can be called multiple times per turn in
  parallel. Counts against your dispatch budget.
- `get_research_state()`: compact snapshot of all questions (with
  their status/confidence/bottom_line) + source corpus shape + your
  remaining dispatch budget. Call between rounds to decide next moves.
- `load_note(note_id)`: load a specific note - usually a QUESTION
  note to re-read its synthesis. Do NOT load SOURCE notes; they're
  too noisy for you.
- `answer_question(question_id=<root_id>, ...)`: commit the final
  report. This is your terminal tool - call it last.

## How to work
1. **Round 1 — initial decomposition.** Based on the query and the
   landscape brief, dispatch 2-5 `investigate_question` calls in
   parallel. Each should be a focused, independently-answerable
   sub-question.
2. **Review round.** After analysts return, call
   `get_research_state()` to see the shape. Read the bottom_lines.
3. **Decide next move.** Options (choose based on what's weak):
     - Dispatch more `investigate_question` calls to fill gaps,
       follow up on low-confidence answers, or probe open_issues.
     - If coverage is good and confidence is reasonable, move to
       committing the final report.
   You may do multiple review/dispatch rounds. Stop when further
   work wouldn't meaningfully change the report - or when your
   dispatch budget runs out.
4. **Commit.** Call
   `answer_question(question_id=<root_id from get_research_state>,
                    bottom_line=..., synthesis=..., confidence=...,
                    sources_cited=[...], disagreements=[...],
                    open_issues=[...])`.
   - bottom_line: 2-4 sentence executive answer.
   - synthesis: the full markdown report. Cite source notes inline
     as [source-abc123]. Cite sub-question syntheses by pulling in
     their bottom lines or quoting them.
   - confidence: high/medium/low across the investigation as a whole.
   - sources_cited: NoteIDs of source notes the report leans on.
   - disagreements/open_issues: honest about friction.
5. **End.** After `answer_question` returns, produce a one-line ack
   ("Report committed") and stop.

## Judgment calls
- If the query is simple, one good sub-question is fine - don't force 4.
- A low-confidence analyst result isn't a failure: deciding whether
  to chase it vs. report the uncertainty IS your job.
- Never call investigate_question just because budget is left over.
  Stop when the report won't improve.

## Quality bar
- Every factual claim in the report should trace to a source note.
- Cite liberally. [source-...] references are the report's spine.
- If sources disagree, say so. Don't paper over it.
"""


def _render_source_list(deps: Deps, max_rows: int = 80) -> str:
    """Short-form source list for the researcher's opening prompt.

    Each row: `- [source-id] title — url — topics — snippet`.
    The researcher never sees full source content; this is the
    maximal source detail it ever gets.
    """
    lines: list[str] = []
    rows = 0
    for n in deps.memory.list_by_type(NoteType.SOURCE):
        if rows >= max_rows:
            lines.append(f"- _({len(deps.memory.list_by_type(NoteType.SOURCE)) - rows} more omitted)_")
            break
        meta = n.metadata
        if not isinstance(meta, SourceNoteMetadata):
            continue
        topics = f" — topics: {', '.join(meta.topics)}" if meta.topics else ""
        snippet = (meta.summary or "").replace("\n", " ")[:160]
        lines.append(f"- [{n.id}] {meta.title[:100]} — {meta.url}{topics} — {snippet}")
        rows += 1
    return "\n".join(lines) if lines else "_(no sources scouted)_"


def build_researcher(deps: Deps) -> Agent[Deps, str]:
    model_id = deps.routing.model_id_for(RoleClass.GENERATIVE, TaskTier.HIGH)
    agent = Agent(
        make_model(model_id, deps.local),
        deps_type=Deps,
        output_type=str,
        system_prompt=RESEARCHER_SYSTEM,
    )
    agent.tool(get_research_state)
    agent.tool(load_note)
    agent.tool(answer_question)

    @agent.tool
    async def investigate_question(
        ctx: RunContext[Deps],
        question: str,
    ) -> QuestionSynthesis:
        """Create a sub-question note and dispatch an analyst.

        Parent-links the new question to the root. Decrements the
        analyst dispatch budget; refuses if budget is exhausted.
        """
        budget = ctx.deps.outputs.get("__analyst_budget__")
        if isinstance(budget, int) and budget <= 0:
            raise RuntimeError(
                "analyst dispatch budget exhausted - stop dispatching and commit "
                "the final report with answer_question(question_id=root_id, ...)."
            )
        if isinstance(budget, int):
            ctx.deps.outputs["__analyst_budget__"] = budget - 1

        root_id = ctx.deps.outputs.get("__root_question_id__")
        parent_id = NoteID(root_id) if isinstance(root_id, str) else None
        q_id = new_note_id("question")
        note = Note(
            id=q_id,
            type=NoteType.QUESTION,
            title=question[:120],
            description=question,
            content="",
            metadata=QuestionMetadata(
                classification=QuestionClassification.SYNTHESIS,
                status="IN_PROGRESS",
                parent_question_id=parent_id,
            ),
            last_modified_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        await ctx.deps.memory.create(note)
        return await analyst_run(ctx.deps, q_id, question)

    return agent


async def research_run(deps: Deps, query: str) -> ResearcherReport:
    """Execute a full research run.

    Returns a ResearcherReport built from the root QUESTION note's
    committed synthesis. If the researcher ends without committing,
    returns a minimal report from what's in memory so the run still
    produces something.
    """
    # --- 1. Create the root question note.
    root_id = new_note_id("question")
    root = Note(
        id=root_id,
        type=NoteType.QUESTION,
        title=query[:120],
        description=query,
        content="",
        metadata=QuestionMetadata(
            classification=QuestionClassification.SYNTHESIS,
            status="IN_PROGRESS",
            parent_question_id=None,
        ),
        last_modified_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    await deps.memory.create(root)
    deps.outputs["__root_question_id__"] = root_id
    deps.outputs["__analyst_budget__"] = DEFAULT_ANALYST_BUDGET

    # --- 2. Run the landscape agent (blocking).
    brief_markdown = await landscape_run(deps, query)

    # --- 3. Build the researcher's opening prompt (query + brief + source list).
    agent = build_researcher(deps)
    agent_id = f"res-{uuid.uuid4().hex[:8]}"
    model_id = deps.routing.model_id_for(RoleClass.GENERATIVE, TaskTier.HIGH)
    deps.events.on_agent_start(
        agent_id=agent_id,
        agent_type="RESEARCHER",
        goal=query,
        tier=TaskTier.HIGH.value,
        role=RoleClass.GENERATIVE.value,
        model_id=model_id,
    )
    logger.info("researcher start agent_id=%s query=%r", agent_id, query[:200])

    source_list = _render_source_list(deps)
    opening = (
        f"User query (root_question_id={root_id}):\n{query}\n\n"
        f"## Landscape brief\n{brief_markdown}\n\n"
        f"## Scouted sources (id — title — url — topics — snippet)\n{source_list}\n\n"
        f"Your analyst dispatch budget: {DEFAULT_ANALYST_BUDGET}.\n"
        f"Begin. When you commit the final report, pass question_id={root_id} "
        "to answer_question."
    )

    token = set_current_agent_id(agent_id)
    try:
        try:
            await agent.run(opening, deps=deps)
        except Exception as exc:
            deps.events.on_agent_done(
                agent_id=agent_id,
                agent_type="RESEARCHER",
                status="ABANDONED",
                verdict=f"failed: {type(exc).__name__}: {exc}"[:200],
            )
            raise

        report = _build_report_from_root(deps, root_id, query)
        verdict = f"{len(deps.memory)} notes"
        deps.events.on_agent_done(
            agent_id=agent_id,
            agent_type="RESEARCHER",
            status="DONE",
            verdict=verdict,
        )
        logger.info("researcher done agent_id=%s", agent_id)
        return report
    finally:
        reset_current_agent_id(token)
        deps.outputs.pop("__root_question_id__", None)
        deps.outputs.pop("__analyst_budget__", None)


def _build_report_from_root(deps: Deps, root_id: NoteID, query: str) -> ResearcherReport:
    """Assemble the final ResearcherReport from the root QUESTION note.

    If the root note was answered, use its synthesis. Otherwise build a
    minimal fallback from whatever sub-question answers exist.
    """
    root = deps.memory.get(root_id)
    sub_syntheses: list[QuestionSynthesis] = []
    for n in deps.memory.list_by_type(NoteType.QUESTION):
        if n.id == root_id:
            continue
        meta = n.metadata
        if not isinstance(meta, QuestionMetadata) or meta.status != "SYNTHESIZED":
            continue
        sub_syntheses.append(
            QuestionSynthesis(
                question=n.description or n.title,
                bottom_line=meta.bottom_line or "",
                synthesis=meta.synthesis_markdown or "",
                confidence=meta.confidence or "low",
                sources_cited=list(meta.sources_cited),
                disagreements=list(meta.disagreements),
                open_issues=list(meta.open_issues),
            )
        )

    if root is not None and isinstance(root.metadata, QuestionMetadata) and root.metadata.status == "SYNTHESIZED":
        meta = root.metadata
        return ResearcherReport(
            query=query,
            bottom_line=meta.bottom_line or "",
            cross_cutting_synthesis="",
            report_markdown=meta.synthesis_markdown or "",
            questions_investigated=sub_syntheses,
            limitations=list(meta.open_issues),
        )

    logger.warning("researcher ended without answering root question %s", root_id)
    return ResearcherReport(
        query=query,
        bottom_line=(
            "(no top-level report committed - researcher ended without calling "
            "answer_question on the root question)"
        ),
        report_markdown="",
        questions_investigated=sub_syntheses,
        limitations=["Top-level researcher did not commit a final report."],
    )
```

**Step 2: Ruff**

`ruff check --fix src/deep_research_agent/agents/researcher.py && ruff format src/deep_research_agent/agents/researcher.py`

**Step 3: Import smoke**

`python3 -c "from deep_research_agent.agents.researcher import research_run; print('ok')"`

**Step 4: End-to-end smoke via CLI**

Run: `dra research "what is prompt caching in LLMs" --routing config/routing_diverse.yaml 2>&1 | tail -60`
Expected:
- Landscape agent event appears before researcher event.
- Report produced at `runs/<id>/report.md`.
- `runs/<id>/notes.json` contains at least one LANDSCAPE note and one QUESTION note with status='SYNTHESIZED' (the root).
- No tracebacks.

If the researcher ever skips `answer_question` on the root, the fallback produces a minimal report — that's a prompt issue to iterate on, not a blocker for committing this phase.

**Step 5: Commit**

```bash
git add src/deep_research_agent/agents/researcher.py
git commit -m "feat(researcher): iterative orchestrator w/ landscape + answer_question commit"
```

---

## Phase F — Update report composer + server runner to read QUESTION notes

The old `compose_report_markdown` and `server/runner.py` read SYNTHESIS notes to reconstruct partial reports on crash. Now the equivalent data lives on QUESTION notes (`status=SYNTHESIZED` with `synthesis_markdown` in metadata). Update both.

### Task F1: Update `compose_report_markdown`

**Files:**
- Modify: `src/deep_research_agent/agents/schemas.py` — `compose_report_markdown`

**Step 1: Replace the fallback branch**

Find the block:

```python
        elif memory is not None:
            # No report at all - reconstruct from the note graph.
            syntheses = memory.list_by_type(NoteType.SYNTHESIS)
```

Replace with:

```python
        elif memory is not None:
            # No report at all - reconstruct from answered QUESTION notes.
            from ..schemas.note import QuestionMetadata

            answered = [
                n
                for n in memory.list_by_type(NoteType.QUESTION)
                if isinstance(n.metadata, QuestionMetadata)
                and n.metadata.status == "SYNTHESIZED"
            ]
            if answered:
                parts.append("## Partial report (reconstructed from answered questions)")
                parts.append("")
                parts.append(
                    "_The top-level researcher did not produce a final "
                    "structured report. The sub-question answers below "
                    "were recovered from the note graph._"
                )
                parts.append("")
                for n in answered:
                    meta = n.metadata
                    assert isinstance(meta, QuestionMetadata)
                    parts.append(f"### {n.description or n.title}")
                    parts.append("")
                    if meta.bottom_line:
                        parts.append(f"**Bottom line:** {meta.bottom_line}")
                        parts.append("")
                    if meta.synthesis_markdown:
                        parts.append(meta.synthesis_markdown)
                        parts.append("")
            else:
                parts.append("_No answered questions in memory._")
                parts.append("")
```

And remove the `_ = SynthesisMetadata` line and the `SynthesisMetadata` import from the local-scope import at the top of the function; leave `SourceNoteMetadata` there.

**Step 2: Ruff**

`ruff check --fix src/deep_research_agent/agents/schemas.py && ruff format src/deep_research_agent/agents/schemas.py`

**Step 3: Commit**

```bash
git add src/deep_research_agent/agents/schemas.py
git commit -m "refactor(schemas): compose_report_markdown reads answered QUESTION notes"
```

### Task F2: Update `server/runner.py`

**Files:**
- Modify: `src/deep_research_agent/server/runner.py`

**Step 1: Find the synthesis-note touchpoints**

Run: `grep -n "SYNTHESIS\|SynthesisMetadata\|synthesis_note" src/deep_research_agent/server/runner.py`

There are multiple spots. For each:
- **Materializing the final report as a note**: the runner currently creates a SYNTHESIS note holding the final report. After Phase E, the root QUESTION note IS the final report — the runner doesn't need to create a separate synthesis note. Delete the materialization block and instead surface the root question's NoteID (look up via `deps.memory.list_by_type(NoteType.QUESTION)` filtered to `parent_question_id=None, status=SYNTHESIZED`).
- **Reconstructing from SYNTHESIS notes on crash**: replace with the same QUESTION-based reconstruction from Task F1.

**Step 2: Perform the edits**

Read the file and make the changes described above. Keep exports (`ResearcherReport`) intact. Update the docstring at the top to reflect that the final report lives on the root question note.

**Step 3: Ruff + smoke**

`ruff check --fix src/deep_research_agent/server/runner.py && ruff format src/deep_research_agent/server/runner.py`

Smoke: start the server (`dra serve`), make one research request, and confirm the UI still renders the final report. If the UI reads a synthesis-note endpoint, that endpoint either needs to accept a QUESTION note id or we keep SYNTHESIS notes around as a compat shim for this phase. **Default: if the UI requires SYNTHESIS notes, defer UI updates to a follow-up and keep Phase F2 scoped to the CLI path.** Flag this in the commit message.

**Step 4: Commit**

```bash
git add src/deep_research_agent/server/runner.py
git commit -m "refactor(server): final report lives on root QUESTION note"
```

---

## Phase G — Cleanup (optional, can defer)

With the new protocol landed, `write_question_synthesis` and `write_research_report` are unused. Remove them. Also consider removing `NoteType.SYNTHESIS` + `SynthesisMetadata` if the UI doesn't need them.

### Task G1: Remove `write_question_synthesis` + `write_research_report`

**Files:**
- Modify: `src/deep_research_agent/agents/tools/notes.py`

**Step 1: Confirm they are unused**

Run: `grep -rn "write_question_synthesis\|write_research_report" src/deep_research_agent tests/`
Expected: no hits in src/ outside the definition in `tools/notes.py`. (tests/ may still reference; fix them.)

**Step 2: Delete the two tool functions** from `tools/notes.py`.

**Step 3: Ruff + smoke CLI run**

`ruff check --fix src/deep_research_agent/agents/tools/notes.py && ruff format src/deep_research_agent/agents/tools/notes.py`
`dra research "a short smoke query" 2>&1 | tail -30`

**Step 4: Commit**

```bash
git add src/deep_research_agent/agents/tools/notes.py
git commit -m "chore(tools): drop obsolete write_question_synthesis / write_research_report"
```

### Task G2 (further-deferred, only if confirmed unused): Remove SYNTHESIS note type

Skip unless `grep -rn "NoteType.SYNTHESIS\|SynthesisMetadata" src/` comes back clean across `server/` and any UI rendering code. If the UI still reads SYNTHESIS notes, leave the enum value + metadata class in place — they're cheap dead weight, not harmful.

---

## Phase H — End-to-end validation

### Task H1: Full CLI smoke with inspection

**Step 1: Clean run**

Run: `dra research "what are the tradeoffs between RAG and long-context for enterprise LLM apps" --routing config/routing_diverse.yaml`

**Step 2: Inspect the artifacts**

- `runs/<id>/report.md` — should be non-empty, include `[source-...]` citations, and read as a coherent synthesis.
- `runs/<id>/notes.json` — should contain:
  - One LANDSCAPE note
  - One root QUESTION note with `status=SYNTHESIZED`, `parent_question_id=None`
  - Multiple child QUESTION notes (one per sub-question), `status=SYNTHESIZED`, `parent_question_id=<root>`
  - Multiple SOURCE notes, some with `topics=[...]` (landscape-created) and `state=ANALYZED` (analyst-upgraded)
  - Zero SYNTHESIS notes (after Phase G1) — or some (before Phase G1)
- `runs/<id>/events.jsonl` — should show agent_start/done events for LANDSCAPE, RESEARCHER, multiple ANALYST entries.

**Step 3: Verify the researcher never saw raw source content**

Inspect the researcher's logfire trace (or console output) and confirm its tool calls are only `get_research_state`, `load_note` (on QUESTION ids only), `investigate_question`, `answer_question`. No `search_*`, no `fetch_url`, no `load_note` on source ids.

**Step 4: Verify the iterative loop kicked in at least once**

The events log should show at least one case of: analyst A done → researcher dispatches analyst B in a later turn. If the researcher only did one round and committed, that's fine on a narrow query but the infrastructure should support a second round. Rerun with a broader query if needed to observe iteration.

**Step 5: Commit any tweaks made during validation**

---

## Summary of what exists after this plan

**Agents:**
- `landscape` (new) — `src/deep_research_agent/agents/landscape.py`
- `researcher` (rewritten) — `src/deep_research_agent/agents/researcher.py`
- `analyst` (renamed from `question_investigator`) — `src/deep_research_agent/agents/analyst.py`

**Tools added to `agents/tools/notes.py`:**
- `write_landscape_brief` — landscape's commit tool
- `answer_question` — shared commit tool (analysts + researcher root-question commit)
- `get_research_state` — researcher's between-round state snapshot

**Tools removed:**
- `write_question_synthesis`, `write_research_report` (Phase G1)

**Schema changes:**
- `QuestionMetadata` gains synthesis fields + `parent_question_id`
- `SourceMetadata` gains `topics: list[str]`

**Protocol changes:**
- Source notes dedup by URL in `create_source_note`
- Analysts receive their `question_id` from the caller; they update the existing QUESTION note in place instead of creating a SYNTHESIS note
- The researcher creates a root QUESTION note on run start and commits the final report by answering it
- Researcher has no scouting tools — landscape owns scouting
- Per-run analyst dispatch budget (backstop; prompt governs main behavior)

**Deferred (future work):**
- `adversarial_check`, `competing_hypothesis` pattern tools
- `verify_claim`
- Analyst-side search sub-agent
- Full removal of `NoteType.SYNTHESIS` + `SynthesisMetadata`
