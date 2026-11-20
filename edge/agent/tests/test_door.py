"""Door crossings (AC-F1-1, AC-F1-2) and staff tagging (AC-F1-3)."""

from collections.abc import Sequence

from seetlu_agent.door import Track


def track(steps: Sequence[tuple[float, list[str]]], score: float = 0.8, label: str = "person") -> Track:
    t = Track(id="t1", camera="door", label=label, first_ts=steps[0][0], last_ts=steps[0][0])
    for ts, zones in steps:
        t.observe(ts, zones, score)
    return t


def kinds(t: Track) -> list[str]:
    return [c.kind for c in t.crossings]


def test_out_then_in_is_an_entry_and_in_then_out_an_exit_AC_F1_1() -> None:
    assert kinds(track([(0, ["door_out"]), (1, ["door_in"]), (2, [])])) == ["entry"]
    assert kinds(track([(0, ["door_in"]), (1, ["door_out"]), (2, [])])) == ["exit"]
    entry = track([(0, ["door_out"]), (1, ["door_out"]), (1.5, ["door_in"])])
    assert entry.crossings[0].ts == 1.5  # time door_in first appeared


def test_no_crossing_without_both_bands_AC_F1_1() -> None:
    assert kinds(track([(0, ["door_in"]), (5, ["door_in"]), (6, [])])) == []
    assert kinds(track([(0, []), (5, ["shelf_main"])])) == []


def test_recrossing_within_10s_counts_once_AC_F1_2() -> None:
    steps = [(0, ["door_out"]), (1, ["door_in"]), (3, ["door_out"]), (5, ["door_in"]), (9, ["door_out"]),
             (11, ["door_in"])]  # fmt: skip
    assert kinds(track(steps)) == ["entry"]


def test_exit_after_debounce_and_one_of_each_per_track_AC_F1_2() -> None:
    steps = [(0, ["door_out"]), (1, ["door_in"]), (30, ["door_out"]), (60, ["door_in"]), (90, ["door_out"])]
    assert kinds(track(steps)) == ["entry", "exit"]


def test_low_score_and_non_person_tracks_are_ignored() -> None:
    assert not track([(0, ["door_out"]), (1, ["door_in"])], score=0.55).counted
    assert track([(0, ["door_out"]), (1, ["door_in"])], score=0.6).counted
    assert not track([(0, ["door_out"]), (1, ["door_in"])], label="dog").counted


def test_staff_tag_after_600s_in_staff_zone_AC_F1_3() -> None:
    steps: list[tuple[float, list[str]]] = [(0, ["door_out"]), (1, ["door_in", "counter_staff"])]
    steps += [(1 + 60 * i, ["counter_staff"]) for i in range(1, 10)]
    almost = track(steps)
    assert almost.staff_s == 540 and not almost.is_staff
    tagged = track([*steps, (601, ["counter_staff"]), (700, [])])
    assert tagged.staff_s == 699 and tagged.is_staff  # in the zone until the 700 s update
