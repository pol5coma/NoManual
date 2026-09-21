"""Listing, reading and deleting conversations.

Threads are created by /ask, never here: a conversation with no question in it
would be an empty row waiting for someone to garbage-collect it. What this
router does is list them, read one back so the browser can rebuild the chat
after a reload, and delete one.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from nomanual.conversations import service
from nomanual.core.db import get_session
from nomanual.schemas.conversation import (
    ConversationSchema,
    ConversationSummarySchema,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationSummarySchema])
async def list_conversations(
    product_id: UUID = Query(..., description="The appliance whose threads to list."),
    session: AsyncSession = Depends(get_session),
) -> list[ConversationSummarySchema]:
    """Threads about one appliance, most recently active first.

    product_id is required rather than optional: a conversation belongs to an
    appliance, and a list of every thread in the catalogue is not a screen this
    application has.
    """
    rows = await service.list_for_product(session, product_id)

    return [
        ConversationSummarySchema(
            id=conversation.id,
            title=conversation.title,
            created_at=conversation.created_at,
            last_message_at=last_message_at,
            message_count=message_count,
        )
        for conversation, message_count, last_message_at in rows
    ]


@router.get("/{conversation_id}", response_model=ConversationSchema)
async def get_conversation(
    conversation_id: UUID, session: AsyncSession = Depends(get_session)
) -> ConversationSchema:
    """Every message of a thread, oldest first."""
    conversation = await service.get(session, conversation_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found.")

    messages = await service.all_messages(session, conversation_id)

    return ConversationSchema(
        id=conversation.id,
        title=conversation.title,
        product_id=conversation.product_id,
        created_at=conversation.created_at,
        messages=messages,
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID, session: AsyncSession = Depends(get_session)
) -> None:
    """Delete a thread and everything said in it."""
    conversation = await service.get(session, conversation_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found.")

    await service.delete(session, conversation)
    await session.commit()
