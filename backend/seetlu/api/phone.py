"""Shop phone app (docs/08, M9): pairing, parser rules, sales batch. Device token = '<device id>.<secret>'."""

import base64
import binascii
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from seetlu.api.deps import DB, CurrentUser, load_shop
from seetlu.core.audit import audit
from seetlu.core.authz import Action
from seetlu.core.config import get_settings
from seetlu.core.problem import Problem
from seetlu.core.security import hash_token, new_device_token, verify_token
from seetlu.db import models as m
from seetlu.phone import crypto
from seetlu.phone import rules as phone_rules
from seetlu.reports import service as report_service

router = APIRouter(prefix="/v1", tags=["phone"])
CODE_TTL = timedelta(minutes=10)
FAIL_WINDOW = timedelta(minutes=15)
FAIL_MAX = 10
PHONE_SOURCES = ("wave", "orange_money", "quick_log")


def _code_hmac(code: str) -> str:
    return hmac.new(get_settings().jwt_secret.encode(), f"pair:{code}".encode(), hashlib.sha256).hexdigest()


# ---------- owner side ----------
class PairCodeOut(BaseModel):
    code: str
    expires_at: datetime


@router.post("/shops/{shop_id}/phone-pairing-codes", status_code=201)
def new_pair_code(shop_id: uuid.UUID, user: CurrentUser, s: DB) -> PairCodeOut:
    """Owner app → 'pair shop phone': a fresh 6-digit code; older unused codes of the shop stop working."""
    shop = load_shop(s, shop_id, user, Action.shop_settings)
    now = datetime.now(UTC)
    for old in s.scalars(
        select(m.PhonePairCode).where(m.PhonePairCode.shop_id == shop.id, m.PhonePairCode.used_at.is_(None))
    ):
        old.expires_at = min(old.expires_at, now)
    code = f"{secrets.randbelow(1_000_000):06d}"
    row = m.PhonePairCode(
        shop_id=shop.id, code_hmac=_code_hmac(code), created_by=user.id, expires_at=now + CODE_TTL
    )
    s.add(row)
    s.flush()
    audit(s, user, "phone.pair_code", account_id=shop.account_id, target_type="shop", target_id=shop.id)
    s.commit()
    return PairCodeOut(code=code, expires_at=row.expires_at)


class PhoneOut(BaseModel):
    id: uuid.UUID
    model: str | None
    app_version: str | None
    parser_version: str | None
    parser_current: bool
    last_seen_at: datetime | None
    created_at: datetime


@router.get("/shops/{shop_id}/phones")
def list_phones(shop_id: uuid.UUID, user: CurrentUser, s: DB) -> list[PhoneOut]:
    shop = load_shop(s, shop_id, user, Action.shop_settings)
    current = phone_rules.current_version()
    return [
        PhoneOut(
            id=p.id,
            model=p.model,
            app_version=p.app_version,
            parser_version=p.parser_version,
            parser_current=p.parser_version == current,
            last_seen_at=p.last_seen_at,
            created_at=p.created_at,
        )
        for p in s.scalars(
            select(m.PhoneDevice).where(m.PhoneDevice.shop_id == shop.id).order_by(m.PhoneDevice.created_at)
        )
    ]


