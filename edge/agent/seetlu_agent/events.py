"""Events the agent sends to `POST /v1/edge/events` (docs/04 EdgeEvent)."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from seetlu_agent.ids import event_uuid

EventType = Literal["entry", "exit", "service", "wait", "unattended", "after_hours_motion"]


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class EdgeEvent:
    type: EventType
    camera: str
    started_at: float
    key: str  # stable identity → deterministic UUIDv7
    ended_at: float | None = None
    is_staff: bool = False
    confidence: float = 0.8
    frigate_event_ids: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return str(event_uuid(self.started_at, self.key))

    @property
    def duration_s(self) -> float:
        return 0.0 if self.ended_at is None else self.ended_at - self.started_at

    def to_api(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "camera": self.camera,
            "started_at": iso(self.started_at),
            "ended_at": None if self.ended_at is None else iso(self.ended_at),
            "is_staff": self.is_staff,
            "confidence": round(min(1.0, max(0.0, self.confidence)), 3),
            "frigate_event_ids": self.frigate_event_ids,
            "meta": self.meta,
        }
