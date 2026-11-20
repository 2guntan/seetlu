"""JWT access (15 min) + rotating refresh (30 days) tokens (docs/09)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from seetlu.core.config import get_settings

ACCESS_TTL = timedelta(minutes=15)
REFRESH_TTL = timedelta(days=30)
ALGORITHM = "HS256"


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    typ: str
    jti: uuid.UUID
    expires_at: datetime


def _encode(claims: dict[str, Any]) -> str:
    return jwt.encode(claims, get_settings().jwt_secret, algorithm=ALGORITHM)


def make_token(
    user_id: uuid.UUID, typ: str, jti: uuid.UUID, now: datetime | None = None
) -> tuple[str, datetime]:
    now = now or datetime.now(UTC)
    exp = now + (ACCESS_TTL if typ == "access" else REFRESH_TTL)
    token = _encode({"sub": str(user_id), "typ": typ, "jti": str(jti), "iat": now, "exp": exp})
    return token, exp


def decode_token(token: str, typ: str) -> TokenClaims | None:
    try:
        data = jwt.decode(
            token, get_settings().jwt_secret, algorithms=[ALGORITHM], options={"require": ["exp"]}
        )
    except jwt.PyJWTError:
        return None
    if data.get("typ") != typ:
        return None
    try:
        return TokenClaims(
            user_id=uuid.UUID(data["sub"]),
            typ=typ,
            jti=uuid.UUID(data["jti"]),
            expires_at=datetime.fromtimestamp(data["exp"], UTC),
        )
    except (KeyError, ValueError):
        return None
