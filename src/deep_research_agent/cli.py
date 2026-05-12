"""Command-line entry point.

Two subcommands:

    dra research "your query"    # run a single research session to the terminal
    dra serve                     # start the live UI (FastAPI + WebSocket)

The `serve` path is the main way to watch a run unfold - the UI
renders an "Agents Running" panel, a live note graph, an activity
log, and the final report. The `research` subcommand is the headless
equivalent: same agent pipeline, writes `runs/<id>/report.md`.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

from .agents.deps import build_deps, close_deps
from .agents.researcher import research_run
from .agents.schemas import ResearcherReport, compose_report_markdown
from .config import load_local_config, load_routing_config
from .observability import silence_noisy_loggers
from .retrieval import apply_retrieval_rate_limits
from .run_artifacts import build_run_summary, persist_run_artifacts
from .run_id import new_run_id

logger = logging.getLogger(__name__)
console = Console(stderr=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dra",
        description=(
            "Deep research agent: a top-level researcher agent over the web + academic literature."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_research = sub.add_parser("research", help="Run one research session to the terminal")
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

    p_serve = sub.add_parser("serve", help="Start the live UI server")
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
        "--runs-dir",
        default="runs",
        help="Directory to write per-run output into",
    )
    p_serve.add_argument("--host", default="127.0.0.1", help="Bind host")
    p_serve.add_argument("--port", default=8000, type=int, help="Bind port")

    args = parser.parse_args(argv)

    log_level = logging.INFO if getattr(args, "verbose", False) else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    silence_noisy_loggers()

    if args.command == "research":
        return asyncio.run(_run_research(args))
    if args.command == "serve":
        return _run_serve(args)
    return 1


def _run_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .server import create_app

    app = create_app(
        routing_path=args.routing,
        local_path=args.local_config,
        runs_dir=args.runs_dir,
    )
    console.print(f"[bold cyan]dra serve[/] - live UI at [bold]http://{args.host}:{args.port}[/]")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


async def _run_research(args: argparse.Namespace) -> int:
    local = load_local_config(args.local_config)
    routing = load_routing_config(args.routing)
    apply_retrieval_rate_limits(local.retrieval)

    run_id = new_run_id()
    started_at = datetime.now(UTC)
    run_dir = Path(args.runs_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    console.print(
        f"[bold cyan]dra[/] run=[bold]{run_id}[/] "
        f"routing=[dim]{routing.name}[/] "
        f"query=[italic]{args.query!r}[/]"
    )

    deps = build_deps(local, routing)

    report: ResearcherReport | None = None
    failed = False
    try:
        with console.status("[cyan]researcher agent running...", spinner="dots"):
            try:
                report = await research_run(deps, args.query)
            except Exception:
                logger.exception("research run failed")
                failed = True

        # Always dump what we have - notes accumulated up to the failure point
        # are usually the most useful artifact for debugging.
        try:
            await _dump_run(run_id, run_dir, args.query, started_at, deps, report)
        except Exception:
            logger.exception("dump failed")
    finally:
        await close_deps(deps)

    if failed or report is None:
        console.print("[red]run failed - see log for details[/]")
        console.print(f"  partial notes: [dim]{run_dir}/notes.json[/]")
        return 1

    console.print()
    console.print("[green]OK[/] research run complete")
    console.print(f"  notes in memory: [bold]{len(deps.memory)}[/]")
    console.print(f"  questions investigated: [bold]{len(report.questions_investigated)}[/]")
    console.print(f"  report:          [bold cyan]{run_dir / 'report.md'}[/]")
    console.print(f"  notes json:      [dim]{run_dir / 'notes.json'}[/]")
    console.print(f"  full report:     [dim]{run_dir / 'report.json'}[/]")
    console.print(f"  token usage:     [dim]{run_dir / 'token_usage.json'}[/]")
    return 0


async def _dump_run(
    run_id: str,
    run_dir: Path,
    query: str,
    started_at,
    deps,
    report: ResearcherReport | None,
) -> None:
    """Write per-run artifacts to disk. `compose_report_markdown`
    handles happy-path (use ResearcherReport) and crash-path
    (reconstruct from synthesis/source notes) uniformly.
    """
    md = compose_report_markdown(query=query, report=report, memory=deps.memory)
    summary = build_run_summary(
        run_id=run_id,
        query=query,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        report_note_id=None,
        notes=deps.memory.all(),
        tokens=deps.tracker.to_dict(),
    )
    await persist_run_artifacts(
        run_dir,
        notes=deps.memory.all(),
        report_markdown=md,
        report_json=report.model_dump(mode="json") if report is not None else None,
        summary=summary,
    )
    try:
        await asyncio.to_thread(deps.tracker.save_json, run_dir / "token_usage.json")
    except Exception:
        logger.exception("token_usage save failed")
    logger.info("%s", deps.tracker.format_table())


if __name__ == "__main__":
    sys.exit(main())
