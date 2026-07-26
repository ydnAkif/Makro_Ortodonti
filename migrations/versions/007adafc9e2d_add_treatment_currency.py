"""add treatment currency

Revision ID: 007adafc9e2d
Revises: dd8d21a9a3e0
Create Date: 2026-07-20 19:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '007adafc9e2d'
down_revision = 'dd8d21a9a3e0'
branch_labels = None
depends_on = None


def upgrade():
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("treatments")}
    if "currency" not in columns:
        with op.batch_alter_table('treatments', schema=None) as batch_op:
            batch_op.add_column(sa.Column('currency', sa.String(length=3), nullable=False, server_default='TL'))


def downgrade():
    with op.batch_alter_table('treatments', schema=None) as batch_op:
        batch_op.drop_column('currency')