# ---------- phone side ----------
class PairIn(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")
    model: str | None = Field(default=None, max_length=120)
    app_version: str | None = Field(default=None, max_length=40)


class PairOut(BaseModel):
    device_token: str
    device_id: uuid.UUID
    shop_id: uuid.UUID
    shop_name: str
    timezone: str
    raw_public_key_b64: str | None
    parsers_version: str


@router.post("/phone/pair")
def pair(body: PairIn, request: Request, s: DB) -> PairOut:
    now = datetime.now(UTC)
    ip = request.client.host if request.client else "unknown"
    fails = s.scalar(
        select(func.count())
        .select_from(m.PhonePairFailure)
        .where(m.PhonePairFailure.ip == ip, m.PhonePairFailure.at > now - FAIL_WINDOW)
    )
    if (fails or 0) >= FAIL_MAX:
        raise Problem(429, "pair-rate-limited", "Too many wrong codes, try again later")
    row = s.scalars(
        select(m.PhonePairCode).where(
            m.PhonePairCode.code_hmac == _code_hmac(body.code),
            m.PhonePairCode.used_at.is_(None),
            m.PhonePairCode.expires_at > now,
        )
    ).first()
    if row is None:
        s.add(m.PhonePairFailure(ip=ip, at=now))
        s.commit()
        raise Problem(404, "invalid-code", "Unknown or expired code")
    shop = s.get(m.Shop, row.shop_id)
    assert shop is not None
    row.used_at = now
    secret = new_device_token()
    device = m.PhoneDevice(
        shop_id=shop.id,
        token_hash=hash_token(secret),
        model=body.model,
        app_version=body.app_version,
        last_seen_at=now,
    )
    s.add(device)
    s.flush()
    audit(
        s,
        None,
        "phone.pair",
        account_id=shop.account_id,
        target_type="phone_device",
        target_id=device.id,
        detail={"model": body.model, "code_by": str(row.created_by) if row.created_by else None},
    )
    s.commit()
    return PairOut(
        device_token=f"{device.id}.{secret}",
        device_id=device.id,
        shop_id=shop.id,
        shop_name=shop.name,
        timezone=shop.timezone,
        raw_public_key_b64=get_settings().raw_public_key_b64 or None,
        parsers_version=phone_rules.current_version(),
    )


def current_phone(request: Request, s: DB) -> m.PhoneDevice:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    dev_part, _, secret = token.partition(".")
    if scheme.lower() != "bearer" or not secret:
        raise Problem(401, "unauthorized", "Missing device token")
    try:
        dev_id = uuid.UUID(dev_part)
    except ValueError as exc:
        raise Problem(401, "invalid-token", "Device token is invalid") from exc
    device = s.get(m.PhoneDevice, dev_id)
    if device is None or not verify_token(device.token_hash, secret):
        raise Problem(401, "invalid-token", "Device token is invalid")
    device.last_seen_at = datetime.now(UTC)
    app_version = request.headers.get("x-app-version")
    if app_version:
        device.app_version = app_version[:40]
    return device


CurrentPhone = Annotated[m.PhoneDevice, Depends(current_phone)]


class ParsersOut(BaseModel):
    version: str
    rules: list[dict[str, Any]]
    raw_public_key_b64: str | None


@router.get("/phone/parsers", response_model=ParsersOut, responses={304: {"description": "unchanged"}})
def parsers(request: Request, device: CurrentPhone, s: DB) -> Response:
    s.commit()  # last_seen_at
    etag = phone_rules.etag()
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    data = phone_rules.load()
    out = ParsersOut(
        version=str(data["version"]),
        rules=data["rules"],
        raw_public_key_b64=get_settings().raw_public_key_b64 or None,
    )
    return Response(out.model_dump_json(), media_type="application/json", headers={"ETag": etag})


class PhoneSaleIn(BaseModel):
    """docs/04 SaleIn, for what a phone sends: captured mobile-money payments and the quick-log pad."""

    client_id: uuid.UUID
    source: Literal["wave", "orange_money", "quick_log"]
    amount_xof: int = Field(ge=0, le=10_000_000)
    occurred_at: datetime
    external_ref: str | None = Field(default=None, max_length=80)
    raw: str | None = Field(default=None, max_length=8000, description="base64 sealed blob (docs/09)")
    parser_version: str | None = Field(default=None, max_length=40)


class UnparsedIn(BaseModel):
    package_name: str = Field(max_length=200)
    received_at: datetime
    raw: str = Field(max_length=8000, description="base64 sealed blob (docs/09)")


class BatchIn(BaseModel):
    sales: list[PhoneSaleIn] = Field(default=[], max_length=200)
    unparsed: list[UnparsedIn] = Field(default=[], max_length=200)


class BatchOut(BaseModel):
    accepted: int
    duplicates: int
    unparsed: int


def _blob(b64: str | None) -> bytes | None:
    if b64 is None:
        return None
    try:
        blob = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise Problem(422, "validation-error", "raw must be base64") from exc
    if not crypto.valid_blob(blob):
        raise Problem(422, "validation-error", "raw must be a sealed blob, never plain text (docs/09)")
    return blob


def _recompute_late(s: Session, shop: m.Shop, times: list[datetime]) -> None:
    for d in report_service.late_dates(s, shop, times):
        report_service.recompute(s, shop.id, d)


@router.post("/sales/batch")
def sales_batch(body: BatchIn, device: CurrentPhone, s: DB) -> BatchOut:
    """Idempotent: the same client_id, or the same mobile-money reference, is counted once."""
    shop = s.get(m.Shop, device.shop_id)
    assert shop is not None
    tz = ZoneInfo(shop.timezone)
    accepted = duplicates = 0
    fresh: list[datetime] = []
    for sale in body.sales:
        if sale.occurred_at.tzinfo is None:
            raise Problem(422, "validation-error", "occurred_at needs a UTC offset")
        row = {
            "id": sale.client_id,
            "shop_id": shop.id,
            "source": m.SaleSource(sale.source),
            "amount_xof": sale.amount_xof,
            "occurred_at": sale.occurred_at,
            "local_date": sale.occurred_at.astimezone(tz).date(),
            "external_ref": sale.external_ref if sale.source != "quick_log" else None,
            "device_id": device.id,
            "raw_encrypted": _blob(sale.raw),
        }
        done = s.execute(insert(m.Sale).values(**row).on_conflict_do_nothing().returning(m.Sale.id)).first()
        if done is None:
            duplicates += 1
        else:
            accepted += 1
            fresh.append(sale.occurred_at)
        if sale.parser_version and sale.source != "quick_log":
            device.parser_version = sale.parser_version
    for u in body.unparsed:
        blob = _blob(u.raw)
        assert blob is not None
        s.add(
            m.UnparsedNotification(
                shop_id=shop.id, package_name=u.package_name, received_at=u.received_at, raw_encrypted=blob
            )
        )
    s.commit()
    if fresh:
        try:
            _recompute_late(s, shop, fresh)
        except Exception:  # the upload succeeded; a failed recompute must not make the phone retry
            s.rollback()
    return BatchOut(accepted=accepted, duplicates=duplicates, unparsed=len(body.unparsed))
