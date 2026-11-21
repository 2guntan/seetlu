"""Application settings, read from environment variables only (CLAUDE.md rule 6)."""

from functools import lru_cache
from typing import Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-jwt-secret-change-me-0123456789"  # noqa: S105 - dev default; refused in prod


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    seetlu_env: str = "dev"  # dev | staging | prod

    database_url: str = "postgresql+psycopg://seetlu:seetlu@localhost:5432/seetlu"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = DEV_JWT_SECRET
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

    @model_validator(mode="after")
    def _no_dev_values_outside_dev(self) -> Self:
        """Staging and prod refuse to start with dev shortcuts (docs/09, CLAUDE.md rule 6)."""
        if self.seetlu_env == "dev":
            return self
        problems = []
        if self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET is the dev value or shorter than 32 characters")
        if self.dev_fixed_otp:
            problems.append("DEV_FIXED_OTP must be empty")
        if self.s3_secret_key == "minio123":  # noqa: S105 - comparing against the dev default
            problems.append("S3_SECRET_KEY is the dev value")
        if self.seetlu_env == "prod" and self.messaging_provider != "whatsapp_cloud":
            problems.append("MESSAGING_PROVIDER must be whatsapp_cloud")
        if problems:
            raise ValueError(f"unsafe settings for SEETLU_ENV={self.seetlu_env}: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
