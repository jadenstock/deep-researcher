"""Markdown export of the note graph.

Writes one markdown file per note under `<run_dir>/notes/`, the final
report at `<run_dir>/report.md`, and a task graph snapshot at
`<run_dir>/tasks.json` for inspection.

Format is intentionally plain markdown — no tool-specific syntax (no
wikilinks, no YAML frontmatter). The note graph itself is the
load-bearing structure; this layer is one way to view it.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..scheduler import NoteGraph, TaskGraph
from ..schemas import Note
from ..schemas.enums import NoteType


def export_run(
    run_dir: Path,
    note_graph: NoteGraph,
    task_graph: TaskGraph,
) -> Path | None:
    """Write the run's notes + tasks to disk. Returns the report path if found."""
    run_dir.mkdir(parents=True, exist_ok=True)
    notes_dir = run_dir / "notes"
    notes_dir.mkdir(exist_ok=True)

    for note in note_graph.all():
        (notes_dir / f"{note.id}.md").write_text(_render_note(note))

    report_path: Path | None = None
    for n in note_graph.all():
        if n.type == NoteType.DECISION and n.metadata.category == "final_report":
            report_path = run_dir / "report.md"
            report_path.write_text(n.content)
            break

    tasks_path = run_dir / "tasks.json"
    tasks_path.write_text(
        json.dumps(
            {"tasks": [t.model_dump(mode="json") for t in task_graph.all()]},
            indent=2,
            default=str,
        )
    )

    return report_path


def _render_note(note: Note) -> str:
    out: list[str] = []
    out.append(f"# {note.title}")
    out.append("")
    out.append(f"- **id:** `{note.id}`")
    out.append(f"- **type:** `{note.type.value}`")
    out.append(f"- **version:** {note.version}")
    if note.created_by:
        out.append(f"- **created by task:** `{note.created_by}`")
    if note.description:
        out.append("")
        out.append(f"> {note.description}")

    out.extend(_render_metadata(note))

    if note.content:
        out.append("")
        out.append("---")
        out.append("")
        out.append(note.content)

    if note.links:
        out.append("")
        out.append("## Links")
        for link in note.links:
            ctx = f"  ({link.context})" if link.context else ""
            out.append(f"- `{link.edge_type}` → `{link.target_id}`{ctx}")

    return "\n".join(out) + "\n"


def _render_metadata(note: Note) -> list[str]:
    meta = note.metadata
    lines: list[str] = []
    if note.type == NoteType.SOURCE:
        lines.extend(
            [
                "",
                f"- **url:** {meta.url}",
                f"- **tier:** {meta.tier.value} — {meta.tier_rationale}",
                f"- **peer_reviewed:** {meta.peer_reviewed}",
                f"- **classifier_confidence:** {meta.classifier_confidence:.2f}",
            ]
        )
        if meta.claims:
            lines.append("")
            lines.append("## Claims")
            for c in meta.claims:
                lines.append(f"- **{c.text}**")
                lines.append(f'  - quote: "{c.quote}"')
                lines.append(f"  - verification: `{c.verification_status.value}`")
                lines.append(f"  - extractor confidence: {c.extractor_confidence:.2f}")
                if c.models_tested:
                    lines.append(f"  - models tested: {', '.join(c.models_tested)}")
    elif note.type == NoteType.QUESTION:
        lines.extend(
            [
                "",
                f"- **classification:** `{meta.classification.value}`",
                f"- **status:** `{meta.status}`",
                f"- **adopted_position:** {meta.adopted_position or '(none)'}",
            ]
        )
    elif note.type == NoteType.SYNTHESIS:
        lines.extend(["", f"- **pattern:** `{meta.pattern}`"])
        if meta.surviving_dissent:
            lines.append("")
            lines.append("### Surviving dissent")
            for d in meta.surviving_dissent:
                lines.append(f"- {d}")
        if meta.linchpin_evidence:
            lines.append("")
            lines.append("### Linchpin evidence")
            for s in meta.linchpin_evidence:
                lines.append(f"- `{s}`")
    elif note.type == NoteType.DECISION:
        lines.extend(
            [
                "",
                f"- **category:** `{meta.category}`",
                f"- **rationale:** {meta.rationale}",
            ]
        )
        if meta.relates_to_task:
            lines.append(f"- **relates_to_task:** `{meta.relates_to_task}`")
    elif note.type == NoteType.LANDSCAPE:
        lines.extend(
            [
                "",
                f"- **raw_query:** {meta.raw_query}",
                f"- **themes:** {len(meta.themes)}",
                f"- **positions:** {len(meta.positions)}",
                f"- **peer_review_fraction:** {meta.peer_review_fraction:.2f}",
            ]
        )
    elif note.type == NoteType.HYPOTHESIS:
        score = (
            f"{meta.inconsistency_score:.3f}"
            if meta.inconsistency_score is not None
            else "(unscored)"
        )
        lines.extend(
            [
                "",
                f"- **hypothesis:** {meta.hypothesis_text}",
                f"- **inconsistency_score:** {score}",
                f"- **tentatively_adopted:** {meta.tentatively_adopted}",
            ]
        )
    return lines
