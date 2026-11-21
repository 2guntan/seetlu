"""WhatsApp conversations (M7, docs/07).

- users.reports_paused: `stop` / `start` from the owner
- edge_commands.notify_user_ids / notified_at: who asked for this clip/snapshot on WhatsApp, and when
  they were answered (link, image, « kit injoignable »)
- wa_inbound: webhook messages, unique by WhatsApp message id (Meta retries deliveries)
- wa_sessions: short conversation state per phone (`faux` → number, cash prompt reply window)
- scheduled_sends: one cash prompt per shop per local day

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN reports_paused boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE edge_commands ADD COLUMN notify_user_ids uuid[] NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE edge_commands ADD COLUMN notified_at timestamptz")
    op.execute(
        """
        CREATE TABLE wa_inbound (
            id              uuid PRIMARY KEY,
            wa_message_id   text NOT NULL UNIQUE,
            from_phone      text NOT NULL,
            body            text,
            received_at     timestamptz NOT NULL DEFAULT now(),
            processed_at    timestamptz
        )
        """
    )
    op.execute(
        """
        CREATE TABLE wa_sessions (
            phone_e164      text PRIMARY KEY,
            state           text NOT NULL,
            context         jsonb NOT NULL DEFAULT '{}',
            expires_at      timestamptz NOT NULL,
            updated_at      timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE scheduled_sends (
            shop_id         uuid NOT NULL REFERENCES shops(id),
            kind            text NOT NULL,
            local_date      date NOT NULL,
            sent_at         timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (shop_id, kind, local_date)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS scheduled_sends")
    op.execute("DROP TABLE IF EXISTS wa_sessions")
    op.execute("DROP TABLE IF EXISTS wa_inbound")
    op.execute("ALTER TABLE edge_commands DROP COLUMN IF EXISTS notified_at")
    op.execute("ALTER TABLE edge_commands DROP COLUMN IF EXISTS notify_user_ids")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS reports_paused")
