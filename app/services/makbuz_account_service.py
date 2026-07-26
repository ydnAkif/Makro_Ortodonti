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
    current_collected: Decimal
    current_outstanding: Decimal
    total_due: Decimal


def open_periods_before(makbuz: Makbuz) -> list[OpenPeriod]:
    rows = db.session.execute(
        db.select(Makbuz)
        .where(
            Makbuz.party_id == makbuz.party_id,
            (Makbuz.year * 100 + Makbuz.month) < (makbuz.year * 100 + makbuz.month),
            Makbuz.status.in_((Makbuz.STATUS_SENT, Makbuz.STATUS_PAID)),
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
        if row.outstanding_amount > 0
    ]


def account_statement(makbuz: Makbuz) -> AccountStatement:
    previous_periods = open_periods_before(makbuz)
    previous_balance = money(sum((row.outstanding for row in previous_periods), Decimal("0.00")))
    current_collected = makbuz.collected_amount
    current_outstanding = makbuz.outstanding_amount
    party_previous_balance = money(makbuz.party.previous_balance if makbuz.party else Decimal("0.00"))
    total_due = money(previous_balance + current_outstanding + party_previous_balance)
    return AccountStatement(
        previous_periods=previous_periods,
        previous_balance=previous_balance,
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
    if amount > makbuz.outstanding_amount:
        raise ValueError(
            f"Ödeme kalan ₺{makbuz.outstanding_amount:,.2f} bakiyeyi aşamaz."
        )

    entry = MakbuzPayment(
        makbuz=makbuz,
        payment_date=payment_date,
        amount=amount,
        method=method,
        reference=reference,
        notes=notes,
    )
    db.session.add(entry)
    db.session.flush()
    sync_makbuz_collection(makbuz)
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
