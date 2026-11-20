"""Turn a scenario into (a) a deterministic, time-ordered list of Frigate-shaped MQTT messages and
(b) the ground truth a correct seetlu-agent must report (`expected.json`).

Message shapes follow the Frigate MQTT docs (checked against the 0.18 docs, see docs/decisions.md):
- `frigate/events`: {"type": "new"|"update"|"end", "before": {...}, "after": {...}}
- `frigate/<zone>/person`: integer person count in a zone (payload is the number as text)
- `frigate/available`: "online"; `frigate/stats`: stats JSON
- `seetlu-sim/clock`: simulator-only wall clock (epoch seconds), so the agent can run on scenario time

Rules that keep the ground truth exact (docs/05 algorithms):
- counter visits never overlap and are separated by >= 8 s (a service closes after 5 s empty);
- staff step-aways for "wait" customers last < 300 s (no unattended) and >= 190 s (a wait);
- nothing is generated inside an outage (the box is off: no messages, no clock).
"""

import hashlib
import json
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, time
from typing import Any

from fake_frigate.scenario import AfterHours, Customers, Flicker, Scenario, Staff

DOOR_OUT, DOOR_IN = "door_out", "door_in"
ZONE_CUSTOMER, ZONE_STAFF = "counter_customer", "counter_staff"
SERVICE_CLOSE_GAP_S = 8
UNATTENDED_MIN_S = 300
WAIT_MIN_S = 180
CUSTOMER_PATIENCE_S = 240
STATS_EVERY_S = 60
FRIGATE_VERSION = "0.16.0-fake"


@dataclass(order=True)
class Message:
    ts: float
    seq: int
    topic: str = field(compare=False)
    payload: Any = field(compare=False)
    retain: bool = field(default=False, compare=False)

    def encoded(self) -> bytes:
        if isinstance(self.payload, str | int | float):
            return str(self.payload).encode()
        return json.dumps(self.payload, sort_keys=True, separators=(",", ":")).encode()


@dataclass
class Truth:
    door_entries: int = 0
    door_exits: int = 0
    customer_entries: int = 0
    staff_entries: int = 0
    hourly_entries: dict[str, int] = field(default_factory=dict)
    service: int = 0
    wait: int = 0
    unattended: int = 0
    unattended_minutes: int = 0
    after_hours_motion: int = 0
    missing_hours: list[int] = field(default_factory=list)
    visitors_in: int = 0


