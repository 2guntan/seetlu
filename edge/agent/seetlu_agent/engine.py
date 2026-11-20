"""MQTT messages from Frigate → Seetlu edge events. Pure: no network, no clock of its own.

The caller passes the current time with every message (wall clock on a kit, the simulator clock in
tests and `make sim-day`), so a whole simulated day replays deterministically.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

from seetlu_agent.counter import CounterMachine, Thresholds
from seetlu_agent.door import COUNTER_ZONES, ZONE_CUSTOMER, ZONE_STAFF, Track
from seetlu_agent.edge_config import EdgeConfig, OpeningHours
from seetlu_agent.events import EdgeEvent

log = logging.getLogger(__name__)

AFTER_HOURS_MARGIN_S = 30 * 60  # docs/decisions.md (M4): motion counts as after-hours 30 min past hours
AFTER_HOURS_MIN_SCORE = 0.7
AFTER_HOURS_EVERY_S = 600  # one after_hours_motion per 10 min per camera
RESTART_GAP_S = 120  # no input for 2 min = the box was off; in-memory state is lost
STALE_TRACK_S = 30 * 60
SPAN_KEEP_S = 2 * 24 * 3600
SIM_CLOCK_TOPIC = "seetlu-sim/clock"


@dataclass
class CountCheck:
    started_at: float
    count: int = 0


class Engine:
    def __init__(self, cfg: EdgeConfig, namespace: str) -> None:
        self.ns = namespace
        self.tracks: dict[str, Track] = {}
        self.spans: list[tuple[float, float, float, str]] = []  # counter-zone presence of ended tracks
        self.after_hours_last: dict[str, float] = {}
        self.count_check: CountCheck | None = None
        self.last_ts: float | None = None
        self.stats: dict[str, Any] = {}
        self.frigate_online = False
        self.configure(cfg)
        self.counter = CounterMachine(self.counter_camera, namespace, self.th, self.hours, self._span_lookup)

    def configure(self, cfg: EdgeConfig) -> None:
        self.cfg = cfg
        self.hours = OpeningHours(cfg.shop.opening_hours, cfg.shop.timezone)
        self.th = Thresholds(cfg.shop.service_min_s, cfg.shop.wait_min_s, cfg.shop.unattended_min_s)
        self.door_camera = cfg.camera_for("door", "door")
        self.counter_camera = cfg.camera_for("counter", "counter")
        if hasattr(self, "counter"):
            self.counter.th, self.counter.hours, self.counter.camera = (
                self.th,
                self.hours,
                self.counter_camera,
            )

    # ---------- time ----------
    def _clock(self, ts: float) -> list[EdgeEvent]:
        out: list[EdgeEvent] = []
        if self.last_ts is None:
            self.counter.start(ts)
        elif ts - self.last_ts > RESTART_GAP_S or ts < self.last_ts - 5:
            log.info("time jumped %.0f s: treating as an agent restart", ts - self.last_ts)
            out += self.counter.shutdown(self.last_ts)
            self.tracks.clear()
            self.counter.start(ts)
        if self.last_ts is None or ts >= self.last_ts:
            self.last_ts = ts
        out += self.counter.advance(ts)
        return out

    def tick(self, ts: float) -> list[EdgeEvent]:
        out = self._clock(ts)
        for tid in [t for t, tr in self.tracks.items() if ts - tr.last_ts > STALE_TRACK_S]:
            out += self._flush(self.tracks.pop(tid))  # Frigate never sent `end` for it
        self.spans = [sp for sp in self.spans if sp[1] > ts - SPAN_KEEP_S]
        return out

    # ---------- input ----------
    def handle(self, topic: str, payload: bytes, ts: float) -> list[EdgeEvent]:
        out = self._clock(ts)
        if topic == "frigate/events":
            out += self._on_event(json.loads(payload), ts)
        elif topic.startswith("frigate/") and topic.endswith("/person"):
            zone = topic.split("/")[1]
            if zone in COUNTER_ZONES:
                out += self.counter.set_count(ts, zone, int(float(payload.decode() or 0)))
        elif topic == "frigate/stats":
            self.stats = json.loads(payload)
        elif topic == "frigate/available":
            self.frigate_online = payload.decode().strip() == "online"
        return out

    def _on_event(self, msg: dict[str, Any], now: float) -> list[EdgeEvent]:
        after = msg.get("after") or {}
        tid = str(after.get("id", ""))
        if not tid:
            return []
        ts = float(after.get("frame_time") or now)
        tr = self.tracks.get(tid)
        if tr is None:
            tr = Track(
                id=tid,
                camera=str(after.get("camera", "")),
                label=str(after.get("label", "")),
                first_ts=float(after.get("start_time") or ts),
                last_ts=ts,
            )
            self.tracks[tid] = tr
        score = float(after.get("top_score") or after.get("score") or 0.0)
        tr.observe(ts, list(after.get("current_zones") or []), score)
        out = self._after_hours(tr, ts, float(after.get("score") or score))
        if msg.get("type") == "end":
            out += self._flush(self.tracks.pop(tid))
        return out

    def _after_hours(self, tr: Track, ts: float, score: float) -> list[EdgeEvent]:
        if tr.after_hours_done or not tr.is_person or score < AFTER_HOURS_MIN_SCORE:
            return []
        tr.after_hours_done = True
        if self.hours.is_open(ts, AFTER_HOURS_MARGIN_S):
            return []
        last = self.after_hours_last.get(tr.camera)
        if last is not None and ts - last < AFTER_HOURS_EVERY_S:
            return []
        self.after_hours_last[tr.camera] = ts
        return [
            EdgeEvent(
                type="after_hours_motion",
                camera=tr.camera,
                started_at=ts,
                key=f"{self.ns}|{tr.camera}|{tr.id}|after_hours_motion",
                confidence=score,
                frigate_event_ids=[tr.id],
            )
        ]

    def _flush(self, tr: Track) -> list[EdgeEvent]:
        """Track ended: write its door crossings (with the final staff tag) and keep its counter span."""
        if tr.counter_first is not None:
            self.spans.append((tr.counter_first, tr.counter_last or tr.last_ts, tr.max_score, tr.id))
        if not tr.counted:
            return []
        out: list[EdgeEvent] = []
        for c in tr.crossings:
            out.append(
                EdgeEvent(
                    type=c.kind,  # type: ignore[arg-type]
                    camera=tr.camera,
                    started_at=c.ts,
                    key=f"{self.ns}|{tr.camera}|{tr.id}|{c.kind}",
                    is_staff=tr.is_staff,
                    confidence=tr.max_score,
                    frigate_event_ids=[tr.id],
                    meta={"staff_s": round(tr.staff_s)} if tr.is_staff else {},
                )
            )
            if c.kind == "entry" and self.count_check and c.ts >= self.count_check.started_at:
                self.count_check.count += 1
        return out

    def _span_lookup(self, a: float, b: float) -> tuple[list[float], list[str]]:
        spans = list(self.spans) + [
            (t.counter_first, t.last_ts, t.max_score, t.id)
            for t in self.tracks.values()
            if t.counter_first is not None
        ]
        hit = [(sc, tid) for s0, s1, sc, tid in spans if s0 <= b + 1 and s1 >= a - 1]
        return [sc for sc, _ in hit], sorted({tid for _, tid in hit})

    # ---------- count check (F8-3) ----------
    def count_check_start(self, ts: float) -> None:
        self.count_check = CountCheck(ts)

    def count_check_stop(self) -> int:
        n = self.count_check.count if self.count_check else 0
        self.count_check = None
        return n


__all__ = ["ZONE_CUSTOMER", "ZONE_STAFF", "Engine"]
