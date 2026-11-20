"""Replay a fake-frigate scenario through the agent engine (no MQTT) and summarise the events."""

from collections import Counter
from datetime import datetime
from typing import Any

from fake_frigate import generator, scenario
from seetlu_agent.edge_config import DAYS, EdgeConfig
from seetlu_agent.engine import Engine
from seetlu_agent.events import EdgeEvent


def config_for(sc: scenario.Scenario) -> EdgeConfig:
    hours = [[sc.opening[0].strftime("%H:%M"), sc.opening[1].strftime("%H:%M")]]
    return EdgeConfig.model_validate(
        {
            "config_version": 1,
            "shop": {
                "timezone": sc.timezone,
                "opening_hours": dict.fromkeys(DAYS, hours),
                "expected_staff": sc.expected_staff,
                "service_min_s": 15,
                "wait_min_s": 180,
                "unattended_min_s": 300,
            },
            "cameras": [{"name": "door", "role": "door"}, {"name": "counter", "role": "counter"}],
        }
    )


def replay(name: str) -> tuple[scenario.Scenario, dict[str, EdgeEvent]]:
    sc = scenario.load(name)
    msgs, _ = generator.generate(sc)
    engine = Engine(config_for(sc), namespace="TEST-KIT")
    final: dict[str, EdgeEvent] = {}
    for msg in msgs:
        for ev in engine.handle(msg.topic, msg.encoded(), msg.ts):
            final[ev.id] = ev  # same id = update of the same event (upsert on the server)
    for ev in engine.tick(sc.at(sc.opening[1], day_offset=1)):
        final[ev.id] = ev
    return sc, final


def summarise(sc: scenario.Scenario, events: dict[str, EdgeEvent]) -> dict[str, Any]:
    evs = list(events.values())
    by_type = Counter(e.type for e in evs)
    entries = [e for e in evs if e.type == "entry"]
    hourly = Counter(f"{datetime.fromtimestamp(e.started_at, sc.tz).hour:02d}" for e in entries)
    unattended = [e for e in evs if e.type == "unattended" and e.ended_at is not None]
    return {
        "door_entries": by_type["entry"],
        "door_exits": by_type["exit"],
        "hourly_entries": dict(sorted(hourly.items())),
        "service": by_type["service"],
        "wait": by_type["wait"],
        "unattended": len(unattended),
        "unattended_minutes": sum(int(e.duration_s // 60) for e in unattended),
        "after_hours_motion": by_type["after_hours_motion"],
    }
