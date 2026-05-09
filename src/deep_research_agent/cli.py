"""Command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

from .config import load_local_config, load_pipeline_config, load_routing_config
from .executor import AgentExecutor, register_handlers
from .export import export_run
from .observability import setup_logfire
from .retrieval.brave import set_brave_min_interval
from .scheduler import NoteGraph, Scheduler, TaskGraph, TaskResult, new_run_id, new_task_id
from .schemas import Task
from .schemas.enums import RoleClass, TaskTier, TaskType
from .token_usage import TokenUsageTracker

logger = logging.getLogger(__name__)
console = Console(stderr=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dra",
        description="Deep research agent — four-phase pipeline with mutable task graph.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_research = sub.add_parser("research", help="Run a research session on a query")
    p_research.add_argument("query", help="Natural-language research query")
    p_research.add_argument(
        "--routing",
        default="config/routing_diverse.yaml",
        help="Path to the routing config",
    )
    p_research.add_argument(
        "--local-config",
        default="config/local.toml",
        help="Path to the local TOML (endpoints + keys)",
    )
    p_research.add_argument(
        "--pipeline",
        default="config/pipeline.yaml",
        help=(
            "Path to the pipeline config YAML (thresholds, caps, hygiene "
            "toggles). Missing file falls back to built-in defaults."
        ),
    )
    p_research.add_argument(
        "--runs-dir",
        default="runs",
        help="Directory to write per-run output into",
    )
    p_research.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Log at INFO level to stderr",
    )

    p_replay = sub.add_parser("replay", help="Replay a cached run (not yet implemented)")
    p_replay.add_argument("run_id")

    p_serve = sub.add_parser("serve", help="Run the live UI server (FastAPI + WebSocket)")
    p_serve.add_argument(
        "--routing",
        default="config/routing_diverse.yaml",
        help="Path to the routing config",
    )
    p_serve.add_argument(
        "--local-config",
        default="config/local.toml",
        help="Path to the local TOML (endpoints + keys)",
    )
    p_serve.add_argument(
        "--pipeline",
        default="config/pipeline.yaml",
        help="Path to the pipeline config YAML",
    )
    p_serve.add_argument(
        "--runs-dir",
        default="runs",
        help="Directory to write per-run output into",
    )
    p_serve.add_argument("--host", default="127.0.0.1", help="Bind host (default: localhost)")
    p_serve.add_argument("--port", default=8000, type=int, help="Bind port (default: 8000)")

    args = parser.parse_args(argv)

    log_level = logging.INFO if getattr(args, "verbose", False) else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    # Silence third-party libraries that log at DEBUG with extreme verbosity.
    # pdfminer logs every PDF object parse (GB-scale per long PDF); pypdf and
    # httpcore/httpx are noisy at DEBUG on every request. We keep WARNING so
    # real errors still surface.
    for noisy in ("pdfminer", "pypdf", "httpcore", "httpx", "urllib3", "trafilatura"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if args.command == "research":
        return asyncio.run(_run_research(args))
    if args.command == "replay":
        console.print(f"[yellow]replay not yet implemented (run_id={args.run_id})[/]")
        return 1
    if args.command == "serve":
        return _run_serve(args)
    return 1


def _run_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .server import create_app

    app = create_app(
        routing_path=args.routing,
        local_path=args.local_config,
        pipeline_path=args.pipeline,
        runs_dir=args.runs_dir,
    )
    console.print(
        f"[bold cyan]dra serve[/] — live UI at " f"[bold]http://{args.host}:{args.port}[/]"
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


async def _run_research(args: argparse.Namespace) -> int:
    local = load_local_config(args.local_config)
    routing = load_routing_config(args.routing)
    pipeline = load_pipeline_config(args.pipeline)
    setup_logfire(local)
    set_brave_min_interval(local.retrieval.brave_min_interval_s)

    run_id = new_run_id()
    run_dir = Path(args.runs_dir) / run_id

    console.print(
        f"[bold cyan]dra[/] run=[bold]{run_id}[/] "
        f"routing=[dim]{routing.name}[/] "
        f"query=[italic]{args.query!r}[/]"
    )

    tracker = TokenUsageTracker()
    ex = AgentExecutor(routing=routing, local=local, pipeline=pipeline, tracker=tracker)
    register_handlers(ex)

    tg = TaskGraph()
    ng = NoteGraph()
    root_task = Task(
        id=new_task_id(),
        goal=args.query,
        type=TaskType.LANDSCAPE_SURVEY,
        role=RoleClass.GENERATIVE,
        tier=TaskTier.HIGH,
        success_criteria="produce a research report answering the query",
        created_at=datetime.now(UTC),
    )
    tg.add(root_task)

    with console.status("[cyan]starting...", spinner="dots") as status:

        def _on_start(task: Task) -> None:
            status.update(
                f"[cyan]running [bold]{task.type.value}[/] " f"[dim]id={task.id[-6:]}[/]..."
            )

        def _on_done(task: Task, result: TaskResult) -> None:
            verdict = result.verdict or f"wrote {len(task.writes_notes)} note(s)"
            console.print(
                f"  [dim]✓[/] [bold green]{task.type.value}[/] "
                f"[dim]{task.id[-6:]}[/] — {verdict}"
            )
            status.update("[cyan]working...")

        async def _replanner(task_graph: TaskGraph, note_graph: NoteGraph):
            from .replanner import run_replanner

            return await run_replanner(
                task_graph, note_graph, routing, local, root_task.id, tracker=tracker
            )

        sched = Scheduler(
            tg,
            ng,
            ex,
            on_task_start=_on_start,
            on_task_done=_on_done,
            replanner=_replanner,
            replan_cadence=pipeline.replanner.cadence,
            replan_budget=pipeline.replanner.budget,
            replan_min_progress_tasks=pipeline.replanner.min_progress_tasks,
            replan_skip_if_no_new_synthesis=pipeline.replanner.skip_if_no_new_synthesis,
        )
        run_failed = False
        try:
            await sched.run()
        except Exception:
            logger.exception("research run failed")
            console.print("[red]run failed — see log for details[/]")
            run_failed = True

        # Always export what we have (even on failure) so partial runs
        # are autopsy-able. Token usage is always written, summary is
        # always logged — costs are real whether the run finished or not.
        status.update("[cyan]exporting note graph...")
        try:
            report_path = export_run(run_dir, ng, tg)
        except Exception:
            logger.exception("export failed")
            report_path = None
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            tracker.save_json(run_dir / "token_usage.json")
        except Exception:
            logger.exception("token_usage save failed")
        logger.info(tracker.format_table())
        if run_failed:
            return 1

    console.print()
    console.print("[green]✓[/] run complete")
    console.print(f"  tasks completed: [bold]{len(tg)}[/]")
    console.print(f"  notes in graph:  [bold]{len(ng)}[/]")
    if report_path:
        console.print(f"  report:          [bold cyan]{report_path}[/]")
    else:
        console.print("  [yellow]no report emitted[/]")
    console.print(f"  notes directory: [dim]{run_dir}/notes/[/]")
    console.print(f"  tasks snapshot:  [dim]{run_dir}/tasks.json[/]")
    return 0 if report_path else 1


if __name__ == "__main__":
    sys.exit(main())
