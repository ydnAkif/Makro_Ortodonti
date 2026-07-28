"""Legacy /patients routes — kept as redirects for bookmark compatibility."""
from flask import Blueprint, redirect, url_for
from flask_login import login_required
from app.extensions import db
from app.models.models import Patient

patients_bp = Blueprint("patients", __name__)


@patients_bp.route("/", defaults={"path": ""})
@patients_bp.route("/<path:path>")
@login_required
def catch_all(path):
    if path and path.isdigit():
        patient_id = int(path)
        patient = db.session.get(Patient, patient_id)
        if patient and patient.party_id:
            return redirect(url_for("parties.detail_party", party_id=patient.party_id))
    return redirect(url_for("parties.list_parties"))

