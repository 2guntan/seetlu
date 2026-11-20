"""Shared fixtures: one TimescaleDB container per test session (testcontainers)."""

import itertools
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.community.postgres import PostgresContainer

from seetlu.api import deps
from seetlu.api.auth import _issue
from seetlu.db import models as m
from seetlu.main import create_app

BACKEND = Path(__file__).resolve().parent.parent
TIMESCALE_IMAGE = "timescale/timescaledb:2.17.2-pg16"


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    with PostgresContainer(TIMESCALE_IMAGE, username="seetlu", password="seetlu", dbname="seetlu") as pg:
        yield pg.get_connection_url(driver="psycopg")


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture(scope="session")
def migrated_engine(pg_url: str) -> Iterator[Engine]:
    command.upgrade(alembic_config(pg_url), "head")
    engine = create_engine(pg_url)
    yield engine
    engine.dispose()


# ---------- API fixtures ----------


HOURS = {d: [["08:00", "21:00"]] for d in ("mon", "tue", "wed", "thu", "fri", "sat")} | {"sun": []}
_phones = itertools.count(1)


@pytest.fixture
def db(migrated_engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with factory() as s:
        yield s
    tables = ", ".join(t.name for t in m.Base.metadata.sorted_tables)
    with migrated_engine.begin() as c:
        c.execute(text(f"TRUNCATE {tables} CASCADE"))


@pytest.fixture
def client(migrated_engine: Engine, db: Session) -> Iterator[TestClient]:
    app = create_app()
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)

    def _get_db() -> Iterator[Session]:
        with factory() as s:
            yield s

    app.dependency_overrides[deps.get_db] = _get_db
    with TestClient(app) as c:
        yield c


def new_phone() -> str:
    return f"+22178{next(_phones):07d}"


@dataclass
class World:
    """Two accounts; account A has 2 shops, a manager+staff on shop A1, a kit on A1 being installed."""

    acc_a: m.Account
    acc_b: m.Account
    owner_a: m.User
    owner_b: m.User
    manager: m.User
    staff: m.User
    installer: m.User
    support: m.User
    shop_a1: m.Shop
    shop_a2: m.Shop
    shop_b: m.Shop
    kit_a1: m.Kit


def make_world(s: Session) -> World:
    acc_a, acc_b = m.Account(name="A"), m.Account(name="B")
    s.add_all([acc_a, acc_b])
    s.flush()

    def user(role: m.UserRole, account: m.Account | None, **kw: object) -> m.User:
        u = m.User(
            name=role.value, phone_e164=new_phone(), role=role, account_id=account.id if account else None
        )
        for k, v in kw.items():
            setattr(u, k, v)
        s.add(u)
        return u

    owner_a, owner_b = user(m.UserRole.owner, acc_a), user(m.UserRole.owner, acc_b)
    manager, staff = user(m.UserRole.manager, acc_a), user(m.UserRole.staff, acc_a)
    installer, support = user(m.UserRole.installer, None), user(m.UserRole.support, None)
    s.flush()
    shops = [
        m.Shop(account_id=a.id, name=n, category="boutique", opening_hours=HOURS)
        for a, n in ((acc_a, "A1"), (acc_a, "A2"), (acc_b, "B"))
    ]
    s.add_all(shops)
    s.flush()
    s.add_all(
        [
            m.UserShop(user_id=manager.id, shop_id=shops[0].id),
            m.UserShop(user_id=staff.id, shop_id=shops[0].id),
        ]
    )
    kit = m.Kit(
        serial=f"T-{new_phone()}", claim_token_hash="x", shop_id=shops[0].id, installer_id=installer.id,
        status=m.KitStatus.installing,
    )  # fmt: skip
    s.add(kit)
    s.commit()
    return World(
        acc_a, acc_b, owner_a, owner_b, manager, staff, installer, support, shops[0], shops[1], shops[2], kit
    )


@pytest.fixture
def world(db: Session) -> World:
    return make_world(db)


def bearer(s: Session, user: m.User) -> dict[str, str]:
    tokens = _issue(s, user)
    s.commit()
    return {"Authorization": f"Bearer {tokens.access_token}"}
