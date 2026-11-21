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


@celery_app.task(name="seetlu.whatsapp.process_inbound")
def process_inbound(inbound_id: str) -> str | None:
    from seetlu.messaging.processing import process
    from seetlu.messaging.provider import get_provider

    with session_factory()() as s:
        return process(s, uuid.UUID(inbound_id), get_provider(s), datetime.now(UTC))


@celery_app.task(name="seetlu.alerts.evaluate")
def evaluate_alerts() -> int:
    from seetlu.alerts.service import evaluate_all
    from seetlu.messaging.provider import get_provider

    with session_factory()() as s:
        return evaluate_all(s, get_provider(s), datetime.now(UTC))


@celery_app.task(name="seetlu.whatsapp.cash_prompts")
def cash_prompts() -> int:
    from seetlu.alerts.service import send_cash_prompts
    from seetlu.messaging.provider import get_provider

    with session_factory()() as s:
        return send_cash_prompts(s, get_provider(s), datetime.now(UTC))


@celery_app.task(name="seetlu.whatsapp.sweep")
def whatsapp_sweep() -> int:
    """Unprocessed inbound messages, and clip/snapshot requesters still waiting (snapshot timeout 2 min)."""
    from seetlu.messaging import clips, processing
    from seetlu.messaging.provider import get_provider

    with session_factory()() as s:
        provider = get_provider(s)
        now = datetime.now(UTC)
        n = processing.sweep(s, provider, now)
        n += clips.notify_stale(s, provider, now)
        s.commit()
        return n
