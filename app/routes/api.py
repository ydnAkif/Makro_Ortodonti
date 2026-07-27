"""Salt okunur JSON API katmanı.

Gelecekteki mobil uygulamalar veya dış entegrasyonlar için temel
REST API endpoint'leri. Tümü ``/api/v1/`` önekine bağlıdır.

Endpoints:
    GET /api/v1/parties              — Diş hekimleri listesi
    GET /api/v1/parties/<id>         — Tek hekim detayı + iş emirleri
    GET /api/v1/work-orders          — İş emirleri (dönem filtresi ile)
    GET /api/v1/makbuzlar            — Makbuz listesi (dönem filtresi ile)
    GET /api/v1/makbuzlar/<id>       — Tek makbuz detayı
    GET /api/v1/treatments           — Tedavi kataloğu
    GET /api/v1/exchange-rate        — Güncel döviz kuru
    GET /api/v1/dashboard            — Panel özeti
"""

from datetime import date
from decimal import Decimal

from flask import Blueprint, jsonify, request

from app.authz import api_permissions_required
from app.extensions import db
from app.models.models import (
    Makbuz, Party, PartyType, Treatment, WorkOrder,
)
from app.services.exchange_service import get_latest_rate
from app.services.search_service import tr_order

api_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")


def _json_safe(obj):
    """JSON güvenli dönüştürme (Decimal, date, None)."""
    if obj is None:
        return None
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    return obj


def _serialize_party(p: Party) -> dict:
    return {
        "id": p.id,
        "party_type": p.party_type.value if hasattr(p.party_type, "value") else p.party_type,
        "name": p.name,
        "phone": p.phone,
        "email": p.email,
        "address": p.address,
        "tax_id": p.tax_id,
        "is_active": p.is_active,
        "previous_balance": _json_safe(p.previous_balance),
        "previous_balance_outstanding": _json_safe(p.previous_balance_outstanding),
    }


def _serialize_work_order(wo: WorkOrder) -> dict:
    return {
        "id": wo.id,
        "party_id": wo.party_id,
        "work_date": _json_safe(wo.work_date),
        "patient_name": wo.patient_name,
        "apparatus_type": wo.apparatus_type,
        "extra_addons": wo.extra_addons,
        "apparatus_price": _json_safe(wo.apparatus_price),
        "extra_price": _json_safe(wo.extra_price),
        "total_price": _json_safe(wo.total_price),
        "notes": wo.notes,
    }


def _serialize_makbuz(m: Makbuz) -> dict:
    return {
        "id": m.id,
        "party_id": m.party_id,
        "party_name": m.party.name if m.party else None,
        "year": m.year,
        "month": m.month,
        "work_order_count": m.work_order_count,
        "subtotal": _json_safe(m.subtotal),
        "vat_applied": m.vat_applied,
        "vat_rate": _json_safe(m.vat_rate),
        "vat_amount": _json_safe(m.vat_amount),
        "grand_total": _json_safe(m.grand_total),
        "status": m.status,
        "outstanding_amount": _json_safe(m.outstanding_amount),
    }


def _serialize_treatment(t: Treatment) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "category": t.category,
        "price_eur": _json_safe(t.price_eur),
        "currency": t.currency,
        "is_active": t.is_active,
    }


# ---------------------------------------------------------------------------
# Parties
# ---------------------------------------------------------------------------

@api_bp.route("/parties")
@api_permissions_required("clinical.view")
def list_parties():
    q = db.select(Party).where(
        Party.party_type == PartyType.DENTIST,
        Party.is_active.is_(True),
    ).order_by(tr_order(Party.name))
    parties = db.session.execute(q).scalars().all()
    return jsonify([_serialize_party(p) for p in parties])


@api_bp.route("/parties/<int:party_id>")
@api_permissions_required("clinical.view")
def get_party(party_id):
    p = db.session.get(Party, party_id)
    if not p:
        return jsonify({"error": "Doktor bulunamadı"}), 404

    year = request.args.get("year", date.today().year, type=int)
    month = request.args.get("month", date.today().month, type=int)

    work_orders = db.session.execute(
        db.select(WorkOrder)
        .where(
            WorkOrder.party_id == party_id,
            db.extract("year", WorkOrder.work_date) == year,
            db.extract("month", WorkOrder.work_date) == month,
        )
        .order_by(WorkOrder.work_date.desc())
    ).scalars().all()

    makbuz = db.session.execute(
        db.select(Makbuz).where(
            Makbuz.party_id == party_id, Makbuz.year == year, Makbuz.month == month
        )
    ).scalar_one_or_none()

    return jsonify({
        "party": _serialize_party(p),
        "period": {"year": year, "month": month},
        "work_orders": [_serialize_work_order(wo) for wo in work_orders],
        "makbuz": _serialize_makbuz(makbuz) if makbuz else None,
    })


