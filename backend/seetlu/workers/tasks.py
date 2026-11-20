"""Scheduled report jobs (docs/06): beat ticks every minute and sends each shop's report at its local
`report_time`; late data recomputes a sent report without resending."""

import logging
import uuid
from datetime import UTC, date, datetime

from seetlu.db.session import session_factory
from seetlu.reports import service
from seetlu.workers.celery_app import celery_app

log = logging.getLogger(__name__)


@celery_app.task(name="seetlu.reports.schedule_due")
def schedule_due_reports() -> int:
    with session_factory()() as s:
        due = service.due_reports(s, datetime.now(UTC))
    for shop_id, d in due:
        send_daily_report.delay(str(shop_id), d.isoformat())
    return len(due)


@celery_app.task(name="seetlu.reports.send", autoretry_for=(Exception,), retry_backoff=30, max_retries=5)
def send_daily_report(shop_id: str, local_date: str) -> str:
    with session_factory()() as s:
        c = service.compute_and_send(s, uuid.UUID(shop_id), date.fromisoformat(local_date))
        return c.row.verdict.value


@celery_app.task(name="seetlu.reports.recompute")
def recompute_report(shop_id: str, local_date: str) -> str | None:
    with session_factory()() as s:
        c = service.recompute(s, uuid.UUID(shop_id), date.fromisoformat(local_date))
        return c.row.verdict.value if c else None
