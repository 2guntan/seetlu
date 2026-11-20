"""Audit log writer (docs/09: clip.view, clip.save, snapshot.request, zone.update, correction.create,
support.access, user.invite, kit.activate, count_check.override)."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from seetlu.db.models import AuditLog, User


def audit(
    s: Session,
    actor: User | None,
    action: str,
    *,
    account_id: uuid.UUID | None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    row = AuditLog(
        account_id=account_id,
        actor_id=actor.id if actor else None,
        actor_role=actor.role if actor else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail or {},
    )
    s.add(row)
    s.flush()
    return row
