from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """NoManual configuration, validated at startup.

    Los nombres en minúscula se mapean solos a variables de entorno en
    mayúscula: `database_url` lee DATABASE_URL.
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Infra---
    database_url: str
    redis_url: str
    openai_api_key: str
    gemini_api_key: str
    anthropic_api_key: str
    kimi_api_key: str

    # Mounts /debug, which exposes raw file contents. Never on in production.
    debug_endpoints: bool = True

    # Used for short utility calls - translating a query, classifying a
    # question - not for answering. Small and cheap is the point.
    chat_model: str = "gpt-4.1-2025-04-14"

    # Browsers block a request from the Vite dev server (5174) to the API
    # (8000) unless the API says the origin is allowed. Listed explicitly
    # rather than "*" because the API will carry credentials later.
    cors_origins: list[str] = [
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]

    # --- Ingest ---
    # pymupdf infers word boundaries from real font metrics, so it glues
    # words together far less often than pdfplumber (0.1% vs 0.7% on a
    # 130-page manual) and runs ~57x faster. It is AGPL-3.0 though, which
    # matters if this ever ships as a service. Set "pdfplumber" to compare.
    pdf_backend: Literal["pymupdf", "pdfplumber"] = "pymupdf"

    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    # A manual stuck in `processing` for longer than this is assumed dead:
    # its worker crashed or was killed. Must stay above the celery
    # task_time_limit (1800s) or we would reclaim tasks still working.
    ingestion_stale_after_seconds: int = 2700  # 45 min
    chunk_size: int = 1200
    chunk_overlap: int = 150

    # A stored file younger than this is never treated as an orphan: the
    # upload that created it may still be committing its row.
    orphan_file_min_age_seconds: int = 3600

    # --- Uploads ---
    storage_dir: Path = PROJECT_ROOT / Path("uploads")
    max_upload_bytes: int = 100 * 1024 * 1024  # 50 MB

    # --- Monitoring ---
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Unique instance: cache avoids reading .env file on each request"""
    return Settings()
