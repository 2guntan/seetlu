"""CLI.

fake-frigate serve                          HTTP API + `frigate/available` heartbeat (default)
fake-frigate run <scenario> [--speed 600] [--date YYYY-MM-DD]   publish a scenario to MQTT
fake-frigate expect <scenario>|--all [--write]                   print / write expected.json
"""

import argparse
import json
import logging
import os
import threading
import time
from datetime import date
from pathlib import Path

import paho.mqtt.client as mqtt
import uvicorn
from paho.mqtt.enums import CallbackAPIVersion

from fake_frigate import generator, scenario
from fake_frigate.http import create_app
from fake_frigate.publisher import run_scenario

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


def expected_path(name: str) -> Path:
    return scenario.SCENARIOS_DIR / name / "expected.json"


def render_expected(name: str) -> str:
    return json.dumps(generator.expected(scenario.load(name)), indent=2, sort_keys=False) + "\n"


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(prog="fake-frigate")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("serve")
    run = sub.add_parser("run")
    run.add_argument("scenario")
    run.add_argument("--speed", type=float, default=600)
    run.add_argument("--date", type=date.fromisoformat, default=None)
    exp = sub.add_parser("expect")
    exp.add_argument("scenario", nargs="?")
    exp.add_argument("--all", action="store_true")
    exp.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)

    host = os.environ.get("MQTT_HOST", "localhost")
    port = int(os.environ.get("MQTT_PORT", "1883"))
    if args.cmd == "run":
        n = run_scenario(args.scenario, host, port, args.speed, args.date)
        print(f"published {n} messages")
    elif args.cmd == "expect":
        for name in scenario.names() if args.all else [args.scenario]:
            text = render_expected(name)
            if args.write:
                expected_path(name).write_text(text)
                print(f"wrote {expected_path(name)}")
            else:
                print(text, end="")
    else:
        threading.Thread(target=publish_available_forever, args=(host, port), daemon=True).start()
        uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))  # noqa: S104


if __name__ == "__main__":
    main()
