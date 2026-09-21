"""The ingestion claim, under concurrency.

Ingesting a manual costs minutes of work and real money in embeddings, so it
must happen exactly once even if the upload endpoint, the explicit /ingest call
and a retry all fire at the same moment. The guarantee is not in Python: it is
a single conditional UPDATE that PostgreSQL serialises on the row.

That is why these tests use several sessions committing for real. With one
shared session, or inside a transaction that never commits, there is no race
left to test.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from conftest import make_manual
from nomanual.api import manuals as manuals_api
from nomanual.core.config import get_settings
from nomanual.core.db import SessionLocal
from nomanual.models import Manual
from nomanual.models.enums import ManualStatus
from sqlalchemy import func, select


@pytest.fixture
def queued(monkeypatch) -> list[str]:
    """Record what would have been sent to Celery instead of sending it."""
    sent: list[str] = []
    monkeypatch.setattr(
        manuals_api, "_queue_ingestion", lambda manual_id: sent.append(str(manual_id))
    )
    return sent


async def _claim(manual_id) -> bool:
    """One claim on its own session, the way a separate request would run."""
    async with SessionLocal() as session:
        return await manuals_api.claim_and_queue(session, manual_id)


async def test_only_one_of_five_concurrent_claims_wins(session, queued):
    manual = await make_manual(session)
    await session.commit()

    results = await asyncio.gather(*(_claim(manual.id) for _ in range(5)))

    assert results.count(True) == 1
    assert len(queued) == 1

    await session.refresh(manual)
    assert manual.status == ManualStatus.PROCESSING
    assert manual.processing_started_at is not None


async def test_ready_manual_is_not_reclaimed(session, queued):
    manual = await make_manual(session, status=ManualStatus.READY)
    await session.commit()

    assert await _claim(manual.id) is False
    assert queued == []

    await session.refresh(manual)
    assert manual.status == ManualStatus.READY


async def test_live_processing_is_not_stolen(session, queued):
    manual = await make_manual(
        session,
        status=ManualStatus.PROCESSING,
        processing_started_at=datetime.now(UTC),
    )
    await session.commit()

    assert await _claim(manual.id) is False
    assert queued == []


async def test_stale_processing_is_reclaimed(session, queued):
    """A worker that died leaves its manual stuck in `processing` forever."""
    stale_seconds = get_settings().ingestion_stale_after_seconds
    manual = await make_manual(
        session,
        status=ManualStatus.PROCESSING,
        processing_started_at=datetime.now(UTC) - timedelta(seconds=stale_seconds + 60),
    )
    await session.commit()

    assert await _claim(manual.id) is True
    assert queued == [str(manual.id)]


async def test_failed_manual_can_be_retried_and_error_is_cleared(session, queued):
    manual = await make_manual(
        session, status=ManualStatus.FAILED, error="The PDF has no extractable text."
    )
    await session.commit()

    assert await _claim(manual.id) is True

    await session.refresh(manual)
    assert manual.status == ManualStatus.PROCESSING
    assert manual.error is None


async def test_claim_on_unknown_manual_does_nothing(session, queued):
    assert await _claim(uuid4()) is False
    assert queued == []
    assert await session.scalar(select(func.count()).select_from(Manual)) == 0
