from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nomanual.models._types import sa_enum
from nomanual.models.base import Base, TimestampMixin, UUIDMixin
from nomanual.models.enums import ManualSource, ManualStatus
from nomanual.models.product import Product

# A family manual covers many models, and a model can have several documents
# (user guide, installation sheet, error code addendum). Hence many-to-many.
manual_product = Table(
    "manual_product",
    Base.metadata,
    Column(
        "manual_id",
        PgUUID(as_uuid=True),
        ForeignKey("manual.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "product_id",
        PgUUID(as_uuid=True),
        ForeignKey("product.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Manual(UUIDMixin, TimestampMixin, Base):
    """A source document plus the state of its ingestion."""

    __tablename__ = "manual"

    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[ManualSource] = mapped_column(
        sa_enum(ManualSource, "manual_source"),
        default=ManualSource.USER_UPLOAD,
        nullable=False,
    )

    # Manufacturers reissue manuals when firmware changes the button sequence,
    # so answers have to be traceable to a specific revision.
    revision: Mapped[str | None] = mapped_column(String(40))
    published_at: Mapped[date | None] = mapped_column(Date)

    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)

    # sha256 of the file: lets us recognise a re-upload of something we already
    # ingested instead of paying for the embeddings twice.
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    status: Mapped[ManualStatus] = mapped_column(
        sa_enum(ManualStatus, "manual_status"),
        default=ManualStatus.PENDING,
        nullable=False,
        index=True,
    )
    # Set when a worker claims the manual. Lets us tell a live ingestion
    # from one whose worker died, which `updated_at` cannot do because it
    # moves on every write.
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    error: Mapped[str | None] = mapped_column(Text)

    # What the pipeline did, step by step:
    #
    #   [{"step": "extract", "status": "done", "duration_ms": 1430,
    #     "detail": {"pages": 130, "backend": "pymupdf"}}, ...]
    #
    # Written as the worker goes, in short transactions of its own, so the API
    # can show an ingestion in progress. It lives in the row rather than in a
    # websocket because the state has to survive a reload, a redeploy and a
    # worker restart - and because a manual ingested last week is still worth
    # being able to explain.
    progress: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )
    page_count: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int | None] = mapped_column(Integer)

    # lazy="raise" makes an accidental lazy load fail loudly instead of blowing
    # up with MissingGreenlet deep inside async code. Load it explicitly with
    # selectinload() when you actually need it.
    products: Mapped[list[Product]] = relationship(
        secondary=manual_product, lazy="raise"
    )
