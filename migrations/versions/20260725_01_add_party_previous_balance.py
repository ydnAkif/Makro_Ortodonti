"""Add previous_balance column to parties for carried-forward doctor debt."""

from alembic import op
import sqlalchemy as sa

revision = "20260725_01"
down_revision = "20260722_01"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "parties" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("parties")}
    if "previous_balance" not in columns:
        op.add_column(
            "parties",
            sa.Column("previous_balance", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "parties" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("parties")}
    if "previous_balance" in columns:
        op.drop_column("parties", "previous_balance")
