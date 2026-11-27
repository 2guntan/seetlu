"""Render Frigate's config.yml from the cloud EdgeConfig (docs/05 "Frigate configuration rendered by the
agent") and refuse any configuration that enables a biometric or identifying feature (CLAUDE.md rule 1)."""

import copy
import hashlib
import math
import os
from pathlib import Path
from typing import Any

import yaml

from seetlu_agent import recorder
from seetlu_agent.edge_config import Camera, EdgeConfig, Zone

TEMPLATE = Path(
    os.environ.get(
        "FRIGATE_TEMPLATE", Path(__file__).resolve().parents[2] / "frigate" / "config.template.yml"
    )
)
DOOR_BAND_PX = 40
ZONE_NAMES = {"customer_side": "counter_customer", "staff_side": "counter_staff", "shelf": "shelf_main"}
# Features that must stay disabled everywhere (globally and per camera).
FORBIDDEN = ("face_recognition", "lpr", "semantic_search", "genai", "audio", "birdseye")


class BiometricsError(ValueError):
    """A rendered config enables a forbidden feature."""


def load_template(path: Path = TEMPLATE) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, dict)
    return data


def _px(points: list[tuple[float, float]], w: int, h: int) -> str:
    out: list[str] = []
    for x, y in points:
        out += [str(round(min(max(x, 0.0), 1.0) * w)), str(round(min(max(y, 0.0), 1.0) * h))]
    return ",".join(out)


def door_bands(zone: Zone, w: int, h: int) -> dict[str, list[tuple[float, float]]]:
    """A door line → two 40 px bands `door_in` / `door_out` on either side (normalised coordinates).

    "left"/"right" is relative to walking along the line from its first to its last point, in image
    coordinates (y grows downwards): for a left-to-right line, left is the upper side of the image.
    """
    (x0, y0), (x1, y1) = zone.geometry[0], zone.geometry[-1]
    dx, dy = (x1 - x0) * w, (y1 - y0) * h
    length = math.hypot(dx, dy) or 1.0
    lx, ly = dy / length, -dx / length  # unit normal pointing to the left side, in pixels
    ox, oy = lx * DOOR_BAND_PX / w, ly * DOOR_BAND_PX / h

    def band(sign: float) -> list[tuple[float, float]]:
        return [(x0, y0), (x1, y1), (x1 + sign * ox, y1 + sign * oy), (x0 + sign * ox, y0 + sign * oy)]

    inward = 1.0 if (zone.inward_side or "left") == "left" else -1.0
    return {"door_in": band(inward), "door_out": band(-inward)}


def _rtsp(cam: Camera, secrets: dict[str, Any]) -> tuple[str, bool]:
    s = secrets.get("cameras", {}).get(cam.name)
    if not s or not s.get("host"):
        return "rtsp://127.0.0.1:554" + cam.rtsp_sub_path, False  # not set up yet on the LAN page
    return recorder.url_for(s, cam.rtsp_sub_path), True  # brand preset + channel, or the raw path


def render(
    cfg: EdgeConfig, secrets: dict[str, Any], template: dict[str, Any] | None = None
) -> dict[str, Any]:
    out = copy.deepcopy(template if template is not None else load_template())
    out.setdefault("ui", {})["timezone"] = cfg.shop.timezone
    cameras: dict[str, Any] = {}
    for cam in cfg.cameras:
        w, h, fps = cam.detect.width, cam.detect.height, cam.detect.fps
        url, ready = _rtsp(cam, secrets)
        zones: dict[str, Any] = {}
        masks: list[str] = []
        for z in cam.zones:
            if z.type == "door_line" and len(z.geometry) >= 2:
                for name, pts in door_bands(z, w, h).items():
                    zones[name] = {"coordinates": _px(pts, w, h), "objects": ["person"]}
            elif z.type in ZONE_NAMES and len(z.geometry) >= 3:
                zones[ZONE_NAMES[z.type]] = {
                    "coordinates": _px([(p[0], p[1]) for p in z.geometry], w, h),
                    "objects": ["person"],
                    "inertia": 3,
                    "loitering_time": 0,
                }
            elif z.type == "ignore" and len(z.geometry) >= 3:
                masks.append(_px([(p[0], p[1]) for p in z.geometry], w, h))
        camera: dict[str, Any] = {
            "enabled": ready,
            "ffmpeg": {"inputs": [{"path": url, "roles": ["detect", "record"]}]},
            "detect": {"enabled": True, "width": w, "height": h, "fps": fps},
            "objects": {"track": ["person"]},
            "snapshots": {"enabled": False},
            "record": {"enabled": True, "retain": {"days": 7, "mode": "motion"}},
            "zones": zones,
        }
        if masks:
            camera["motion"] = {"mask": masks}
        cameras[cam.name] = camera
    out["cameras"] = cameras
    assert_no_biometrics(out)
    return out


def _walk(node: Any, path: str = "") -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    if isinstance(node, dict):
        for k, v in node.items():
            items.append((f"{path}.{k}" if path else str(k), v))
            items += _walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            items += _walk(v, f"{path}[{i}]")
    return items


def assert_no_biometrics(cfg: dict[str, Any]) -> None:
    """Every forbidden feature is present at top level with `enabled: false`; none is enabled anywhere;
    only `person` is tracked; snapshots are off (docs/05, docs/09)."""
    for feature in FORBIDDEN:
        if not isinstance(cfg.get(feature), dict) or cfg[feature].get("enabled") is not False:
            raise BiometricsError(f"{feature} must be explicitly disabled")
    for path, value in _walk(cfg):
        leaf = path.rsplit(".", 1)[-1]
        if leaf in FORBIDDEN and isinstance(value, dict) and value.get("enabled", False) is not False:
            raise BiometricsError(f"{path} is enabled")
        if leaf == "track" and value != ["person"]:
            raise BiometricsError(f"{path} must track only person, got {value!r}")
        if leaf == "snapshots" and isinstance(value, dict) and value.get("enabled") is not False:
            raise BiometricsError(f"{path} must be disabled")
        if leaf in ("attributes", "sub_label", "face", "faces"):
            raise BiometricsError(f"{path} is not allowed")


def dump(cfg: dict[str, Any]) -> str:
    return "# Rendered by seetlu-agent from the cloud EdgeConfig. Do not edit.\n" + yaml.safe_dump(
        cfg, sort_keys=False, allow_unicode=True
    )


def config_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def write_if_changed(text: str, path: Path) -> bool:
    """Write the rendered config; True when it changed (the caller then restarts Frigate)."""
    if path.exists() and config_hash(path.read_text()) == config_hash(text):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(path)
    return True
