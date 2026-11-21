"""Edge command queue (docs/05 "Commands"). The agent polls; nothing is pushed to the box."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from seetlu.db import models as m

DEFAULT_TTL = {
    m.CommandType.clip: timedelta(hours=24),
    m.CommandType.snapshot: timedelta(minutes=2),  # docs/07: photo timeout 2 min
    m.CommandType.count_check_start: timedelta(minutes=10),
    m.CommandType.count_check_stop: timedelta(minutes=10),
    m.CommandType.update_agent: timedelta(days=1),
    m.CommandType.reboot: timedelta(minutes=30),
}
UPLOAD_KINDS = {
    m.CommandType.clip: ("clip", "mp4", "video/mp4"),
    m.CommandType.snapshot: ("snapshot", "jpg", "image/jpeg"),
}


def enqueue(
    s: Session,
    kit: m.Kit,
    type_: m.CommandType,
    params: dict[str, Any] | None = None,
    *,
    requested_by: uuid.UUID | None = None,
    ttl: timedelta | None = None,
    now: datetime | None = None,
) -> m.EdgeCommand:
    now = now or datetime.now(UTC)
    cmd = m.EdgeCommand(
        kit_id=kit.id,
        type=type_,
        params=params or {},
        requested_by=requested_by,
        expires_at=now + (ttl or DEFAULT_TTL[type_]),
    )
    s.add(cmd)
    s.flush()
    return cmd


def reusable_clip_command(
    s: Session, kit_id: uuid.UUID, event_id: str, now: datetime
) -> m.EdgeCommand | None:
    """A clip command for this event that is still useful: waiting on the kit, or done with a live clip.

    A report can be rebuilt from scratch (late data, `make e2e`); asking the kit again for the same
    event would cut and upload the same video twice and list it twice under Moments.
    """
    cmds = s.scalars(
        select(m.EdgeCommand)
        .where(
            m.EdgeCommand.kit_id == kit_id,
            m.EdgeCommand.type == m.CommandType.clip,
            m.EdgeCommand.params["event_id"].astext == event_id,
        )
        .order_by(m.EdgeCommand.created_at.desc())
    )
    for cmd in cmds:
        if cmd.status in (m.CommandStatus.queued, m.CommandStatus.sent) and cmd.expires_at > now:
            return cmd
        if cmd.status is m.CommandStatus.done:
            clip = s.scalars(select(m.Clip).where(m.Clip.command_id == cmd.id)).first()
            if clip is not None and (clip.expires_at is None or clip.expires_at > now):
                return cmd
    return None


def clip_command(
    s: Session,
    kit: m.Kit,
    params: dict[str, Any],
    *,
    requested_by: uuid.UUID | None = None,
    now: datetime | None = None,
) -> m.EdgeCommand:
    """Reuse the live clip command for `params["event_id"]`, or queue a new one."""
    now = now or datetime.now(UTC)
    existing = reusable_clip_command(s, kit.id, str(params["event_id"]), now)
    if existing is not None:
        return existing
    return enqueue(s, kit, m.CommandType.clip, params, requested_by=requested_by, now=now)


def object_key(shop_id: uuid.UUID, cmd: m.EdgeCommand) -> str | None:
    kind = UPLOAD_KINDS.get(cmd.type)
    if kind is None:
        return None
    folder, ext, _ = kind
    return f"shops/{shop_id}/{folder}s/{cmd.id}.{ext}"
