"""Add itemized collection movements for monthly receipts.

Revision ID: 20260722_01
Revises: 20260721_02
Create Date: 2026-07-22
"""

from alembic import op
import sqlalchemy as sa

revision = "20260722_01"
down_revision = "20260721_02"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "makbuz_payments" not in inspector.get_table_names():
        op.create_table(
            "makbuz_payments",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("makbuz_id", sa.Integer(), sa.ForeignKey("makbuzlar.id"), nullable=False),
            sa.Column("payment_date", sa.Date(), nullable=False),
            sa.Column("amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("method", sa.String(30), nullable=False, server_default="cash"),
            sa.Column("reference", sa.String(100), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.CheckConstraint("amount > 0", name="ck_makbuz_payment_positive_amount"),
        )
        op.create_index("ix_makbuz_payments_makbuz_id", "makbuz_payments", ["makbuz_id"])
        op.create_index("ix_makbuz_payments_payment_date", "makbuz_payments", ["payment_date"])

        # Preserve collections recorded by older versions as their first movement.
        op.execute(sa.text("""
            INSERT INTO makbuz_payments
                (makbuz_id, payment_date, amount, method, reference, notes, created_at, updated_at)
            SELECT
                id,
                COALESCE(paid_at, DATE(created_at), DATE('now')),
                paid_amount,
                COALESCE(payment_method, 'cash'),
                payment_reference,
                'Eski tahsilat kaydından aktarıldı',
                COALESCE(created_at, CURRENT_TIMESTAMP),
                COALESCE(updated_at, CURRENT_TIMESTAMP)
            FROM makbuzlar
            WHERE paid_amount IS NOT NULL AND paid_amount > 0
        """))


def downgrade():
    op.drop_index("ix_makbuz_payments_payment_date", table_name="makbuz_payments")
    op.drop_index("ix_makbuz_payments_makbuz_id", table_name="makbuz_payments")
    op.drop_table("makbuz_payments")
