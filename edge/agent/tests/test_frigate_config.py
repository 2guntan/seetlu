"""Frigate config rendering (docs/05) and the no-biometrics assertion (CLAUDE.md rule 1, docs/09)."""

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from seetlu_agent.edge_config import EdgeConfig
from seetlu_agent.frigate_config import (
    FORBIDDEN,
    BiometricsError,
    assert_no_biometrics,
    door_bands,
    dump,
    load_template,
    render,
    write_if_changed,
)

CFG = EdgeConfig.model_validate(
    {
        "config_version": 3,
        "shop": {"timezone": "Africa/Dakar"},
        "cameras": [
            {
                "name": "door",
                "role": "door",
                "rtsp_sub_path": "/stream2",
                "detect": {"width": 640, "height": 360, "fps": 5},
                "zones": [
                    {
                        "id": "z1",
                        "type": "door_line",
                        "geometry": [[0.1, 0.5], [0.9, 0.5]],
                        "inward_side": "right",
                    }
                ],
            },
            {
                "name": "counter",
                "role": "counter",
                "zones": [
                    {"id": "z2", "type": "customer_side", "geometry": [[0, 0.5], [1, 0.5], [1, 1], [0, 1]]},
                    {"id": "z3", "type": "staff_side", "geometry": [[0, 0], [1, 0], [1, 0.5], [0, 0.5]]},
                    {"id": "z4", "type": "shelf", "geometry": [[0, 0], [0.2, 0], [0.2, 0.2]]},
                    {"id": "z5", "type": "ignore", "geometry": [[0.8, 0], [1, 0], [1, 0.1]]},
                ],
            },
        ],
    }
)
SECRETS = {"cameras": {"door": {"host": "192.168.1.20", "username": "admin", "password": "p@ss:w/rd"}}}


def test_rendered_config_has_no_biometrics() -> None:
    out = render(CFG, SECRETS)
    assert_no_biometrics(out)
    for feature in FORBIDDEN:
        assert out[feature] == {"enabled": False}
    assert out["objects"]["track"] == ["person"]
    assert out["snapshots"]["enabled"] is False
    text = dump(out)
    for word in ("face_recognition: true", "lpr:\n  enabled: true", "attributes"):
        assert word not in text


@pytest.mark.parametrize("feature", FORBIDDEN)
def test_enabling_any_forbidden_feature_is_refused(feature: str) -> None:
    out = render(CFG, SECRETS)
    bad = copy.deepcopy(out)
    bad[feature] = {"enabled": True}
    with pytest.raises(BiometricsError):
        assert_no_biometrics(bad)
    per_camera = copy.deepcopy(out)
    per_camera["cameras"]["door"][feature] = {"enabled": True}
    with pytest.raises(BiometricsError):
        assert_no_biometrics(per_camera)
    missing = copy.deepcopy(out)
    del missing[feature]
    with pytest.raises(BiometricsError):
        assert_no_biometrics(missing)


@pytest.mark.parametrize(
    "patch",
    [
        {"objects": {"track": ["person", "car"]}},
        {"snapshots": {"enabled": True}},
    ],
)
def test_other_unsafe_settings_are_refused(patch: dict[str, Any]) -> None:
    out = render(CFG, SECRETS) | patch
    with pytest.raises(BiometricsError):
        assert_no_biometrics(out)


def test_render_refuses_a_bad_template() -> None:
    tpl = load_template()
    tpl["face_recognition"] = {"enabled": True}
    with pytest.raises(BiometricsError):
        render(CFG, SECRETS, tpl)


def test_cameras_zones_and_streams() -> None:
    out = render(CFG, SECRETS)
    door = out["cameras"]["door"]
    assert door["enabled"] is True
    assert door["ffmpeg"]["inputs"] == [
        {"path": "rtsp://admin:p%40ss%3Aw%2Frd@192.168.1.20:554/stream2", "roles": ["detect", "record"]}
    ]
    assert door["detect"] == {"enabled": True, "width": 640, "height": 360, "fps": 5}
    assert door["record"]["retain"] == {"days": 7, "mode": "motion"}
    assert set(door["zones"]) == {"door_in", "door_out"}
    counter = out["cameras"]["counter"]
    assert counter["enabled"] is False  # no RTSP credentials entered on the LAN page yet
    assert set(counter["zones"]) == {"counter_customer", "counter_staff", "shelf_main"}
    for z in ("counter_customer", "counter_staff"):
        assert counter["zones"][z]["inertia"] == 3 and counter["zones"][z]["loitering_time"] == 0
    assert counter["zones"]["counter_customer"]["coordinates"] == "0,180,640,180,640,360,0,360"
    assert counter["motion"]["mask"] == ["512,0,640,0,640,36"]


def test_door_bands_follow_inward_side() -> None:
    zone = CFG.cameras[0].zones[0]  # horizontal line, left → right; "right" = lower half of the image
    bands = door_bands(zone, 640, 360)
    in_y = max(y for _, y in bands["door_in"])
    out_y = min(y for _, y in bands["door_out"])
    assert in_y == pytest.approx(0.5 + 40 / 360)
    assert out_y == pytest.approx(0.5 - 40 / 360)
    left = zone.model_copy(update={"inward_side": "left"})
    assert door_bands(left, 640, 360)["door_in"] == bands["door_out"]


def test_write_only_when_changed(tmp_path: Path) -> None:
    path = tmp_path / "config" / "config.yml"
    text = dump(render(CFG, SECRETS))
    assert write_if_changed(text, path) is True
    assert write_if_changed(text, path) is False
    assert yaml.safe_load(path.read_text())["cameras"]["door"]["zones"]
    assert write_if_changed(text + "# x\n", path) is True
