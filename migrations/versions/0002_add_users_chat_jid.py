"""Add users.chat_jid for restart-safe reminder delivery."""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("chat_jid", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "chat_jid")
