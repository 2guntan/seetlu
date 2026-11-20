from fastapi.testclient import TestClient

from seetlu.main import app
from seetlu.messaging.mock_inbox import create_app as create_mock_inbox


def test_m0_healthz() -> None:
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_m0_mock_inbox_roundtrip() -> None:
    client = TestClient(create_mock_inbox())
    assert client.post("/messages", json={"to": "+221770000000", "text": "test"}).status_code == 201
    msgs = client.get("/messages").json()
    assert len(msgs) == 1 and msgs[0]["to"] == "+221770000000"
    assert client.delete("/messages").status_code == 204
    assert client.get("/messages").json() == []


def test_m0_celery_ping_registered() -> None:
    from seetlu.workers.celery_app import celery_app

    assert "seetlu.ping" in celery_app.tasks
