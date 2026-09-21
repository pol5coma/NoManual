"""A tenant never sees, reuses or deletes another tenant's data.

Today everything runs under the public tenant, so none of this is reachable
from outside yet. That is exactly why it is worth pinning now: these queries
are written once and then trusted forever, and the day authentication lands the
boundary has to already hold.
"""

import hashlib
from uuid import UUID

from conftest import make_manual, make_product, make_tenant
from sqlalchemy import func, select

from nomanual.models import PUBLIC_TENANT_ID, Manual
from nomanual.models.enums import ManualStatus


async def test_upload_does_not_reuse_another_tenants_file(session, client, monkeypatch):
    """Deduplication by checksum stops at the tenant boundary.

    The same PDF uploaded by a manufacturer and by a user is two manuals, not
    one: reusing the row would hand a private document to the public catalogue.
    """
    from nomanual.api import manuals as manuals_api

    monkeypatch.setattr(manuals_api, "_queue_ingestion", lambda manual_id: None)

    pdf = b"%PDF-1.4 the same bytes"
    other = await make_tenant(session, name="Bosch")
    product = await make_product(session, tenant_id=other.id)
    await make_manual(
        session,
        product=product,
        tenant_id=other.id,
        checksum=hashlib.sha256(pdf).hexdigest(),
    )
    await session.commit()

    response = await client.post(
        "/manuals/upload",
        data={"brand": "Haier", "model": "AS09FBAHRA"},
        files={"file": ("manual.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 202

    # Two rows for the same bytes: one per tenant.
    manuals = await session.scalar(select(func.count()).select_from(Manual))
    assert manuals == 2

    stored = await session.get(Manual, UUID(response.json()["id"]))
    assert stored.tenant_id == PUBLIC_TENANT_ID


async def test_listing_only_returns_the_public_catalogue(session, client):
    other = await make_tenant(session, name="Bosch")
    await make_manual(session, tenant_id=other.id, title="Private manual")
    await make_manual(session, title="Public manual")
    await session.commit()

    response = await client.get("/manuals")

    titles = [manual["title"] for manual in response.json()]
    assert titles == ["Public manual"]


async def test_another_tenants_manual_cannot_be_deleted(session, client):
    """The tenant comes from the server, so this row is simply not visible."""
    other = await make_tenant(session, name="Bosch")
    manual = await make_manual(
        session, tenant_id=other.id, status=ManualStatus.READY
    )
    await session.commit()

    response = await client.delete(f"/manuals/{manual.id}")

    assert response.status_code == 404
    assert await session.get(Manual, manual.id) is not None


async def test_delete_removes_manual_chunks_and_file(session, client, tmp_path):
    from conftest import make_chunk

    from nomanual.core.storage import get_storage
    from nomanual.models import Chunk

    manual = await make_manual(session, status=ManualStatus.READY)
    await make_chunk(session, manual)
    await session.commit()

    # A real file to remove, stored under the key the manual points at.
    storage = get_storage()
    key = storage.save(b"%PDF-1.4 bytes", "manual.pdf")
    manual.storage_key = key
    await session.commit()

    response = await client.delete(f"/manuals/{manual.id}")

    assert response.status_code == 204
    # The test session still holds the row it created, so ask the database.
    session.expire_all()
    assert await session.scalar(select(func.count()).select_from(Manual)) == 0
    # ON DELETE CASCADE, checked against the database rather than assumed.
    assert await session.scalar(select(func.count()).select_from(Chunk)) == 0
    assert key not in storage.list_keys()


async def test_a_manual_being_processed_cannot_be_deleted(session, client):
    manual = await make_manual(session, status=ManualStatus.PROCESSING)
    await session.commit()

    response = await client.delete(f"/manuals/{manual.id}")

    assert response.status_code == 409
    assert await session.get(Manual, manual.id) is not None
