"""EdgeConfig as served by `GET /v1/edge/config` (docs/04), plus opening-hours helpers."""

from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Detect(_Model):
    width: int = 640
    height: int = 360
    fps: int = 5


class Zone(_Model):
    id: str
    type: Literal["door_line", "customer_side", "staff_side", "shelf", "ignore"]
    geometry: list[list[float]]
    inward_side: Literal["left", "right"] | None = None


class Camera(_Model):
    name: str
    role: Literal["door", "counter", "shelf"]
    rtsp_main_path: str = "/stream1"
    rtsp_sub_path: str = "/stream2"
    detect: Detect = Field(default_factory=Detect)
    zones: list[Zone] = []


class ShopConfig(_Model):
    timezone: str = "Africa/Dakar"
    opening_hours: dict[str, list[list[str]]] = {}
    expected_staff: int = 0
    service_min_s: int = 15
    wait_min_s: int = 180
    unattended_min_s: int = 300


class EdgeConfig(_Model):
    config_version: int = 0
    shop: ShopConfig = Field(default_factory=ShopConfig)
    cameras: list[Camera] = []
    target_agent_version: str | None = None
    activated: bool = False  # the LAN setup page closes once the kit is active (AC-F10-4)

    def camera_for(self, role: str, default: str) -> str:
        return next((c.name for c in self.cameras if c.role == role), default)


def _hm(value: str) -> time:
    hh, mm = value.split(":")
    if hh == "24":
        return time(23, 59, 59)
    return time(int(hh), int(mm))


class OpeningHours:
    """Opening intervals as epoch seconds, from `{"mon": [["08:00", "21:00"]], ...}` in a shop timezone."""

    def __init__(self, hours: dict[str, list[list[str]]], timezone: str) -> None:
        self.hours = hours
        self.tz = ZoneInfo(timezone)

    def _day(self, d: date) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        for start, end in self.hours.get(DAYS[d.weekday()], []):
            a = datetime.combine(d, _hm(start), tzinfo=self.tz).timestamp()
            b = datetime.combine(d, _hm(end), tzinfo=self.tz).timestamp()
            if b > a:
                out.append((a, b))
        return out

    def intervals(self, a: float, b: float) -> list[tuple[float, float]]:
        """Opening intervals that overlap [a, b], in time order."""
        d0 = datetime.fromtimestamp(a, self.tz).date() - timedelta(days=1)
        d1 = datetime.fromtimestamp(b, self.tz).date()
        out: list[tuple[float, float]] = []
        d = d0
        while d <= d1:
            out += [(o, c) for o, c in self._day(d) if o < b and c > a]
            d += timedelta(days=1)
        return out

    def is_open(self, ts: float, margin_s: float = 0) -> bool:
        return any(o - margin_s <= ts < c + margin_s for o, c in self.intervals(ts - margin_s, ts + margin_s))
