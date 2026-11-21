"""WhatsApp: webhook, inbound grammar actions and replies, clip links (docs/07, AC-F3-4/5, AC-F4-6, AC-F5-*)."""

import hashlib
import hmac
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from seetlu.core.config import get_settings
from seetlu.core.ids import uuid7
from seetlu.core.security import hash_token
from seetlu.db import models as m
from seetlu.domain.report_text import money
from seetlu.i18n import t
from seetlu.messaging import clips
from seetlu.messaging.inbound import handle, open_cash_prompt
from seetlu.messaging.processing import process
from seetlu.messaging.provider import MockProvider
from seetlu.reports import service
from tests.conftest import World, bearer
from tests.test_reports_service import D, at, fill_day, setup_shop

NOW = at(21, 5)


def texts(s: Session, phone: str) -> list[str]:
    q = select(m.MockMessage).where(m.MockMessage.to_phone == phone).order_by(m.MockMessage.id)
    return [x.body or "" for x in s.scalars(q)]


def say(s: Session, user: m.User, text: str, now: datetime = NOW) -> str | None:
    return handle(s, user.phone_e164.lstrip("+"), text, MockProvider(s), now)


@pytest.fixture
def reported(db: Session, world: World) -> m.DailyReport:
    """Shop A1 with a sent report whose first moment is after-hours motion (a clip command queued)."""
    shop, door, counter = setup_shop(db, world)
    fill_day(db, world, door, counter)
    db.add(m.Event(started_at=at(6, 0), shop_id=shop.id, kit_id=world.kit_a1.id, camera_id=door.id,
                   type=m.EventType.after_hours_motion, id=uuid7()))  # fmt: skip
    db.commit()
    c = service.compute_and_send(db, shop.id, D, now=at(21, 0), provider=MockProvider(db))
    return c.row


def finish(db: Session, cmd: m.EdgeCommand, now: datetime = NOW) -> m.Clip:
    cmd.status = m.CommandStatus.done
    kind = "snapshot" if cmd.type is m.CommandType.snapshot else "clip"
    kit = db.get(m.Kit, cmd.kit_id)
    assert kit is not None and kit.shop_id is not None
    clip = m.Clip(shop_id=kit.shop_id, command_id=cmd.id, object_key=f"shops/x/{kind}s/{cmd.id}", kind=kind,
                  expires_at=now + timedelta(days=7))  # fmt: skip
    db.add(clip)
    db.flush()
    return clip


# ---------- webhook ----------
def signed(body: dict[str, Any], secret: str = "app-secret") -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(body).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"X-Hub-Signature-256": f"sha256={sig}", "Content-Type": "application/json"}


def wa_payload(*msgs: tuple[str, str, str]) -> dict[str, Any]:
    return {"entry": [{"changes": [{"value": {
        "messages": [{"id": i, "from": f, "type": "text", "text": {"body": b}} for i, f, b in msgs],
        "statuses": [{"id": "x", "status": "delivered"}]}}]}]}  # fmt: skip


@pytest.fixture
def wa_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    st = get_settings()
    monkeypatch.setattr(st, "wa_app_secret", "app-secret")
    monkeypatch.setattr(st, "wa_verify_token", "verify-me")


def test_webhook_verification_challenge(client: TestClient, wa_secrets: None) -> None:
    q = {"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"}
    r = client.get("/v1/webhooks/whatsapp", params=q)
    assert r.status_code == 200 and r.text == "42"
    assert client.get("/v1/webhooks/whatsapp", params=q | {"hub.verify_token": "no"}).status_code == 403


