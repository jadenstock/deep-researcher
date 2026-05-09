# 02 — Data Model

This is the type-level spine of the system. The rest of the code exists
to read, produce, and mutate these structures.

All schemas live under `deep_research_agent.schemas`.

## IDs

`schemas/ids.py` — typed aliases over `str`:

```python
TaskID   = NewType("TaskID", str)    # "task_<10 hex>"
NoteID   = NewType("NoteID", str)    # "<prefix>_<10 hex>"
RunID    = NewType("RunID", str)     # "run_<YYYYMMDD_HHMMSS>_<4 hex>"
SourceID = NewType("SourceID", str)  # alias for NoteID pointing at a source_note
```

IDs are minted by `scheduler/ids.py` (`new_task_id`, `new_note_id`,
`new_run_id`). Prefixes are purely cosmetic (they show up in logs and
the Obsidian vault filename); the graphs don't interpret them.

## Task graph

### `Task` (`schemas/task.py`)

A unit of work. One handler invocation per task. Fields:

| Field | Type | Purpose |
|-------|------|---------|
| `id` | `TaskID` | Primary key |
| `parent_id` | `TaskID \| None` | Spawner (for audit trail) |
| `goal` | `str` | Natural-language goal; often seeded into the LLM prompt |
| `type` | `TaskType` | Dispatcher key (see below) |
| `role` | `RoleClass` | `generative` / `judgment` / `cheap_deterministic` |
| `tier` | `TaskTier` | `LOW` / `MID` / `HIGH` |
| `pattern` | `OrchestrationPattern \| None` | Which sub-DAG of `QUESTION_SYNTHESIZE` to run |
| `question_round` | `QuestionRound \| None` | 1–5, see §Methodology below |
| `status` | `TaskStatus` | Lifecycle state |
| `success_criteria` | `str` | Documentation / prompt material |
| `depends_on` | `list[DepEdge]` | Typed upstream dependencies |
| `dep_scope` | `DepScope` | Retrieval-ignores vs. synthesis-waits policy |
| `reads_notes` | `list[NoteID]` | Notes the handler expects on entry |
| `writes_notes` | `list[NoteID]` | Filled in by the scheduler after a mutation lands |
| `spawned_sub_tasks` | `list[TaskID]` | Children, filled in when the scheduler applies the result |
| `input_refs` | `dict[str, str]` | Free-form string refs between handlers (e.g. `{"claim_id", "source_note_id", "question", "write_report_task_id"}`) |
| `created_at` / `completed_at` | `datetime` | Timestamps |

### Enums

From `schemas/enums.py`:

- **`TaskType`**: `LANDSCAPE_SURVEY`, `DECOMPOSE`, `SEARCH`,
  `SCAN_SEARCH_RESULTS`, `FETCH_AND_EXTRACT`, `ANALYZE_SOURCE`,
  `QUESTION_SYNTHESIZE`, `VERIFY_CLAIM`, `ADVERSARIAL_CRITIQUE`,
  `ANALYZE_CONSISTENCY`, `SYNTHESIZE`, `REPLAN`, `SCOPE_ESCALATION`,
  `CHECK_TERMINATION_READY`, `VALIDATE_COMPLETION`, `WRITE_REPORT`.
  (Not all have handlers in the current tree — `ANALYZE_SOURCE`,
  `SEARCH`, `SCAN_SEARCH_RESULTS` etc. are intentionally folded into
  the fat `QUESTION_SYNTHESIZE` handler; see
  [05-orchestration-patterns.md](05-orchestration-patterns.md).)

- **`TaskStatus`**: `PENDING`, `RUNNING`, `BLOCKED_ON_SYNTHESIS_DEP`,
  `BLOCKED_ON_SPLIT`, `DONE`, `ESCALATED`, `ABANDONED`.

- **`RoleClass`**: `generative`, `judgment`, `cheap_deterministic`.

- **`TaskTier`**: `LOW`, `MID`, `HIGH`. Drives the
  `RoutingConfig.tiers[tier].<role>` lookup.

- **`OrchestrationPattern`**: `single_researcher`, `maker_checker`,
  `multi_perspective`, `debate`, `ach`.

- **`QuestionRound`**: `STARBURSTING` (1), `STRUCTURAL` (2),
  `FALSIFICATION` (3), `PREMORTEM` (4), `METACOGNITIVE` (5). Each
  agent prompt declares its round; the round scaffolds the prompt's
  framing (generate-questions / decompose / falsify /
  premortem / audit).

- **`DependencyType`**: `produces_context_for`, `compared_against`,
  `temporally_follows`, `none`.

### Dependencies — `DepEdge` + `DepScope`

```python
class DepEdge(BaseModel):
    upstream: TaskID
    kind: DependencyType

class DepScope(BaseModel):
    retrieval_ignores: bool = False   # retrieval runs regardless of deps
    synthesis_waits: bool = True      # synthesis waits for upstream DONE
```

