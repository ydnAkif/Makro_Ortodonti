"""Kapsamlı muhasebe raporları — TRY merkezli, PDF çıktı destekli."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from flask import Blueprint, render_template, request, send_file
from flask_login import login_required
from io import BytesIO

from app.authz import permissions_required
from app.models.models import INVOICE_CATEGORY_LABELS
from app.services.reports_service import (
    MONTH_NAMES,
    build_aging_buckets,
    build_category_stats,
    build_daily_rows,
    build_doctor_detail,
    build_doctor_summaries,
    build_monthly_trend,
    build_period_overview,
    build_treatment_stats,
    build_vat_summary,
    fetch_report_data,
    resolve_period,
)
from app.services.settings_service import get_setting as _get_setting
from app.constants import VAT_RATE


reports_bp = Blueprint("reports", __name__)


def _period_label(start: date, end: date) -> str:
    return f"{start.strftime('%d.%m.%Y')} – {end.strftime('%d.%m.%Y')}"


def _resolve_year_month() -> tuple[int, int]:
    today = date.today()
    try:
        year = int(request.args.get("year", today.year))
    except (ValueError, TypeError):
        year = today.year
    try:
        month = int(request.args.get("month", today.month))
    except (ValueError, TypeError):
        month = today.month
    if month not in range(1, 13):
        month = today.month
    return year, month


def _build_kdv_doctor_rows(year: int, month: int) -> list[dict]:
    """Doktor KDV tercihine göre aylık rapor satırlarını tek veri kaynağından üret."""
    from sqlalchemy import extract
    from app.extensions import db
    from app.models.models import Party, PartyType, Makbuz, WorkOrder, money

    doctors = db.session.execute(
        db.select(Party).where(
            Party.party_type == PartyType.DENTIST,
            Party.is_active.is_(True),
            Party.applies_kdv.is_(True),
        ).order_by(Party.name)
    ).scalars().all()
    if not doctors:
        return []

    doctor_ids = [doctor.id for doctor in doctors]
    summaries = db.session.execute(
        db.select(Makbuz).where(
            Makbuz.party_id.in_(doctor_ids),
            Makbuz.year == year,
            Makbuz.month == month,
        )
    ).scalars().all()
    summary_by_party = {summary.party_id: summary for summary in summaries}

    work_orders = db.session.execute(
        db.select(WorkOrder).where(
            WorkOrder.party_id.in_(doctor_ids),
            extract("year", WorkOrder.work_date) == year,
            extract("month", WorkOrder.work_date) == month,
        )
    ).scalars().all()
    work_orders_by_party: dict[int, list] = {doctor_id: [] for doctor_id in doctor_ids}
    for work_order in work_orders:
        work_orders_by_party[work_order.party_id].append(work_order)

    rows = []
    for doctor in doctors:
        summary = summary_by_party.get(doctor.id)
        doctor_work_orders = work_orders_by_party[doctor.id]
        subtotal = money(
            summary.subtotal if summary
            else sum((work_order.total_price for work_order in doctor_work_orders), Decimal("0.00"))
        )
        vat_rate = VAT_RATE
        vat_amount = money(summary.vat_amount) if summary and summary.vat_applied else money(subtotal * vat_rate / Decimal("100"))
        grand_total = money(subtotal + vat_amount)
        rows.append({
            "name": doctor.display_name,
            "tax_id": doctor.tax_id or "-",
            "work_order_count": len(doctor_work_orders),
            "net_total": subtotal,
            "vat_rate": vat_rate,
            "vat_total": vat_amount,
            "grand_total": grand_total,
            "status": "Özet hazır" if summary else ("Özet bekliyor" if doctor_work_orders else "İşlem yok"),
        })
    return rows


# ---------------------------------------------------------------------------
# Ana rapor sayfası
# ---------------------------------------------------------------------------

@reports_bp.route("/")
@login_required
@permissions_required("reports.view")
def index():
    today = date.today()
    start_date, end_date, selected_period = resolve_period(
        today,
        request.args.get("period", "this_month"),
        request.args.get("start_date", ""),
        request.args.get("end_date", ""),
    )

    data = fetch_report_data(start_date, end_date)

    overview = build_period_overview(
        start_date, end_date,
        data["invoices"], data["payments"],
        data["work_orders"], data["makbuzlar"], data["all_makbuzlar"],
        data.get("receivable_invoices"),
    )
    doctor_summaries = build_doctor_summaries(
        start_date, end_date,
        data["work_orders"], data["all_makbuzlar"],
    )
    aging = build_aging_buckets(end_date, data["all_makbuzlar"], data.get("receivable_invoices"))
    treatment_stats = build_treatment_stats(data["work_orders"])
    category_stats = build_category_stats(data["work_orders"])
    vat_summary = build_vat_summary(data["makbuzlar"])
    daily_rows = build_daily_rows(start_date, end_date, data["work_orders"], data["all_makbuzlar"])
    trend_rows = build_monthly_trend(start_date, end_date, data["work_orders"], data["all_makbuzlar"])

    max_trend = max(
        (max(r["issued"], r["collected"]) for r in trend_rows),
        default=Decimal("1"),
    ) or Decimal("1")
    max_category = max(
        (r.amount_try for r in category_stats),
        default=Decimal("1"),
    ) or Decimal("1")
    max_aging = max(
        (b.amount for b in aging),
        default=Decimal("1"),
    ) or Decimal("1")

    return render_template(
        "reports/index.html",
        today=today,
        start_date=start_date,
        end_date=end_date,
        selected_period=selected_period,
        overview=overview,
        doctor_summaries=doctor_summaries,
        aging=aging,
        treatment_stats=treatment_stats,
        category_stats=category_stats,
        category_labels=INVOICE_CATEGORY_LABELS,
        vat_summary=vat_summary,
        daily_rows=daily_rows,
        trend_rows=trend_rows,
        current_rate=data["current_rate"],
        max_trend=max_trend,
        max_category=max_category,
        max_aging=max_aging,
        month_names=MONTH_NAMES,
    )


# ---------------------------------------------------------------------------
# Doktor detay raporu
# ---------------------------------------------------------------------------

@reports_bp.route("/doctor/<int:party_id>")
@login_required
@permissions_required("reports.view")
def doctor_detail(party_id: int):
    today = date.today()
    start_date, end_date, selected_period = resolve_period(
        today,
        request.args.get("period", "this_month"),
        request.args.get("start_date", ""),
        request.args.get("end_date", ""),
    )

    data = fetch_report_data(start_date, end_date)
    detail = build_doctor_detail(party_id, start_date, end_date, data["all_makbuzlar"], data["work_orders"])
    vat_summary = build_vat_summary([
        m for m in data["makbuzlar"] if m.party_id == party_id
    ])

    return render_template(
        "reports/doctor_detail.html",
        today=today,
        start_date=start_date,
        end_date=end_date,
        selected_period=selected_period,
        detail=detail,
        vat_summary=vat_summary,
        current_rate=data["current_rate"],
        month_names=MONTH_NAMES,
    )


# ---------------------------------------------------------------------------
# PDF Raporlar
# ---------------------------------------------------------------------------

@reports_bp.route("/pdf/doctor/<int:party_id>")
@login_required
@permissions_required("reports.view")
def doctor_pdf(party_id: int):
    today = date.today()
    start_date, end_date, selected_period = resolve_period(
        today,
        request.args.get("period", "this_month"),
        request.args.get("start_date", ""),
        request.args.get("end_date", ""),
    )

    data = fetch_report_data(start_date, end_date)
    detail = build_doctor_detail(party_id, start_date, end_date, data["all_makbuzlar"], data["work_orders"])
    vat_data = build_vat_summary([
        m for m in data["makbuzlar"] if m.party_id == party_id
    ])

    period_lbl = _period_label(start_date, end_date)
    summary_rows = [
        ("İş emri sayısı", str(detail.doctor.work_order_count)),
        ("Toplam iş emri (₺)", f"{detail.doctor.total_try:,.2f}"),
        ("Aylık özet sayısı", str(detail.doctor.makbuz_count)),
        ("Aylık özet toplamı (₺)", f"{detail.doctor.makbuz_total_try:,.2f}"),
        ("Tahsil edilen (₺)", f"{detail.doctor.collected_try:,.2f}"),
        ("Açık bakiye (₺)", f"{detail.doctor.outstanding_try:,.2f}"),
        ("Devreden borç (₺)", f"{detail.doctor.previous_debt:,.2f}"),
    ]
    vat_list = [
        {"label": v.label, "gross": v.gross, "vat_amount": v.vat_amount, "net": v.net}
        for v in vat_data
    ]
    aging_list = [
        {"label": b.label, "count": b.count, "amount": b.amount}
        for b in detail.aging if b.amount > 0
    ]

    pdf_bytes = __import__("app.services.reports_pdf_service", fromlist=["generate_doctor_report_pdf"]).generate_doctor_report_pdf(
        clinic_name=_get_setting("clinic_name", "Makro Ortodonti"),
        clinic_phone=_get_setting("clinic_phone"),
        clinic_email=_get_setting("clinic_email"),
        title="DOKTOR RAPORU",
        subtitle=period_lbl,
        doctor_name=detail.doctor.doctor_name,
        period_label=period_lbl,
        summary_rows=summary_rows,
        work_orders=detail.work_orders,
        makbuzlar=detail.makbuzlar,
        aging_rows=aging_list,
        vat_summary=vat_list,
    )

    filename = f"doktor_raporu_{detail.doctor.doctor_name.replace(' ', '_')}_{start_date.isoformat()}.pdf"
    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


@reports_bp.route("/pdf/period")
@login_required
@permissions_required("reports.view")
def period_pdf():
    today = date.today()
    start_date, end_date, selected_period = resolve_period(
        today,
        request.args.get("period", "this_month"),
        request.args.get("start_date", ""),
        request.args.get("end_date", ""),
    )

    data = fetch_report_data(start_date, end_date)

    overview = build_period_overview(
        start_date, end_date,
        data["invoices"], data["payments"],
        data["work_orders"], data["makbuzlar"], data["all_makbuzlar"],
        data.get("receivable_invoices"),
    )
    doctor_summaries = build_doctor_summaries(
        start_date, end_date,
        data["work_orders"], data["all_makbuzlar"],
    )
    aging = build_aging_buckets(end_date, data["all_makbuzlar"], data.get("receivable_invoices"))
    vat_data = build_vat_summary(data["makbuzlar"])

    period_lbl = _period_label(start_date, end_date)
    summary_rows = [
        ("Toplam faturalanan (₺)", f"{overview.issued_try:,.2f}"),
        ("Toplam tahsil (₺)", f"{overview.collected_try:,.2f}"),
        ("Açık bakiye (₺)", f"{overview.outstanding_try:,.2f}"),
        ("Tahsilat oranı", f"%{overview.collection_ratio}"),
        ("İş emri sayısı", str(overview.work_order_count)),
        ("Aylık özet sayısı", str(overview.makbuz_count)),
        ("Ödeme hareketi", str(overview.payment_count)),
    ]
    doctor_rows = [
        {
            "doctor_name": d.doctor_name,
            "work_order_count": d.work_order_count,
            "total_try": d.total_try,
            "collected_try": d.collected_try,
            "outstanding_try": d.outstanding_try,
            "previous_debt": d.previous_debt,
        }
        for d in doctor_summaries
    ]
    vat_list = [
        {"label": v.label, "gross": v.gross, "vat_amount": v.vat_amount, "net": v.net}
        for v in vat_data
    ]
    aging_list = [
        {"label": b.label, "count": b.count, "amount": b.amount}
        for b in aging if b.amount > 0
    ]

    from app.services.reports_pdf_service import generate_period_report_pdf
    pdf_bytes = generate_period_report_pdf(
        clinic_name=_get_setting("clinic_name", "Makro Ortodonti"),
        clinic_phone=_get_setting("clinic_phone"),
        clinic_email=_get_setting("clinic_email"),
        title="DÖNEMSEL RAPOR",
        period_label=period_lbl,
        summary_rows=summary_rows,
        doctor_rows=doctor_rows,
        aging_rows=aging_list,
        vat_summary=vat_list,
    )

    filename = f"donemsel_rapor_{start_date.isoformat()}_{end_date.isoformat()}.pdf"
    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


@reports_bp.route("/kdv-doctors")
@login_required
@permissions_required("reports.view")
def kdv_doctors():
    """KDV uygulanan doktorların aylık önizleme ve dönem seçim ekranı."""
    from app.constants import MONTHS

    year, month = _resolve_year_month()
    rows = _build_kdv_doctor_rows(year, month)
    return render_template(
        "reports/kdv_doctors.html",
        rows=rows,
        year=year,
        month=month,
        months=MONTHS,
        years=range(date.today().year + 1, date.today().year - 4, -1),
        total_net=sum((row["net_total"] for row in rows), Decimal("0.00")),
        total_vat=sum((row["vat_total"] for row in rows), Decimal("0.00")),
        total_grand=sum((row["grand_total"] for row in rows), Decimal("0.00")),
    )


@reports_bp.route("/kdv-doctors/pdf")
@login_required
@permissions_required("reports.view")
def kdv_doctors_pdf():
    """KDV ödeyen doktorların aylık iş hacmi ve KDV tutarları raporu (PDF)."""
    from app.services.reports_pdf_service import generate_kdv_doctors_pdf
    from app.services.settings_service import get_clinic_identity

    year, month = _resolve_year_month()
    doctor_data = _build_kdv_doctor_rows(year, month)

    clinic = get_clinic_identity()
    from app.constants import MONTHS
    period_lbl = f"{MONTHS[month - 1][1]} {year}"

    pdf_bytes = generate_kdv_doctors_pdf(
        clinic_name=clinic["clinic_name"],
        clinic_phone=clinic["clinic_phone"],
        clinic_email=clinic["clinic_email"],
        period_label=period_lbl,
        kdv_doctors_data=doctor_data,
    )

    filename = f"kdv_odeyen_doktorlar_{year}_{month:02d}.pdf"
    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )
