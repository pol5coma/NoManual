from contextlib import asynccontextmanager

from fastapi import FastAPI

from nomanual.api import health
from nomanual.core.db import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Close the pool cleanly on shutdown, otherwise asyncpg logs warnings about
    # connections destroyed while still open.
    await engine.dispose()


app = FastAPI(
    title="NoManual API",
    description="Ask product manuals in plain language.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
