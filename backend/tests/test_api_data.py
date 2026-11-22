"""M8 owner-app data: reports/history, today, hourly, sales log, corrections (AC-F9-1), clips (AC-F5-3), audit."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from seetlu.core.ids import uuid7
from seetlu.db import models as m
from seetlu.reports import service
from tests.conftest import World, bearer

DAY = date(2026, 11, 17)  # a Tuesday


def _at(h: int, mi: int = 0) -> datetime:
    return datetime(DAY.year, DAY.month, DAY.day, h, mi, tzinfo=ZoneInfo("Africa/Dakar"))


def _day(db: Session, world: World) -> None:
    shop, kit = world.shop_a1, world.kit_a1
    for i in range(6):
        db.add(
            m.Event(id=uuid7(), started_at=_at(9, i), shop_id=shop.id, kit_id=kit.id, type=m.EventType.entry)
        )
    db.add(
        m.Event(id=uuid7(), started_at=_at(9, 30), shop_id=shop.id, kit_id=kit.id, type=m.EventType.service)
    )
    for h in range(8, 21):  # heartbeats every hour so no hour is missing
        db.add(m.Heartbeat(kit_id=kit.id, at=_at(h, 10)))
    db.add(
        m.Sale(
            shop_id=shop.id,
            source=m.SaleSource.quick_log,
            amount_xof=5000,
            occurred_at=_at(9, 40),
            local_date=DAY,
        )
    )
    db.commit()


def test_ac_f7_1_history_and_hourly(client: TestClient, db: Session, world: World) -> None:
    world.kit_a1.status = m.KitStatus.active
    db.merge(world.kit_a1)
    db.commit()
    _day(db, world)
    service.compute(db, world.shop_a1, DAY)
    db.commit()
    h = bearer(db, world.owner_a)
    r = client.get(
        f"/v1/shops/{world.shop_a1.id}/reports", headers=h, params={"from": "2026-11-01", "to": "2026-11-30"}
    )
    assert r.status_code == 200, r.text
    [rep] = r.json()
    assert rep["local_date"] == "2026-11-17" and rep["visitors_in"] == 6 and rep["sales_xof"] == 5000
    assert rep["verdict"] and rep["corrections"] == []
    bad = {"from": "2026-01-01", "to": "2026-11-30"}
    assert client.get(f"/v1/shops/{world.shop_a1.id}/reports", headers=h, params=bad).status_code == 422
    r = client.get(f"/v1/shops/{world.shop_a1.id}/hourly", headers=h, params={"date": "2026-11-17"})
    hours = r.json()
    assert len(hours) == 24 and hours[9]["entries"] == 6 and hours[9]["served"] == 1
    assert hours[9]["sales_xof"] == 5000 and hours[9]["missing"] is False
    r = client.get(
        f"/v1/shops/{world.shop_a1.id}/events", headers=h, params={"date": "2026-11-17", "type": "service"}
    )
    assert [e["type"] for e in r.json()] == ["service"]
    # other account: invisible
    other = client.get(
        f"/v1/shops/{world.shop_a1.id}/hourly",
        headers=bearer(db, world.owner_b),
        params={"date": "2026-11-17"},
    )
    assert other.status_code == 404


def test_m8_today_counter_state(client: TestClient, db: Session, world: World) -> None:
    h = bearer(db, world.owner_a)
    r = client.get(f"/v1/shops/{world.shop_a1.id}/today", headers=h)
    assert r.status_code == 200 and r.json()["counter"]["state"] == "unknown"  # no heartbeat: never "empty"
    now = datetime.now(UTC)
    db.add(m.Heartbeat(kit_id=world.kit_a1.id, at=now - timedelta(minutes=1)))
    db.add(
        m.Event(id=uuid7(), started_at=now - timedelta(minutes=3), shop_id=world.shop_a1.id,
                kit_id=world.kit_a1.id, type=m.EventType.unattended)
    )  # fmt: skip
    db.commit()
    r = client.get(f"/v1/shops/{world.shop_a1.id}/today", headers=h)
    assert r.json()["counter"]["state"] == "empty" and r.json()["verdict"] is None


def test_m8_sales_log_quick_log_cash_and_void(client: TestClient, db: Session, world: World) -> None:
    url = f"/v1/shops/{world.shop_a1.id}/sales"
    staff, manager = bearer(db, world.staff), bearer(db, world.manager)
    now = datetime.now(UTC).isoformat()
    cid = str(uuid7())
    body = {"client_id": cid, "source": "quick_log", "amount_xof": 2500, "occurred_at": now}
    r1, r2 = client.post(url, headers=staff, json=body), client.post(url, headers=staff, json=body)
    assert r1.status_code == 201 and r2.json()["id"] == r1.json()["id"] == cid  # idempotent offline retry
    cash = {"source": "cash_declaration", "amount_xof": 40000, "occurred_at": now}
    assert client.post(url, headers=staff, json=cash).status_code == 403  # staff: quick log only
    assert client.post(url, headers=manager, json=cash).status_code == 201
    assert client.post(url, headers=manager, json=cash | {"amount_xof": 42000}).status_code == 201
    today = datetime.now(UTC).astimezone(ZoneInfo("Africa/Dakar")).date().isoformat()
    rows = client.get(url, headers=manager, params={"date": today}).json()
    live_cash = [x for x in rows if x["source"] == "cash_declaration" and x["voided_at"] is None]
    assert [x["amount_xof"] for x in live_cash] == [42000]  # a new declaration replaces the previous one
    assert (
        client.post(url, headers=staff, json=body | {"amount_xof": 0, "client_id": None}).status_code == 422
    )
    # void: own entry only
    assert client.delete(f"{url}/{cid}", headers=manager).status_code == 403
    assert client.delete(f"{url}/{cid}", headers=staff).status_code == 204


def test_ac_f9_1_correction_stored_shown_and_audited(client: TestClient, db: Session, world: World) -> None:
    _day(db, world)
    service.compute(db, world.shop_a1, DAY)
    db.commit()
    h = bearer(db, world.manager)
    body = {
        "local_date": "2026-11-17",
        "metric": "visitors_in",
        "corrected_value": 40,
        "note": "porte bloquée",
    }
    r = client.post(f"/v1/shops/{world.shop_a1.id}/corrections", headers=h, json=body)
    assert r.status_code == 201, r.text
    assert r.json()["corrections"] == [{"metric": "visitors_in", "corrected_value": 40, "reported_value": 6}]
    db.expire_all()
    assert db.scalars(select(m.AuditLog).where(m.AuditLog.action == "correction.create")).one()
    r = client.get(
        f"/v1/shops/{world.shop_a1.id}/reports", headers=h, params={"from": "2026-11-17", "to": "2026-11-17"}
    )
    assert r.json()[0]["corrections"][0]["corrected_value"] == 40
    staff = client.post(
        f"/v1/shops/{world.shop_a1.id}/corrections", headers=bearer(db, world.staff), json=body
    )
    assert staff.status_code == 403


def _clip(db: Session, world: World, **kw: object) -> m.Clip:
    c = m.Clip(shop_id=world.shop_a1.id, object_key=f"k/{uuid7()}.mp4", kind="clip", **kw)
    db.add(c)
    db.commit()
    return c


def test_ac_f5_3_save_limit_30_per_account(client: TestClient, db: Session, world: World) -> None:
    h = bearer(db, world.owner_a)
    soon = datetime.now(UTC) + timedelta(days=3)
    for _ in range(30):
        _clip(db, world, saved_by=world.owner_a.id)
    extra = _clip(db, world, expires_at=soon)
    r = client.post(f"/v1/clips/{extra.id}/save", headers=h)
    assert r.status_code == 409 and r.json()["type"].endswith("save-limit")
    one = db.scalars(select(m.Clip).where(m.Clip.saved_by.is_not(None))).first()
    assert one is not None
    r = client.delete(f"/v1/clips/{one.id}/save", headers=h)
    assert r.status_code == 200 and r.json()["expires_at"] is not None
    r = client.post(f"/v1/clips/{extra.id}/save", headers=h)
    assert r.status_code == 200 and r.json()["saved"] is True and r.json()["expires_at"] is None
    expired = _clip(db, world, expires_at=datetime.now(UTC) - timedelta(minutes=1))
    assert client.post(f"/v1/clips/{expired.id}/save", headers=h).status_code == 410
    listed = client.get(f"/v1/shops/{world.shop_a1.id}/clips", headers=h).json()
    assert expired.id not in {c["id"] for c in listed} and len(listed) == 31
    db.expire_all()
    actions = [a.action for a in db.scalars(select(m.AuditLog))]
    assert actions.count("clip.save") == 1 and actions.count("clip.unsave") == 1


def test_m8_audit_log_scoped_to_account(client: TestClient, db: Session, world: World) -> None:
    assert client.post("/v1/support-grants", headers=bearer(db, world.owner_a), json={}).status_code == 201
    assert (
        client.post("/v1/support-grants", headers=bearer(db, world.owner_b), json={"hours": 1}).status_code
        == 201
    )
    a = client.get("/v1/audit-log", headers=bearer(db, world.owner_a)).json()
    assert {r["account_id"] for r in a} == {str(world.acc_a.id)} and a[0]["actor_name"] == "owner"
    assert len(client.get("/v1/audit-log", headers=bearer(db, world.support)).json()) == 2
    assert client.get("/v1/audit-log", headers=bearer(db, world.staff)).status_code == 403
    assert client.post("/v1/support-grants", headers=bearer(db, world.manager), json={}).status_code == 403
    assert (
        client.post("/v1/support-grants", headers=bearer(db, world.owner_a), json={"hours": 48}).status_code
        == 422
    )


def test_ac_f5_3_clips_listed_by_moment_time_not_cut_time(
    client: TestClient, db: Session, world: World
) -> None:
    """Moments shows when the filmed event happened; all clips of a report are cut at the same minute."""
    cam = m.Camera(kit_id=world.kit_a1.id, role=m.CameraRole.door, name="door", rtsp_main_path="/a",
                   rtsp_sub_path="/b")  # fmt: skip
    db.add(cam)
    db.flush()
    early, late = datetime(2026, 11, 20, 9, 5, tzinfo=UTC), datetime(2026, 11, 20, 15, 5, tzinfo=UTC)
    evs = [m.Event(id=uuid7(), started_at=at, shop_id=world.shop_a1.id, kit_id=world.kit_a1.id,
                   camera_id=cam.id, type=m.EventType.entry) for at in (early, late)]  # fmt: skip
    db.add_all(evs)
    db.commit()
    for ev in evs:
        _clip(db, world, event_id=ev.id)
    loose = _clip(db, world)  # no event: falls back to the cut time
    listed = client.get(f"/v1/shops/{world.shop_a1.id}/clips", headers=bearer(db, world.owner_a)).json()
    assert listed[0]["id"] == str(loose.id)
    by_event = {c["event_id"]: c["moment_at"] for c in listed if c["event_id"]}
    assert datetime.fromisoformat(by_event[str(evs[0].id)]) == early
    assert datetime.fromisoformat(by_event[str(evs[1].id)]) == late
    assert [c["event_id"] for c in listed][1:] == [str(evs[1].id), str(evs[0].id)]
