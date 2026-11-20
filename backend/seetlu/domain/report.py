"""Daily report engine (docs/06): metrics, validity, baseline, verdict, confidence, moments, comparison.

Pure functions over plain data. Money is integer XOF; ratios are `Decimal` (never float).
"""

import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MOBILE_SOURCES = ("wave", "orange_money", "quick_log", "pos")
MIN_SERVED = 10
LEARNING_DAYS = 14
BASELINE_WINDOW_DAYS = 56
BASELINE_MAX_DAYS = 28
MAD_FLOOR = Decimal("0.10")
MISSING_MAX = Decimal("0.25")
STAFF_FALLBACK_BEFORE = time(11, 0)
CLIP_BEFORE_S = 5
CLIP_AFTER_S = 15
MAX_MOMENTS = 3
CENT = Decimal("0.01")


# ---------- inputs ----------
@dataclass(frozen=True)
class EventIn:
    id: str
    type: str
    started_at: datetime
    ended_at: datetime | None = None
    is_staff: bool = False
    confidence: float = 1.0
    camera: str = ""
    camera_role: str = ""

    @property
    def duration_s(self) -> float:
        return 0.0 if self.ended_at is None else (self.ended_at - self.started_at).total_seconds()


@dataclass(frozen=True)
class SaleIn:
    source: str
    amount_xof: int
    occurred_at: datetime


@dataclass(frozen=True)
class HeartbeatIn:
    at: datetime
    fps: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class DayInput:
    local_date: date
    timezone: str
    opening_hours: dict[str, list[list[str]]]
    events: list[EventIn]
    sales: list[SaleIn]
    heartbeats: list[HeartbeatIn]
    expected_staff: int = 0
    camera_roles: dict[str, str] = field(default_factory=dict)  # camera name → door|counter|shelf

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


# ---------- opening hours ----------
def _hm(value: str) -> time:
    hh, mm = value.split(":")
    return time(23, 59, 59) if hh == "24" else time(int(hh), int(mm))


def opening_intervals(
    d: date, tz: ZoneInfo, hours: dict[str, list[list[str]]]
) -> list[tuple[datetime, datetime]]:
    out = []
    for start, end in hours.get(DAYS[d.weekday()], []):
        a, b = datetime.combine(d, _hm(start), tzinfo=tz), datetime.combine(d, _hm(end), tzinfo=tz)
        if b > a:
            out.append((a, b))
    return out


def opening_hour_slots(d: date, tz: ZoneInfo, hours: dict[str, list[list[str]]]) -> list[int]:
    """Local clock hours that overlap opening hours (08:00-21:00 → 8..20; 07:30-22:00 → 7..21)."""
    slots: set[int] = set()
    for a, b in opening_intervals(d, tz, hours):
        h = a.replace(minute=0, second=0, microsecond=0)
        while h < b:
            slots.add(h.hour)
            h += timedelta(hours=1)
    return sorted(slots)


def _in_opening(ts: datetime, intervals: list[tuple[datetime, datetime]]) -> bool:
    return any(a <= ts < b for a, b in intervals)


# ---------- metrics ----------
@dataclass(frozen=True)
class Metrics:
    visitors_in: int
    served: int
    waits: int
    unattended_min: int
    busiest_hour: int | None
    sales_count: int
    sales_xof: int
    sales_by_source: dict[str, int]
    cash_declared_xof: int | None
    rps_xof: Decimal | None
    missing_hours: list[int]
    opening_hours_count: int
    hourly_entries: dict[int, int]

    @property
    def missing_ratio(self) -> Decimal:
        if not self.opening_hours_count:
            return Decimal(0)
        return Decimal(len(self.missing_hours)) / Decimal(self.opening_hours_count)

    @property
    def incomplete(self) -> bool:
        return self.missing_ratio > MISSING_MAX


def local_hour(ts: datetime, tz: ZoneInfo) -> int:
    return ts.astimezone(tz).hour


