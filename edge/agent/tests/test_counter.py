"""Counter state machine (AC-F2-1 service, AC-F2-2 wait, AC-F2-3 unattended), with exact boundaries."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from seetlu_agent.counter import CounterMachine, Thresholds
from seetlu_agent.edge_config import DAYS, OpeningHours
from seetlu_agent.events import EdgeEvent

TZ = "Africa/Dakar"
DAY = date(2026, 11, 20)
HOURS = OpeningHours({d: [["08:00", "21:00"]] for d in DAYS}, TZ)


def at(hh: int, mm: int = 0, ss: int = 0) -> float:
    return datetime.combine(DAY, time(hh, mm, ss), tzinfo=ZoneInfo(TZ)).timestamp()


def machine(spans: list[tuple[float, float, float, str]] | None = None) -> CounterMachine:
    def lookup(a: float, b: float) -> tuple[list[float], list[str]]:
        hit = [(sc, i) for s0, s1, sc, i in spans or [] if s0 <= b and s1 >= a]
        return [sc for sc, _ in hit], [i for _, i in hit]

    m = CounterMachine("counter", "K", Thresholds(15, 180, 300), HOURS, lookup)
    m.start(at(7, 0))
    return m


def run(m: CounterMachine, steps: list[tuple[float, str, int]], until: float) -> list[EdgeEvent]:
    out: list[EdgeEvent] = []
    for ts, zone, n in steps:
        out += m.set_count(ts, zone, n)
    out += m.advance(until)
    return out


def closed(events: list[EdgeEvent], kind: str) -> list[EdgeEvent]:
    return [e for e in events if e.type == kind and e.ended_at is not None]


def test_service_needs_both_zones_for_service_min_s_AC_F2_1() -> None:
    t = at(10)
    staff = [(at(9), "counter_staff", 1)]
    short = run(machine(), [*staff, (t, "counter_customer", 1), (t + 14, "counter_customer", 0)], t + 60)
    assert closed(short, "service") == []
    ok = run(machine(), [*staff, (t, "counter_customer", 1), (t + 15, "counter_customer", 0)], t + 60)
    [svc] = closed(ok, "service")
    assert (svc.started_at, svc.ended_at) == (t, t + 15)


def test_service_ends_after_5s_empty_and_survives_short_gaps_AC_F2_1() -> None:
    t = at(10)
    steps = [(at(9), "counter_staff", 1), (t, "counter_customer", 1), (t + 30, "counter_customer", 0),
             (t + 34, "counter_customer", 1), (t + 60, "counter_customer", 0)]  # fmt: skip
    m = machine()
    events = run(m, steps, t + 64)
    assert closed(events, "service") == []  # 4 s after the end: still open
    [svc] = closed(m.advance(t + 65), "service")
    assert (svc.started_at, svc.ended_at) == (t, t + 60)


def test_wait_when_customer_alone_for_wait_min_s_AC_F2_2() -> None:
    t = at(11)
    m = machine()
    steps = [(at(9), "counter_staff", 1), (t, "counter_staff", 0), (t, "counter_customer", 1),
             (t + 179, "counter_staff", 1)]  # fmt: skip
    assert closed(run(m, steps, t + 200), "wait") == []
    m2 = machine()
    steps2 = [(at(9), "counter_staff", 1), (t, "counter_staff", 0), (t, "counter_customer", 1),
              (t + 200, "counter_staff", 1)]  # fmt: skip
    [w] = closed(run(m2, steps2, t + 300), "wait")
    assert (w.started_at, w.ended_at) == (t, t + 200)


def test_unattended_inside_opening_hours_only_AC_F2_3() -> None:
    m = machine()
    # staff zone empty from 07:00 (agent start) until 08:04:59: 299 s inside hours → nothing
    assert closed(run(m, [(at(8, 4, 59), "counter_staff", 1)], at(9)), "unattended") == []
    m = machine()
    [u] = closed(run(m, [(at(8, 5), "counter_staff", 1)], at(9)), "unattended")
    assert (u.started_at, u.ended_at) == (at(8), at(8, 5))


def test_unattended_is_announced_open_then_closed_with_same_id_AC_F2_3() -> None:
    m = machine()
    events = run(m, [(at(7, 30), "counter_staff", 1), (at(13), "counter_staff", 0)], at(13, 5))
    [opened] = [e for e in events if e.type == "unattended"]
    assert opened.ended_at is None and opened.started_at == at(13)
    [done] = m.set_count(at(13, 40), "counter_staff", 1)
    assert done.id == opened.id and done.ended_at == at(13, 40)


def test_unattended_closes_at_closing_time_AC_F2_3() -> None:
    m = machine()
    events = run(m, [(at(7, 30), "counter_staff", 1), (at(20, 30), "counter_staff", 0)], at(23))
    [u] = closed(events, "unattended")
    assert (u.started_at, u.ended_at) == (at(20, 30), at(21))


def test_confidence_and_frigate_ids_from_tracks_AC_F2_4() -> None:
    t = at(10)
    m = machine([(t, t + 30, 0.7, "cust"), (at(9), at(12), 0.9, "staff")])
    steps = [(at(9), "counter_staff", 1), (t, "counter_customer", 1), (t + 30, "counter_customer", 0)]
    [svc] = closed(run(m, steps, t + 40), "service")
    assert svc.confidence == 0.8 and svc.frigate_event_ids == ["cust", "staff"]
    assert machine()._event("wait", t, t + 1).confidence == 0.8  # fallback without tracks


def test_shutdown_closes_announced_unattended_and_forgets_the_rest() -> None:
    m = machine()
    run(m, [(at(7, 30), "counter_staff", 1), (at(13), "counter_staff", 0)], at(13, 6))
    [u] = m.shutdown(at(13, 10))
    assert u.ended_at == at(13, 10)
    assert m.staff_zero_since is None and m.c == 0 and m.s == 0
