"""OTP login over WhatsApp (AC-F7-2) and JWT refresh (docs/09)."""

import re
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from seetlu.api.deps import DB
from seetlu.core.config import get_settings
from seetlu.core.ids import uuid7
from seetlu.core.problem import Problem
from seetlu.core.security import hash_token, verify_token
from seetlu.core.tokens import ACCESS_TTL, decode_token, make_token
from seetlu.db import models as m
from seetlu.messaging.provider import get_provider

router = APIRouter(prefix="/v1/auth", tags=["auth"])

OTP_TTL = timedelta(minutes=5)
OTP_MAX_ATTEMPTS = 5
RATE_WINDOW = timedelta(minutes=15)
RATE_MAX = 3
E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_phone(value: str) -> str:
    phone = re.sub(r"[\s.\-()]", "", value)
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    if not E164.match(phone):
        raise ValueError("phone must be E.164, e.g. +221770000000")
    return phone


class OtpRequest(BaseModel):
    phone_e164: str

    @field_validator("phone_e164")
    @classmethod
    def _phone(cls, v: str) -> str:
        return normalize_phone(v)


class OtpVerify(OtpRequest):
    code: str


class RefreshIn(BaseModel):
    refresh_token: str


class Tokens(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int = int(ACCESS_TTL.total_seconds())


def _recent_requests(s: Session, now: datetime, *, phone: str | None = None, ip: str | None = None) -> int:
    # otp_codes has no created_at; a row was created at expires_at - OTP_TTL.
    since = now - RATE_WINDOW + OTP_TTL
    q = select(func.count()).select_from(m.OtpCode).where(m.OtpCode.expires_at > since)
    q = q.where(m.OtpCode.phone_e164 == phone) if phone is not None else q.where(m.OtpCode.request_ip == ip)
    return s.scalar(q) or 0


@router.post("/otp/request", status_code=204, response_class=Response)
def request_otp(body: OtpRequest, request: Request, s: DB) -> Response:
    """Always 204 (no phone enumeration). Unknown phones get a row too, so rate limits look the same."""
    now = datetime.now(UTC)
    ip = request.client.host if request.client else None
    if _recent_requests(s, now, phone=body.phone_e164) >= RATE_MAX or (
        ip is not None and _recent_requests(s, now, ip=ip) >= RATE_MAX
    ):
        raise Problem(429, "otp-rate-limited", "Too many code requests, try again later")

    user = s.scalars(select(m.User).where(m.User.phone_e164 == body.phone_e164, m.User.active)).first()
    fixed = get_settings().dev_fixed_otp
    code = fixed if fixed else f"{secrets.randbelow(1_000_000):06d}"
    s.add(
        m.OtpCode(
            phone_e164=body.phone_e164,
            code_hash=hash_token(code if user else secrets.token_hex(8)),
            expires_at=now + OTP_TTL,
            request_ip=ip,
        )
    )
    if user is not None:
        get_provider(s).send_template(user.phone_e164, "otp_fr", "fr", [code], buttons=["copy_code"])
    s.commit()
    return Response(status_code=204)


def _issue(s: Session, user: m.User) -> Tokens:
    jti = uuid7()
    refresh, refresh_exp = make_token(user.id, "refresh", jti)
    s.add(m.RefreshToken(id=jti, user_id=user.id, expires_at=refresh_exp))
    access, _ = make_token(user.id, "access", uuid7())
    return Tokens(access_token=access, refresh_token=refresh)


@router.post("/otp/verify")
def verify_otp(body: OtpVerify, s: DB) -> Tokens:
    now = datetime.now(UTC)
    otp = s.scalars(
        select(m.OtpCode)
        .where(
            m.OtpCode.phone_e164 == body.phone_e164,
            m.OtpCode.consumed_at.is_(None),
            m.OtpCode.expires_at > now,
        )
        .order_by(m.OtpCode.expires_at.desc())
        .with_for_update()
    ).first()
    invalid = Problem(401, "invalid-code", "Code is invalid or expired")
    if otp is None or otp.attempts >= OTP_MAX_ATTEMPTS:
        raise invalid
    if not verify_token(otp.code_hash, body.code.strip()):
        otp.attempts += 1
        s.commit()
        raise invalid
    user = s.scalars(select(m.User).where(m.User.phone_e164 == body.phone_e164, m.User.active)).first()
    if user is None:
        raise invalid
    otp.consumed_at = now
    tokens = _issue(s, user)
    s.commit()
    return tokens


@router.post("/refresh")
def refresh(body: RefreshIn, s: DB) -> Tokens:
    now = datetime.now(UTC)
    invalid = Problem(401, "invalid-token", "Refresh token is invalid or expired")
    claims = decode_token(body.refresh_token, "refresh")
    if claims is None:
        raise invalid
    row = s.get(m.RefreshToken, claims.jti, with_for_update=True)
    if row is None or row.user_id != claims.user_id or row.expires_at <= now:
        raise invalid
    if row.revoked_at is not None:
        # reuse of a rotated token: revoke the whole family for this user
        s.execute(
            update(m.RefreshToken)
            .where(m.RefreshToken.user_id == row.user_id, m.RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        s.commit()
        raise invalid
    user = s.get(m.User, row.user_id)
    if user is None or not user.active:
        raise invalid
    tokens = _issue(s, user)
    new_claims = decode_token(tokens.refresh_token, "refresh")
    row.revoked_at = now
    row.replaced_by = new_claims.jti if new_claims else None
    s.commit()
    return tokens
