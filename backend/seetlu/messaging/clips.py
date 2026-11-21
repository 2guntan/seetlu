"""Clips and snapshots requested from WhatsApp or the app (docs/06 moments, docs/07 replies, AC-F5-*).

A link sent in WhatsApp opens the web app page `/clips/<id>` (login required); it carries an expiry and
an HMAC so a forwarded link stops working after 24 h (AC-F5-3). The video itself is only ever served
through a 15-minute presigned GET returned by `GET /v1/clips/{id}`, which writes the audit row.
"""

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from seetlu.core.config import get_settings
from seetlu.db import models as m
from seetlu.domain import commands
from seetlu.i18n import t
from seetlu.messaging.provider import MessagingProvider
from seetlu.storage.s3 import presigned_get

LINK_TTL = timedelta(hours=24)
SNAPSHOT_TIMEOUT = timedelta(minutes=2)
EDGE_BUFFER = timedelta(days=7)  # AC-F5-4


# ---------- signed links ----------
def _sig(clip_id: uuid.UUID, exp: int) -> str:
    key = get_settings().jwt_secret.encode()
    return hmac.new(key, f"clip:{clip_id}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]


def clip_link(clip_id: uuid.UUID, now: datetime) -> str:
    exp = int((now + LINK_TTL).timestamp())
    base = get_settings().app_base_url.rstrip("/")
    return f"{base}/clips/{clip_id}?exp={exp}&sig={_sig(clip_id, exp)}"


def link_valid(clip_id: uuid.UUID, exp: int, sig: str, now: datetime) -> bool:
    return hmac.compare_digest(_sig(clip_id, exp), sig) and now.timestamp() <= exp


# ---------- moment → clip ----------
Status = Literal["ready", "queued", "unavailable", "no_moment"]


@dataclass
class ClipRequest:
    status: Status
    clip: m.Clip | None = None
    command: m.EdgeCommand | None = None


def shop_kit(s: Session, shop_id: uuid.UUID) -> m.Kit | None:
    return s.scalars(select(m.Kit).where(m.Kit.shop_id == shop_id).order_by(m.Kit.created_at)).first()


def clip_for_command(s: Session, command_id: uuid.UUID) -> m.Clip | None:
    return s.scalars(select(m.Clip).where(m.Clip.command_id == command_id)).first()


def _watch(cmd: m.EdgeCommand, user: m.User | None) -> None:
    if user is not None and user.id not in cmd.notify_user_ids:
        cmd.notify_user_ids = [*cmd.notify_user_ids, user.id]
        cmd.notified_at = None


def request_moment_clip(
    s: Session, report: m.DailyReport, rank: int, user: m.User | None, now: datetime
) -> ClipRequest:
    """Existing clip, or the queued command (the user is told when it is ready), or unavailable."""
    moments = report.moments or []
    if not 1 <= rank <= len(moments):
        return ClipRequest("no_moment")
    mo = moments[rank - 1]
    cmd = s.get(m.EdgeCommand, uuid.UUID(mo["clip_command_id"])) if mo.get("clip_command_id") else None
    if cmd is not None and cmd.status is m.CommandStatus.done:
        clip = clip_for_command(s, cmd.id)
        if clip is not None and (clip.expires_at is None or clip.expires_at > now):
            return ClipRequest("ready", clip, cmd)
        cmd = None  # the cloud copy expired: ask the edge again (it keeps 7 days)
    if cmd is not None and cmd.status in (m.CommandStatus.failed, m.CommandStatus.unavailable):
        return ClipRequest("unavailable", command=cmd)
    if cmd is None or cmd.expires_at <= now:
        if now - datetime.fromisoformat(mo["started_at"]) > EDGE_BUFFER:
            return ClipRequest("unavailable")
        kit = shop_kit(s, report.shop_id)
        if kit is None:
            return ClipRequest("unavailable")
        params = {
            "camera": mo["camera"],
            "start": mo["clip_start"],
            "end": mo["clip_end"],
            "event_id": mo["event_id"],
        }
        cmd = commands.clip_command(s, kit, params, requested_by=user.id if user else None, now=now)
        report.moments = [*moments[: rank - 1], mo | {"clip_command_id": str(cmd.id)}, *moments[rank:]]
    _watch(cmd, user)
    s.flush()
    return ClipRequest("queued", command=cmd)


def request_snapshot(s: Session, shop: m.Shop, user: m.User, now: datetime) -> m.EdgeCommand | None:
    kit = shop_kit(s, shop.id)
    if kit is None:
        return None
    cmd = commands.enqueue(
        s, kit, m.CommandType.snapshot, {"camera": "counter"}, requested_by=user.id, now=now
    )
    _watch(cmd, user)
    s.flush()
    return cmd


# ---------- answering the people who asked ----------
def _rank_of(s: Session, cmd: m.EdgeCommand) -> int | None:
    reports = s.scalars(
        select(m.DailyReport).where(m.DailyReport.moments.contains([{"clip_command_id": str(cmd.id)}]))
    ).all()
    for r in reports:
        for i, mo in enumerate(r.moments, 1):
            if mo.get("clip_command_id") == str(cmd.id):
                return i
    return None


def notify_command(s: Session, cmd: m.EdgeCommand, provider: MessagingProvider, now: datetime) -> int:
    """Send the result of a finished (or timed-out) clip/snapshot to everyone waiting for it."""
    if not cmd.notify_user_ids or cmd.notified_at is not None:
        return 0
    users = s.scalars(select(m.User).where(m.User.id.in_(cmd.notify_user_ids), m.User.active.is_(True))).all()
    clip = clip_for_command(s, cmd.id) if cmd.status is m.CommandStatus.done else None
    kit = s.get(m.Kit, cmd.kit_id)
    shop = s.get(m.Shop, kit.shop_id) if kit and kit.shop_id else None
    for u in users:
        lang = u.language.value
        if cmd.type is m.CommandType.snapshot:
            if clip is not None and shop is not None:
                local = clip.created_at.astimezone(ZoneInfo(shop.timezone))
                when = t("report.time", lang, h=local.hour, m=f"{local.minute:02d}")
                caption = t("wa.photo_caption", lang, shop=shop.name, time=when)
                provider.send_media_link(u.phone_e164, presigned_get(clip.object_key), caption)
            else:
                provider.send_text(u.phone_e164, t("wa.kit_unreachable", lang))
        elif clip is not None:
            rank = _rank_of(s, cmd) or 1
            provider.send_text(u.phone_e164, t("wa.clip_link", lang, rank=rank, url=clip_link(clip.id, now)))
        else:
            provider.send_text(u.phone_e164, t("wa.clip_unavailable", lang))
    cmd.notified_at = now
    s.flush()
    return len(users)


def notify_stale(s: Session, provider: MessagingProvider, now: datetime) -> int:
    """Snapshots not back after 2 min → « kit injoignable »; clips whose command expired → unavailable."""
    q = select(m.EdgeCommand).where(
        m.EdgeCommand.notified_at.is_(None),
        m.EdgeCommand.notify_user_ids != [],
        m.EdgeCommand.type.in_([m.CommandType.snapshot, m.CommandType.clip]),
    )
    sent = 0
    for cmd in s.scalars(q):
        finished = cmd.status in (m.CommandStatus.done, m.CommandStatus.failed, m.CommandStatus.unavailable)
        timed_out = (
            cmd.type is m.CommandType.snapshot and now - cmd.created_at >= SNAPSHOT_TIMEOUT
        ) or cmd.expires_at <= now
        if finished or timed_out:
            sent += notify_command(s, cmd, provider, now)
    return sent


def now_utc() -> datetime:
    return datetime.now(UTC)
