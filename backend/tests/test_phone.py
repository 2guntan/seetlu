"""M9 backend for the shop phone: parser rules (shared fixtures), sealing, pairing, sales batch."""

import base64
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from seetlu.core.config import get_settings
from seetlu.core.ids import uuid7
from seetlu.db import models as m
from seetlu.phone import crypto
from seetlu.phone import rules as phone_rules
from seetlu.reports import service
from tests.conftest import World, bearer

FIXTURES = Path(__file__).resolve().parents[2] / "android/shop-phone/src/test/resources/notifications"
CASES = json.loads((FIXTURES / "placeholder-cases.json").read_text("utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_m9_reference_parser_on_shared_fixtures(case: dict[str, Any]) -> None:
    got = phone_rules.parse(case["package"], case["text"])
    want = case["expect"]
    if want is None or want == "unparsed":
        assert got == want
    else:
        assert isinstance(got, phone_rules.Parsed)
        assert (got.source, got.amount_xof, got.external_ref) == (
            want["source"],
            want["amount_xof"],
            want["external_ref"],
        )


def test_m9_rules_are_well_formed() -> None:
    data = phone_rules.load()
    assert data["version"] == phone_rules.current_version()
    for r in data["rules"]:
        assert {"id", "source", "package", "match_regex", "amount_group", "direction"} <= set(r)
        assert r["source"] in ("wave", "orange_money") and r["direction"] == "in"


def test_m9_seal_roundtrip_and_shape() -> None:
    pub, priv = crypto.generate_keypair()
    blob = crypto.seal(pub, "Vous avez reçu 5.000F")
    assert crypto.valid_blob(blob) and b"5.000" not in blob
    assert crypto.open_sealed(priv, blob) == "Vous avez reçu 5.000F"
    assert not crypto.valid_blob(b"Vous avez recu 5.000F")


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, str]]:
    pub, priv = crypto.generate_keypair()
    monkeypatch.setenv("RAW_PUBLIC_KEY_B64", pub)
    get_settings.cache_clear()
    yield pub, priv
    get_settings.cache_clear()


