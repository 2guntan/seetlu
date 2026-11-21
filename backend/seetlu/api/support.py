"""Support console (docs/08, AC-F10-2/3): kits by health, 7 days of heartbeats, commands, OTA target."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from seetlu.api.deps import DB, CurrentUser, shop_resource
from seetlu.core.audit import audit
from seetlu.core.problem import Problem
from seetlu.db import models as m
from seetlu.domain import commands

router = APIRouter(prefix="/v1/support", tags=["support"])
OFFLINE_AFTER = timedelta(minutes=30)


def _support(user: m.User) -> None:
    if user.role is not m.UserRole.support or not user.active:
        raise Problem(403, "forbidden", "Support only")


def health_of(kit: m.Kit, last_hb: datetime | None, queue_depth: int | None, now: datetime) -> m.KitHealth:
    """ok | degraded | offline (AC-F10-2): offline = no heartbeat for 30 min; degraded = a backlog
    of more than 100 queued events or a camera below 2 fps in the last heartbeat."""
    if last_hb is None or now - last_hb > OFFLINE_AFTER:
        return m.KitHealth.offline
    if queue_depth is not None and queue_depth > 100:
        return m.KitHealth.degraded
    return m.KitHealth.ok


class SupportKitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    serial: str
    shop_id: uuid.UUID | None
    shop_name: str | None = None
    status: m.KitStatus
    health: m.KitHealth
    agent_version: str | None
    frigate_version: str | None
    target_agent_version: str | None
    config_version: int
    last_heartbeat_at: datetime | None = None
    queue_depth: int | None = None
    min_fps: float | None = None


def _kit_row(s: DB, kit: m.Kit, now: datetime) -> SupportKitOut:
    hb = s.scalars(
        select(m.Heartbeat).where(m.Heartbeat.kit_id == kit.id).order_by(m.Heartbeat.at.desc())
    ).first()
    out = SupportKitOut.model_validate(kit)
    shop = s.get(m.Shop, kit.shop_id) if kit.shop_id else None
    out.shop_name = shop.name if shop else None
    if hb is not None:
        out.last_heartbeat_at, out.queue_depth = hb.at, hb.queue_depth
        fps = [float(v) for v in (hb.fps or {}).values()]
        out.min_fps = min(fps) if fps else None
    health = health_of(kit, out.last_heartbeat_at, out.queue_depth, now)
    if health is m.KitHealth.ok and out.min_fps is not None and out.min_fps < 2:
        health = m.KitHealth.degraded
    out.health = health
    return out


@router.get("/kits")
def list_kits(
    user: CurrentUser, s: DB, health: Literal["ok", "degraded", "offline"] | None = None
) -> list[SupportKitOut]:
    _support(user)
    now = datetime.now(UTC)
    rows = [_kit_row(s, k, now) for k in s.scalars(select(m.Kit).order_by(m.Kit.serial))]
    return [r for r in rows if health is None or r.health.value == health]


class HeartbeatPoint(BaseModel):
    hour: datetime
    count: int
    min_fps: float | None
    max_queue_depth: int | None
    max_cpu_temp_c: float | None


class SupportKitDetail(SupportKitOut):
    heartbeats_7d: list[HeartbeatPoint]
    config: dict[str, object]


@router.get("/kits/{kit_id}")
def kit_detail(kit_id: uuid.UUID, user: CurrentUser, s: DB) -> SupportKitDetail:
    """Kit page: hourly heartbeat aggregates for 7 days (sparklines) and the config the agent gets."""
    _support(user)
    kit = s.get(m.Kit, kit_id)
    if kit is None:
        raise Problem(404, "not-found", "Kit not found")
    now = datetime.now(UTC)
    hour = func.date_trunc("hour", m.Heartbeat.at)
    rows = s.execute(
        select(hour, func.count(), func.max(m.Heartbeat.queue_depth), func.max(m.Heartbeat.cpu_temp_c))
        .where(m.Heartbeat.kit_id == kit.id, m.Heartbeat.at >= now - timedelta(days=7))
        .group_by(hour)
        .order_by(hour)
    ).all()
    points = [
        HeartbeatPoint(hour=h, count=n, min_fps=None, max_queue_depth=q, max_cpu_temp_c=t)
        for h, n, q, t in rows
    ]
    from seetlu.api.edge import build_config  # same config the agent receives

    base = _kit_row(s, kit, now)
    config = build_config(s, kit).model_dump(mode="json") if kit.shop_id else {}
    return SupportKitDetail(**base.model_dump(), heartbeats_7d=points, config=config)


class TargetIn(BaseModel):
    version: str | None = Field(default=None, max_length=40, pattern=r"^[0-9A-Za-z.\-+]+$")


@router.put("/kits/{kit_id}/target-version")
def set_target(kit_id: uuid.UUID, body: TargetIn, user: CurrentUser, s: DB) -> SupportKitOut:
    """AC-F10-3: the agent sees the target in its config and updates itself."""
    _support(user)
    kit = s.get(m.Kit, kit_id)
    if kit is None:
        raise Problem(404, "not-found", "Kit not found")
    kit.target_agent_version = body.version
    kit.config_version += 1
    shop = s.get(m.Shop, kit.shop_id) if kit.shop_id else None
    audit(
        s,
        user,
        "kit.target_version",
        account_id=shop.account_id if shop else None,
        target_type="kit",
        target_id=kit.id,
        detail={"version": body.version},
    )
    s.commit()
    return _kit_row(s, kit, datetime.now(UTC))


class CommandIn(BaseModel):
    type: Literal["snapshot", "reboot"]


class QueuedOut(BaseModel):
    command_id: uuid.UUID


@router.post("/kits/{kit_id}/commands", status_code=202)
def kit_command(kit_id: uuid.UUID, body: CommandIn, user: CurrentUser, s: DB) -> QueuedOut:
    """Snapshot only with an active owner grant (docs/09); every support action is audited (rule 5)."""
    _support(user)
    kit = s.get(m.Kit, kit_id)
    if kit is None:
        raise Problem(404, "not-found", "Kit not found")
    shop = s.get(m.Shop, kit.shop_id) if kit.shop_id else None
    if body.type == "snapshot" and (shop is None or not shop_resource(s, shop, user).support_grant_active):
        raise Problem(403, "grant-required", "The owner must grant support access first")
    cmd = commands.enqueue(
        s,
        kit,
        m.CommandType(body.type),
        {"camera": "counter"} if body.type == "snapshot" else {},
        requested_by=user.id,
    )
    audit(
        s,
        user,
        "support.access",
        account_id=shop.account_id if shop else None,
        target_type="kit",
        target_id=kit.id,
        detail={"command": body.type, "command_id": str(cmd.id)},
    )
    s.commit()
    return QueuedOut(command_id=cmd.id)
