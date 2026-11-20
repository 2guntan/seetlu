"""/v1/me, shops, shop users and alert rules (M2)."""

import re
import uuid
from datetime import datetime, time
from decimal import Decimal
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from seetlu.api.auth import normalize_phone
from seetlu.api.deps import DB, CurrentUser, load_shop, require, shop_resource, subject_for
from seetlu.core.audit import audit
from seetlu.core.authz import Action, Resource, authorize
from seetlu.core.problem import Problem
from seetlu.db import models as m

router = APIRouter(prefix="/v1", tags=["shops"])

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
CATEGORIES = ("boutique", "superette", "pharmacie", "quincaillerie", "salon", "telephonie", "other")
DEFAULT_ALERT_PARAMS: dict[m.AlertType, dict[str, int]] = {
    m.AlertType.not_opened: {"grace_min": 30},
    m.AlertType.unattended: {"min": 10},
    m.AlertType.after_hours_motion: {},
    m.AlertType.kit_offline: {"min": 30},
}
EDGE_FIELDS = {
    "timezone",
    "opening_hours",
    "expected_staff",
    "service_min_s",
    "wait_min_s",
    "unattended_min_s",
}


# ---------- schemas ----------
def _validate_hours(v: dict[str, list[list[str]]]) -> dict[str, list[list[str]]]:
    if set(v) != set(DAYS):
        raise ValueError(f"opening_hours needs exactly the keys {', '.join(DAYS)}")
    for day, ranges in v.items():
        for r in ranges:
            if len(r) != 2 or not all(HHMM.match(t) for t in r) or r[0] >= r[1]:
                raise ValueError(f'{day}: each range is ["HH:MM", "HH:MM"] with open < close')
    return v


def _validate_tz(v: str) -> str:
    try:
        ZoneInfo(v)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("timezone must be an IANA name, e.g. Africa/Dakar") from exc
    return v


class QuietHours(BaseModel):
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not HHMM.match(v):
            raise ValueError("HH:MM")
        return v


class ShopSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    category: Literal[CATEGORIES] | None = None  # type: ignore[valid-type]
    address: str | None = None
    gps_lat: Decimal | None = Field(default=None, ge=-90, le=90)
    gps_lng: Decimal | None = Field(default=None, ge=-180, le=180)
    timezone: str | None = None
    opening_hours: dict[str, list[list[str]]] | None = None
    report_time: time | None = None
    cash_prompt_time: time | None = None
    quiet_hours: QuietHours | None = None
    expected_staff: int | None = Field(default=None, ge=0, le=20)
    service_min_s: int | None = Field(default=None, ge=10, le=60)
    wait_min_s: int | None = Field(default=None, ge=30, le=3600)
    unattended_min_s: int | None = Field(default=None, ge=60, le=7200)
    cdp_declaration_ref: str | None = Field(default=None, max_length=120)
    clip_access_for_managers: bool | None = None  # account-level flag (docs/decisions.md, M2)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        return v if v is None else _validate_tz(v)

    @field_validator("opening_hours")
    @classmethod
    def _hours(cls, v: dict[str, list[list[str]]] | None) -> dict[str, list[list[str]]] | None:
        return v if v is None else _validate_hours(v)


class OwnerIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone_e164: str

    @field_validator("phone_e164")
    @classmethod
    def _phone(cls, v: str) -> str:
        return normalize_phone(v)


class ShopCreate(ShopSettings):
    name: str = Field(min_length=1, max_length=120)
    category: Literal[CATEGORIES]  # type: ignore[valid-type]
    opening_hours: dict[str, list[list[str]]]
    owner: OwnerIn | None = None  # required when an installer creates the shop


class ShopOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    account_id: uuid.UUID
    name: str
    category: str
    address: str | None
    gps_lat: Decimal | None
    gps_lng: Decimal | None
    timezone: str
    opening_hours: dict[str, Any]
    report_time: time
    cash_prompt_time: time
    quiet_hours: dict[str, Any]
    expected_staff: int
    service_min_s: int
    wait_min_s: int
    unattended_min_s: int
    cdp_declaration_ref: str | None
    status: m.ShopStatus
    activated_at: datetime | None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    phone_e164: str
    role: m.UserRole
    language: m.LangCode
    receives_report: bool
    active: bool


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    plan: str
    language: m.LangCode
    clip_access_for_managers: bool


class MeOut(BaseModel):
    user: UserOut
    account: AccountOut | None
    shops: list[ShopOut]


class InviteIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone_e164: str
    role: Literal["manager", "staff"]
    receives_report: bool = False
    language: m.LangCode = m.LangCode.fr

    @field_validator("phone_e164")
    @classmethod
    def _phone(cls, v: str) -> str:
        return normalize_phone(v)


class AlertRuleIn(BaseModel):
    type: m.AlertType
    enabled: bool
    params: dict[str, Annotated[int, Field(ge=1, le=1440)]] = {}


class AlertRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    type: m.AlertType
    enabled: bool
    params: dict[str, Any]


class AlertRulesIn(BaseModel):
    rules: list[AlertRuleIn]


ALLOWED_PARAM_KEYS: dict[m.AlertType, set[str]] = {t: set(p) for t, p in DEFAULT_ALERT_PARAMS.items()}


# ---------- helpers ----------
def visible_shops(s: Session, user: m.User) -> list[m.Shop]:
    if user.role is m.UserRole.support:
        candidates = s.scalars(select(m.Shop).order_by(m.Shop.created_at)).all()
    elif user.role is m.UserRole.installer:
        candidates = s.scalars(
            select(m.Shop)
            .join(m.Kit, m.Kit.shop_id == m.Shop.id)
            .where(m.Kit.installer_id == user.id)
            .distinct()
        ).all()
    elif user.account_id is not None:
        candidates = s.scalars(
            select(m.Shop).where(m.Shop.account_id == user.account_id).order_by(m.Shop.created_at)
        ).all()
    else:
        candidates = []
    subject = subject_for(s, user)
    return [sh for sh in candidates if authorize(subject, Action.shop_view, shop_resource(s, sh, user))]


def _ensure_alert_rules(s: Session, shop: m.Shop) -> None:
    existing = {r.type for r in s.scalars(select(m.AlertRule).where(m.AlertRule.shop_id == shop.id))}
    for t, params in DEFAULT_ALERT_PARAMS.items():
        if t not in existing:
            s.add(m.AlertRule(shop_id=shop.id, type=t, enabled=True, params=dict(params)))


def _apply_settings(s: Session, shop: m.Shop, body: ShopSettings) -> None:
    data = body.model_dump(exclude_unset=True)
    flag = data.pop("clip_access_for_managers", None)
    data.pop("owner", None)
    if flag is not None:
        account = s.get(m.Account, shop.account_id)
        if account is not None:
            account.clip_access_for_managers = flag
    for key, value in data.items():
        setattr(shop, key, value)
    if EDGE_FIELDS & data.keys():
        s.execute(
            update(m.Kit).where(m.Kit.shop_id == shop.id).values(config_version=m.Kit.config_version + 1)
        )


# ---------- routes ----------
@router.get("/me", tags=["me"])
def me(user: CurrentUser, s: DB) -> MeOut:
    account = s.get(m.Account, user.account_id) if user.account_id else None
    return MeOut(
        user=UserOut.model_validate(user),
        account=AccountOut.model_validate(account) if account else None,
        shops=[ShopOut.model_validate(sh) for sh in visible_shops(s, user)],
    )


@router.get("/shops")
def list_shops(user: CurrentUser, s: DB) -> list[ShopOut]:
    return [ShopOut.model_validate(sh) for sh in visible_shops(s, user)]


@router.post("/shops", status_code=201)
def create_shop(body: ShopCreate, user: CurrentUser, s: DB) -> ShopOut:
    if user.role is m.UserRole.installer:
        if body.owner is None:
            raise Problem(422, "owner-required", "An installer must give the owner's name and phone")
        owner = s.scalars(select(m.User).where(m.User.phone_e164 == body.owner.phone_e164)).first()
        if owner is None:
            account = m.Account(name=body.owner.name)
            s.add(account)
            s.flush()
            owner = m.User(
                account_id=account.id, name=body.owner.name, phone_e164=body.owner.phone_e164,
                role=m.UserRole.owner, receives_report=True,
            )  # fmt: skip
            s.add(owner)
            s.flush()
        elif owner.role is not m.UserRole.owner or owner.account_id is None:
            raise Problem(409, "phone-in-use", "This phone belongs to a user who is not an owner")
        account_id = owner.account_id
    else:
        account_id = user.account_id
    require(s, user, Action.shop_create, Resource(account_id=account_id))
    assert account_id is not None

    shop = m.Shop(
        account_id=account_id, name=body.name, category=body.category, opening_hours=body.opening_hours
    )
    s.add(shop)
    s.flush()
    _apply_settings(s, shop, body)
    _ensure_alert_rules(s, shop)
    s.commit()
    s.refresh(shop)
    return ShopOut.model_validate(shop)


