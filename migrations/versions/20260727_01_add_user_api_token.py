"""Add api_token_hash column to users for /api/v1/* bearer-token auth."""

from alembic import op
import sqlalchemy as sa

revision = "20260727_01"
down_revision = "20260725_01"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "users" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("users")}
    if "api_token_hash" not in columns:
        with op.batch_alter_table("users") as batch_op:
            batch_op.add_column(sa.Column("api_token_hash", sa.String(64), nullable=True))
            batch_op.create_unique_constraint("uq_users_api_token_hash", ["api_token_hash"])
            batch_op.create_index("ix_users_api_token_hash", ["api_token_hash"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "users" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("users")}
    if "api_token_hash" in columns:
        with op.batch_alter_table("users") as batch_op:
            batch_op.drop_index("ix_users_api_token_hash")
            batch_op.drop_constraint("uq_users_api_token_hash", type_="unique")
            batch_op.drop_column("api_token_hash")
