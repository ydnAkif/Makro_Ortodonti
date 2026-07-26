"""Tests for audit enhancements: patient routing, treatment price formatting, BasePDF helpers."""

import pytest
from app.models.models import Patient, Party, PartyType, Treatment, TreatmentCategory
from app.services.base_pdf import BasePDF


def test_patients_route_redirects_to_dentist_party(app, client):
    """Test /patients/<id> looks up patient's dentist party_id."""
    with app.app_context():
        from app.extensions import db
        party = Party(name="Dr. Ahmet Yılmaz", party_type=PartyType.DENTIST, phone="05321112233")
        db.session.add(party)
        db.session.flush()

        patient = Patient(first_name="Mehmet", last_name="Kaya", party_id=party.id)
        db.session.add(patient)
        db.session.commit()
        patient_id = patient.id
        party_id = party.id

    client.post("/login", data={"username": "admin", "password": "admin-pass"})

    response = client.get(f"/patients/{patient_id}")
    assert response.status_code == 302
    assert f"/parties/{party_id}" in response.location


def test_patients_route_redirects_to_list_when_not_found(app, client):
    """Test /patients/<id> redirects to parties list when patient doesn't exist."""
    client.post("/login", data={"username": "admin", "password": "admin-pass"})

    response = client.get("/patients/999999")
    assert response.status_code == 302
    assert "/parties" in response.location


def test_treatment_price_formatted_property():
    """Test Treatment price_formatted property returns correct currency symbol."""
    t1 = Treatment(name="Aparey TL", price_eur=150.00, currency="TL", category=TreatmentCategory.ANA_ISLEMLER)
    assert t1.price_formatted == "₺150.00"

    t2 = Treatment(name="Aparey EUR", price_eur=50.00, currency="EUR", category=TreatmentCategory.ANA_ISLEMLER)
    assert t2.price_formatted == "€50.00"


def test_base_pdf_header_and_footer_helpers():
    """Test BasePDF draw_header_banner and draw_footer_bar render without errors."""
    pdf = BasePDF()
    pdf.add_page()
    pdf.draw_header_banner("Makro Ortodonti", "0555 123 45 67 | info@makro.com", "TEST DOKUMANI", "Aylık Özet")
    pdf.draw_footer_bar("Makro Ortodonti Laboratuvarı")
    output = pdf.output()
    assert len(output) > 0


def test_party_service_crud_and_validations(app):
    """Test PartyService create_party, update_party, delete_party and validation errors."""
    from app.services.party_service import PartyService

    with app.app_context():
        # Create party
        party = PartyService.create_party({
            "name": "Dr. Ayşe Demir",
            "party_type": "dentist",
            "phone": "0533 222 33 44",
            "email": "ayse@example.com",
            "address": "Kadıköy İstanbul",
            "notes": "VIP Hekim",
            "is_active": "on",
        })
        assert party.id is not None
        assert party.name == "Dr. Ayşe Demir"
        assert party.party_type == PartyType.DENTIST

        # Update party
        updated = PartyService.update_party(party.id, {
            "name": "Dr. Ayşe Demir (Güncellendi)",
            "phone": "0533 999 88 77",
            "is_active": True,
        })
        assert updated.name == "Dr. Ayşe Demir (güncellendi)"

        # Empty name validation errors
        with pytest.raises(ValueError, match="İsim alanı gereklidir"):
            PartyService.create_party({"name": "   "})

        with pytest.raises(ValueError, match="İsim alanı gereklidir"):
            PartyService.update_party(party.id, {"name": ""})

        # Delete party
        assert PartyService.delete_party(party.id) is True


def test_party_service_work_order_validations(app):
    """Test PartyService work order creation and update error branches."""
    from app.services.party_service import PartyService
    from datetime import date

    with app.app_context():
        party = PartyService.create_party({"name": "Dr. Mehmet Can"})

        # Invalid date
        with pytest.raises(ValueError, match="Geçersiz tarih"):
            PartyService.create_work_order(party.id, {"work_date": "invalid-date"})

        # Valid creation
        wo = PartyService.create_work_order(party.id, {
            "work_date": date.today().isoformat(),
            "apparatus_type": "Gece Plağı",
            "patient_name": "Ali Veli",
            "apparatus_price": "500",
            "extra_price": "100",
        })
        assert wo.id is not None

        # Invalid update date
        with pytest.raises(ValueError, match="Geçersiz tarih"):
            PartyService.update_work_order(party.id, wo.id, {"work_date": "invalid-date"})


def test_cli_seed_command(app):
    """Test flask db-tools seed CLI command runs without error."""
    runner = app.test_cli_runner()
    result = runner.invoke(args=["db-tools", "seed"])
    assert result.exit_code == 0
    assert "Database seeding completed successfully" in result.output

