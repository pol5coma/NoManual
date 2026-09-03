"""seed public tenant

Revision ID: 7d56728e6ea1
Revises: aed387bc41ac
Create Date: 2026-09-01 12:48:12.193633

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7d56728e6ea1"
down_revision: str | Sequence[str] | None = "aed387bc41ac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PUBLIC_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    """Create the tenant that owns every user-uploaded manual."""
    op.execute(
        f"""
        INSERT INTO tenant (
            id, type, name, slug, verified, allows_official_retrieval,
            branding, plan, created_at, updated_at
        )
        VALUES (
            '{PUBLIC_TENANT_ID}', 'public', 'Public catalogue', 'public',
            false, false, '{{}}', 'free', now(), now()
        )
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM tenant WHERE id = '{PUBLIC_TENANT_ID}'")
