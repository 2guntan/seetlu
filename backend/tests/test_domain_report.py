"""Report engine domain tests (docs/06), incl. verdict boundaries and money never float (docs/10)."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from seetlu.domain.report import (
    DAYS,
    Baseline,
    ConfidenceInput,
    DayInput,
    EventIn,
    HeartbeatIn,
    Metrics,
    PastDay,
    SaleIn,
    baseline,
    build_report,
    compute_metrics,
    confidence,
    is_valid,
    moments,
    opening_hour_slots,
    verdict,
    vs_last_week,
)

TZ = ZoneInfo("Africa/Dakar")
D = date(2026, 11, 20)  # Friday
HOURS = {d: [["08:00", "21:00"]] for d in DAYS}
ROLES = {"door": "door", "counter": "counter"}


def at(hh: int, mm: int = 0, ss: int = 0, d: date = D) -> datetime:
    return datetime.combine(d, time(hh, mm, ss), tzinfo=TZ)


def full_heartbeats(d: date = D, skip: set[int] | None = None, fps: float = 5.0) -> list[HeartbeatIn]:
    out = []
    t = at(0, d=d)
    while t < at(0, d=d) + timedelta(days=1):
        if t.hour not in (skip or set()):
            out.append(HeartbeatIn(t, {"door": fps, "counter": fps}))
        t += timedelta(minutes=5)
    return out


def ev(i: int, type_: str, start: datetime, dur_s: int = 0, **kw: object) -> EventIn:
    end = start + timedelta(seconds=dur_s) if dur_s else None
    cam = "door" if type_ in ("entry", "exit", "after_hours_motion") else "counter"
    return EventIn(id=f"e{i}", type=type_, started_at=start, ended_at=end, camera=cam, camera_role=cam, **kw)  # type: ignore[arg-type]


def day(events: list[EventIn] | None = None, sales: list[SaleIn] | None = None,
        heartbeats: list[HeartbeatIn] | None = None, expected_staff: int = 0) -> DayInput:  # fmt: skip
    return DayInput(D, "Africa/Dakar", HOURS, events or [], sales or [],
                    full_heartbeats() if heartbeats is None else heartbeats, expected_staff, ROLES)  # fmt: skip


def metrics(**kw: object) -> Metrics:
    base: dict[str, object] = {
        "visitors_in": 100, "served": 50, "waits": 0, "unattended_min": 0, "busiest_hour": 18, "sales_count": 10,
        "sales_xof": 125_000, "sales_by_source": {}, "cash_declared_xof": None, "rps_xof": Decimal("2500.00"),
        "missing_hours": [], "opening_hours_count": 13, "hourly_entries": {},
    }  # fmt: skip
    return Metrics(**(base | kw))  # type: ignore[arg-type]


B = Baseline(Decimal("2500.00"), Decimal("250.00"), 20)


# ---------- metrics ----------
def test_visitors_exclude_staff_and_apply_expected_staff_fallback_AC_F1_3() -> None:
    entries = [ev(i, "entry", at(9, i)) for i in range(10)]
    assert compute_metrics(day(entries, expected_staff=1)).visitors_in == 9  # nobody tagged before 11:00
    tagged = [*entries, ev(99, "entry", at(10, 30), is_staff=True)]
    assert compute_metrics(day(tagged, expected_staff=1)).visitors_in == 10  # staff tagged early: no fallback
    late = [*entries, ev(99, "entry", at(11, 30), is_staff=True)]
    assert compute_metrics(day(late, expected_staff=1)).visitors_in == 9
    assert compute_metrics(day([], expected_staff=2)).visitors_in == 0  # floor 0


def test_busiest_hour_ties_go_to_the_earliest() -> None:
    entries = [
        ev(1, "entry", at(10)),
        ev(2, "entry", at(10, 5)),
        ev(3, "entry", at(18)),
        ev(4, "entry", at(18, 1)),
    ]
    assert compute_metrics(day(entries)).busiest_hour == 10
    assert compute_metrics(day([])).busiest_hour is None


def test_served_counts_services_started_in_opening_hours() -> None:
    svc = [ev(1, "service", at(7, 59), 30), ev(2, "service", at(8), 30), ev(3, "service", at(20, 59), 30),
           ev(4, "service", at(21), 30)]  # fmt: skip
    assert compute_metrics(day(svc)).served == 2


def test_unattended_minutes_rounded_and_waits_counted() -> None:
    evs = [ev(1, "unattended", at(13), 40 * 60 + 29), ev(2, "unattended", at(15), 30),
           ev(3, "unattended", at(16)), ev(4, "wait", at(12), 200), ev(5, "wait", at(14), 190)]  # fmt: skip
    m = compute_metrics(day(evs))
    assert m.unattended_min == 41 and m.waits == 2  # 40.98 min → 41; the open one (no end) is ignored


def test_money_sources_and_cash_declaration_rule() -> None:
    sales = [SaleIn("wave", 45_000, at(10)), SaleIn("orange_money", 12_000, at(11)), SaleIn("pos", 3_000, at(12)),
             SaleIn("cash_declaration", 30_000, at(20, 30))]  # fmt: skip
    m = compute_metrics(day(sales=sales))
    assert m.sales_xof == 90_000 and m.cash_declared_xof == 30_000 and m.sales_count == 3
    assert m.sales_by_source == {
        "wave": 45_000,
        "orange_money": 12_000,
        "pos": 3_000,
        "cash_declaration": 30_000,
    }
    with_logs = [*sales, SaleIn("quick_log", 2_500, at(15))]
    m2 = compute_metrics(day(sales=with_logs))
    assert m2.sales_xof == 62_500  # quick logs exist → the declaration is shown but not added
    assert isinstance(m2.sales_xof, int)


def test_rps_is_decimal_and_null_without_service() -> None:
    svc = [ev(i, "service", at(9, i), 30) for i in range(3)]
    m = compute_metrics(day(svc, [SaleIn("wave", 10_000, at(9))]))
    assert m.rps_xof == Decimal("3333.33") and isinstance(m.rps_xof, Decimal)
    assert compute_metrics(day([], [SaleIn("wave", 10_000, at(9))])).rps_xof is None


def test_missing_hours_are_opening_hours_without_heartbeat_AC_F4_5() -> None:
    m = compute_metrics(day(heartbeats=full_heartbeats(skip={14, 15})))
    assert m.missing_hours == [14, 15] and m.opening_hours_count == 13 and not m.incomplete
    m2 = compute_metrics(day(heartbeats=full_heartbeats(skip={0, 1, 2, 22, 23})))
    assert m2.missing_hours == []  # outside opening hours does not count
    assert opening_hour_slots(D, TZ, {d: [["07:30", "22:00"]] for d in DAYS}) == list(range(7, 22))


def test_missing_more_than_25_percent_is_incomplete_AC_F4_5() -> None:
    three = compute_metrics(day(heartbeats=full_heartbeats(skip={8, 9, 10})))  # 3/13 = 23 %
    four = compute_metrics(day(heartbeats=full_heartbeats(skip={8, 9, 10, 11})))  # 4/13 = 31 %
    assert not three.incomplete and four.incomplete
    assert verdict(four, B) == "incomplete_data"
    assert compute_metrics(day(heartbeats=[])).missing_hours == list(range(8, 21))  # never zeros: all missing


# ---------- validity and baseline ----------
def test_valid_day_rules() -> None:
    assert is_valid(metrics())
    assert not is_valid(metrics(), shop_active=False)
    assert not is_valid(metrics(served=9))
    assert not is_valid(metrics(sales_xof=0))
    assert not is_valid(metrics(missing_hours=[8, 9, 10, 11]))
    assert not is_valid(metrics(), served_corrected=True)


def past(n: int, rps: str = "2500", valid: bool = True, start: int = 1) -> list[PastDay]:
    return [PastDay(D - timedelta(days=i), Decimal(rps), valid) for i in range(start, start + n)]


def test_baseline_median_mad_with_floor() -> None:
    hist = [
        PastDay(D - timedelta(days=i), Decimal(v), True)
        for i, v in enumerate(["2000", "2400", "2500", "2600", "3000"], 1)
    ]
    b = baseline(D, hist)
    assert b.rps_median == Decimal("2500.00") and b.n_days == 5
    assert b.rps_mad == Decimal("250.00")  # MAD 100 floored at 10 % of the median
    wide = [
        PastDay(D - timedelta(days=i), Decimal(v), True)
        for i, v in enumerate(["1000", "2000", "2500", "3000", "4000"], 1)
    ]
    assert baseline(D, wide).rps_mad == Decimal("500.00")


def test_baseline_window_56_days_max_28_valid_only() -> None:
    hist = past(40) + past(5, "100", valid=False, start=41) + past(10, "9999", start=57)
    b = baseline(D, hist)
    assert b.n_days == 28 and b.rps_median == Decimal("2500.00")
    assert baseline(D, past(3, start=0)).n_days == 2  # day D itself is not in its own baseline
    assert baseline(D, []) == Baseline(None, None, 0)


# ---------- verdict ----------
@pytest.mark.parametrize(
    ("rps", "expected"),
    [("3500", "normal"), ("2500", "normal"), ("2000", "normal"), ("1999.99", "worth_a_look"),
     ("1500", "worth_a_look"), ("1499.99", "large_gap"), ("100", "large_gap")],
)  # fmt: skip
def test_verdict_z_boundaries_2_and_4_AC_F4_3(rps: str, expected: str) -> None:
    assert verdict(metrics(rps_xof=Decimal(rps)), B) == expected  # z = (2500 - rps) / 250


def test_verdict_order_AC_F4_3_AC_F4_4() -> None:
    incomplete = metrics(missing_hours=[8, 9, 10, 11], served=0)
    assert verdict(incomplete, B) == "incomplete_data"
    assert verdict(metrics(served=9), B) == "not_enough_activity"
    assert verdict(metrics(), Baseline(Decimal(2500), Decimal(250), 13)) == "learning"  # < 14 valid days
    assert verdict(metrics(), Baseline(Decimal(2500), Decimal(250), 14)) == "normal"
    assert verdict(metrics(sales_xof=0, rps_xof=Decimal(0)), B) == "large_gap"


@given(st.integers(min_value=0, max_value=10_000_000), st.integers(min_value=10, max_value=500),
       st.integers(min_value=0, max_value=13))  # fmt: skip
def test_verdict_is_always_one_of_six_and_learning_before_14_days_AC_F4_4(
    sales: int, served: int, n: int
) -> None:
    rps = Decimal(sales) / Decimal(served)
    v = verdict(
        metrics(sales_xof=sales, served=served, rps_xof=rps), Baseline(Decimal(2500), Decimal(250), n)
    )
    assert v in ("learning", "not_enough_activity")
    v2 = verdict(metrics(sales_xof=sales, served=served, rps_xof=rps), B)
    assert v2 in ("normal", "worth_a_look", "large_gap")
    if rps >= Decimal(2500):
        assert v2 == "normal"  # more money than usual is always normal


# ---------- confidence ----------
def conf_in(**kw: object) -> ConfidenceInput:
    base: dict[str, object] = {"count_check_passed_at": at(9) - timedelta(days=10), "phone_last_seen_at": at(20, 30),
                                   "phone_parser_current": True, "report_at": at(21)}  # fmt: skip
    return ConfidenceInput(**(base | kw))  # type: ignore[arg-type]


def test_confidence_levels_AC_F9_2() -> None:
    svc = [ev(i, "service", at(9, i), 30, confidence=0.8) for i in range(5)]
    assert confidence(day(svc), conf_in()) == {"visitors_in": "high", "served": "high", "sales": "high"}
    old_check = confidence(day(svc), conf_in(count_check_passed_at=at(9) - timedelta(days=31)))
    assert old_check["visitors_in"] == "medium"
    slow = confidence(day(svc, heartbeats=full_heartbeats(fps=1.5)), conf_in())
    assert slow["visitors_in"] == "low" and slow["served"] == "medium"
    weak = [ev(i, "service", at(9, i), 30, confidence=0.5) for i in range(5)]
    assert confidence(day(weak), conf_in())["served"] == "low"
    assert confidence(day(svc), conf_in(phone_last_seen_at=at(12)))["sales"] == "medium"
    assert confidence(day(svc), conf_in(phone_parser_current=False))["sales"] == "medium"
    assert confidence(day(svc), conf_in(phone_last_seen_at=at(12, d=D - timedelta(days=1))))["sales"] == "low"
    assert confidence(day(svc), conf_in(phone_last_seen_at=None))["sales"] == "low"


# ---------- moments ----------
def test_moments_priority_and_clip_window_AC_F5_1() -> None:
    entries = [ev(100 + i, "entry", at(18, i)) for i in range(5)]
    evs = [*entries,
           ev(1, "after_hours_motion", at(23, 14)), ev(2, "after_hours_motion", at(5, 2)),
           ev(3, "unattended", at(13), 40 * 60), ev(4, "unattended", at(18, 10), 6 * 60),
           ev(5, "wait", at(12), 200), ev(6, "wait", at(19), 250)]  # fmt: skip
    ms = moments(day(evs), compute_metrics(day(evs)), B)
    assert [(m.rank, m.kind, m.event_id) for m in ms] == [
        (1, "after_hours_motion", "e1"), (2, "after_hours_motion", "e2"), (3, "unattended", "e4")]  # fmt: skip
    assert ms[0].clip_end - ms[0].clip_start == timedelta(seconds=20)
    assert ms[0].clip_start == at(23, 14) - timedelta(seconds=5)


def test_unattended_moment_needs_a_busy_hour_then_longest_wait_AC_F5_1() -> None:
    evs = [ev(100 + i, "entry", at(18, i)) for i in range(3)] + [
        ev(3, "unattended", at(13), 40 * 60), ev(5, "wait", at(12), 200), ev(6, "wait", at(19), 250)]  # fmt: skip
    ms = moments(day(evs), compute_metrics(day(evs)), B)
    assert [(m.kind, m.event_id) for m in ms] == [("wait", "e6")]  # 13:00 is not busy; no RPS drop data


def test_low_rps_hour_moment_AC_F5_1() -> None:
    svc = [ev(i, "service", at(10, i * 5), 30 + i) for i in range(3)] + [
        ev(10 + i, "service", at(18, i * 5), 40) for i in range(4)
    ]
    sales = [SaleIn("wave", 3 * 2400, at(10, 30)), SaleIn("wave", 4 * 1000, at(18, 30))]
    ms = moments(day(svc, sales), compute_metrics(day(svc, sales)), B)
    assert [(m.kind, m.hour) for m in ms] == [("low_rps_hour", 18)]
    assert moments(day(svc, sales), compute_metrics(day(svc, sales)), Baseline(None, None, 0)) == []


# ---------- vs last week ----------
def test_vs_last_week_only_when_that_day_was_valid() -> None:
    today = metrics(visitors_in=112, served=55, sales_xof=115_000)
    last = metrics(visitors_in=100, served=50, sales_xof=125_000)
    out = vs_last_week(today, last, True) or {}
    assert out["visitors_in"] == {"today": 112, "last_week": 100, "delta": 12, "pct": 12}
    assert out["sales_xof"]["pct"] == -8
    assert vs_last_week(today, last, False) is None and vs_last_week(today, None, True) is None
    assert (vs_last_week(today, metrics(served=0), True) or {})["served"]["pct"] is None


def test_build_report_end_to_end() -> None:
    svc = [ev(i, "service", at(9, 0) + timedelta(minutes=5 * i), 60, confidence=0.8) for i in range(40)]
    entries = [ev(100 + i, "entry", at(9, 0) + timedelta(minutes=5 * i)) for i in range(50)]
    r = build_report(day([*svc, *entries], [SaleIn("wave", 100_000, at(12))], expected_staff=1),
                     past(20), conf_in(), (metrics(), True))  # fmt: skip
    assert r.verdict == "normal" and r.valid and r.metrics.visitors_in == 49
    assert r.baseline.to_json() == {"rps_median": "2500.00", "rps_mad": "250.00", "n_days": 20}
    assert r.vs_last_week is not None
    assert datetime.now(UTC)  # sanity
