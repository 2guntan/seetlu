"""Counter state machine (F2): service, wait, unattended. Pure and time-exact (docs/05).

Inputs are the live person counts of `counter_customer` (c) and `counter_staff` (s). Counts are piecewise
constant between MQTT messages, so instead of sampling every second we evaluate every "continuously for
N seconds" rule exactly at its deadline when `advance(now)` is called; the result is identical to a 1 s
re-evaluation with last values, without rounding.
"""

from collections.abc import Callable
from dataclasses import dataclass

from seetlu_agent.edge_config import OpeningHours
from seetlu_agent.events import EdgeEvent

SERVICE_CLOSE_S = 5.0
FALLBACK_CONFIDENCE = 0.8

# (start, end) -> (scores of tracks seen in the counter zones, their Frigate ids)
SpanLookup = Callable[[float, float], tuple[list[float], list[str]]]


@dataclass(frozen=True)
class Thresholds:
    service_min_s: int = 15
    wait_min_s: int = 180
    unattended_min_s: int = 300


class CounterMachine:
    def __init__(
        self, camera: str, namespace: str, th: Thresholds, hours: OpeningHours, spans: SpanLookup
    ) -> None:
        self.camera, self.ns, self.th, self.hours, self.spans = camera, namespace, th, hours, spans
        self._reset()

    def _reset(self) -> None:
        self.c = 0
        self.s = 0
        self.now: float | None = None
        self.svc_start: float | None = None  # both zones occupied since
        self.svc_break: float | None = None  # open service, one zone empty since
        self.wait_since: float | None = None  # c >= 1 and s == 0 since
        self.staff_zero_since: float | None = None  # s == 0 since (not yet accounted for)
        self.unatt_open: float | None = None  # start of the unattended event already announced

    # ---------- helpers ----------
    def _event(self, kind: str, a: float, b: float | None) -> EdgeEvent:
        scores, ids = self.spans(a, b if b is not None else a)
        conf = sum(scores) / len(scores) if scores else FALLBACK_CONFIDENCE
        return EdgeEvent(
            type=kind,  # type: ignore[arg-type]
            camera=self.camera,
            started_at=a,
            ended_at=b,
            key=f"{self.ns}|{self.camera}|{kind}|{a:.3f}",
            confidence=conf,
            frigate_event_ids=ids,
        )

    @property
    def both(self) -> bool:
        return self.c >= 1 and self.s >= 1

    @property
    def waiting(self) -> bool:
        return self.c >= 1 and self.s == 0

    # ---------- time ----------
    def advance(self, now: float) -> list[EdgeEvent]:
        """Fire every deadline up to `now` with the current counts."""
        out: list[EdgeEvent] = []
        if self.now is not None and now < self.now:
            now = self.now
        if self.svc_break is not None and now - self.svc_break >= SERVICE_CLOSE_S:
            assert self.svc_start is not None
            out.append(self._event("service", self.svc_start, self.svc_break))
            self.svc_start = self.svc_break = None
        if self.staff_zero_since is not None:
            out += self._unattended_until(now, staff_back=False)
        self.now = now
        return out

    def _unattended_until(self, now: float, staff_back: bool) -> list[EdgeEvent]:
        """Account for the staff-empty period [staff_zero_since, now] against opening hours."""
        assert self.staff_zero_since is not None
        out: list[EdgeEvent] = []
        min_s = self.th.unattended_min_s
        for o, c in self.hours.intervals(self.staff_zero_since, now):
            a = max(self.staff_zero_since, o)
            if c <= now:  # closing time reached while still empty: close at closing time
                if c - a >= min_s:
                    out.append(self._event("unattended", a, c))
                self.unatt_open = None
                self.staff_zero_since = c
                continue
            if staff_back:
                if now - a >= min_s:
                    out.append(self._event("unattended", a, now))
                self.unatt_open = None
            elif now - a >= min_s and self.unatt_open is None:
                self.unatt_open = a  # announce the open event (ended_at null) so alerts can fire
                out.append(self._event("unattended", a, None))
        return out

    # ---------- inputs ----------
    def set_count(self, ts: float, zone: str, count: int) -> list[EdgeEvent]:
        out = self.advance(ts)
        was_both, was_waiting, was_staff = self.both, self.waiting, self.s >= 1
        if zone == "counter_customer":
            self.c = max(0, count)
        elif zone == "counter_staff":
            self.s = max(0, count)
        else:
            return out
        # service
        if self.both and not was_both:
            if self.svc_break is not None:
                self.svc_break = None  # back within 5 s: same service continues
            else:
                self.svc_start = ts
        elif was_both and not self.both and self.svc_start is not None:
            if ts - self.svc_start >= self.th.service_min_s:
                self.svc_break = ts
            else:
                self.svc_start = None
        # wait
        if self.waiting and not was_waiting:
            self.wait_since = ts
        elif was_waiting and not self.waiting and self.wait_since is not None:
            if ts - self.wait_since >= self.th.wait_min_s:
                out.append(self._event("wait", self.wait_since, ts))
            self.wait_since = None
        # unattended
        staff = self.s >= 1
        if was_staff and not staff:
            self.staff_zero_since = ts
        elif staff and not was_staff and self.staff_zero_since is not None:
            out += self._unattended_until(ts, staff_back=True)
            self.staff_zero_since = None
        elif not staff and self.staff_zero_since is None:
            self.staff_zero_since = ts
        return out

    def start(self, ts: float) -> None:
        """Agent (re)start: nobody is known to be at the counter yet, so the staff zone counts as empty."""
        self.now = ts
        if self.s == 0 and self.staff_zero_since is None:
            self.staff_zero_since = ts

    def shutdown(self, ts: float) -> list[EdgeEvent]:
        """The agent stops seeing data (power cut, restart): close what is announced, drop the rest."""
        out: list[EdgeEvent] = []
        if self.unatt_open is not None:
            out.append(self._event("unattended", self.unatt_open, ts))
        self._reset()
        return out
