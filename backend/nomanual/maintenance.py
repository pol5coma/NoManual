"""Housekeeping tasks.

These reconcile reality against what the database says, rather than working
from a queue of pending repairs. A list of "things that failed" can itself be
lost - if the process dies right after the failure, nothing ever records it.
Comparing the two sides finds every discrepancy regardless of how it happened,
and running twice is harmless.
"""

import asyncio
import logging
from typing import Any

from sqlalchemy import select

from nomanual.core.config import get_settings
from nomanual.core.db import worker_session
from nomanual.core.storage import get_storage
from nomanual.models import Manual
from nomanual.worker import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="nomanual.sweep_orphaned_files")
def sweep_orphaned_files(dry_run: bool = True) -> dict[str, Any]:
    """Delete stored files no manual points at.

    Orphans appear when a delete removes the row but fails to unlink, when an
    upload stores the file and its transaction rolls back, or when the database
    is reset without clearing the volume.

    Defaults to dry_run: a task that deletes files should have to be asked.
    """
    return asyncio.run(_sweep(dry_run))


async def _sweep(dry_run: bool) -> dict[str, Any]:
    settings = get_settings()
    storage = get_storage()

    on_disk = set(storage.list_keys(settings.orphan_file_min_age_seconds))

    async with worker_session() as session:
        referenced = set(await session.scalars(select(Manual.storage_key)))

    orphans = sorted(on_disk - referenced)

    if not dry_run:
        for key in orphans:
            storage.delete(key)

    logger.info(
        "Orphan sweep: %d stored, %d referenced, %d orphaned%s",
        len(on_disk),
        len(referenced),
        len(orphans),
        "" if not dry_run else " (dry run, nothing deleted)",
    )

    return {
        "checked": len(on_disk),
        "referenced": len(referenced),
        "orphaned": len(orphans),
        "deleted": 0 if dry_run else len(orphans),
        "keys": orphans,
        "dry_run": dry_run,
    }
