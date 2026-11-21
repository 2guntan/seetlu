"""Inbound WhatsApp messages → actions and replies (docs/07 "Inbound command grammar").

`handle()` is called by the Celery task behind the webhook, and directly by the dev mock inbox.
Rights come from the one authorization function (docs/09 matrix).
"""

import logging
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from seetlu.api.deps import shop_resource, subject_for
from seetlu.core.audit import audit
from seetlu.core.authz import Action, authorize
from seetlu.db import models as m
from seetlu.domain.grammar import parse
from seetlu.domain.report_text import money
from seetlu.i18n import t
from seetlu.messaging import clips
from seetlu.messaging.provider import MessagingProvider
from seetlu.reports import service

log = logging.getLogger(__name__)

CASH_REPLY_WINDOW = timedelta(hours=3)
FAUX_WINDOW = timedelta(minutes=30)
CANCEL_WINDOW = timedelta(minutes=10)


def e164(wa_from: str) -> str:
    return wa_from if wa_from.startswith("+") else f"+{wa_from}"


def user_shops(s: Session, user: m.User) -> list[m.Shop]:
    if user.account_id is None:
        return []
    if user.role is m.UserRole.owner:
        q = select(m.Shop).where(m.Shop.account_id == user.account_id)
    else:
        q = (
            select(m.Shop)
            .join(m.UserShop, m.UserShop.shop_id == m.Shop.id)
            .where(m.UserShop.user_id == user.id)
        )
    return list(s.scalars(q.order_by(m.Shop.created_at)))


def latest_report(s: Session, shops: list[m.Shop]) -> m.DailyReport | None:
    if not shops:
        return None
    return s.scalars(
        select(m.DailyReport)
        .where(m.DailyReport.shop_id.in_([x.id for x in shops]), m.DailyReport.sent_at.is_not(None))
        .order_by(m.DailyReport.sent_at.desc())
    ).first()


def current_shop(s: Session, user: m.User) -> m.Shop | None:
    """The shop of the latest report this user could have received, else their first shop."""
    shops = user_shops(s, user)
    report = latest_report(s, shops)
    if report is not None:
        return next(x for x in shops if x.id == report.shop_id)
    return shops[0] if shops else None


def allowed(s: Session, user: m.User, shop: m.Shop, action: Action) -> bool:
    return authorize(subject_for(s, user), action, shop_resource(s, shop, user))


def shop_today(shop: m.Shop, now: datetime) -> date:
    return now.astimezone(ZoneInfo(shop.timezone)).date()


def day_total(s: Session, shop: m.Shop, d: date) -> int:
    """Money recorded today, as the report counts it (a cash declaration is not added to quick logs)."""
    q = select(m.Sale.source, func.sum(m.Sale.amount_xof)).where(
        m.Sale.shop_id == shop.id, m.Sale.local_date == d, m.Sale.voided_at.is_(None)
    )
    by_source = {src: int(v) for src, v in s.execute(q.group_by(m.Sale.source))}
    if by_source.get(m.SaleSource.quick_log):
        by_source.pop(m.SaleSource.cash_declaration, None)
    return sum(by_source.values())


# ---------- conversation state ----------
def get_session(s: Session, phone: str, now: datetime) -> m.WaSession | None:
    row = s.get(m.WaSession, phone)
    return row if row is not None and row.expires_at > now else None


def set_session(s: Session, phone: str, state: str, context: dict[str, str], expires_at: datetime) -> None:
    stmt = insert(m.WaSession).values(phone_e164=phone, state=state, context=context, expires_at=expires_at)
    s.execute(
        stmt.on_conflict_do_update(
            index_elements=[m.WaSession.phone_e164],
            set_={"state": state, "context": context, "expires_at": expires_at, "updated_at": func.now()},
        )
    )


def clear_session(s: Session, phone: str) -> None:
    row = s.get(m.WaSession, phone)
    if row is not None:
        s.delete(row)


# ---------- the handler ----------
def handle(s: Session, wa_from: str, text: str, provider: MessagingProvider, now: datetime) -> str | None:
    """Process one inbound message; returns the reply text sent (None = no reply)."""
    phone = e164(wa_from)
    user = s.scalars(select(m.User).where(m.User.phone_e164 == phone, m.User.active.is_(True))).first()
    if user is None:
        log.info("inbound from unknown phone %s ignored", phone)  # docs/07: no reply, log only
        return None
    reply = _dispatch(s, user, text, provider, now)
    if reply is not None:
        provider.send_text(phone, reply)
    s.flush()
    return reply


def _dispatch(s: Session, user: m.User, text: str, provider: MessagingProvider, now: datetime) -> str | None:
    lang = user.language.value
    cmd = parse(text)
    shop = current_shop(s, user)
    if cmd.kind == "aide":
        return t("wa.help", lang)
    if cmd.kind == "too_large":
        return t("wa.too_large", lang)
    if shop is None:
        return t("wa.not_allowed", lang)

    if cmd.kind == "moment":
        return _moment(s, user, cmd.value or 1, now)
    if cmd.kind == "photo":
        if not allowed(s, user, shop, Action.snapshot_request):
            return t("wa.not_allowed", lang)
        snap = clips.request_snapshot(s, shop, user, now)
        if snap is None:
            return t("wa.kit_unreachable", lang)
        audit(
            s,
            user,
            "snapshot.request",
            account_id=shop.account_id,
            target_type="edge_command",
            target_id=snap.id,
            detail={"via": "whatsapp", "shop_id": str(shop.id)},
        )
        return t("wa.photo_wait", lang)
    if cmd.kind == "faux":
        if not allowed(s, user, shop, Action.correction_create):
            return t("wa.not_allowed", lang)
        report = latest_report(s, [shop])
        d = report.local_date if report is not None else shop_today(shop, now)
        set_session(
            s,
            user.phone_e164,
            "faux",
            {"shop_id": str(shop.id), "local_date": d.isoformat()},
            now + FAUX_WINDOW,
        )
        return t("wa.faux_ask", lang)
    if cmd.kind == "quick_log":
        if not allowed(s, user, shop, Action.sale_quick_log):
            return t("wa.not_allowed", lang)
        return _quick_log(s, user, shop, cmd.value or 0, now)
    if cmd.kind == "annuler":
        return _cancel(s, user, shop, now)
    if cmd.kind in ("stop", "start"):
        if user.role is not m.UserRole.owner:
            return t("wa.not_allowed", lang)
        user.reports_paused = cmd.kind == "stop"
        return t(f"wa.{cmd.kind}_ok", lang)
    if cmd.kind == "number":
        return _number(s, user, cmd.value or 0, now)
    return t("wa.unknown", lang)


