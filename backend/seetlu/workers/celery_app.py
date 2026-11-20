"""Celery application (worker + beat)."""

from celery import Celery

from seetlu.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "seetlu", broker=settings.redis_url, backend=settings.redis_url, include=["seetlu.workers.tasks"]
)
celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    beat_schedule={
        # every minute: send the reports whose shop-local report_time has passed (docs/06 scheduling)
        "reports-due": {"task": "seetlu.reports.schedule_due", "schedule": 60.0},
    },
)


@celery_app.task(name="seetlu.ping")
def ping() -> str:
    return "pong"
