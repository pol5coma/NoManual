from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from nomanual.models._types import sa_enum
from nomanual.models.base import Base, TimestampMixin, UUIDMixin
from nomanual.models.enums import QueryIntent


class QueryLog(UUIDMixin, TimestampMixin, Base):
    """Every question asked, and what we answered.

    This is not an audit table, it is the B2B product: which features confuse
    people, which models generate the most queries, and above all which
    questions we could not answer - a map of the holes in the manufacturer's
    own documentation.
    """

    __tablename__ = "query_log"

    # SET NULL rather than CASCADE: deleting a product must not erase the
    # historical record of what people asked about it.
    tenant_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenant.id", ondelete="SET NULL"), index=True
    )
    product_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("product.id", ondelete="SET NULL"), index=True
    )
    manual_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("manual.id", ondelete="SET NULL")
    )
    client_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("client.id", ondelete="SET NULL")
    )
    session_id: Mapped[str | None] = mapped_column(String(64), index=True)

    question: Mapped[str] = mapped_column(Text, nullable=False)

    # Lowercased and stripped of model references, so "how do I delay the start"
    # and "how to start it later" collapse into one row in the analytics.
    normalized_question: Mapped[str | None] = mapped_column(Text, index=True)

    language: Mapped[str | None] = mapped_column(String(8))
    intent: Mapped[QueryIntent | None] = mapped_column(
        sa_enum(QueryIntent, "query_intent"), index=True
    )

    answer: Mapped[str | None] = mapped_column(Text)

    # [{"chunk_id": ..., "page": 34, "snippet": "..."}]
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )

    # Did we produce a grounded answer? NULL while still being processed.
    # This is the metric the manufacturer is actually buying.
    resolved: Mapped[bool | None] = mapped_column(Boolean, index=True)

    feedback: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    token_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