def _moment(s: Session, user: m.User, rank: int, now: datetime) -> str:
    lang = user.language.value
    report = latest_report(s, user_shops(s, user))
    if report is None:
        return t("wa.no_report", lang)
    shop = s.get(m.Shop, report.shop_id)
    assert shop is not None
    if not allowed(s, user, shop, Action.clip_view):
        return t("wa.not_allowed", lang)
    req = clips.request_moment_clip(s, report, rank, user, now)
    if req.status == "no_moment":
        return t("wa.no_moment", lang, rank=rank)
    if req.status == "unavailable":
        return t("wa.clip_unavailable", lang)
    if req.status == "ready" and req.clip is not None:
        return t("wa.clip_link", lang, rank=rank, url=clips.clip_link(req.clip.id, now))
    return t("wa.clip_preparing", lang)


def _quick_log(s: Session, user: m.User, shop: m.Shop, amount: int, now: datetime) -> str:
    d = shop_today(shop, now)
    s.add(
        m.Sale(
            shop_id=shop.id,
            source=m.SaleSource.quick_log,
            amount_xof=amount,
            occurred_at=now,
            local_date=d,
            entered_by=user.id,
        )
    )
    s.flush()
    return t("wa.quick_log_ok", user.language.value, amount=money(amount), total=money(day_total(s, shop, d)))


def _cancel(s: Session, user: m.User, shop: m.Shop, now: datetime) -> str:
    lang = user.language.value
    last = s.scalars(
        select(m.Sale)
        .where(
            m.Sale.entered_by == user.id,
            m.Sale.source == m.SaleSource.quick_log,
            m.Sale.voided_at.is_(None),
            m.Sale.occurred_at >= now - CANCEL_WINDOW,
        )
        .order_by(m.Sale.occurred_at.desc())
    ).first()
    if last is None:
        return t("wa.cancel_none", lang)
    last.voided_at = now
    s.flush()
    sale_shop = s.get(m.Shop, last.shop_id) or shop
    total = day_total(s, sale_shop, last.local_date)
    return t("wa.cancel_ok", lang, amount=money(last.amount_xof), total=money(total))


def _number(s: Session, user: m.User, value: int, now: datetime) -> str:
    """A bare number answers the pending question: `faux` → visitors, cash prompt → cash declaration."""
    lang = user.language.value
    state = get_session(s, user.phone_e164, now)
    if state is None:
        return t("wa.unknown", lang)
    shop = s.get(m.Shop, uuid.UUID(state.context["shop_id"]))
    d = date.fromisoformat(state.context["local_date"])
    clear_session(s, user.phone_e164)
    if shop is None:
        return t("wa.unknown", lang)
    if state.state == "faux" and allowed(s, user, shop, Action.correction_create):
        report = s.scalars(
            select(m.DailyReport).where(m.DailyReport.shop_id == shop.id, m.DailyReport.local_date == d)
        ).first()
        corr = m.DayCorrection(
            shop_id=shop.id,
            local_date=d,
            metric="visitors_in",
            reported_value=report.visitors_in if report else None,
            corrected_value=value,
            note="whatsapp",
            created_by=user.id,
        )
        s.add(corr)
        s.flush()
        detail = {"metric": "visitors_in", "value": value, "via": "whatsapp"}
        audit(
            s,
            user,
            "correction.create",
            account_id=shop.account_id,
            target_type="day_correction",
            target_id=corr.id,
            detail=detail,
        )
        if report is not None:
            service.compute(s, shop, d, now)
        return t("wa.faux_ok", lang, n=value)
    if state.state == "cash_prompt" and allowed(s, user, shop, Action.sale_cash_declaration):
        for old in s.scalars(
            select(m.Sale).where(
                m.Sale.shop_id == shop.id,
                m.Sale.local_date == d,
                m.Sale.source == m.SaleSource.cash_declaration,
                m.Sale.voided_at.is_(None),
            )
        ):
            old.voided_at = now  # AC-F3-5: replace
        s.flush()
        s.add(
            m.Sale(
                shop_id=shop.id,
                source=m.SaleSource.cash_declaration,
                amount_xof=value,
                occurred_at=now,
                local_date=d,
                entered_by=user.id,
            )
        )
        return t("wa.cash_ok", lang, amount=money(value))
    return t("wa.not_allowed", lang)


def open_cash_prompt(s: Session, user: m.User, shop: m.Shop, d: date, now: datetime) -> None:
    set_session(
        s,
        user.phone_e164,
        "cash_prompt",
        {"shop_id": str(shop.id), "local_date": d.isoformat()},
        now + CASH_REPLY_WINDOW,
    )
