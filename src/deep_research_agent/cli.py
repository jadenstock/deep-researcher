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
import json
import logging
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

from .agents.deps import build_deps
from .agents.researcher import research_run
from .agents.schemas import ResearcherReport, compose_report_markdown
from .config import load_local_config, load_routing_config
from .observability import setup_logfire
from .retrieval import apply_retrieval_rate_limits

logger = logging.getLogger(__name__)
console = Console(stderr=True)


def _new_run_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


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
    for noisy in ("pdfminer", "pypdf", "httpcore", "httpx", "urllib3", "trafilatura"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

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
    setup_logfire(local)
    apply_retrieval_rate_limits(local.retrieval)

    run_id = _new_run_id()
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
    with console.status("[cyan]researcher agent running...", spinner="dots"):
        try:
            report = await research_run(deps, args.query)
        except Exception:
            logger.exception("research run failed")
            failed = True

    # Always dump what we have - notes accumulated up to the failure point
    # are usually the most useful artifact for debugging.
    try:
        _dump_run(run_dir, args.query, deps, report)
    except Exception:
        logger.exception("dump failed")

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


def _dump_run(
    run_dir: Path,
    query: str,
    deps,
    report: ResearcherReport | None,
) -> None:
    """Write per-run artifacts to disk. Three files side by side:
    - `report.md` for humans (always written, even on partial runs)
    - `report.json` for post-hoc inspection of the typed payload
    - `notes.json` for the full note graph (sources + questions + claims)

    Report composition delegates to `compose_report_markdown`, which
    handles happy-path (use ResearcherReport) and crash-path
    (reconstruct from synthesis/source notes) uniformly.
    """
    notes_out = [n.model_dump(mode="json") for n in deps.memory.all()]
    (run_dir / "notes.json").write_text(json.dumps(notes_out, indent=2, default=str))

    if report is not None:
        (run_dir / "report.json").write_text(
            json.dumps(report.model_dump(mode="json"), indent=2, default=str)
        )

    # Always write report.md - even on failure there's usually
    # something useful from the sub-agents that finished.
    md = compose_report_markdown(query=query, report=report, memory=deps.memory)
    (run_dir / "report.md").write_text(md)

    # Per-run token accounting. Mirrors the server runner so CLI users
    # get the same table/JSON. Written last so a failure here doesn't
    # mask the report artifacts.
    try:
        deps.tracker.save_json(run_dir / "token_usage.json")
    except Exception:
        logger.exception("token_usage save failed")
    logger.info("%s", deps.tracker.format_table())


if __name__ == "__main__":
    sys.exit(main())
