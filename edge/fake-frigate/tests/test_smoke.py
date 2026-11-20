from fastapi.testclient import TestClient

from fake_frigate.generator import FRIGATE_VERSION
from fake_frigate.http import create_app


def test_m0_fake_frigate_version() -> None:
    client = TestClient(create_app())
    assert client.get("/api/version").json() == FRIGATE_VERSION