def compute_metrics(day: DayInput) -> Metrics:
    tz = day.tz
    intervals = opening_intervals(day.local_date, tz, day.opening_hours)
    by_type: dict[str, list[EventIn]] = {}
    for e in day.events:
        by_type.setdefault(e.type, []).append(e)

    # visitors: non-staff entries, minus expected staff when no staff track was tagged before 11:00 (05)
    entries = by_type.get("entry", [])
    visitors = [e for e in entries if not e.is_staff]
    cutoff = datetime.combine(day.local_date, STAFF_FALLBACK_BEFORE, tzinfo=tz)
    tagged_early = any(e.is_staff and e.started_at < cutoff for e in entries)
    visitors_in = max(0, len(visitors) - (0 if tagged_early else day.expected_staff))
    hourly = Counter(local_hour(e.started_at, tz) for e in visitors)
    busiest = min(hourly, key=lambda h: (-hourly[h], h)) if hourly else None

    served = sum(1 for e in by_type.get("service", []) if _in_opening(e.started_at, intervals))
    waits = len(by_type.get("wait", []))
    unattended_s = sum(e.duration_s for e in by_type.get("unattended", []) if e.ended_at is not None)
    unattended_min = int((Decimal(str(unattended_s)) / 60).quantize(Decimal(1), rounding=ROUND_HALF_UP))

    by_source: dict[str, int] = {}
    count = 0
    cash_declared: int | None = None
    for s in day.sales:
        if s.source == "cash_declaration":
            cash_declared = (cash_declared or 0) + s.amount_xof
            continue
        by_source[s.source] = by_source.get(s.source, 0) + s.amount_xof
        count += 1
    sales_xof = sum(by_source.get(src, 0) for src in MOBILE_SOURCES)
    if cash_declared is not None:
        by_source["cash_declaration"] = cash_declared
        if not by_source.get("quick_log"):
            sales_xof += cash_declared  # quick logs already count the cash: never add both (06)
    rps = (Decimal(sales_xof) / Decimal(served)).quantize(CENT, rounding=ROUND_HALF_UP) if served else None

    slots = opening_hour_slots(day.local_date, tz, day.opening_hours)
    seen = {local_hour(h.at, tz) for h in day.heartbeats if h.at.astimezone(tz).date() == day.local_date}
    missing = [h for h in slots if h not in seen]

    return Metrics(
        visitors_in=visitors_in, served=served, waits=waits, unattended_min=unattended_min,
        busiest_hour=busiest, sales_count=count, sales_xof=sales_xof, sales_by_source=by_source,
        cash_declared_xof=cash_declared, rps_xof=rps, missing_hours=missing, opening_hours_count=len(slots),
        hourly_entries=dict(sorted(hourly.items())),
    )  # fmt: skip


def is_valid(m: Metrics, *, shop_active: bool = True, served_corrected: bool = False) -> bool:
    """docs/06 "Valid days": active, ≤ 25 % missing hours, served ≥ 10, money > 0, served not corrected."""
    return (
        shop_active
        and not m.incomplete
        and m.served >= MIN_SERVED
        and m.sales_xof > 0
        and not served_corrected
    )


# ---------- baseline and verdict ----------
@dataclass(frozen=True)
class Baseline:
    rps_median: Decimal | None
    rps_mad: Decimal | None
    n_days: int

    def to_json(self) -> dict[str, Any]:
        return {
            "rps_median": None if self.rps_median is None else str(self.rps_median),
            "rps_mad": None if self.rps_mad is None else str(self.rps_mad),
            "n_days": self.n_days,
        }


@dataclass(frozen=True)
class PastDay:
    local_date: date
    rps_xof: Decimal | None
    valid: bool


def baseline(d: date, history: list[PastDay]) -> Baseline:
    """Valid days in the 56 days before D, at most the 28 most recent."""
    window = [
        p for p in history
        if p.valid and p.rps_xof is not None and d - timedelta(days=BASELINE_WINDOW_DAYS) <= p.local_date < d
    ]  # fmt: skip
    window = sorted(window, key=lambda p: p.local_date)[-BASELINE_MAX_DAYS:]
    if not window:
        return Baseline(None, None, 0)
    values = [p.rps_xof for p in window if p.rps_xof is not None]
    med = Decimal(statistics.median(values)).quantize(CENT, rounding=ROUND_HALF_UP)
    mad = Decimal(statistics.median([abs(v - med) for v in values]))
    mad = max(mad, med * MAD_FLOOR).quantize(CENT, rounding=ROUND_HALF_UP)
    return Baseline(med, mad, len(window))


