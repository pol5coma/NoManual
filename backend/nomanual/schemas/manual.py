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
