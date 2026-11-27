"""LAN setup page (docs/05, docs/13): PIN, LAN only, credentials stay on the box (chmod 600), French default,
recorder brand presets and channel scan (AC-F8-5/6), stream check (AC-F8-7), setup window (AC-F10-4)."""

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from seetlu_agent.edge_config import EdgeConfig
from seetlu_agent.setup_page import SecretsStore, create_app, is_lan, load_locale
from tests.fakes import fake_frigate

CFG = EdgeConfig.model_validate(
    {"cameras": [{"name": "door", "role": "door"}, {"name": "counter", "role": "counter"}]}
)


GOOD = {"reachable": True, "codec": "h264", "width": 704, "height": 576, "fps": 6.0}


def app(
    tmp_path: Path,
    changes: list[int],
    reports: list[tuple[str, dict[str, Any]]] | None = None,
    is_open: bool = True,
    channels: tuple[int, ...] = (1, 2, 3),
    seen: list[str] | None = None,
) -> tuple[TestClient, SecretsStore]:
    store = SecretsStore(tmp_path / "secrets.json")
    urls = seen if seen is not None else []

    def check(url: str) -> dict[str, Any]:
        urls.append(url)
        return GOOD if "192.168.1.20:554/" in url else {"reachable": False}

    def grab(url: str) -> bytes | None:
        urls.append(url)
        return b"\xff\xd8jpeg" if any(f"/Streaming/Channels/{c}02" in url for c in channels) else None

    a = create_app(
        pin="123456", serial="KIT-1", secrets_store=store, get_config=lambda: CFG, registered=lambda: True,
        on_change=lambda: changes.append(1), frigate=fake_frigate(),
        discover=lambda: [{"host": "192.168.1.20", "xaddrs": "http://192.168.1.20/onvif/device_service"}],
        stream_check=check, grab=grab,
        on_stream=lambda name, rep: (reports if reports is not None else []).append((name, rep)),
        is_open=lambda: is_open,
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
    assert c.put("/api/cameras/door", json=body, auth=auth).status_code == 200
    assert changes == [1]  # Frigate config re-rendered
    assert (tmp_path / "secrets.json").stat().st_mode & 0o777 == 0o600
    assert json.loads((tmp_path / "secrets.json").read_text())["cameras"]["door"]["password"] == "pw"
    assert c.put("/api/cameras/nope", json=body, auth=auth).status_code == 404
    assert c.put("/api/cameras/door", json=body | {"host": "x; rm -rf /"}, auth=auth).status_code == 422
    st = c.get("/api/status", auth=auth).json()
    assert st["cameras"] == [{"name": "door", "ready": True}, {"name": "counter", "ready": False}]
    assert "pw" not in json.dumps(st)
    assert c.post("/api/cameras/door/test", auth=auth).json()["verdict"] == "ok"
    assert c.post("/api/cameras/counter/test", auth=auth).status_code == 404


def test_discovery_and_snapshot(tmp_path: Path) -> None:
    c, _ = app(tmp_path, [])
    auth = ("i", "123456")
    assert c.get("/api/discover", auth=auth).json()[0]["host"] == "192.168.1.20"
    r = c.get("/api/cameras/counter/snapshot.jpg", auth=auth)
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"


AUTH = ("i", "123456")
LOGIN = {"brand": "hikvision", "host": "192.168.1.20", "username": "admin", "password": "pw"}


def test_ac_f8_6_scan_lists_channels_with_thumbnails_and_stops_after_empty_run(tmp_path: Path) -> None:
    seen: list[str] = []
    c, _ = app(tmp_path, [], channels=(1, 3), seen=seen)
    found = c.post("/api/recorder/scan", json=LOGIN, auth=AUTH).json()
    assert [f["channel"] for f in found] == [1, 3]
    assert len(seen) == 3 + 4  # channels 1..3, then 4 misses in a row (4..7) end the scan
    r = c.get(found[1]["thumbnail"], auth=AUTH)
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert c.get("/api/recorder/channels/9.jpg", auth=AUTH).status_code == 404
    assert c.post("/api/recorder/scan", json=LOGIN | {"brand": "other"}, auth=AUTH).status_code == 422


def test_ac_f8_5_brand_preset_and_channel_build_the_stream_url(tmp_path: Path) -> None:
    seen: list[str] = []
    reports: list[tuple[str, dict[str, Any]]] = []
    c, store = app(tmp_path, [], reports=reports, seen=seen)
    r = c.put("/api/cameras/counter", json=LOGIN | {"channel": 3}, auth=AUTH)
    assert r.status_code == 200 and r.json()["verdict"] == "ok"
    assert seen[-1] == "rtsp://admin:pw@192.168.1.20:554/Streaming/Channels/302"
    assert store.load()["cameras"]["counter"]["channel"] == 3
    # AC-F8-7: the report sent to the cloud names the channel, never the login
    name, rep = reports[-1]
    assert name == "counter" and rep["source"] == "hikvision 192.168.1.20 ch3" and rep["codec"] == "h264"
    assert "pw" not in json.dumps(rep) and "admin" not in json.dumps(rep)


def test_ac_f8_6_one_channel_cannot_be_both_door_and_counter(tmp_path: Path) -> None:
    c, _ = app(tmp_path, [])
    assert c.put("/api/cameras/door", json=LOGIN | {"channel": 1}, auth=AUTH).status_code == 200
    assert c.put("/api/cameras/counter", json=LOGIN | {"channel": 1}, auth=AUTH).status_code == 409
    assert c.put("/api/cameras/counter", json=LOGIN | {"channel": 2}, auth=AUTH).status_code == 200
    assert c.put("/api/cameras/door", json=LOGIN | {"channel": 1}, auth=AUTH).status_code == 200  # same slot


def test_ac_f8_6_door_and_counter_slots_exist_before_the_cloud_config(tmp_path: Path) -> None:
    from seetlu_agent import setup_page

    empty = EdgeConfig()
    a = setup_page.create_app(pin="123456", serial="K", secrets_store=SecretsStore(tmp_path / "s.json"),
                              get_config=lambda: empty, registered=lambda: False, on_change=lambda: None,
                              frigate=fake_frigate())  # fmt: skip
    names = [x["name"] for x in TestClient(a).get("/api/status", auth=AUTH).json()["cameras"]]
    assert names == ["door", "counter"]


def test_ac_f10_4_setup_page_closed_after_activation(tmp_path: Path) -> None:
    c, _ = app(tmp_path, [], is_open=False)
    r = c.get("/", auth=AUTH)
    assert r.status_code == 403 and "10 s" in r.text
    assert c.get("/", auth=("i", "000000")).status_code == 401  # PIN still checked first
