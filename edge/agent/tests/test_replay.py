"""`seetlu-agent replay` (make sim-day): a whole day uploaded, heartbeats included."""

from pathlib import Path

from tests.test_agent import make_agent, play


def test_all_heartbeats_are_flushed(tmp_path: Path) -> None:
    agent, cloud = make_agent(tmp_path, "normal-day")
    agent.periodic()
    cloud.calls.clear()
    play(agent, "normal-day")
    assert len(cloud.heartbeats) == 288 and agent.pending_heartbeats() == 0
    ats = [h["at"] for h in cloud.heartbeats]
    assert ats == sorted(ats)