Dependencies are staged: retrieval-phase tasks can run regardless of
unresolved upstream deps, while synthesis-phase tasks wait until
upstream work is in a terminal state. `TaskGraph.get_ready()`
implements this — it returns tasks that either (a) have
`dep_scope.retrieval_ignores=True`, or (b) whose deps are all `DONE` /
`ABANDONED` / `ESCALATED`.

Treating `ABANDONED` as satisfied is deliberate cascade behavior:
downstream tasks should not deadlock on upstream work that will never
land.

### `TaskGraph` (`scheduler/task_graph.py`)

An in-memory dict keyed on `TaskID`, with four operations that matter:

| Method | Purpose |
|--------|---------|
| `add(task)` | Insert; raises if ID collides |
| `get_ready()` | Returns PENDING tasks with satisfied deps |
| `abandon_task(task_id)` | Mark ABANDONED and strip incoming dep edges from all other tasks |
| `all_terminal()` | True when every task is DONE/ABANDONED/ESCALATED |

Status transitions go through `update_status` or, for cascading, through
`abandon_task`. The scheduler sets DONE via `_finish` after a
successful handler run.

## Note graph

### `Note` (`schemas/note.py`)

The only long-term memory. Every piece of evidence, synthesis, or
decision is a `Note`:

```python
class Note(BaseModel):
    id: NoteID
    type: NoteType                  # discriminator
    title: str
    description: str = ""
    content: str = ""
    links: list[Link] = []
    metadata: NoteMetadata          # discriminated union keyed on type
    version: int = 1
    last_modified_by: TaskID | None
    last_modified_at: datetime
    created_by: TaskID | None
    created_at: datetime
```

The `metadata` field is a **discriminated union** over per-type
payloads, validated via Pydantic's `Field(discriminator="type")`:

| `NoteType` | Metadata class | Purpose |
|------------|----------------|---------|
| `landscape_note` | `LandscapeMetadata` | Output of Phase 1. Themes, positions, under-covered areas, raw query |
| `source_note` | `SourceNoteMetadata` | Fetched source + extracted claims + tier + peer-review flag |
| `question_note` | `QuestionMetadata` | Sub-question with `classification` and `status` (`OPEN` / `IN_PROGRESS` / `SYNTHESIZED`) |
| `synthesis_note` | `SynthesisMetadata` | Per-question synthesis; records pattern, surviving dissent, triangulation_score, distinct_tiers |
| `decision_note` | `DecisionMetadata` | Free-form decisions: AIMS scoping, verification verdicts, replan cycles, completion audits, final report |
| `open_question_note` | `OpenQuestionMetadata` | Scope-creep cut list items, out-of-scope acknowledgements |
| `hypothesis_note` | `HypothesisMetadata` | ACH hypothesis with per-source verdict breakdown |

### `Link` — typed edges

```python
class Link(BaseModel):
    target_id: NoteID
    edge_type: str       # e.g. "supports", "refutes", "answers",
                         #      "source_for_synthesis", "hypothesis_of_synthesis"
    context: str | None
```

Edge types in use across the codebase:

- `answers` — synthesis_note → question_note
- `source_for_synthesis` — synthesis_note → source_note
- `hypothesis_of_synthesis` — hypothesis_note ↔ synthesis_note
- `verification_of` — verification decision_note → source_note
- `archives_question` — abandon decision_note → question_note
- `spawned_by_replan` — replan decision_note → spawned note

Nothing enforces the edge-type string globally — it's a string-typed
convention.

### `SourceMetadata` (`schemas/source.py`)

The richest metadata payload. Source_notes are produced by the
`QUESTION_SYNTHESIZE` handler after fetch, extraction, and tier
classification. The schema supports a "stub" form (core metadata but
no `claims` / `evaluation`) and a "full" form (both populated); the
Landscape Survey in this codebase does not currently produce stubs,
so every source_note written is full.

```python
class SourceMetadata(BaseModel):
    url: str
    title: str
    authors: list[str] = []
    venue: str | None = None
    year: int | None = None
    tier: Tier                                      # 1..5
    tier_rationale: str                             # classifier's explanation
    classifier_confidence: float                    # 0..1
    peer_reviewed: bool                             # strict; independent of tier
    citation_count: int | None = None
    raw_content_ref: str | None = None              # path to on-disk full content
    structured_content: StructuredContent | None    # only for long sources (>=8K tokens)
    summary: str | None = None
    landscape_contribution: str | None = None       # survey-only one-liner
    claims: list[ClaimItem] = []                    # populated on analyzer upgrade
    evaluation: EvalItem | None = None              # methodology + agent skepticism
```

### `ClaimItem`

The atomic unit of evidence:

```python
class ClaimItem(BaseModel):
    id: str                                 # "<note.id>-<idx>"
    text: str                                # paraphrased claim
    quote: str = Field(min_length=1)         # verbatim passage — required
    page_or_section: str | None
    extractor_confidence: float              # 0..1
    verification_status: VerificationStatus  # UNVERIFIED / SUPPORTS / REFUTES / INCONCLUSIVE
    analyzed_by_family: str | None           # "anthropic" / "openai" / ... for cross-family routing
    perspective: str                         # "neutral" / "skeptic" / "advocate" / "affirmative" / "negative"
    verification_rationale: str | None       # set by VERIFY_CLAIM handler
    verification_note_id: str | None         # link to the decision_note carrying the rationale
    models_tested: list[str]                 # AI/ML model names the source explicitly evaluates
```

