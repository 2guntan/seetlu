"""M4: every scenario publishes a deterministic Frigate-shaped stream with a matching expected.json."""

import itertools
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

import pytest

from fake_frigate import generator, scenario
from fake_frigate.generator import DOOR_IN, DOOR_OUT, Message
from fake_frigate.main import expected_path, render_expected

REQUIRED = {
    "normal-day", "busy-day", "staff-absent-afternoon", "power-cut-14-16", "after-hours-motion",
    "crowded-door", "re-entry-flicker",
}  # fmt: skip
ALL = sorted(scenario.names())
EVENT_FIELDS = {"id", "camera", "label", "score", "top_score", "start_time", "end_time", "current_zones",
                "entered_zones", "false_positive"}  # fmt: skip


def _gen(name: str) -> tuple[list[Message], generator.Truth, scenario.Scenario]:
    sc = scenario.load(name)
    msgs, truth = generator.generate(sc)
    return msgs, truth, sc


def _tracks(msgs: list[Message]) -> dict[str, list[dict[str, Any]]]:
    tracks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for m in msgs:
        if m.topic == "frigate/events":
            tracks[m.payload["after"]["id"]].append(m.payload)
    return tracks


def test_m4_all_required_scenarios_exist() -> None:
    assert set(ALL) >= REQUIRED
    for name in ALL:
        assert expected_path(name).exists(), f"run: fake-frigate expect {name} --write"


@pytest.mark.parametrize("name", ALL)
def test_m4_stream_is_deterministic_and_matches_golden(name: str) -> None:
    a, _, _ = _gen(name)
    b, _, _ = _gen(name)
    assert generator.digest(a) == generator.digest(b)
    golden = json.loads(expected_path(name).read_text())
    assert golden == json.loads(render_expected(name)), "regenerate with: fake-frigate expect --all --write"
    assert golden["messages"]["count"] == len(a)


