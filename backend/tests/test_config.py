"""Staging/prod refuse dev shortcuts (docs/09 technical security; CLAUDE.md rule 6)."""

import pytest
from pydantic import ValidationError

from seetlu.core.config import Settings

SAFE = {
    "jwt_secret": "x" * 40,
    "s3_secret_key": "s3-secret-from-env",
    "messaging_provider": "whatsapp_cloud",
}


def test_dev_accepts_the_dev_defaults() -> None:
    assert Settings.model_validate({"seetlu_env": "dev", "dev_fixed_otp": "000000"}).jwt_secret


def test_prod_accepts_real_values() -> None:
    assert Settings.model_validate({"seetlu_env": "prod", **SAFE}).seetlu_env == "prod"


@pytest.mark.parametrize(
    ("override", "needle"),
    [
        ({"jwt_secret": "short"}, "JWT_SECRET"),
        ({"dev_fixed_otp": "000000"}, "DEV_FIXED_OTP"),
        ({"s3_secret_key": "minio123"}, "S3_SECRET_KEY"),
        ({"messaging_provider": "mock"}, "MESSAGING_PROVIDER"),
    ],
)
def test_prod_refuses_dev_shortcuts(override: dict[str, str], needle: str) -> None:
    with pytest.raises(ValidationError, match=needle):
        Settings.model_validate({"seetlu_env": "prod", **SAFE, **override})


def test_staging_may_use_the_mock_inbox_but_not_dev_secrets() -> None:
    assert Settings.model_validate({"seetlu_env": "staging", **SAFE, "messaging_provider": "mock"})
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings.model_validate({"seetlu_env": "staging"})
