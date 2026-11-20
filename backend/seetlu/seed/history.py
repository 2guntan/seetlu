"""30 days of simulated history for the demo shops (docs/10 "Seed data"): events, heartbeats and sales,
then the daily reports computed by the real engine, oldest first, so the baseline builds up naturally.

Deterministic (seeded by shop and date) and idempotent: rows carry ids derived from their content and
are inserted with ON CONFLICT DO NOTHING. History reports are marked as sent at their report time but
no message is written to the mock inbox and no clip is queued (the edge buffer would not have them).

Shop 1 (Boutique Awa) carries the special days the demo needs, counted back from the anchor date:
2 `worth_a_look` days, 1 `large_gap` day and 1 day with missing hours. The anchor day itself gets
only sales: its events come from `make sim-day` / `make e2e` through the real edge agent.
"""

import hashlib
import os
import random
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from seetlu.core.config import get_settings
from seetlu.core.security import hash_token
from seetlu.db import models as m
from seetlu.domain.report import opening_intervals
from seetlu.reports import service

DEFAULT_ANCHOR = date(2026, 11, 20)  # the date of the fixed `normal-day` scenario (docs/10)
HISTORY_DAYS = 30
BASE_RPS_XOF = 2_500
SOURCES = ((m.SaleSource.wave, 45), (m.SaleSource.orange_money, 30), (m.SaleSource.quick_log, 25))


@dataclass(frozen=True)
class DayPlan:
    visitors: int
    served_ratio: float = 0.77
    rps_factor: float = 1.0
    missing_hours: frozenset[int] = frozenset()


# Days before the anchor → special plan for the first demo shop.
SPECIAL: dict[int, DayPlan] = {
    2: DayPlan(140, rps_factor=0.70),  # worth_a_look: about 3 MAD below the median
    4: DayPlan(140, rps_factor=0.45),  # large_gap: more than 4 MAD below
    6: DayPlan(140, rps_factor=0.68),  # worth_a_look
    9: DayPlan(140, missing_hours=frozenset({14, 15, 16})),  # 3 of 13 hours missing: listed, not incomplete
}

# The anchor day's money for shop 1, sized on the `normal-day` scenario (108 people served).
ANCHOR_SALES: list[tuple[m.SaleSource, int, str]] = [
    *[(m.SaleSource.wave, 2_750, f"{h:02d}:{mm:02d}") for h in range(9, 21) for mm in (5, 25, 45, 55)][:48],
    *[(m.SaleSource.orange_money, 2_500, f"{h:02d}:{mm:02d}") for h in range(9, 21) for mm in (10, 40, 50)][
        :33
    ],
    *[(m.SaleSource.quick_log, 2_000, f"{h:02d}:{mm:02d}") for h in range(9, 21) for mm in (15, 35)][:24],
]


def anchor_date() -> date:
    raw = os.environ.get("SEED_ANCHOR_DATE")
    return date.fromisoformat(raw) if raw else DEFAULT_ANCHOR


def stable_uuid(ts: datetime, key: str) -> uuid.UUID:
    """UUIDv7 layout (48-bit ms timestamp) with the rest derived from `key`: sortable and repeatable."""
    ms = int(ts.timestamp() * 1000) & ((1 << 48) - 1)
    h = int.from_bytes(hashlib.sha256(key.encode()).digest()[:10], "big")
    rand_a, rand_b = (h >> 62) & 0xFFF, h & ((1 << 62) - 1)
    return uuid.UUID(int=(ms << 80) | (0x7 << 76) | (rand_a << 64) | (0x2 << 62) | rand_b)


def plan_for(shop_index: int, back: int, weekday: int, rng: random.Random) -> DayPlan:
    if shop_index == 0 and back in SPECIAL:
        return SPECIAL[back]
    base = (140 if weekday != 6 else 50) if shop_index == 0 else 220
    return DayPlan(visitors=round(base * rng.uniform(0.9, 1.1)))


def _random_times(
    rng: random.Random, spans: list[tuple[datetime, datetime]], n: int, peak: int
) -> list[datetime]:
    """`n` instants inside the opening spans, about half of them in the two hours from `peak`."""
    total = sum((b - a).total_seconds() for a, b in spans)
    out = []
    for _ in range(n):
        if rng.random() < 0.5:
            for a, b in spans:
                lo = max(a, a.replace(hour=peak, minute=0, second=0))
                hi = min(b, lo + timedelta(hours=2))
                if lo < hi:
                    out.append(lo + timedelta(seconds=rng.uniform(0, (hi - lo).total_seconds())))
                    break
            else:
                out.append(spans[0][0] + timedelta(seconds=rng.uniform(0, total)))
            continue
        x = rng.uniform(0, total)
        for a, b in spans:
            length = (b - a).total_seconds()
            if x <= length:
                out.append(a + timedelta(seconds=x))
                break
            x -= length
    return sorted(t.replace(microsecond=0) for t in out)


