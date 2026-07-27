from __future__ import annotations

from datetime import date
from decimal import Decimal
from app.extensions import db
from app.models.models import Party, PartyType, WorkOrder, Makbuz, money
from app.services.makbuz_service import generate_makbuz
from app.services.makbuz_account_service import account_statement, record_payment


def test_v3_carried_over_debt_does_not_recalculate_vat(app):
    """Test V3 core math rule:

    - Month 1: 5000 TL + 10% KDV = 5500 TL.
    - Doctor pays 2000 TL. Carried over debt = 3500 TL.
    - Month 2: 3000 TL + 10% KDV = 3300 TL.
    - Month 2 statement shows:
        - Current work subtotal: 3000 TL
        - Current VAT: 300 TL
        - Current month total: 3300 TL
        - Carried over balance: 3500 TL (NO extra VAT calculated on 3500 TL!)
        - Total due: 6800 TL (3300 + 3500)
    """
    with app.app_context():
        doctor = Party(party_type=PartyType.DENTIST, name="Dr. V3 Test Math", phone="+905559998877", applies_kdv=True)
        db.session.add(doctor)
        db.session.commit()
        doctor_id = doctor.id

        # Month 1: June 2026 work order
        wo1 = WorkOrder(
            party_id=doctor_id,
            work_date=date(2026, 6, 1),
            apparatus_type="Tester Appliance 1",
            patient_name="Hasta 1",
            apparatus_price=Decimal("5000.00"),
            extra_price=Decimal("0.00"),
            total_price=Decimal("5000.00"),
        )
        db.session.add(wo1)
        db.session.commit()

        june_makbuz = generate_makbuz(doctor_id, 2026, 6, vat_applied=True, vat_rate=Decimal("10.00"))
        assert june_makbuz.subtotal == Decimal("5000.00")
        assert june_makbuz.vat_amount == Decimal("500.00")
        assert june_makbuz.grand_total == Decimal("5500.00")

        # Doctor pays 2000 TL on June 5
        record_payment(
            june_makbuz,
            payment_date=date(2026, 6, 5),
            amount=Decimal("2000.00"),
            method="transfer",
            notes="Partial payment",
        )
        db.session.commit()

        assert june_makbuz.collected_amount == Decimal("2000.00")
        assert june_makbuz.outstanding_amount == Decimal("3500.00")

        # Month 2: July 2026 work order
        wo2 = WorkOrder(
            party_id=doctor_id,
            work_date=date(2026, 7, 1),
            apparatus_type="Tester Appliance 2",
            patient_name="Hasta 2",
            apparatus_price=Decimal("3000.00"),
            extra_price=Decimal("0.00"),
            total_price=Decimal("3000.00"),
        )
        db.session.add(wo2)
        db.session.commit()

        july_makbuz = generate_makbuz(doctor_id, 2026, 7, vat_applied=True, vat_rate=Decimal("10.00"))
        assert july_makbuz.subtotal == Decimal("3000.00")
        assert july_makbuz.vat_amount == Decimal("300.00")
        assert july_makbuz.grand_total == Decimal("3300.00")

        # Account statement for July
        stmt = account_statement(july_makbuz)

        assert stmt.current_work_subtotal == Decimal("3000.00")
        assert stmt.current_vat_amount == Decimal("300.00")
        assert stmt.current_month_total == Decimal("3300.00")
        assert stmt.carried_over_balance == Decimal("3500.00")
        assert stmt.total_due == Decimal("6800.00")


def test_v3_opening_balance_included_in_carried_over_balance(app):
    """Test physical ledger opening balance (previous_balance) integration."""
    with app.app_context():
        doctor = Party(
            party_type=PartyType.DENTIST,
            name="Dr. Opening Debt Test",
            phone="+905559998866",
            previous_balance=Decimal("1500.00"),  # 1500 TL ledger debt from June
        )
        db.session.add(doctor)
        db.session.commit()
        doctor_id = doctor.id

        wo = WorkOrder(
            party_id=doctor_id,
            work_date=date(2026, 7, 10),
            apparatus_type="Aligner",
            patient_name="Hasta 3",
            apparatus_price=Decimal("2000.00"),
            total_price=Decimal("2000.00"),
        )
        db.session.add(wo)
        db.session.commit()

        makbuz = generate_makbuz(doctor_id, 2026, 7, vat_applied=False, vat_rate=Decimal("0.00"))
        stmt = account_statement(makbuz)

        assert stmt.party_previous_balance == Decimal("1500.00")
        assert stmt.carried_over_balance == Decimal("1500.00")
        assert stmt.current_month_total == Decimal("2000.00")
        assert stmt.total_due == Decimal("3500.00")
