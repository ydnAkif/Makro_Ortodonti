"""Set the monthly summary VAT rate permanently to ten percent."""

from alembic import op
import sqlalchemy as sa


revision = "20260727_04"
down_revision = "20260727_03"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "makbuzlar" not in inspector.get_table_names():
        return

    op.execute(sa.text("""
        UPDATE makbuzlar
           SET vat_rate = 10.00,
               vat_amount = ROUND(subtotal * 0.10, 2),
               grand_total = subtotal + ROUND(subtotal * 0.10, 2)
         WHERE vat_applied = 1
    """))


def downgrade():
    # The previous per-row rates cannot be reconstructed safely.
    pass
