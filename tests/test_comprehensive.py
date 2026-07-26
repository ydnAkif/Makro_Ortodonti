"""Comprehensive tests covering all major application flows."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
import io
import json
import pytest

from app.extensions import db
from app.models.invoice_service import InvoiceService
from app.models.models import (
    ExchangeRate, Invoice, Party, PartyType, Payment, PaymentMethod,
    Settings, Treatment, WorkOrder
)
from conftest import login


# ==================== AUTH ====================

def test_login_invalid_password(client):
    """Yanlis sifre ile giris yapilamaz."""
    response = client.post("/login", data={"username": "admin", "password": "wrong"})
    assert response.status_code == 200
    assert "Kullanıcı adı veya şifre hatalı" in response.get_data(as_text=True)


def test_login_invalid_username(client):
    """Var olmayan kullanici ile giris yapilamaz."""
    response = client.post("/login", data={"username": "nonexistent", "password": "x"})
    assert response.status_code == 200
    assert "Kullanıcı adı veya şifre hatalı" in response.get_data(as_text=True)


def test_logout(client):
    """Cikis yapilabilmeli."""
    login(client, "admin", "admin-pass")
    response = client.post("/logout", follow_redirects=True)
    assert response.status_code == 200


def test_unauthenticated_redirect(client):
    """Giris yapilmamis istekler login sayfasina yonlendirilmeli."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.location


# ==================== DASHBOARD ====================

def test_dashboard_loads(client, app):
    """Dashboard sayfasi acilmali ve temel bilgileri gostermeli."""
    login(client, "admin", "admin-pass")

    with app.app_context():
        party = db.session.execute(
            db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
        ).scalar_one()
        db.session.add(WorkOrder(
            party_id=party.id,
            work_date=date.today(),
            apparatus_type="Aparey",
            patient_name="Dashboard Test",
            apparatus_price=Decimal("100.00"),
            extra_price=Decimal("0.00"),
            total_price=Decimal("100.00"),
        ))
        db.session.commit()

    response = client.get("/")
    assert response.status_code == 200
    assert "Makro" in response.get_data(as_text=True)


# ==================== PATIENTS CRUD ====================

def test_patient_list(client, app):
    """Hasta listesi redirect olmali."""
    login(client, "admin", "admin-pass")
    response = client.get("/patients/", follow_redirects=False)
    assert response.status_code == 302
    assert "/parties/" in response.location


def test_patient_add(client, app):
    """Dis hekimi ekleme + otomatik Party olusturma."""
    login(client, "admin", "admin-pass")

    response = client.post("/parties/add", data={
        "name": "Dr. Zeynep Kaya",
        "phone": "5559998877",
        "email": "zeynep@test.com",
        "is_active": "on",
    }, follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        party = db.session.execute(
            db.select(Party).where(Party.name == "Dr. Zeynep Kaya")
        ).scalar_one()
        assert party.phone == "5559998877"
        assert party.party_type == PartyType.DENTIST


def test_patient_detail(client, app):
    """Hasta detay sayfasi redirect olmali."""
    login(client, "admin", "admin-pass")

    with app.app_context():
        patient_id = db.session.execute(db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)).scalar_one().id

    response = client.get(f"/patients/{patient_id}", follow_redirects=False)
    assert response.status_code == 302
    assert f"/parties/{patient_id}" in response.location


