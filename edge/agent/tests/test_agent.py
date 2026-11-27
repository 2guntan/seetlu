"""Agent runtime end to end, in process: simulator messages (with sim clock) → engine → outbox →
fake cloud; registration, ETag config polling, Frigate config rendering, commands, heartbeats."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml

from fake_frigate import generator, scenario
from fake_frigate.publisher import with_clock
from seetlu_agent.api import Api
from seetlu_agent.config import AgentEnv
from seetlu_agent.main import Agent
from tests.fakes import FakeCloud, fake_frigate
from tests.scenario_replay import config_for, replay, summarise


def env(tmp_path: Path, **kw: Any) -> AgentEnv:
    base = AgentEnv(
        api_url="http://api.test", kit_serial="TEST-KIT", claim_token="dev-claim-token",
        frigate_url="http://frigate.test", mqtt_host="localhost", mqtt_port=1883, data_dir=tmp_path / "agent",
        frigate_config_path=tmp_path / "frigate" / "config.yml", compose_file=str(tmp_path / "c.yml"), setup_port=0,
        sim_clock=True,
    )  # fmt: skip
    return replace(base, **kw)


def make_agent(tmp_path: Path, name: str = "normal-day", **kw: Any) -> tuple[Agent, FakeCloud]:
    sc = scenario.load(name)
    cfg = config_for(sc).model_dump()
    cloud = FakeCloud(config=cfg)
    e = env(tmp_path, **kw)
    agent = Agent(e, api=Api(e.api_url, e.data_dir / "state.json", cloud.client()), frigate=fake_frigate())
    return agent, cloud


def play(agent: Agent, name: str) -> None:
    sc = scenario.load(name)
    msgs, _ = generator.generate(sc)
    for i, m in enumerate(with_clock(msgs)):
        agent.handle(m.topic, m.encoded())
        if i % 2000 == 0:
            agent.periodic()
    agent.uploader.run(agent.wall(), force=True)
    agent.send_heartbeats()


@pytest.mark.parametrize("name", ["normal-day", "power-cut-14-16"])
def test_sim_day_through_the_agent_matches_the_engine_replay(tmp_path: Path, name: str) -> None:
    agent, cloud = make_agent(tmp_path, name)
    agent.periodic()  # register + config
    play(agent, name)
    _, want = replay(name)
    sc = scenario.load(name)
    assert set(cloud.events) == set(want)
    assert agent.outbox.depth() == 0
    for eid, ev in want.items():
        assert cloud.events[eid] == ev.to_api()  # final version of every event (open → closed upserts)
    assert summarise(sc, want)["door_entries"] > 0


def test_heartbeats_every_5_min_on_sim_time_and_none_during_power_cut_AC_F10_1(tmp_path: Path) -> None:
    agent, cloud = make_agent(tmp_path, "power-cut-14-16")
    agent.periodic()
    play(agent, "power-cut-14-16")
    hours = sorted({int(h["at"][11:13]) for h in cloud.heartbeats})
    # Dakar is UTC+0: no heartbeat from 14:00 to 16:00 → the report lists those hours as missing
    assert 14 not in hours and 15 not in hours and 13 in hours and 16 in hours
    assert len(cloud.heartbeats) == 288 - 24  # every 5 min of a 24 h day, minus the 2 h cut
    hb = cloud.heartbeats[-1]
    assert (
        hb["agent_version"] and hb["power_source"] == "mains" and hb["fps"] == {"door": 5.0, "counter": 5.0}
    )
    assert hb["frigate_version"] == "0.16.0-fake" and "queue_depth" in hb


def test_registration_waits_for_claim_then_polls_config_with_etag(tmp_path: Path) -> None:
    agent, cloud = make_agent(tmp_path)
    cloud.claimed = False
    agent.periodic()
    assert not agent.registered and "GET /v1/edge/config" not in cloud.calls
    cloud.claimed = True
    agent.last.pop("register")
    agent.periodic()
    assert agent.registered and agent.cfg.config_version == 1
    assert json.loads((tmp_path / "agent" / "state.json").read_text())["device_token"] == cloud.token
    assert (tmp_path / "agent" / "state.json").stat().st_mode & 0o777 == 0o600
    agent.last.pop("config")
    agent.poll_config()
    assert cloud.calls.count("GET /v1/edge/config") == 2  # second answered 304
    assert agent.engine.th.wait_min_s == 180


def test_frigate_config_is_rendered_from_cloud_config(tmp_path: Path) -> None:
    agent, _ = make_agent(tmp_path)
    agent.periodic()
    rendered = yaml.safe_load((tmp_path / "frigate" / "config.yml").read_text())
    assert set(rendered["cameras"]) == {"door", "counter"}
    assert rendered["face_recognition"] == {"enabled": False}
    mtime = (tmp_path / "frigate" / "config.yml").stat().st_mtime_ns
    agent.render_frigate()
    assert (tmp_path / "frigate" / "config.yml").stat().st_mtime_ns == mtime  # unchanged → no restart


def test_commands_are_executed_once_and_reported(tmp_path: Path) -> None:
    agent, cloud = make_agent(tmp_path)
    cloud.commands.append({"id": "cc1", "type": "count_check_start", "params": {}, "upload_url": None})
    agent.periodic()
    assert cloud.results["cc1"]["status"] == "done"
    agent.last.pop("commands")
    agent.poll_commands()
    assert list(cloud.results) == ["cc1"]


def test_ota_target_version_triggers_one_update_AC_F10_3(tmp_path: Path) -> None:
    agent, cloud = make_agent(tmp_path)
    calls: list[list[str]] = []
    agent.commands.run = calls.append
    cloud.config["target_agent_version"] = "9.9.9"
    agent.periodic()
    assert [c[-1] for c in calls] == ["seetlu-agent", "seetlu-agent"]
    agent.apply_config(agent.cfg)
    assert len(calls) == 2  # not again for the same target


def test_events_survive_cloud_outage_and_restart(tmp_path: Path) -> None:
    agent, cloud = make_agent(tmp_path, "after-hours-motion")
    agent.periodic()
    cloud.fail_events = 10**6
    play(agent, "after-hours-motion")
    pending = agent.outbox.depth()
    assert pending > 0 and not cloud.events
    agent2, _ = make_agent(tmp_path, "after-hours-motion")
    agent2.api = Api("http://api.test", tmp_path / "agent" / "state.json", cloud.client())
    agent2.uploader.post = agent2.api.post_events
    cloud.fail_events = 0
    agent2.uploader.run(agent2.wall(), force=True)
    assert len(cloud.events) == pending and agent2.outbox.depth() == 0


def test_rotated_token_triggers_re_registration(tmp_path: Path) -> None:
    agent, cloud = make_agent(tmp_path, "after-hours-motion")
    agent.periodic()
    cloud.token = "kit-1.rotated"  # another process registered the same kit
    play(agent, "after-hours-motion")
    assert not agent.registered  # 401 → token forgotten
    agent.last.pop("register")
    agent.periodic()
    agent.uploader.blocked_until = 0
    agent.uploader.run(agent.wall(), force=True)
    agent.send_heartbeats()
    assert agent.registered and agent.outbox.depth() == 0 and agent.pending_heartbeats() == 0


def test_ac_f8_7_stream_reports_wait_for_registration_then_reach_the_cloud(tmp_path: Path) -> None:
    agent, cloud = make_agent(tmp_path)
    cloud.claimed = False
    agent.queue_stream_report("door", {"source": "hikvision 192.168.1.64 ch1", "reachable": True, "codec": "h264",
                                       "width": 704, "height": 576, "fps": 6.0})  # fmt: skip
    agent.periodic()
    assert cloud.streams == {}
    cloud.claimed = True
    agent.last.clear()
    agent.periodic()
    assert cloud.streams["door"]["source"] == "hikvision 192.168.1.64 ch1"
    assert json.loads((tmp_path / "agent" / "streams-pending.json").read_text()) == {}


def test_ac_f10_4_agent_writes_led_state_for_the_host_daemon(tmp_path: Path) -> None:
    agent, _cloud = make_agent(tmp_path)
    agent.update_panel()
    assert (tmp_path / "agent" / "host" / "led").read_text().strip() == "green-blink"  # starting
    agent.started_at -= 1000
    agent.update_panel()
    assert (tmp_path / "agent" / "host" / "led").read_text().strip() == "red"  # no frames yet
