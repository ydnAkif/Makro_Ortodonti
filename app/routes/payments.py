from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models.models import Party, PartyType, Makbuz, MakbuzPayment, money
from app.authz import permissions_required

payments_bp = Blueprint("payments", __name__)

METHOD_LABELS = {
    "cash": "Nakit",
    "card": "Kredi / Banka Kartı",
    "transfer": "Havale / EFT",
    "check": "Çek",
    "other": "Diğer",
}


@payments_bp.route("/")
@login_required
@permissions_required("billing.view")
def list_payments():
    search = request.args.get("search", "").strip()
    year = request.args.get("year", type=int)
    active_tab = request.args.get("tab", "pending")
    if active_tab not in {"pending", "paid", "summary"}:
        active_tab = "pending"

    doctors_query = db.select(Party).where(
        Party.party_type == PartyType.DENTIST, Party.is_active.is_(True)
    )
    if search:
        from app.services.search_service import tr_contains

        doctors_query = doctors_query.where(tr_contains(Party.name, search))
    from app.services.search_service import tr_order

    doctors = db.session.execute(doctors_query.order_by(tr_order(Party.name))).scalars().all()

    makbuz_query = db.select(Makbuz)
    if year:
        makbuz_query = makbuz_query.where(Makbuz.year == year)
    all_makbuzlar = db.session.execute(makbuz_query).scalars().all()

    by_party: dict[int, list[Makbuz]] = {}
    for m in all_makbuzlar:
        by_party.setdefault(m.party_id, []).append(m)

    rows = []
    for party in doctors:
        m_list = by_party.get(party.id, [])
        billed = money(sum(
            (m.grand_total for m in m_list if m.status in (Makbuz.STATUS_SENT, Makbuz.STATUS_PAID)),
            Decimal("0.00"),
        ))
        paid = money(sum(
            (m.collected_amount for m in m_list),
            Decimal("0.00"),
        ))
        prev_bal = money(party.previous_balance or Decimal("0.00"))
        outstanding = money(billed - paid + prev_bal)
        rows.append({
            "party": party,
            "billed": billed,
            "paid": paid,
            "previous_balance": prev_bal,
            "outstanding": outstanding,
            "makbuz_count": len(m_list),
        })

    rows.sort(key=lambda r: r["outstanding"], reverse=True)

    grand_billed = money(sum((r["billed"] for r in rows), Decimal("0.00")))
    grand_paid = money(sum((r["paid"] for r in rows), Decimal("0.00")))
    grand_outstanding = money(sum((r["outstanding"] for r in rows), Decimal("0.00")))

    visible_party_ids = {party.id for party in doctors}
    from app.services.makbuz_account_service import account_statement

    pending_makbuzlar = sorted(
        (
            m for m in all_makbuzlar
            if m.status in (Makbuz.STATUS_SENT, Makbuz.STATUS_PAID)
            and m.party_id in visible_party_ids
        ),
        key=lambda m: (m.year, m.month),
        reverse=True,
    )
    for m in pending_makbuzlar:
        statement = account_statement(m)
        m._effective_outstanding = statement.total_due
    payment_entries = sorted(
        (
            entry for m in all_makbuzlar
            if m.party_id in visible_party_ids
            for entry in m.payment_entries
        ),
        key=lambda entry: (entry.payment_date, entry.id),
        reverse=True,
    )

    years = sorted({m.year for m in db.session.execute(db.select(Makbuz)).scalars().all()} | {date.today().year}, reverse=True)

    return render_template(
        "payments/list.html",
        rows=rows,
        pending_makbuzlar=pending_makbuzlar,
        payment_entries=payment_entries,
        method_labels=METHOD_LABELS,
        grand_billed=grand_billed,
        grand_paid=grand_paid,
        grand_outstanding=grand_outstanding,
        search=search,
        year=year,
        years=years,
        active_tab=active_tab,
    )


