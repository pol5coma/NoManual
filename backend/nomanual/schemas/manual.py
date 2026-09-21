from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from nomanual.models.enums import ManualSource, ManualStatus


class ManualOut(BaseModel):
    """What the API returns for a manual."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    source: ManualSource
    status: ManualStatus
    page_count: int | None = None
    chunk_count: int | None = None
    error: str | None = None

    # The pipeline, step by step, with timings and what each one produced.
    # Polled by the web app while a manual is being processed.
    progress: list[dict[str, Any]] = []
