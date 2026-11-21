"""`make e2e` helpers (docs/10 End-to-end): reset one shop day, then compute the report, send it to the
mock inbox and compare the rendered message with the golden file.

    python -m seetlu.reports.e2e prepare <shop id | kit serial> YYYY-MM-DD
    python -m seetlu.reports.e2e check <shop id | kit serial> YYYY-MM-DD <golden file>
    python -m seetlu.reports.e2e reply <shop id | kit serial> YYYY-MM-DD   (owner replies « 1 »)
"""

import difflib
import sys
import time
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from seetlu.db import models as m
from seetlu.db.session import session_factory
from seetlu.messaging.mock_inbox import receive
from seetlu.reports import service
from seetlu.reports.__main__ import render_last_message, resolve_shop


def prepare(s: Session, shop: m.Shop, d: date) -> None:
    """Remove what earlier runs left for this shop day so the scenario starts from a clean day."""
    a, b = service.day_bounds(d, ZoneInfo(shop.timezone))
    kit_ids = list(s.scalars(select(m.Kit.id).where(m.Kit.shop_id == shop.id)))
    s.execute(
        delete(m.Event).where(m.Event.shop_id == shop.id, m.Event.started_at >= a, m.Event.started_at < b)
    )
    s.execute(
        delete(m.Heartbeat).where(m.Heartbeat.kit_id.in_(kit_ids), m.Heartbeat.at >= a, m.Heartbeat.at < b)
    )
    s.execute(delete(m.DailyReport).where(m.DailyReport.shop_id == shop.id, m.DailyReport.local_date == d))
    phones = [u.phone_e164 for u in service.recipients(s, shop)]
    s.execute(delete(m.MockMessage).where(m.MockMessage.to_phone.in_(phones)))
    s.commit()


def check(s: Session, shop: m.Shop, d: date, golden: Path) -> bool:
    c = service.compute_and_send(s, shop.id, d, force=True)
    text = render_last_message(s, shop)
    print(f"e2e: {shop.name} {d} verdict={c.row.verdict.value}; WhatsApp message in the mock inbox:\n")
    print(text)
    expected = golden.read_text(encoding="utf-8")
    if text.strip() == expected.strip():
        print(f"\ne2e: OK, matches {golden}")
        return True
    diff = difflib.unified_diff(expected.splitlines(), text.splitlines(), "golden", "actual", lineterm="")
    print("\ne2e: MISMATCH\n" + "\n".join(diff))
    return False


def reply_1(s: Session, shop: m.Shop, timeout_s: float = 120.0) -> bool:
    """The owner answers « 1 »; the edge agent cuts and uploads the clip; the link arrives (docs/11 M7)."""
    owner = service.recipients(s, shop)[0]
    first = receive(s, owner.phone_e164, "1")
    print(f"e2e: {owner.name} → « 1 »\ne2e: Seetlu → {first}")
    if first and "/clips/" in first:
        return True
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        time.sleep(2)
        s.expire_all()
        last = s.scalars(
            select(m.MockMessage)
            .where(m.MockMessage.to_phone == owner.phone_e164)
            .order_by(m.MockMessage.id.desc())
        ).first()
        if last is not None and last.body and "/clips/" in last.body:
            print(f"e2e: Seetlu → {last.body}\ne2e: OK, reply 1 returned a clip link")
            return True
    print("e2e: no clip link within the timeout (is the dev agent running? `make logs`)")
    return False


def main() -> None:
    if len(sys.argv) < 4 or sys.argv[1] not in ("prepare", "check", "reply"):
        raise SystemExit(__doc__)
    with session_factory()() as s:
        shop = resolve_shop(s, sys.argv[2])
        if shop is None:
            raise SystemExit(f"no shop {sys.argv[2]!r}")
        d = date.fromisoformat(sys.argv[3])
        if sys.argv[1] == "prepare":
            prepare(s, shop, d)
        elif sys.argv[1] == "reply":
            if not reply_1(s, shop):
                raise SystemExit(1)
        elif not check(s, shop, d, Path(sys.argv[4])):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
