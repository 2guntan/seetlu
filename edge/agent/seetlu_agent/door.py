"""Per-track state: door crossings (F1), staff tagging (F1-3). Pure, no I/O (docs/05 algorithms)."""

from dataclasses import dataclass, field

DOOR_OUT, DOOR_IN = "door_out", "door_in"
ZONE_CUSTOMER, ZONE_STAFF = "counter_customer", "counter_staff"
COUNTER_ZONES = (ZONE_CUSTOMER, ZONE_STAFF)
DEBOUNCE_S = 10.0
MIN_SCORE = 0.6
STAFF_MIN_S = 600.0


@dataclass
class Crossing:
    kind: str  # "entry" | "exit"
    ts: float


@dataclass
class Track:
    id: str
    camera: str
    label: str
    first_ts: float
    last_ts: float
    max_score: float = 0.0
    door_seq: list[str] = field(default_factory=list)
    crossings: list[Crossing] = field(default_factory=list)
    staff_s: float = 0.0
    in_staff: bool = False
    in_counter: bool = False
    counter_first: float | None = None
    counter_last: float | None = None
    after_hours_done: bool = False

    @property
    def is_person(self) -> bool:
        return self.label == "person"

    @property
    def counted(self) -> bool:
        """Tracks that are not `person` or never reach score 0.6 are ignored (docs/05)."""
        return self.is_person and self.max_score >= MIN_SCORE

    @property
    def is_staff(self) -> bool:
        return self.staff_s >= STAFF_MIN_S

    def observe(self, ts: float, zones: list[str], score: float) -> None:
        """One Frigate `new`/`update`/`end` message for this track."""
        if self.in_staff and ts > self.last_ts:
            self.staff_s += ts - self.last_ts
        self.max_score = max(self.max_score, score)
        self.in_staff = ZONE_STAFF in zones
        if any(z in COUNTER_ZONES for z in zones):
            self.counter_first = ts if self.counter_first is None else self.counter_first
            self.counter_last = ts
            self.in_counter = True
        elif self.in_counter:
            self.counter_last = ts
            self.in_counter = False
        self.last_ts = max(self.last_ts, ts)

        door = next((z for z in zones if z in (DOOR_OUT, DOOR_IN)), None)
        if door is None or (self.door_seq and self.door_seq[-1] == door):
            return
        self.door_seq.append(door)
        if len(self.door_seq) < 2:
            return
        kind = "entry" if door == DOOR_IN else "exit"  # out→in is an entry, in→out an exit
        last = self.crossings[-1].ts if self.crossings else None
        if last is not None and ts - last <= DEBOUNCE_S:
            return  # AC-F1-2: re-crossing within 10 s of the counted one is ignored
        if any(c.kind == kind for c in self.crossings):
            return  # at most one entry and one exit per track
        self.crossings.append(Crossing(kind, ts))
