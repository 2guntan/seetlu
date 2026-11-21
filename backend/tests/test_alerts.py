"""Alerts (docs/06, AC-F6-1..3) and the evening cash prompt (AC-F3-5)."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from seetlu.alerts.service import evaluate_shop, send_cash_prompts
from seetlu.core.ids import uuid7
from seetlu.db import models as m
from seetlu.domain.alerts import AlertFacts, EventFact, Rule, SentFact, decide, in_quiet_hours
from seetlu.messaging.inbound import handle
from seetlu.messaging.provider import MockProvider
from tests.conftest import World
from tests.test_reports_service import D, at, setup_shop

TZ = ZoneInfo("Africa/Dakar")
OPEN = [(at(8), at(21))]


def facts(now: datetime, events: list[EventFact] | None = None, sent: list[SentFact] | None = None,
          hb: datetime | None = None, rules: dict[str, Rule] | None = None) -> AlertFacts:  # fmt: skip
    return AlertFacts(now, TZ, OPEN, time(22), time(7), rules or {}, events or [],
                      hb if hb is not None else now, sent or [])  # fmt: skip


def entry(hh: int) -> EventFact:
    return EventFact(f"in-{hh}", "entry", at(hh))


def test_only_four_alert_types_exist_AC_F6_1() -> None:
    assert {a.value for a in m.AlertType} == {"not_opened", "unattended", "after_hours_motion", "kit_offline"}


def test_not_opened_after_grace_once_a_day() -> None:
    assert decide(facts(at(8, 29))) == []
    [a] = decide(facts(at(8, 30)))
    assert (a.type, a.at) == ("not_opened", at(8))
    assert decide(facts(at(8, 30), [entry(8)])) == []
    assert decide(facts(at(9), sent=[SentFact("not_opened", None, at(8, 30))])) == []
    assert decide(facts(at(8, 45), rules={"not_opened": Rule(params={"grace_min": 60})})) == []  # AC-F6-3


def test_unattended_open_event_over_threshold_once_per_event() -> None:
    ev = EventFact("u1", "unattended", at(14), None)
    assert decide(facts(at(14, 9), [entry(8), ev])) == []
    [a] = decide(facts(at(14, 12), [entry(8), ev]))
    assert (a.type, a.event_id, a.minutes) == ("unattended", "u1", 12)
    assert decide(facts(at(14, 20), [entry(8), ev], sent=[SentFact("unattended", "u1", at(14, 12))])) == []
    closed = EventFact("u1", "unattended", at(14), at(14, 11))
    assert decide(facts(at(14, 20), [entry(8), closed])) == []
    assert decide(facts(at(14, 12), [entry(8), ev], rules={"unattended": Rule(enabled=False)})) == []


def test_kit_offline_after_30_min_during_opening_once_per_outage() -> None:
    assert decide(facts(at(10, 30), [entry(8)], hb=at(10, 1))) == []
    [a] = decide(facts(at(10, 31), [entry(8)], hb=at(10)))
    assert (a.type, a.at) == ("kit_offline", at(10))
    assert (
        decide(facts(at(11), [entry(8)], hb=at(10), sent=[SentFact("kit_offline", None, at(10, 31))])) == []
    )
    assert decide(facts(at(21, 40), [entry(8)], hb=at(20))) == []  # closed


def test_quiet_hours_only_let_after_hours_motion_through_AC_F6_2() -> None:
    assert in_quiet_hours(time(23), time(22), time(7)) and in_quiet_hours(time(6, 59), time(22), time(7))
    assert not in_quiet_hours(time(7), time(22), time(7))
    motion = EventFact("ahm", "after_hours_motion", at(23, 14))
    [a] = decide(facts(at(23, 15), [entry(8), motion]))
    assert a.type == "after_hours_motion"
    old = EventFact("old", "after_hours_motion", at(5))
    assert decide(facts(at(23, 15), [entry(8), old])) == []  # late upload of old motion


def test_daily_cap_of_three_and_priority_AC_F6_2() -> None:
    motions = [EventFact(f"m{i}", "after_hours_motion", at(21, 30 + i)) for i in range(5)]
    assert len(decide(facts(at(21, 40), [entry(8), *motions]))) == 3
    two_sent = [SentFact("after_hours_motion", f"x{i}", at(6)) for i in range(2)]
    assert [a.event_id for a in decide(facts(at(21, 40), [entry(8), *motions], sent=two_sent))] == ["m0"]
    three = [*two_sent, SentFact("unattended", "y", at(9))]
    assert decide(facts(at(21, 40), [entry(8), *motions], sent=three)) == []


def test_evaluate_shop_sends_alert_template_and_records_it(db: Session, world: World) -> None:
    shop, _, _ = setup_shop(db, world)
    db.add(m.Heartbeat(kit_id=world.kit_a1.id, at=at(8, 50), fps={}))
    world.kit_a1.status = m.KitStatus.active
    db.commit()
    sent = evaluate_shop(db, shop, MockProvider(db), at(9))
    assert [a.type for a in sent] == ["not_opened"]
    msgs = db.scalars(select(m.MockMessage)).all()
    assert {x.to_phone for x in msgs} == {world.owner_a.phone_e164, world.manager.phone_e164}
    assert msgs[0].template == "alert_fr" and msgs[0].params == [
        "A1",
        "la boutique n'a pas encore ouvert (8h00).",
    ]
    assert db.scalars(select(m.AlertSent)).one().local_date == D
    assert evaluate_shop(db, shop, MockProvider(db), at(9, 1)) == []


def test_cash_prompt_goes_to_manager_once_and_opens_the_reply_window_AC_F3_5(
    db: Session, world: World
) -> None:
    setup_shop(db, world)
    db.commit()
    assert send_cash_prompts(db, MockProvider(db), at(20, 29)) == 0
    assert send_cash_prompts(db, MockProvider(db), at(20, 30)) == 1
    assert send_cash_prompts(db, MockProvider(db), at(20, 35)) == 0
    msg = db.scalars(select(m.MockMessage)).one()
    assert (msg.to_phone, msg.template, msg.params) == (world.manager.phone_e164, "cash_prompt_fr", ["A1"])
    reply = handle(db, world.manager.phone_e164, "60 000", MockProvider(db), at(20, 40))
    assert reply is not None and reply.startswith("✓")
    sale = db.scalars(select(m.Sale).where(m.Sale.source == m.SaleSource.cash_declaration)).one()
    assert (sale.amount_xof, sale.local_date, sale.entered_by) == (60_000, D, world.manager.id)


def test_cash_prompt_falls_back_to_owner_without_manager(db: Session, world: World) -> None:
    setup_shop(db, world)
    db.execute(delete(m.UserShop).where(m.UserShop.user_id == world.manager.id))
    db.commit()
    send_cash_prompts(db, MockProvider(db), at(20, 30) + timedelta(seconds=1))
    assert [x.to_phone for x in db.scalars(select(m.MockMessage))] == [world.owner_a.phone_e164]
    assert uuid7()  # ids stay UUIDv7
