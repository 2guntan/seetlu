"""Data for the owner/manager web app (docs/04 "data for the owner app", docs/08 screens)."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from seetlu.api.deps import DB, CurrentUser, load_shop, require
from seetlu.core.audit import audit
from seetlu.core.authz import Action, Resource
from seetlu.core.problem import Problem
from seetlu.db import models as m
from seetlu.domain.report import compute_metrics
from seetlu.reports import service

DateQ = Annotated[date, Query(alias="date")]
FromQ = Annotated[date, Query(alias="from")]

router = APIRouter(prefix="/v1", tags=["data"])
MAX_RANGE_DAYS = 92
MAX_SAVED_CLIPS = 30  # docs/09 rule 4
CLIP_RETENTION = timedelta(days=7)


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID | None = None
    local_date: date
    visitors_in: int | None
    served: int | None
    waits: int | None
    unattended_min: int | None
    busiest_hour: int | None
    sales_count: int
    sales_xof: int
    sales_by_source: dict[str, int]
    cash_declared_xof: int | None
    rps_xof: Decimal | None
    verdict: m.VerdictCode | None = None
    confidence: dict[str, str] = {}
    missing_hours: list[int]
    moments: list[dict[str, Any]] = []
    vs_last_week: dict[str, Any] | None = None
    computed_at: datetime | None = None
    sent_at: datetime | None = None
    updated_after_send: bool = False
    corrections: list[dict[str, Any]] = []


def _report_out(s: Any, r: m.DailyReport) -> ReportOut:
    out = ReportOut.model_validate(r)
    out.updated_after_send = r.sent_at is not None and r.computed_at > r.sent_at + timedelta(seconds=1)
    out.corrections = [
        {"metric": c.metric, "corrected_value": c.corrected_value, "reported_value": c.reported_value}
        for c in s.scalars(
            select(m.DayCorrection).where(
                m.DayCorrection.shop_id == r.shop_id, m.DayCorrection.local_date == r.local_date
            )
        )
    ]
    return out


@router.get("/shops/{shop_id}/reports")
def reports(shop_id: uuid.UUID, user: CurrentUser, s: DB, from_: FromQ, to: date) -> list[ReportOut]:
    load_shop(s, shop_id, user, Action.report_view)
    if to < from_ or (to - from_).days > MAX_RANGE_DAYS:
        raise Problem(422, "bad-range", f"from..to must be at most {MAX_RANGE_DAYS} days")
    rows = s.scalars(
        select(m.DailyReport)
        .where(
            m.DailyReport.shop_id == shop_id,
            m.DailyReport.local_date >= from_,
            m.DailyReport.local_date <= to,
        )
        .order_by(m.DailyReport.local_date)
    ).all()
    return [_report_out(s, r) for r in rows]


class CounterStatus(BaseModel):
    state: Literal["empty", "staffed", "unknown"]
    since: datetime | None = None


class TodayOut(ReportOut):
    counter: CounterStatus
    last_heartbeat_at: datetime | None


@router.get("/shops/{shop_id}/today")
def today(shop_id: uuid.UUID, user: CurrentUser, s: DB) -> TodayOut:
    """Partial-day figures: same shape as a report, no verdict; hours still to come are not missing."""
    shop = load_shop(s, shop_id, user, Action.report_view)
    now = datetime.now(UTC)
    local = now.astimezone(ZoneInfo(shop.timezone))
    day = service.load_day(s, shop, local.date())
    mt = compute_metrics(day)
    kit_ids = list(s.scalars(select(m.Kit.id).where(m.Kit.shop_id == shop.id)))
    last_hb = (
        s.scalar(select(func.max(m.Heartbeat.at)).where(m.Heartbeat.kit_id.in_(kit_ids))) if kit_ids else None
    )
    open_unattended = [e for e in day.events if e.type == "unattended" and e.ended_at is None]
    if last_hb is None or now - last_hb > timedelta(minutes=10):
        counter = CounterStatus(state="unknown")
    elif open_unattended:
        counter = CounterStatus(state="empty", since=max(e.started_at for e in open_unattended))
    else:
        counter = CounterStatus(state="staffed")
    return TodayOut(
        local_date=local.date(),
        visitors_in=mt.visitors_in,
        served=mt.served,
        waits=mt.waits,
        unattended_min=mt.unattended_min,
        busiest_hour=mt.busiest_hour,
        sales_count=mt.sales_count,
        sales_xof=mt.sales_xof,
        sales_by_source=mt.sales_by_source,
        cash_declared_xof=mt.cash_declared_xof,
        rps_xof=mt.rps_xof,
        missing_hours=[h for h in mt.missing_hours if h < local.hour],
        counter=counter,
        last_heartbeat_at=last_hb,
    )


class HourOut(BaseModel):
    hour: int
    entries: int
    served: int
    waits: int
    sales_xof: int
    missing: bool


@router.get("/shops/{shop_id}/hourly")
def hourly(shop_id: uuid.UUID, user: CurrentUser, s: DB, date_: DateQ) -> list[HourOut]:
    shop = load_shop(s, shop_id, user, Action.report_view)
    tz = ZoneInfo(shop.timezone)
    day = service.load_day(s, shop, date_)
    missing = set(compute_metrics(day).missing_hours)
    hours = {
        h: HourOut(hour=h, entries=0, served=0, waits=0, sales_xof=0, missing=h in missing) for h in range(24)
    }
    for e in day.events:
        h = e.started_at.astimezone(tz).hour
        if e.type == "entry" and not e.is_staff:
            hours[h].entries += 1
        elif e.type == "service":
            hours[h].served += 1
        elif e.type == "wait":
            hours[h].waits += 1
    for sale in day.sales:
        if sale.source != "cash_declaration":
            hours[sale.occurred_at.astimezone(tz).hour].sales_xof += sale.amount_xof
    return list(hours.values())


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    type: m.EventType
    started_at: datetime
    ended_at: datetime | None
    duration_s: int | None
    is_staff: bool
    confidence: float


@router.get("/shops/{shop_id}/events")
def events(
    shop_id: uuid.UUID, user: CurrentUser, s: DB, date_: DateQ, type: str | None = None
) -> list[EventOut]:
    shop = load_shop(s, shop_id, user, Action.counts_view)
    a, b = service.day_bounds(date_, ZoneInfo(shop.timezone))
    q = select(m.Event).where(m.Event.shop_id == shop.id, m.Event.started_at >= a, m.Event.started_at < b)
    if type:
        try:
            q = q.where(m.Event.type == m.EventType(type))
        except ValueError as exc:
            raise Problem(422, "bad-type", f"unknown event type {type!r}") from exc
    return [EventOut.model_validate(e) for e in s.scalars(q.order_by(m.Event.started_at))]


# ---------- sales ----------
class SaleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    source: m.SaleSource
    amount_xof: int
    occurred_at: datetime
    local_date: date
    external_ref: str | None
    entered_by: uuid.UUID | None
    voided_at: datetime | None


class WebSaleIn(BaseModel):
    """docs/04 SaleIn, restricted to what a person enters by hand in the app."""

    client_id: uuid.UUID | None = None
    source: Literal["quick_log", "cash_declaration"]
    amount_xof: int = Field(ge=1, le=10_000_000)
    occurred_at: datetime


@router.get("/shops/{shop_id}/sales")
def list_sales(shop_id: uuid.UUID, user: CurrentUser, s: DB, date_: DateQ) -> list[SaleOut]:
    load_shop(s, shop_id, user, Action.report_view)
    q = (
        select(m.Sale)
        .where(m.Sale.shop_id == shop_id, m.Sale.local_date == date_)
        .order_by(m.Sale.occurred_at)
    )
    return [SaleOut.model_validate(x) for x in s.scalars(q)]


@router.post("/shops/{shop_id}/sales", status_code=201)
def add_sale(shop_id: uuid.UUID, body: WebSaleIn, user: CurrentUser, s: DB) -> SaleOut:
    action = Action.sale_quick_log if body.source == "quick_log" else Action.sale_cash_declaration
    shop = load_shop(s, shop_id, user, action)
    if body.occurred_at.tzinfo is None:
        raise Problem(422, "validation-error", "occurred_at needs a UTC offset")
    d = body.occurred_at.astimezone(ZoneInfo(shop.timezone)).date()
    if body.client_id is not None and (existing := s.get(m.Sale, body.client_id)) is not None:
        return SaleOut.model_validate(existing)  # retried from the offline queue
    if body.source == "cash_declaration":
        for old in s.scalars(
            select(m.Sale).where(
                m.Sale.shop_id == shop.id,
                m.Sale.local_date == d,
                m.Sale.source == m.SaleSource.cash_declaration,
                m.Sale.voided_at.is_(None),
            )
        ):
            old.voided_at = datetime.now(UTC)
        s.flush()
    sale = m.Sale(
        shop_id=shop.id,
        source=m.SaleSource(body.source),
        amount_xof=body.amount_xof,
        occurred_at=body.occurred_at,
        local_date=d,
        entered_by=user.id,
    )
    if body.client_id is not None:
        sale.id = body.client_id
    s.add(sale)
    s.commit()
    return SaleOut.model_validate(sale)


@router.delete("/shops/{shop_id}/sales/{sale_id}", status_code=204, response_class=Response)
def void_sale(shop_id: uuid.UUID, sale_id: uuid.UUID, user: CurrentUser, s: DB) -> Response:
    """Void one's own hand-entered sale of the shop's current day (docs/08 sales log)."""
    shop = load_shop(s, shop_id, user, Action.sale_quick_log)
    sale = s.get(m.Sale, sale_id)
    if sale is None or sale.shop_id != shop.id:
        raise Problem(404, "not-found", "Sale not found")
    today_local = datetime.now(UTC).astimezone(ZoneInfo(shop.timezone)).date()
    if sale.entered_by != user.id or sale.local_date != today_local:
        raise Problem(403, "forbidden", "Only your own entries of today can be voided")
    sale.voided_at = sale.voided_at or datetime.now(UTC)
    s.commit()
    return Response(status_code=204)


# ---------- corrections ----------
class CorrectionIn(BaseModel):
    local_date: date
    metric: Literal["visitors_in", "served"]
    corrected_value: int = Field(ge=0, le=100_000)
    note: str | None = Field(default=None, max_length=500)


@router.post("/shops/{shop_id}/corrections", status_code=201)
def add_correction(shop_id: uuid.UUID, body: CorrectionIn, user: CurrentUser, s: DB) -> ReportOut | None:
    """AC-F9-1: stored, shown in history, excluded from baselines (served); the report is recomputed."""
    shop = load_shop(s, shop_id, user, Action.correction_create)
    report = s.scalars(
        select(m.DailyReport).where(
            m.DailyReport.shop_id == shop.id, m.DailyReport.local_date == body.local_date
        )
    ).first()
    reported = getattr(report, body.metric) if report is not None else None
    corr = m.DayCorrection(
        shop_id=shop.id,
        local_date=body.local_date,
        metric=body.metric,
        reported_value=reported,
        corrected_value=body.corrected_value,
        note=body.note,
        created_by=user.id,
    )
    s.add(corr)
    s.flush()
    audit(
        s,
        user,
        "correction.create",
        account_id=shop.account_id,
        target_type="day_correction",
        target_id=corr.id,
        detail={"metric": body.metric, "value": body.corrected_value},
    )
    out = None
    if report is not None:
        out = _report_out(s, service.compute(s, shop, body.local_date).row)
    s.commit()
    return out


# ---------- clips ----------
class ClipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    kind: str
    event_id: uuid.UUID | None
    duration_s: int | None
    saved: bool = False
    expires_at: datetime | None
    created_at: datetime


@router.get("/shops/{shop_id}/clips")
def list_clips(shop_id: uuid.UUID, user: CurrentUser, s: DB) -> list[ClipOut]:
    """docs/08 /moments: clips still stored (7 days) and saved ones. Metadata only; playback is audited."""
    load_shop(s, shop_id, user, Action.clip_view)
    now = datetime.now(UTC)
    q = select(m.Clip).where(
        m.Clip.shop_id == shop_id,
        m.Clip.kind == "clip",
        (m.Clip.expires_at.is_(None)) | (m.Clip.expires_at > now),
    )
    out = []
    for c in s.scalars(q.order_by(m.Clip.created_at.desc())):
        item = ClipOut.model_validate(c)
        item.saved = c.saved_by is not None
        out.append(item)
    return out


def _clip_for(s: Any, clip_id: uuid.UUID, user: m.User) -> tuple[m.Clip, m.Shop]:
    clip = s.get(m.Clip, clip_id)
    if clip is None:
        raise Problem(404, "not-found", "Clip not found")
    return clip, load_shop(s, clip.shop_id, user, Action.clip_view)


@router.post("/clips/{clip_id}/save", responses={409: {"description": "limit of 30 reached"}})
def save_clip(clip_id: uuid.UUID, user: CurrentUser, s: DB) -> ClipOut:
    clip, shop = _clip_for(s, clip_id, user)
    now = datetime.now(UTC)
    if clip.expires_at is not None and clip.expires_at <= now:
        raise Problem(410, "clip-expired", "This clip is no longer stored")
    if clip.saved_by is None:
        saved = (
            s.scalar(
                select(func.count())
                .select_from(m.Clip)
                .join(m.Shop, m.Shop.id == m.Clip.shop_id)
                .where(m.Shop.account_id == shop.account_id, m.Clip.saved_by.is_not(None))
            )
            or 0
        )
        if saved >= MAX_SAVED_CLIPS:
            raise Problem(409, "save-limit", f"At most {MAX_SAVED_CLIPS} saved clips per account")
        clip.saved_by, clip.expires_at = user.id, None
        audit(s, user, "clip.save", account_id=shop.account_id, target_type="clip", target_id=clip.id)
    s.commit()
    return ClipOut(**ClipOut.model_validate(clip).model_dump() | {"saved": True})


@router.delete("/clips/{clip_id}/save")
def unsave_clip(clip_id: uuid.UUID, user: CurrentUser, s: DB) -> ClipOut:
    clip, shop = _clip_for(s, clip_id, user)
    if clip.saved_by is not None:
        clip.saved_by = None
        clip.expires_at = max(clip.created_at + CLIP_RETENTION, datetime.now(UTC) + timedelta(hours=1))
        audit(s, user, "clip.unsave", account_id=shop.account_id, target_type="clip", target_id=clip.id)
    s.commit()
    return ClipOut.model_validate(clip)


# ---------- audit log and support grants ----------
class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    account_id: uuid.UUID | None
    actor_id: uuid.UUID | None
    actor_name: str | None = None
    actor_role: m.UserRole | None
    action: str
    target_type: str | None
    target_id: uuid.UUID | None
    detail: dict[str, Any]
    at: datetime


@router.get("/audit-log")
def audit_log(user: CurrentUser, s: DB, limit: int = Query(100, ge=1, le=500)) -> list[AuditOut]:
    """Owner: own account. Support: everything."""
    q = select(m.AuditLog).order_by(m.AuditLog.at.desc()).limit(limit)
    if user.role is not m.UserRole.support:
        require(s, user, Action.audit_view, Resource(account_id=user.account_id))
        q = q.where(m.AuditLog.account_id == user.account_id)
    rows = s.scalars(q).all()
    names = {u.id: u.name for u in s.scalars(select(m.User).where(m.User.id.in_({r.actor_id for r in rows})))}
    out = []
    for r in rows:
        item = AuditOut.model_validate(r)
        item.actor_name = names.get(r.actor_id) if r.actor_id else None
        out.append(item)
    return out


class GrantIn(BaseModel):
    hours: int = Field(default=24, ge=1, le=24)


class GrantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    account_id: uuid.UUID
    expires_at: datetime


@router.post("/support-grants", status_code=201)
def grant_support(body: GrantIn, user: CurrentUser, s: DB) -> GrantOut:
    require(s, user, Action.support_grant_create, Resource(account_id=user.account_id))
    assert user.account_id is not None
    grant = m.SupportGrant(
        account_id=user.account_id,
        granted_by=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=body.hours),
    )
    s.add(grant)
    s.flush()
    audit(
        s,
        user,
        "support.grant",
        account_id=user.account_id,
        target_type="support_grant",
        target_id=grant.id,
        detail={"hours": body.hours},
    )
    s.commit()
    return GrantOut.model_validate(grant)
