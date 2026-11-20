"""M5 acceptance: every fake-frigate scenario replayed through the agent gives its expected.json truth."""

import json

import pytest

from fake_frigate import scenario
from fake_frigate.main import expected_path
from tests.scenario_replay import replay, summarise

KEYS = ("door_entries", "door_exits", "hourly_entries", "service", "wait", "unattended",
        "unattended_minutes", "after_hours_motion")  # fmt: skip


@pytest.mark.parametrize("name", scenario.names())
def test_scenario_matches_expected_AC_F1_1_AC_F2_1_AC_F2_2_AC_F2_3(name: str) -> None:
    sc, events = replay(name)
    truth = json.loads(expected_path(name).read_text())["truth"]
    got = summarise(sc, events)
    assert got == {k: truth[k] for k in KEYS}


def test_events_are_well_formed_AC_F2_4() -> None:
    _, events = replay("normal-day")
    for ev in events.values():
        body = ev.to_api()
        assert body["id"] == ev.id and 0 <= body["confidence"] <= 1
        if ev.type in ("service", "wait", "unattended"):
            assert body["ended_at"] is not None and ev.duration_s > 0
            assert ev.frigate_event_ids, "counter events carry the Frigate ids needed to fetch a clip"
        if ev.type in ("entry", "exit", "after_hours_motion"):
            assert len(ev.frigate_event_ids) == 1


def test_replay_is_deterministic() -> None:
    _, a = replay("re-entry-flicker")
    _, b = replay("re-entry-flicker")
    assert sorted(a) == sorted(b)
