import asyncio
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from nomanual.core.config import get_settings
from nomanual.core.db import get_session
from nomanual.core.storage import compute_checksum, get_storage
from nomanual.models import PUBLIC_TENANT_ID, Manual, Product, manual_product
from nomanual.models.enums import ManualSource, ManualStatus
from nomanual.schemas.manual import ManualOut

router = APIRouter(prefix="/manuals", tags=["manuals"])

# A manual is only worth re-queueing when no successful ingestion produced its
# chunks. PROCESSING is excluded on purpose: a worker already has it.
REQUEUEABLE = (ManualStatus.PENDING, ManualStatus.FAILED)


async def _get_or_create_product(
    session: AsyncSession, brand: str, model: str
) -> Product:
    """Find the product for this brand and model, creating it if needed.

    Brand and model are matched case-insensitively so "balay" and "Balay" do
    not end up as two products with two separate manual libraries.
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


@router.post("", response_model=ManualOut, status_code=status.HTTP_202_ACCEPTED)
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

        # An earlier upload may have died before its chunks were produced.
        if existing.status in REQUEUEABLE:
            _queue_ingestion(existing.id)

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
    _queue_ingestion(manual.id)

    return manual


@router.get("/{manual_id}", response_model=ManualOut)
async def get_manual(
    manual_id: UUID, session: AsyncSession = Depends(get_session)
) -> Manual:

    # TODO: REDIS -> check if that manual have been requested recently.

    manual = await session.get(Manual, manual_id)
    if manual is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Manual not found.")
    return manual

@router.get("",response_model=list[ManualOut])
async def get(session: AsyncSession = Depends(get_session)) -> list[Manual]:
    return await session.scalars(select(Manual).limit(50))