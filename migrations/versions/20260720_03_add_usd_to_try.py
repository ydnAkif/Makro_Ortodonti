"""add usd_to_try to exchange_rates

Revision ID: 20260720_03
Revises: 007adafc9e2d
Create Date: 2026-07-20 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260720_03'
down_revision = '007adafc9e2d'
branch_labels = None
depends_on = None


def upgrade():
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("exchange_rates")}
    if "usd_to_try" not in columns:
        with op.batch_alter_table('exchange_rates', schema=None) as batch_op:
            batch_op.add_column(sa.Column('usd_to_try', sa.Numeric(12, 4), nullable=True))


def downgrade():
    with op.batch_alter_table('exchange_rates', schema=None) as batch_op:
        batch_op.drop_column('usd_to_try')