# ---------------------------------------------------------------------------
# Work Orders
# ---------------------------------------------------------------------------

@api_bp.route("/work-orders")
@api_permissions_required("clinical.view")
def list_work_orders():
    year = request.args.get("year", date.today().year, type=int)
    month = request.args.get("month", date.today().month, type=int)

    work_orders = db.session.execute(
        db.select(WorkOrder)
        .join(Party, WorkOrder.party_id == Party.id)
        .where(
            db.extract("year", WorkOrder.work_date) == year,
            db.extract("month", WorkOrder.work_date) == month,
            Party.is_active.is_(True),
        )
        .order_by(WorkOrder.work_date.desc())
    ).scalars().all()

    return jsonify({
        "period": {"year": year, "month": month},
        "count": len(work_orders),
        "total": _json_safe(sum((wo.total_price for wo in work_orders), Decimal("0.00"))),
        "work_orders": [_serialize_work_order(wo) for wo in work_orders],
    })


# ---------------------------------------------------------------------------
# Makbuzlar
# ---------------------------------------------------------------------------

@api_bp.route("/makbuzlar")
@api_permissions_required("billing.view")
def list_makbuzlar():
    year = request.args.get("year", date.today().year, type=int)
    month = request.args.get("month", date.today().month, type=int)

    makbuzlar = db.session.execute(
        db.select(Makbuz)
        .join(Party, Makbuz.party_id == Party.id)
        .where(
            Makbuz.year == year, Makbuz.month == month,
            Party.is_active.is_(True),
        )
        .order_by(Makbuz.grand_total.desc())
    ).scalars().all()

    return jsonify({
        "period": {"year": year, "month": month},
        "count": len(makbuzlar),
        "makbuzlar": [_serialize_makbuz(m) for m in makbuzlar],
    })


@api_bp.route("/makbuzlar/<int:makbuz_id>")
@api_permissions_required("billing.view")
def get_makbuz(makbuz_id):
    m = db.session.get(Makbuz, makbuz_id)
    if not m:
        return jsonify({"error": "Makbuz bulunamadı"}), 404

    work_orders = db.session.execute(
        db.select(WorkOrder).where(
            WorkOrder.party_id == m.party_id,
            db.extract("year", WorkOrder.work_date) == m.year,
            db.extract("month", WorkOrder.work_date) == m.month,
        ).order_by(WorkOrder.work_date.desc())
    ).scalars().all()

    return jsonify({
        "makbuz": _serialize_makbuz(m),
        "work_orders": [_serialize_work_order(wo) for wo in work_orders],
    })


# ---------------------------------------------------------------------------
# Treatments
# ---------------------------------------------------------------------------

@api_bp.route("/treatments")
@api_permissions_required("clinical.view")
def list_treatments():
    category = request.args.get("category")
    q = db.select(Treatment).where(Treatment.is_active.is_(True))
    if category:
        q = q.where(Treatment.category == category)
    q = q.order_by(tr_order(Treatment.name))
    treatments = db.session.execute(q).scalars().all()
    return jsonify([_serialize_treatment(t) for t in treatments])


# ---------------------------------------------------------------------------
# Exchange Rate
# ---------------------------------------------------------------------------

@api_bp.route("/exchange-rate")
@api_permissions_required("clinical.view")
def get_exchange_rate():
    rate = get_latest_rate()
    if rate is None:
        return jsonify({"error": "Döviz kuru bulunamadı"}), 404
    return jsonify({"eur_to_try": float(rate)})


# ---------------------------------------------------------------------------
# Dashboard summary
# ---------------------------------------------------------------------------

@api_bp.route("/dashboard")
@api_permissions_required("clinical.view")
def dashboard_summary():
    from datetime import timedelta

    today = date.today()
    month_start = today.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)

    active_dentists = db.session.execute(
        db.select(db.func.count(Party.id)).where(
            Party.party_type == PartyType.DENTIST, Party.is_active.is_(True)
        )
    ).scalar() or 0

    monthly_wo_count = db.session.execute(
        db.select(db.func.count(WorkOrder.id))
        .join(Party, WorkOrder.party_id == Party.id)
        .where(
            WorkOrder.work_date >= month_start,
            WorkOrder.work_date < next_month,
            Party.is_active.is_(True),
        )
    ).scalar() or 0

    monthly_eur_total = db.session.execute(
        db.select(db.func.coalesce(db.func.sum(WorkOrder.total_price), 0))
        .join(Party, WorkOrder.party_id == Party.id)
        .where(
            WorkOrder.work_date >= month_start,
            WorkOrder.work_date < next_month,
            Party.is_active.is_(True),
        )
    ).scalar() or 0

    return jsonify({
        "active_dentists": active_dentists,
        "monthly_work_orders": monthly_wo_count,
        "monthly_total_try": float(monthly_eur_total),
        "eur_to_try": float(get_latest_rate() or 0),
    })
