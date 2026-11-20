"""Edge command queue (docs/05 "Commands"). The agent polls; nothing is pushed to the box."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

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


def object_key(shop_id: uuid.UUID, cmd: m.EdgeCommand) -> str | None:
    kind = UPLOAD_KINDS.get(cmd.type)
    if kind is None:
        return None
    folder, ext, _ = kind
    return f"shops/{shop_id}/{folder}s/{cmd.id}.{ext}"
