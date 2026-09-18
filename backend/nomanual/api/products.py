from collections.abc import Sequence
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nomanual.core.db import get_session
from nomanual.models import PUBLIC_TENANT_ID
from nomanual.models.product import Product
from nomanual.schemas.product import ProductSchema

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductSchema])
async def list_products(
    # A limit does not identify a resource, so it is a query parameter rather
    # than part of the path. It also kept colliding with /{product_id}, since
    # both would match /products/<something>.
    limit: int | None = Query(None, le=500, description="Omit to return all."),
    session: AsyncSession = Depends(get_session),
) -> Sequence[Product]:
    """Products the user can ask about.

    Returns everything by default because this populates a picker. That holds
    while the catalogue is small; with thousands of models the picker becomes
    a search box and this grows a `search` parameter instead.
    """
    result = await session.scalars(
        select(Product)
        .where(Product.tenant_id == PUBLIC_TENANT_ID)
        .order_by(Product.brand, Product.model)
        .limit(limit)
    )
    return result.all()


@router.get("/{product_id}", response_model=ProductSchema)
async def get_product(
    product_id: UUID, session: AsyncSession = Depends(get_session)
) -> Product:
    product = await session.scalar(
        select(Product).where(
            Product.id == product_id, Product.tenant_id == PUBLIC_TENANT_ID
        )
    )
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found.")
    return product
