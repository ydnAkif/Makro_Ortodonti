from __future__ import annotations

import json
from datetime import datetime, timezone

from flask import Blueprint, Response, abort, render_template, request
from flask_login import login_required

from app.authz import permissions_required
from app.extensions import db
from app.models.models import AuditLog, Makbuz, Party, WorkOrder


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
    work_orders = db.session.execute(
        db.select(WorkOrder).where(WorkOrder.party_id == party.id)
    ).scalars().all()
    makbuzlar = db.session.execute(
        db.select(Makbuz).where(Makbuz.party_id == party.id)
    ).scalars().all()
    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "party": {column.name: getattr(party, column.name) for column in Party.__table__.columns},
        "work_orders": [
            {
                "id": wo.id,
                "patient_name": wo.patient_name,
                "apparatus_type": wo.apparatus_type,
                "order_date": wo.order_date,
                "delivery_date": wo.delivery_date,
                "price_eur": wo.price_eur,
            }
            for wo in work_orders
        ],
        "makbuzlar": [
            {
                "id": m.id,
                "period_year": m.period_year,
                "period_month": m.period_month,
                "status": m.status,
                "total_eur": m.total_eur,
                "total_try": m.total_try,
            }
            for m in makbuzlar
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
    unpaid = db.session.execute(
        db.select(Makbuz).where(Makbuz.party_id == party.id, Makbuz.status != "paid")
    ).scalars().first()
    if unpaid:
        abort(409, "Finansal kayıtları bulunan kişi doğrudan anonimleştirilemez; saklama süresini doğrulayın.")
    token = f"ANON-{party.id}"
    party.name = token
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

