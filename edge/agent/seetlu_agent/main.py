"""seetlu-agent runtime: wires MQTT → engine → outbox → uploader, plus config polling, commands,
heartbeats and the LAN setup page (docs/05).

Time: wall clock on a kit. With SIM_CLOCK=1 (dev stack, `make sim-day`) the agent runs on the
simulator's `seetlu-sim/clock` topic so a simulated day can be replayed at any speed.
"""

import json
import logging
import queue
import sys
import threading
import time
from collections.abc import Callable

import httpx
import paho.mqtt.client as mqtt
import uvicorn
from paho.mqtt.enums import CallbackAPIVersion

from seetlu_agent import __version__, frigate_config, heartbeat, panel
from seetlu_agent.api import Api, ApiError
from seetlu_agent.commands import CommandRunner
from seetlu_agent.config import AgentEnv
from seetlu_agent.edge_config import EdgeConfig
from seetlu_agent.engine import SIM_CLOCK_TOPIC, Engine
from seetlu_agent.events import EdgeEvent
from seetlu_agent.outbox import Outbox
from seetlu_agent.setup_page import SecretsStore, create_app
from seetlu_agent.uploader import Uploader

log = logging.getLogger("seetlu_agent")

CONFIG_EVERY_S = 60.0
COMMANDS_EVERY_S = 30.0
REGISTER_EVERY_S = 30.0


