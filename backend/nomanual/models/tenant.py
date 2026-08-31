from typing import Any

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nomanual.models._types import sa_enum
from nomanual.models.base import Base, TimestampMixin, UUIDMixin
from nomanual.models.enums import TenantType


class Tenant(UUIDMixin, TimestampMixin, Base):
    """An isolation boundary: one manufacturer, or the public catalogue.

    Everything else in the schema hangs off a tenant, and every retrieval query
    filters by it. A Bosch manual must never surface in Balay's chat.
    """

    __tablename__ = "tenant"

    type: Mapped[TenantType] = mapped_column(
        sa_enum(TenantType, "tenant_type"),
        default=TenantType.MANUFACTURER,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(255))
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Whether we are allowed to fetch their documentation from official public
    # channels. Off by default: consent is opt-in, never assumed.
    allows_official_retrieval: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # Logo, colours and tone of voice for the white-label chat. Config, never a
    # per-client fork.
    branding: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )

    # Not enforced in the MVP; modelled so billing can land without a migration.
    plan: Mapped[str] = mapped_column(String(40), default="free", nullable=False)
    monthly_query_limit: Mapped[int | None] = mapped_column(Integer)
