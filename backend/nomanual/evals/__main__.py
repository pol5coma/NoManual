"""CLI: uv run python -m nomanual.evals

Prints a summary, writes the full report, and compares against the previous run
when there is one. A single number says little; a number next to last week's
says whether the change helped.
"""

import argparse
import asyncio
import json
import logging

from nomanual.core.db import engine
from nomanual.evals.cases import load_cases
from nomanual.evals.runner import RESULTS_DIR, run_all, write_report


def _previous_report() -> dict | None:
    reports = sorted(RESULTS_DIR.glob("*.json"))
    return json.loads(reports[-1].read_text()) if reports else None


def _print_summary(report: dict, previous: dict | None) -> None:
    print(f"\n{'=' * 62}\nEVAL  ·  {report['run_at']}\n{'=' * 62}")

    old = (previous or {}).get("summary", {})
    for key, value in report["summary"].items():
        if value is None:
            continue
        delta = ""
        before = old.get(key)
        if isinstance(value, float) and isinstance(before, float):
            change = value - before
            arrow = "▲" if change > 0 else "▼" if change < 0 else "="
            delta = f"   {arrow} {change:+.3f}  (antes {before:.3f})"
        print(f"  {key:<18} {value}{delta}")

    failures = [c for c in report["cases"] if not c["correct"]]
    if failures:
        print(f"\n  fallos ({len(failures)}):")
        for case in failures:
            flag = "no-recall" if case["recall"] is False else "         "
            print(f"    {flag}  {case['id']:<28} {case['judge_reason'][:58]}")


async def main() -> None:
    parser = argparse.ArgumentParser(prog="nomanual.evals")
    parser.add_argument("--case", help="Run a single case by id")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="  %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    cases = load_cases()
    if args.case:
        cases = [c for c in cases if c.id == args.case]
        if not cases:
            raise SystemExit(f"No case with id {args.case!r}")

    previous = _previous_report()
    report = await run_all(cases)
    path = write_report(report)

    _print_summary(report, previous)
    print(f"\n  informe: {path}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
