"""M8 support console: kits by health + 7 days of heartbeats (AC-F10-2), OTA target (AC-F10-3), audited actions."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from seetlu.api.support import health_of
from seetlu.db import models as m
from tests.conftest import World, bearer


def _hb(db: Session, kit: m.Kit, at: datetime, **kw: object) -> None:
    db.add(m.Heartbeat(kit_id=kit.id, at=at, **kw))
    db.commit()


def test_ac_f10_2_health_rules(world: World) -> None:
    now = datetime.now(UTC)
    kit = world.kit_a1
    assert health_of(kit, None, None, now) is m.KitHealth.offline
    assert health_of(kit, now - timedelta(minutes=31), 0, now) is m.KitHealth.offline
    assert health_of(kit, now - timedelta(minutes=5), 500, now) is m.KitHealth.degraded
    assert health_of(kit, now - timedelta(minutes=5), 3, now) is m.KitHealth.ok


def test_ac_f10_2_support_lists_kits_by_health(client: TestClient, db: Session, world: World) -> None:
    now = datetime.now(UTC)
    _hb(db, world.kit_a1, now - timedelta(minutes=2), queue_depth=0, fps={"door": 5, "counter": 1.5})
    other = m.Kit(serial="ZZ-OFF", claim_token_hash="x", shop_id=world.shop_b.id)
    db.add(other)
    db.commit()
    h = bearer(db, world.support)
    r = client.get("/v1/support/kits", headers=h)
    assert r.status_code == 200, r.text
    rows = {k["serial"]: k for k in r.json()}
    assert rows[world.kit_a1.serial]["health"] == "degraded"  # a camera below 2 fps
    assert rows[world.kit_a1.serial]["min_fps"] == 1.5
    assert rows["ZZ-OFF"]["health"] == "offline"
    r = client.get("/v1/support/kits", headers=h, params={"health": "offline"})
    assert [k["serial"] for k in r.json()] == ["ZZ-OFF"]
    for who in (world.owner_a, world.installer, world.manager):
        assert client.get("/v1/support/kits", headers=bearer(db, who)).status_code == 403


def test_ac_f10_2_kit_detail_has_7_days_of_heartbeats(client: TestClient, db: Session, world: World) -> None:
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    for ago in (timedelta(minutes=50), timedelta(minutes=40), timedelta(hours=30), timedelta(days=8)):
        _hb(db, world.kit_a1, now - ago, queue_depth=1)
    _hb(db, world.kit_a1, now - timedelta(minutes=45), queue_depth=2, cpu_temp_c=61.5)
    r = client.get(f"/v1/support/kits/{world.kit_a1.id}", headers=bearer(db, world.support))
    assert r.status_code == 200, r.text
    points = r.json()["heartbeats_7d"]
    assert len(points) == 2  # the 8-day-old one is outside the window
    assert sum(p["count"] for p in points) == 4
    assert max(p["max_cpu_temp_c"] or 0 for p in points) == 61.5
    assert r.json()["config"]["config_version"] == world.kit_a1.config_version


def test_ac_f10_3_target_version_reaches_agent_config(client: TestClient, db: Session, world: World) -> None:
    before = world.kit_a1.config_version
    h = bearer(db, world.support)
    r = client.put(f"/v1/support/kits/{world.kit_a1.id}/target-version", headers=h, json={"version": "0.9.1"})
    assert r.status_code == 200 and r.json()["target_agent_version"] == "0.9.1"
    db.expire_all()
    kit = db.get(m.Kit, world.kit_a1.id)
    assert kit is not None and kit.config_version == before + 1
    from seetlu.api.edge import build_config

    assert "0.9.1" in str(build_config(db, kit).model_dump(mode="json"))
    rows = db.scalars(select(m.AuditLog).where(m.AuditLog.action == "kit.target_version")).all()
    assert len(rows) == 1 and rows[0].account_id == world.acc_a.id
    bad = {"version": "1.0; rm -rf /"}
    assert client.put(f"/v1/support/kits/{kit.id}/target-version", headers=h, json=bad).status_code == 422


def test_m8_support_snapshot_needs_grant_and_is_audited(
    client: TestClient, db: Session, world: World
) -> None:
    h = bearer(db, world.support)
    url = f"/v1/support/kits/{world.kit_a1.id}/commands"
    r = client.post(url, headers=h, json={"type": "snapshot"})
    assert r.status_code == 403 and r.json()["type"].endswith("grant-required")
    assert client.post(url, headers=h, json={"type": "reboot"}).status_code == 202
    g = client.post("/v1/support-grants", headers=bearer(db, world.owner_a), json={"hours": 2})
    assert g.status_code == 201, g.text
    assert client.post(url, headers=h, json={"type": "snapshot"}).status_code == 202
    db.expire_all()
    actions = [a.action for a in db.scalars(select(m.AuditLog).order_by(m.AuditLog.at))]
    assert actions.count("support.access") == 2 and "support.grant" in actions