class Builder:
    def __init__(self, sc: Scenario) -> None:
        self.sc = sc
        self.rng = random.Random(f"{sc.name}:{sc.seed}:{sc.date.isoformat()}")  # noqa: S311 - simulation only
        self.msgs: list[Message] = []
        self.seq = 0
        self.truth = Truth()
        self.outages = [(sc.at(a), sc.at(b)) for a, b in sc.outages]
        self.open_s, self.close_s = sc.at(sc.opening[0]), sc.at(sc.opening[1])
        self.staff_absent: list[tuple[float, float]] = []  # counter_staff empty intervals
        self.counter_free_at = 0.0
        self.zone_deltas: list[tuple[float, str, int]] = []
        self.staff_present: list[tuple[float, float]] = []

    # ---------- primitives ----------
    def in_outage(self, a: float, b: float | None = None) -> bool:
        b = a if b is None else b
        return any(a < o1 and b >= o0 for o0, o1 in self.outages)  # outage = [o0, o1)

    def emit(self, ts: float, topic: str, payload: Any, retain: bool = False) -> None:
        if self.in_outage(ts):
            return
        self.seq += 1
        self.msgs.append(Message(round(ts, 3), self.seq, topic, payload, retain))

    def track_id(self, ts: float) -> str:
        return f"{ts:.6f}-{self.rng.randrange(16**6):06x}"

    def track(self, camera: str, start: float, steps: list[tuple[float, list[str]]], score: float) -> str:
        """Emit new/update/end for one tracked person. steps = [(ts, current_zones), ...]; last ts = end."""
        tid = self.track_id(start)
        entered: list[str] = []
        before: dict[str, Any] | None = None
        for i, (ts, zones) in enumerate(steps):
            for z in zones:
                if z not in entered:
                    entered.append(z)
            last = i == len(steps) - 1
            after = {
                "id": tid, "camera": camera, "label": "person", "sub_label": None, "score": score,
                "top_score": score, "false_positive": False, "start_time": start,
                "end_time": ts if last else None,
                "current_zones": list(zones), "entered_zones": list(entered), "stationary": False,
                "active": not last, "has_clip": True, "has_snapshot": False, "frame_time": ts,
            }  # fmt: skip
            kind = "new" if i == 0 else ("end" if last else "update")
            self.emit(ts, "frigate/events", {"type": kind, "before": before or after, "after": after})
            before = after
        return tid

    def zone(self, ts: float, zone: str, delta: int) -> None:
        self.zone_deltas.append((ts, zone, delta))

    # ---------- door ----------
    def entry(self, ts: float, *, staff: bool = False) -> None:
        if self.in_outage(ts - 1, ts + 3):
            return
        score = round(self.rng.uniform(0.7, 0.95), 2)
        self.track("door", ts - 1, [(ts - 1, [DOOR_OUT]), (ts, [DOOR_IN]), (ts + 1, []), (ts + 2, [])], score)
        self.truth.door_entries += 1
        if staff:
            self.truth.staff_entries += 1
        else:
            self.truth.customer_entries += 1
        hour = datetime.fromtimestamp(ts, self.sc.tz).hour
        key = f"{hour:02d}"
        self.truth.hourly_entries[key] = self.truth.hourly_entries.get(key, 0) + 1

    def exit(self, ts: float) -> None:
        if self.in_outage(ts - 1, ts + 3):
            return
        score = round(self.rng.uniform(0.7, 0.95), 2)
        self.track("door", ts - 1, [(ts - 1, [DOOR_IN]), (ts, [DOOR_OUT]), (ts + 1, []), (ts + 2, [])], score)
        self.truth.door_exits += 1

    # ---------- actors ----------
    def staff(self, a: Staff) -> None:
        arrive, leave = self.sc.at(a.arrive), self.sc.at(a.leave)
        self.entry(arrive, staff=True)
        present: list[tuple[float, float]] = []
        cursor = arrive + 60
        for b0, b1 in a.breaks:
            present.append((cursor, self.sc.at(b0)))
            cursor = self.sc.at(b1)
        present.append((cursor, leave - 60))
        self.staff_present += present
        self.exit(leave)

    def staff_is_present(self, a: float, b: float) -> bool:
        """Staff at the counter for the whole of [a, b]."""
        return any(p0 <= a and b <= p1 for p0, p1 in self.staff_present)

    def staff_overlaps(self, a: float, b: float) -> bool:
        """Staff at the counter at any moment of [a, b]."""
        return any(a < p1 and b > p0 for p0, p1 in self.staff_present)

    def counter_visit(self, desired: float, service_s: int, wait: bool) -> float | None:
        """Schedule one customer at the counter. Returns when they leave the counter (or None)."""
        start = max(desired, self.counter_free_at + SERVICE_CLOSE_GAP_S)
        score = round(self.rng.uniform(0.6, 0.9), 2)
        if self.staff_is_present(start - 10, start + 280 + service_s + 30):
            if wait:
                w = self.rng.randint(190, 280)
                self.staff_absent.append((start, start + w))
                self.truth.wait += 1
                served_from = start + w
            else:
                served_from = start
            end = served_from + service_s
            if self.in_outage(start, end + 2):
                return None
            self.track(
                "counter", start, [(start, [ZONE_CUSTOMER]), (end, [ZONE_CUSTOMER]), (end + 1, [])], score
            )
            self.zone(start, ZONE_CUSTOMER, +1)
            self.zone(end, ZONE_CUSTOMER, -1)
            self.truth.service += 1
            self.counter_free_at = end
            return end
        # staff not there: the customer waits up to their patience, then leaves unserved
        end = start + CUSTOMER_PATIENCE_S
        if self.in_outage(start, end + 2) or self.staff_overlaps(start - 10, end + 10):
            return None
        self.track("counter", start, [(start, [ZONE_CUSTOMER]), (end, [ZONE_CUSTOMER]), (end + 1, [])], score)
        self.zone(start, ZONE_CUSTOMER, +1)
        self.zone(end, ZONE_CUSTOMER, -1)
        if CUSTOMER_PATIENCE_S >= WAIT_MIN_S:
            self.truth.wait += 1
        self.counter_free_at = end
        return end

    def customers(self, c: Customers) -> None:
        w0, w1 = self.sc.at(c.window[0]), self.sc.at(c.window[1])
        p = (self.sc.at(c.peak[0]), self.sc.at(c.peak[1])) if c.peak else None
        groups = max(1, c.count // c.group_size)
        arrivals: list[float] = []
        for _ in range(groups):
            if p and self.rng.random() < 0.5:
                arrivals.append(self.rng.uniform(p[0], p[1] - 600))
            else:
                arrivals.append(self.rng.uniform(w0, w1 - 900))
        for t in sorted(arrivals):
            t = float(int(t))
            if self.in_outage(t - 5, t + 1200):
                continue  # nobody is seen around an outage: keeps the truth exact
            for g in range(c.group_size):
                self.entry(t + g * 0.3)
            for g in range(c.group_size):
                dwell = self.rng.randint(60, 300)
                leave_at = t + g * 0.3 + dwell
                if self.rng.random() < c.served_ratio:
                    svc = self.rng.randint(*c.service_s)
                    wait = self.rng.random() < c.wait_ratio
                    left = self.counter_visit(t + g * 0.3 + self.rng.randint(20, 90), svc, wait)
                    if left is not None:
                        leave_at = left + self.rng.randint(10, 60)
                self.exit(float(int(leave_at)) + 0.5)

    def flicker(self, f: Flicker) -> None:
        w0, w1 = self.sc.at(f.window[0]), self.sc.at(f.window[1])
        for _ in range(f.count):
            t = float(int(self.rng.uniform(w0, w1 - 900)))
            steps = [(t - 1, [DOOR_OUT]), (t, [DOOR_IN]), (t + 2, [DOOR_OUT]), (t + 4, [DOOR_IN]),
                     (t + 6, [DOOR_OUT]), (t + 8, [DOOR_IN]), (t + 9, [])]  # fmt: skip
            self.track("door", t - 1, steps, 0.8)
            self.truth.door_entries += 1  # all crossings within 10 s count once (AC-F1-2)
            self.truth.customer_entries += 1
            key = f"{datetime.fromtimestamp(t, self.sc.tz).hour:02d}"
            self.truth.hourly_entries[key] = self.truth.hourly_entries.get(key, 0) + 1
            self.exit(t + self.rng.randint(120, 400) + 0.5)

    def after_hours(self, a: AfterHours) -> None:
        t = self.sc.at(a.at)
        self.track("door", t, [(t, []), (t + 15, []), (t + 20, [])], 0.82)
        self.truth.after_hours_motion += 1

    # ---------- derived streams ----------
    def staff_zone_stream(self) -> None:
        present = self.staff_present
        intervals: list[tuple[float, float]] = []
        for p0, p1 in present:
            cuts = sorted(a for a in self.staff_absent if p0 < a[0] < p1)
            cursor = p0
            for a0, a1 in cuts:
                intervals.append((cursor, a0))
                cursor = a1
            intervals.append((cursor, p1))
        # Frigate restarts after a power cut: tracks never span an outage
        for o0, o1 in self.outages:
            split: list[tuple[float, float]] = []
            for i0, i1 in intervals:
                if i1 <= o0 - 3 or i0 >= o1:
                    split.append((i0, i1))
                    continue
                if i0 < o0 - 3:
                    split.append((i0, o0 - 3))
                if i1 > o1 + 1:
                    split.append((o1 + 1, i1))
            intervals = split
        for i0, i1 in intervals:
            if i1 - i0 < 1:
                continue
            steps: list[tuple[float, list[str]]] = [(i0, [ZONE_STAFF])]
            t = i0 + 60
            while t < i1:
                steps.append((t, [ZONE_STAFF]))
                t += 60
            steps += [(i1, [ZONE_STAFF]), (i1 + 1, [])]
            self.track("counter", i0, steps, 0.88)
            self.zone(i0, ZONE_STAFF, +1)
            self.zone(i1, ZONE_STAFF, -1)
        # unattended truth: staff zone empty >= 300 s inside opening hours
        gaps: list[tuple[float, float]] = []
        cursor = self.open_s
        for i0, i1 in sorted(intervals):
            if i0 > cursor:
                gaps.append((cursor, min(i0, self.close_s)))
            cursor = max(cursor, i1)
        if cursor < self.close_s:
            gaps.append((cursor, self.close_s))
        for g0, g1 in gaps:
            if g1 - g0 >= UNATTENDED_MIN_S and not self.in_outage(g0, g1):
                self.truth.unattended += 1
                self.truth.unattended_minutes += int((g1 - g0) // 60)

    def zone_count_stream(self) -> None:
        counts = {ZONE_CUSTOMER: 0, ZONE_STAFF: 0}
        for ts, zone, delta in sorted(self.zone_deltas):
            counts[zone] += delta
            self.emit(ts, f"frigate/{zone}/person", counts[zone])

    def clock_and_stats(self) -> None:
        day0 = self.sc.at(time(0, 0))
        day1 = self.sc.at(time(0, 0), day_offset=1)
        self.emit(day0, "frigate/available", "online", retain=True)
        t = day0
        was_out = False
        while t < day1:
            out = self.in_outage(t)
            if was_out and not out:
                self.emit(t, "frigate/available", "online", retain=True)
            was_out = out
            self.emit(t, "seetlu-sim/clock", int(t))
            self.emit(t, "frigate/stats", {
                "cameras": {"door": {"camera_fps": 5.0, "detection_fps": 4.8},
                            "counter": {"camera_fps": 5.0, "detection_fps": 4.9}},
                "service": {"version": FRIGATE_VERSION, "uptime": int(t - day0)},
            })  # fmt: skip
            t += STATS_EVERY_S
        for o0, o1 in self.outages:
            start = datetime.fromtimestamp(o0, self.sc.tz)
            end = datetime.fromtimestamp(o1, self.sc.tz)
            self.truth.missing_hours += list(range(start.hour, end.hour if end.minute == 0 else end.hour + 1))

    def build(self) -> tuple[list[Message], Truth]:
        staff = [a for a in self.sc.actors if isinstance(a, Staff)]
        for a in staff:
            self.staff(a)
        for actor in self.sc.actors:
            if isinstance(actor, Customers):
                self.customers(actor)
            elif isinstance(actor, Flicker):
                self.flicker(actor)
            elif isinstance(actor, AfterHours):
                self.after_hours(actor)
        self.staff_zone_stream()
        self.zone_count_stream()
        self.clock_and_stats()
        self.truth.visitors_in = max(0, self.truth.door_entries - self.sc.expected_staff)
        self.truth.hourly_entries = dict(sorted(self.truth.hourly_entries.items()))
        self.truth.missing_hours = sorted(set(self.truth.missing_hours))
        return sorted(self.msgs), self.truth


def generate(sc: Scenario) -> tuple[list[Message], Truth]:
    return Builder(sc).build()


def digest(msgs: list[Message]) -> str:
    h = hashlib.sha256()
    for msg in msgs:
        h.update(f"{msg.ts:.3f}|{msg.topic}|".encode())
        h.update(msg.encoded())
        h.update(b"\n")
    return h.hexdigest()


def expected(sc: Scenario) -> dict[str, Any]:
    msgs, truth = generate(sc)
    return {
        "scenario": sc.name,
        "date": sc.date.isoformat(),
        "timezone": sc.timezone,
        "opening": [sc.opening[0].strftime("%H:%M"), sc.opening[1].strftime("%H:%M")],
        "expected_staff": sc.expected_staff,
        "truth": asdict(truth),
        "messages": {"count": len(msgs), "sha256": digest(msgs)},
    }
