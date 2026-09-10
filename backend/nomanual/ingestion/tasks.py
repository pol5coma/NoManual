import asyncio
import logging
from uuid import UUID

from sqlalchemy import delete

from nomanual.core.config import get_settings
from nomanual.core.db import worker_session
from nomanual.core.storage import get_storage
from nomanual.ingestion.chunker import chunk_pages
from nomanual.ingestion.embeddings import embed_texts
from nomanual.ingestion.extract import extract_pages
from nomanual.models import Chunk, Manual
from nomanual.models.enums import ManualStatus
from nomanual.worker import celery_app

logger = logging.getLogger(__name__)
settings = get_settings()

SCANNED_PDF_MESSAGE = (
    "This PDF has no extractable text. It looks scanned and would need OCR."
)
MAX_ERROR_CHARS = 2000


@celery_app.task(name="nomanual.ingest_manual")
def ingest_manual(manual_id: str) -> None:
    """Synchronous Celery entrypoint over the async pipeline.

    Queued automatically when a user uploads a manual, or by hand through
    POST /manuals/{id}/ingest.
    """
    asyncio.run(_ingest(UUID(manual_id)))


async def _mark_failed(manual_id: UUID, message: str) -> None:
    """Record why an ingestion did not finish.

    Opens its own session on purpose: when this runs after an exception, the
    session that raised has an aborted transaction and Postgres rejects every
    further statement on it.
    """
    async with worker_session() as session:
        manual = await session.get(Manual, manual_id)
        if manual is None:
            return
        manual.status = ManualStatus.FAILED
        manual.error = message[:MAX_ERROR_CHARS]
        # Nothing is running any more, so drop the claim.
        manual.processing_started_at = None
        await session.commit()


async def _ingest(manual_id: UUID) -> None:
    # The manual is already in `processing`: whoever queued this task claimed it
    # with a conditional UPDATE, which is also what stops two workers picking up
    # the same manual.
    async with worker_session() as session:
        manual = await session.get(Manual, manual_id)
        if manual is None:
            logger.warning("Manual %s no longer exists, skipping", manual_id)
            return
        storage_key = manual.storage_key
        tenant_id = manual.tenant_id

    try:
        # Roughly two minutes of work, deliberately outside any session: a
        # pooled connection held open while we wait on OpenAI is a connection
        # nobody else can use.
        data = get_storage().read(storage_key)
        pages = extract_pages(data)

        if not pages:
            # Expected outcome, not a crash: the file is a stack of images.
            logger.warning("Manual %s has no extractable text", manual_id)
            await _mark_failed(manual_id, SCANNED_PDF_MESSAGE)
            return

        chunks = chunk_pages(pages, settings.chunk_size, settings.chunk_overlap)
        vectors = await embed_texts([str(chunk) for chunk in chunks])

        rows = [
            Chunk(
                manual_id=manual_id,
                tenant_id=tenant_id,
                ordinal=chunk.ordinal,
                page_from=chunk.page_from,
                page_to=chunk.page_to,
                language=chunk.language,
                section_path=chunk.section,
                content=chunk.content,
                embedding=vector,
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]

        # One short transaction. The delete and the insert go together, so a
        # failure here leaves the previous index intact and still serving.
        async with worker_session() as session:
            await session.execute(delete(Chunk).where(Chunk.manual_id == manual_id))
            session.add_all(rows)

            manual = await session.get(Manual, manual_id)
            manual.status = ManualStatus.READY
            manual.page_count = len(pages)
            manual.chunk_count = len(chunks)
            manual.processing_started_at = None

            await session.commit()

        logger.info(
            "Manual %s ingested: %d pages, %d chunks",
            manual_id,
            len(pages),
            len(chunks),
        )

    # Not BaseException: KeyboardInterrupt and SystemExit have to reach the
    # worker so Ctrl+C still stops it.
    except Exception as exc:  # noqa: BLE001 - any failure must leave a trace
        logger.exception("Ingestion failed for manual %s", manual_id)
        await _mark_failed(manual_id, f"{type(exc).__name__}: {exc}")