def test_webhook_checks_signature_stores_once_and_enqueues(
    client: TestClient, db: Session, wa_secrets: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from seetlu.workers import tasks

    queued: list[str] = []
    monkeypatch.setattr(tasks.process_inbound, "delay", lambda i: queued.append(i))
    raw, headers = signed(wa_payload(("wamid.1", "221770000009", "aide")))
    assert client.post("/v1/webhooks/whatsapp", content=raw, headers=headers | {
        "X-Hub-Signature-256": "sha256=bad"}).status_code == 401  # fmt: skip
    assert client.post("/v1/webhooks/whatsapp", content=raw, headers=headers).json() == {"received": 1}
    assert client.post("/v1/webhooks/whatsapp", content=raw, headers=headers).json() == {
        "received": 0
    }  # retry
    assert len(queued) == 1
    row = db.scalars(select(m.WaInbound)).one()
    assert (row.from_phone, row.body, row.processed_at) == ("221770000009", "aide", None)


def test_process_runs_each_inbound_once(db: Session, world: World) -> None:
    row = m.WaInbound(wa_message_id="wamid.2", from_phone=world.owner_a.phone_e164.lstrip("+"), body="aide")
    db.add(row)
    db.commit()
    assert process(db, row.id, MockProvider(db), NOW) == t("wa.help")
    assert process(db, row.id, MockProvider(db), NOW) is None
    assert texts(db, world.owner_a.phone_e164) == [t("wa.help")]


# ---------- grammar actions ----------
def test_unknown_phone_gets_no_reply_and_unknown_text_gets_help_hint(db: Session, world: World) -> None:
    assert handle(db, "221779999999", "aide", MockProvider(db), NOW) is None
    assert db.scalar(select(func.count()).select_from(m.MockMessage)) == 0
    assert say(db, world.owner_a, "bonjour") == "Je n'ai pas compris. Tapez aide."
    assert say(db, world.owner_a, "+20000000") == "Montant trop élevé, vérifiez."


def test_reply_1_returns_clip_link_when_ready_else_preparing_then_link_AC_F4_6(
    db: Session, world: World, reported: m.DailyReport
) -> None:
    owner = world.owner_a
    assert say(db, owner, "1") == t("wa.clip_preparing")
    cmd = db.get(m.EdgeCommand, uuid.UUID(reported.moments[0]["clip_command_id"]))
    assert cmd is not None and cmd.notify_user_ids == [owner.id]
    clip = finish(db, cmd)
    assert clips.notify_command(db, cmd, MockProvider(db), NOW) == 1
    link = texts(db, owner.phone_e164)[-1]
    assert link.startswith("Moment 1 : http") and f"/clips/{clip.id}?exp=" in link
    assert (say(db, owner, "1") or "").startswith("Moment 1 : http")  # now ready: link at once
    assert say(db, owner, str(len(reported.moments) + 1)) == t("wa.no_moment", rank=len(reported.moments) + 1)


def test_manager_needs_clip_access_and_staff_can_only_quick_log(
    db: Session, world: World, reported: m.DailyReport
) -> None:
    assert say(db, world.manager, "1") == t("wa.not_allowed")
    assert say(db, world.manager, "photo") == t("wa.not_allowed")
    acc = db.get(m.Account, world.acc_a.id)
    assert acc is not None
    acc.clip_access_for_managers = True
    assert say(db, world.manager, "1") == t("wa.clip_preparing")
    assert say(db, world.staff, "faux") == t("wa.not_allowed")
    assert (say(db, world.staff, "+1000", now=at(10)) or "").startswith(f"✓ {money(1000)} F")


def test_photo_queues_snapshot_audits_and_times_out_after_2_min(
    db: Session, world: World, reported: m.DailyReport
) -> None:
    owner = world.owner_a
    assert say(db, owner, "photo") == t("wa.photo_wait")
    snap = db.scalars(select(m.EdgeCommand).where(m.EdgeCommand.type == m.CommandType.snapshot)).one()
    assert snap.params == {"camera": "counter"} and snap.requested_by == owner.id
    assert db.scalars(select(m.AuditLog).where(m.AuditLog.action == "snapshot.request")).one()
    assert clips.notify_stale(db, MockProvider(db), NOW + timedelta(seconds=60)) == 0
    snap.created_at = NOW
    assert clips.notify_stale(db, MockProvider(db), NOW + timedelta(minutes=2)) == 1
    assert texts(db, owner.phone_e164)[-1] == "Kit injoignable."


def test_photo_done_sends_the_image(db: Session, world: World, reported: m.DailyReport) -> None:
    say(db, world.owner_a, "photo")
    snap = db.scalars(select(m.EdgeCommand).where(m.EdgeCommand.type == m.CommandType.snapshot)).one()
    finish(db, snap)
    clips.notify_command(db, snap, MockProvider(db), NOW)
    media = db.scalars(select(m.MockMessage).where(m.MockMessage.kind == "media")).one()
    assert (
        media.url and "X-Amz-Signature" in media.url and media.body and media.body.startswith("A1 – photo de")
    )


def test_quick_log_and_cancel_within_10_min_AC_F3_4(
    db: Session, world: World, reported: m.DailyReport
) -> None:
    owner = world.owner_a
    # the day already has 40 wave sales of 2 500 F = 100 000 F
    assert say(db, owner, "+2500", now=at(20, 0)) == f"✓ {money(2500)} F – total du jour : {money(102_500)} F"
    assert (say(db, owner, "+ 1 000", now=at(20, 1)) or "").endswith(f"{money(103_500)} F")
    sales = db.scalars(select(m.Sale).where(m.Sale.source == m.SaleSource.quick_log)).all()
    assert {(x.amount_xof, x.entered_by, x.local_date) for x in sales} == {
        (2500, owner.id, D),
        (1000, owner.id, D),
    }
    assert (
        say(db, owner, "annuler", now=at(20, 5))
        == f"Annulé : {money(1000)} F – total du jour : {money(102_500)} F"
    )
    assert say(db, owner, "annuler", now=at(20, 30)) == t("wa.cancel_none")  # the 20:00 one is too old


def test_cash_prompt_reply_creates_then_replaces_declaration_AC_F3_5(
    db: Session, world: World, reported: m.DailyReport
) -> None:
    owner, shop = world.owner_a, world.shop_a1
    assert say(db, owner, "85000") == t("wa.unknown")  # no prompt pending
    open_cash_prompt(db, owner, shop, D, at(20, 30))
    assert say(db, owner, "85 000 F", now=at(20, 40)) == f"✓ Espèces déclarées ce soir : {money(85_000)} F."
    open_cash_prompt(db, owner, shop, D, at(20, 45))
    say(db, owner, "90000", now=at(20, 50))
    decl = db.scalars(select(m.Sale).where(m.Sale.source == m.SaleSource.cash_declaration)).all()
    assert sorted((x.amount_xof, x.voided_at is None) for x in decl) == [(85000, False), (90000, True)]
    open_cash_prompt(db, owner, shop, D, at(20, 30))
    assert say(db, owner, "70000", now=at(23, 31)) == t("wa.unknown")  # reply window is 3 h


def test_faux_asks_then_records_visitors_correction_AC_F9_1(
    db: Session, world: World, reported: m.DailyReport
) -> None:
    owner = world.owner_a
    assert say(db, owner, "faux") == "Combien d'entrées environ aujourd'hui ?"
    assert say(db, owner, "55") == "Merci, c'est noté : environ 55 entrées."
    corr = db.scalars(select(m.DayCorrection)).one()
    assert (corr.metric, corr.reported_value, corr.corrected_value, corr.local_date) == (
        "visitors_in",
        40,
        55,
        D,
    )
    assert db.scalars(select(m.AuditLog).where(m.AuditLog.action == "correction.create")).one()
    assert say(db, owner, "56") == t("wa.unknown")  # the question was answered


def test_stop_and_start_pause_the_owner_report(db: Session, world: World, reported: m.DailyReport) -> None:
    assert say(db, world.manager, "stop") == t("wa.not_allowed")
    assert say(db, world.owner_a, "STOP") == t("wa.stop_ok")
    assert world.owner_a.reports_paused
    assert world.owner_a.id not in [u.id for u in service.recipients(db, world.shop_a1)]
    assert say(db, world.owner_a, "start") == t("wa.start_ok")
    assert world.owner_a.id in [u.id for u in service.recipients(db, world.shop_a1)]


# ---------- clip API ----------
def test_clip_link_requires_login_is_audited_and_expires_after_24h_AC_F5_3(
    client: TestClient, db: Session, world: World, reported: m.DailyReport
) -> None:
    cmd = db.get(m.EdgeCommand, uuid.UUID(reported.moments[0]["clip_command_id"]))
    assert cmd is not None
    clip = finish(db, cmd, datetime.now(UTC))
    db.commit()
    link = clips.clip_link(clip.id, datetime.now(UTC))
    query = link.split("?", 1)[1]
    assert client.get(f"/v1/clips/{clip.id}?{query}").status_code == 401
    r = client.get(f"/v1/clips/{clip.id}?{query}", headers=bearer(db, world.owner_a))
    assert r.status_code == 200 and "X-Amz-Signature" in r.json()["url"] and r.json()["expires_in_s"] == 900
    assert db.scalars(select(m.AuditLog).where(m.AuditLog.action == "clip.view")).one().target_id == clip.id
    old = clips.clip_link(clip.id, datetime.now(UTC) - timedelta(hours=25)).split("?", 1)[1]
    assert client.get(f"/v1/clips/{clip.id}?{old}", headers=bearer(db, world.owner_a)).status_code == 410
    assert client.get(f"/v1/clips/{clip.id}", headers=bearer(db, world.owner_b)).status_code == 404


def test_moment_clip_endpoint_queues_then_returns_ready_AC_F5_2(
    client: TestClient, db: Session, world: World, reported: m.DailyReport
) -> None:
    h = bearer(db, world.owner_a)
    r = client.post(f"/v1/moments/{reported.id}/1/clip", headers=h)
    assert r.status_code == 202 and r.json()["status"] == "queued"
    cmd = db.get(m.EdgeCommand, uuid.UUID(r.json()["command_id"]))
    assert cmd is not None
    db.refresh(cmd)
    finish(db, cmd, datetime.now(UTC))
    db.commit()
    r = client.post(f"/v1/moments/{reported.id}/1/clip", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "ready"
    assert client.post(f"/v1/moments/{reported.id}/9/clip", headers=h).status_code == 404


def test_moment_older_than_edge_buffer_is_unavailable_AC_F5_4(db: Session, world: World) -> None:
    shop, _, _ = setup_shop(db, world)
    report = m.DailyReport(shop_id=shop.id, local_date=date(2026, 11, 1), verdict=m.VerdictCode.normal,
                           sent_at=at(21), moments=[{"rank": 1, "kind": "wait", "event_id": str(uuid7()),
                           "camera": "counter", "started_at": "2026-11-01T10:00:00+00:00",
                           "clip_start": "2026-11-01T09:59:55+00:00", "clip_end": "2026-11-01T10:00:15+00:00",
                           "duration_s": 200}])  # fmt: skip
    db.add(report)
    db.flush()
    assert clips.request_moment_clip(db, report, 1, world.owner_a, NOW).status == "unavailable"


def test_edge_result_notifies_whatsapp_requesters(client: TestClient, db: Session, world: World) -> None:
    kit = db.get(m.Kit, world.kit_a1.id)
    assert kit is not None
    kit.claim_token_hash = hash_token("claim")
    world.shop_a1.status = m.ShopStatus.active
    db.commit()
    token = client.post("/v1/edge/register", json={"serial": kit.serial, "claim_token": "claim"}).json()
    dev = {"Authorization": f"Bearer {token['device_token']}"}
    snap = clips.request_snapshot(db, world.shop_a1, world.owner_a, datetime.now(UTC))
    assert snap is not None
    db.commit()
    r = client.post(f"/v1/edge/commands/{snap.id}/result", headers=dev,
                    json={"status": "done", "result": {"size_bytes": 1000}})  # fmt: skip
    assert r.status_code == 204
    db.expire_all()
    media = db.scalars(select(m.MockMessage).where(m.MockMessage.to_phone == world.owner_a.phone_e164)).one()
    assert media.kind == "media"
    assert db.get(m.EdgeCommand, snap.id).notified_at is not None  # type: ignore[union-attr]


def test_local_time_caption_uses_shop_timezone() -> None:
    assert datetime(2026, 11, 20, 21, 0, tzinfo=UTC).astimezone(ZoneInfo("Africa/Dakar")).hour == 21


def test_cloud_provider_builds_graph_api_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from seetlu.messaging.provider import WhatsAppCloudProvider

    st = get_settings()
    monkeypatch.setattr(st, "wa_phone_number_id", "123")
    monkeypatch.setattr(st, "wa_access_token", "tok")
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"messages": [{"id": f"wamid.{len(seen)}"}]})

    p = WhatsAppCloudProvider(httpx.Client(transport=httpx.MockTransport(answer)))
    assert p.send_template("+221770000001", "daily_report_fr", "fr", ["A", "B"]) == "wamid.1"
    p.send_text("+221770000001", "hello")
    p.send_media_link("+221770000001", "https://x/y.jpg", "cap")
    bodies = [json.loads(r.content) for r in seen]
    assert str(seen[0].url) == "https://graph.facebook.com/v21.0/123/messages"
    assert seen[0].headers["authorization"] == "Bearer tok"
    assert bodies[0]["to"] == "221770000001" and bodies[0]["template"]["language"] == {"code": "fr"}
    assert bodies[0]["template"]["components"][0]["parameters"][1] == {"type": "text", "text": "B"}
    assert bodies[1]["text"]["body"] == "hello" and bodies[2]["image"] == {
        "link": "https://x/y.jpg",
        "caption": "cap",
    }


def test_mock_inbox_reply_runs_the_handler(db: Session, world: World, migrated_engine: Any) -> None:
    from sqlalchemy.orm import sessionmaker

    from seetlu.messaging import mock_inbox

    app = mock_inbox.create_app()
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)

    def _db() -> Any:
        with factory() as s:
            yield s

    app.dependency_overrides[mock_inbox.get_db] = _db
    with TestClient(app) as c:
        r = c.post("/inbound", json={"from_phone": world.owner_a.phone_e164, "text": "aide"})
        assert r.json() == {"reply": t("wa.help")}
        page = c.get("/")
        assert page.status_code == 200 and "Tapez" not in page.text and "1, 2 ou 3" in page.text
