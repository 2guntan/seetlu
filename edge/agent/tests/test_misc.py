"""Heartbeat body (AC-F10-1), opening hours, deterministic event ids, API client."""

from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from seetlu_agent import heartbeat
from seetlu_agent.api import Api
from seetlu_agent.edge_config import DAYS, OpeningHours
from seetlu_agent.ids import event_uuid
from tests.fakes import FakeCloud


def test_heartbeat_fields_AC_F10_1(tmp_path: Path) -> None:
    stats = {"cameras": {"door": {"camera_fps": 5.0}, "counter": {"camera_fps": 4.0}},
             "service": {"version": "0.16.1"}}  # fmt: skip
    probes = {"cpu_temp_c": lambda: 51.2, "storage_pct": lambda: 40, "network": lambda: "4g"}
    hb = heartbeat.build(1_800_000_000.0, stats, 7, probes)
    assert hb == {
        "at": "2027-01-15T08:00:00.000Z", "agent_version": hb["agent_version"], "power_source": "mains",
        "storage_pct": 40, "cpu_temp_c": 51.2, "fps": {"door": 5.0, "counter": 4.0}, "network": "4g",
        "frigate_version": "0.16.1", "queue_depth": 7,
    }  # fmt: skip


def test_network_detection(tmp_path: Path) -> None:
    for name, state in (("lo", "unknown"), ("eth0", "down"), ("wlan0", "up")):
        (tmp_path / name).mkdir()
        (tmp_path / name / "operstate").write_text(state)
    assert heartbeat.network(tmp_path) == "wifi"
    (tmp_path / "wwan0").mkdir()
    (tmp_path / "wwan0" / "operstate").write_text("up")
    assert heartbeat.network(tmp_path) == "4g"
    assert heartbeat.cpu_temp_c(tmp_path / "missing") is None


def test_opening_hours_in_shop_timezone() -> None:
    tz = ZoneInfo("Africa/Abidjan")
    hours = OpeningHours({d: [["08:00", "13:00"], ["15:00", "21:00"]] for d in DAYS} | {"sun": []},
                         "Africa/Abidjan")  # fmt: skip
    fri = date(2026, 11, 20)

    def at(d: date, hh: int, mm: int = 0) -> float:
        return datetime.combine(d, time(hh, mm), tzinfo=tz).timestamp()

    assert hours.is_open(at(fri, 9)) and not hours.is_open(at(fri, 14))
    assert hours.is_open(at(fri, 21, 20), margin_s=1800) and not hours.is_open(at(fri, 21, 40), margin_s=1800)
    assert not hours.is_open(at(date(2026, 11, 22), 10))  # closed on Sunday
    assert hours.intervals(at(fri, 12), at(fri, 16)) == [
        (at(fri, 8), at(fri, 13)),
        (at(fri, 15), at(fri, 21)),
    ]


def test_event_ids_are_uuid7_and_deterministic() -> None:
    a = event_uuid(1_800_000_000.5, "K|door|t1|entry")
    assert a.version == 7 and a == event_uuid(1_800_000_000.5, "K|door|t1|entry")
    assert a != event_uuid(1_800_000_000.5, "K2|door|t1|entry")
    assert a.int >> 80 == 1_800_000_000_500
    assert event_uuid(1.0, "x") < event_uuid(2.0, "x")


def test_api_uses_device_token_and_etag(tmp_path: Path) -> None:
    cloud = FakeCloud(config={"config_version": 4, "shop": {"timezone": "Africa/Dakar"}})
    api = Api("http://api.test", tmp_path / "state.json", cloud.client())
    assert api.register("TEST-KIT", "dev-claim-token", "0.1.0") == "kit-1"
    cfg = api.config()
    assert cfg is not None and cfg.config_version == 4 and api.etag == '"4"'
    assert api.config() is None
    cloud.config["config_version"] = 5
    assert (api.config() or cfg).config_version == 5
    again = Api("http://api.test", tmp_path / "state.json", cloud.client())
    assert again.token == cloud.token  # persisted across restarts
