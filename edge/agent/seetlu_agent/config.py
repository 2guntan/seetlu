"""Agent settings from environment variables."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentEnv:
    api_url: str
    kit_serial: str
    frigate_url: str
    mqtt_host: str
    mqtt_port: int

    @classmethod
    def from_env(cls) -> "AgentEnv":
        return cls(
            api_url=os.environ.get("SEETLU_API_URL", "http://localhost:8000"),
            kit_serial=os.environ.get("KIT_SERIAL", "DEV-KIT-0001"),
            frigate_url=os.environ.get("FRIGATE_URL", "http://localhost:5000"),
            mqtt_host=os.environ.get("MQTT_HOST", "localhost"),
            mqtt_port=int(os.environ.get("MQTT_PORT", "1883")),
        )
