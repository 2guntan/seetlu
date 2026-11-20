"""M5 acceptance over a real broker: fake-frigate publishes a scenario to mosquitto, the agent consumes it
on the simulator clock, and the events it uploads match the scenario's expected.json."""

import json
import queue
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

from fake_frigate import publisher, scenario
from fake_frigate.main import expected_path
from seetlu_agent.events import EdgeEvent
from tests.scenario_replay import summarise
from tests.test_agent import make_agent

MOSQUITTO_CONF = Path(__file__).resolve().parents[2] / "mosquitto" / "mosquitto.conf"
KEYS = ("door_entries", "door_exits", "service", "wait", "unattended", "unattended_minutes",
        "after_hours_motion")  # fmt: skip


@pytest.fixture(scope="module")
def broker() -> Iterator[tuple[str, int]]:
    container = (
        DockerContainer("eclipse-mosquitto:2")
        .with_volume_mapping(str(MOSQUITTO_CONF), "/mosquitto/config/mosquitto.conf", "ro")
        .with_exposed_ports(1883)
    )
    with container:
        wait_for_logs(container, "running", timeout=30)
        yield container.get_container_host_ip(), int(container.get_exposed_port(1883))


def test_scenario_over_mqtt_gives_expected_events_AC_F1_1_AC_F2_1(
    tmp_path: Path, broker: tuple[str, int]
) -> None:
    host, port = broker
    name = "normal-day"
    agent, cloud = make_agent(tmp_path, name, mqtt_host=host, mqtt_port=port)
    agent.periodic()
    client = agent.start_mqtt()
    time.sleep(0.5)
    try:
        n = publisher.run_scenario(name, host, port, speed=0)
        handled, idle_since = 0, time.monotonic()
        while time.monotonic() - idle_since < 3:
            try:
                topic, payload = agent.inbox.get(timeout=0.2)
            except queue.Empty:
                continue
            agent.handle(topic, payload)
            handled += 1
            idle_since = time.monotonic()
    finally:
        client.loop_stop()
        client.disconnect()
    assert handled == n
    agent.uploader.run(agent.wall(), force=True)
    sc = scenario.load(name)
    events = {
        e["id"]: EdgeEvent(
            type=e["type"], camera=e["camera"], key="",
            started_at=_ts(e["started_at"]), ended_at=_ts(e["ended_at"]) if e["ended_at"] else None,
        )
        for e in cloud.events.values()
    }  # fmt: skip
    truth = json.loads(expected_path(name).read_text())["truth"]
    got = summarise(sc, events)
    assert {k: got[k] for k in KEYS} == {k: truth[k] for k in KEYS}


def _ts(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
