"""M4: Frigate HTTP endpoints + real MQTT publishing through mosquitto."""

import threading
import time
from collections.abc import Iterator
from pathlib import Path

import paho.mqtt.client as mqtt
import pytest
from fastapi.testclient import TestClient
from paho.mqtt.enums import CallbackAPIVersion
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

from fake_frigate import generator, publisher, scenario
from fake_frigate.http import EDGE_BUFFER_S, create_app

MOSQUITTO_CONF = Path(__file__).resolve().parents[2] / "mosquitto" / "mosquitto.conf"


def test_m4_http_clip_and_snapshot() -> None:
    client = TestClient(create_app())
    r = client.get("/api/counter/start/1732096800/end/1732096820/clip.mp4")
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp4" and r.content[4:8] == b"ftyp"
    r = client.get("/api/door/latest.jpg")
    assert r.status_code == 200 and r.content[:2] == b"\xff\xd8"
    assert client.get("/api/kitchen/latest.jpg").status_code == 404
    assert client.get("/api/counter/start/20/end/10/clip.mp4").status_code == 404


def test_m4_ac_f5_4_clip_older_than_edge_buffer_is_unavailable() -> None:
    publisher.STATE.tick(1_800_000_000.0)
    try:
        client = TestClient(create_app())
        old = 1_800_000_000 - EDGE_BUFFER_S - 60
        assert client.get(f"/api/counter/start/{old}/end/{old + 20}/clip.mp4").status_code == 404
        recent = 1_800_000_000 - 3600
        assert client.get(f"/api/counter/start/{recent}/end/{recent + 20}/clip.mp4").status_code == 200
    finally:
        publisher.STATE.sim_now = None


def test_m4_sim_endpoints() -> None:
    client = TestClient(create_app())
    assert set(client.get("/sim/scenarios").json()["scenarios"]) >= {"normal-day", "power-cut-14-16"}
    assert client.post("/sim/scenarios/nope/run").status_code == 404


def test_m4_play_accelerates_time() -> None:
    msgs, _ = generator.generate(scenario.load("normal-day"))
    slept: list[float] = []
    published: list[str] = []
    n = publisher.play(msgs, lambda m: published.append(m.topic), speed=600, sleep=slept.append)
    assert n == len(msgs) == len(published)
    assert sum(slept) == pytest.approx((msgs[-1].ts - msgs[0].ts) / 600, rel=1e-6)  # ~144 s for a day


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


def test_m4_scenario_round_trips_through_mosquitto(broker: tuple[str, int]) -> None:
    host, port = broker
    received: list[generator.Message] = []
    done = threading.Event()
    sub = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="m4-test-sub")

    def on_message(_c: mqtt.Client, _u: object, msg: mqtt.MQTTMessage) -> None:
        received.append(generator.Message(0, len(received), msg.topic, msg.payload.decode()))
        if msg.topic == "seetlu-sim/done":
            done.set()

    sub.on_message = on_message
    sub.connect(host, port)
    sub.subscribe([("frigate/#", 1), ("seetlu-sim/#", 1)])
    sub.loop_start()
    time.sleep(0.5)
    try:
        sc = scenario.load("after-hours-motion")
        expected_msgs, _ = generator.generate(sc)
        n = publisher.run_scenario("after-hours-motion", host, port, speed=0)
        client, publish = publisher.mqtt_publisher(host, port)
        publish(generator.Message(0, 0, "seetlu-sim/done", "1"))
        client.disconnect()
        assert done.wait(30)
    finally:
        sub.loop_stop()
        sub.disconnect()
    got = [(m.topic, m.payload) for m in received if m.topic != "seetlu-sim/done"]
    want = [(m.topic, m.encoded().decode()) for m in expected_msgs]
    assert n == len(want)
    assert got == want  # same messages, same order (QoS 1, single publisher)
