#!/usr/bin/env python3
"""seetlu-panel: host daemon for the box front panel (AC-F10-4, docs/13 section 4.3). Standard library only.

LEDs: two Linux LED-class devices from the `seetlu-panel` device-tree overlay (edge/os/seetlu-panel.dts):
`/sys/class/leds/seetlu:green` and `/sys/class/leds/seetlu:red`; amber = both on; blinking uses the kernel
`timer` trigger. The wanted state is written by the agent to /data/agent/host/led.

Button: a gpio-keys input device from the same overlay sending KEY_RESTART. Held for 10 s, the daemon writes
/data/agent/host/setup-open-until (now + 30 min) and restarts the agent container, which serves the LAN
setup page again for 30 minutes.
"""

import os
import select
import struct
import subprocess
import sys
import time
from pathlib import Path

HOST_DIR = Path(os.environ.get("SEETLU_HOST_DIR", "/data/agent/host"))
LEDS_DIR = Path(os.environ.get("SEETLU_LEDS_DIR", "/sys/class/leds"))
BUTTON_DEVICE = os.environ.get("SEETLU_BUTTON_DEVICE", "/dev/input/by-path/platform-seetlu-keys-event")
AGENT_CONTAINER = os.environ.get("SEETLU_AGENT_CONTAINER", "seetlu-edge-seetlu-agent-1")
HOLD_S = 10.0
OPEN_S = 30 * 60.0
KEY_RESTART = 0x198
EV_KEY = 0x01
EVENT = struct.Struct("llHHi")  # struct input_event on 64-bit Linux: timeval, type, code, value

# state -> (green, red), each "on" | "off" | "blink"
LED_MAP = {
    "green": ("on", "off"),
    "green-blink": ("blink", "off"),
    "amber": ("on", "on"),
    "red": ("off", "on"),
}


def _write(path: Path, value: str) -> None:
    try:
        path.write_text(value)
    except OSError:
        pass  # LED not present (overlay not loaded yet): the box still works


def set_led(leds_dir: Path, name: str, mode: str) -> None:
    led = leds_dir / f"seetlu:{name}"
    if mode == "blink":
        _write(led / "trigger", "timer")
        _write(led / "delay_on", "500")
        _write(led / "delay_off", "500")
    else:
        _write(led / "trigger", "none")
        _write(led / "brightness", "1" if mode == "on" else "0")


def apply_led(state: str, leds_dir: Path = LEDS_DIR) -> None:
    green, red = LED_MAP.get(state, LED_MAP["green-blink"])
    set_led(leds_dir, "green", green)
    set_led(leds_dir, "red", red)


class HoldDetector:
    """Fires once per press when the button stays down for HOLD_S."""

    def __init__(self, hold_s: float = HOLD_S) -> None:
        self.hold_s = hold_s
        self.pressed_at: float | None = None
        self.fired = False

    def key(self, down: bool, now: float) -> None:
        if down and self.pressed_at is None:
            self.pressed_at, self.fired = now, False
        elif not down:
            self.pressed_at = None

    def due(self, now: float) -> bool:
        if self.pressed_at is not None and not self.fired and now - self.pressed_at >= self.hold_s:
            self.fired = True
            return True
        return False


def open_setup(now: float, host_dir: Path = HOST_DIR, restart: bool = True) -> None:
    host_dir.mkdir(parents=True, exist_ok=True)
    (host_dir / "setup-open-until").write_text(f"{now + OPEN_S:.0f}\n")
    if restart:
        subprocess.run(["docker", "restart", AGENT_CONTAINER], check=False, timeout=60)  # noqa: S603, S607


def main() -> int:
    hold = HoldDetector()
    shown = None
    fd = None
    while True:
        if fd is None:
            try:
                fd = os.open(BUTTON_DEVICE, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                fd = None
        try:
            state = (HOST_DIR / "led").read_text().strip()
        except OSError:
            state = "green-blink"
        if state != shown:
            apply_led(state)
            shown = state
        now = time.monotonic()
        if fd is not None and select.select([fd], [], [], 0.25)[0]:
            try:
                data = os.read(fd, EVENT.size * 64)
            except OSError:
                os.close(fd)
                fd = None
                continue
            for i in range(0, len(data) - EVENT.size + 1, EVENT.size):
                _s, _us, etype, code, value = EVENT.unpack_from(data, i)
                if etype == EV_KEY and code == KEY_RESTART:
                    hold.key(value != 0, now)
        else:
            time.sleep(0.25)
        if hold.due(time.monotonic()):
            open_setup(time.time())


if __name__ == "__main__":
    sys.exit(main())
