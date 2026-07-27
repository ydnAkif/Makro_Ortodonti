"""Shared lookup for single-value Settings rows (clinic identity, etc.).

Was previously re-implemented independently in reports.py, makbuzlar.py and
twice in parties.py — the same query with the same "or default" fallback,
copy-pasted instead of shared.
"""

from app.extensions import db
from app.models.models import Settings


def get_setting(key: str, default: str = "") -> str:
    value = db.session.execute(
        db.select(Settings.value).where(Settings.key == key)
    ).scalar_one_or_none()
    return value or default


def get_clinic_identity() -> dict[str, str]:
    """The three clinic-identity fields used on makbuz/report/work-order PDFs and pages."""
    return {
        "clinic_name": get_setting("clinic_name", "Makro Ortodonti"),
        "clinic_phone": get_setting("clinic_phone"),
        "clinic_email": get_setting("clinic_email"),
    }
