from uuid import UUID

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from nomanual.models._types import sa_enum
from nomanual.models.base import Base, TimestampMixin, UUIDMixin
from nomanual.models.enums import ProductType


class Product(UUIDMixin, TimestampMixin, Base):
    """A specific commercial model, never a product family.

    Families are expressed through the manual <-> product association: one
    manual covering twelve models links to twelve rows here.
    """

    __tablename__ = "product"
    __table_args__ = (
        UniqueConstraint("tenant_id", "brand", "model", name="uq_product_identity"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tenant.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    brand: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    type: Mapped[ProductType] = mapped_column(
        sa_enum(ProductType, "product_type"),
        default=ProductType.OTHER,
        nullable=False,
        index=True,
    )

    # What the QR code encodes. Resolving it gives the chat both the tenant and
    # the exact model, so the user never has to type a reference.
    public_token: Mapped[str] = mapped_column(
        String(22), unique=True, nullable=False, index=True
    )
