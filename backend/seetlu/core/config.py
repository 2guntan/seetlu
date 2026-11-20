"""Application settings, read from environment variables only (CLAUDE.md rule 6)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    database_url: str = "postgresql+psycopg://seetlu:seetlu@localhost:5432/seetlu"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "dev-only-jwt-secret-change-me-0123456789"  # noqa: S105 - dev default; env overrides
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minio"
    s3_secret_key: str = "minio123"  # noqa: S105 - dev default, overridden by env
    s3_bucket_clips: str = "seetlu-clips"
    app_base_url: str = "http://localhost:5173"
    dev_fixed_otp: str | None = None
    messaging_provider: str = "mock"
    mock_whatsapp_url: str = "http://localhost:8025"
    parser_version: str = "1"  # current shop-phone parser rules version (sales confidence, docs/06)


@lru_cache
def get_settings() -> Settings:
    return Settings()
