from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from nomanual.core.db import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    """Liveness check that actually touches the database.

    A /health returning a hardcoded {"status": "ok"} keeps lying after Postgres
    goes down, so it runs a real query.
    """
    await session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}
