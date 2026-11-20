"""M2 auth: OTP over WhatsApp (MockProvider), JWT access/refresh (AC-F7-2, docs/09)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from seetlu.core.config import get_settings
from seetlu.db import models as m
from tests.conftest import World


def _last_code(db: Session, phone: str) -> str:
    db.expire_all()
    msg = db.scalars(
        select(m.MockMessage).where(m.MockMessage.to_phone == phone).order_by(m.MockMessage.created_at.desc())
    ).first()
    assert msg is not None and msg.template == "otp_fr"
    return str(msg.params[0])


def _login(client: TestClient, db: Session, phone: str) -> dict[str, Any]:
    assert client.post("/v1/auth/otp/request", json={"phone_e164": phone}).status_code == 204
    r = client.post("/v1/auth/otp/verify", json={"phone_e164": phone, "code": _last_code(db, phone)})
    assert r.status_code == 200, r.text
    return dict(r.json())


def test_m2_ac_f7_2_login_with_whatsapp_code(client: TestClient, db: Session, world: World) -> None:
    tokens = _login(client, db, world.owner_a.phone_e164)
    me = client.get("/v1/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200
    assert me.json()["user"]["id"] == str(world.owner_a.id)
    assert {s["name"] for s in me.json()["shops"]} == {"A1", "A2"}
    assert tokens["expires_in"] == 900  # 15 min access token


def test_m2_ac_f7_2_phone_is_normalised(client: TestClient, db: Session, world: World) -> None:
    raw = world.owner_a.phone_e164
    spaced = f"{raw[:4]} {raw[4:6]} {raw[6:9]} {raw[9:]}"
    assert client.post("/v1/auth/otp/request", json={"phone_e164": spaced}).status_code == 204
    _last_code(db, raw)


def test_m2_unknown_phone_gets_204_and_no_message(client: TestClient, db: Session, world: World) -> None:
    assert client.post("/v1/auth/otp/request", json={"phone_e164": "+221779999999"}).status_code == 204
    assert db.scalars(select(m.MockMessage)).first() is None
    r = client.post("/v1/auth/otp/verify", json={"phone_e164": "+221779999999", "code": "123456"})
    assert r.status_code == 401


def test_m2_wrong_code_five_attempts_then_locked(client: TestClient, db: Session, world: World) -> None:
    phone = world.owner_a.phone_e164
    client.post("/v1/auth/otp/request", json={"phone_e164": phone})
    good = _last_code(db, phone)
    bad = "000001" if good != "000001" else "000002"
    for _ in range(5):
        r = client.post("/v1/auth/otp/verify", json={"phone_e164": phone, "code": bad})
        assert r.status_code == 401
        assert r.headers["content-type"].startswith("application/problem+json")
    assert client.post("/v1/auth/otp/verify", json={"phone_e164": phone, "code": good}).status_code == 401


def test_m2_expired_code_rejected(client: TestClient, db: Session, world: World) -> None:
    phone = world.owner_a.phone_e164
    client.post("/v1/auth/otp/request", json={"phone_e164": phone})
    code = _last_code(db, phone)
    db.execute(update(m.OtpCode).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    db.commit()
    assert client.post("/v1/auth/otp/verify", json={"phone_e164": phone, "code": code}).status_code == 401


def test_m2_code_is_single_use(client: TestClient, db: Session, world: World) -> None:
    phone = world.owner_a.phone_e164
    client.post("/v1/auth/otp/request", json={"phone_e164": phone})
    code = _last_code(db, phone)
    assert client.post("/v1/auth/otp/verify", json={"phone_e164": phone, "code": code}).status_code == 200
    assert client.post("/v1/auth/otp/verify", json={"phone_e164": phone, "code": code}).status_code == 401


def test_m2_otp_rate_limit_per_phone(client: TestClient, world: World) -> None:
    phone = world.owner_a.phone_e164
    for _ in range(3):
        assert client.post("/v1/auth/otp/request", json={"phone_e164": phone}).status_code == 204
    r = client.post("/v1/auth/otp/request", json={"phone_e164": phone})
    assert r.status_code == 429
    assert r.json()["type"].endswith("/otp-rate-limited")


def test_m2_otp_rate_limit_per_ip(client: TestClient, world: World) -> None:
    for u in (world.owner_a, world.owner_b, world.manager):
        assert client.post("/v1/auth/otp/request", json={"phone_e164": u.phone_e164}).status_code == 204
    assert client.post("/v1/auth/otp/request", json={"phone_e164": world.staff.phone_e164}).status_code == 429


def test_m2_dev_fixed_otp(
    client: TestClient, db: Session, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "dev_fixed_otp", "000000")
    phone = world.owner_a.phone_e164
    client.post("/v1/auth/otp/request", json={"phone_e164": phone})
    r = client.post("/v1/auth/otp/verify", json={"phone_e164": phone, "code": "000000"})
    assert r.status_code == 200


def test_m2_invalid_phone_is_problem_422(client: TestClient) -> None:
    r = client.post("/v1/auth/otp/request", json={"phone_e164": "77 000"})
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["status"] == 422 and r.json()["errors"]


def test_m2_refresh_rotates_and_detects_reuse(client: TestClient, db: Session, world: World) -> None:
    first = _login(client, db, world.owner_a.phone_e164)
    second = client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert second.status_code == 200
    assert second.json()["refresh_token"] != first["refresh_token"]
    # reusing the rotated token fails and revokes the whole family
    assert client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}).status_code == 401
    assert (
        client.post("/v1/auth/refresh", json={"refresh_token": second.json()["refresh_token"]}).status_code
        == 401
    )


def test_m2_token_types_and_missing_token(client: TestClient, db: Session, world: World) -> None:
    tokens = _login(client, db, world.owner_a.phone_e164)
    assert client.get("/v1/me").status_code == 401
    r = client.get("/v1/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"})
    assert r.status_code == 401 and r.headers["content-type"].startswith("application/problem+json")
    bad = client.post("/v1/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert bad.status_code == 401


def test_m2_inactive_user_cannot_use_token(client: TestClient, db: Session, world: World) -> None:
    tokens = _login(client, db, world.owner_a.phone_e164)
    db.execute(update(m.User).where(m.User.id == world.owner_a.id).values(active=False))
    db.commit()
    assert (
        client.get("/v1/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}).status_code == 401
    )
