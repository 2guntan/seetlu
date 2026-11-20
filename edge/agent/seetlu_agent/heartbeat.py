"""Heartbeat body (docs/04 Heartbeat, AC-F10-1), sent every 5 min."""

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from seetlu_agent import __version__
from seetlu_agent.events import iso

EVERY_S = 300.0


def cpu_temp_c(path: Path = Path("/sys/class/thermal/thermal_zone0/temp")) -> float | None:
    try:
        return round(int(path.read_text().strip()) / 1000, 1)
    except (OSError, ValueError):
        return None


def storage_pct(path: str = "/data") -> int | None:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return round(100 * usage.used / usage.total) if usage.total else None


def network(sys_net: Path = Path("/sys/class/net")) -> str | None:
    """wwan*/usb*/ppp* up → 4g; wl* up → wifi; any other non-loopback link up → ethernet."""
    try:
        links = {p.name: (p / "operstate").read_text().strip() for p in sys_net.iterdir()}
    except OSError:
        return None
    up = [n for n, state in links.items() if state in ("up", "unknown") and n != "lo"]
    if any(n.startswith(("wwan", "usb", "ppp")) for n in up):
        return "4g"
    if any(n.startswith("wl") for n in up):
        return "wifi"
    if any(n.startswith(("eth", "en")) for n in up):
        return "ethernet"
    return None


def build(
    at: float,
    stats: dict[str, Any],
    queue_depth: int,
    probes: dict[str, Callable[[], Any]] | None = None,
) -> dict[str, Any]:
    """`power_source` is `mains` and `battery_pct` is omitted until the kit's mini-UPS model (and its
    status interface) is chosen (docs/12 H1, docs/decisions.md)."""
    p: dict[str, Callable[[], Any]] = {
        "cpu_temp_c": cpu_temp_c,
        "storage_pct": storage_pct,
        "network": network,
    }
    p |= probes or {}
    fps = {
        name: float(cam.get("camera_fps", 0.0))
        for name, cam in (stats.get("cameras") or {}).items()
        if isinstance(cam, dict)
    }
    body: dict[str, Any] = {
        "at": iso(at),
        "agent_version": __version__,
        "power_source": "mains",
        "battery_pct": None,
        "storage_pct": p["storage_pct"](),
        "cpu_temp_c": p["cpu_temp_c"](),
        "fps": fps,
        "network": p["network"](),
        "frigate_version": (stats.get("service") or {}).get("version"),
        "queue_depth": queue_depth,
    }
    return {k: v for k, v in body.items() if v is not None}
