"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys


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
        help="Path to the model routing config",
    )
    p_research.add_argument(
        "--interactivity",
        default="L0",
        choices=["L0", "L1", "L2", "L3", "L4", "L5"],
        help="User-in-the-loop level",
    )

    p_replay = sub.add_parser(
        "replay", help="Replay a previous run against cached tool results (no network)"
    )
    p_replay.add_argument("run_id", help="Run ID under ./runs/")

    args = parser.parse_args(argv)

    if args.command == "research":
        print(
            f"[stub] would run research: query={args.query!r} "
            f"routing={args.routing} interactivity={args.interactivity}",
            file=sys.stderr,
        )
        return 0
    if args.command == "replay":
        print(f"[stub] would replay run: {args.run_id}", file=sys.stderr)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
