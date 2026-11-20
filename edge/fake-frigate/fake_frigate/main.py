"""Entry point: serve HTTP and publish `frigate/available` on MQTT."""

import logging
import os
import threading
import time

import paho.mqtt.client as mqtt
import uvicorn
from paho.mqtt.enums import CallbackAPIVersion

from fake_frigate.http import create_app

log = logging.getLogger("fake_frigate")


def publish_available_forever(host: str, port: int) -> None:
    client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="fake-frigate")
    while True:
        try:
            client.connect(host, port)
            break
        except OSError as exc:
            log.warning("mqtt connect failed (%s), retrying in 5 s", exc)
            time.sleep(5)
    client.loop_start()
    while True:
        client.publish("frigate/available", "online", retain=True)
        time.sleep(30)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    host = os.environ.get("MQTT_HOST", "localhost")
    port = int(os.environ.get("MQTT_PORT", "1883"))
    threading.Thread(target=publish_available_forever, args=(host, port), daemon=True).start()
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))  # noqa: S104


if __name__ == "__main__":
    main()
