"""Agent settings from environment variables (docs/09: secrets only via env / files on the box)."""

import os
from dataclasses import dataclass
from pathlib import Path


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class AgentEnv:
    api_url: str
    kit_serial: str
    claim_token: str
    frigate_url: str
    mqtt_host: str
    mqtt_port: int
    data_dir: Path
    frigate_config_path: Path
    compose_file: str
    setup_port: int
    sim_clock: bool

    @classmethod
    def from_env(cls) -> "AgentEnv":
        data = Path(os.environ.get("AGENT_DATA_DIR", "/data/agent"))
        return cls(
            api_url=os.environ.get("SEETLU_API_URL", "http://localhost:8000"),
            kit_serial=os.environ.get("KIT_SERIAL", "DEV-KIT-0001"),
            claim_token=os.environ.get("KIT_CLAIM_TOKEN", ""),
            frigate_url=os.environ.get("FRIGATE_URL", "http://127.0.0.1:5000"),
            mqtt_host=os.environ.get("MQTT_HOST", "127.0.0.1"),
            mqtt_port=int(os.environ.get("MQTT_PORT", "1883")),
            data_dir=data,
            frigate_config_path=Path(
                os.environ.get("FRIGATE_CONFIG_PATH", "/data/frigate/config/config.yml")
            ),
            compose_file=os.environ.get("EDGE_COMPOSE_FILE", "/data/agent/docker-compose.edge.yml"),
            setup_port=int(os.environ.get("SETUP_PORT", "8080")),
            sim_clock=_flag("SIM_CLOCK"),
        )

    @property
    def setup_pin(self) -> str:
        """LAN setup page PIN = last 6 characters of the claim token (docs/05)."""
        return self.claim_token[-6:]
