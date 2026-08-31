from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from nomanual.models.base import Base, TimestampMixin, UUIDMixin


class IndexedPage(UUIDMixin, TimestampMixin, Base):
    """An answered question turned into a public, indexable page.

    People searching "balay 3TS976BE error F03" on Google are our users at
    their moment of highest intent, and a chatbot has no page for Google to
    rank. This is the acquisition loop.
    """

    __tablename__ = "indexed_page"

    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("product.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    slug: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)

    # Nothing goes public without a human deciding it should.
    published: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
