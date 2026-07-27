"""Add applies_kdv column to parties table."""

from alembic import op
import sqlalchemy as sa

revision = "20260727_02"
down_revision = "20260727_01"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "parties" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("parties")}
    if "applies_kdv" not in columns:
        with op.batch_alter_table("parties") as batch_op:
            batch_op.add_column(
                sa.Column("applies_kdv", sa.Boolean(), nullable=False, server_default=sa.text("0"))
            )
            batch_op.create_index("ix_parties_applies_kdv", ["applies_kdv"])

    # Existing installations already contain the best available signal for
    # this preference: doctors whose earlier monthly summaries included VAT.
    # Carry that choice forward so the new report is useful immediately.
    if "makbuzlar" in inspector.get_table_names():
        op.execute(
            sa.text(
                """
                UPDATE parties
                   SET applies_kdv = 1
                 WHERE id IN (
                       SELECT DISTINCT party_id
                         FROM makbuzlar
                        WHERE vat_applied = 1
                 )
                """
            )
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "parties" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("parties")}
    if "applies_kdv" in columns:
        with op.batch_alter_table("parties") as batch_op:
            batch_op.drop_index("ix_parties_applies_kdv")
            batch_op.drop_column("applies_kdv")
