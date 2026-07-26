"""Add makbuz_send_logs table (WhatsApp send history).

Revision ID: 20260721_02
Revises: 20260721_01
Create Date: 2026-07-21
"""

from alembic import op
import sqlalchemy as sa

revision = "20260721_02"
down_revision = "20260721_01"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "makbuz_send_logs" not in inspector.get_table_names():
        op.create_table(
            "makbuz_send_logs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("batch_id", sa.String(32), nullable=False, index=True),
            sa.Column("makbuz_id", sa.Integer(), sa.ForeignKey("makbuzlar.id"), nullable=True, index=True),
            sa.Column("party_id", sa.Integer(), sa.ForeignKey("parties.id"), nullable=True, index=True),
            sa.Column("doctor_name", sa.String(200), nullable=False),
            sa.Column("phone", sa.String(20), nullable=True),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("month", sa.Integer(), nullable=False),
            sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("triggered_by", sa.String(20), nullable=False, server_default="manual"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )


def downgrade():
    op.drop_table("makbuz_send_logs")
