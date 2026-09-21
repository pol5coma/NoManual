from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from nomanual.models._types import sa_enum
from nomanual.models.base import Base, TimestampMixin, UUIDMixin
from nomanual.models.enums import MessageRole


class Conversation(UUIDMixin, TimestampMixin, Base):
    """A thread of messages about one appliance.

    Bound to a product, not just started from one: retrieval is scoped to the
    product, so carrying a thread across appliances would mean the summary
    talks about a washing machine while the search only sees an oven. Picking
    another product starts another conversation.
    """

    __tablename__ = "conversation"

    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # SET NULL rather than CASCADE: deleting a product from the catalogue must
    # not erase what people asked about it.
    product_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("product.id", ondelete="SET NULL"), index=True
    )

    # Taken from the first question, trimmed. Enough to recognise a thread in
    # a list, and free: a generated title would cost a model call per
    # conversation to say roughly what the question already says.
    title: Mapped[str | None] = mapped_column(String(120))

    # Running state of the conversation, not prose:
    #
    #   {"goal": ..., "tried": [...], "outcome": ..., "facts": [...]}
    #
    # Structured because it is read by two very different consumers. The model
    # gets fields it cannot wander away from, and a human can see at a glance
    # where a conversation stands - which is exactly what a support dashboard
    # would show.
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # How many messages the summary already covers. The rest are sent verbatim,
    # so nothing is summarised twice and nothing falls between the two.
    summarised_through: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )


class Message(UUIDMixin, TimestampMixin, Base):
    """One turn, from the user or from the assistant."""

    __tablename__ = "message"
    __table_args__ = (
        # Every read is "the last messages of this conversation, in order".
        Index("ix_message_conversation_ordinal", "conversation_id", "ordinal"),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("conversation.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Position in the thread. created_at would almost always work, but two
    # messages written in the same transaction can share a timestamp, and the
    # order of a conversation is not something to leave to a tie-break.
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    role: Mapped[MessageRole] = mapped_column(
        sa_enum(MessageRole, "message_role"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Same shape as query_log.citations: [{"chunk_id": ..., "page": 34}]. Kept
    # on the message so reloading a conversation shows the sources again, not
    # a bare wall of text.
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )
