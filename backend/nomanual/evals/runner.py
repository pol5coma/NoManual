"""Run the golden set and write a report.

Not a pytest suite, on purpose. A test passes or fails, is fast and is free;
an eval returns a number, takes minutes and costs money. Running these on every
`pytest` would make the test suite slow and expensive, and the output wanted
here is a report, not "3 passed".

Three things are measured separately, because a single figure cannot tell you
whether retrieval or generation broke:

  recall      did any retrieved chunk cover a page where the answer lives
  correctness does the answer match the reference (judged)
  abstention  on questions the manual cannot answer, did it decline
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from nomanual.agent.graph import answer_question
from nomanual.agent.nodes import MAX_ATTEMPTS, MIN_SIMILARITY
from nomanual.core.config import get_settings
from nomanual.core.db import SessionLocal
from nomanual.evals.cases import EvalCase, load_cases
from nomanual.evals.judge import judge_answer
from nomanual.models import Product
from nomanual.searching.search import TOP_K

logger = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).resolve().parents[3] / "evals" / "results"


def current_config() -> dict[str, Any]:
    """The knobs the result depends on.

    Without this a comparison between two runs is an anecdote: a change in the
    numbers could come from the new chunker or from a different model, and
    there would be no way to tell.
    """
    settings = get_settings()
    return {
        "pdf_backend": settings.pdf_backend,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "embedding_model": settings.embedding_model,
        "embedding_dimensions": settings.embedding_dimensions,
        "chat_model": settings.chat_model,
        "top_k": TOP_K,
        "min_similarity": MIN_SIMILARITY,
        "max_attempts": MAX_ATTEMPTS,
    }


async def resolve_products(cases: list[EvalCase]) -> dict[tuple[str, str], Any]:
    """Map each case's brand and model to the product id retrieval needs.

    Resolved once up front so a missing product fails loudly here, rather than
    quietly running the whole golden set against the entire corpus.
    """
    wanted = {(case.brand, case.model) for case in cases}

    async with SessionLocal() as session:
        rows = (
            await session.execute(select(Product.brand, Product.model, Product.id))
        ).all()

    catalogue = {
        (brand.casefold(), model.casefold()): pid for brand, model, pid in rows
    }

    resolved = {}
    for brand, model in wanted:
        product_id = catalogue.get((brand.casefold(), model.casefold()))
        if product_id is None:
            raise ValueError(f"No indexed product for {brand} {model}")
        resolved[(brand, model)] = product_id
    return resolved


async def run_case(case: EvalCase, product_id: Any) -> dict[str, Any]:
    """Run one question through the full graph and grade it."""
    started = asyncio.get_running_loop().time()
    state = await answer_question(case.question, product_id=product_id)
    latency_ms = int((asyncio.get_running_loop().time() - started) * 1000)

    hits = state.get("hits") or []
    answer = state.get("answer") or ""

    # Retrieval is already scoped to the product, so pages alone identify the
    # right source: every chunk returned belongs to this appliance.
    retrieved = {page for hit in hits for page in range(hit.page_from, hit.page_to + 1)}
    expected = set(case.expected_pages)
    recall = bool(expected & retrieved) if expected else None

    verdict = await judge_answer(
        case.question, answer, case.expected_answer, case.answerable
    )

    # Cheap deterministic signal alongside the judge. When the two disagree,
    # the judge is usually being generous.
    lowered = answer.casefold()
    facts_found = [fact for fact in case.key_facts if fact.casefold() in lowered]

    return {
        "id": case.id,
        "question": case.question,
        "product": f"{case.brand} {case.model}",
        "answerable": case.answerable,
        "intent_expected": case.intent,
        "intent_actual": str(state.get("intent") or ""),
        "recall": recall,
        "correct": verdict.matches,
        "judge_reason": verdict.reason,
        "key_facts_found": f"{len(facts_found)}/{len(case.key_facts)}"
        if case.key_facts
        else None,
        "grounded": bool(state.get("grounded")),
        "escalated": bool(state.get("escalated", False)),
        "best_similarity": round(hits[0].similarity, 3) if hits else 0.0,
        "pages_retrieved": sorted(retrieved),
        "answer": answer,
        "latency_ms": latency_ms,
    }


def summarise(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate, keeping answerable and unanswerable apart.

    Mixing them hides the trade-off that matters: a system can look accurate by
    answering everything, including what it should decline.
    """
    answerable = [r for r in results if r["answerable"]]
    unanswerable = [r for r in results if not r["answerable"]]
    scored = [r for r in answerable if r["recall"] is not None]

    def ratio(items: list[Any], key: str) -> float | None:
        return (
            round(sum(bool(i[key]) for i in items) / len(items), 3) if items else None
        )

    return {
        "cases": len(results),
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
        f"recall@{TOP_K}": ratio(scored, "recall"),
        "correctness": ratio(answerable, "correct"),
        "abstention": ratio(unanswerable, "correct"),
        "escalation_rate": ratio(answerable, "escalated"),
        "median_latency_ms": sorted(r["latency_ms"] for r in results)[len(results) // 2]
        if results
        else None,
    }


async def run_all(cases: list[EvalCase] | None = None) -> dict[str, Any]:
    cases = cases or load_cases()
    products = await resolve_products(cases)

    results = []
    for index, case in enumerate(cases, start=1):
        logger.info("[%d/%d] %s", index, len(cases), case.id)
        results.append(await run_case(case, products[(case.brand, case.model)]))

    return {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "config": current_config(),
        "summary": summarise(results),
        "cases": results,
    }


def write_report(report: dict[str, Any]) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = report["run_at"].replace(":", "-")
    path = RESULTS_DIR / f"{stamp}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return path
