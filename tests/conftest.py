"""Shared test setup.

The integration tests run against a real PostgreSQL, not a mock. What they
check - the claim race, product scoping, tenant isolation - is enforced by SQL
and by pgvector, so a mocked session would only test that SQLAlchemy builds the
statement we asked for, never that the database behaves the way we think.

Three decisions worth knowing before reading anything else:

* A separate database, `nomanual_test`, created on the same server. Development
  data stays untouched, and a test can truncate whatever it likes.

* The schema is built with `alembic upgrade head`, not `create_all`. The
  migrations are part of what ships, including the one that seeds the public
  tenant, so they are part of what is tested.

* Tables are truncated between tests instead of wrapping each test in a
  transaction that gets rolled back. The claim race needs several connections
  that really commit and really see each other; inside one uncommitted
  transaction there is no race to observe.
"""

import asyncio
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_DB_NAME = "nomanual_test"

# --- Environment, before nomanual is imported anywhere ------------------------
#
# nomanual.core.db builds its engine at import time and searching/search.py uses
# that module-level SessionLocal directly, so pointing the tests at another
# database after the import would be too late. Environment variables win over
# the .env file in pydantic-settings, which is what makes this work.


def _with_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{name}"))


_dev_url = os.environ.get("DATABASE_URL")
if _dev_url is None:  # pragma: no cover - only when .env is read instead
    from dotenv import dotenv_values  # type: ignore[import-not-found]

    _dev_url = dotenv_values(PROJECT_ROOT / ".env")["DATABASE_URL"]

ADMIN_URL = _with_database(_dev_url, "postgres")
TEST_URL = _with_database(_dev_url, TEST_DB_NAME)

os.environ["DATABASE_URL"] = TEST_URL
# Uploaded files go to a throwaway directory: a test must never write into the
# real uploads/ folder.
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="nomanual-test-uploads-")
# No test is allowed to reach OpenAI. A placeholder satisfies the required
# setting; anything that would really call out is faked in the test itself.
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from nomanual.core.config import get_settings  # noqa: E402
from nomanual.core.db import SessionLocal, engine  # noqa: E402
from nomanual.models import (  # noqa: E402
    PUBLIC_TENANT_ID,
    Chunk,
    Manual,
    Product,
    Tenant,
    manual_product,
)
from nomanual.models.enums import ManualStatus, ProductType, TenantType  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

EMBEDDING_DIMENSIONS = get_settings().embedding_dimensions


# --- Database lifecycle -------------------------------------------------------


async def _recreate_database() -> None:
    """Drop and create nomanual_test from a connection to `postgres`.

    CREATE DATABASE cannot run inside a transaction, hence AUTOCOMMIT.
    """
    admin = create_async_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await conn.execute(
                text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)')
            )
            await conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    finally:
        await admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    """Build the test database once for the whole run.

    Deliberately a sync fixture: alembic's env.py calls asyncio.run() itself,
    which would explode inside an already running event loop.
    """
    from alembic import command
    from alembic.config import Config

    asyncio.run(_recreate_database())

    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.upgrade(config, "head")

    yield

    asyncio.run(engine.dispose())


# Truncated between tests. alembic_version is excluded because it describes the
# schema, and tenant because the public tenant is seeded by a migration -
# re-creating it here would duplicate that logic in test code.
_TABLES_TO_CLEAR = (
    "chunk",
    "manual_product",
    "manual",
    "query_log",
    "escalation",
    "indexed_page",
    "api_key",
    "client",
    "product",
)


@pytest.fixture(autouse=True)
async def clean_tables(database) -> None:
    """Leave every test an empty database, without touching the seed data."""
    async with SessionLocal() as session:
        await session.execute(
            text(f"TRUNCATE {', '.join(_TABLES_TO_CLEAR)} RESTART IDENTITY CASCADE")
        )
        # Tenants created by a test go; the seeded public one stays.
        await session.execute(
            text("DELETE FROM tenant WHERE id <> :public"),
            {"public": str(PUBLIC_TENANT_ID)},
        )
        await session.commit()
    yield


@pytest.fixture(autouse=True)
def fake_embeddings(monkeypatch) -> None:
    """No test ever calls OpenAI.

    Autouse on purpose: a forgotten patch would turn a test run into a bill and
    make the suite depend on the network.
    """
    from nomanual.searching import search

    async def _embed(text: str) -> list[float]:
        return vector(1.0)

    monkeypatch.setattr(search, "get_embeddings", _embed)


@pytest.fixture
async def session():
    """A session for the test body itself, separate from the app's."""
    async with SessionLocal() as session:
        yield session


@pytest.fixture
async def client():
    """HTTP client wired straight to the ASGI app, no network, no server."""
    from httpx import ASGITransport, AsyncClient
    from nomanual.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# --- Factories ----------------------------------------------------------------


def vector(seed: float) -> list[float]:
    """A deterministic embedding.

    Value on the first axis, zeros elsewhere: two vectors built with different
    seeds are far apart, and the same seed is identical. Enough to rank
    neighbours without calling an embedding model.
    """
    return [seed] + [0.0] * (EMBEDDING_DIMENSIONS - 1)


async def make_tenant(session, name: str = "Acme") -> Tenant:
    tenant = Tenant(
        name=name,
        slug=f"{name.lower()}-{uuid4().hex[:6]}",
        type=TenantType.MANUFACTURER,
    )
    session.add(tenant)
    await session.flush()
    return tenant


async def make_product(
    session,
    brand: str = "Haier",
    model: str = "AS09FBAHRA",
    tenant_id: UUID = PUBLIC_TENANT_ID,
) -> Product:
    product = Product(
        tenant_id=tenant_id,
        brand=brand,
        model=model,
        type=ProductType.OTHER,
        public_token=uuid4().hex[:22],
    )
    session.add(product)
    await session.flush()
    return product


async def make_manual(
    session,
    product: Product | None = None,
    tenant_id: UUID = PUBLIC_TENANT_ID,
    status: ManualStatus = ManualStatus.PENDING,
    checksum: str | None = None,
    **kwargs,
) -> Manual:
    manual = Manual(
        tenant_id=tenant_id,
        title=kwargs.pop("title", "Test manual"),
        storage_key=kwargs.pop("storage_key", f"{uuid4().hex}-manual.pdf"),
        checksum=checksum or uuid4().hex,
        status=status,
        **kwargs,
    )
    session.add(manual)
    await session.flush()

    if product is not None:
        await session.execute(
            manual_product.insert().values(manual_id=manual.id, product_id=product.id)
        )
    return manual


async def link(session, manual: Manual, product: Product) -> None:
    """Add a product to a manual that already exists: a family manual covers many."""
    await session.execute(
        manual_product.insert().values(manual_id=manual.id, product_id=product.id)
    )


async def make_chunk(
    session,
    manual: Manual,
    content: str = "Clean the air filter every two weeks.",
    seed: float = 1.0,
    applies_to: list[UUID] | None = None,
    **kwargs,
) -> Chunk:
    chunk = Chunk(
        manual_id=manual.id,
        tenant_id=manual.tenant_id,
        ordinal=kwargs.pop("ordinal", 0),
        page_from=kwargs.pop("page_from", 1),
        page_to=kwargs.pop("page_to", 1),
        language=kwargs.pop("language", "en"),
        content=content,
        embedding=vector(seed),
        applies_to=applies_to,
        **kwargs,
    )
    session.add(chunk)
    await session.flush()
    return chunk
