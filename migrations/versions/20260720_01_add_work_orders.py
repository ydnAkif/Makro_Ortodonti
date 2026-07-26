"""Add work_orders table and simplify PartyType to dentist only.

Revision ID: 20260720_01
Revises: 20260719_01
Create Date: 2026-07-20
"""

from alembic import op
import sqlalchemy as sa

revision = "20260720_01"
down_revision = "20260719_01"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = __import__('sqlalchemy').inspect(bind)
    if "work_orders" in inspector.get_table_names():
        return
    op.create_table(
        "work_orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("party_id", sa.Integer(), sa.ForeignKey("parties.id"), nullable=False, index=True),
        sa.Column("work_date", sa.Date(), nullable=False, index=True),
        sa.Column("apparatus_type", sa.String(100), nullable=False),
        sa.Column("extra_addons", sa.Text(), nullable=True),
        sa.Column("patient_name", sa.String(200), nullable=False),
        sa.Column("apparatus_price", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
        sa.Column("extra_price", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
        sa.Column("total_price", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table("work_orders")
