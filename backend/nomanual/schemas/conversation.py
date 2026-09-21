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


class ConversationSchema(BaseModel):
    """A thread and everything said in it, for rebuilding the chat on reload."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID | None
    created_at: datetime
    messages: list[MessageSchema]
