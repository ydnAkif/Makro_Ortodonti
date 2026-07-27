from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models.models import Party, PartyType, Makbuz, MakbuzPayment, PartyPayment, money
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

    party_payment_query = db.select(PartyPayment)
    if year:
        party_payment_query = party_payment_query.where(
            db.extract("year", PartyPayment.payment_date) == year
        )
    all_party_payments = db.session.execute(party_payment_query).scalars().all()
    party_payments_by_party: dict[int, list[PartyPayment]] = {}
    for payment in all_party_payments:
        party_payments_by_party.setdefault(payment.party_id, []).append(payment)

    rows = []
    for party in doctors:
        m_list = by_party.get(party.id, [])
        financial_makbuzlar = [m for m in m_list if m.affects_balance]
        billed = money(sum(
            (m.grand_total for m in financial_makbuzlar),
            Decimal("0.00"),
        ))
        # Tahsil edilen, kasaya giren gerçek hareket toplamıdır. Bir ödeme
        # hem güncel makbuzu hem de devreden borcu kapatabileceği için bunu
        # makbuz tutarıyla sınırlamayız.
        paid = money(sum(
            (
                sum((entry.amount for entry in m.payment_entries), Decimal("0.00"))
                if m.payment_entries
                else (m.paid_amount or Decimal("0.00"))
                for m in m_list
            ),
            Decimal("0.00"),
        ) + sum(
            (payment.amount for payment in party_payments_by_party.get(party.id, [])),
            Decimal("0.00"),
        ))
        prev_bal = party.previous_balance_outstanding
        # Açık bakiye, gerçek tahsilattan bağımsız olarak henüz
        # kapanmamış makbuzlar ve kalan devreden borçtan oluşur. Billed -
        # paid hesabı, devreden borca uygulanan tahsilatı ikinci kez düşürür.
        outstanding = money(sum(
            (m.outstanding_amount for m in financial_makbuzlar),
            Decimal("0.00"),
        ) + prev_bal)
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

    pending_makbuzlar = [
        m for m in all_makbuzlar
        if m.affects_balance
        and m.outstanding_amount > 0
        and m.party_id in visible_party_ids
    ]
    for m in pending_makbuzlar:
        statement = account_statement(m)
        m._effective_outstanding = statement.total_due
        m._payment_total = money(sum(
            (entry.amount for entry in m.payment_entries),
            Decimal("0.00"),
        )) if m.payment_entries else money(m.paid_amount or Decimal("0.00"))

    pending_party_ids = {m.party_id for m in pending_makbuzlar}
    for doctor in doctors:
        if doctor.id not in pending_party_ids:
            doc_makbuzlar = [m for m in all_makbuzlar if m.party_id == doctor.id]
            if doc_makbuzlar:
                latest_m = max(doc_makbuzlar, key=lambda m: (m.year, m.month))
                statement = account_statement(latest_m)
                if statement.total_due > 0:
                    latest_m._effective_outstanding = statement.total_due
                    latest_m._payment_total = money(sum(
                        (entry.amount for entry in latest_m.payment_entries),
                        Decimal("0.00"),
                    )) if latest_m.payment_entries else money(latest_m.paid_amount or Decimal("0.00"))
                    pending_makbuzlar.append(latest_m)
                    pending_party_ids.add(doctor.id)

    pending_makbuzlar.sort(key=lambda m: (m.year, m.month), reverse=True)
    payment_entries = sorted(
        (
            entry for m in all_makbuzlar
            if m.party_id in visible_party_ids
            for entry in m.payment_entries
        ),
        key=lambda entry: (entry.payment_date, entry.id),
        reverse=True,
    )
    party_payment_entries = sorted(
        (
            payment for payment in all_party_payments
            if payment.party_id in visible_party_ids
        ),
        key=lambda payment: (payment.payment_date, payment.id),
        reverse=True,
    )

    years = sorted({m.year for m in db.session.execute(db.select(Makbuz)).scalars().all()} | {date.today().year}, reverse=True)

    pending_doctors = [r for r in rows if r["outstanding"] > 0]
    previous_balance_rows = [
        {"party": doctor, "outstanding": doctor.previous_balance_outstanding}
        for doctor in doctors
        if doctor.previous_balance_outstanding > 0
    ]

    return render_template(
        "payments/list.html",
        rows=rows,
        pending_doctors=pending_doctors,
        pending_makbuzlar=pending_makbuzlar,
        payment_entries=payment_entries,
        party_payment_entries=party_payment_entries,
        previous_balance_rows=previous_balance_rows,
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
        flash("Bu aylık hesap özetinin açık bakiyesi bulunmuyor.", "info")
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
            print("MARK PAID EXC:", exc)
            flash(str(exc), "danger")
            return redirect(url_for("payments.mark_paid", makbuz_id=makbuz.id))

        if makbuz.outstanding_amount > 0:
            flash(
                f"Kısmi ödeme kaydedildi: ₺{paid_amount:,.2f}. "
                f"Kalan bakiye: ₺{makbuz.outstanding_amount:,.2f}",
                "success",
            )
            return redirect(url_for("payments.list_payments", tab="pending"))

        flash(f"Ödeme kaydedildi ve dönem bakiyesi kapandı: ₺{paid_amount:,.2f}", "success")
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


@payments_bp.route("/parties/<int:party_id>/previous-balance", methods=["GET", "POST"])
@login_required
@permissions_required("billing.edit")
def pay_previous_balance(party_id):
    party = db.get_or_404(Party, party_id)
    outstanding = party.previous_balance_outstanding
    if outstanding <= 0:
        flash("Bu doktorun açık devreden borcu bulunmuyor.", "info")
        return redirect(url_for("payments.list_payments"))

    if request.method == "POST":
        from app.services.validation_service import parse_date, parse_decimal

        payment_date = parse_date(request.form.get("paid_at", "")) or date.today()
        amount = parse_decimal(request.form.get("paid_amount", ""))
        method = request.form.get("payment_method", "cash")
        reference = request.form.get("payment_reference", "").strip() or None
        notes = request.form.get("notes", "").strip() or None

        if amount is None or amount <= 0:
            flash("Geçerli bir ödeme tutarı girin.", "danger")
            return redirect(url_for("payments.pay_previous_balance", party_id=party.id))
        if amount > outstanding:
            flash(f"Ödeme ₺{outstanding:,.2f} devreden borcu aşamaz.", "danger")
            return redirect(url_for("payments.pay_previous_balance", party_id=party.id))
        if method not in METHOD_LABELS:
            flash("Geçerli bir ödeme yöntemi seçin.", "danger")
            return redirect(url_for("payments.pay_previous_balance", party_id=party.id))

        db.session.add(PartyPayment(
            party=party,
            payment_date=payment_date,
            amount=amount,
            method=method,
            reference=reference,
            notes=notes,
        ))
        db.session.commit()
        remaining = party.previous_balance_outstanding
        if remaining > 0:
            flash(
                f"Devreden borç tahsilatı kaydedildi: ₺{amount:,.2f}. "
                f"Kalan: ₺{remaining:,.2f}",
                "success",
            )
        else:
            flash(f"Devreden borç tamamen kapatıldı: ₺{amount:,.2f}", "success")
        return redirect(url_for("payments.list_payments", tab="paid"))

    return render_template(
        "payments/previous_balance_form.html",
        party=party,
        outstanding=outstanding,
        method_labels=METHOD_LABELS,
        today=date.today(),
    )


@payments_bp.route("/<int:makbuz_id>/unmark-paid", methods=["POST"])
@login_required
@permissions_required("billing.cancel_makbuz")
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
@permissions_required("billing.delete_payment")
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


@payments_bp.route("/party-entries/<int:payment_id>/delete", methods=["POST"])
@login_required
@permissions_required("billing.delete_payment")
def delete_party_payment(payment_id):
    payment = db.get_or_404(PartyPayment, payment_id)
    amount = payment.amount
    db.session.delete(payment)
    db.session.commit()
    flash(
        f"₺{amount:,.2f} tutarındaki devreden borç tahsilatı silindi; borç yeniden açıldı.",
        "warning",
    )
    return redirect(url_for("payments.list_payments", tab="paid"))
