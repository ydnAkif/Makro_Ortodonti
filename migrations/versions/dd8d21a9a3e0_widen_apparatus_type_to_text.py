"""widen apparatus_type to text

Revision ID: dd8d21a9a3e0
Revises: 20260720_02
Create Date: 2026-07-20 18:00:49.034784

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'dd8d21a9a3e0'
down_revision = '20260720_02'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('work_orders', schema=None) as batch_op:
        batch_op.alter_column(
            'apparatus_type',
            existing_type=sa.String(length=100),
            type_=sa.Text(),
        )


def downgrade():
    with op.batch_alter_table('work_orders', schema=None) as batch_op:
        batch_op.alter_column(
            'apparatus_type',
            existing_type=sa.Text(),
            type_=sa.String(length=100),
        )
