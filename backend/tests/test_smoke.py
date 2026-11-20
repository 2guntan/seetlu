from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from seetlu.main import app
from seetlu.messaging import mock_inbox
from seetlu.messaging.provider import MockProvider


def test_m0_healthz() -> None:
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_m2_mock_inbox_lists_provider_messages(migrated_engine: Engine, db: Session) -> None:
    MockProvider(db).send_template("+221770000000", "otp_fr", "fr", ["123456"])
    db.commit()
    inbox = mock_inbox.create_app()
    factory = sessionmaker(bind=migrated_engine)

    def _db() -> Iterator[Session]:
        with factory() as s:
            yield s

    inbox.dependency_overrides[mock_inbox.get_db] = _db
    client = TestClient(inbox)
    msgs = client.get("/messages", params={"to": "+221770000000"}).json()
    assert len(msgs) == 1 and msgs[0]["template"] == "otp_fr" and msgs[0]["params"] == ["123456"]
    assert client.delete("/messages").status_code == 204
    assert client.get("/messages").json() == []


def test_m0_celery_ping_registered() -> None:
    from seetlu.workers.celery_app import celery_app

    assert "seetlu.ping" in celery_app.tasks
