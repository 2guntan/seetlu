"""Run stored inbound messages through the handler exactly once."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from seetlu.db import models as m
from seetlu.messaging.inbound import handle
from seetlu.messaging.provider import MessagingProvider


def process(s: Session, inbound_id: uuid.UUID, provider: MessagingProvider, now: datetime) -> str | None:
    row = s.get(m.WaInbound, inbound_id, with_for_update=True)
    if row is None or row.processed_at is not None:
        s.commit()
        return None
    reply = handle(s, row.from_phone, row.body or "", provider, now)
    row.processed_at = now
    s.commit()
    return reply


def sweep(s: Session, provider: MessagingProvider, now: datetime) -> int:
    """Messages stored but never processed (broker was down), older than 1 min and younger than 1 day."""
    ids = list(
        s.scalars(
            select(m.WaInbound.id).where(
                m.WaInbound.processed_at.is_(None),
                m.WaInbound.received_at < now - timedelta(minutes=1),
                m.WaInbound.received_at > now - timedelta(days=1),
            )
        )
    )
    for inbound_id in ids:
        process(s, inbound_id, provider, now)
    return len(ids)
