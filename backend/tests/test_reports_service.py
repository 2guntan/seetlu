"""Report service against a real database: load, compute, persist, clips, send, recompute (docs/06)."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from seetlu.core.ids import uuid7
from seetlu.db import models as m
from seetlu.messaging.provider import MockProvider
from seetlu.reports import service
from tests.conftest import World

TZ = ZoneInfo("Africa/Dakar")
D = date(2026, 11, 20)  # Friday; HOURS in conftest: 08:00-21:00


def at(hh: int, mm: int = 0, d: date = D) -> datetime:
    return datetime.combine(d, time(hh, mm), tzinfo=TZ)


def setup_shop(s: Session, w: World) -> tuple[m.Shop, m.Camera, m.Camera]:
    shop = w.shop_a1
    shop.status = m.ShopStatus.active
    w.manager.receives_report = True
    door = m.Camera(
        kit_id=w.kit_a1.id, role=m.CameraRole.door, name="door", rtsp_main_path="/a", rtsp_sub_path="/b"
    )
    counter = m.Camera(
        kit_id=w.kit_a1.id, role=m.CameraRole.counter, name="counter", rtsp_main_path="/a", rtsp_sub_path="/b"
    )
    s.add_all([door, counter])
    s.flush()
    return shop, door, counter


def fill_day(
    s: Session,
    w: World,
    door: m.Camera,
    counter: m.Camera,
    d: date = D,
    visitors: int = 40,
    skip: frozenset[int] = frozenset(),
) -> None:
    t = at(0, d=d)
    while t < at(0, d=d) + timedelta(days=1):
        if t.hour not in skip:
            s.add(m.Heartbeat(kit_id=w.kit_a1.id, at=t, fps={"door": 5.0, "counter": 5.0}))
        t += timedelta(minutes=5)
    for i in range(visitors):
        start = at(9, d=d) + timedelta(minutes=15 * i)
        s.add(m.Event(id=uuid7(), started_at=start, shop_id=w.shop_a1.id, kit_id=w.kit_a1.id,
                      camera_id=door.id, type=m.EventType.entry))  # fmt: skip
        s.add(m.Event(id=uuid7(), started_at=start + timedelta(minutes=1), ended_at=start + timedelta(minutes=2),
                      shop_id=w.shop_a1.id, kit_id=w.kit_a1.id, camera_id=counter.id, type=m.EventType.service))  # fmt: skip
        s.add(m.Sale(shop_id=w.shop_a1.id, source=m.SaleSource.wave, amount_xof=2_500, occurred_at=start,
                     local_date=d))  # fmt: skip
    s.flush()


def test_compute_and_send_persists_and_sends_to_owner_and_opted_in_manager_AC_F4_1(
    db: Session, world: World
) -> None:
    shop, door, counter = setup_shop(db, world)
    fill_day(db, world, door, counter)
    db.add(m.Event(id=uuid7(), started_at=at(23, 10), shop_id=shop.id, kit_id=world.kit_a1.id,
                   camera_id=door.id, type=m.EventType.after_hours_motion))  # fmt: skip
    db.commit()
    now = at(21, 0).astimezone(UTC)
    c = service.compute_and_send(db, shop.id, D, now=now, provider=MockProvider(db))
    row = db.scalars(select(m.DailyReport).where(m.DailyReport.shop_id == shop.id)).one()
    assert (row.visitors_in, row.served, row.sales_xof) == (40, 40, 100_000)
    assert row.verdict == m.VerdictCode.learning  # AC-F4-4: no history yet
    assert row.sent_at is not None and row.message_id
    msgs = db.scalars(select(m.MockMessage).order_by(m.MockMessage.to_phone)).all()
    assert sorted(x.to_phone for x in msgs) == sorted([world.owner_a.phone_e164, world.manager.phone_e164])
    assert all(x.template == "daily_report_fr" and len(x.params) == 12 for x in msgs)
    assert msgs[0].params[0] == "A1"
    # AC-F5-1/AC-F5-2: after-hours moment first, a clip command queued for it
    assert row.moments[0]["kind"] == "after_hours_motion"
    cmds = db.scalars(select(m.EdgeCommand).where(m.EdgeCommand.type == m.CommandType.clip)).all()
    assert len(cmds) == len(row.moments) >= 1
    assert all(mo["clip_command_id"] for mo in row.moments)
    assert c.report.metrics.missing_hours == []


def test_second_run_does_not_resend_or_requeue(db: Session, world: World) -> None:
    shop, door, counter = setup_shop(db, world)
    fill_day(db, world, door, counter)
    db.add(m.Event(id=uuid7(), started_at=at(23, 10), shop_id=shop.id, kit_id=world.kit_a1.id,
                   camera_id=door.id, type=m.EventType.after_hours_motion))  # fmt: skip
    db.commit()
    now = at(21, 0).astimezone(UTC)
    service.compute_and_send(db, shop.id, D, now=now, provider=MockProvider(db))
    service.compute_and_send(db, shop.id, D, now=now + timedelta(minutes=1), provider=MockProvider(db))
    assert len(db.scalars(select(m.MockMessage)).all()) == 2
    assert len(db.scalars(select(m.EdgeCommand)).all()) == 1


def test_missing_hours_reported_and_incomplete_over_25_percent_AC_F4_5(db: Session, world: World) -> None:
    shop, door, counter = setup_shop(db, world)
    fill_day(db, world, door, counter, skip=frozenset({14, 15}))
    db.commit()
    c = service.compute(db, shop, D, now=at(21, 0))
    assert c.row.missing_hours == [14, 15]
    assert c.row.verdict == m.VerdictCode.learning
    other = date(2026, 11, 19)
    fill_day(db, world, door, counter, d=other, skip=frozenset(range(8, 13)))
    assert service.compute(db, shop, other, now=at(21, 0, other)).row.verdict == m.VerdictCode.incomplete_data


def test_baseline_from_history_gives_normal_after_14_valid_days_AC_F4_4(db: Session, world: World) -> None:
    shop, door, counter = setup_shop(db, world)
    for back in range(14, 0, -1):
        d = D - timedelta(days=back)
        if d.weekday() == 6:
            continue  # closed on Sunday
        fill_day(db, world, door, counter, d=d)
        service.compute(db, shop, d, now=at(21, 0, d))
    n_valid = len([p for p in service.history(db, shop.id, D) if p.valid])
    fill_day(db, world, door, counter)
    row = service.compute(db, shop, D, now=at(21, 0)).row
    assert n_valid == 12 and row.verdict == m.VerdictCode.learning  # only 12 open days in the last 14
    for back in range(21, 14, -1):
        d = D - timedelta(days=back)
        if d.weekday() != 6:
            fill_day(db, world, door, counter, d=d)
            service.compute(db, shop, d, now=at(21, 0, d))
    row = service.compute(db, shop, D, now=at(21, 0)).row
    assert row.verdict == m.VerdictCode.normal
    assert row.vs_last_week is not None and row.vs_last_week["visitors_in"]["pct"] == 0


def test_recompute_on_late_data_updates_without_resending(db: Session, world: World) -> None:
    shop, door, counter = setup_shop(db, world)
    fill_day(db, world, door, counter)
    db.commit()
    service.compute_and_send(db, shop.id, D, now=at(21, 0), provider=MockProvider(db))
    late = at(20, 30)
    db.add(m.Event(id=uuid7(), started_at=late, shop_id=shop.id, kit_id=world.kit_a1.id,
                   camera_id=door.id, type=m.EventType.entry))  # fmt: skip
    db.commit()
    assert service.late_dates(db, shop, [late]) == [D]
    c = service.recompute(db, shop.id, D, now=at(21, 30))
    assert c is not None and c.row.visitors_in == 41
    assert len(db.scalars(select(m.MockMessage)).all()) == 2


def test_due_reports_after_local_report_time_only(db: Session, world: World) -> None:
    shop, _, _ = setup_shop(db, world)
    db.commit()
    assert service.due_reports(db, at(20, 59)) == []
    assert service.due_reports(db, at(21, 0)) == [(shop.id, D)]
    service.compute_and_send(db, shop.id, D, now=at(21, 0), provider=MockProvider(db))
    assert service.due_reports(db, at(21, 5)) == []


def test_celery_beat_schedules_due_reports_every_minute() -> None:
    from seetlu.workers import tasks
    from seetlu.workers.celery_app import celery_app

    assert celery_app.conf.beat_schedule["reports-due"]["schedule"] == 60.0
    assert tasks.schedule_due_reports.name == "seetlu.reports.schedule_due"
