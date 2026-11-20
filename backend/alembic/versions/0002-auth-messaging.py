"""Auth and messaging support tables (M2).

- otp_codes.request_ip: per-IP OTP rate limit (docs/09: 3 requests / 15 min per phone and per IP)
- refresh_tokens: rotating, revocable refresh tokens (docs/09)
- mock_messages: MockProvider outbox, read by the dev inbox (docs/07)

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE otp_codes ADD COLUMN request_ip text")
    op.execute("CREATE INDEX otp_codes_request_ip_idx ON otp_codes (request_ip)")
    op.execute(
        """
        CREATE TABLE refresh_tokens (
            id          uuid PRIMARY KEY,
            user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at  timestamptz NOT NULL,
            revoked_at  timestamptz,
            replaced_by uuid,
            created_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX refresh_tokens_user_id_idx ON refresh_tokens (user_id)")
    op.execute(
        """
        CREATE TABLE mock_messages (
            id          uuid PRIMARY KEY,
            to_phone    text NOT NULL,
            kind        text NOT NULL CHECK (kind IN ('template', 'text', 'media')),
            template    text,
            lang        text,
            params      jsonb NOT NULL DEFAULT '[]',
            buttons     jsonb NOT NULL DEFAULT '[]',
            body        text,
            url         text,
            created_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX mock_messages_to_phone_created_at_idx ON mock_messages (to_phone, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mock_messages")
    op.execute("DROP TABLE IF EXISTS refresh_tokens")
    op.execute("DROP INDEX IF EXISTS otp_codes_request_ip_idx")
    op.execute("ALTER TABLE otp_codes DROP COLUMN IF EXISTS request_ip")