class Agent:
    def __init__(self, env: AgentEnv, api: Api | None = None, frigate: httpx.Client | None = None,
                 wall: Callable[[], float] = time.time) -> None:  # fmt: skip
        self.env, self.wall = env, wall
        env.data_dir.mkdir(parents=True, exist_ok=True)
        self.api = api or Api(env.api_url, env.data_dir / "state.json")
        self.frigate = frigate or httpx.Client(base_url=env.frigate_url, timeout=30)
        self.outbox = Outbox(env.data_dir / "outbox.db")
        self.secrets = SecretsStore(env.data_dir / "secrets.json")
        self.config_cache = env.data_dir / "config.json"
        cfg = EdgeConfig()
        if self.config_cache.exists():
            cfg = EdgeConfig.model_validate_json(self.config_cache.read_text())
        self.cfg = cfg
        self.engine = Engine(cfg, namespace=env.kit_serial)
        self.uploader = Uploader(self.outbox, self.api.post_events)
        self.commands = CommandRunner(self.engine, self.outbox, self.frigate, compose_file=env.compose_file,
                                      host_dir=env.data_dir / "host", clock=self.now)  # fmt: skip
        self.inbox: queue.Queue[tuple[str, bytes]] = queue.Queue()
        self.sim_now: float | None = None
        self.last: dict[str, float] = {}
        self.last_heartbeat: float | None = None
        self.ota_requested: str | None = None
        self.host_dir = env.data_dir / "host"
        self.streams_pending = env.data_dir / "streams-pending.json"
        self.started_at = wall()
        self.last_cloud_ok: float | None = None

    # ---------- time ----------
    def now(self) -> float:
        if self.env.sim_clock:
            return self.sim_now if self.sim_now is not None else self.wall()
        return self.wall()

    def _due(self, name: str, every: float, now: float) -> bool:
        last = self.last.get(name)
        if last is not None and now - last < every:
            return False
        self.last[name] = now
        return True

    # ---------- events ----------
    def _store(self, events: list[EdgeEvent]) -> None:
        for ev in events:
            self.outbox.put(ev.to_api(), now=self.wall())

    def handle(self, topic: str, payload: bytes) -> None:
        if topic == SIM_CLOCK_TOPIC:
            if not self.env.sim_clock:
                return
            self.sim_now = float(payload.decode())
        if not self.env.sim_clock or self.sim_now is not None:
            self._store(self.engine.handle(topic, payload, self.now()))
        self._maybe_heartbeat()

    # ---------- cloud ----------
    @property
    def registered(self) -> bool:
        return self.api.token is not None

    def ensure_registered(self) -> bool:
        if self.registered:
            return True
        if not self._due("register", REGISTER_EVERY_S, self.wall()):
            return False
        try:
            kit_id = self.api.register(self.env.kit_serial, self.env.claim_token, __version__)
            log.info("registered as kit %s", kit_id)
        except (ApiError, httpx.HTTPError) as exc:
            log.warning("registration failed (%s); retrying in %.0f s", exc, REGISTER_EVERY_S)
            return False
        return True

    def poll_config(self) -> None:
        try:
            cfg = self.api.config()
        except ApiError as exc:
            log.warning("config poll failed: %s", exc)
            return
        except httpx.HTTPError as exc:
            log.warning("config poll failed: %s", exc)
            return
        self.last_cloud_ok = self.wall()
        if cfg is not None:
            self.apply_config(cfg)

    def apply_config(self, cfg: EdgeConfig) -> None:
        log.info("config version %s", cfg.config_version)
        self.cfg = cfg
        self.engine.configure(cfg)
        self.config_cache.write_text(cfg.model_dump_json())
        self.render_frigate()
        target = cfg.target_agent_version
        if target and target != __version__ and self.ota_requested != target:
            self.ota_requested = target  # AC-F10-3: update once per target version
            result = self.commands.execute({"id": f"ota-{target}", "type": "update_agent",
                                            "params": {"version": target}})  # fmt: skip
            log.info("self-update to %s: %s", target, result)

    def render_frigate(self) -> None:
        text = frigate_config.dump(frigate_config.render(self.cfg, self.secrets.load()))
        if frigate_config.write_if_changed(text, self.env.frigate_config_path):
            log.info("Frigate config changed; restarting Frigate")
            try:
                self.frigate.post("/api/restart", timeout=10)
            except httpx.HTTPError as exc:
                log.warning("Frigate restart request failed: %s", exc)

    def poll_commands(self) -> None:
        try:
            cmds = self.api.commands()
        except (ApiError, httpx.HTTPError) as exc:
            log.warning("command poll failed: %s", exc)
            return
        for cmd in cmds:
            done = self.commands.execute(cmd)
            if done is None:
                continue
            status, result = done
            try:
                self.api.command_result(str(cmd["id"]), status, result)
            except (ApiError, httpx.HTTPError) as exc:
                log.warning("command result %s not sent: %s", cmd["id"], exc)

    def _maybe_heartbeat(self) -> None:
        now = self.now()
        if self.env.sim_clock and self.sim_now is None:
            return
        if self.last_heartbeat is not None and now - self.last_heartbeat < heartbeat.EVERY_S:
            return
        self.last_heartbeat = now
        body = heartbeat.build(now, self.engine.stats, self.outbox.depth())
        self.outbox.put({"id": body["at"], **body}, kind="heartbeat", now=self.wall())

    def send_heartbeats(self) -> int:
        """Send queued heartbeats oldest first (late ones still fill their hours); stop at the first
        network/server error and keep the rest for the next round."""
        sent = 0
        while rows := self.outbox.due(float("inf"), 100, kind="heartbeat"):
            for hid, body in rows:
                body.pop("id", None)
                try:
                    self.api.heartbeat(body)
                except ApiError as exc:
                    if exc.status != 422:
                        return sent
                except httpx.HTTPError:
                    return sent
                self.outbox.delete([hid])
                sent += 1
        return sent

    def pending_heartbeats(self) -> int:
        return len(self.outbox.due(float("inf"), 10**6, kind="heartbeat"))

    # ---------- installation: stream reports (AC-F8-7), front panel (AC-F10-4) ----------
    def queue_stream_report(self, camera: str, report: dict[str, object]) -> None:
        """Kept on disk until the cloud has it: the installer may set cameras before the box registers."""
        pending = self._pending_streams()
        pending[camera] = report
        self.streams_pending.write_text(json.dumps(pending))

    def _pending_streams(self) -> dict[str, dict[str, object]]:
        try:
            data: dict[str, dict[str, object]] = json.loads(self.streams_pending.read_text())
        except (OSError, ValueError):
            return {}
        return data

    def send_stream_reports(self) -> None:
        pending = self._pending_streams()
        for camera, report in list(pending.items()):
            try:
                self.api.put_stream(camera, report)
            except (ApiError, httpx.HTTPError) as exc:
                log.warning("stream report for %s not sent: %s", camera, exc)
                return
            del pending[camera]
            self.streams_pending.write_text(json.dumps(pending))

    def update_panel(self) -> None:
        wall = self.wall()
        ok = self.last_cloud_ok
        fps = heartbeat.camera_fps(self.engine.stats)
        state = panel.led_state(
            starting=ok is None and wall - self.started_at < panel.STARTING_S,
            internet_ok=ok is not None and wall - ok < panel.INTERNET_STALE_S,
            cameras_ok=panel.cameras_streaming([c.name for c in self.cfg.cameras], fps),
        )
        panel.write_led(self.host_dir, state)

    def setup_open(self) -> bool:
        return panel.setup_open(self.host_dir, activated=self.cfg.activated, now=self.wall())

    def periodic(self) -> None:
        wall = self.wall()
        if not self.env.sim_clock:
            self._store(self.engine.tick(wall))
            self._maybe_heartbeat()
        self.update_panel()
        if not self.ensure_registered():
            return
        self.send_stream_reports()
        if self._due("config", CONFIG_EVERY_S, wall):
            self.poll_config()
        if self._due("commands", COMMANDS_EVERY_S, wall):
            self.poll_commands()
        self.uploader.run(wall)
        self.send_heartbeats()

    # ---------- run ----------
    def start_mqtt(self) -> mqtt.Client:
        client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=f"seetlu-agent-{self.env.kit_serial}")

        def on_connect(c: mqtt.Client, _u: object, _f: object, _rc: object, _p: object) -> None:
            c.subscribe([("frigate/#", 1), (f"{SIM_CLOCK_TOPIC}", 1)])

        def on_message(_c: mqtt.Client, _u: object, msg: mqtt.MQTTMessage) -> None:
            self.inbox.put((msg.topic, bytes(msg.payload)))

        client.on_connect = on_connect
        client.on_message = on_message
        client.reconnect_delay_set(1, 30)
        while True:
            try:
                client.connect(self.env.mqtt_host, self.env.mqtt_port)
                break
            except OSError as exc:
                log.warning("mqtt connect failed (%s), retrying in 5 s", exc)
                time.sleep(5)
        client.loop_start()
        return client

    def start_setup_page(self) -> None:
        app = create_app(
            pin=self.env.setup_pin,
            serial=self.env.kit_serial,
            secrets_store=self.secrets,
            get_config=lambda: self.cfg,
            registered=lambda: self.registered,
            on_change=self.render_frigate,
            frigate=self.frigate,
            on_stream=self.queue_stream_report,
            is_open=self.setup_open,
        )
        server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=self.env.setup_port,  # noqa: S104
                                               log_level="warning"))  # fmt: skip
        threading.Thread(target=server.run, daemon=True, name="setup-page").start()

    def run_forever(self) -> None:
        self.start_setup_page()
        self.start_mqtt()
        next_periodic = 0.0
        while True:
            try:
                topic, payload = self.inbox.get(timeout=1)
                self.handle(topic, payload)
            except queue.Empty:
                pass
            except Exception:
                log.exception("failed to process a message")
            if self.wall() >= next_periodic:
                next_periodic = self.wall() + 1
                try:
                    self.periodic()
                except Exception:
                    log.exception("periodic step failed")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    env = AgentEnv.from_env()
    if len(sys.argv) > 1 and sys.argv[1] == "replay":
        from seetlu_agent.replay import replay

        idle = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0
        result = replay(env, idle_exit_s=idle)
        print(json.dumps(result))
        sys.exit(0 if result["queued"] == 0 else 1)
    log.info(
        "seetlu-agent %s starting for kit %s (sim clock: %s)", __version__, env.kit_serial, env.sim_clock
    )
    Agent(env).run_forever()


if __name__ == "__main__":
    main()