def _pair(client: TestClient, db: Session, world: World) -> dict[str, Any]:
    r = client.post(f"/v1/shops/{world.shop_a1.id}/phone-pairing-codes", headers=bearer(db, world.owner_a))
    assert r.status_code == 201, r.text
    r = client.post(
        "/v1/phone/pair", json={"code": r.json()["code"], "model": "Tecno Spark", "app_version": "0.1.0"}
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


def test_m9_pairing_with_6_digit_code(
    client: TestClient, db: Session, world: World, keys: tuple[str, str]
) -> None:
    owner = bearer(db, world.owner_a)
    url = f"/v1/shops/{world.shop_a1.id}/phone-pairing-codes"
    assert client.post(url, headers=bearer(db, world.manager)).status_code == 403
    code = client.post(url, headers=owner).json()["code"]
    assert len(code) == 6 and code.isdigit()
    r = client.post("/v1/phone/pair", json={"code": code, "model": "Itel A70"})
    assert r.status_code == 200 and r.json()["shop_id"] == str(world.shop_a1.id)
    assert r.json()["raw_public_key_b64"] == keys[0]
    assert client.post("/v1/phone/pair", json={"code": code}).status_code == 404  # single use
    # a new code invalidates the previous unused one
    c1 = client.post(url, headers=owner).json()["code"]
    c2 = client.post(url, headers=owner).json()["code"]
    if c1 != c2:
        assert client.post("/v1/phone/pair", json={"code": c1}).status_code == 404
    assert client.post("/v1/phone/pair", json={"code": c2}).status_code == 200
    phones = client.get(f"/v1/shops/{world.shop_a1.id}/phones", headers=owner).json()
    assert len(phones) == 2 and phones[0]["model"] == "Itel A70"
    actions = [a.action for a in db.scalars(select(m.AuditLog))]
    assert actions.count("phone.pair") == 2


def test_m9_pairing_rate_limited(client: TestClient, db: Session, world: World) -> None:
    for _ in range(10):
        assert client.post("/v1/phone/pair", json={"code": "000001"}).status_code == 404
    assert client.post("/v1/phone/pair", json={"code": "000001"}).status_code == 429


def test_m9_expired_code(client: TestClient, db: Session, world: World) -> None:
    code = client.post(
        f"/v1/shops/{world.shop_a1.id}/phone-pairing-codes", headers=bearer(db, world.owner_a)
    ).json()["code"]
    for row in db.scalars(select(m.PhonePairCode)):
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert client.post("/v1/phone/pair", json={"code": code}).status_code == 404


def test_m9_parsers_need_token_and_support_etag(client: TestClient, db: Session, world: World) -> None:
    tok = _pair(client, db, world)["device_token"]
    assert client.get("/v1/phone/parsers").status_code == 401
    bad = tok.split(".")[0] + ".nope"
    assert client.get("/v1/phone/parsers", headers={"Authorization": f"Bearer {bad}"}).status_code == 401
    h = {"Authorization": f"Bearer {tok}"}
    r = client.get("/v1/phone/parsers", headers=h)
    assert r.status_code == 200 and r.json()["version"] == phone_rules.current_version()
    assert len(r.json()["rules"]) >= 2
    r2 = client.get("/v1/phone/parsers", headers=h | {"If-None-Match": r.headers["etag"]})
    assert r2.status_code == 304


def _sale(**kw: Any) -> dict[str, Any]:
    base = {
        "client_id": str(uuid7()),
        "source": "wave",
        "amount_xof": 5000,
        "occurred_at": datetime.now(UTC).isoformat(),
        "external_ref": "T8K2M9QZ",
        "parser_version": phone_rules.current_version(),
    }
    return base | kw


def test_m9_sales_batch_idempotent(
    client: TestClient, db: Session, world: World, keys: tuple[str, str]
) -> None:
    tok = _pair(client, db, world)["device_token"]
    h = {"Authorization": f"Bearer {tok}", "X-App-Version": "0.1.1"}
    sealed = base64.b64encode(crypto.seal(keys[0], "Vous avez reçu 5.000F de Awa. Réf: T8K2M9QZ")).decode()
    first = _sale(raw=sealed)
    quick = _sale(source="quick_log", amount_xof=1500, external_ref="ignored")
    r = client.post("/v1/sales/batch", headers=h, json={"sales": [first, quick]})
    assert r.status_code == 200, r.text
    assert r.json() == {"accepted": 2, "duplicates": 0, "unparsed": 0}
    # same client_id again, and another client_id with the same mobile-money reference
    again = {"sales": [first, _sale(), _sale(external_ref="OTHER-REF-1", amount_xof=2000)]}
    assert client.post("/v1/sales/batch", headers=h, json=again).json() == {
        "accepted": 1,
        "duplicates": 2,
        "unparsed": 0,
    }
    db.expire_all()
    rows = db.scalars(select(m.Sale).where(m.Sale.shop_id == world.shop_a1.id)).all()
    assert sorted(r.amount_xof for r in rows) == [1500, 2000, 5000]
    wave = next(r for r in rows if r.external_ref == "T8K2M9QZ")
    assert wave.raw_encrypted is not None and crypto.open_sealed(keys[1], wave.raw_encrypted).startswith(
        "Vous avez"
    )
    assert next(r for r in rows if r.source is m.SaleSource.quick_log).external_ref is None
    device = db.scalars(select(m.PhoneDevice)).one()
    assert device.parser_version == phone_rules.current_version() and device.app_version == "0.1.1"


def test_m9_plain_text_raw_rejected_and_unparsed_stored(
    client: TestClient, db: Session, world: World, keys: tuple[str, str]
) -> None:
    tok = _pair(client, db, world)["device_token"]
    h = {"Authorization": f"Bearer {tok}"}
    plain = base64.b64encode("Vous avez reçu 5.000F".encode()).decode()
    assert client.post("/v1/sales/batch", headers=h, json={"sales": [_sale(raw=plain)]}).status_code == 422
    sealed = base64.b64encode(crypto.seal(keys[0], "Paiement reçu de 3.000F")).decode()
    body = {
        "unparsed": [
            {"package_name": "com.wave.personal", "received_at": datetime.now(UTC).isoformat(), "raw": sealed}
        ]
    }
    r = client.post("/v1/sales/batch", headers=h, json=body)
    assert r.json()["unparsed"] == 1
    assert db.scalars(select(m.UnparsedNotification)).one().package_name == "com.wave.personal"
    too_many = {"sales": [_sale() for _ in range(201)]}
    assert client.post("/v1/sales/batch", headers=h, json=too_many).status_code == 422


def test_m9_late_phone_sale_recomputes_sent_report(client: TestClient, db: Session, world: World) -> None:
    world.kit_a1.status = m.KitStatus.active
    db.merge(world.kit_a1)
    db.commit()
    d = date(2026, 11, 17)
    computed = service.compute(db, world.shop_a1, d)
    computed.row.sent_at = datetime.now(UTC) - timedelta(hours=1)
    db.commit()
    tok = _pair(client, db, world)["device_token"]
    at = datetime(2026, 11, 17, 12, 0, tzinfo=ZoneInfo("Africa/Dakar")).isoformat()
    r = client.post(
        "/v1/sales/batch",
        headers={"Authorization": f"Bearer {tok}"},
        json={"sales": [_sale(occurred_at=at, amount_xof=9000)]},
    )
    assert r.json()["accepted"] == 1
    db.expire_all()
    rep = db.scalars(select(m.DailyReport).where(m.DailyReport.local_date == d)).one()
    assert rep.sales_xof == 9000
