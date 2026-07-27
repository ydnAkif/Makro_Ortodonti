"""Add direct collection movements for opening doctor balances."""

from alembic import op
import sqlalchemy as sa


revision = "20260727_03"
down_revision = "20260727_02"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "party_payments" in inspector.get_table_names():
        return

    op.create_table(
        "party_payments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("party_id", sa.Integer(), sa.ForeignKey("parties.id"), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("method", sa.String(30), nullable=False, server_default="cash"),
        sa.Column("reference", sa.String(100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_party_payments_party_id", "party_payments", ["party_id"])
    op.create_index("ix_party_payments_payment_date", "party_payments", ["payment_date"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "party_payments" not in inspector.get_table_names():
        return
    op.drop_index("ix_party_payments_payment_date", table_name="party_payments")
    op.drop_index("ix_party_payments_party_id", table_name="party_payments")
    op.drop_table("party_payments")