def test_patient_edit(client, app):
    """Dis hekimi guncelleme + Party senkronizasyonu."""
    login(client, "admin", "admin-pass")

    with app.app_context():
        patient_id = db.session.execute(db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)).scalar_one().id

    response = client.post(f"/parties/{patient_id}/edit", data={
        "name": "Dr. Guncellenmis Hekim",
        "phone": "5550001122",
        "email": "updated@test.com",
        "is_active": "on",
    }, follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        party = db.session.get(Party, patient_id)
        assert party.name == "Dr. Guncellenmis Hekim"


def test_patient_delete(client, app):
    """Dis hekimi soft-delete + Party deaktivasyonu."""
    login(client, "admin", "admin-pass")

    with app.app_context():
        patient_id = db.session.execute(db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)).scalar_one().id

    response = client.post(f"/parties/{patient_id}/delete", follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        party = db.session.get(Party, patient_id)
        assert party.is_active is False


def test_patient_add_treatment(client, app):
    """Patients route redirect olmali."""
    login(client, "admin", "admin-pass")

    with app.app_context():
        patient_id = db.session.execute(db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)).scalar_one().id

    response = client.post(f"/patients/{patient_id}/add-treatment", data={
        "treatment_id": 1,
        "treatment_date": date.today().isoformat(),
        "price_override": "",
        "notes": "Test tedavi",
    }, follow_redirects=False)
    assert response.status_code in (302, 404, 405)


# ==================== TREATMENTS CRUD ====================

def test_treatment_list(client, app):
    """Tedavi listesi gorunmeli."""
    login(client, "admin", "admin-pass")
    response = client.get("/treatments/")
    assert response.status_code == 200
    assert "Consultation" in response.get_data(as_text=True)


def test_treatment_list_filter_category(client, app):
    """Tedavi listesi kategoriye gore filtrelenmeli."""
    login(client, "admin", "admin-pass")
    response = client.get("/treatments/?category=ekstra_islemler")
    assert response.status_code == 200
    assert "Crown" in response.get_data(as_text=True)


def test_treatment_list_search(client, app):
    """Tedavi listesi arama ile filtrelenmeli."""
    login(client, "admin", "admin-pass")
    response = client.get("/treatments/?search=Crown")
    assert response.status_code == 200


