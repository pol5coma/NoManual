from celery import Celery

from nomanual.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "nomanual",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["nomanual.ingestion.tasks", "nomanual.maintenance"],
)

celery_app.conf.update(
    task_track_started=True,
    # If the worker dies mid-task the message goes back to the queue instead of
    # being lost. Ingestion is idempotent enough to retry.
    task_acks_late=True,
    # Ingestion is slow, so a worker should not hoard messages it cannot start.
    worker_prefetch_multiplier=1,
    task_time_limit=1800,
)
