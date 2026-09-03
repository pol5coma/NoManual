from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Configuración de NoManual, validada al arrancar.

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

    # --- Ingest ---
    embedding_model: str
    embedding_dimensions: int = 1536
    chunk_size: int = 1200
    chunk_overlap: int = 150

    # --- Uploads ---
    storage_dir: Path = PROJECT_ROOT / Path("uploads")
    max_upload_bytes: int = 50 * 1024 * 1024  # 50 MB

    # --- Monitoring ---
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Unique instance: cache avoids reading .env file on each request"""
    return Settings()