def zscore(m: Metrics, b: Baseline) -> Decimal | None:
    if m.rps_xof is None or b.rps_median is None or not b.rps_mad:
        return None
    return (b.rps_median - m.rps_xof) / b.rps_mad


def verdict(m: Metrics, b: Baseline) -> str:
    """docs/06 "Verdict": first match wins."""
    if m.incomplete:
        return "incomplete_data"
    if m.served < MIN_SERVED:
        return "not_enough_activity"
    if b.n_days < LEARNING_DAYS:
        return "learning"
    if m.sales_xof == 0:
        return "large_gap"
    z = zscore(m, b)
    if z is None or z <= 2:
        return "normal"
    if z <= 4:
        return "worth_a_look"
    return "large_gap"


# ---------- confidence ----------
@dataclass(frozen=True)
class ConfidenceInput:
    count_check_passed_at: datetime | None
    phone_last_seen_at: datetime | None
    phone_parser_current: bool
    report_at: datetime


def _min_fps(day: DayInput, role: str) -> float | None:
    """Lowest fps reported by any camera with that role over the day's heartbeats (None: no data)."""
    cams = {name for name, r in day.camera_roles.items() if r == role}
    vals = [v for h in day.heartbeats for name, v in h.fps.items() if name in cams]
    return min(vals) if vals else None


def confidence(day: DayInput, c: ConfidenceInput) -> dict[str, str]:
    door_fps = _min_fps(day, "door")
    counter_fps = _min_fps(day, "counter")
    checked = c.count_check_passed_at is not None and c.report_at - c.count_check_passed_at <= timedelta(
        days=30
    )
    if checked and door_fps is not None and door_fps >= 4:
        visitors = "high"
    elif door_fps is not None and door_fps >= 2:
        visitors = "medium"
    else:
        visitors = "low"

    svc = [e.confidence for e in day.events if e.type == "service"]
    mean = sum(svc) / len(svc) if svc else 0.0
    if counter_fps is not None and counter_fps >= 4 and mean >= 0.75:
        served = "high"
    elif mean >= 0.6:
        served = "medium"
    else:
        served = "low"

    seen = c.phone_last_seen_at
    today = day.local_date
    if seen is not None and c.report_at - seen <= timedelta(hours=2) and c.phone_parser_current:
        sales = "high"
    elif seen is not None and seen.astimezone(day.tz).date() == today:
        sales = "medium"
    else:
        sales = "low"
    return {"visitors_in": visitors, "served": served, "sales": sales}


# ---------- moments ----------
@dataclass(frozen=True)
class Moment:
    rank: int
    kind: str  # after_hours_motion | unattended | wait | low_rps_hour
    event_id: str
    camera: str
    started_at: datetime
    duration_s: int
    hour: int | None = None

    @property
    def clip_start(self) -> datetime:
        return self.started_at - timedelta(seconds=CLIP_BEFORE_S)

    @property
    def clip_end(self) -> datetime:
        return self.started_at + timedelta(seconds=CLIP_AFTER_S)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "rank": self.rank, "kind": self.kind, "event_id": self.event_id, "camera": self.camera,
            "started_at": self.started_at.isoformat(), "duration_s": self.duration_s,
            "clip_start": self.clip_start.isoformat(), "clip_end": self.clip_end.isoformat(),
        }  # fmt: skip
        if self.hour is not None:
            out["hour"] = self.hour
        return out


