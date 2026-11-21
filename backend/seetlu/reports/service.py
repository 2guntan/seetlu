"""Daily report: load a shop day from the database, run the pure engine (domain/report.py), persist the
`daily_reports` row, queue clip commands for the moments and send the template (docs/06, docs/07)."""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from seetlu.db import models as m
from seetlu.domain import commands
from seetlu.domain.report import (
    BASELINE_WINDOW_DAYS,
    ConfidenceInput,
    DayInput,
    EventIn,
    HeartbeatIn,
    Metrics,
    PastDay,
    Report,
    SaleIn,
    build_report,
    compute_metrics,
    is_valid,
)
from seetlu.domain.report_text import daily_report_params
from seetlu.messaging.provider import MessagingProvider, get_provider
from seetlu.phone import rules as phone_rules

log = logging.getLogger(__name__)

TEMPLATE = "daily_report"


def day_bounds(d: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(d, time(0), tzinfo=tz)
    return start, datetime.combine(d + timedelta(days=1), time(0), tzinfo=tz)


def local_date(ts: datetime, tz: ZoneInfo) -> date:
    return ts.astimezone(tz).date()


# ---------- loading ----------
def load_day(s: Session, shop: m.Shop, d: date) -> DayInput:
    tz = ZoneInfo(shop.timezone)
    a, b = day_bounds(d, tz)
    kit_ids = list(s.scalars(select(m.Kit.id).where(m.Kit.shop_id == shop.id)))
    cams = (
        {c.id: c for c in s.scalars(select(m.Camera).where(m.Camera.kit_id.in_(kit_ids)))} if kit_ids else {}
    )
    rows = s.scalars(
        select(m.Event).where(m.Event.shop_id == shop.id, m.Event.started_at >= a, m.Event.started_at < b)
    ).all()
    events = [
        EventIn(
            id=str(e.id),
            type=e.type.value,
            started_at=e.started_at,
            ended_at=e.ended_at,
            is_staff=e.is_staff,
            confidence=float(e.confidence),
            camera=cams[e.camera_id].name if e.camera_id in cams else "",
            camera_role=cams[e.camera_id].role.value if e.camera_id in cams else "",
        )
        for e in rows
    ]
    sales = [
        SaleIn(x.source.value, int(x.amount_xof), x.occurred_at)
        for x in s.scalars(
            select(m.Sale).where(
                m.Sale.shop_id == shop.id, m.Sale.local_date == d, m.Sale.voided_at.is_(None)
            )
        )
    ]
    heartbeats = (
        [
            HeartbeatIn(h.at, {k: float(v) for k, v in (h.fps or {}).items()})
            for h in s.scalars(
                select(m.Heartbeat).where(
                    m.Heartbeat.kit_id.in_(kit_ids), m.Heartbeat.at >= a, m.Heartbeat.at < b
                )
            )
        ]
        if kit_ids
        else []
    )
    return DayInput(
        local_date=d,
        timezone=shop.timezone,
        opening_hours=shop.opening_hours,
        events=events,
        sales=sales,
        heartbeats=heartbeats,
        expected_staff=shop.expected_staff,
        camera_roles={c.name: c.role.value for c in cams.values()},
    )


def served_corrected(s: Session, shop_id: uuid.UUID, d: date) -> bool:
    q = select(m.DayCorrection.id).where(
        m.DayCorrection.shop_id == shop_id,
        m.DayCorrection.local_date == d,
        m.DayCorrection.metric == "served",
    )
    return s.scalars(q).first() is not None


def history(s: Session, shop_id: uuid.UUID, d: date) -> list[PastDay]:
    """Past reports in the baseline window; validity was decided when each was computed."""
    rows = s.scalars(
        select(m.DailyReport).where(
            m.DailyReport.shop_id == shop_id,
            m.DailyReport.local_date >= d - timedelta(days=BASELINE_WINDOW_DAYS),
            m.DailyReport.local_date < d,
        )
    ).all()
    out = []
    for r in rows:
        valid = bool((r.baseline or {}).get("day_valid")) and not served_corrected(s, shop_id, r.local_date)
        out.append(PastDay(r.local_date, r.rps_xof, valid))
    return out


def last_week(s: Session, shop: m.Shop, d: date) -> tuple[Metrics, bool]:
    prev = d - timedelta(days=7)
    metrics = compute_metrics(load_day(s, shop, prev))
    valid = is_valid(metrics, served_corrected=served_corrected(s, shop.id, prev))
    return metrics, valid


def confidence_input(s: Session, shop: m.Shop, report_at: datetime) -> ConfidenceInput:
    kit_ids = list(s.scalars(select(m.Kit.id).where(m.Kit.shop_id == shop.id)))
    passed = (
        s.scalar(
            select(func.max(m.CountCheck.ended_at)).where(
                m.CountCheck.kit_id.in_(kit_ids), m.CountCheck.passed.is_(True)
            )
        )
        if kit_ids
        else None
    )
    phone = s.scalars(
        select(m.PhoneDevice)
        .where(m.PhoneDevice.shop_id == shop.id, m.PhoneDevice.last_seen_at.is_not(None))
        .order_by(m.PhoneDevice.last_seen_at.desc())
    ).first()
    return ConfidenceInput(
        count_check_passed_at=passed,
        phone_last_seen_at=phone.last_seen_at if phone else None,
        phone_parser_current=bool(phone and phone.parser_version == phone_rules.current_version()),
        report_at=report_at,
    )


# ---------- compute + persist ----------
@dataclass
class Computed:
    row: m.DailyReport
    report: Report


def report_time_of(shop: m.Shop, d: date) -> datetime:
    return datetime.combine(d, shop.report_time, tzinfo=ZoneInfo(shop.timezone))


def compute(s: Session, shop: m.Shop, d: date, now: datetime | None = None) -> Computed:
    """Compute (or recompute) the report for shop day `d` and upsert `daily_reports`. Does not send."""
    now = now or datetime.now(UTC)
    report_at = min(now, report_time_of(shop, d)) if now.date() == d else report_time_of(shop, d)
    report = build_report(
        load_day(s, shop, d),
        history(s, shop.id, d),
        confidence_input(s, shop, report_at),
        last_week(s, shop, d),
        shop_active=shop.status == m.ShopStatus.active,
        served_corrected=served_corrected(s, shop.id, d),
    )
    row = s.scalars(
        select(m.DailyReport).where(m.DailyReport.shop_id == shop.id, m.DailyReport.local_date == d)
    ).first()
    if row is None:
        row = m.DailyReport(shop_id=shop.id, local_date=d)
        s.add(row)
    mt = report.metrics
    previous = {mo.get("event_id"): mo for mo in (row.moments or [])}
    row.visitors_in, row.served, row.waits, row.unattended_min = (
        mt.visitors_in,
        mt.served,
        mt.waits,
        mt.unattended_min,
    )
    row.busiest_hour = mt.busiest_hour
    row.sales_count, row.sales_xof, row.sales_by_source = mt.sales_count, mt.sales_xof, mt.sales_by_source
    row.cash_declared_xof, row.rps_xof = mt.cash_declared_xof, mt.rps_xof
    row.baseline = report.baseline.to_json() | {"day_valid": report.valid}
    row.verdict = m.VerdictCode(report.verdict)
    row.confidence = report.confidence
    row.missing_hours = mt.missing_hours
    row.moments = [
        mo.to_json() | {k: v for k, v in previous.get(mo.event_id, {}).items() if k == "clip_command_id"}
        for mo in report.moments
    ]
    row.vs_last_week = report.vs_last_week
    row.computed_at = now
    s.flush()
    return Computed(row, report)


def queue_clips(s: Session, shop: m.Shop, c: Computed, now: datetime) -> None:
    """docs/06: clip commands are queued at report time; links are generated only on request."""
    cams = {
        cam.name: cam
        for cam in s.scalars(
            select(m.Camera).join(m.Kit, m.Kit.id == m.Camera.kit_id).where(m.Kit.shop_id == shop.id)
        )
    }
    out = []
    for mo in c.row.moments:
        cam = cams.get(mo["camera"])
        if cam is not None and not mo.get("clip_command_id"):
            kit = s.get(m.Kit, cam.kit_id)
            assert kit is not None
            params = {
                "camera": cam.name,
                "start": mo["clip_start"],
                "end": mo["clip_end"],
                "event_id": mo["event_id"],
            }
            cmd = commands.enqueue(s, kit, m.CommandType.clip, params, now=now)
            mo = mo | {"clip_command_id": str(cmd.id)}
        out.append(mo)
    c.row.moments = out
    s.flush()


def recipients(s: Session, shop: m.Shop) -> list[m.User]:
    """Owners of the account, plus managers of this shop who opted in to the report."""
    owners = s.scalars(
        select(m.User).where(
            m.User.account_id == shop.account_id,
            m.User.role == m.UserRole.owner,
            m.User.active.is_(True),
            m.User.reports_paused.is_(False),
        )
    ).all()
    managers = s.scalars(
        select(m.User)
        .join(m.UserShop, m.UserShop.user_id == m.User.id)
        .where(
            m.UserShop.shop_id == shop.id,
            m.User.role == m.UserRole.manager,
            m.User.receives_report.is_(True),
            m.User.active.is_(True),
            m.User.reports_paused.is_(False),
        )
    ).all()
    seen: dict[uuid.UUID, m.User] = {u.id: u for u in [*owners, *managers]}
    return sorted(seen.values(), key=lambda u: (u.role.value != "owner", u.phone_e164))


def send(s: Session, shop: m.Shop, c: Computed, provider: MessagingProvider, now: datetime) -> list[str]:
    tz = ZoneInfo(shop.timezone)
    ids = []
    for user in recipients(s, shop):
        lang = "fr"  # Wolof/English templates are v2 (docs/07)
        params = daily_report_params(shop.name, c.row.local_date, tz, c.report, lang)
        ids.append(provider.send_template(user.phone_e164, f"{TEMPLATE}_{lang}", lang, params))
    c.row.sent_at = now
    c.row.message_id = ids[0] if ids else None
    s.flush()
    return ids


def compute_and_send(
    s: Session,
    shop_id: uuid.UUID,
    d: date,
    now: datetime | None = None,
    provider: MessagingProvider | None = None,
    *,
    force: bool = False,
) -> Computed:
    """`force` resends a report that was already sent (dev `make report` / `make e2e` only)."""
    now = now or datetime.now(UTC)
    shop = s.get(m.Shop, shop_id)
    if shop is None:
        raise LookupError(f"shop {shop_id} not found")
    c = compute(s, shop, d, now)
    if c.row.sent_at is None or force:
        queue_clips(s, shop, c, now)
        send(s, shop, c, provider or get_provider(s), now)
    s.commit()
    return c


def recompute(s: Session, shop_id: uuid.UUID, d: date, now: datetime | None = None) -> Computed | None:
    """Late data after the report: recompute, never resend (the app shows « mis à jour »)."""
    shop = s.get(m.Shop, shop_id)
    if shop is None:
        return None
    c = compute(s, shop, d, now)
    s.commit()
    return c


# ---------- scheduling ----------
def due_reports(s: Session, now: datetime) -> list[tuple[uuid.UUID, date]]:
    """Active shops whose local report time has passed today and whose report is not sent yet."""
    out = []
    for shop in s.scalars(select(m.Shop).where(m.Shop.status == m.ShopStatus.active)):
        tz = ZoneInfo(shop.timezone)
        local = now.astimezone(tz)
        if local.time() < shop.report_time:
            continue
        sent = s.scalar(
            select(m.DailyReport.sent_at).where(
                m.DailyReport.shop_id == shop.id, m.DailyReport.local_date == local.date()
            )
        )
        if sent is None:
            out.append((shop.id, local.date()))
    return out


def late_dates(s: Session, shop: m.Shop, starts: list[datetime]) -> list[date]:
    """Local days touched by newly received events whose report was already sent."""
    tz = ZoneInfo(shop.timezone)
    days = sorted({local_date(ts, tz) for ts in starts})
    if not days:
        return []
    sent = set(
        s.scalars(
            select(m.DailyReport.local_date).where(
                m.DailyReport.shop_id == shop.id,
                m.DailyReport.local_date.in_(days),
                m.DailyReport.sent_at.is_not(None),
            )
        )
    )
    return [d for d in days if d in sent]


def report_summary(c: Computed) -> dict[str, Any]:
    r = c.row
    return {
        "local_date": r.local_date.isoformat(),
        "verdict": r.verdict.value,
        "visitors_in": r.visitors_in,
        "served": r.served,
        "sales_xof": r.sales_xof,
        "missing_hours": r.missing_hours,
        "moments": [mo["kind"] for mo in r.moments],
        "baseline": r.baseline,
    }
