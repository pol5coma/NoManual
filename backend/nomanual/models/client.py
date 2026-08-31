from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from nomanual.models.base import Base, TimestampMixin, UUIDMixin


class Client(UUIDMixin, TimestampMixin, Base):
    """An end user.

    The MVP only creates anonymous clients keyed by session. Every account
    field is present but nullable, so adding real sign-up later is code, not a
    migration.
    """

    __tablename__ = "client"

    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    email: Mapped[str | None] = mapped_column(String(255), unique=True)

    # Hashed with argon2, never encrypted: encryption is reversible and that is
    # exactly what a password store must not be.
    password_hash: Mapped[str | None] = mapped_column(String(255))

    country: Mapped[str | None] = mapped_column(String(2))

    # An IP address is personal data under GDPR. We keep a salted hash, which
    # is enough for abuse detection and rate limiting.
    ip_hash: Mapped[str | None] = mapped_column(String(64))