def moments(day: DayInput, m: Metrics, b: Baseline) -> list[Moment]:
    """docs/06 "Moments": up to 3, after-hours first (latest first), then the longest unattended period
    in a busy hour, the longest wait, and the hour with the largest RPS drop."""
    tz = day.tz
    picked: list[tuple[str, EventIn, int | None]] = []
    ahm = sorted(
        (e for e in day.events if e.type == "after_hours_motion"), key=lambda e: e.started_at, reverse=True
    )
    picked += [("after_hours_motion", e, None) for e in ahm]

    busy = {h for h, n in m.hourly_entries.items() if n >= 3}
    if m.busiest_hour is not None:
        busy.add(m.busiest_hour)

    def hours_of(e: EventIn) -> set[int]:
        end = e.ended_at or e.started_at
        hs, t = set(), e.started_at.astimezone(tz).replace(minute=0, second=0, microsecond=0)
        while t <= end:
            hs.add(t.hour)
            t += timedelta(hours=1)
        return hs

    unatt = [
        e for e in day.events if e.type == "unattended" and e.ended_at is not None and hours_of(e) & busy
    ]
    if unatt:
        picked.append(
            ("unattended", max(unatt, key=lambda e: (e.duration_s, -e.started_at.timestamp())), None)
        )
    waits = [e for e in day.events if e.type == "wait"]
    if waits:
        picked.append(("wait", max(waits, key=lambda e: (e.duration_s, -e.started_at.timestamp())), None))

    drop = _largest_rps_drop(day, b)
    if drop is not None:
        picked.append(("low_rps_hour", drop[1], drop[0]))

    out: list[Moment] = []
    for kind, e, hour in picked[:MAX_MOMENTS]:
        out.append(Moment(len(out) + 1, kind, e.id, e.camera, e.started_at, round(e.duration_s), hour))
    return out


def _largest_rps_drop(day: DayInput, b: Baseline) -> tuple[int, EventIn] | None:
    """Hour (≥ 3 services) whose RPS is furthest below the shop's median RPS; its longest service."""
    if b.rps_median is None:
        return None
    tz = day.tz
    services: dict[int, list[EventIn]] = {}
    for e in day.events:
        if e.type == "service":
            services.setdefault(local_hour(e.started_at, tz), []).append(e)
    money: dict[int, int] = {}
    for s in day.sales:
        if s.source != "cash_declaration":
            money[local_hour(s.occurred_at, tz)] = money.get(local_hour(s.occurred_at, tz), 0) + s.amount_xof
    best: tuple[Decimal, int] | None = None
    for hour, evs in services.items():
        if len(evs) < 3:
            continue
        gap = b.rps_median - Decimal(money.get(hour, 0)) / Decimal(len(evs))
        if gap > 0 and (best is None or gap > best[0]):
            best = (gap, hour)
    if best is None:
        return None
    longest = max(services[best[1]], key=lambda e: (e.duration_s, -e.started_at.timestamp()))
    return best[1], longest


# ---------- comparison with last week ----------
def vs_last_week(today: Metrics, last: Metrics | None, last_valid: bool) -> dict[str, Any] | None:
    if last is None or not last_valid:
        return None
    out: dict[str, Any] = {}
    for key in ("visitors_in", "served", "sales_xof"):
        a, b = getattr(today, key), getattr(last, key)
        pct = (
            None
            if b == 0
            else int((Decimal(a - b) * 100 / Decimal(b)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        )
        out[key] = {"today": a, "last_week": b, "delta": a - b, "pct": pct}
    return out


# ---------- whole report ----------
@dataclass(frozen=True)
class Report:
    metrics: Metrics
    baseline: Baseline
    verdict: str
    valid: bool
    confidence: dict[str, str]
    moments: list[Moment]
    vs_last_week: dict[str, Any] | None


def build_report(
    day: DayInput,
    history: list[PastDay],
    conf: ConfidenceInput,
    last_week: tuple[Metrics, bool] | None = None,
    *,
    shop_active: bool = True,
    served_corrected: bool = False,
) -> Report:
    m = compute_metrics(day)
    b = baseline(day.local_date, history)
    return Report(
        metrics=m,
        baseline=b,
        verdict=verdict(m, b),
        valid=is_valid(m, shop_active=shop_active, served_corrected=served_corrected),
        confidence=confidence(day, conf),
        moments=moments(day, m, b),
        vs_last_week=vs_last_week(m, *last_week) if last_week else None,
    )
