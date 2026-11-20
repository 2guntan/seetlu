"""Golden normal-day report (docs/10 End-to-end, docs/11 M6): the events the real edge agent produces
for the `normal-day` scenario (exported in tests/fixtures), on top of the 30-day demo history, render
exactly tests/golden/normal-day-report.fr.txt. `make e2e` checks the same file through the live stack."""

import json
import os
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from seetlu.db import models as m
from seetlu.messaging.provider import MockProvider
from seetlu.reports import service
from seetlu.reports.__main__ import render_last_message
from seetlu.seed.demo import seed_demo
from seetlu.seed.history import seed_history

HERE = Path(__file__).parent
GOLDEN = HERE / "golden" / "normal-day-report.fr.txt"
ANCHOR = date(2026, 11, 20)


def load_scenario(s: Session, shop: m.Shop) -> None:
    kit = s.scalars(select(m.Kit).where(m.Kit.shop_id == shop.id)).one()
    cams = {c.name: c.id for c in s.scalars(select(m.Camera).where(m.Camera.kit_id == kit.id))}
    rows = json.loads((HERE / "fixtures" / "normal-day-events.json").read_text())["events"]
    for ev in rows:
        s.execute(insert(m.Event).values(
            id=ev["id"], started_at=ev["started_at"], ended_at=ev["ended_at"], shop_id=shop.id, kit_id=kit.id,
            camera_id=cams[ev["camera"]], type=m.EventType(ev["type"]), is_staff=ev["is_staff"],
            confidence=ev["confidence"], frigate_event_ids=ev["frigate_event_ids"], meta=ev["meta"],
        ).on_conflict_do_nothing())  # fmt: skip
    t = datetime.combine(ANCHOR, time(0), tzinfo=ZoneInfo(shop.timezone))
    for i in range(288):  # what the agent sends: one heartbeat every 5 min, both cameras at 5 fps
        at = t + timedelta(minutes=5 * i)
        s.execute(insert(m.Heartbeat).values(kit_id=kit.id, at=at, fps={"door": 5.0, "counter": 5.0})
                  .on_conflict_do_nothing())  # fmt: skip
    s.commit()


def test_normal_day_produces_the_golden_report_AC_F4_2(migrated_engine: Engine, db: Session) -> None:
    """`db` truncates every table afterwards."""
    with Session(migrated_engine, expire_on_commit=False) as s:
        result = seed_demo(s, claim_token="tok")
        seed_history(s, result.shop_ids, ANCHOR)
        shop = s.get(m.Shop, result.shop_ids[0])
        assert shop is not None
        load_scenario(s, shop)
        now = service.report_time_of(shop, ANCHOR).astimezone(UTC)
        c = service.compute_and_send(s, shop.id, ANCHOR, now=now, provider=MockProvider(s), force=True)
        text = render_last_message(s, shop)
        if os.environ.get("UPDATE_GOLDEN"):
            GOLDEN.write_text(text + "\n", encoding="utf-8")
        assert c.row.verdict == m.VerdictCode.normal
        assert (c.row.visitors_in, c.row.served) == (140, 108)
        assert text.strip() == GOLDEN.read_text(encoding="utf-8").strip()
