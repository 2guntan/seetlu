"""LAN setup page (docs/05): PIN, LAN only, credentials stay on the box (chmod 600), French default."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from seetlu_agent.edge_config import EdgeConfig
from seetlu_agent.setup_page import SecretsStore, create_app, is_lan, load_locale
from tests.fakes import fake_frigate

CFG = EdgeConfig.model_validate(
    {"cameras": [{"name": "door", "role": "door"}, {"name": "counter", "role": "counter"}]}
)


def app(tmp_path: Path, changes: list[int]) -> tuple[TestClient, SecretsStore]:
    store = SecretsStore(tmp_path / "secrets.json")
    a = create_app(
        pin="123456", serial="KIT-1", secrets_store=store, get_config=lambda: CFG, registered=lambda: True,
        on_change=lambda: changes.append(1), frigate=fake_frigate(),
        discover=lambda: [{"host": "192.168.1.20", "xaddrs": "http://192.168.1.20/onvif/device_service"}],
        probe=lambda url: url.startswith("rtsp://admin:pw@192.168.1.20:554/"),
    )  # fmt: skip
    return TestClient(a), store


def test_pin_required(tmp_path: Path) -> None:
    c, _ = app(tmp_path, [])
    assert c.get("/").status_code == 401
    assert c.get("/", auth=("installer", "000000")).status_code == 401
    assert c.get("/", auth=("installer", "123456")).status_code == 200


def test_lan_only() -> None:
    assert is_lan("192.168.1.10") and is_lan("10.0.0.2") and is_lan("127.0.0.1") and is_lan("fe80::1")
    assert not is_lan("41.82.10.10") and not is_lan(None)


def test_page_is_french_by_default(tmp_path: Path) -> None:
    c, _ = app(tmp_path, [])
    page = c.get("/", auth=("i", "123456")).text
    assert "installation du kit" in page and "Caméras" in page
    assert "kit setup" in c.get("/?lang=en", auth=("i", "123456")).text
    assert set(load_locale("en")) == set(load_locale("fr"))


def test_credentials_saved_on_box_only(tmp_path: Path) -> None:
    changes: list[int] = []
    c, _ = app(tmp_path, changes)
    auth = ("i", "123456")
    body = {"host": "192.168.1.20", "port": 554, "username": "admin", "password": "pw"}
    assert c.put("/api/cameras/door", json=body, auth=auth).status_code == 204
    assert changes == [1]  # Frigate config re-rendered
    assert (tmp_path / "secrets.json").stat().st_mode & 0o777 == 0o600
    assert json.loads((tmp_path / "secrets.json").read_text())["cameras"]["door"]["password"] == "pw"
    assert c.put("/api/cameras/nope", json=body, auth=auth).status_code == 404
    assert c.put("/api/cameras/door", json=body | {"host": "x; rm -rf /"}, auth=auth).status_code == 422
    st = c.get("/api/status", auth=auth).json()
    assert st["cameras"] == [{"name": "door", "ready": True}, {"name": "counter", "ready": False}]
    assert "pw" not in json.dumps(st)
    assert c.post("/api/cameras/door/test", auth=auth).json() == {"ok": True}
    assert c.post("/api/cameras/counter/test", auth=auth).status_code == 404


def test_discovery_and_snapshot(tmp_path: Path) -> None:
    c, _ = app(tmp_path, [])
    auth = ("i", "123456")
    assert c.get("/api/discover", auth=auth).json()[0]["host"] == "192.168.1.20"
    r = c.get("/api/cameras/counter/snapshot.jpg", auth=auth)
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
