from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from nomanual.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield one database session per request.

    FastAPI closes it automatically when the request ends, even on error.
    """
    async with SessionLocal() as session:
        yield session


@asynccontextmanager
async def worker_session() -> AsyncGenerator[AsyncSession, None]:
    """Database session for Celery tasks.

    Celery tasks run under their own short-lived event loop, so they cannot
    share the module-level engine: its pooled connections stay bound to the
    loop that opened them, and the second task would get a connection from a
    loop that no longer exists.

    NullPool opens a connection per use and closes it, which is the right
    trade-off here - ingesting a manual takes minutes, so the cost of a
    connection handshake is irrelevant.
    """
    worker_engine = create_async_engine(settings.database_url, poolclass=NullPool)
    factory = async_sessionmaker(
        worker_engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with factory() as session:
            yield session
    finally:
        await worker_engine.dispose()
