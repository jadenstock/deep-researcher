"""Command-line entry point.

Subcommands:

    dra research "your query"    # run a single research session to the terminal
    dra research --query-file q.md --detach   # start in the background, print run_id
    dra status [RUN_ID]           # one-line progress (cost so far, analysts, sources)
    dra wait RUN_ID --timeout 540 # block until done or timeout, then print status
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
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

from .agents.deps import build_deps, close_deps
from .agents.researcher import research_run
from .agents.run_config import RunConfig
from .agents.schemas import ReportRenderOptions, ResearcherReport, compose_report_markdown
from .config import load_local_config, load_routing_config
from .observability import silence_noisy_loggers
from .pricing import fetch_router_prices, tracker_cost_usd
from .progress import PROGRESS_FILE, ProgressPublisher, find_runs, format_status, read_status
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
    p_research.add_argument("query", nargs="?", help="Natural-language research query")
    p_research.add_argument(
        "--query-file",
        help="Read the query from a file instead of the command line (for long structured queries)",
    )
    p_research.add_argument(
        "--detach",
        action="store_true",
        help="Start the run as a detached background process, print its run_id, and return",
    )
    p_research.add_argument(
        "--analyst-budget", type=int, help="Max analyst dispatches (default from RunConfig)"
    )
    p_research.add_argument(
        "--scout-budget-per-analyst",
        type=int,
        help="Max scouts per analyst (default from RunConfig)",
    )
    p_research.add_argument(
        "--scout-search-budget", type=int, help="Max searches per scout (default from RunConfig)"
    )
    # Internal: set by --detach so the child writes into the run dir the parent announced.
    p_research.add_argument("--run-id", help=argparse.SUPPRESS)
    p_research.add_argument(
        "--routing",
        default="config/routing_lean.yaml",
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
    p_research.add_argument(
        "--inline-reference-links",
        dest="inline_reference_links",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Render inline source references as links to the Sources section",
    )
    p_research.add_argument(
        "--bibliography",
        choices=("all", "inline"),
        default="inline",
        help="Sources section scope: all found sources, or only inline-cited sources",
    )
    p_research.add_argument(
        "--source-label-style",
        choices=("numbered", "note-id"),
        default="numbered",
        help="Render source labels as Source 1/2 or raw source note ids",
    )

    p_serve = sub.add_parser("serve", help="Start the live UI server")
    p_serve.add_argument(
        "--routing",
        default="config/routing_lean.yaml",
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

    p_status = sub.add_parser("status", help="Show progress of a run (default: newest)")
    p_status.add_argument("run_id", nargs="?", help="Run id (default: newest run)")
    p_status.add_argument("--runs-dir", default="runs", help="Directory holding per-run output")
    p_status.add_argument("--json", action="store_true", help="Print the raw progress JSON")
    p_status.add_argument("--active", action="store_true", help="List runs still in progress")

    p_wait = sub.add_parser(
        "wait",
        help="Block until a run finishes or the timeout passes (exit 0 ok, 1 failed, 3 running)",
    )
    p_wait.add_argument("run_id", help="Run id")
    p_wait.add_argument("--runs-dir", default="runs", help="Directory holding per-run output")
    p_wait.add_argument("--timeout", type=float, default=540, help="Seconds to wait (default 540)")
    p_wait.add_argument("--poll", type=float, default=10, help="Poll interval in seconds")

    args = parser.parse_args(argv)

    log_level = logging.INFO if getattr(args, "verbose", False) else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    silence_noisy_loggers()

    if args.command == "research":
        query = _resolve_query(args)
        if query is None:
            parser.error("research needs a query or --query-file")
        args.query = query
        if args.detach:
            return _detach_research(args)
        return asyncio.run(_run_research(args))
    if args.command == "status":
        return _run_status(args)
    if args.command == "wait":
        return _run_wait(args)
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


def _resolve_query(args: argparse.Namespace) -> str | None:
    if args.query_file:
        return Path(args.query_file).read_text().strip() or None
    return args.query.strip() if args.query else None


def _detach_research(args: argparse.Namespace) -> int:
    """Re-launch this research command as a detached process.

    The child runs in its own session so it outlives the shell (or Claude
    Code session) that started it. Paths are made absolute because the
    defaults are relative to the current directory.
    """
    run_id = new_run_id()
    runs_dir = Path(args.runs_dir).resolve()
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    query_file = run_dir / "query.md"
    query_file.write_text(args.query)
    cmd = [
        sys.executable,
        "-m",
        "deep_research_agent.cli",
        "research",
        "--query-file",
        str(query_file),
        "--run-id",
        run_id,
        "--routing",
        str(Path(args.routing).resolve()),
        "--local-config",
        str(Path(args.local_config).resolve()),
        "--runs-dir",
        str(runs_dir),
        "--bibliography",
        args.bibliography,
        "--source-label-style",
        args.source_label_style,
        "--inline-reference-links"
        if args.inline_reference_links
        else "--no-inline-reference-links",
    ]
    if args.verbose:
        cmd.append("--verbose")
    for flag in ("analyst_budget", "scout_budget_per_analyst", "scout_search_budget"):
        if getattr(args, flag) is not None:
            cmd += ["--" + flag.replace("_", "-"), str(getattr(args, flag))]
    with (run_dir / "console.log").open("w") as log:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    # Stub progress so `dra status`/`dra wait` see a starting run (not a
    # missing one) until the child's ProgressPublisher takes over the file.
    (run_dir / PROGRESS_FILE).write_text(
        json.dumps(
            {
                "run_id": run_id,
                "query": args.query[:200],
                "pid": proc.pid,
                "started_at": datetime.now(UTC).isoformat(),
                "phase": "starting",
                "finished": False,
                "ok": None,
                "last_event": "process starting",
            }
        )
    )
    print(f"run_id={run_id}")
    print(f"pid={proc.pid}")
    print(f"run_dir={run_dir}")
    print(f"log={run_dir / 'console.log'}")
    return 0


def _resolve_run_dir(runs_dir: str, run_id: str | None) -> Path | None:
    if run_id:
        d = Path(runs_dir) / run_id
        return d if d.is_dir() else None
    runs = find_runs(Path(runs_dir))
    return runs[0] if runs else None


def _run_status(args: argparse.Namespace) -> int:
    if args.active:
        active = [
            st
            for d in find_runs(Path(args.runs_dir))
            if (d / "progress.json").exists() and (st := read_status(d)).state == "running"
        ]
        for st in active:
            print(format_status(st))
        if not active:
            print("no active runs")
        return 0
    run_dir = _resolve_run_dir(args.runs_dir, args.run_id)
    if run_dir is None:
        print(f"run not found: {args.run_id or '(no runs)'}", file=sys.stderr)
        return 1
    st = read_status(run_dir)
    if args.json:
        print(json.dumps({"state": st.state, **st.progress}, indent=2))
    else:
        print(format_status(st))
    return 0


def _run_wait(args: argparse.Namespace) -> int:
    run_dir = _resolve_run_dir(args.runs_dir, args.run_id)
    if run_dir is None:
        print(f"run not found: {args.run_id}", file=sys.stderr)
        return 1
    deadline = time.monotonic() + args.timeout
    st = read_status(run_dir)
    while not st.done and time.monotonic() < deadline:
        time.sleep(min(args.poll, max(0.0, deadline - time.monotonic())))
        st = read_status(run_dir)
    print(format_status(st))
    if st.state == "running":
        return 3
    return 0 if st.state == "finished" else 1


async def _run_research(args: argparse.Namespace) -> int:
    local = load_local_config(args.local_config)
    routing = load_routing_config(args.routing)
    apply_retrieval_rate_limits(local.retrieval)

    run_id = args.run_id or new_run_id()
    started_at = datetime.now(UTC)
    run_dir = Path(args.runs_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    console.print(
        f"[bold cyan]dra[/] run=[bold]{run_id}[/] "
        f"routing=[dim]{routing.name}[/] "
        f"query=[italic]{args.query!r}[/]"
    )

    prices = await fetch_router_prices(local)
    run_config = RunConfig.from_payload(
        {
            k: getattr(args, k)
            for k in ("analyst_budget", "scout_budget_per_analyst", "scout_search_budget")
            if getattr(args, k) is not None
        }
    )
    progress = ProgressPublisher(
        run_dir,
        run_id=run_id,
        query=args.query,
        analyst_budget=run_config.analyst_budget,
        prices=prices,
    )
    deps = build_deps(local, routing, events=progress, run_config=run_config, prices=prices)

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
            await _dump_run(
                run_id,
                run_dir,
                args.query,
                started_at,
                deps,
                report,
                _report_render_options_from_args(args),
            )
        except Exception:
            logger.exception("dump failed")
    finally:
        progress.finish(ok=not failed and report is not None)
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
    render_options: ReportRenderOptions,
) -> None:
    """Write per-run artifacts to disk. `compose_report_markdown`
    handles happy-path (use ResearcherReport) and crash-path
    (reconstruct from synthesis/source notes) uniformly.
    """
    md = compose_report_markdown(
        query=query,
        report=report,
        memory=deps.memory,
        render_options=render_options,
    )
    summary = build_run_summary(
        run_id=run_id,
        query=query,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        report_note_id=None,
        notes=deps.memory.all(),
        tokens=deps.tracker.to_dict(),
        cost=tracker_cost_usd(deps.prices, deps.tracker.to_dict()),
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


def _report_render_options_from_args(args: argparse.Namespace) -> ReportRenderOptions:
    return ReportRenderOptions(
        inline_reference_links=args.inline_reference_links,
        bibliography_source_scope=args.bibliography,
        source_label_style="note_id" if args.source_label_style == "note-id" else "numbered",
    )


if __name__ == "__main__":
    sys.exit(main())
