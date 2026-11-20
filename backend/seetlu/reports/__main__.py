"""`python -m seetlu.reports <shop id | kit serial> YYYY-MM-DD` (make report): compute the shop day's
report, send it to the mock WhatsApp inbox and print the rendered message."""

import sys
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from seetlu.db import models as m
from seetlu.db.session import session_factory
from seetlu.i18n import render_template
from seetlu.reports import service


def resolve_shop(s: Session, ref: str) -> m.Shop | None:
    try:
        return s.get(m.Shop, uuid.UUID(ref))
    except ValueError:
        kit = s.scalars(select(m.Kit).where(m.Kit.serial == ref)).first()
        return s.get(m.Shop, kit.shop_id) if kit and kit.shop_id else None


def render_last_message(s: Session, shop: m.Shop) -> str:
    to = service.recipients(s, shop)[0].phone_e164
    msg = s.scalars(
        select(m.MockMessage).where(m.MockMessage.to_phone == to).order_by(m.MockMessage.created_at.desc())
    ).first()
    assert msg is not None and msg.template is not None
    return render_template(msg.template.removesuffix(f"_{msg.lang}"), msg.params, msg.lang or "fr")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m seetlu.reports <shop id | kit serial> YYYY-MM-DD")
    with session_factory()() as s:
        shop = resolve_shop(s, sys.argv[1])
        if shop is None:
            raise SystemExit(f"no shop {sys.argv[1]!r} (`make seed` prints the shop ids)")
        c = service.compute_and_send(s, shop.id, date.fromisoformat(sys.argv[2]), force=True)
        print(f"report: {shop.name} {c.row.local_date} verdict={c.row.verdict.value} → mock inbox")
        print(render_last_message(s, shop))


if __name__ == "__main__":
    main()
