import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import and_, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from nomanual.core.config import get_settings
from nomanual.core.db import get_session
from nomanual.core.storage import compute_checksum, get_storage
from nomanual.models import PUBLIC_TENANT_ID, Manual, Product, manual_product
from nomanual.models.enums import ManualSource, ManualStatus
from nomanual.schemas.manual import ManualOut

router = APIRouter(prefix="/manuals", tags=["manuals"])

# States from which an ingestion may start. READY is excluded: its chunks are
# already there. PROCESSING is handled separately, since a stale one is fair game.
REQUEUEABLE = (ManualStatus.PENDING, ManualStatus.FAILED)

CONFLICT_REASON = {
    ManualStatus.READY: (
        "This manual has already been processed and indexed successfully (ready)."
    ),
    ManualStatus.PROCESSING: (
        "This manual is being processed right now. Wait for it to finish."
    ),
}


async def _get_or_create_product(
    session: AsyncSession, brand: str, model: str
) -> Product:
    """Find the product for this brand and model, creating it if needed.

    Brand and model are matched case-insensitively with ilike(), so "balay"
    and "Balay" do not end up as two products with two separate libraries.
    """
    product = await session.scalar(
        select(Product).where(
            Product.tenant_id == PUBLIC_TENANT_ID,
            Product.brand.ilike(brand),
            Product.model.ilike(model),
        )
    )
    if product is None:
        product = Product(
            tenant_id=PUBLIC_TENANT_ID,
            brand=brand,
            model=model,
            public_token=uuid4().hex[:22],
        )
        session.add(product)
        # We need product.id to link the manual, and ids are only assigned once
        # the INSERT reaches the database.
        await session.flush()
    return product


def _queue_ingestion(manual_id: UUID) -> None:
    # Local import: breaks the api -> tasks -> models -> api import cycle.
    from nomanual.ingestion.tasks import ingest_manual

    ingest_manual.delay(str(manual_id))


async def claim_and_queue(session: AsyncSession, manual_id: UUID) -> bool:
    """Claim a manual for ingestion and queue it. True if we won the claim.

    The claim is a single conditional UPDATE, which is what makes concurrent
    calls safe: Postgres locks the row while it runs, so a second request only
    sees the row once the status is already `processing` and its WHERE no
    longer matches. rowcount tells us who won.

    The same statement also reclaims manuals whose worker died: a `processing`
    older than the stale threshold is treated as abandoned.
    """
    settings = get_settings()
    stale_before = datetime.now(UTC) - timedelta(
        seconds=settings.ingestion_stale_after_seconds
    )

    result = await session.execute(
        update(Manual)
        .where(
            Manual.id == manual_id,
            or_(
                Manual.status.in_(REQUEUEABLE),
                and_(
                    Manual.status == ManualStatus.PROCESSING,
                    or_(
                        # NULL means it was claimed before this column existed,
                        # so there is no evidence anyone is still working on it.
                        Manual.processing_started_at.is_(None),
                        Manual.processing_started_at < stale_before,
                    ),
                ),
            ),
        )
        .values(
            status=ManualStatus.PROCESSING,
            processing_started_at=func.now(),
            error=None,
        )
    )
    await session.commit()

    if result.rowcount != 1:
        return False

    _queue_ingestion(manual_id)
    return True


@router.post("/upload", response_model=ManualOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_manual(
    brand: str = Form(..., min_length=1, max_length=120),
    model: str = Form(..., min_length=1, max_length=160),
    title: str | None = Form(None),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> Manual:
    """Accept a PDF and queue it for ingestion.

    Returns 202: the manual is stored as `pending` and processed in the
    background. Poll GET /manuals/{id} to see it reach `ready`.
    """
    settings = get_settings()

    if file.content_type != "application/pdf":
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Only PDF files are accepted. Convert the manual and try again.",
        )

    # Cheap up-front rejection from Content-Length, before reading the body.
    if file.size is not None and file.size > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes // (1024 * 1024)
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"The PDF exceeds the {limit_mb} MB limit.",
        )

    data = await file.read()

    # Content-Length is client-supplied and can lie, so the real check happens
    # against the bytes we actually received.
    if len(data) > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes // (1024 * 1024)
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"The PDF exceeds the {limit_mb} MB limit.",
        )

    checksum = compute_checksum(data)
    brand, model = brand.strip(), model.strip()

    existing = await session.scalar(
        select(Manual).where(
            Manual.tenant_id == PUBLIC_TENANT_ID, Manual.checksum == checksum
        )
    )
    if existing is not None:
        # Same file we already stored, but possibly for a different model: a
        # family manual legitimately covers several. Link the product and skip
        # paying for the embeddings a second time.
        product = await _get_or_create_product(session, brand, model)
        await session.execute(
            pg_insert(manual_product)
            .values(manual_id=existing.id, product_id=product.id)
            .on_conflict_do_nothing()
        )
        await session.commit()

        # An earlier upload may have died before its chunks were produced. The
        # claim decides: if it is already ready or genuinely running, nothing
        # happens and we just return what we have.
        await claim_and_queue(session, existing.id)
        await session.refresh(existing)
        return existing

    product = await _get_or_create_product(session, brand, model)

    key = await asyncio.to_thread(
        get_storage().save, data, file.filename or "manual.pdf"
    )

    manual = Manual(
        tenant_id=PUBLIC_TENANT_ID,
        title=title or f"{brand} {model}",
        source=ManualSource.USER_UPLOAD,
        storage_key=key,
        checksum=checksum,
    )
    session.add(manual)
    await session.flush()

    # Written directly to the association table: Manual.products is lazy="raise",
    # and going through the relationship would trigger a load we do not need.
    await session.execute(
        insert(manual_product).values(manual_id=manual.id, product_id=product.id)
    )

    await session.commit()

    # Same path as the explicit endpoint, so a manual only ever reaches
    # `processing` one way.
    await claim_and_queue(session, manual.id)
    await session.refresh(manual)
    return manual


@router.get("/{manual_id}", response_model=ManualOut)
async def get_manual(
    manual_id: UUID, session: AsyncSession = Depends(get_session)
) -> Manual:

    # TODO: REDIS -> check if that manual have been requested recently.

    manual = await session.get(Manual, manual_id)
    if manual is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Manual not found.")
    return manual


@router.post(
    "/{manual_id}/ingest",
    response_model=ManualOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_manual_now(
    manual_id: UUID, session: AsyncSession = Depends(get_session)
) -> Manual:
    """Queue ingestion for a manual that has not been indexed yet.

    Only manuals in `pending` or `failed` are eligible, plus any left in
    `processing` by a worker that died. Anything else returns 409.
    """
    manual = await session.get(Manual, manual_id)
    if manual is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Manual not found.")

    claimed = await claim_and_queue(session, manual_id)
    await session.refresh(manual)

    if not claimed:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            CONFLICT_REASON.get(
                manual.status,
                f"This manual cannot be ingested from its current state "
                f"({manual.status.value}).",
            ),
        )

    return manual


@router.get("", response_model=list[ManualOut])
async def list_manuals(
    session: AsyncSession = Depends(get_session),
) -> Sequence[Manual]:
    result = await session.scalars(
        select(Manual)
        .where(Manual.tenant_id == PUBLIC_TENANT_ID)
        .order_by(Manual.created_at.desc())
        .limit(50)
    )
    return result.all()
