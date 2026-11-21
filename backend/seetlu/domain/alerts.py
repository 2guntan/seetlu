"""Alert decisions (docs/06 "Alerts", AC-F6-1..3). Pure: the caller loads the facts.

Only 4 types. At most 3 per shop per local day; quiet hours suppress all but `after_hours_motion`;
one alert per event id; `not_opened` once a day; `kit_offline` once per outage.
"""

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

MAX_PER_DAY = 3
AFTER_HOURS_MAX_AGE = timedelta(hours=1)  # late uploads of old motion do not wake anyone up
PRIORITY = ("after_hours_motion", "kit_offline", "unattended", "not_opened")
DEFAULT_PARAMS = {"not_opened": {"grace_min": 30}, "unattended": {"min": 10}, "kit_offline": {"min": 30}}


@dataclass(frozen=True)
class Rule:
    enabled: bool = True
    params: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class EventFact:
    id: str
    type: str  # entry | service | unattended | after_hours_motion | …
    started_at: datetime
    ended_at: datetime | None = None


@dataclass(frozen=True)
class SentFact:
    type: str
    event_id: str | None
    sent_at: datetime


@dataclass(frozen=True)
class AlertFacts:
    now: datetime  # aware, any zone
    tz: ZoneInfo  # the shop's zone
    opening: list[tuple[datetime, datetime]]  # today's opening intervals (aware, shop zone)
    quiet_start: time
    quiet_end: time
    rules: dict[str, Rule]
    events: list[EventFact]  # today's events (shop local day)
    last_heartbeat: datetime | None
    sent_today: list[SentFact]


@dataclass(frozen=True)
class Alert:
    type: str
    event_id: str | None
    at: datetime  # the time shown in the text (opening time, motion time, last heartbeat)
    minutes: int | None = None


def in_quiet_hours(local: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= local < end
    return local >= start or local < end  # wraps midnight (22:00 → 07:00)


def _open_now(f: AlertFacts) -> bool:
    return any(a <= f.now < b for a, b in f.opening)


def _param(f: AlertFacts, kind: str, key: str) -> int:
    rule = f.rules.get(kind, Rule())
    return int(rule.params.get(key, DEFAULT_PARAMS[kind][key]))


def candidates(f: AlertFacts) -> list[Alert]:
    sent_ids = {(x.type, x.event_id) for x in f.sent_today}
    sent_types = {x.type for x in f.sent_today}
    out: list[Alert] = []

    for e in sorted(f.events, key=lambda e: e.started_at):
        fresh = f.now - e.started_at <= AFTER_HOURS_MAX_AGE
        if e.type == "after_hours_motion" and ("after_hours_motion", e.id) not in sent_ids and fresh:
            out.append(Alert("after_hours_motion", e.id, e.started_at))

    offline_after = timedelta(minutes=_param(f, "kit_offline", "min"))
    if _open_now(f) and f.last_heartbeat is not None and f.now - f.last_heartbeat > offline_after:
        already = any(x.type == "kit_offline" and x.sent_at > f.last_heartbeat for x in f.sent_today)
        if not already:
            out.append(Alert("kit_offline", None, f.last_heartbeat))

    threshold = timedelta(minutes=_param(f, "unattended", "min"))
    for e in f.events:
        if e.type == "unattended" and e.ended_at is None and ("unattended", e.id) not in sent_ids:
            open_for = f.now - e.started_at
            if _open_now(f) and open_for >= threshold:
                out.append(Alert("unattended", e.id, e.started_at, round(open_for.total_seconds() / 60)))

    if f.opening and "not_opened" not in sent_types:
        first_open = f.opening[0][0]
        grace = timedelta(minutes=_param(f, "not_opened", "grace_min"))
        presence = any(e.type in ("entry", "service") for e in f.events)
        if first_open + grace <= f.now < f.opening[-1][1] and not presence:
            out.append(Alert("not_opened", None, first_open))
    return out


def decide(f: AlertFacts) -> list[Alert]:
    """Alerts to send now, highest priority first, within the daily cap and quiet hours."""
    room = MAX_PER_DAY - len(f.sent_today)
    if room <= 0:
        return []
    quiet = in_quiet_hours(f.now.astimezone(f.tz).time(), f.quiet_start, f.quiet_end)
    keep = [
        a
        for a in candidates(f)
        if f.rules.get(a.type, Rule()).enabled and (not quiet or a.type == "after_hours_motion")
    ]
    keep.sort(key=lambda a: PRIORITY.index(a.type))
    return keep[:room]
