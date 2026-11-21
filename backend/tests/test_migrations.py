"""M1 done-when: migration up/down works on a clean DB."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, inspect, make_url, text

from tests.conftest import BACKEND, alembic_config

DOCS_SQL = BACKEND.parent / "docs" / "03-data-model.sql"
MIGRATION_SQL = BACKEND / "alembic" / "sql" / "0001-initial.sql"
EXPECTED_TABLES = {
    "phone_pair_codes",  # 0004
    "phone_pair_failures",  # 0004
    "wa_inbound",  # 0003
    "wa_sessions",  # 0003
    "scheduled_sends",  # 0003
    "accounts",
    "users",
    "otp_codes",
    "shops",
    "user_shops",
    "kits",
    "cameras",
    "zones",
    "events",
    "heartbeats",
    "sales",
    "unparsed_notifications",
    "phone_devices",
    "daily_reports",
    "day_corrections",
    "alert_rules",
    "alerts_sent",
    "edge_commands",
    "clips",
    "count_checks",
    "support_grants",
    "audit_log",
    "subscriptions",
    "payments",
    "refresh_tokens",
    "mock_messages",
}


@pytest.fixture
def clean_db(pg_url: str) -> Iterator[str]:
    admin = create_engine(pg_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS updown"))
        c.execute(text("CREATE DATABASE updown"))
    url = make_url(pg_url).set(database="updown").render_as_string(hide_password=False)
    yield url
    with admin.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS updown WITH (FORCE)"))
    admin.dispose()


def _tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names()) - {"alembic_version"}


def _user_types(engine: Engine) -> set[str]:
    with engine.connect() as c:
        rows = c.execute(text("SELECT typname FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid"))
        return {r[0] for r in rows}


def test_m1_migration_sql_matches_spec() -> None:
    if not DOCS_SQL.exists():
        pytest.skip("docs/ not available (running outside the repo)")
    assert MIGRATION_SQL.read_text() == DOCS_SQL.read_text()


def test_m1_migration_up_down_up_on_clean_db(clean_db: str) -> None:
    cfg = alembic_config(clean_db)
    engine = create_engine(clean_db)
    try:
        command.upgrade(cfg, "head")
        assert _tables(engine) == EXPECTED_TABLES
        with engine.connect() as c:
            hypertables = {
                r[0]
                for r in c.execute(text("SELECT hypertable_name FROM timescaledb_information.hypertables"))
            }
        assert hypertables == {"events", "heartbeats"}

        command.downgrade(cfg, "base")
        assert _tables(engine) == set()
        assert _user_types(engine) == set()

        command.upgrade(cfg, "head")
        assert _tables(engine) == EXPECTED_TABLES
    finally:
        engine.dispose()


def test_m1_migration_file_is_in_image_context() -> None:
    # The Dockerfile copies the whole backend/ dir; the SQL must live inside it, not only in docs/.
    assert MIGRATION_SQL.is_file() and Path(MIGRATION_SQL).stat().st_size > 1000
