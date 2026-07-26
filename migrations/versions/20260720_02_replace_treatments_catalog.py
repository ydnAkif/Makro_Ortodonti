"""Replace treatment catalog with Makro Orthodonti specific products.

Revision ID: 20260720_02
Revises: 20260720_01
Create Date: 2026-07-20
"""

from alembic import op
import sqlalchemy as sa

revision = "20260720_02"
down_revision = "20260720_01"
branch_labels = None
depends_on = None

ANA_ISLEMLER = [
    ("Dijital Planlama (Tek Çene)", 1750.00),
    ("Lingual Ark", 1000.00),
    ("Dijital Plak (Adet)", 1200.00),
    ("Nance", 1100.00),
    ("Şeffaf Plak (Soft, Medium, Hard)", 1600.00),
    ("TPA", 1000.00),
    ("Set-up'lı Sx", 1100.00),
    ("Habit Appliances", 1200.00),
    ("Dijital Model (Adet)", 500.00),
    ("Quad Helix", 1200.00),
    ("Bi Helix", 1200.00),
    ("Lingual Indirect Bonding Tek Çene 7-7", 3500.00),
    ("Lingual Indirect Bonding set-upsız Tek Diş", 300.00),
    ("Rapid Expansion (Hyrax Type) (Vidasız)", 1400.00),
    ("Labial Indirect Bonding Tek Çene", 1600.00),
    ("Rapid Expansion (Mc Namara) (Vidasız)", 1500.00),
    ("Rapid Expansion (Fan Type) (Vidasız)", 1500.00),
    ("Hawley", 1100.00),
    ("Molar Slider", 1500.00),
    ("Wrap Around", 1100.00),
    ("Pendulum Appliance", 1500.00),
    ("Lingual Retainer", 450.00),
    ("Expansion (Transverse)", 1500.00),
    ("Sx Plak", 375.00),
    ("Expansion (3 way Type) (Vidasız)", 1400.00),
    ("Yer Tutucu (Sabit)", 850.00),
    ("Expansion (Fan Type) (Vidasız)", 1400.00),
    ("Yer Tutucu (Hareketli)", 1100.00),
    ("Bite Plate", 1500.00),
    ("Gece Plağı", 1000.00),
    ("Activator (FKO)", 2500.00),
    ("Durasoft Gece Plağı (2.5 mm)", 1600.00),
    ("Bionator (Açık-Kapalı)", 2700.00),
    ("Eklem Splinti", 1750.00),
    ("Frankel (I, II, III, IV)", 3000.00),
    ("Twin Block", 3300.00),
    ("Horlama Apareyi (Akrilik)", 2900.00),
    ("Herbst", 4000.00),
    ("Horlama Apareyi (Plak)", 3600.00),
    ("Horlama Apareyi (SomnoMed)", 5000.00),
    ("Hotz Plate", 1100.00),
    ("Beyazlatma Plağı", 1100.00),
    ("Sporcu Plağı", 2800.00),
    ("PRO Sporcu Plağı", 4000.00),
]

EKSTRA_ISLEMLER = [
    ("Bant", 3.00),
    ("Activator Tüpü", 5.00),
    ("Tüplü Bant", 4.00),
    ("Hyrax Vida", 20.00),
    ("Lingual Sheat", 4.00),
    ("3 way (Bertoni)", 25.00),
    ("Ekstra Vida", 4.50),
    ("Fantype (Hyrax)", 60.00),
    ("Z Zemberek, Finger Spring Vs.", 30.00),
    ("Oklüzyon Yükseltme", 100.00),
]


def upgrade():
    from datetime import datetime, timezone
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)

    if "invoice_items" in inspector.get_table_names():
        op.execute("UPDATE invoice_items SET treatment_id = NULL WHERE treatment_id IS NOT NULL")
    op.execute("DELETE FROM treatments")

    treatments_table = sa.table(
        "treatments",
        sa.column("name", sa.String(200)),
        sa.column("category", sa.String(50)),
        sa.column("price_eur", sa.Numeric(12, 2)),
        sa.column("currency", sa.String(3)),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = []
    for name, price in ANA_ISLEMLER:
        rows.append({"name": name, "category": "ana_islemler", "price_eur": price, "currency": "TL", "is_active": True, "created_at": now, "updated_at": now})
    for name, price in EKSTRA_ISLEMLER:
        rows.append({"name": name, "category": "ekstra_islemler", "price_eur": price, "currency": "EUR", "is_active": True, "created_at": now, "updated_at": now})

    op.bulk_insert(treatments_table, rows)


def downgrade():
    op.execute("DELETE FROM treatments")
