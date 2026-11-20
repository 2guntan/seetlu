"""`python -m seetlu.seed.kit_serial <shop id | kit serial>` → the serial of the shop's kit (make sim-day)."""

import sys
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from seetlu.db import models as m
from seetlu.db.session import session_factory


def kit_serial(s: Session, shop: str) -> str | None:
    try:
        shop_id = uuid.UUID(shop)
    except ValueError:
        kit = s.scalars(select(m.Kit).where(m.Kit.serial == shop)).first()
        return kit.serial if kit else None
    kit = s.scalars(select(m.Kit).where(m.Kit.shop_id == shop_id).order_by(m.Kit.created_at)).first()
    return kit.serial if kit else None


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m seetlu.seed.kit_serial <shop id | kit serial>")
    with session_factory()() as s:
        serial = kit_serial(s, sys.argv[1])
    if serial is None:
        raise SystemExit(f"no kit for shop {sys.argv[1]!r} (`make seed` prints the shop ids)")
    print(serial)


if __name__ == "__main__":
    main()
