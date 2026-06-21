"""Eval harness entry point.

    python -m evals.cli run [--dataset ...] [--tags ...] [--judge] [--out ...]
                            [--fail-under thresholds.yaml]

Requires the stack up and MCP_SERVER_URLS set (e.g.
http://localhost:9101,http://localhost:9102) so the in-process target can reach
the MCP servers.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from .report import evaluate_gates, print_summary, write_json, write_markdown
from .runner import load_dataset, run_suite
from .targets.in_process import InProcessTarget

DEFAULT_DATASET = "evals/datasets/golden.jsonl"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


async def _run(args: argparse.Namespace) -> int:
    cases = load_dataset(args.dataset)
    target = await InProcessTarget.create()

    judge = None
    if args.judge:
        try:
            from .judge import Judge  # Phase 4

            judge = Judge()
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] judge unavailable ({exc}); continuing without it", file=sys.stderr)

    try:
        report = await run_suite(
            cases,
            target,
            judge=judge,
            tags=args.tags,
            k=args.k,
            repeats=args.repeats,
            dataset=Path(args.dataset).name,
        )

        if args.fail_under:
            import yaml  # optional dep (evals extra)

            thresholds = yaml.safe_load(Path(args.fail_under).read_text(encoding="utf-8")) or {}
            report.thresholds = thresholds
            report.gate_failures = evaluate_gates(report, thresholds)

        out = Path(args.out) / _timestamp()
        write_json(report, out)
        write_markdown(report, out)
        print_summary(report)
        print(f"\nwrote: {out}/results.json and {out}/report.md")
        return 1 if report.gate_failures else 0
    finally:
        await target.aclose()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evals")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run the eval suite")
    r.add_argument("--dataset", default=DEFAULT_DATASET)
    r.add_argument("--tags", nargs="*", default=None, help="only run cases with any of these tags")
    r.add_argument("--k", type=int, default=5, help="k for retrieval@k metrics")
    r.add_argument("--repeats", type=int, default=1, help="judge repeats (Phase 4)")
    r.add_argument("--judge", action="store_true", help="enable LLM-as-judge (Phase 4)")
    r.add_argument("--out", default="results")
    r.add_argument("--fail-under", default=None, help="thresholds YAML; non-zero exit if any gate fails")

    args = ap.parse_args(argv)
    if args.cmd == "run":
        return asyncio.run(_run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
