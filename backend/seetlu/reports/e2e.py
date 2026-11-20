"""`make e2e` helpers (docs/10 End-to-end): reset one shop day, then compute the report, send it to the
mock inbox and compare the rendered message with the golden file.

    python -m seetlu.reports.e2e prepare <shop id | kit serial> YYYY-MM-DD
    python -m seetlu.reports.e2e check <shop id | kit serial> YYYY-MM-DD <golden file>
"""

import difflib
import sys
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from seetlu.db import models as m
from seetlu.db.session import session_factory
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


def main() -> None:
    if len(sys.argv) < 4 or sys.argv[1] not in ("prepare", "check"):
        raise SystemExit(__doc__)
    with session_factory()() as s:
        shop = resolve_shop(s, sys.argv[2])
        if shop is None:
            raise SystemExit(f"no shop {sys.argv[2]!r}")
        d = date.fromisoformat(sys.argv[3])
        if sys.argv[1] == "prepare":
            prepare(s, shop, d)
        elif not check(s, shop, d, Path(sys.argv[4])):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
