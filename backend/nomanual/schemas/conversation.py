"""What a conversation looks like over HTTP."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MessageSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: str
    content: str
    # Same shape the answer returns: [{"chunk_id": ..., "page": 34}]
    citations: list[dict[str, Any]]
    created_at: datetime


class ConversationSummarySchema(BaseModel):
    """A row in the sidebar: enough to recognise a thread, nothing more."""

    id: UUID
    title: str | None
    created_at: datetime
    last_message_at: datetime | None
    message_count: int


class ConversationSchema(BaseModel):
    """A thread and everything said in it, for rebuilding the chat on reload."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str | None
    product_id: UUID | None
    created_at: datetime
    messages: list[MessageSchema]
