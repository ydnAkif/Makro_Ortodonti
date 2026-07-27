from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, make_response
from flask_login import login_required
from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models.models import WorkOrder, Party, Makbuz, MakbuzSendLog
from app.authz import permissions_required
from sqlalchemy import extract
from app.services.validation_service import parse_date

makbuzlar_bp = Blueprint("makbuzlar", __name__)

from app.constants import MONTHS, VAT_RATE
from app.services.makbuz_service import resolve_makbuzlar_query

STATUS_LABELS = {
    Makbuz.STATUS_DRAFT: "Taslak",
    Makbuz.STATUS_SENT: "Tahsilat bekliyor",
    Makbuz.STATUS_PAID: "Ödendi",
}


def _work_orders_for_period(party_id: int, year: int, month: int) -> list[WorkOrder]:
    return db.session.execute(
        db.select(WorkOrder)
        .where(
            WorkOrder.party_id == party_id,
            extract("year", WorkOrder.work_date) == year,
            extract("month", WorkOrder.work_date) == month,
        )
        .order_by(WorkOrder.work_date.desc())
    ).scalars().all()


def _existing_makbuzlar(year: int, month: int) -> dict[int, Makbuz]:
    rows = db.session.execute(
        db.select(Makbuz).where(Makbuz.year == year, Makbuz.month == month)
    ).scalars().all()
    return {m.party_id: m for m in rows}


def _parse_vat_form(prefix: str = "") -> tuple[bool, Decimal]:
    vat_applied = request.form.get(f"{prefix}vat_applied") in ("on", "true", "1")
    return vat_applied, VAT_RATE if vat_applied else Decimal("0.00")


def _generate_makbuz(party_id: int, year: int, month: int, vat_applied: bool, vat_rate: Decimal) -> Makbuz:
    """Geriye dönük uyumluluk için delegate — gerçek mantık makbuz_service.generate_makbuz'da."""
    from app.services.makbuz_service import generate_makbuz
    return generate_makbuz(party_id, year, month, vat_applied=vat_applied, vat_rate=vat_rate)


def _send_makbuz(makbuz: Makbuz) -> tuple[bool, str]:
    from app.services.makbuz_send_queue import send_makbuz_via_whatsapp

    return send_makbuz_via_whatsapp(makbuz.id)



@makbuzlar_bp.route("/", strict_slashes=False)
@login_required
@permissions_required("billing.view")
def list_makbuzlar():
    data = resolve_makbuzlar_query(request.args)
    data["sending"] = request.args.get("sending") == "1"
    return render_template("makbuzlar/list.html", **data)


@makbuzlar_bp.route("/pdf", strict_slashes=False)
@login_required
@permissions_required("billing.view")
def export_makbuzlar_pdf():
    """Aylık hesap özeti listesini PDF olarak dışa aktar."""
    from flask import Response
    from app.services.reports_pdf_service import generate_makbuz_list_pdf
    from app.services.settings_service import get_clinic_identity

    data = resolve_makbuzlar_query(request.args)
    clinic = get_clinic_identity()

    pdf_bytes = generate_makbuz_list_pdf(
        clinic_name=clinic["clinic_name"],
        clinic_phone=clinic["clinic_phone"],
        clinic_email=clinic["clinic_email"],
        period_label=data["period_label"],
        doctors=data["doctors"],
        grand_total_price=data["grand_total_price"],
    )

    filename = f"aylik_hesap_ozetleri_{data['view']}_{data['period_label'].replace(' ', '_').lower()}.pdf"
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@makbuzlar_bp.route("/<int:party_id>")
@login_required
@permissions_required("billing.view")
def detail_makbuz(party_id):
    party = db.get_or_404(Party, party_id)
    year = request.args.get("year", date.today().year, type=int)
    month = request.args.get("month", date.today().month, type=int)

    work_orders = _work_orders_for_period(party_id, year, month)

    total_apparatus = sum((wo.apparatus_price for wo in work_orders), Decimal("0.00"))
    total_extra = sum((wo.extra_price for wo in work_orders), Decimal("0.00"))
    total_price = sum((wo.total_price for wo in work_orders), Decimal("0.00"))

    makbuz = db.session.execute(
        db.select(Makbuz).where(
            Makbuz.party_id == party_id, Makbuz.year == year, Makbuz.month == month
        )
    ).scalar_one_or_none()
    statement = None
    if makbuz:
        from app.services.makbuz_account_service import account_statement

        statement = account_statement(makbuz)

    return render_template(
        "makbuzlar/detail.html",
        party=party,
        work_orders=work_orders,
        year=year,
        month=month,
        months=MONTHS,
        status_labels=STATUS_LABELS,
        makbuz=makbuz,
        statement=statement,
        total_apparatus=total_apparatus,
        total_extra=total_extra,
        total_price=total_price,
    )