@router.get("/shops/{shop_id}")
def get_shop(shop_id: uuid.UUID, user: CurrentUser, s: DB) -> ShopOut:
    return ShopOut.model_validate(load_shop(s, shop_id, user, Action.shop_view))


@router.patch("/shops/{shop_id}")
def patch_shop(shop_id: uuid.UUID, body: ShopSettings, user: CurrentUser, s: DB) -> ShopOut:
    shop = load_shop(s, shop_id, user, Action.shop_settings)
    if body.clip_access_for_managers is not None and user.role is not m.UserRole.owner:
        raise Problem(403, "forbidden", "Only the owner can change clip access for managers")
    _apply_settings(s, shop, body)
    s.commit()
    s.refresh(shop)
    return ShopOut.model_validate(shop)


@router.get("/shops/{shop_id}/users")
def list_shop_users(shop_id: uuid.UUID, user: CurrentUser, s: DB) -> list[UserOut]:
    shop = load_shop(s, shop_id, user, Action.users_manage)
    assigned = select(m.UserShop.user_id).where(m.UserShop.shop_id == shop.id)
    rows = s.scalars(
        select(m.User)
        .where(
            m.User.account_id == shop.account_id,
            (m.User.role == m.UserRole.owner) | m.User.id.in_(assigned),
        )
        .order_by(m.User.created_at)
    ).all()
    return [UserOut.model_validate(u) for u in rows]


@router.post("/shops/{shop_id}/users", status_code=201)
def invite_user(shop_id: uuid.UUID, body: InviteIn, user: CurrentUser, s: DB) -> UserOut:
    shop = load_shop(s, shop_id, user, Action.users_manage)
    invited = s.scalars(select(m.User).where(m.User.phone_e164 == body.phone_e164)).first()
    if invited is None:
        invited = m.User(
            account_id=shop.account_id, name=body.name, phone_e164=body.phone_e164,
            role=m.UserRole(body.role), receives_report=body.receives_report, language=body.language,
        )  # fmt: skip
        s.add(invited)
        s.flush()
    elif invited.account_id != shop.account_id or invited.role not in (m.UserRole.manager, m.UserRole.staff):
        raise Problem(409, "phone-in-use", "This phone is already registered")
    else:
        invited.role = m.UserRole(body.role)
        invited.receives_report = body.receives_report
        invited.active = True
    if s.get(m.UserShop, (invited.id, shop.id)) is None:
        s.add(m.UserShop(user_id=invited.id, shop_id=shop.id))
    audit(
        s, user, "user.invite", account_id=shop.account_id, target_type="user", target_id=invited.id,
        detail={"shop_id": str(shop.id), "role": body.role},
    )  # fmt: skip
    s.commit()
    s.refresh(invited)
    return UserOut.model_validate(invited)


@router.get("/shops/{shop_id}/alert-rules")
def get_alert_rules(shop_id: uuid.UUID, user: CurrentUser, s: DB) -> list[AlertRuleOut]:
    shop = load_shop(s, shop_id, user, Action.alerts_manage)
    _ensure_alert_rules(s, shop)
    s.commit()
    rules = s.scalars(select(m.AlertRule).where(m.AlertRule.shop_id == shop.id)).all()
    order = list(m.AlertType)
    return [AlertRuleOut.model_validate(r) for r in sorted(rules, key=lambda r: order.index(r.type))]


@router.put("/shops/{shop_id}/alert-rules")
def put_alert_rules(shop_id: uuid.UUID, body: AlertRulesIn, user: CurrentUser, s: DB) -> list[AlertRuleOut]:
    """AC-F6-3: each alert type can be enabled/disabled and its threshold changed by the owner."""
    shop = load_shop(s, shop_id, user, Action.alerts_manage)
    _ensure_alert_rules(s, shop)
    s.flush()
    by_type = {r.type: r for r in s.scalars(select(m.AlertRule).where(m.AlertRule.shop_id == shop.id))}
    for rule in body.rules:
        unknown = set(rule.params) - ALLOWED_PARAM_KEYS[rule.type]
        if unknown:
            raise Problem(422, "invalid-alert-params", f"{rule.type.value}: unknown params {sorted(unknown)}")
        row = by_type[rule.type]
        row.enabled = rule.enabled
        row.params = {**row.params, **rule.params}
    s.commit()
    return get_alert_rules(shop_id, user, s)
