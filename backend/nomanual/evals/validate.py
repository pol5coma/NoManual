"""Check the judge before trusting what it measures.

An unstable judge invalidates every comparison: a drop from 0.80 to 0.60 could
be a regression or could be the judge's mood. This happened once already -
haier-modo-sueno was graded correct on one run and incorrect on the next, with
the system's answer unchanged.

Two checks, run against a previous report so no system calls are repeated:

  consistency  grade the same answers N times; how many verdicts move
  agreement    compare against your own verdicts, when you have recorded them
"""

import asyncio
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

from nomanual.evals.cases import load_cases
from nomanual.evals.judge import judge_answer
from nomanual.evals.runner import RESULTS_DIR, resolve_products, source_text

logger = logging.getLogger(__name__)


def latest_report() -> dict[str, Any]:
    reports = sorted(Path(RESULTS_DIR).glob("*.json"))
    if not reports:
        raise SystemExit("No reports yet. Run the evals first.")
    return json.loads(reports[-1].read_text())


async def consistency(rounds: int = 3) -> dict[str, Any]:
    """Grade the same answers several times and count the disagreements.

    Reuses a stored report rather than re-running the system: the point is to
    isolate the judge's variance, so everything else has to stay identical.
    """
    report = latest_report()
    cases = {case.id: case for case in load_cases()}
    products = await resolve_products(list(cases.values()))

    unstable: list[dict[str, Any]] = []

    for stored in report["cases"]:
        case = cases.get(stored["id"])
        if case is None:
            continue

        source = ""
        if case.answerable:
            pages = set(case.expected_pages) | set(stored.get("cited_pages") or [])
            source = await source_text(products[(case.brand, case.model)], pages)

        verdicts = []
        for _ in range(rounds):
            verdict = await judge_answer(
                case.question,
                stored["answer"],
                case.expected_answer,
                case.answerable,
                source,
            )
            verdicts.append(verdict.matches)

        counts = Counter(verdicts)
        if len(counts) > 1:
            unstable.append(
                {"id": case.id, "verdicts": verdicts, "split": dict(counts)}
            )

    total = len([c for c in report["cases"] if c["id"] in cases])
    return {
        "rounds": rounds,
        "cases": total,
        "unstable": len(unstable),
        "stability": round(1 - len(unstable) / total, 3) if total else None,
        "details": unstable,
    }


async def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="  %(message)s")
    result = await consistency()

    print(f"\n{'=' * 58}\nJUDGE CONSISTENCY  ·  {result['rounds']} rounds\n{'=' * 58}")
    print(f"  cases      {result['cases']}")
    print(f"  unstable   {result['unstable']}")
    print(f"  stability  {result['stability']}")

    for case in result["details"]:
        print(f"    {case['id']:<28} {case['verdicts']}")

    if not result["details"]:
        print("\n  Every case graded the same way on every round.")

    from nomanual.core.db import engine

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
