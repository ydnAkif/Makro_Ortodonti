from __future__ import annotations

import json
from datetime import datetime, timezone

from flask import Blueprint, Response, abort, render_template, request
from flask_login import login_required

from app.authz import permissions_required
from app.extensions import db
from app.models.models import AuditLog, Invoice, Party, PatientTreatment


privacy_bp = Blueprint("privacy", __name__)


@privacy_bp.get("/audit")
@login_required
@permissions_required("privacy.audit")
def audit_index():
    page = max(request.args.get("page", 1, type=int), 1)
    pagination = db.paginate(
        db.select(AuditLog).order_by(AuditLog.occurred_at.desc()),
        page=page, per_page=50, max_per_page=100, error_out=False,
    )
    return render_template("privacy/audit.html", pagination=pagination, audit_rows=pagination.items)


@privacy_bp.get("/parties/<int:party_id>/export")
@login_required
@permissions_required("privacy.export")
def export_party(party_id: int):
    party = db.get_or_404(Party, party_id)
    invoices = db.session.execute(db.select(Invoice).where(Invoice.party_id == party.id)).scalars().all()
    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "party": {column.name: getattr(party, column.name) for column in Party.__table__.columns},
        "invoices": [
            {
                "invoice_number": invoice.invoice_number,
                "invoice_date": invoice.invoice_date,
                "status": invoice.status,
                "total_eur": invoice.total_eur,
                "total_try": invoice.total_try,
                "payments": [
                    {"date": p.payment_date, "amount_eur": p.amount_eur, "amount_try": p.amount_try, "method": p.method}
                    for p in invoice.payments
                ],
            }
            for invoice in invoices
        ],
    }
    body = json.dumps(payload, default=str, ensure_ascii=False, indent=2)
    return Response(body, mimetype="application/json", headers={
        "Content-Disposition": f'attachment; filename="party-{party.id}-kvkk-export.json"'
    })


@privacy_bp.post("/parties/<int:party_id>/anonymize")
@login_required
@permissions_required("privacy.anonymize")
def anonymize_party(party_id: int):
    party = db.get_or_404(Party, party_id)
    if any(not invoice.is_deleted for invoice in party.invoices):
        abort(409, "Finansal kayıtları bulunan kişi doğrudan anonimleştirilemez; saklama süresini doğrulayın.")
    token = f"ANON-{party.id}"
    party.name = token
    party.first_name = "Anonim"
    party.last_name = str(party.id)
    party.phone = None
    party.email = None
    party.address = None
    party.tax_id = None
    party.notes = None
    party.date_of_birth = None
    party.contact_person = None
    party.contact_phone = None
    party.is_active = False
    db.session.commit()
    return {"ok": True, "party_id": party.id}
