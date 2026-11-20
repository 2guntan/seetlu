"""Agent entry point. M0: connects to MQTT and logs Frigate availability; real logic lands in M5."""

import logging
import time

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from seetlu_agent import __version__
from seetlu_agent.config import AgentEnv

log = logging.getLogger("seetlu_agent")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    env = AgentEnv.from_env()
    log.info("seetlu-agent %s starting for kit %s", __version__, env.kit_serial)
    client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=f"seetlu-agent-{env.kit_serial}")

    def on_message(_c: mqtt.Client, _u: object, msg: mqtt.MQTTMessage) -> None:
        log.info("mqtt %s %s", msg.topic, msg.payload[:200].decode(errors="replace"))

    client.on_message = on_message
    while True:
        try:
            client.connect(env.mqtt_host, env.mqtt_port)
            break
        except OSError as exc:
            log.warning("mqtt connect failed (%s), retrying in 5 s", exc)
            time.sleep(5)
    client.subscribe("frigate/#")
    client.loop_forever()


if __name__ == "__main__":
    main()
