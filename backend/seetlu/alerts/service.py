"""Alerts and the evening cash prompt, run every minute by beat (docs/06 Alerts + Scheduling, AC-F3-5)."""

import logging
import uuid
from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from seetlu.db import models as m
from seetlu.domain.alerts import Alert, AlertFacts, EventFact, Rule, SentFact, decide
from seetlu.domain.report import opening_intervals
from seetlu.i18n import t
from seetlu.messaging.inbound import open_cash_prompt
from seetlu.messaging.provider import MessagingProvider
from seetlu.reports.service import day_bounds, recipients

log = logging.getLogger(__name__)
TEMPLATE_ALERT = "alert"
TEMPLATE_CASH = "cash_prompt"


def _hm(value: str, default: str) -> time:
    return time.fromisoformat(value or default)


def facts(s: Session, shop: m.Shop, now: datetime) -> AlertFacts:
    tz = ZoneInfo(shop.timezone)
    d = now.astimezone(tz).date()
    a, b = day_bounds(d, tz)
    events = [
        EventFact(str(e.id), e.type.value, e.started_at, e.ended_at)
        for e in s.scalars(
            select(m.Event).where(m.Event.shop_id == shop.id, m.Event.started_at >= a, m.Event.started_at < b)
        )
    ]
    kit_ids = list(
        s.scalars(select(m.Kit.id).where(m.Kit.shop_id == shop.id, m.Kit.status == m.KitStatus.active))
    )
    last_hb = (
        s.scalar(select(func.max(m.Heartbeat.at)).where(m.Heartbeat.kit_id.in_(kit_ids))) if kit_ids else None
    )
    rules = {
        r.type.value: Rule(r.enabled, {k: int(v) for k, v in (r.params or {}).items()})
        for r in s.scalars(select(m.AlertRule).where(m.AlertRule.shop_id == shop.id))
    }
    sent = [
        SentFact(x.type.value, str(x.event_id) if x.event_id else None, x.sent_at)
        for x in s.scalars(
            select(m.AlertSent).where(m.AlertSent.shop_id == shop.id, m.AlertSent.local_date == d)
        )
    ]
    quiet = shop.quiet_hours or {}
    return AlertFacts(
        now=now,
        tz=tz,
        opening=opening_intervals(d, tz, shop.opening_hours),
        quiet_start=_hm(quiet.get("start", ""), "22:00"),
        quiet_end=_hm(quiet.get("end", ""), "07:00"),
        rules=rules,
        events=events,
        last_heartbeat=last_hb,
        sent_today=sent,
    )


def alert_text(alert: Alert, tz: ZoneInfo, lang: str) -> str:
    local = alert.at.astimezone(tz)
    hhmm = t("report.time", lang, h=local.hour, m=f"{local.minute:02d}")
    return t(f"alert.{alert.type}", lang, time=hhmm, min=alert.minutes or 0)


def evaluate_shop(s: Session, shop: m.Shop, provider: MessagingProvider, now: datetime) -> list[Alert]:
    f = facts(s, shop, now)
    due = decide(f)
    if not due:
        return []
    people = recipients(s, shop)
    d = now.astimezone(f.tz).date()
    for alert in due:
        message_id = None
        for user in people:
            lang = "fr"  # Wolof/English templates are v2 (docs/07)
            params = [shop.name, alert_text(alert, f.tz, lang)]
            mid = provider.send_template(user.phone_e164, f"{TEMPLATE_ALERT}_{lang}", lang, params)
            message_id = message_id or mid
        s.add(
            m.AlertSent(
                shop_id=shop.id,
                type=m.AlertType(alert.type),
                local_date=d,
                event_id=uuid.UUID(alert.event_id) if alert.event_id else None,
                sent_at=now,
                message_id=message_id,
            )
        )
    s.flush()
    return due


def evaluate_all(s: Session, provider: MessagingProvider, now: datetime) -> int:
    n = 0
    for shop in s.scalars(select(m.Shop).where(m.Shop.status == m.ShopStatus.active)):
        try:
            n += len(evaluate_shop(s, shop, provider, now))
            s.commit()
        except Exception:
            s.rollback()
            log.exception("alert evaluation failed for shop %s", shop.id)
    return n


# ---------- cash prompt ----------
def cash_prompt_people(s: Session, shop: m.Shop) -> list[m.User]:
    """The shop's managers; the owner(s) when the shop has no manager (AC-F3-5)."""
    managers = s.scalars(
        select(m.User)
        .join(m.UserShop, m.UserShop.user_id == m.User.id)
        .where(m.UserShop.shop_id == shop.id, m.User.role == m.UserRole.manager, m.User.active.is_(True))
    ).all()
    if managers:
        return list(managers)
    return list(
        s.scalars(
            select(m.User).where(
                m.User.account_id == shop.account_id, m.User.role == m.UserRole.owner, m.User.active.is_(True)
            )
        )
    )


def send_cash_prompts(s: Session, provider: MessagingProvider, now: datetime) -> int:
    sent = 0
    for shop in s.scalars(select(m.Shop).where(m.Shop.status == m.ShopStatus.active)):
        tz = ZoneInfo(shop.timezone)
        local = now.astimezone(tz)
        if local.time() < shop.cash_prompt_time or not opening_intervals(
            local.date(), tz, shop.opening_hours
        ):
            continue
        claim = insert(m.ScheduledSend).values(shop_id=shop.id, kind="cash_prompt", local_date=local.date())
        if s.execute(claim.on_conflict_do_nothing().returning(m.ScheduledSend.shop_id)).first() is None:
            continue  # already sent today
        for user in cash_prompt_people(s, shop):
            provider.send_template(user.phone_e164, f"{TEMPLATE_CASH}_fr", "fr", [shop.name])
            open_cash_prompt(s, user, shop, local.date(), now)
            sent += 1
        s.commit()
    return sent
