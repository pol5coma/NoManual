import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from nomanual.core.config import get_settings


class Storage(Protocol):
    """Contract for binary file storage.

    An S3 implementation will satisfy this without the ingestion pipeline
    knowing anything changed.
    """

    def save(self, data: bytes, filename: str) -> str: ...
    def read(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class LocalStorage:
    """Files on local disk. Enough for development and a pilot."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes, filename: str) -> str:
        # Path(...).name strips any directory component: without it a filename
        # like "../../etc/passwd" would escape the storage root.
        safe_name = Path(filename).name or "manual.pdf"
        key = f"{uuid4().hex}-{safe_name}"
        (self.root / key).write_bytes(data)
        return key

    def read(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def delete(self, key: str) -> None:
        (self.root / key).unlink(missing_ok=True)


def compute_checksum(data: bytes) -> str:
    """sha256 of the raw file, used to recognise a manual we already ingested."""
    return hashlib.sha256(data).hexdigest()


@lru_cache
def get_storage() -> Storage:
    return LocalStorage(get_settings().storage_dir)
