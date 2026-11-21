"""M8 installer flow: claim (AC-F8-1), zones (AC-F8-2), count check (AC-F8-3), activation (AC-F8-4)."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from seetlu.api.installer import evaluate
from seetlu.core.ids import uuid7
from seetlu.core.security import hash_token
from seetlu.db import models as m
from tests.conftest import World, bearer

DOOR = {"type": "door_line", "geometry": [[0.2, 0.5], [0.8, 0.5]], "inward_side": "left"}
POLY = [[0.1, 0.1], [0.4, 0.1], [0.4, 0.4]]
COUNTER_ZONES = [{"type": "customer_side", "geometry": POLY}, {"type": "staff_side", "geometry": POLY}]
CAMERAS = [
    {"name": "door", "role": "door", "zones": [DOOR]},
    {"name": "counter", "role": "counter", "zones": COUNTER_ZONES},
]


def _new_kit(db: Session) -> tuple[m.Kit, str]:
    token = secrets.token_urlsafe(12)
    kit = m.Kit(serial=f"SN-{secrets.token_hex(4)}", claim_token_hash=hash_token(token))
    db.add(kit)
    db.commit()
    return kit, token


def _actions(db: Session, action: str) -> list[m.AuditLog]:
    db.expire_all()
    return list(db.scalars(select(m.AuditLog).where(m.AuditLog.action == action)))


def test_ac_f8_1_installer_claims_kit_from_qr(client: TestClient, db: Session, world: World) -> None:
    kit, token = _new_kit(db)
    h = bearer(db, world.installer)
    body = {"serial": kit.serial, "claim_token": token, "shop_id": str(world.shop_a2.id)}
    assert client.post("/v1/kits/claim", headers=h, json=body | {"claim_token": "wrong"}).status_code == 404
    r = client.post("/v1/kits/claim", headers=h, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "installing" and r.json()["shop_id"] == str(world.shop_a2.id)
    assert len(_actions(db, "kit.claim")) == 1
    # owners cannot claim; a claimed kit cannot move to another shop
    assert client.post("/v1/kits/claim", headers=bearer(db, world.owner_a), json=body).status_code == 403
    other = body | {"shop_id": str(world.shop_b.id)}
    assert client.post("/v1/kits/claim", headers=h, json=other).status_code == 409


def test_ac_f8_2_zones_saved_and_config_bumped(client: TestClient, db: Session, world: World) -> None:
    h = bearer(db, world.installer)
    before = world.kit_a1.config_version
    r = client.put(f"/v1/kits/{world.kit_a1.id}/cameras", headers=h, json=CAMERAS)
    assert r.status_code == 200, r.text
    db.expire_all()
    kit = db.get(m.Kit, world.kit_a1.id)
    assert kit is not None and kit.config_version == before + 1
    cams = {c.name: c for c in db.scalars(select(m.Camera).where(m.Camera.kit_id == kit.id))}
    assert set(cams) == {"door", "counter"}
    zones = list(db.scalars(select(m.Zone).where(m.Zone.camera_id == cams["door"].id)))
    assert zones[0].type is m.ZoneType.door_line and zones[0].inward_side == "left"
    assert len(_actions(db, "zone.update")) == 1
    # the agent receives them in its config
    from seetlu.api.edge import build_config

    cfg = build_config(db, kit).model_dump(mode="json")
    assert "door" in str(cfg) and "customer_side" in str(cfg)
    # re-sending replaces, not duplicates
    assert client.put(f"/v1/kits/{kit.id}/cameras", headers=h, json=CAMERAS[:1]).status_code == 200
    db.expire_all()
    assert [c.name for c in db.scalars(select(m.Camera).where(m.Camera.kit_id == kit.id))] == ["door"]


@pytest.mark.parametrize(
    "cameras",
    [
        [{"name": "door", "role": "door", "zones": []}],
        [{"name": "door", "role": "door", "zones": [DOOR | {"inward_side": None}]}],
        [{"name": "door", "role": "door", "zones": [DOOR | {"geometry": [[0.1, 1.5], [0.2, 0.2]]}]}],
        [{"name": "counter", "role": "counter", "zones": COUNTER_ZONES[:1]}],
        [CAMERAS[0], CAMERAS[0]],
    ],
)
def test_ac_f8_2_invalid_zones_rejected(
    client: TestClient, db: Session, world: World, cameras: list[dict[str, Any]]
) -> None:
    r = client.put(f"/v1/kits/{world.kit_a1.id}/cameras", headers=bearer(db, world.installer), json=cameras)
    assert r.status_code == 422


def test_ac_f8_3_evaluate_thresholds() -> None:
    assert evaluate(20, 22) == (Decimal("10.00"), True)
    assert evaluate(20, 23)[1] is False
    assert evaluate(19, 19) == (Decimal("0.00"), False)  # fewer than 20 entries
    assert evaluate(0, 3) == (None, False)


def _entries(db: Session, world: World, n: int, check_id: str) -> None:
    """A 30-minute check that started in the past, with n door entries inside it."""
    check = db.get(m.CountCheck, uuid.UUID(check_id))
    assert check is not None
    since = datetime.now(UTC) - timedelta(minutes=30)
    check.started_at = since
    for i in range(n):
        db.add(
            m.Event(
                id=uuid7(), started_at=since + timedelta(seconds=i + 1), shop_id=world.shop_a1.id,
                kit_id=world.kit_a1.id, type=m.EventType.entry,
            )
        )  # fmt: skip
    db.commit()


def test_ac_f8_3_count_check_pass_and_activation(client: TestClient, db: Session, world: World) -> None:
    h = bearer(db, world.installer)
    kit_id = world.kit_a1.id
    r = client.post(f"/v1/kits/{kit_id}/count-checks", headers=h)
    assert r.status_code == 201, r.text
    check = r.json()
    cmd = db.scalars(select(m.EdgeCommand).where(m.EdgeCommand.type == m.CommandType.count_check_start)).one()
    assert cmd.params["count_check_id"] == check["id"]
    _entries(db, world, 21, check["id"])
    r = client.post(f"/v1/count-checks/{check['id']}/stop", headers=h, json={"manual_count": 20})
    assert r.status_code == 200 and r.json()["passed"] is True and r.json()["agent_count"] == 21, r.text
    # AC-F8-4: no CDP reference → 409
    r = client.post(f"/v1/kits/{kit_id}/activate", headers=h)
    assert r.status_code == 409 and r.json()["type"].endswith("cdp-missing")
    world.shop_a1.cdp_declaration_ref = "CDP-2026-001"
    db.merge(world.shop_a1)
    db.commit()
    r = client.post(f"/v1/kits/{kit_id}/activate", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "active"
    db.expire_all()
    assert db.get(m.Shop, world.shop_a1.id).status is m.ShopStatus.active  # type: ignore[union-attr]
    assert len(_actions(db, "kit.activate")) == 1


def test_ac_f8_3_failed_check_blocks_activation_unless_override(
    client: TestClient, db: Session, world: World
) -> None:
    world.shop_a1.cdp_declaration_ref = "CDP-1"
    db.merge(world.shop_a1)
    db.commit()
    h = bearer(db, world.installer)
    kit_id = world.kit_a1.id
    assert client.post(f"/v1/kits/{kit_id}/activate", headers=h).status_code == 409  # no check at all
    check = client.post(f"/v1/kits/{kit_id}/count-checks", headers=h).json()
    _entries(db, world, 10, check["id"])
    r = client.post(f"/v1/count-checks/{check['id']}/stop", headers=h, json={"manual_count": 25})
    assert r.json()["passed"] is False
    r = client.post(f"/v1/kits/{kit_id}/activate", headers=h)
    assert r.status_code == 409 and r.json()["type"].endswith("count-check-required")
    body = {"manual_count": 25, "override_reason": "porte double, comptage manuel incertain"}
    r = client.post(f"/v1/count-checks/{check['id']}/stop", headers=h, json=body)  # override after the result
    assert r.json()["passed"] is False and r.json()["override_reason"] and r.json()["manual_count"] == 25
    assert len(_actions(db, "count_check.override")) == 1
    r = client.post(
        f"/v1/count-checks/{check['id']}/stop", headers=h, json=body | {"override_reason": "again"}
    )
    assert r.json()["override_reason"] != "again" and len(_actions(db, "count_check.override")) == 1
    assert client.post(f"/v1/kits/{kit_id}/activate", headers=h).status_code == 200


def test_m8_owner_cannot_run_count_check(client: TestClient, db: Session, world: World) -> None:
    r = client.post(f"/v1/kits/{world.kit_a1.id}/count-checks", headers=bearer(db, world.owner_a))
    assert r.status_code == 403


def test_m8_command_status_poll(client: TestClient, db: Session, world: World) -> None:
    h = bearer(db, world.installer)
    r = client.post(f"/v1/shops/{world.shop_a1.id}/snapshot", headers=h, params={"camera": "door"})
    assert r.status_code == 202, r.text
    cid = r.json()["command_id"]
    r = client.get(f"/v1/commands/{cid}", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "queued" and r.json()["clip_id"] is None
    assert client.get(f"/v1/commands/{cid}", headers=bearer(db, world.owner_b)).status_code == 404
