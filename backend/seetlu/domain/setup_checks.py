"""Install checks for the AI box on the shop's existing recorder (docs/13, AC-F8-6..8).

The box reports each camera's sub stream (codec, size, fps) as it sees it; the installer ticks an angle
checklist on the camera's snapshot. Activation needs exactly one door and one counter camera, each with a
usable stream and a passed angle check done on that same stream source.
"""

from typing import Any, Literal

from seetlu.db import models as m

USABLE_CODECS = {"h264", "hevc"}  # hardware-decoded on RK3588
MIN_WIDTH, MIN_HEIGHT = 640, 360  # AC-F8-7: CIF 352x288 is too small to count at the door
MIN_FPS = 5.0

ANGLE_ITEMS: dict[str, tuple[str, ...]] = {  # AC-F8-8
    "door": ("doorway_in_frame", "person_big_enough"),
    "counter": ("customer_side_visible", "staff_side_visible"),
}

StreamVerdict = Literal["ok", "low_fps", "unreachable", "bad_codec", "too_small"]


def stream_verdict(report: dict[str, Any] | None) -> StreamVerdict | None:
    """None: never reported. `low_fps` is a warning only; the others block activation."""
    if report is None:
        return None
    if not report.get("reachable"):
        return "unreachable"
    if str(report.get("codec") or "").lower() not in USABLE_CODECS:
        return "bad_codec"
    if int(report.get("width") or 0) < MIN_WIDTH or int(report.get("height") or 0) < MIN_HEIGHT:
        return "too_small"
    if float(report.get("fps") or 0) < MIN_FPS:
        return "low_fps"
    return "ok"


def stream_usable(report: dict[str, Any] | None) -> bool:
    return stream_verdict(report) in ("ok", "low_fps")


def angle_passed(kit: m.Kit, name: str) -> bool:
    """Passed on the stream source the box reports now (a channel change asks for a new check)."""
    angle = kit.angle_checks.get(name)
    stream = kit.stream_checks.get(name)
    return bool(angle and angle.get("passed") and stream and angle.get("source") == stream.get("source"))


def addon_camera_needed(kit: m.Kit, name: str) -> bool:
    angle = kit.angle_checks.get(name)
    stream = kit.stream_checks.get(name)
    return bool(angle and not angle.get("passed") and stream and angle.get("source") == stream.get("source"))


def blockers(kit: m.Kit, cameras: list[m.Camera]) -> list[str]:
    """Problem codes that stop activation, in the order the installer fixes them."""
    roles = [c.role for c in cameras]
    if roles.count(m.CameraRole.door) != 1 or roles.count(m.CameraRole.counter) != 1:
        return ["cameras-required"]  # AC-F8-6
    out: list[str] = []
    for cam in sorted(cameras, key=lambda c: c.name):
        if cam.role not in (m.CameraRole.door, m.CameraRole.counter):
            continue
        if not stream_usable(kit.stream_checks.get(cam.name)):
            out.append(f"stream-check-failed:{cam.name}")  # AC-F8-7
        elif addon_camera_needed(kit, cam.name):
            out.append(f"addon-camera-needed:{cam.name}")  # AC-F8-8
        elif not angle_passed(kit, cam.name):
            out.append(f"angle-check-required:{cam.name}")
    return out
