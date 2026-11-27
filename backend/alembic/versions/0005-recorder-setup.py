"""AI box on the shop's recorder (docs/13, AC-F8-6..8).

- kits.stream_checks: last stream report per camera name, sent by the box (codec, size, fps, source)
- kits.angle_checks: installer angle checklist per camera name, tied to the stream source it was done on

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE kits ADD COLUMN stream_checks jsonb NOT NULL DEFAULT '{}', "
        "ADD COLUMN angle_checks jsonb NOT NULL DEFAULT '{}'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE kits DROP COLUMN angle_checks, DROP COLUMN stream_checks")
