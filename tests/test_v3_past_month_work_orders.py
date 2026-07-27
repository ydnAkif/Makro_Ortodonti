from decimal import Decimal

from app.extensions import db
from app.models.models import Party, PartyType, Makbuz
from app.services.party_service import PartyService
from app.services.makbuz_account_service import account_statement


from conftest import login


def test_past_month_work_order_creates_makbuz_and_applies_kdv(app, client):
    login(client, "admin", "admin-pass")
    with app.app_context():
        # 1. Create a doctor with applies_kdv = True
        doctor = Party(
            party_type=PartyType.DENTIST,
            name="Dr. Past Month Test",
            applies_kdv=True,
            previous_balance=Decimal("320.00"),
        )
        db.session.add(doctor)
        db.session.commit()
        doc_id = doctor.id

        # 2. Add a work order for July 2026 (current month)
        PartyService.create_work_order(
            doc_id,
            {
                "work_date": "2026-07-28",
                "apparatus_type": "Dijital Model",
                "patient_name": "Aysel Mani",
                "apparatus_price": "3600.00",
                "extra_price": "0.00",
            },
        )

        # 3. Add a work order for June 2026 (past month)
        PartyService.create_work_order(
            doc_id,
            {
                "work_date": "2026-06-28",
                "apparatus_type": "Dijital Model",
                "patient_name": "Mahmut Tuncer",
                "apparatus_price": "500.00",
                "extra_price": "0.00",
            },
        )

        # 4. Verify June 2026 Makbuz exists and has KDV applied (500 + 10% = 550 TL)
        june_m = db.session.execute(
            db.select(Makbuz).where(
                Makbuz.party_id == doc_id,
                Makbuz.year == 2026,
                Makbuz.month == 6,
            )
        ).scalar_one_or_none()
        assert june_m is not None
        assert june_m.subtotal == Decimal("500.00")
        assert june_m.vat_applied is True
        assert june_m.vat_amount == Decimal("50.00")
        assert june_m.grand_total == Decimal("550.00")
        assert june_m.outstanding_amount == Decimal("550.00")

        # 5. Verify July 2026 Makbuz account statement includes June (550) + previous_balance (320) = 870 TL carried over
        july_m = db.session.execute(
            db.select(Makbuz).where(
                Makbuz.party_id == doc_id,
                Makbuz.year == 2026,
                Makbuz.month == 7,
            )
        ).scalar_one()
        stmt = account_statement(july_m)
        assert len(stmt.previous_periods) == 1
        assert stmt.previous_periods[0].outstanding == Decimal("550.00")
        assert stmt.carried_over_balance == Decimal("870.00")
        assert stmt.total_due == Decimal("4830.00")  # 3960 + 870

    # 6. Verify payments pending list includes 6/2026 Makbuz
    resp = client.get("/payments/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Dr. Past Month Test" in html
    assert "6/2026" in html


def test_toggling_applies_kdv_refreshes_all_party_makbuzlar(app):
    with app.app_context():
        doctor = Party(
            party_type=PartyType.DENTIST,
            name="Dr. KDV Toggle Test",
            applies_kdv=False,
        )
        db.session.add(doctor)
        db.session.commit()
        doc_id = doctor.id

        PartyService.create_work_order(
            doc_id,
            {
                "work_date": "2026-06-15",
                "apparatus_type": "Aparey",
                "patient_name": "Hasta X",
                "apparatus_price": "1000.00",
            },
        )

        m_before = db.session.execute(
            db.select(Makbuz).where(Makbuz.party_id == doc_id, Makbuz.year == 2026, Makbuz.month == 6)
        ).scalar_one()
        assert m_before.vat_applied is False
        assert m_before.grand_total == Decimal("1000.00")

        # Update doctor to enable applies_kdv
        PartyService.update_party(
            doc_id,
            {
                "name": "Dr. KDV Toggle Test",
                "applies_kdv": True,
            },
        )

        m_after = db.session.execute(
            db.select(Makbuz).where(Makbuz.party_id == doc_id, Makbuz.year == 2026, Makbuz.month == 6)
        ).scalar_one()
        assert m_after.vat_applied is True
        assert m_after.vat_amount == Decimal("100.00")
        assert m_after.grand_total == Decimal("1100.00")
