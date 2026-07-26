"""Database initialization and migration utilities."""

from __future__ import annotations

import os

from .seeds import (  # noqa: F401
    _hash_password,
    _is_valid_bcrypt_hash,
    _resolve_admin_password,
    _seed_parties,
    link_invoices_to_parties,
    migrate_patients_to_parties,
    seed_sample_data,
)

# Project paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DATABASE_DIR = os.path.join(PROJECT_ROOT, "data")
DATABASE_PATH = os.path.join(DATABASE_DIR, "makroortodonti.db")


def init_db() -> None:
    """Upgrade the configured database to the latest Alembic revision."""
    from flask_migrate import upgrade

    os.makedirs(DATABASE_DIR, exist_ok=True)
    upgrade()
