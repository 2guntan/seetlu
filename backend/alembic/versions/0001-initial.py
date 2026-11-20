"""Initial schema: docs/03-data-model.sql verbatim (copied to alembic/sql/0001-initial.sql).

Revision ID: 0001
Revises:
Create Date: 2026-11-20
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0001-initial.sql"

TABLES = [
    "payments", "subscriptions", "audit_log", "support_grants", "count_checks", "clips",
    "edge_commands", "alerts_sent", "alert_rules", "day_corrections", "daily_reports",
    "phone_devices", "unparsed_notifications", "sales", "heartbeats", "events", "zones",
    "cameras", "kits", "user_shops", "shops", "otp_codes", "users", "accounts",
]  # fmt: skip
TYPES = [
    "command_status", "command_type", "alert_type", "confidence_level", "verdict_code",
    "sale_source", "event_type", "zone_type", "camera_role", "kit_health", "kit_status",
    "shop_status", "lang_code", "user_role",
]  # fmt: skip


def upgrade() -> None:
    # exec_driver_sql: the file contains JSON literals with ":" that SQLAlchemy text() would treat as binds.
    op.get_bind().exec_driver_sql(SQL_FILE.read_text())


def downgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        bind.exec_driver_sql(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    for typ in TYPES:
        bind.exec_driver_sql(f'DROP TYPE IF EXISTS "{typ}"')