@payments_bp.route("/<int:makbuz_id>/mark-paid", methods=["GET", "POST"])
@login_required
@permissions_required("billing.edit")
def mark_paid(makbuz_id):
    makbuz = db.get_or_404(Makbuz, makbuz_id)
    if makbuz.outstanding_amount <= 0:
        flash("Bu makbuzun açık bakiyesi bulunmuyor.", "info")
        return redirect(url_for("payments.list_payments", tab="paid"))

    if request.method == "POST":
        from app.services.validation_service import parse_date, parse_decimal

        paid_date = parse_date(request.form.get("paid_at", "")) or date.today()
        paid_amount = parse_decimal(request.form.get("paid_amount", ""))
        method = request.form.get("payment_method", "cash")
        reference = request.form.get("payment_reference", "").strip() or None
        notes = request.form.get("notes", "").strip() or None

        if paid_amount is None or paid_amount <= 0:
            flash("Geçerli bir ödeme tutarı girin.", "danger")
            return redirect(url_for("payments.mark_paid", makbuz_id=makbuz.id))
        if method not in METHOD_LABELS:
            flash("Geçerli bir ödeme yöntemi seçin.", "danger")
            return redirect(url_for("payments.mark_paid", makbuz_id=makbuz.id))

        try:
            from app.services.makbuz_account_service import record_payment

            record_payment(
                makbuz,
                payment_date=paid_date,
                amount=paid_amount,
                method=method,
                reference=reference,
                notes=notes,
            )
            db.session.commit()
        except (TypeError, ValueError) as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return redirect(url_for("payments.mark_paid", makbuz_id=makbuz.id))

        if makbuz.outstanding_amount > 0:
            flash(
                f"Kısmi ödeme kaydedildi: ₺{paid_amount:,.2f}. "
                f"Kalan bakiye: ₺{makbuz.outstanding_amount:,.2f}",
                "success",
            )
            return redirect(url_for("payments.list_payments", tab="pending"))

        flash(f"Ödeme kaydedildi ve makbuz kapandı: ₺{paid_amount:,.2f}", "success")
        return redirect(url_for("payments.list_payments", tab="paid"))

    from app.services.makbuz_account_service import account_statement

    statement = account_statement(makbuz)
    effective_outstanding = statement.total_due

    return render_template(
        "payments/form.html",
        makbuz=makbuz,
        method_labels=METHOD_LABELS,
        today=date.today(),
        effective_outstanding=effective_outstanding,
        statement=statement,
    )


@payments_bp.route("/<int:makbuz_id>/unmark-paid", methods=["POST"])
@login_required
@permissions_required("billing.edit")
def unmark_paid(makbuz_id):
    makbuz = db.get_or_404(Makbuz, makbuz_id)
    for entry in list(makbuz.payment_entries):
        db.session.delete(entry)
    makbuz.status = Makbuz.STATUS_SENT if makbuz.sent_at else Makbuz.STATUS_DRAFT
    makbuz.paid_at = None
    makbuz.paid_amount = None
    makbuz.payment_method = None
    makbuz.payment_reference = None
    db.session.commit()
    flash("Makbuza ait tüm tahsilat hareketleri geri alındı.", "warning")
    return redirect(url_for("payments.list_payments"))


@payments_bp.route("/entries/<int:payment_id>/delete", methods=["POST"])
@login_required
@permissions_required("billing.edit")
def delete_payment(payment_id):
    payment = db.get_or_404(MakbuzPayment, payment_id)
    makbuz = payment.makbuz
    makbuz.payment_entries.remove(payment)
    db.session.flush()

    from app.services.makbuz_account_service import sync_makbuz_collection

    sync_makbuz_collection(makbuz)
    db.session.commit()
    flash(
        f"₺{payment.amount:,.2f} tutarındaki tahsilat hareketi silindi. "
        f"Güncel kalan: ₺{makbuz.outstanding_amount:,.2f}",
        "warning",
    )
    return redirect(url_for("payments.list_payments", tab="paid"))
