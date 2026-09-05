import asyncio
import logging
from uuid import UUID

from nomanual.core.db import worker_session
from nomanual.models import Manual
from nomanual.models.enums import ManualStatus
from nomanual.worker import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="nomanual.ingest_manual")
def ingest_manual(manual_id: str) -> None:
    """Synchronous Celery entrypoint over the async pipeline."""
    asyncio.run(_ingest(UUID(manual_id)))


async def _ingest(manual_id: UUID) -> None:
    async with worker_session() as session:
        manual = await session.get(Manual, manual_id)
        if manual is None:
            logger.warning("Manual %s no longer exists, skipping", manual_id)
            return

        manual.status = ManualStatus.PROCESSING
        await session.commit()
        logger.info("Manual %s picked up for ingestion", manual_id)
