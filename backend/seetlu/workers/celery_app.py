"""Celery application (worker + beat)."""

from celery import Celery

from seetlu.core.config import get_settings

settings = get_settings()

celery_app = Celery("seetlu", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(timezone="UTC", enable_utc=True, task_acks_late=True)


@celery_app.task(name="seetlu.ping")
def ping() -> str:
    return "pong"