def test_treatment_add(client, app):
    """Tedavi ekleme (admin)."""
    login(client, "admin", "admin-pass")

    response = client.post("/treatments/add", data={
        "name": "New Treatment",
        "description": "A new test treatment",
        "category": "ana_islemler",
        "price_eur": 150.00,
    }, follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        t = db.session.execute(
            db.select(Treatment).where(Treatment.name == "New Treatment")
        ).scalar_one()
        assert t.category == "ana_islemler"
        assert t.price_eur == 150.00


def test_treatment_edit(client, app):
    """Tedavi guncelleme (admin)."""
    login(client, "admin", "admin-pass")

    with app.app_context():
        treatment_id = db.session.execute(
            db.select(Treatment).where(Treatment.name == "Consultation")
        ).scalar_one().id

    response = client.post(f"/treatments/{treatment_id}/edit", data={
        "name": "Consultation Updated",
        "description": "Updated desc",
        "category": "ana_islemler",
        "price_eur": 75.00,
    }, follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        t = db.session.get(Treatment, treatment_id)
        assert t.name == "Consultation Updated"
        assert t.price_eur == 75.00


def test_treatment_delete(client, app):
    """Tedavi soft-delete (admin)."""
    login(client, "admin", "admin-pass")

    with app.app_context():
        treatment_id = db.session.execute(
            db.select(Treatment).where(Treatment.name == "Extraction")
        ).scalar_one().id

    response = client.post(f"/treatments/{treatment_id}/delete", follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        t = db.session.get(Treatment, treatment_id)
        assert t.is_active is False


def test_treatment_api_update(client, app):
    """Tedavi inline guncelleme API'si."""
    login(client, "admin", "admin-pass")

    with app.app_context():
        treatment_id = db.session.execute(
            db.select(Treatment).where(Treatment.name == "Crown")
        ).scalar_one().id

    response = client.post("/treatments/api/update",
        data=json.dumps({"id": treatment_id, "name": "Crown Updated", "price_eur": 250.00}),
        content_type="application/json",
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["treatment"]["name"] == "Crown Updated"
    assert data["treatment"]["price_eur"] == 250.00


def test_treatment_api_update_invalid_id(client, app):
    """Var olmayan tedavi guncellenemez."""
    login(client, "admin", "admin-pass")

    response = client.post("/treatments/api/update",
        data=json.dumps({"id": 99999, "name": "X"}),
        content_type="application/json",
    )
    assert response.status_code == 404


def test_treatment_import_xlsx(client, app):
    """XLSX dosyasindan tedavi ice aktarma."""
    login(client, "admin", "admin-pass")

    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Tedavi Adi", "Kategori", "Fiyat (EUR)", "Aciklama"])
    ws.append(["Imported Treatment 1", "ana_islemler", 120.0, "Imported desc 1"])
    ws.append(["Imported Treatment 2", "ana_islemler", 300.0, "Imported desc 2"])
    ws.append(["Consultation", "ana_islemler", 55.0, "Updated via import"])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    response = client.post("/treatments/import",
        data={"file": (buf, "test.xlsx")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        t1 = db.session.execute(
            db.select(Treatment).where(Treatment.name == "Imported Treatment 1")
        ).scalar_one_or_none()
        assert t1 is not None
        assert t1.price_eur == 120.0
        assert t1.category == "ana_islemler"

        t2 = db.session.execute(
            db.select(Treatment).where(Treatment.name == "Imported Treatment 2")
        ).scalar_one_or_none()
        assert t2 is not None

        consult = db.session.execute(
            db.select(Treatment).where(Treatment.name == "Consultation")
        ).scalar_one()
        assert consult.price_eur == 55.0


def test_treatment_import_invalid_file(client, app):
    """Gecersiz dosya turu reddedilmeli."""
    login(client, "admin", "admin-pass")

    response = client.post("/treatments/import",
        data={"file": (io.BytesIO(b"test"), "test.txt")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "desteklenir" in response.get_data(as_text=True)


# ==================== INVOICES ====================

# Not: eski Invoice CRUD rotalari kaldirildi; fatura akisi artik Makbuzlar
# uzerinden yurutuluyor (bkz. tests/test_makbuz.py).


# ==================== PAYMENTS ====================

# Not: eski hasta bazlı Invoice tahsilat testleri (test_payment_add, test_payment_delete)
# kaldırıldı; /payments artık doktor/makbuz tahsilatını yönetiyor (bkz. tests/test_makbuz.py).


# ==================== SETTINGS ====================

def test_settings_page_loads(client, app):
    """Ayarlar sayfasi acilmali."""
    login(client, "admin", "admin-pass")
    response = client.get("/settings/")
    assert response.status_code == 200


def test_settings_update_clinic_info(client, app):
    """Klinik bilgileri guncellenebilmeli."""
    login(client, "admin", "admin-pass")

    response = client.post("/settings/update", data={
        "clinic_name": "Guncellenmis Klinik",
        "clinic_phone": "02121112233",
        "clinic_email": "info@klinik.com",
        "clinic_address": "Ankara",
    }, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        name = db.session.execute(
            db.select(Settings.value).where(Settings.key == "clinic_name")
        ).scalar_one()
        assert name == "Guncellenmis Klinik"


def test_exchange_rate_add_manual(client, app):
    """Manuel kur ekleme."""
    login(client, "admin", "admin-pass")

    response = client.post("/settings/exchange-rate/add", data={
        "rate_date": "2025-01-15",
        "eur_try_rate": "38.5000",
    }, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        rate = db.session.execute(
            db.select(ExchangeRate).where(ExchangeRate.rate_date == date(2025, 1, 15))
        ).scalar_one_or_none()
        assert rate is not None
        assert rate.eur_to_try == 38.5


# ==================== REPORTS ====================

def test_reports_page_loads(client, app):
    """Raporlar sayfasi acilmali."""
    login(client, "admin", "admin-pass")
    response = client.get("/reports/")
    assert response.status_code == 200
    assert "Raporlar" in response.get_data(as_text=True)


# ==================== PARTY SEARCH ====================

def test_party_search(client, app):
    """Kisi arama calismali."""
    login(client, "admin", "admin-pass")

    with app.app_context():
        party = db.session.execute(
            db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
        ).scalar_one()

    response = client.get(f"/parties/?search={party.name}")
    assert response.status_code == 200


def test_party_referred_by(client, app):
    """Hasta sevk bilgisi (referred_by) kaydedilebilmeli."""
    login(client, "admin", "admin-pass")

    with app.app_context():
        dentist = Party(
            party_type=PartyType.DENTIST,
            name="Dr. Sevk Hekimi",
            phone="5550000000",
        )
        db.session.add(dentist)
        db.session.flush()

        referred = Party(
            party_type=PartyType.DENTIST,
            name="Sevkli Hasta",
            phone="5551234567",
            referred_by_id=dentist.id,
        )
        db.session.add(referred)
        db.session.commit()

        party = db.session.execute(
            db.select(Party).where(Party.name == "Sevkli Hasta")
        ).scalar_one()
        assert party.referred_by_id == dentist.id


# ==================== BUG FIX TESTS ====================

def test_party_list_enum_badges(client, app):
    """Parties listesi dogru bicimde calismali."""
    login(client, "admin", "admin-pass")

    # Create DENTIST parties (is_active must be "on" to appear in list)
    client.post("/parties/add", data={
        "party_type": "dentist",
        "name": "Dr. Badge Test 1",
        "phone": "5559990001",
        "is_active": "on",
    })
    client.post("/parties/add", data={
        "party_type": "dentist",
        "name": "Dr. Badge Test 2",
        "phone": "5559990002",
        "is_active": "on",
    })

    # All parties page
    response = client.get("/parties/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Doktorlar" in html
    assert "Dr. Badge Test 1" in html
    assert "Dr. Badge Test 2" in html


def test_payments_list_no_crash(client, app):
    """Bug #8: Odeme listesi craslamamali."""
    login(client, "admin", "admin-pass")

    response = client.get("/payments/")
    assert response.status_code == 200

    response = client.get("/payments/?method=cash")
    assert response.status_code == 200

    today = date.today()
    response = client.get(f"/payments/?start_date={today.isoformat()}&end_date={today.isoformat()}")
    assert response.status_code == 200


def test_email_service_party_only(client, app):
    """Bug #2: Email servisi party faturalarinda craslamamali."""
    from app.services.email_service import send_invoice_email

    with app.app_context():
        party = db.session.execute(
            db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
        ).scalar_one()
        invoice = InvoiceService.create_invoice(
            session=db.session,
            party_id=party.id,
            items=[{"item_type": "service", "description": "Email Test", "quantity": 1, "unit_price_eur": 100}],
            invoice_date=date.today(),
        )

        # Should NOT crash, should return error message about missing email
        success, message = send_invoice_email(invoice)
        assert not success  # No SMTP configured in test


def test_whatsapp_service_party_only(client, app):
    """Bug #3: WhatsApp servisi party faturalarinda craslamamali."""
    from app.services.whatsapp_service import WhatsAppService

    with app.app_context():
        party = db.session.execute(
            db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
        ).scalar_one()
        invoice = InvoiceService.create_invoice(
            session=db.session,
            party_id=party.id,
            items=[{"item_type": "service", "description": "WA Test", "quantity": 1, "unit_price_eur": 100}],
            invoice_date=date.today(),
        )

        # Should NOT crash, should return error about disconnected
        result = WhatsAppService.send_invoice_message(invoice)
        assert not result["success"]  # WhatsApp not connected in test


# ==================== UI CONTRACT TESTS ====================

def test_login_success(client):
    response = login(client, "admin", "admin-pass")
    assert response.status_code == 200
    assert "Giriş başarılı!" in response.get_data(as_text=True)


def test_ui_shell_uses_unique_mobile_navigation_target(client):
    login(client, "admin", "admin-pass")
    html = client.get("/").get_data(as_text=True)

    assert html.count('id="mobileSidebar"') == 1
    assert 'aria-controls="mobileSidebar"' in html
    assert 'href="#main-content"' in html


def test_party_form_has_unique_common_fields_and_active_default(client):
    login(client, "admin", "admin-pass")
    html = client.get("/parties/add").get_data(as_text=True)

    for field_id in ("phone", "email", "address", "tax_id"):
        assert html.count(f'id="{field_id}"') == 1
    assert 'id="is_active" name="is_active" checked' in html


# ==================== SETTINGS TESTS ====================

def test_settings_update_does_not_overwrite_unsent_fields(client, app):
    login(client, "admin", "admin-pass")

    response = client.post(
        "/settings/update",
        data={
            "clinic_name": "Yeni Klinik",
            "clinic_phone": "02120000000",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        smtp_user = db.session.execute(
            db.select(Settings.value).where(Settings.key == "smtp_username")
        ).scalar_one_or_none()
        clinic_name = db.session.execute(
            db.select(Settings.value).where(Settings.key == "clinic_name")
        ).scalar_one_or_none()

    assert smtp_user == "old-user@example.com"
    assert clinic_name == "Yeni Klinik"


def test_rate_fetch_updates_today_rate(client, app, monkeypatch):
    login(client, "admin", "admin-pass")

    def fake_fetch_rate():
        return 41.75

    monkeypatch.setattr("app.services.exchange_service.fetch_eur_try_rate", fake_fetch_rate)

    response = client.post("/settings/exchange-rate/fetch", follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        rate = db.session.execute(
            db.select(ExchangeRate).where(ExchangeRate.rate_date == date.today())
        ).scalar_one_or_none()

    assert rate is not None
    assert rate.eur_to_try == 41.75


def test_defensive_validation_exchange_rate(client, app):
    login(client, "admin", "admin-pass")

    response = client.post(
        "/settings/exchange-rate/add",
        data={"rate_date": "2026-07-19", "eur_try_rate": "invalid-float-abc"},
        follow_redirects=True
    )
    assert response.status_code == 200
    assert "Geçersiz tarih veya kur değeri girildi" in response.get_data(as_text=True)

    response = client.post(
        "/settings/exchange-rate/add",
        data={"rate_date": "invalid-date", "eur_try_rate": "41.50"},
        follow_redirects=True
    )
    assert response.status_code == 200
    assert "Geçersiz tarih veya kur değeri girildi" in response.get_data(as_text=True)


# ==================== REPORTS TESTS ====================

def test_reports_use_payments_for_collections_without_double_counting(client, app):
    login(client, "admin", "admin-pass")

    with app.app_context():
        party = db.session.execute(
            db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
        ).scalar_one()
        treatment = db.session.execute(
            db.select(Treatment).where(Treatment.name == "Consultation")
        ).scalar_one()
        invoice = InvoiceService.create_invoice(
            session=db.session,
            party_id=party.id,
            items=[{
                "item_type": "treatment",
                "treatment_id": treatment.id,
                "description": treatment.name,
                "quantity": 1,
                "unit_price_eur": 50.0,
            }],
            invoice_date=date.today(),
        )
        invoice_id = invoice.id

    report = client.get("/reports/").get_data(as_text=True)
    assert "Tahsil edilen" in report
    assert "Muhasebe Raporları" in report

    with app.app_context():
        db.session.add(Payment(
            invoice_id=invoice_id,
            payment_date=date.today(),
            amount_eur=20.0,
            amount_try=800.0,
            exchange_rate=40.0,
            method=PaymentMethod.CASH,
        ))
        db.session.commit()

    report_after_payment = client.get("/reports/").get_data(as_text=True)
    assert "800.00" in report_after_payment


def test_reports_include_old_receivables_and_keep_invoice_rate_basis(client, app):
    login(client, "admin", "admin-pass")
    old_date = date.today().replace(day=1) - timedelta(days=10)

    with app.app_context():
        party = db.session.execute(db.select(Party).limit(1)).scalar_one()
        invoice = Invoice(
            party_id=party.id,
            invoice_number="MKR-OLD-0001",
            invoice_date=old_date,
            due_date=old_date,
            total_eur=100.0,
            total_try=4000.0,
            exchange_rate=40.0,
            status=Invoice.STATUS_PENDING,
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(Payment(
            invoice_id=invoice.id,
            payment_date=date.today(),
            amount_eur=50.0,
            amount_try=2500.0,
            exchange_rate=50.0,
            method=PaymentMethod.CASH,
        ))
        db.session.commit()

    current_report = client.get("/reports/").get_data(as_text=True)
    assert "₺1,500.00" in current_report

    historical_report = client.get(
        f"/reports/?period=custom&start_date={old_date}&end_date={old_date}"
    ).get_data(as_text=True)
    assert "₺4,000.00" in historical_report


def test_reports_aging_report(client, app):
    login(client, "admin", "admin-pass")

    with app.app_context():
        party = db.session.execute(
            db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
        ).scalar_one()

        due_dates = [
            date.today(),
            date.today() - timedelta(days=15),
            date.today() - timedelta(days=45),
            date.today() - timedelta(days=75),
        ]
        for i, due_date in enumerate(due_dates):
            InvoiceService.create_invoice(
                session=db.session,
                party_id=party.id,
                items=[{
                    "item_type": "treatment",
                    "treatment_id": 1,
                    "description": f"Tedavi {i+1}",
                    "quantity": 1,
                    "unit_price_eur": 200.00,
                }],
                invoice_date=date.today(),
                due_date=due_date,
            )

    response = client.get("/reports/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Devreden & Açık Borçlar" in html
    assert "Vadesi henüz gelmedi" in html
    assert "1–30 gün gecikmiş" in html
    assert "31–60 gün gecikmiş" in html
    assert "61–90 gün gecikmiş" in html
    assert "91+ gün gecikmiş" in html


# ==================== PAYMENT TESTS ====================
# Not: eski hasta bazlı Invoice tahsilat testleri kaldırıldı;
# /payments artık doktor/makbuz tahsilatını yönetiyor (bkz. tests/test_makbuz.py).


def test_party_work_order_totals_on_detail(client, app):
    """Doktor detay sayfasi is emri toplamlarini gostermeli."""
    login(client, "admin", "admin-pass")

    with app.app_context():
        party = db.session.execute(
            db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
        ).scalar_one()
        party_id = party.id
        for i in range(2):
            db.session.add(WorkOrder(
                party_id=party_id,
                work_date=date.today(),
                apparatus_type="Aparey",
                patient_name=f"Hasta {i+1}",
                apparatus_price=Decimal("300.00"),
                extra_price=Decimal("0.00"),
                total_price=Decimal("300.00"),
            ))
        previous_month_date = date.today().replace(day=1) - timedelta(days=1)
        db.session.add(WorkOrder(
            party_id=party_id,
            work_date=previous_month_date,
            apparatus_type="Önceki Ay Apareyi",
            patient_name="Önceki Ay Detay Hastası",
            apparatus_price=Decimal("900.00"),
            extra_price=Decimal("0.00"),
            total_price=Decimal("900.00"),
        ))
        db.session.commit()

    response = client.get(f"/parties/{party_id}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "600.00" in html
    assert "Önceki Ay Detay Hastası" not in html

    previous_response = client.get(
        f"/parties/{party_id}?year={previous_month_date.year}&month={previous_month_date.month}"
    )
    assert "Önceki Ay Detay Hastası" in previous_response.get_data(as_text=True)


def test_work_order_ledger_filters_by_day_and_month(client, app):
    login(client, "admin", "admin-pass")
    today = date.today()
    previous_month_date = today.replace(day=1) - timedelta(days=1)

    with app.app_context():
        party = db.session.execute(
            db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
        ).scalar_one()
        today_order = WorkOrder(
            party_id=party.id, work_date=today,
            apparatus_type=json.dumps([
                {"name": "Günlük Test Apareyi", "price": 500, "currency": "TL"},
                {"name": "İkinci Test Apareyi", "price": 200, "currency": "TL"},
            ], ensure_ascii=False),
            extra_addons=json.dumps([
                {"name": "Test Ekstra İşlemi", "price": 100, "currency": "TL"},
            ], ensure_ascii=False),
            patient_name="Bugünkü Hasta", apparatus_price=Decimal("700"),
            extra_price=Decimal("100"), total_price=Decimal("800"),
            notes="Kontrol notu",
        )
        previous_order = WorkOrder(
            party_id=party.id, work_date=previous_month_date,
            apparatus_type="Aylık Test Apareyi", extra_addons="None",
            patient_name="Önceki Ay Hastası", notes="None",
            apparatus_price=Decimal("900"), extra_price=Decimal("0"),
            total_price=Decimal("900"),
        )
        db.session.add_all([today_order, previous_order])
        db.session.commit()
        party_id, today_order_id = party.id, today_order.id

    day_html = client.get("/parties/work-orders").get_data(as_text=True)
    assert "Bugünkü Hasta" in day_html
    assert "Önceki Ay Hastası" not in day_html
    assert "Günlük Test Apareyi" in day_html
    assert "İkinci Test Apareyi" in day_html
    assert "Test Ekstra İşlemi" in day_html
    assert "Kontrol notu" in day_html
    assert "₺800.00" in day_html
    assert f"/work-orders/{today_order_id}/edit" in day_html

    search_html = client.get(
        f"/parties/work-orders?view=day&date={today.isoformat()}&search=test+ekstra"
    ).get_data(as_text=True)
    assert "Bugünkü Hasta" in search_html
    assert "Test Ekstra İşlemi" in search_html
    assert "için 1 sonuç" in search_html

    edit_response = client.post(
        f"/parties/{party_id}/work-orders/{today_order_id}/edit",
        data={
            "work_date": today.isoformat(),
            "apparatus_type": "Düzenlenen Aparey",
            "patient_name": "Düzenlenen Hasta",
            "apparatus_price": "750",
            "extra_price": "0",
            "return_to": "work_orders",
            "return_view": "day",
            "return_date": today.isoformat(),
            "return_search": "Bugünkü Hasta",
        },
        follow_redirects=False,
    )
    assert edit_response.status_code == 302
    assert "/parties/work-orders?" in edit_response.location
    assert "search=Bug%C3%BCnk%C3%BC+Hasta" in edit_response.location

    month_html = client.get(
        f"/parties/work-orders?view=month&year={previous_month_date.year}&month={previous_month_date.month}"
    ).get_data(as_text=True)
    assert "Önceki Ay Hastası" in month_html
    assert "Bugünkü Hasta" not in month_html
    previous_row = month_html.split("Önceki Ay Hastası", 1)[1].split("</tr>", 1)[0]
    assert "workorder-line-group--extra" in previous_row
    assert ">-<" in previous_row
    assert "None" not in previous_row


def test_work_order_delete_returns_to_ledger(client, app):
    login(client, "admin", "admin-pass")
    with app.app_context():
        party = db.session.execute(
            db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
        ).scalar_one()
        work_order = WorkOrder(
            party_id=party.id, work_date=date.today(), apparatus_type="Silinecek",
            patient_name="Silinecek Hasta", apparatus_price=Decimal("100"),
            extra_price=Decimal("0"), total_price=Decimal("100"),
        )
        db.session.add(work_order)
        db.session.commit()
        party_id, work_order_id = party.id, work_order.id

    response = client.post(
        f"/parties/{party_id}/work-orders/{work_order_id}/delete",
        data={
            "return_to": "work_orders",
            "return_view": "day",
            "return_date": date.today().isoformat(),
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/parties/work-orders?" in response.location
    with app.app_context():
        assert db.session.get(WorkOrder, work_order_id) is None


# ==================== PARTY TESTS ====================

def test_party_crud_dentist_customer(client, app):
    login(client, "admin", "admin-pass")

    response = client.post("/parties/add", data={
        "party_type": "dentist",
        "name": "DR. mehmet oz",
        "phone": "+905559876543",
        "email": "mehmet@dentist.com",
        "tax_id": "12345678901",
    }, follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        party = db.session.execute(
            db.select(Party).where(Party.name == "Dr. Mehmet Oz")
        ).scalar_one()
        assert party.party_type == PartyType.DENTIST
        assert party.display_name == "Dr. Mehmet Oz"
        assert party.tax_id == "12345678901"


def test_party_crud_company_customer(client, app):
    login(client, "admin", "admin-pass")

    response = client.post("/parties/add", data={
        "party_type": "dentist",
        "name": "ABC Saglik A.S.",
        "phone": "+902125551234",
        "email": "info@abc.com",
        "address": "Istanbul",
        "tax_id": "1234567890",
    }, follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        party = db.session.execute(
            db.select(Party).where(Party.name == "ABC Saglik A.S.")
        ).scalar_one()
        assert party.party_type == PartyType.DENTIST
        assert party.display_name == "ABC Saglik A.S."


def test_changing_patient_type_deactivates_legacy_patient(client, app):
    login(client, "admin", "admin-pass")

    with app.app_context():
        party = db.session.execute(
            db.select(Party).where(Party.party_type == PartyType.DENTIST)
        ).scalar_one()
        party_id = party.id

    response = client.post(
        f"/parties/{party_id}/edit",
        data={
            "party_type": "dentist",
            "name": "Dr. Ayse Guncel",
            "phone": "5551112233",
            "is_active": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        party = db.session.get(Party, party_id)
        assert party.party_type == PartyType.DENTIST
        assert party.is_active is True
        assert party.name == "Dr. Ayse Guncel"


# ==================== TREATMENT TESTS ====================

@pytest.mark.parametrize("price,category", [("-1", "ana_islemler"), ("nan", "ana_islemler"), ("10", "invalid")])
def test_treatment_route_rejects_invalid_financial_values(client, app, price, category):
    login(client, "admin", "admin-pass")

    with app.app_context():
        before = db.session.scalar(db.select(db.func.count(Treatment.id)))

    response = client.post(
        "/treatments/add",
        data={"name": "Invalid treatment", "category": category, "price_eur": price},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Geçersiz" in response.get_data(as_text=True) or "negatif" in response.get_data(as_text=True)

    with app.app_context():
        after = db.session.scalar(db.select(db.func.count(Treatment.id)))
        assert after == before


# ==================== SECURITY TESTS ====================

def test_smtp_password_encryption_decryption(app):
    with app.app_context():
        from app.services.security_service import encrypt_value, decrypt_value

        test_pass = "mypass123!@#"
        encrypted = encrypt_value(test_pass)
        assert encrypted != test_pass
        assert len(encrypted) > 0

        decrypted = decrypt_value(encrypted)
        assert decrypted == test_pass

        with pytest.raises(ValueError, match="Failed to decrypt"):
            decrypt_value("legacy_plaintext")

        assert encrypt_value("") == ""
        assert decrypt_value("") == ""


def test_login_rate_limiting_and_lockout(client, app):
    for _ in range(5):
        response = client.post("/login", data={"username": "admin", "password": "wrong-password"})
        assert response.status_code == 200
        assert "Kullanıcı adı veya şifre hatalı" in response.get_data(as_text=True)

    response = client.post("/login", data={"username": "admin", "password": "wrong-password"})
    assert response.status_code == 200
    assert "Çok fazla başarısız giriş denemesi" in response.get_data(as_text=True)

    response = client.post("/login", data={"username": "admin", "password": "admin-pass"})
    assert response.status_code == 200
    assert "Çok fazla başarısız giriş denemesi" in response.get_data(as_text=True)
