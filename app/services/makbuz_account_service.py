from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.extensions import db
from app.models.models import Makbuz, MakbuzPayment, money
from app.constants import MONTH_NAMES


@dataclass(frozen=True)
class OpenPeriod:
    makbuz: Makbuz
    period_label: str
    original_total: Decimal
    collected: Decimal
    outstanding: Decimal


@dataclass(frozen=True)
class AccountStatement:
    previous_periods: list[OpenPeriod]
    previous_balance: Decimal
    party_previous_balance: Decimal
    carried_over_balance: Decimal
    current_work_subtotal: Decimal
    current_vat_amount: Decimal
    current_month_total: Decimal
    current_collected: Decimal
    current_outstanding: Decimal
    total_due: Decimal


def open_periods_before(makbuz: Makbuz) -> list[OpenPeriod]:
    rows = db.session.execute(
        db.select(Makbuz)
        .where(
            Makbuz.party_id == makbuz.party_id,
            (Makbuz.year * 100 + Makbuz.month) < (makbuz.year * 100 + makbuz.month),
        )
        .order_by(Makbuz.year, Makbuz.month)
    ).scalars().all()

    return [
        OpenPeriod(
            makbuz=row,
            period_label=f"{MONTH_NAMES[row.month]} {row.year}",
            original_total=money(row.grand_total),
            collected=row.collected_amount,
            outstanding=row.outstanding_amount,
        )
        for row in rows
        if row.affects_balance and row.outstanding_amount > 0
    ]


def account_statement(makbuz: Makbuz) -> AccountStatement:
    previous_periods = open_periods_before(makbuz)
    previous_balance = money(sum((row.outstanding for row in previous_periods), Decimal("0.00")))
    party_previous_balance = money(
        makbuz.party.previous_balance_outstanding if makbuz.party else Decimal("0.00")
    )
    carried_over_balance = money(previous_balance + party_previous_balance)

    current_work_subtotal = money(makbuz.subtotal)
    current_vat_amount = money(makbuz.vat_amount)
    current_month_total = money(makbuz.grand_total)
    current_collected = makbuz.collected_amount
    current_outstanding = makbuz.outstanding_amount
    total_due = money(carried_over_balance + current_outstanding)

    return AccountStatement(
        previous_periods=previous_periods,
        previous_balance=previous_balance,
        party_previous_balance=party_previous_balance,
        carried_over_balance=carried_over_balance,
        current_work_subtotal=current_work_subtotal,
        current_vat_amount=current_vat_amount,
        current_month_total=current_month_total,
        current_collected=current_collected,
        current_outstanding=current_outstanding,
        total_due=total_due,
    )


def record_payment(
    makbuz: Makbuz,
    *,
    payment_date: date,
    amount: Decimal,
    method: str,
    reference: str | None = None,
    notes: str | None = None,
) -> MakbuzPayment:
    amount = money(amount)
    if amount <= 0:
        raise ValueError("Geçerli bir ödeme tutarı girin.")

    statement = account_statement(makbuz)
    limit = statement.total_due if statement.total_due > 0 else makbuz.outstanding_amount

    if amount > limit:
        raise ValueError(
            f"Ödeme kalan ₺{limit:,.2f} bakiyeyi aşamaz."
        )

    original_outstanding = makbuz.outstanding_amount
    makbuz_payment_amount = min(amount, original_outstanding)
    excess = amount - makbuz_payment_amount

    # 1. Record payment entry for current makbuz
    entry = MakbuzPayment(
        makbuz=makbuz,
        payment_date=payment_date,
        amount=makbuz_payment_amount,
        method=method,
        reference=reference,
        notes=notes,
    )
    db.session.add(entry)
    db.session.flush()
    sync_makbuz_collection(makbuz)

    # 2. Allocate excess over current makbuz to older open periods or party.previous_balance
    if excess > 0:
        for prev_period in statement.previous_periods:
            if excess <= 0:
                break
            prev_makbuz = prev_period.makbuz
            apply_to_prev = min(excess, prev_makbuz.outstanding_amount)
            if apply_to_prev > 0:
                prev_entry = MakbuzPayment(
                    makbuz=prev_makbuz,
                    payment_date=payment_date,
                    amount=apply_to_prev,
                    method=method,
                    reference=reference,
                    notes=f"Aktarılan tahsilat ({makbuz.year}-{makbuz.month:02d})",
                )
                db.session.add(prev_entry)
                db.session.flush()
                sync_makbuz_collection(prev_makbuz)
                excess -= apply_to_prev

    if excess > 0 and makbuz.party and makbuz.party.previous_balance_outstanding:
        prev_bal = makbuz.party.previous_balance_outstanding
        deduct = min(excess, prev_bal)
        from app.models.models import PartyPayment
        party_payment = PartyPayment(
            party_id=makbuz.party.id,
            payment_date=payment_date,
            amount=deduct,
            method=method,
            reference=reference,
            notes=f"Devreden borç tahsilatı ({makbuz.year}-{makbuz.month:02d})",
        )
        db.session.add(party_payment)
        makbuz.party.previous_balance_payments.append(party_payment)
        db.session.flush()
        excess -= deduct

    return entry


def sync_makbuz_collection(makbuz: Makbuz) -> None:
    total = money(sum((entry.amount for entry in makbuz.payment_entries), Decimal("0.00")))
    latest = max(makbuz.payment_entries, key=lambda entry: (entry.payment_date, entry.id or 0), default=None)

    makbuz.paid_amount = total if total > 0 else None
    makbuz.paid_at = latest.payment_date if latest else None
    makbuz.payment_method = latest.method if latest else None
    makbuz.payment_reference = latest.reference if latest else None
    makbuz.status = (
        Makbuz.STATUS_PAID
        if total >= makbuz.grand_total and makbuz.grand_total > 0
        else Makbuz.STATUS_SENT if makbuz.sent_at else Makbuz.STATUS_DRAFT
    )
