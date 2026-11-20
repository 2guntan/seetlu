"""Shared fixtures: one TimescaleDB container per test session (testcontainers)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine
from testcontainers.community.postgres import PostgresContainer

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
