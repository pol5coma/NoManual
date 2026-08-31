from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from nomanual.models._types import sa_enum
from nomanual.models.base import Base, TimestampMixin, UUIDMixin
from nomanual.models.enums import EscalationReason, EscalationStatus


class Escalation(UUIDMixin, TimestampMixin, Base):
    """Hand-off to the manufacturer's support team.

    Knowing when to stop answering is part of the product: a safety question or
    a gap in the documentation should reach a human, not get a confident guess.
    """

    __tablename__ = "escalation"

    query_log_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("query_log.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    reason: Mapped[EscalationReason] = mapped_column(
        sa_enum(EscalationReason, "escalation_reason"), nullable=False
    )
    status: Mapped[EscalationStatus] = mapped_column(
        sa_enum(EscalationStatus, "escalation_status"),
        default=EscalationStatus.OPEN,
        nullable=False,
        index=True,
    )

    # Whatever the user chose to share so support can reach them back.
    contact_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
