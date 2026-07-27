"""Domain service for makbuz resolution, generation and list filtering."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from sqlalchemy import extract

from app.constants import MONTHS
from app.extensions import db
from app.models.models import WorkOrder, Party, Makbuz, money
from app.services.validation_service import parse_date

STATUS_LABELS = {
    Makbuz.STATUS_DRAFT: "Taslak",
    Makbuz.STATUS_SENT: "Tahsilat bekliyor",
    Makbuz.STATUS_PAID: "Ödendi",
}


def generate_makbuz(party_id: int, year: int, month: int, vat_applied: bool, vat_rate: Decimal) -> Makbuz:
    """Belirtilen döneme ait iş emirlerini aylık hesap özetine dönüştür / günceller.

    Gönderilmiş özetler resmi belge olmadığı için güncellenebilir. Tahsilat
    hareketi varsa hareket korunur; yeni toplam üzerinden kalan bakiye ve
    ödeme durumu yeniden hesaplanır.

    NOT: Fonksiyon db.session.flush() yapar ama commit() ağaç sahibi koda bırakılır.
    """
    existing = db.session.execute(
        db.select(Makbuz).where(
            Makbuz.party_id == party_id, Makbuz.year == year, Makbuz.month == month
        )
    ).scalar_one_or_none()

    work_orders = db.session.execute(
        db.select(WorkOrder).where(
            WorkOrder.party_id == party_id,
            extract("year", WorkOrder.work_date) == year,
            extract("month", WorkOrder.work_date) == month,
        ).order_by(WorkOrder.work_date.desc())
    ).scalars().all()

    subtotal = money(sum((wo.total_price for wo in work_orders), Decimal("0.00")))

    makbuz = existing or Makbuz(party_id=party_id, year=year, month=month)
    makbuz.work_order_count = len(work_orders)
    makbuz.subtotal = subtotal
    makbuz.vat_applied = vat_applied
    makbuz.vat_rate = vat_rate if vat_applied else Decimal("0.00")
    has_collection = bool(existing and existing.collected_amount > 0)
    if not has_collection:
        makbuz.status = Makbuz.STATUS_DRAFT
        makbuz.sent_at = None
    makbuz.generated_at = datetime.now().astimezone()
    makbuz.recalculate_totals()

    if has_collection:
        makbuz.status = (
            Makbuz.STATUS_PAID
            if makbuz.collected_amount >= makbuz.grand_total and makbuz.grand_total > 0
            else Makbuz.STATUS_SENT if makbuz.sent_at else Makbuz.STATUS_DRAFT
        )

    if not existing:
        db.session.add(makbuz)
    db.session.flush()
    return makbuz


def resolve_makbuzlar_query(request_args: dict) -> dict:
    """Helper to parse makbuzlar list filters and return period data & aggregated doctor status."""
    today = date.today()
    view = request_args.get("view", "month")
    if view not in ("day", "month", "year", "all"):
        view = "month"

    try:
        year = int(request_args.get("year", today.year))
    except (ValueError, TypeError):
        year = today.year

    try:
        month = int(request_args.get("month", today.month))
    except (ValueError, TypeError):
        month = today.month

    date_str = str(request_args.get("date", "")).strip()
    selected_date = parse_date(date_str) or today

    previous_date = (selected_date - timedelta(days=1)).isoformat()
    next_date = (selected_date + timedelta(days=1)).isoformat()

    prev_nav_month = 12 if month == 1 else month - 1
    prev_nav_year = year - 1 if month == 1 else year
    next_nav_month = 1 if month == 12 else month + 1
    next_nav_year = year + 1 if month == 12 else year

    wo_query = db.select(WorkOrder).join(Party, WorkOrder.party_id == Party.id).where(Party.is_active.is_(True))
    makbuz_query = db.select(Makbuz).join(Party, Makbuz.party_id == Party.id).where(Party.is_active.is_(True))

    if view == "all":
        period_label = "Tüm Zamanlar"
    elif view == "year":
        wo_query = wo_query.where(extract("year", WorkOrder.work_date) == year)
        makbuz_query = makbuz_query.where(Makbuz.year == year)
        period_label = f"{year} Yılı"
    elif view == "day":
        wo_query = wo_query.where(WorkOrder.work_date == selected_date)
        makbuz_query = makbuz_query.where(Makbuz.year == selected_date.year, Makbuz.month == selected_date.month)
        period_label = selected_date.strftime("%d.%m.%Y")
    else:  # view == "month"
        wo_query = wo_query.where(
            extract("year", WorkOrder.work_date) == year,
            extract("month", WorkOrder.work_date) == month,
        )
        makbuz_query = makbuz_query.where(Makbuz.year == year, Makbuz.month == month)
        period_label = f"{MONTHS[month - 1][1]} {year}"

    work_orders = db.session.execute(wo_query).scalars().all()
    all_makbuzlar = db.session.execute(makbuz_query).scalars().all()

    makbuz_by_party = {m.party_id: m for m in all_makbuzlar}

    doctor_data = {}
    for wo in work_orders:
        pid = wo.party_id
        if pid not in doctor_data:
            doctor_data[pid] = {
                "party": wo.party,
                "party_id": pid,
                "count": 0,
                "total_apparatus": Decimal("0.00"),
                "total_extra": Decimal("0.00"),
                "total_price": Decimal("0.00"),
                "makbuz": makbuz_by_party.get(pid),
            }
        d = doctor_data[pid]
        d["count"] += 1
        d["total_apparatus"] += wo.apparatus_price
        d["total_extra"] += wo.extra_price
        d["total_price"] += wo.total_price

    for pid, makbuz in makbuz_by_party.items():
        if pid not in doctor_data and makbuz.party and makbuz.party.is_active:
            doctor_data[pid] = {
                "party": makbuz.party,
                "party_id": pid,
                "count": makbuz.work_order_count or 0,
                "total_apparatus": Decimal("0.00"),
                "total_extra": Decimal("0.00"),
                "total_price": makbuz.subtotal or Decimal("0.00"),
                "makbuz": makbuz,
            }

    doctors = sorted(doctor_data.values(), key=lambda x: x["total_price"], reverse=True)

    status_filter = str(request_args.get("status_filter", "all"))
    if status_filter == "draft":
        doctors = [d for d in doctors if d["makbuz"] and d["makbuz"].status == Makbuz.STATUS_DRAFT]
    elif status_filter == "sent":
        doctors = [d for d in doctors if d["makbuz"] and d["makbuz"].status == Makbuz.STATUS_SENT]
    elif status_filter == "paid":
        doctors = [d for d in doctors if d["makbuz"] and d["makbuz"].status == Makbuz.STATUS_PAID]
    elif status_filter == "unprepared":
        doctors = [d for d in doctors if d["makbuz"] is None]

    grand_total_apparatus = sum(d["total_apparatus"] for d in doctors)
    grand_total_extra = sum(d["total_extra"] for d in doctors)
    grand_total_price = sum(
        (d["makbuz"].grand_total if d["makbuz"] else d["total_price"])
        for d in doctors
    )
    grand_total_count = sum(d["count"] for d in doctors)
    preparation_count = sum(
        1 for d in doctors
        if d["makbuz"] is None or d["makbuz"].status == Makbuz.STATUS_DRAFT
    )
    draft_count = sum(
        1 for d in doctors
        if d["makbuz"] and d["makbuz"].status == Makbuz.STATUS_DRAFT
    )
    awaiting_payment_count = sum(
        1 for d in doctors
        if d["makbuz"] and d["makbuz"].status == Makbuz.STATUS_SENT
    )
    paid_count = sum(
        1 for d in doctors
        if d["makbuz"] and d["makbuz"].status == Makbuz.STATUS_PAID
    )
    deletable_count = sum(
        1 for d in doctors
        if d["makbuz"]
        and not d["makbuz"].payment_entries
        and d["makbuz"].collected_amount <= 0
    )

    return {
        "doctors": doctors,
        "view": view,
        "selected_date": selected_date,
        "year": year,
        "month": month,
        "months": MONTHS,
        "years": list(range(today.year - 3, today.year + 2)),
        "period_label": period_label,
        "status_filter": status_filter,
        "status_labels": STATUS_LABELS,
        "preparation_count": preparation_count,
        "draft_count": draft_count,
        "awaiting_payment_count": awaiting_payment_count,
        "paid_count": paid_count,
        "deletable_count": deletable_count,
        "grand_total_apparatus": grand_total_apparatus,
        "grand_total_extra": grand_total_extra,
        "grand_total_price": grand_total_price,
        "grand_total_count": grand_total_count,
        "today": today,
        "previous_date": previous_date,
        "next_date": next_date,
        "previous_month": prev_nav_month,
        "previous_year": prev_nav_year,
        "next_month": next_nav_month,
        "next_year": next_nav_year,
    }
