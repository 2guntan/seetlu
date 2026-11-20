"""`seetlu-agent replay`: run the real agent pipeline until the simulator goes quiet, then flush and exit.

Used by `make sim-day`: fake-frigate publishes one simulated day on MQTT (with `seetlu-sim/clock` ticks),
this process consumes it exactly like a kit would, uploads the events and heartbeats, and stops.
"""

import logging
import queue
import time
from collections import Counter

from seetlu_agent.config import AgentEnv
from seetlu_agent.main import Agent

log = logging.getLogger("seetlu_agent.replay")


def replay(env: AgentEnv, idle_exit_s: float = 15.0, start_timeout_s: float = 300.0) -> dict[str, int]:
    agent = Agent(env)
    t0 = time.monotonic()
    while not agent.ensure_registered():
        if time.monotonic() - t0 > start_timeout_s:
            raise SystemExit("kit could not register (is it claimed? run `make seed`)")
        agent.last.pop("register", None)
        time.sleep(2)
    agent.poll_config()
    client = agent.start_mqtt()
    handled = 0
    last_msg = time.monotonic()
    try:
        while True:
            try:
                topic, payload = agent.inbox.get(timeout=0.5)
                agent.handle(topic, payload)
                handled += 1
                last_msg = time.monotonic()
            except queue.Empty:
                pass
            if handled and time.monotonic() - last_msg > idle_exit_s:
                break
            if not handled and time.monotonic() - t0 > start_timeout_s:
                raise SystemExit("no simulator messages received")
            if handled % 5000 == 0:
                agent.uploader.run(agent.wall())
                agent.send_heartbeats()
    finally:
        client.loop_stop()
        client.disconnect()
    sent = 0
    for _ in range(5):  # re-register if the token was rotated meanwhile, then flush everything
        agent.last.pop("register", None)
        if agent.ensure_registered():
            sent += agent.uploader.run(agent.wall(), force=True)
            agent.send_heartbeats()
        if agent.outbox.depth() + agent.pending_heartbeats() == 0:
            break
        time.sleep(2)
    counts = Counter(e["type"] for _, e in agent.outbox.due(float("inf"), 10**6))
    log.info("replay done: %d messages, %d events uploaded, %d still queued %s", handled, sent,
             agent.outbox.depth(), dict(counts))  # fmt: skip
    return {
        "messages": handled,
        "uploaded": sent,
        "queued": agent.outbox.depth() + agent.pending_heartbeats(),
    }
