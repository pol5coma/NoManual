import asyncio
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from nomanual.core.config import get_settings
from nomanual.core.db import get_session
from nomanual.core.storage import compute_checksum, get_storage
from nomanual.models import PUBLIC_TENANT_ID, Manual, Product, manual_product
from nomanual.models.enums import ManualSource
from nomanual.schemas.manual import ManualOut

router = APIRouter(prefix="/manuals", tags=["manuals"])


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

    if file.size is not None and file.size > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes // (1024 * 1024)
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"The PDF exceeds the {limit_mb} MB limit.",
        )

    data = await file.read()
    checksum = compute_checksum(data)

    # Same file uploaded twice: reuse it instead of paying for embeddings again.
    existing = await session.scalar(
        select(Manual).where(
            Manual.tenant_id == PUBLIC_TENANT_ID, Manual.checksum == checksum
        )
    )
    if existing is not None:
        return existing

    brand, model = brand.strip(), model.strip()

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
    # TODO: queue ingestion here once the Celery task exists.
    return manual


@router.get("/{manual_id}", response_model=ManualOut)
async def get_manual(
    manual_id: UUID, session: AsyncSession = Depends(get_session)
) -> Manual:
    manual = await session.get(Manual, manual_id)
    if manual is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Manual not found.")
    return manual
