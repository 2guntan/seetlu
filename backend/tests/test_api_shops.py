"""M2 shops, users, alert rules: role scoping, validation, audit, problem+json."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from seetlu.db import models as m
from tests.conftest import HOURS, World, bearer, new_phone


def _names(resp: Any) -> set[str]:
    assert resp.status_code == 200, resp.text
    return {s["name"] for s in resp.json()}


def test_m2_shop_visibility_by_role(client: TestClient, db: Session, world: World) -> None:
    assert _names(client.get("/v1/shops", headers=bearer(db, world.owner_a))) == {"A1", "A2"}
    assert _names(client.get("/v1/shops", headers=bearer(db, world.owner_b))) == {"B"}
    assert _names(client.get("/v1/shops", headers=bearer(db, world.manager))) == {"A1"}
    assert _names(client.get("/v1/shops", headers=bearer(db, world.staff))) == {"A1"}
    assert _names(client.get("/v1/shops", headers=bearer(db, world.installer))) == {"A1"}
    assert _names(client.get("/v1/shops", headers=bearer(db, world.support))) == {"A1", "A2", "B"}


def test_m2_installer_loses_access_after_activation(client: TestClient, db: Session, world: World) -> None:
    world.kit_a1.status = m.KitStatus.active
    db.merge(world.kit_a1)
    db.commit()
    assert _names(client.get("/v1/shops", headers=bearer(db, world.installer))) == set()


def test_m2_other_account_shop_is_404_problem(client: TestClient, db: Session, world: World) -> None:
    r = client.get(f"/v1/shops/{world.shop_b.id}", headers=bearer(db, world.owner_a))
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["status"] == 404 and body["type"].startswith("https://seetlu.sn/problems/")


def test_m2_owner_updates_settings_and_bumps_edge_config(
    client: TestClient, db: Session, world: World
) -> None:
    h = bearer(db, world.owner_a)
    before = world.kit_a1.config_version
    r = client.patch(
        f"/v1/shops/{world.shop_a1.id}", headers=h, json={"report_time": "20:00", "name": "A1 bis"}
    )
    assert r.status_code == 200 and r.json()["report_time"] == "20:00:00"
    db.expire_all()
    assert db.get(m.Kit, world.kit_a1.id).config_version == before  # type: ignore[union-attr]
    r = client.patch(f"/v1/shops/{world.shop_a1.id}", headers=h, json={"service_min_s": 20})
    assert r.status_code == 200
    db.expire_all()
    assert db.get(m.Kit, world.kit_a1.id).config_version == before + 1  # type: ignore[union-attr]


def test_m2_settings_validation(client: TestClient, db: Session, world: World) -> None:
    h = bearer(db, world.owner_a)
    url = f"/v1/shops/{world.shop_a1.id}"
    for bad in (
        {"service_min_s": 5},
        {"service_min_s": 61},
        {"timezone": "Mars/Olympus"},
        {"opening_hours": {"mon": [["09:00", "08:00"]]}},
        {"unknown_field": 1},
    ):
        r = client.patch(url, headers=h, json=bad)
        assert r.status_code == 422, bad
        assert r.headers["content-type"].startswith("application/problem+json")


def test_m2_only_owner_or_installing_installer_change_settings(
    client: TestClient, db: Session, world: World
) -> None:
    url = f"/v1/shops/{world.shop_a1.id}"
    assert client.patch(url, headers=bearer(db, world.manager), json={"name": "x"}).status_code == 403
    assert client.patch(url, headers=bearer(db, world.staff), json={"name": "x"}).status_code == 403
    assert client.patch(url, headers=bearer(db, world.support), json={"name": "x"}).status_code == 403
    assert client.patch(url, headers=bearer(db, world.installer), json={"name": "x"}).status_code == 200
    r = client.patch(url, headers=bearer(db, world.installer), json={"clip_access_for_managers": True})
    assert r.status_code == 403


def test_m2_owner_toggles_clip_access_for_managers(client: TestClient, db: Session, world: World) -> None:
    r = client.patch(
        f"/v1/shops/{world.shop_a1.id}",
        headers=bearer(db, world.owner_a),
        json={"clip_access_for_managers": True},
    )
    assert r.status_code == 200
    db.expire_all()
    assert db.get(m.Account, world.acc_a.id).clip_access_for_managers is True  # type: ignore[union-attr]


def test_m2_owner_creates_shop_with_default_alert_rules(
    client: TestClient, db: Session, world: World
) -> None:
    body = {"name": "A3", "category": "pharmacie", "opening_hours": HOURS, "timezone": "Africa/Dakar"}
    r = client.post("/v1/shops", headers=bearer(db, world.owner_a), json=body)
    assert r.status_code == 201, r.text
    shop_id = r.json()["id"]
    assert r.json()["account_id"] == str(world.acc_a.id) and r.json()["status"] == "draft"
    rules = db.scalars(select(m.AlertRule).where(m.AlertRule.shop_id == shop_id)).all()
    assert {x.type for x in rules} == set(m.AlertType) and all(x.enabled for x in rules)


def test_m2_installer_creates_shop_for_new_owner(client: TestClient, db: Session, world: World) -> None:
    body: dict[str, Any] = {"name": "New", "category": "boutique", "opening_hours": HOURS}
    h = bearer(db, world.installer)
    assert client.post("/v1/shops", headers=h, json=body).status_code == 422
    phone = new_phone()
    r = client.post("/v1/shops", headers=h, json=body | {"owner": {"name": "Khady", "phone_e164": phone}})
    assert r.status_code == 201, r.text
    owner = db.scalars(select(m.User).where(m.User.phone_e164 == phone)).one()
    assert owner.role is m.UserRole.owner and owner.receives_report
    assert str(owner.account_id) == r.json()["account_id"]


def test_m2_manager_and_staff_cannot_create_shops(client: TestClient, db: Session, world: World) -> None:
    body = {"name": "x", "category": "boutique", "opening_hours": HOURS}
    for u in (world.manager, world.staff, world.support):
        assert client.post("/v1/shops", headers=bearer(db, u), json=body).status_code == 403


def test_m2_owner_invites_manager_with_audit(client: TestClient, db: Session, world: World) -> None:
    phone = new_phone()
    body = {"name": "Ousmane", "phone_e164": phone, "role": "manager", "receives_report": True}
    r = client.post(f"/v1/shops/{world.shop_a2.id}/users", headers=bearer(db, world.owner_a), json=body)
    assert r.status_code == 201, r.text
    invited = db.scalars(select(m.User).where(m.User.phone_e164 == phone)).one()
    assert db.get(m.UserShop, (invited.id, world.shop_a2.id)) is not None
    log = db.scalars(select(m.AuditLog).where(m.AuditLog.action == "user.invite")).one()
    assert (
        log.actor_id == world.owner_a.id and log.target_id == invited.id and log.account_id == world.acc_a.id
    )
    users = client.get(f"/v1/shops/{world.shop_a2.id}/users", headers=bearer(db, world.owner_a)).json()
    assert {u["role"] for u in users} == {"owner", "manager"}


def test_m2_invite_rules(client: TestClient, db: Session, world: World) -> None:
    url = f"/v1/shops/{world.shop_a1.id}/users"
    body = {"name": "x", "phone_e164": new_phone(), "role": "staff"}
    assert client.post(url, headers=bearer(db, world.manager), json=body).status_code == 403
    taken = body | {"phone_e164": world.owner_b.phone_e164}
    assert client.post(url, headers=bearer(db, world.owner_a), json=taken).status_code == 409
    owner_role = body | {"role": "owner"}
    assert client.post(url, headers=bearer(db, world.owner_a), json=owner_role).status_code == 422


def test_m2_ac_f6_3_owner_toggles_and_tunes_alerts(client: TestClient, db: Session, world: World) -> None:
    url = f"/v1/shops/{world.shop_a1.id}/alert-rules"
    h = bearer(db, world.owner_a)
    rules = client.get(url, headers=h).json()
    assert [r["type"] for r in rules] == ["not_opened", "unattended", "after_hours_motion", "kit_offline"]
    body = {
        "rules": [
            {"type": "unattended", "enabled": True, "params": {"min": 20}},
            {"type": "after_hours_motion", "enabled": False, "params": {}},
        ]
    }
    r = client.put(url, headers=h, json=body)
    assert r.status_code == 200
    by_type = {x["type"]: x for x in r.json()}
    assert by_type["unattended"]["params"] == {"min": 20}
    assert by_type["after_hours_motion"]["enabled"] is False
    assert by_type["not_opened"]["params"] == {"grace_min": 30}


def test_m2_alert_rules_validation_and_permissions(client: TestClient, db: Session, world: World) -> None:
    url = f"/v1/shops/{world.shop_a1.id}/alert-rules"
    bad = {"rules": [{"type": "unattended", "enabled": True, "params": {"bogus": 3}}]}
    assert client.put(url, headers=bearer(db, world.owner_a), json=bad).status_code == 422
    zero = {"rules": [{"type": "unattended", "enabled": True, "params": {"min": 0}}]}
    assert client.put(url, headers=bearer(db, world.owner_a), json=zero).status_code == 422
    assert client.get(url, headers=bearer(db, world.manager)).status_code == 403
    assert client.get(url, headers=bearer(db, world.support)).status_code == 403
