"""Shop phone pairing (M9, docs/08).

- phone_pair_codes: 6-digit codes shown in the owner app, 10 minutes, single use (stored as HMAC)
- phone_pair_failures: wrong-code attempts per IP, for rate limiting

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE phone_pair_codes (
            id          uuid PRIMARY KEY,
            shop_id     uuid NOT NULL REFERENCES shops(id),
            code_hmac   text NOT NULL,
            created_by  uuid REFERENCES users(id),
            expires_at  timestamptz NOT NULL,
            used_at     timestamptz,
            created_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ON phone_pair_codes (code_hmac)")
    op.execute(
        """
        CREATE TABLE phone_pair_failures (
            id  uuid PRIMARY KEY,
            ip  text NOT NULL,
            at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ON phone_pair_failures (ip, at)")


def downgrade() -> None:
    op.execute("DROP TABLE phone_pair_failures")
    op.execute("DROP TABLE phone_pair_codes")
