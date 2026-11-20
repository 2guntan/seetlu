"""M3 contract tests for every edge endpoint (docs/04 'edge', docs/05)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from seetlu.core.ids import uuid7
from seetlu.core.security import hash_token
from seetlu.db import models as m
from seetlu.domain.commands import enqueue
from tests.conftest import World, bearer
from tests.contract import assert_matches

CLAIM = "claim-secret"


def _kit(db: Session, world: World, *, serial: str = "EDGE-1", attached: bool = True) -> m.Kit:
    kit = m.Kit(
        serial=serial,
        claim_token_hash=hash_token(CLAIM),
        shop_id=world.shop_a1.id if attached else None,
        installer_id=world.installer.id,
        status=m.KitStatus.installing if attached else m.KitStatus.in_stock,
    )
    db.add(kit)
    db.flush()
    door = m.Camera(
        kit_id=kit.id, role=m.CameraRole.door, name="door", rtsp_main_path="/1", rtsp_sub_path="/2"
    )
    counter = m.Camera(
        kit_id=kit.id, role=m.CameraRole.counter, name="counter", rtsp_main_path="/1", rtsp_sub_path="/2"
    )
    db.add_all([door, counter])
    db.flush()
    db.add_all(
        [
            m.Zone(camera_id=door.id, type=m.ZoneType.door_line, geometry=[[0.3, 0.5], [0.7, 0.5]],
                   inward_side="right"),
            m.Zone(camera_id=counter.id, type=m.ZoneType.customer_side,
                   geometry=[[0.1, 0.5], [0.9, 0.5], [0.9, 0.9], [0.1, 0.9]]),
            m.Zone(camera_id=counter.id, type=m.ZoneType.staff_side,
                   geometry=[[0.1, 0.1], [0.9, 0.1], [0.9, 0.4], [0.1, 0.4]]),
        ]
    )  # fmt: skip
    db.commit()
    return kit


def _register(client: TestClient, serial: str = "EDGE-1") -> dict[str, str]:
    r = client.post(
        "/v1/edge/register", json={"serial": serial, "claim_token": CLAIM, "agent_version": "0.1.0"}
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['device_token']}"}


@pytest.fixture
def kit(db: Session, world: World) -> m.Kit:
    return _kit(db, world)


@pytest.fixture
def dev(client: TestClient, kit: m.Kit) -> dict[str, str]:
    return _register(client)


def _event(**kw: Any) -> dict[str, Any]:
    t0 = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    return {
        "id": str(uuid7()), "type": "entry", "camera": "door", "started_at": t0.isoformat(),
        "confidence": 0.91, "frigate_event_ids": ["1732096800.123-abc"],
    } | kw  # fmt: skip


# ---------- register ----------
def test_m3_register_issues_device_token(client: TestClient, db: Session, kit: m.Kit) -> None:
    r = client.post("/v1/edge/register", json={"serial": "EDGE-1", "claim_token": CLAIM})
    assert r.status_code == 200
    assert r.json()["kit_id"] == str(kit.id)
    token = r.json()["device_token"]
    assert token.startswith(f"{kit.id}.") and len(token.split(".", 1)[1]) >= 43  # 32 random bytes
    db.expire_all()
    stored = db.get(m.Kit, kit.id)
    assert stored is not None and stored.device_token_hash and token not in stored.device_token_hash


def test_m3_register_rejects_wrong_claim_and_unclaimed(client: TestClient, db: Session, world: World) -> None:
    _kit(db, world, serial="IN-STOCK", attached=False)
    assert (
        client.post("/v1/edge/register", json={"serial": "IN-STOCK", "claim_token": "nope"}).status_code
        == 401
    )
    r = client.post("/v1/edge/register", json={"serial": "IN-STOCK", "claim_token": CLAIM})
    assert r.status_code == 403 and r.json()["type"].endswith("/not-claimed")
    assert client.post("/v1/edge/register", json={"serial": "NOPE", "claim_token": CLAIM}).status_code == 401


def test_m3_reregistration_rotates_token(client: TestClient, kit: m.Kit) -> None:
    old = _register(client)
    new = _register(client)
    assert client.get("/v1/edge/config", headers=old).status_code == 401
    assert client.get("/v1/edge/config", headers=new).status_code == 200


def test_m3_device_auth_required(client: TestClient, kit: m.Kit, db: Session, world: World) -> None:
    for headers in ({}, {"Authorization": "Bearer garbage"}, {"Authorization": f"Bearer {kit.id}.wrong"}):
        r = client.get("/v1/edge/config", headers=headers)
        assert r.status_code == 401 and r.headers["content-type"].startswith("application/problem+json")
    # a user JWT is not a device token
    assert client.get("/v1/edge/config", headers=bearer(db, world.owner_a)).status_code == 401


# ---------- config ----------
def test_m3_config_matches_contract_and_uses_etag(
    client: TestClient, dev: dict[str, str], kit: m.Kit
) -> None:
    r = client.get("/v1/edge/config", headers=dev)
    assert r.status_code == 200
    assert_matches("EdgeConfig", r.json())
    etag = r.headers["etag"]
    assert etag == f'"{kit.config_version}"'
    cams = {c["name"]: c for c in r.json()["cameras"]}
    assert {z["type"] for z in cams["counter"]["zones"]} == {"customer_side", "staff_side"}
    assert cams["door"]["zones"][0]["inward_side"] == "right"
    assert "rtsp://" not in r.text and "@" not in r.text  # no credentials in cloud config (docs/05)
    r304 = client.get("/v1/edge/config", headers=dev | {"If-None-Match": etag})
    assert r304.status_code == 304 and r304.headers["etag"] == etag


def test_m3_config_etag_changes_when_owner_edits_thresholds(
    client: TestClient, db: Session, world: World, dev: dict[str, str]
) -> None:
    etag = client.get("/v1/edge/config", headers=dev).headers["etag"]
    assert client.patch(f"/v1/shops/{world.shop_a1.id}", headers=bearer(db, world.owner_a),
                        json={"service_min_s": 25}).status_code == 200  # fmt: skip
    r = client.get("/v1/edge/config", headers=dev | {"If-None-Match": etag})
    assert r.status_code == 200 and r.headers["etag"] != etag
    assert r.json()["shop"]["service_min_s"] == 25


# ---------- events ----------
def test_m3_events_idempotent_upsert(client: TestClient, db: Session, dev: dict[str, str]) -> None:
    batch = [_event(), _event(type="exit")]
    for e in batch:
        assert_matches("EdgeEvent", e)
    r = client.post("/v1/edge/events", headers=dev, json={"events": batch})
    assert r.status_code == 200 and r.json() == {"accepted": 2, "duplicates": 0}
    r = client.post("/v1/edge/events", headers=dev, json={"events": batch})
    assert r.json() == {"accepted": 0, "duplicates": 2}
    assert db.scalar(select(func.count()).select_from(m.Event)) == 2


def test_m3_ac_f1_3_is_staff_correction_upserts_same_event(
    client: TestClient, db: Session, dev: dict[str, str]
) -> None:
    entry = _event()
    client.post("/v1/edge/events", headers=dev, json={"events": [entry]})
    r = client.post("/v1/edge/events", headers=dev, json={"events": [entry | {"is_staff": True}]})
    assert r.json() == {"accepted": 0, "duplicates": 1}
    row = db.scalars(select(m.Event)).one()
    assert row.is_staff is True and str(row.id) == entry["id"]


def test_m3_ac_f2_4_service_event_stores_times_confidence_and_frigate_ids(
    client: TestClient, db: Session, dev: dict[str, str], kit: m.Kit
) -> None:
    t0 = datetime(2026, 11, 20, 18, 0, tzinfo=UTC)
    ev = _event(type="service", camera="counter", started_at=t0.isoformat(),
                ended_at=(t0 + timedelta(seconds=74)).isoformat(), confidence=0.82,
                frigate_event_ids=["a", "b"])  # fmt: skip
    client.post("/v1/edge/events", headers=dev, json={"events": [ev]})
    row = db.scalars(select(m.Event)).one()
    assert row.type is m.EventType.service and row.duration_s == 74
    assert row.started_at == t0 and row.confidence == pytest.approx(0.82)
    assert row.frigate_event_ids == ["a", "b"]
    assert row.kit_id == kit.id and row.shop_id == kit.shop_id and row.camera_id is not None


def test_m3_events_validation(client: TestClient, dev: dict[str, str]) -> None:
    too_many = {"events": [_event() for _ in range(501)]}
    assert client.post("/v1/edge/events", headers=dev, json=too_many).status_code == 422
    t0 = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    backwards = _event(ended_at=(t0 - timedelta(seconds=1)).isoformat())
    assert client.post("/v1/edge/events", headers=dev, json={"events": [backwards]}).status_code == 422
    naive = _event(started_at="2026-11-20T10:00:00")
    assert client.post("/v1/edge/events", headers=dev, json={"events": [naive]}).status_code == 422
    offline = _event(type="kit_offline")  # cloud-generated only
    assert client.post("/v1/edge/events", headers=dev, json={"events": [offline]}).status_code == 422
    ok = {"events": [_event() for _ in range(500)]}
    assert client.post("/v1/edge/events", headers=dev, json=ok).json()["accepted"] == 500


def test_m3_unknown_camera_is_kept(client: TestClient, db: Session, dev: dict[str, str]) -> None:
    client.post("/v1/edge/events", headers=dev, json={"events": [_event(camera="shelf-2")]})
    row = db.scalars(select(m.Event)).one()
    assert row.camera_id is None and row.meta["camera"] == "shelf-2"


# ---------- heartbeat ----------
def test_m3_ac_f10_1_heartbeat_stored(
    client: TestClient, db: Session, dev: dict[str, str], kit: m.Kit
) -> None:
    hb = {
        "at": "2026-11-20T10:05:00+00:00", "power_source": "battery", "battery_pct": 81, "storage_pct": 37,
        "cpu_temp_c": 58.5, "fps": {"door": 5.0, "counter": 4.9}, "network": "4g", "agent_version": "0.2.0",
        "frigate_version": "0.16.0", "queue_depth": 12,
    }  # fmt: skip
    assert_matches("Heartbeat", hb)
    assert client.post("/v1/edge/heartbeat", headers=dev, json=hb).status_code == 204
    assert (
        client.post("/v1/edge/heartbeat", headers=dev, json=hb).status_code == 204
    )  # same timestamp: no error
    row = db.scalars(select(m.Heartbeat)).one()
    assert row.battery_pct == 81 and row.fps == {"door": 5.0, "counter": 4.9} and row.network == "4g"
    db.expire_all()
    k = db.get(m.Kit, kit.id)
    assert k is not None and k.agent_version == "0.2.0" and k.frigate_version == "0.16.0"
    assert k.health is m.KitHealth.ok and k.last_seen_at is not None


def test_m3_heartbeat_validation(client: TestClient, dev: dict[str, str]) -> None:
    assert (
        client.post("/v1/edge/heartbeat", headers=dev, json={"at": "2026-11-20T10:05:00Z"}).status_code == 422
    )
    bad = {"at": "2026-11-20T10:05:00Z", "agent_version": "1", "network": "satellite"}
    assert client.post("/v1/edge/heartbeat", headers=dev, json=bad).status_code == 422


# ---------- commands ----------
def test_m3_commands_queue_with_presigned_upload(
    client: TestClient, db: Session, dev: dict[str, str], kit: m.Kit
) -> None:
    clip = enqueue(db, kit, m.CommandType.clip, {"camera": "counter", "start": "2026-11-20T18:00:00Z",
                                                  "end": "2026-11-20T18:00:20Z"})  # fmt: skip
    reboot = enqueue(db, kit, m.CommandType.reboot)
    db.commit()
    r = client.get("/v1/edge/commands", headers=dev)
    assert r.status_code == 200
    cmds = {c["id"]: c for c in r.json()}
    for c in cmds.values():
        assert_matches("EdgeCommand", c)
    url = urlparse(cmds[str(clip.id)]["upload_url"])
    assert url.path.endswith(f"/shops/{kit.shop_id}/clips/{clip.id}.mp4")
    assert "X-Amz-Signature" in url.query and "X-Amz-Expires=600" in url.query  # PUT 10 min
    assert cmds[str(reboot.id)]["upload_url"] is None
    db.expire_all()
    assert db.get(m.EdgeCommand, clip.id).status is m.CommandStatus.sent  # type: ignore[union-attr]
    assert len(client.get("/v1/edge/commands", headers=dev).json()) == 2  # unfinished commands are re-sent


def test_m3_expired_commands_are_not_sent(
    client: TestClient, db: Session, dev: dict[str, str], kit: m.Kit
) -> None:
    old = enqueue(db, kit, m.CommandType.snapshot, now=datetime.now(UTC) - timedelta(minutes=5))
    db.commit()
    assert client.get("/v1/edge/commands", headers=dev).json() == []
    db.expire_all()
    assert db.get(m.EdgeCommand, old.id).status is m.CommandStatus.expired  # type: ignore[union-attr]


def test_m3_commands_are_per_kit(
    client: TestClient, db: Session, world: World, dev: dict[str, str], kit: m.Kit
) -> None:
    other = _kit(db, world, serial="EDGE-2")
    other_dev = _register(client, "EDGE-2")
    cmd = enqueue(db, kit, m.CommandType.reboot)
    db.commit()
    assert client.get("/v1/edge/commands", headers=other_dev).json() == []
    r = client.post(f"/v1/edge/commands/{cmd.id}/result", headers=other_dev, json={"status": "done"})
    assert r.status_code == 404
    assert other.id != kit.id


def test_m3_clip_result_creates_clip_row(
    client: TestClient, db: Session, dev: dict[str, str], kit: m.Kit
) -> None:
    event_id = uuid7()
    cmd = enqueue(db, kit, m.CommandType.clip, {"camera": "counter", "event_id": str(event_id)})
    db.commit()
    body = {
        "status": "done",
        "result": {"object_key": "evil/elsewhere.mp4", "duration_s": 18, "size_bytes": 912345},
    }
    assert client.post(f"/v1/edge/commands/{cmd.id}/result", headers=dev, json=body).status_code == 204
    assert (
        client.post(f"/v1/edge/commands/{cmd.id}/result", headers=dev, json=body).status_code == 204
    )  # idempotent
    clip = db.scalars(select(m.Clip)).one()
    assert clip.object_key == f"shops/{kit.shop_id}/clips/{cmd.id}.mp4"
    assert clip.event_id == event_id and clip.duration_s == 18 and clip.kind == "clip"
    assert clip.expires_at is not None
    assert timedelta(days=6, hours=23) < clip.expires_at - datetime.now(UTC) <= timedelta(days=7)  # AC-F5-3


def test_m3_ac_f5_4_unavailable_clip_result(
    client: TestClient, db: Session, dev: dict[str, str], kit: m.Kit
) -> None:
    cmd = enqueue(db, kit, m.CommandType.clip, {"camera": "counter"})
    db.commit()
    r = client.post(f"/v1/edge/commands/{cmd.id}/result", headers=dev, json={"status": "unavailable"})
    assert r.status_code == 204
    db.expire_all()
    assert db.get(m.EdgeCommand, cmd.id).status is m.CommandStatus.unavailable  # type: ignore[union-attr]
    assert db.scalars(select(m.Clip)).first() is None


def test_m3_count_check_result_payload_kept(
    client: TestClient, db: Session, dev: dict[str, str], kit: m.Kit
) -> None:
    cmd = enqueue(db, kit, m.CommandType.count_check_stop)
    db.commit()
    client.post(
        f"/v1/edge/commands/{cmd.id}/result",
        headers=dev,
        json={"status": "done", "result": {"agent_count": 23}},
    )
    db.expire_all()
    row = db.get(m.EdgeCommand, cmd.id)
    assert row is not None and row.result == {"agent_count": 23} and row.completed_at is not None
    assert row.status is m.CommandStatus.done


def test_m3_unknown_command_404(client: TestClient, dev: dict[str, str]) -> None:
    r = client.post(f"/v1/edge/commands/{uuid.uuid4()}/result", headers=dev, json={"status": "done"})
    assert r.status_code == 404
