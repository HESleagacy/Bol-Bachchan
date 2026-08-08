"""Persist multilingual audio metadata and Google Calendar event ids."""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("detected_languages", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("reminders", sa.Column("calendar_event_id", sa.String(255), nullable=True))
    op.add_column("timeline_events", sa.Column("calendar_event_id", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("timeline_events", "calendar_event_id")
    op.drop_column("reminders", "calendar_event_id")
    op.drop_column("messages", "detected_languages")
