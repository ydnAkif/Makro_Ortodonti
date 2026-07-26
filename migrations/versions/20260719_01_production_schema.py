"""Adopt Alembic, exact numeric finance columns, and audit storage.

Revision ID: 20260719_01
Revises:
Create Date: 2026-07-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260719_01"
down_revision = None
branch_labels = None
depends_on = None


NUMERIC_COLUMNS = {
    "treatments": {"price_eur": sa.Numeric(12, 2)},
    "patient_treatments": {"price_override_eur": sa.Numeric(12, 2)},
    "exchange_rates": {"eur_to_try": sa.Numeric(12, 4)},
    "invoices": {
        "total_eur": sa.Numeric(14, 2), "total_try": sa.Numeric(14, 2),
        "exchange_rate": sa.Numeric(12, 4),
    },
    "invoice_items": {
        "unit_price_eur": sa.Numeric(12, 2), "unit_price_try": sa.Numeric(14, 2),
        "vat_rate": sa.Numeric(5, 2), "discount_value": sa.Numeric(12, 2),
    },
    "payments": {
        "amount_eur": sa.Numeric(14, 2), "amount_try": sa.Numeric(14, 2),
        "exchange_rate": sa.Numeric(12, 4),
    },
}


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "parties" not in inspector.get_table_names():
        from app.models.base import Base
        import app.models.models  # noqa: F401
        Base.metadata.create_all(bind=bind)
        return

    if "audit_logs" not in inspector.get_table_names():
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("occurred_at", sa.DateTime(), nullable=False),
            sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("actor_username", sa.String(100)),
            sa.Column("action", sa.String(20), nullable=False),
            sa.Column("entity_type", sa.String(100), nullable=False),
            sa.Column("entity_id", sa.String(100)),
            sa.Column("request_id", sa.String(64)),
            sa.Column("ip_address", sa.String(50)),
            sa.Column("endpoint", sa.String(150)),
            sa.Column("changes_json", sa.Text()),
        )
        for name in ("occurred_at", "actor_user_id", "action", "entity_type", "entity_id", "request_id"):
            op.create_index(f"ix_audit_logs_{name}", "audit_logs", [name])

    inspector = inspect(bind)
    # Adopt legacy patient rows before clinical histories are re-keyed.
    op.execute(sa.text(
        "UPDATE patients SET party_id = (SELECT id FROM parties WHERE "
        "parties.party_type = 'PATIENT' AND parties.first_name = patients.first_name "
        "AND parties.last_name = patients.last_name "
        "AND COALESCE(parties.phone, '') = COALESCE(patients.phone, '') LIMIT 1) "
        "WHERE party_id IS NULL"
    ))
    op.execute(sa.text(
        "INSERT INTO parties (party_type, name, first_name, last_name, phone, email, address, notes, "
        "date_of_birth, treatment_status, is_active, created_at, updated_at) "
        "SELECT 'PATIENT', trim(first_name || ' ' || last_name), first_name, last_name, phone, email, "
        "address, notes, date_of_birth, treatment_status, is_active, created_at, updated_at "
        "FROM patients WHERE party_id IS NULL"
    ))
    op.execute(sa.text(
        "UPDATE patients SET party_id = (SELECT id FROM parties WHERE "
        "parties.party_type = 'PATIENT' AND parties.first_name = patients.first_name "
        "AND parties.last_name = patients.last_name "
        "AND COALESCE(parties.phone, '') = COALESCE(patients.phone, '') ORDER BY id DESC LIMIT 1) "
        "WHERE party_id IS NULL"
    ))
    patient_treatment_columns = {c["name"] for c in inspector.get_columns("patient_treatments")}
    if "party_id" not in patient_treatment_columns:
        with op.batch_alter_table("patient_treatments") as batch:
            batch.add_column(sa.Column("party_id", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_patient_treatments_party", "parties", ["party_id"], ["id"])
            batch.create_index("ix_patient_treatments_party_id", ["party_id"])
        op.execute(sa.text(
            "UPDATE patient_treatments SET party_id = "
            "(SELECT party_id FROM patients WHERE patients.id = patient_treatments.patient_id)"
        ))
        null_count = bind.execute(sa.text("SELECT COUNT(*) FROM patient_treatments WHERE party_id IS NULL")).scalar()
        if null_count:
            raise RuntimeError("PatientTreatment migration found orphan patients; migrate patients to parties first")
        with op.batch_alter_table("patient_treatments") as batch:
            batch.alter_column("party_id", existing_type=sa.Integer(), nullable=False)

    for table, columns in NUMERIC_COLUMNS.items():
        if table not in inspector.get_table_names():
            continue
        existing = {column["name"]: column for column in inspector.get_columns(table)}
        with op.batch_alter_table(table) as batch:
            for name, target_type in columns.items():
                if name in existing:
                    batch.alter_column(name, existing_type=existing[name]["type"], type_=target_type)

    violations = bind.execute(sa.text("PRAGMA foreign_key_check")).fetchall()
    if violations:
        raise RuntimeError(f"Foreign-key violations after migration: {violations[:5]}")


def downgrade():
    for table, columns in reversed(list(NUMERIC_COLUMNS.items())):
        with op.batch_alter_table(table) as batch:
            for name, target_type in columns.items():
                batch.alter_column(name, existing_type=target_type, type_=sa.Float())
    op.drop_table("audit_logs")
