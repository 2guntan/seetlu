"""Scenario files (docs/10-testing.md) parsed into typed objects."""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

DateType = date  # the Scenario.date field shadows the name inside the class

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"


def _t(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


@dataclass(frozen=True)
class Staff:
    id: str
    arrive: time
    leave: time
    breaks: tuple[tuple[time, time], ...] = ()


@dataclass(frozen=True)
class Customers:
    count: int
    window: tuple[time, time]
    peak: tuple[time, time] | None = None
    served_ratio: float = 0.8
    service_s: tuple[int, int] = (20, 120)
    wait_ratio: float = 0.0
    group_size: int = 1


@dataclass(frozen=True)
class AfterHours:
    at: time


@dataclass(frozen=True)
class Flicker:
    count: int
    window: tuple[time, time]


Actor = Staff | Customers | AfterHours | Flicker


@dataclass(frozen=True)
class Scenario:
    name: str
    timezone: str
    date: date
    opening: tuple[time, time]
    actors: tuple[Actor, ...]
    outages: tuple[tuple[time, time], ...] = ()
    expected_staff: int = 0
    seed: int = 1
    cameras: dict[str, str] = field(default_factory=lambda: {"door": "door", "counter": "counter"})

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def at(self, t: time, day_offset: int = 0) -> float:
        """Local wall time on the scenario day → unix epoch seconds."""
        local = datetime.combine(self.date + timedelta(days=day_offset), t, tzinfo=self.tz)
        return local.timestamp()

    def with_date(self, d: DateType) -> "Scenario":
        return Scenario(
            self.name, self.timezone, d, self.opening, self.actors, self.outages, self.expected_staff,
            self.seed, self.cameras,
        )  # fmt: skip


def _actor(raw: dict[str, Any]) -> Actor:
    kind = raw["kind"]
    if kind == "staff":
        return Staff(
            id=str(raw["id"]),
            arrive=_t(raw["arrive"]),
            leave=_t(raw["leave"]),
            breaks=tuple((_t(a), _t(b)) for a, b in raw.get("breaks", [])),
        )
    if kind == "customers":
        peak = raw.get("peak")
        return Customers(
            count=int(raw["count"]),
            window=(_t(raw["window"][0]), _t(raw["window"][1])),
            peak=(_t(peak[0]), _t(peak[1])) if peak else None,
            served_ratio=float(raw.get("served_ratio", 0.8)),
            service_s=(int(raw.get("service_s", [20, 120])[0]), int(raw.get("service_s", [20, 120])[1])),
            wait_ratio=float(raw.get("wait_ratio", 0.0)),
            group_size=int(raw.get("group_size", 1)),
        )
    if kind == "after_hours":
        return AfterHours(at=_t(raw["at"]))
    if kind == "flicker":
        return Flicker(count=int(raw["count"]), window=(_t(raw["window"][0]), _t(raw["window"][1])))
    raise ValueError(f"unknown actor kind {kind!r}")


def load(name_or_path: str | Path) -> Scenario:
    path = Path(name_or_path)
    if not path.suffix:
        path = SCENARIOS_DIR / str(name_or_path) / "scenario.yml"
    raw = yaml.safe_load(path.read_text())
    d = raw["date"] if isinstance(raw["date"], date) else date.fromisoformat(str(raw["date"]))
    return Scenario(
        name=str(raw.get("name", path.parent.name)),
        timezone=str(raw["shop_timezone"]),
        date=d,
        opening=(_t(raw["opening"][0]), _t(raw["opening"][1])),
        actors=tuple(_actor(a) for a in raw["actors"]),
        outages=tuple((_t(a), _t(b)) for a, b in raw.get("outages", [])),
        expected_staff=int(raw.get("expected_staff", 0)),
        seed=int(raw.get("seed", 1)),
    )


def names() -> list[str]:
    return sorted(p.name for p in SCENARIOS_DIR.iterdir() if (p / "scenario.yml").exists())
