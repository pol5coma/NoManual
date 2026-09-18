from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nomanual.api import ask, debug, health, manuals, products, search
from nomanual.core.config import get_settings
from nomanual.core.db import engine
from nomanual.mcp_server import mcp

# The MCP transport keeps its own session manager, and Starlette does not run
# a mounted sub-app's lifespan. Without chaining it here the endpoint mounts
# fine and then 500s on the first request.
mcp_app = mcp.streamable_http_app(streamable_http_path="/")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp_app.router.lifespan_context(mcp_app):
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

# The frontend is a separate origin in development, so the browser needs
# the API to opt in explicitly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(manuals.router)
app.include_router(search.router)
app.include_router(ask.router)
app.include_router(products.router)


# Mounted on the same app on purpose: the MCP tools call the same
# functions the HTTP endpoints do, and one process keeps their logs
# together while developing.
app.mount("/mcp", mcp_app)

if get_settings().debug_endpoints:
    app.include_router(debug.router)
