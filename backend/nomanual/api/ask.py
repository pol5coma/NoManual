import logging
import time

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nomanual.agent.graph import answer_question
from nomanual.core.db import get_session
from nomanual.models import Product, QueryLog
from nomanual.models.enums import QueryIntent
from nomanual.schemas.ask import AskRequest, AskResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ask", tags=["ask"])


@router.post("", response_model=AskResponse)
async def ask(
    item: AskRequest, session: AsyncSession = Depends(get_session)
) -> AskResponse:
    """Answer a question from the indexed manuals.

    Every question is recorded, answered or not. That log is the analytics
    product for manufacturers - which features confuse people, which questions
    their documentation does not cover - so the unanswered ones matter as much
    as the rest.
    """
    product_id = item.product_id
    if product_id is None and item.product_token:
        # The QR carries a token rather than an id, so it can be printed on the
        # appliance without exposing an internal identifier.
        product_id = await session.scalar(
            select(Product.id).where(Product.public_token == item.product_token)
        )

    started = time.perf_counter()
    state = await answer_question(item.question, product_id=product_id)
    latency_ms = int((time.perf_counter() - started) * 1000)

    citations = state.get("citations") or []
    intent = state.get("intent")

    entry = QueryLog(
        question=item.question,
        # Lowercased and stripped so "Cada cuanto limpio el filtro" and "cada
        # cuánto limpio el filtro?" group together in the analytics.
        normalized_question=item.question.strip().casefold(),
        # The graph's Intent and the stored QueryIntent share their values, but
        # a routing label we have not modelled should not break the request.
        intent=QueryIntent(intent) if intent in set(QueryIntent) else None,
        answer=state.get("answer"),
        citations=[{"chunk_id": str(c.chunk_id), "page": c.page} for c in citations],
        # Resolved means grounded and not handed off: the metric a manufacturer
        # is actually buying.
        resolved=bool(state.get("grounded")) and not state.get("escalated", False),
        latency_ms=latency_ms,
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)

    return AskResponse(
        query_id=entry.id,
        question=item.question,
        answer=state["answer"],
        intent=intent,
        citations=citations,
        grounded=bool(state.get("grounded")),
        escalated=bool(state.get("escalated", False)),
    )