Two load-bearing design choices in this schema:

- **`quote` has `min_length=1`**. The analyzer cannot emit a claim
  without a quote. This is the primary guard against phantom citations.
- **`analyzed_by_family`** is populated by the executor on every claim
  the analyzer extracts, so a downstream `VERIFY_CLAIM` can be routed
  to a different family without re-reading prompts. See
  [10-routing-and-models.md](10-routing-and-models.md).
- **`perspective`** records which framing the analyzer used
  (`neutral` / `skeptic` / `advocate` / `affirmative` / `negative`)
  so the synthesizer can see per-framing agreement and divergence.

### `StructuredContent` and long-source routing

```python
class StructuredContent(BaseModel):
    title: str
    abstract: str | None
    section_headers: list[str]
    first_paragraph_of_each_section: dict[str, str]
    table_of_contents: list[str]
    figure_captions: list[str]
```

Built deterministically in `retrieval/structure.py` when a source's
extracted markdown exceeds `LONG_SOURCE_TOKEN_THRESHOLD` (8K tokens ≈
32K chars). The analyzer receives the outline plus a 6000-char
excerpt — not the full body — when reading a long source.

### Per-type metadata (summary)

- **`LandscapeMetadata`** — themes, positions, key_sources, under_covered_areas,
  methodology_distribution, tier_distribution, peer_review_fraction,
  raw_query.
- **`QuestionMetadata`** — classification (`lookup` / `synthesis` /
  `contested` / `sparse`), adopted_position, status.
- **`SynthesisMetadata`** — pattern (OrchestrationPattern value),
  surviving_dissent, linchpin_evidence, triangulation_score,
  distinct_tiers.
- **`DecisionMetadata`** — category (free-form; e.g. `aims_scoping`,
  `verification`, `termination_readiness`, `completion_audit`,
  `final_report`, `replan_cycle`, `abandoned_sub_question_archive`),
  rationale, relates_to_task.
- **`OpenQuestionMetadata`** — reason_excluded.
- **`HypothesisMetadata`** — hypothesis_text, inconsistency_score,
  supporting / inconsistent / neutral evidence lists,
  tentatively_adopted.

### `NoteGraph` (`scheduler/note_graph.py`)

In-memory dict keyed on `NoteID`, with three mutating operations —
`add`, `replace`, and nothing else. Writes are serialized by the
scheduler's write lock; this class does no locking itself.

```python
def replace(self, note: Note, by: TaskID, expected_version: int | None = None):
    existing = self._notes[note.id]
    if expected_version is not None and existing.version != expected_version:
        raise NoteVersionConflict(...)
    self._notes[note.id] = note.model_copy(
        update={
            "version": existing.version + 1,
            "last_modified_by": by,
            "last_modified_at": datetime.now(UTC),
        }
    )
```

`expected_version` is a hook for optimistic concurrency but is not
used — every call site passes `None`. Write serialization comes
from the scheduler's `asyncio.Lock`, which is enough as long as every
mutation is routed through `TaskResult`.

## NoteReader — read-only view

Executors receive a `NoteReader` protocol (`scheduler/scheduler.py`)
that exposes only `.get(id)`, `.by_type(type)`, `.all()`, and
`__contains__`. The protocol is implemented by `NoteGraph` itself, but
executors may not call mutating methods — they must return mutations
via `TaskResult.note_mutations` instead. This is not enforced by the
language; it is enforced by convention and by the scheduler being the
only class that holds the write lock.

## TaskResult — what a handler hands back

```python
class TaskResult(BaseModel):
    note_mutations: list[NoteMutation]      # create or replace
    spawned_tasks: list[Task]
    added_dep_edges: list[DepEdgeAdd]       # graft a dep onto an existing task
    abandoned_task_ids: list[TaskID]
    verdict: str                             # short human-readable summary
```

This is the scheduler's only handle on a handler's output. The
scheduler holds the write lock, applies every mutation in order, and
fires the `on_note_mutation` / `on_task_start` / `on_task_done`
callbacks so the UI and the token tracker can observe.

`DepEdgeAdd` lets a handler extend a downstream task's dependency list
post-hoc — for example, `QUESTION_SYNTHESIZE` spawning `VERIFY_CLAIM`
tasks and grafting them onto the termination-check task so the audit
chain waits for verifications to land. This is how the dependency
graph stays mutable as runtime evidence surfaces.

## IDs, version bumps, and audit trail

- `Note.version` starts at 1 and increments on every `replace`.
- `Note.last_modified_by` tracks the task that made the change.
- `Note.created_by` tracks the original creator.
- `Task.writes_notes` is appended to by the scheduler when a mutation
  carrying that note lands — so the task graph records the output of
  each task without the handler having to maintain the list manually.

This pair of invariants is how the markdown export can show per-note
provenance ("synthesized by task X at version 1, verified by task Y
at version 2") without a separate audit log.