@makbuzlar_bp.route("/<int:party_id>/generate", methods=["POST"])
@login_required
@permissions_required("billing.edit")
def generate_makbuz(party_id):
    year = request.form.get("year", date.today().year, type=int)
    month = request.form.get("month", date.today().month, type=int)
    vat_applied, vat_rate = _parse_vat_form()

    try:
        party = db.get_or_404(Party, party_id)
        party.applies_kdv = vat_applied
        makbuz = _generate_makbuz(party_id, year, month, vat_applied, vat_rate)
        db.session.commit()
        flash(f"Aylık hesap özeti güncellendi: ₺{makbuz.grand_total:,.2f}", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")

    return redirect(url_for("makbuzlar.detail_makbuz", party_id=party_id, year=year, month=month))


@makbuzlar_bp.route("/<int:makbuz_id>/pdf")
@login_required
@permissions_required("billing.view")
def pdf_makbuz(makbuz_id):
    """Aylık hesap özetini göndermeden önce tarayıcıda önizle veya indir."""
    from app.services.makbuz_pdf_service import generate_makbuz_pdf

    makbuz = db.get_or_404(Makbuz, makbuz_id)
    work_orders = _work_orders_for_period(makbuz.party_id, makbuz.year, makbuz.month)
    pdf_bytes = generate_makbuz_pdf(makbuz, work_orders)

    filename = f"aylik_hesap_ozeti_{makbuz.year}_{makbuz.month:02d}_{makbuz.party_id}.pdf"
    disposition = "attachment" if request.args.get("download") else "inline"
    response = make_response(pdf_bytes)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    return response


@makbuzlar_bp.route("/<int:makbuz_id>/send", methods=["POST"])
@login_required
@permissions_required("billing.edit")
def send_makbuz(makbuz_id):
    makbuz = db.get_or_404(Makbuz, makbuz_id)
    success, message = _send_makbuz(makbuz)
    flash(message, "success" if success else "danger")
    if request.form.get("return_to") == "list":
        return redirect(url_for(
            "makbuzlar.list_makbuzlar",
            year=makbuz.year,
            month=makbuz.month,
        ))
    return redirect(url_for("makbuzlar.detail_makbuz", party_id=makbuz.party_id, year=makbuz.year, month=makbuz.month))


@makbuzlar_bp.route("/bulk-send", methods=["POST"])
@login_required
@permissions_required("billing.edit")
def bulk_send_makbuzlar():
    """Send the selected doctors' ready drafts as one background batch."""
    from app.services.makbuz_send_queue import MakbuzSendQueue

    year = request.form.get("year", date.today().year, type=int)
    month = request.form.get("month", date.today().month, type=int)
    party_ids = request.form.getlist("party_ids", type=int)

    if not party_ids:
        flash("Gönderilecek doktor seçilmedi.", "danger")
        return redirect(url_for("makbuzlar.list_makbuzlar", year=year, month=month))

    makbuz_ids = db.session.execute(
        db.select(Makbuz.id).where(
            Makbuz.party_id.in_(party_ids),
            Makbuz.year == year,
            Makbuz.month == month,
            Makbuz.status == Makbuz.STATUS_DRAFT,
        )
    ).scalars().all()

    if not makbuz_ids:
        flash("Seçilen doktorlar için gönderilmeye hazır aylık özet yok.", "danger")
        return redirect(url_for("makbuzlar.list_makbuzlar", year=year, month=month))

    started, message = MakbuzSendQueue.start_batch(makbuz_ids)
    flash(message, "info" if started else "danger")
    return redirect(url_for(
        "makbuzlar.list_makbuzlar",
        year=year,
        month=month,
        sending=1 if started else None,
    ))


@makbuzlar_bp.route("/send-status")
@login_required
@permissions_required("billing.view")
def send_status():
    from app.services.makbuz_send_queue import MakbuzSendQueue

    return jsonify({"send_job": MakbuzSendQueue.current_job()})


@makbuzlar_bp.route("/bulk-generate", methods=["POST"])
@login_required
@permissions_required("billing.edit")
def bulk_generate_drafts():
    year = request.form.get("year", date.today().year, type=int)
    month = request.form.get("month", date.today().month, type=int)
    party_ids = request.form.getlist("party_ids", type=int)

    if not party_ids:
        flash("Taslak oluşturulacak doktor seçilmedi.", "danger")
        return redirect(url_for("makbuzlar.list_makbuzlar", year=year, month=month))

    generated, failed = 0, 0
    for pid in party_ids:
        vat_applied, vat_rate = _parse_vat_form(prefix=f"vat_{pid}_")
        try:
            party = db.session.get(Party, pid)
            if party:
                party.applies_kdv = vat_applied
            _generate_makbuz(pid, year, month, vat_applied, vat_rate)
            db.session.commit()
            generated += 1
        except ValueError:
            db.session.rollback()
            failed += 1

    message = f"{generated} aylık hesap özeti oluşturuldu veya güncellendi."
    if failed:
        message += f" {failed} tahsilat hareketi bulunan özet değiştirilemedi."
    flash(message, "success" if not failed else "warning")
    return redirect(url_for("makbuzlar.list_makbuzlar", year=year, month=month))


@makbuzlar_bp.route("/bulk-delete", methods=["POST"])
@login_required
@permissions_required("billing.edit")
def bulk_delete_makbuzlar():
    """Tahsilat hareketi bulunmayan seçili aylık hesap özetlerini siler."""
    year = request.form.get("year", date.today().year, type=int)
    month = request.form.get("month", date.today().month, type=int)
    party_ids = request.form.getlist("party_ids", type=int)

    if not party_ids:
        flash("Silinecek doktor seçilmedi.", "danger")
        return redirect(url_for("makbuzlar.list_makbuzlar", year=year, month=month))

    makbuzlar = db.session.execute(
        db.select(Makbuz).where(
            Makbuz.party_id.in_(party_ids),
            Makbuz.year == year,
            Makbuz.month == month,
        )
    ).scalars().all()

    if not makbuzlar:
        flash("Seçilen doktorlar için silinecek aylık özet bulunamadı.", "warning")
        return redirect(url_for("makbuzlar.list_makbuzlar", year=year, month=month))

    deletable = [m for m in makbuzlar if not m.payment_entries and m.collected_amount <= 0]
    protected_count = len(makbuzlar) - len(deletable)
    for m in deletable:
        db.session.execute(
            db.update(MakbuzSendLog).where(MakbuzSendLog.makbuz_id == m.id).values(makbuz_id=None)
        )
        db.session.delete(m)
    db.session.commit()
    if deletable:
        flash(f"{len(deletable)} aylık hesap özeti silindi.", "success")
    if protected_count:
        flash(f"{protected_count} özette tahsilat hareketi bulunduğu için silinmedi.", "warning")
    return redirect(url_for("makbuzlar.list_makbuzlar", year=year, month=month))


@makbuzlar_bp.route("/<int:makbuz_id>/delete", methods=["POST"])
@login_required
@permissions_required("billing.edit")
def delete_makbuz(makbuz_id):
    """Tahsilat hareketi bulunmayan tek bir aylık hesap özetini siler."""
    makbuz = db.get_or_404(Makbuz, makbuz_id)

    party_id = makbuz.party_id
    year = makbuz.year
    month = makbuz.month

    if makbuz.payment_entries or makbuz.collected_amount > 0:
        flash("Bu hesap özetinde tahsilat hareketi var. Silmek için önce tahsilat kaydını geri alın.", "danger")
        return redirect(url_for("makbuzlar.detail_makbuz", party_id=party_id, year=year, month=month))

    db.session.execute(
        db.update(MakbuzSendLog).where(MakbuzSendLog.makbuz_id == makbuz_id).values(makbuz_id=None)
    )
    db.session.delete(makbuz)
    db.session.commit()
    flash("Aylık hesap özeti silindi.", "warning")
    return redirect(url_for("makbuzlar.detail_makbuz", party_id=party_id, year=year, month=month))


@makbuzlar_bp.route("/api/exchange-rate")
@login_required
@permissions_required("billing.edit")
def get_exchange_rate_for_date():
    """Return the EUR/TRY rate for the requested date."""
    target_date = parse_date(request.args.get("date", ""))
    if not target_date:
        return jsonify({"error": "Geçersiz tarih"}), 400

    from app.services.exchange_service import get_rate_for_date
    rate = get_rate_for_date(target_date)
    if not rate:
        return jsonify({"error": "Bu tarih için kur bulunamadı"}), 404

    return jsonify({
        "rate": float(rate.eur_to_try),
        "usd_rate": float(rate.usd_to_try) if rate.usd_to_try is not None else None,
        "rate_date": rate.rate_date.isoformat(),
        "display_date": rate.rate_date.strftime("%d.%m.%Y"),
        "source": rate.source,
    })
