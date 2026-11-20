from seetlu_agent import __version__
from seetlu_agent.config import AgentEnv


def test_m0_agent_env_defaults(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("MQTT_PORT", raising=False)
    env = AgentEnv.from_env()
    assert env.mqtt_port == 1883
    assert __version__
