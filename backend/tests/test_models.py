"""M1: SQLAlchemy models match the migrated schema, and basic constraints behave."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import REAL, BigInteger, Engine, Float, Integer, Numeric
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from seetlu.core.ids import uuid7
from seetlu.db import models as m

HOURS = {d: [["08:00", "21:00"]] for d in ("mon", "tue", "wed", "thu", "fri", "sat")} | {"sun": []}


def _diff(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(
            conn,
            opts={"compare_type": True, "compare_server_default": False, "include_name": _include},
        )
        return list(compare_metadata(ctx, m.Base.metadata))


def _include(name: str | None, type_: str, _parent: Any) -> bool:
    return not (type_ == "table" and name == "alembic_version")


def test_m1_models_match_migrated_schema(migrated_engine: Engine) -> None:
    assert _diff(migrated_engine) == []


def test_m1_money_columns_are_integers() -> None:
    """CLAUDE.md: money is integer XOF; never floats."""
    for table in m.Base.metadata.tables.values():
        for col in table.columns:
            if col.name.endswith("_xof"):
                assert not isinstance(col.type, Float | REAL), f"{table.name}.{col.name} is a float"
                if col.name != "rps_xof":  # a ratio (money / served), numeric(12,2) per 03-data-model
                    assert isinstance(col.type, BigInteger | Integer), f"{table.name}.{col.name}"
                else:
                    assert isinstance(col.type, Numeric) and col.type.asdecimal


def _shop(s: Session) -> tuple[m.Account, m.Shop, m.Kit]:
    acc = m.Account(name="Test")
    s.add(acc)
    s.flush()
    shop = m.Shop(account_id=acc.id, name="Boutique", category="boutique", opening_hours=HOURS)
    s.add(shop)
    s.flush()
    kit = m.Kit(serial=f"K-{uuid7().hex[:8]}", claim_token_hash="x", shop_id=shop.id)
    s.add(kit)
    s.flush()
    return acc, shop, kit


def test_m1_defaults_and_generated_duration(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as s:
        _, shop, kit = _shop(s)
        t0 = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
        ev = m.Event(
            id=uuid7(),
            shop_id=shop.id,
            kit_id=kit.id,
            type=m.EventType.service,
            started_at=t0,
            ended_at=t0 + timedelta(seconds=95),
        )
        s.add(ev)
        s.flush()
        s.refresh(ev)
        s.refresh(shop)
        assert ev.duration_s == 95
        assert ev.frigate_event_ids == []
        assert shop.timezone == "Africa/Dakar"
        assert shop.service_min_s == 15 and shop.status is m.ShopStatus.draft
        assert shop.quiet_hours == {"start": "22:00", "end": "07:00"}
        s.rollback()


def test_m1_shop_service_min_s_range(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as s:
        acc = m.Account(name="A")
        s.add(acc)
        s.flush()
        s.add(m.Shop(account_id=acc.id, name="x", category="boutique", opening_hours=HOURS, service_min_s=5))
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()


def test_m1_ac_f3_3_sales_source_external_ref_unique(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as s:
        _, shop, _ = _shop(s)
        now = datetime.now(UTC)
        for _ in range(2):
            s.add(
                m.Sale(
                    shop_id=shop.id,
                    source=m.SaleSource.wave,
                    amount_xof=2500,
                    occurred_at=now,
                    local_date=date(2026, 11, 20),
                    external_ref="TX-1",
                )
            )
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()


def test_m1_one_cash_declaration_per_shop_day(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as s:
        _, shop, _ = _shop(s)
        now = datetime.now(UTC)
        day = date(2026, 11, 20)
        first = m.Sale(
            shop_id=shop.id,
            source=m.SaleSource.cash_declaration,
            amount_xof=10_000,
            occurred_at=now,
            local_date=day,
        )
        s.add(first)
        s.flush()
        first.voided_at = now  # a voided declaration does not block a new one
        s.flush()
        s.add(
            m.Sale(
                shop_id=shop.id,
                source=m.SaleSource.cash_declaration,
                amount_xof=12_000,
                occurred_at=now,
                local_date=day,
            )
        )
        s.flush()
        s.add(
            m.Sale(
                shop_id=shop.id,
                source=m.SaleSource.cash_declaration,
                amount_xof=1,
                occurred_at=now,
                local_date=day,
            )
        )
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()


def test_m1_negative_amount_rejected(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as s:
        _, shop, _ = _shop(s)
        s.add(
            m.Sale(
                shop_id=shop.id,
                source=m.SaleSource.quick_log,
                amount_xof=-1,
                occurred_at=datetime.now(UTC),
                local_date=date(2026, 11, 20),
            )
        )
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()
