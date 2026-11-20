"""Publish a generated scenario to MQTT at accelerated time (`speed` = simulated seconds per real second)."""

import logging
import threading
import time
from collections.abc import Callable
from datetime import date

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from fake_frigate import generator, scenario
from fake_frigate.generator import Message

log = logging.getLogger("fake_frigate.publisher")

Publish = Callable[[Message], None]
CLOCK_TOPIC = "seetlu-sim/clock"


class SimState:
    """Latest simulated time, shared with the HTTP side (clip availability uses it)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.sim_now: float | None = None
        self.running: str | None = None

    def tick(self, ts: float) -> None:
        with self.lock:
            self.sim_now = ts


STATE = SimState()


def play(
    msgs: list[Message], publish: Publish, speed: float, sleep: Callable[[float], None] = time.sleep
) -> int:
    """Publish messages in order; with speed <= 0 publish as fast as possible."""
    prev: float | None = None
    for msg in msgs:
        if prev is not None and speed > 0 and msg.ts > prev:
            sleep((msg.ts - prev) / speed)
        publish(msg)
        STATE.tick(msg.ts)
        prev = msg.ts
    return len(msgs)


def with_clock(msgs: list[Message]) -> list[Message]:
    """Precede every message with a `seetlu-sim/clock` tick carrying its exact simulated time, so an agent
    running on the simulator clock (SIM_CLOCK=1) timestamps zone counts exactly, at any playback speed."""
    out: list[Message] = []
    for msg in msgs:
        if msg.topic != CLOCK_TOPIC:
            out.append(Message(msg.ts, msg.seq, CLOCK_TOPIC, f"{msg.ts:.3f}"))
        out.append(msg)
    return out


def mqtt_publisher(host: str, port: int) -> tuple[mqtt.Client, Publish]:
    client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=f"fake-frigate-run-{time.time_ns()}")
    client.connect(host, port)
    client.loop_start()

    def publish(msg: Message) -> None:
        client.publish(msg.topic, msg.encoded(), qos=1, retain=msg.retain).wait_for_publish(timeout=10)

    return client, publish


def run_scenario(name: str, host: str, port: int, speed: float, day: date | None = None) -> int:
    sc = scenario.load(name)
    if day is not None:
        sc = sc.with_date(day)
    msgs, _ = generator.generate(sc)
    msgs = with_clock(msgs)
    client, publish = mqtt_publisher(host, port)
    STATE.running = sc.name
    try:
        log.info("playing %s (%s): %d messages at speed %s", sc.name, sc.date, len(msgs), speed)
        return play(msgs, publish, speed)
    finally:
        STATE.running = None
        client.loop_stop()
        client.disconnect()
