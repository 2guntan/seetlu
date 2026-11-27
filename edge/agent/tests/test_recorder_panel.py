"""Recorder presets and stream rules (AC-F8-5, AC-F8-7), front panel LED and setup window (AC-F10-4)."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from seetlu_agent import frigate_config, panel, recorder
from seetlu_agent.edge_config import EdgeConfig


@pytest.mark.parametrize(
    ("brand", "path"),
    [
        ("hikvision", "/Streaming/Channels/402"),
        ("dahua", "/cam/realmonitor?channel=4&subtype=1"),
        ("xiongmai", "/user=admin&password=p%40ss&channel=4&stream=1.sdp?real_stream"),
    ],
)
def test_ac_f8_5_brand_presets(brand: recorder.Brand, path: str) -> None:
    assert recorder.sub_path(brand, 4, "admin", "p@ss") == path


def test_ac_f8_5_url_and_source_label() -> None:
    hik = {"brand": "hikvision", "host": "10.0.0.5", "port": 554, "username": "admin", "password": "p@ss",
           "channel": 2}  # fmt: skip
    assert recorder.url_for(hik, "/x") == "rtsp://admin:p%40ss@10.0.0.5:554/Streaming/Channels/202"
    xm = hik | {"brand": "xiongmai"}
    assert recorder.url_for(xm, "/x").startswith("rtsp://10.0.0.5:554/user=admin&password=p%40ss")
    other = {"brand": "other", "host": "10.0.0.9", "path": "/live/sub?token=1"}
    assert recorder.url_for(other, "/stream2") == "rtsp://10.0.0.9:554/live/sub?token=1"
    assert (
        recorder.url_for({"host": "10.0.0.9"}, "/stream2") == "rtsp://10.0.0.9:554/stream2"
    )  # saved before presets
    for s in (hik, xm, other):
        label = recorder.source_label(s)
        assert "p@ss" not in label and "admin" not in label and "token" not in label
    assert recorder.source_label(hik) == "hikvision 10.0.0.5 ch2"


@pytest.mark.parametrize(
    ("info", "verdict"),
    [
        ({"reachable": False}, "unreachable"),
        ({"reachable": True, "codec": "mjpeg", "width": 704, "height": 576, "fps": 6}, "bad_codec"),
        ({"reachable": True, "codec": "hevc", "width": 352, "height": 288, "fps": 6}, "too_small"),
        ({"reachable": True, "codec": "h264", "width": 640, "height": 360, "fps": 4}, "low_fps"),
        ({"reachable": True, "codec": "h264", "width": 640, "height": 480, "fps": 5}, "ok"),
    ],
)
def test_ac_f8_7_verdict_matches_cloud_rules(info: dict[str, Any], verdict: str) -> None:
    assert recorder.verdict(info) == verdict


def test_ac_f8_7_fps_parsing() -> None:
    assert recorder._fps("25/1") == 25.0 and recorder._fps("15000/1001") == 14.99
    assert recorder._fps("0/0") is None and recorder._fps(None) is None


def test_ac_f8_5_frigate_reads_the_recorder_channel() -> None:
    cfg = EdgeConfig.model_validate({"cameras": [{"name": "door", "role": "door"}]})
    secrets = {"cameras": {"door": {"brand": "dahua", "host": "192.168.1.108", "port": 554, "username": "u",
                                    "password": "p", "channel": 5}}}  # fmt: skip
    out = yaml.safe_load(frigate_config.dump(frigate_config.render(cfg, secrets)))
    path = out["cameras"]["door"]["ffmpeg"]["inputs"][0]["path"]
    assert path == "rtsp://u:p@192.168.1.108:554/cam/realmonitor?channel=5&subtype=1"


@pytest.mark.parametrize(
    ("starting", "internet", "cameras", "state"),
    [
        (True, False, False, "green-blink"),
        (False, True, False, "red"),
        (False, False, False, "red"),
        (False, False, True, "amber"),
        (False, True, True, "green"),
    ],
)
def test_ac_f10_4_led_state(starting: bool, internet: bool, cameras: bool, state: str) -> None:
    assert panel.led_state(starting=starting, internet_ok=internet, cameras_ok=cameras) == state


def test_ac_f10_4_cameras_streaming() -> None:
    assert panel.cameras_streaming(["door", "counter"], {"door": 5.0, "counter": 4.8})
    assert not panel.cameras_streaming(["door", "counter"], {"door": 5.0, "counter": 0.0})
    assert not panel.cameras_streaming([], {})


def test_ac_f10_4_led_file_written_on_change_only(tmp_path: Path) -> None:
    assert panel.write_led(tmp_path, "amber")
    assert not panel.write_led(tmp_path, "amber")
    assert (tmp_path / "led").read_text() == "amber\n"


def test_ac_f10_4_setup_window(tmp_path: Path) -> None:
    assert panel.setup_open(tmp_path, activated=False, now=1000)
    assert not panel.setup_open(tmp_path, activated=True, now=1000)
    (tmp_path / "setup-open-until").write_text("2800\n")
    assert panel.setup_open(tmp_path, activated=True, now=1000)
    assert not panel.setup_open(tmp_path, activated=True, now=2800)


# ---------- host daemon edge/os/seetlu-panel.py ----------
def _daemon() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "os" / "seetlu-panel.py"
    spec = importlib.util.spec_from_file_location("seetlu_panel", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ac_f10_4_daemon_drives_led_class_devices(tmp_path: Path) -> None:
    d = _daemon()
    for name in ("green", "red"):
        (tmp_path / f"seetlu:{name}").mkdir()
    d.apply_led("amber", tmp_path)
    assert (tmp_path / "seetlu:green" / "brightness").read_text() == "1"
    assert (tmp_path / "seetlu:red" / "brightness").read_text() == "1"
    d.apply_led("green-blink", tmp_path)
    assert (tmp_path / "seetlu:green" / "trigger").read_text() == "timer"
    assert (tmp_path / "seetlu:red" / "brightness").read_text() == "0"
    d.apply_led("green", tmp_path / "missing")  # no overlay loaded: no crash


def test_ac_f10_4_button_hold_10_s_opens_setup_for_30_min(tmp_path: Path) -> None:
    d = _daemon()
    hold = d.HoldDetector()
    hold.key(True, 100.0)
    assert not hold.due(109.9)
    assert hold.due(110.0) and not hold.due(115.0)  # once per press
    hold.key(False, 116.0)
    hold.key(True, 200.0)
    hold.key(False, 205.0)  # short press: nothing
    assert not hold.due(220.0)
    d.open_setup(1000.0, tmp_path, restart=False)
    assert panel.setup_open(tmp_path, activated=True, now=1000 + 30 * 60 - 1)
    assert not panel.setup_open(tmp_path, activated=True, now=1000 + 30 * 60)
    assert json.loads((tmp_path / "setup-open-until").read_text()) == 2800
