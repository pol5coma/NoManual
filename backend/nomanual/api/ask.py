import logging
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nomanual.agent.graph import answer_question
from nomanual.conversations import service
from nomanual.core.db import get_session
from nomanual.models import PUBLIC_TENANT_ID, Conversation, Product, QueryLog
from nomanual.models.enums import QueryIntent
from nomanual.schemas.ask import AskRequest, AskResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ask", tags=["ask"])


async def _resolve_product(
    session: AsyncSession, item: AskRequest
) -> UUID | None:
    """The appliance this question is about, however the client named it."""
    if item.product_id is not None:
        return item.product_id

    if item.product_token:
        # The QR carries a token rather than an id, so it can be printed on the
        # appliance without exposing an internal identifier.
        product_id = await session.scalar(
            select(Product.id).where(Product.public_token == item.product_token)
        )
        if product_id is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown product token.")
        return product_id

    return None


async def _resume_or_start(
    session: AsyncSession, item: AskRequest, product_id: UUID | None
) -> Conversation:
    """Continue the thread the client named, or open a new one.

    A thread belongs to one appliance. Letting a client point an existing
    conversation at another product would mix a washing machine's history into
    an oven's retrieval, so that is a 409 rather than something to paper over.
    """
    if item.conversation_id is None:
        return await service.start(session, PUBLIC_TENANT_ID, product_id)

    conversation = await service.get(session, item.conversation_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found.")

    if product_id is not None and conversation.product_id != product_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This conversation is about another product. Start a new one.",
        )

    return conversation


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
    product_id = await _resolve_product(session, item)
    conversation = await _resume_or_start(session, item, product_id)
    product_id = product_id or conversation.product_id

    # What the graph needs to understand a follow-up: the recent turns as they
    # were said, and the notes covering everything older than the window.
    history = await service.history(session, conversation.id)

    started = time.perf_counter()
    state = await answer_question(
        item.question,
        product_id=product_id,
        history=history,
        summary=conversation.summary,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)

    citations = state.get("citations") or []
    intent = state.get("intent")
    stored_citations = [
        {"chunk_id": str(c.chunk_id), "page": c.page} for c in citations
    ]

    entry = QueryLog(
        conversation_id=conversation.id,
        question=item.question,
        # Lowercased and stripped so "Cada cuanto limpio el filtro" and "cada
        # cuánto limpio el filtro?" group together in the analytics.
        normalized_question=item.question.strip().casefold(),
        # The graph's Intent and the stored QueryIntent share their values, but
        # a routing label we have not modelled should not break the request.
        intent=QueryIntent(intent) if intent in set(QueryIntent) else None,
        answer=state.get("answer"),
        citations=stored_citations,
        # Resolved means grounded and not handed off: the metric a manufacturer
        # is actually buying.
        resolved=bool(state.get("grounded")) and not state.get("escalated", False),
        latency_ms=latency_ms,
    )
    session.add(entry)

    await service.append_turn(
        session,
        conversation,
        question=item.question,
        answer=state["answer"],
        citations=stored_citations,
    )
    # Only does anything once a thread outgrows its window, so short
    # conversations never pay for it.
    await service.maybe_summarise(session, conversation)

    await session.commit()
    await session.refresh(entry)

    return AskResponse(
        query_id=entry.id,
        conversation_id=conversation.id,
        question=item.question,
        answer=state["answer"],
        intent=intent,
        citations=citations,
        grounded=bool(state.get("grounded")),
        escalated=bool(state.get("escalated", False)),
    )
