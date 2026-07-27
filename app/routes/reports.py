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


reports_bp = Blueprint("reports", __name__)


def _period_label(start: date, end: date) -> str:
    return f"{start.strftime('%d.%m.%Y')} – {end.strftime('%d.%m.%Y')}"


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
        ("Makbuz sayısı", str(detail.doctor.makbuz_count)),
        ("Toplam makbuz (₺)", f"{detail.doctor.makbuz_total_try:,.2f}"),
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
        ("Makbuz sayısı", str(overview.makbuz_count)),
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
