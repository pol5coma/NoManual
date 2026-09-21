"""Reading a conversation back.

Threads are created by /ask, never here: a conversation with no question in it
would be an empty row waiting for someone to garbage-collect it. This router
only reads, so the browser can rebuild the chat after a reload.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from nomanual.conversations import service
from nomanual.core.db import get_session
from nomanual.schemas.conversation import ConversationSchema

router = APIRouter(prefix="/conversations", tags=["conversations"])


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
        product_id=conversation.product_id,
        created_at=conversation.created_at,
        messages=messages,
    )