def _day_rows(
    shop: m.Shop, kit: m.Kit, cams: dict[str, m.Camera], d: date, plan: DayPlan, rng: random.Random
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    tz = ZoneInfo(shop.timezone)
    spans = opening_intervals(d, tz, shop.opening_hours)
    heartbeats = []
    t = datetime.combine(d, time(0), tzinfo=tz)
    while t.date() == d:
        if t.hour not in plan.missing_hours:
            heartbeats.append({"kit_id": kit.id, "at": t, "fps": {"door": 5.0, "counter": 5.0},
                               "power_source": "mains", "agent_version": "seed"})  # fmt: skip
        t += timedelta(minutes=5)
    if not spans:
        return heartbeats, [], []
    key = f"{shop.id}:{d.isoformat()}"
    events: list[dict[str, Any]] = []

    def event(
        i: str, type_: m.EventType, cam: str, start: datetime, dur_s: int | None = None, **kw: Any
    ) -> None:
        events.append({
            "id": stable_uuid(start, f"{key}:{i}"), "started_at": start, "shop_id": shop.id, "kit_id": kit.id,
            "camera_id": cams[cam].id, "type": type_,
            "ended_at": start + timedelta(seconds=dur_s) if dur_s else None, "is_staff": False, **kw,
        })  # fmt: skip

    opening = spans[0][0]
    event("staff-in", m.EventType.entry, "door", opening - timedelta(minutes=5), is_staff=True)
    peak = 18 if shop.timezone == "Africa/Dakar" else 17
    visits = [v for v in _random_times(rng, spans, plan.visitors, peak) if v.hour not in plan.missing_hours]
    served = set(rng.sample(range(len(visits)), round(len(visits) * plan.served_ratio)))
    sales = []
    rps = BASE_RPS_XOF * plan.rps_factor
    weights = [w for _, w in SOURCES]
    for i, v in enumerate(visits):
        event(f"in-{i}", m.EventType.entry, "door", v)
        event(f"out-{i}", m.EventType.exit, "door", v + timedelta(minutes=rng.randint(2, 12)))
        if i in served:
            start = v + timedelta(seconds=rng.randint(30, 90))
            event(f"svc-{i}", m.EventType.service, "counter", start, rng.randint(20, 120))
            amount = round(rps * rng.uniform(0.97, 1.03) / 25) * 25
            src = rng.choices([s for s, _ in SOURCES], weights)[0]
            sales.append({"id": stable_uuid(start, f"{key}:sale-{i}"), "shop_id": shop.id, "source": src,
                          "amount_xof": int(amount), "occurred_at": start + timedelta(minutes=1),
                          "local_date": d})  # fmt: skip
    lull = opening.replace(hour=14, minute=10)
    if any(a <= lull < b for a, b in spans) and lull.hour not in plan.missing_hours:
        event("unattended", m.EventType.unattended, "counter", lull, rng.randint(5, 15) * 60)
    return heartbeats, events, sales


def anchor_sales(shop: m.Shop, d: date) -> list[dict[str, Any]]:
    tz = ZoneInfo(shop.timezone)
    rows = []
    for i, (src, amount, hm) in enumerate(ANCHOR_SALES):
        at = datetime.combine(d, time.fromisoformat(hm), tzinfo=tz)
        rows.append({"id": stable_uuid(at, f"{shop.id}:{d}:anchor-{i}"), "shop_id": shop.id, "source": src,
                     "amount_xof": amount, "occurred_at": at, "local_date": d})  # fmt: skip
    return rows


def _demo_phone(s: Session, shop: m.Shop, anchor: date) -> None:
    """Shop 1's sales phone (the M9 app), last seen 30 min before the anchor report: sales confidence high."""
    seen = service.report_time_of(shop, anchor) - timedelta(minutes=30)
    phone = s.scalars(select(m.PhoneDevice).where(m.PhoneDevice.shop_id == shop.id)).first()
    if phone is None:
        phone = m.PhoneDevice(shop_id=shop.id, token_hash=hash_token(secrets.token_urlsafe(24)), model="demo")
        s.add(phone)
    phone.parser_version = get_settings().parser_version
    phone.last_seen_at = max(phone.last_seen_at or seen, seen)


def _insert(s: Session, model: type[m.Base], rows: list[dict[str, Any]]) -> None:
    for i in range(0, len(rows), 1_000):
        s.execute(insert(model).values(rows[i : i + 1_000]).on_conflict_do_nothing())


def seed_history(
    s: Session, shop_ids: list[str], anchor: date | None = None, days: int = HISTORY_DAYS
) -> int:
    """Returns the number of reports computed."""
    anchor = anchor or anchor_date()
    computed = 0
    for index, shop_id in enumerate(shop_ids):
        shop = s.get(m.Shop, uuid.UUID(shop_id))
        assert shop is not None
        kit = s.scalars(select(m.Kit).where(m.Kit.shop_id == shop.id)).one()
        cams = {c.name: c for c in s.scalars(select(m.Camera).where(m.Camera.kit_id == kit.id))}
        for back in range(days, 0, -1):
            d = anchor - timedelta(days=back)
            rng = random.Random(f"{shop.name}:{d.isoformat()}")
            heartbeats, events, sales = _day_rows(
                shop, kit, cams, d, plan_for(index, back, d.weekday(), rng), rng
            )
            _insert(s, m.Heartbeat, heartbeats)
            _insert(s, m.Event, events)
            _insert(s, m.Sale, sales)
            s.flush()
            c = service.compute(s, shop, d, now=service.report_time_of(shop, d).astimezone(UTC))
            c.row.sent_at = c.row.sent_at or c.row.computed_at
            computed += 1
        if index == 0:
            _insert(s, m.Sale, anchor_sales(shop, anchor))
            _demo_phone(s, shop, anchor)
        s.commit()
    return computed
