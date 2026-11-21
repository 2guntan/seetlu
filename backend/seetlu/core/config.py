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
    s3_public_endpoint: str = ""  # host browsers and Meta use for presigned GET links (default: s3_endpoint)
    app_base_url: str = "http://localhost:5173"
    dev_fixed_otp: str | None = None
    messaging_provider: str = "mock"
    mock_whatsapp_url: str = "http://localhost:8025"
    wa_graph_url: str = "https://graph.facebook.com/v21.0"
    wa_phone_number_id: str = ""
    wa_access_token: str = ""
    wa_app_secret: str = ""
    wa_verify_token: str = ""
    raw_public_key_b64: str = ""  # shop phones seal raw notifications with it (docs/09)
    raw_private_key_b64: str = ""  # worker only; never set on the API


@lru_cache
def get_settings() -> Settings:
    return Settings()
