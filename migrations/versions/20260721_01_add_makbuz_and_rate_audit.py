"""Add makbuzlar table and work_orders.exchange_rate_applied.

Revision ID: 20260721_01
Revises: 20260720_03
Create Date: 2026-07-21
"""

from alembic import op
import sqlalchemy as sa

revision = "20260721_01"
down_revision = "20260720_03"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "makbuzlar" not in inspector.get_table_names():
        op.create_table(
            "makbuzlar",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("party_id", sa.Integer(), sa.ForeignKey("parties.id"), nullable=False, index=True),
            sa.Column("year", sa.Integer(), nullable=False, index=True),
            sa.Column("month", sa.Integer(), nullable=False, index=True),
            sa.Column("work_order_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("subtotal", sa.Numeric(14, 2), nullable=False, server_default="0.00"),
            sa.Column("vat_applied", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("vat_rate", sa.Numeric(5, 2), nullable=False, server_default="0.00"),
            sa.Column("vat_amount", sa.Numeric(14, 2), nullable=False, server_default="0.00"),
            sa.Column("grand_total", sa.Numeric(14, 2), nullable=False, server_default="0.00"),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft", index=True),
            sa.Column("generated_at", sa.DateTime(), nullable=False),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("paid_at", sa.Date(), nullable=True),
            sa.Column("paid_amount", sa.Numeric(14, 2), nullable=True),
            sa.Column("payment_method", sa.String(30), nullable=True),
            sa.Column("payment_reference", sa.String(100), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("party_id", "year", "month", name="uq_makbuz_party_period"),
        )

    columns = {c["name"] for c in inspector.get_columns("work_orders")}
    if "exchange_rate_applied" not in columns:
        with op.batch_alter_table("work_orders", schema=None) as batch_op:
            batch_op.add_column(sa.Column("exchange_rate_applied", sa.Numeric(12, 4), nullable=True))


def downgrade():
    with op.batch_alter_table("work_orders", schema=None) as batch_op:
        batch_op.drop_column("exchange_rate_applied")
    op.drop_table("makbuzlar")
