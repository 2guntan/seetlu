"""Box front panel, agent side (AC-F10-4, docs/13 section 4.3).

The agent runs in a container without GPIO access. It writes the wanted LED state to
`/data/agent/host/led`; the host daemon `seetlu-panel` (edge/os, installed by provision.sh) drives the
LEDs and watches the button. A 10 s hold makes the daemon write `setup-open-until` (epoch seconds) and
restart the agent, which then serves the LAN setup page again for 30 minutes.
"""

from pathlib import Path
from typing import Literal

LedState = Literal["green", "green-blink", "amber", "red"]
STARTING_S = 120.0  # blink until the first successful cloud call, at most this long after start
INTERNET_STALE_S = 180.0  # no successful cloud call for 3 min = no internet


def led_state(*, starting: bool, internet_ok: bool, cameras_ok: bool) -> LedState:
    """Green steady ok, green blinking starting, amber no internet, red no camera stream.
    A missing camera matters more than a missing uplink: the box cannot count at all."""
    if starting:
        return "green-blink"
    if not cameras_ok:
        return "red"
    if not internet_ok:
        return "amber"
    return "green"


def cameras_streaming(camera_names: list[str], fps: dict[str, float]) -> bool:
    """Every configured camera has frames in Frigate's latest stats; no camera configured = red."""
    return bool(camera_names) and all(fps.get(n, 0.0) > 0 for n in camera_names)


def write_led(host_dir: Path, state: LedState) -> bool:
    """Write the state only when it changes; True if written."""
    path = host_dir / "led"
    try:
        if path.read_text().strip() == state:
            return False
    except OSError:
        pass
    host_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(state + "\n")
    tmp.replace(path)
    return True


def setup_open(host_dir: Path, *, activated: bool, now: float) -> bool:
    """The LAN setup page is open during installation, then only in the 30 min after a button hold."""
    if not activated:
        return True
    try:
        until = float((host_dir / "setup-open-until").read_text().strip())
    except (OSError, ValueError):
        return False
    return now < until