def test_m4_date_override_is_deterministic() -> None:
    sc = scenario.load("normal-day").with_date(date(2026, 12, 4))
    first, t1 = generator.generate(sc)
    second, t2 = generator.generate(sc)
    assert generator.digest(first) == generator.digest(second) and t1 == t2
    day = datetime.fromtimestamp(first[len(first) // 2].ts, sc.tz).date()
    assert day == date(2026, 12, 4)


@pytest.mark.parametrize("name", ALL)
def test_m4_messages_are_ordered_and_frigate_shaped(name: str) -> None:
    msgs, _, _ = _gen(name)
    assert [m.ts for m in msgs] == sorted(m.ts for m in msgs)
    for track in _tracks(msgs).values():
        assert track[0]["type"] == "new" and track[-1]["type"] == "end"
        assert sum(p["type"] == "new" for p in track) == 1 and sum(p["type"] == "end" for p in track) == 1
        for p in track:
            assert p["after"].keys() >= EVENT_FIELDS and p["after"]["label"] == "person"
            assert p["after"]["sub_label"] is None  # no face/LPR sub labels, ever (CLAUDE.md rule 1)
            assert not any(k.startswith(("recognized_", "face")) for k in p["after"])
    for m in msgs:
        if m.topic.endswith("/person"):
            assert isinstance(m.payload, int) and m.payload >= 0


def _reference_door_count(msgs: list[Message]) -> tuple[int, int]:
    """Independent reading of docs/05 door rules.

    out→in = entry, in→out = exit, crossings within 10 s of the previous one count once.
    """
    entries = exits = 0
    for track in _tracks(msgs).values():
        if track[0]["after"]["camera"] != "door":
            continue
        last_zone: str | None = None
        last_cross: float | None = None
        for p in track:
            ts = p["after"]["frame_time"]
            for z in p["after"]["current_zones"]:
                if z in (DOOR_OUT, DOOR_IN) and z != last_zone:
                    if last_zone is not None and (last_cross is None or ts - last_cross > 10):
                        if z == DOOR_IN:
                            entries += 1
                        else:
                            exits += 1
                        last_cross = ts
                    last_zone = z
    return entries, exits


@pytest.mark.parametrize("name", ALL)
def test_m4_door_truth_matches_stream(name: str) -> None:
    msgs, truth, _ = _gen(name)
    assert _reference_door_count(msgs) == (truth.door_entries, truth.door_exits)
    assert sum(truth.hourly_entries.values()) == truth.door_entries


def test_m4_power_cut_has_no_messages_in_outage() -> None:
    msgs, truth, sc = _gen("power-cut-14-16")
    o0, o1 = sc.at(sc.outages[0][0]), sc.at(sc.outages[0][1])
    assert not [m for m in msgs if o0 <= m.ts < o1]
    clock = [m for m in msgs if m.topic == "seetlu-sim/clock"]
    assert len(clock) == 24 * 60 - 120
    assert truth.missing_hours == [14, 15]
    online = [m for m in msgs if m.topic == "frigate/available"]
    assert len(online) == 2 and online[1].ts == o1  # Frigate back online after the cut


def test_m4_crowded_door_groups_of_three() -> None:
    msgs, truth, _ = _gen("crowded-door")
    door = [t[0]["after"] for t in _tracks(msgs).values() if t[0]["after"]["camera"] == "door"]
    starts = sorted(a["start_time"] for a in door if a["current_zones"] == [DOOR_OUT])
    groups = sum(1 for i in range(len(starts) - 2) if starts[i + 2] - starts[i] <= 1.0)
    assert groups >= 25
    assert truth.customer_entries == 90


def test_m4_flicker_tracks_oscillate_within_ten_seconds() -> None:
    msgs, truth, _ = _gen("re-entry-flicker")
    flickers = [t for t in _tracks(msgs).values() if t[0]["after"]["camera"] == "door" and len(t) >= 7]
    assert len(flickers) == 12
    for t in flickers:
        assert t[-1]["after"]["end_time"] - t[0]["after"]["start_time"] <= 10
    assert truth.door_entries == 101 + 12


def test_m4_after_hours_only_for_after_hours_actors() -> None:
    for name in ALL:
        msgs, truth, sc = _gen(name)
        lo = sc.at(sc.opening[0]) - timedelta(minutes=30).total_seconds()
        hi = sc.at(sc.opening[1]) + timedelta(minutes=30).total_seconds()
        night = [t for t in _tracks(msgs).values() if not lo <= t[0]["after"]["start_time"] <= hi]
        assert len(night) == truth.after_hours_motion, name


def test_m4_staff_absent_afternoon_truth() -> None:
    _, truth, _ = _gen("staff-absent-afternoon")
    assert truth.unattended == 1 and truth.unattended_minutes == 240
    assert truth.wait >= 10  # customers wait at an empty counter, then leave unserved


def test_m4_counter_zone_counts_follow_tracks() -> None:
    msgs, truth, _ = _gen("normal-day")
    customer = [m.payload for m in msgs if m.topic == "frigate/counter_customer/person"]
    assert max(customer) == 1  # visits never overlap, so each one is a distinct service/wait
    rises = sum(1 for a, b in zip([0, *customer], customer, strict=False) if b > a)
    assert rises == truth.service + truth.wait - _waits_then_served("normal-day")


def _waits_then_served(name: str) -> int:
    """Customers who waited (staff stepped away) and were then served count once at the counter."""
    msgs, _, _ = _gen(name)
    staff = [m for m in msgs if m.topic == "frigate/counter_staff/person"]
    drops = sum(1 for a, b in itertools.pairwise(staff) if a.payload == 1 and b.payload == 0)
    # one drop per step-away, plus breaks and end of day
    sc = scenario.load(name)
    breaks = sum(len(a.breaks) for a in sc.actors if isinstance(a, scenario.Staff))
    return drops - breaks - 1
