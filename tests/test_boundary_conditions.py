"""Sınır durumları ve eksik test senaryoları.

Bu dosya, review sürecinde tespit edilen eksik test alanlarını kapsar:
- Permission boundary (staff = clinical.delete yapamaz)
- Exchange rate staleness (3+ günlük kur ile fatura)
- Makbuz lock bypass denemeleri
- TreatmentCategory.OTHER fallback
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.extensions import db
from app.models.models import (
    ExchangeRate, Invoice, InvoiceItem, InvoiceItemType, Makbuz, Party, PartyType,
    Treatment, TreatmentCategory, WorkOrder, money,
)
from conftest import login


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dentist(app, name="Dr. Boundary Test", phone="+905550001122"):
    with app.app_context():
        party = Party(party_type=PartyType.DENTIST, name=name, phone=phone, is_active=True)
        db.session.add(party)
        db.session.commit()
        return party.id


def _make_treatment(app, name="Boundary Treatment", category="ana_islemler", price=75.0):
    with app.app_context():
        t = Treatment(name=name, category=category, price_eur=Decimal(str(price)))
        db.session.add(t)
        db.session.commit()
        return t.id


# ---------------------------------------------------------------------------
# Permission boundary tests
# ---------------------------------------------------------------------------

class TestPermissionBoundary:
    def test_staff_cannot_access_delete_endpoints(self, client, app):
        """Staff kullanıcısı clinical.delete endpoint'lerine erişemez → redirect."""
        login(client, "staff", "staff-pass")
        party_id = _make_dentist(app, name="Dr. Perm Test")

        # DELETE party → yetki yoksa dashboard'a redirect (302)
        res = client.post(f"/parties/{party_id}/delete")
        assert res.status_code == 302

    def test_staff_can_access_clinical_view(self, client, app):
        """Staff kullanıcısı clinical.view endpoint'lerine erişebilir."""
        login(client, "staff", "staff-pass")
        res = client.get("/parties/")
        assert res.status_code == 200

    def test_staff_can_access_billing_view(self, client, app):
        """Staff kullanıcısı billing.view endpoint'lerine erişebilir."""
        login(client, "staff", "staff-pass")
        res = client.get("/makbuzlar/")
        assert res.status_code == 200


# ---------------------------------------------------------------------------
# Exchange rate staleness tests
# ---------------------------------------------------------------------------

class TestExchangeRateStaleness:
    def test_stale_rate_warning_in_context(self, client, app):
        """3 günden eski kur varken context_processor rate_health.is_stale=True dönmeli."""
        login(client, "admin", "admin-pass")

        with app.app_context():
            old_rate = ExchangeRate(
                rate_date=date.today() - timedelta(days=5),
                eur_to_try=Decimal("40.0000"),
                source="ecb",
            )
            db.session.add(old_rate)
            db.session.commit()

        res = client.get("/")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert "kur" in html.lower() or "eski" in html.lower() or "stale" in html.lower()


# ---------------------------------------------------------------------------
# Makbuz lock bypass tests
# ---------------------------------------------------------------------------

class TestMakbuzLockBypass:
    def test_locked_period_blocks_work_order_edit(self, client, app):
        """Kilitli dönemde iş emri düzenlenemez."""
        login(client, "admin", "admin-pass")
        party_id = _make_dentist(app, name="Dr. Lock Test")

        with app.app_context():
            makbuz = Makbuz(
                party_id=party_id,
                year=2026,
                month=1,
                work_order_count=1,
                subtotal=Decimal("100.00"),
                status=Makbuz.STATUS_SENT,
                generated_at=datetime.now().astimezone(),
            )
            makbuz.recalculate_totals()
            db.session.add(makbuz)

            wo = WorkOrder(
                party_id=party_id,
                work_date=date(2026, 1, 15),
                apparatus_type="Test",
                patient_name="Lock Patient",
                apparatus_price=Decimal("100.00"),
                extra_price=Decimal("0.00"),
                total_price=Decimal("100.00"),
            )
            db.session.add(wo)
            db.session.commit()
            wo_id = wo.id

        res = client.post(
            f"/parties/{party_id}/work-orders/{wo_id}/edit",
            data={"work_date": "2026-01-15", "apparatus_type": "Updated"},
            follow_redirects=True,
        )
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert "kesinleştirildiği" in html.lower() or "düzenlenemez" in html.lower()

    def test_locked_period_blocks_work_order_delete(self, client, app):
        """Kilitli dönemde iş emri silinemez."""
        login(client, "admin", "admin-pass")
        party_id = _make_dentist(app, name="Dr. Lock Delete")

        with app.app_context():
            makbuz = Makbuz(
                party_id=party_id,
                year=2026,
                month=2,
                work_order_count=1,
                subtotal=Decimal("50.00"),
                status=Makbuz.STATUS_SENT,
                generated_at=datetime.now().astimezone(),
            )
            makbuz.recalculate_totals()
            db.session.add(makbuz)

            wo = WorkOrder(
                party_id=party_id,
                work_date=date(2026, 2, 10),
                apparatus_type="Delete Test",
                patient_name="Delete Patient",
                apparatus_price=Decimal("50.00"),
                extra_price=Decimal("0.00"),
                total_price=Decimal("50.00"),
            )
            db.session.add(wo)
            db.session.commit()
            wo_id = wo.id

        res = client.post(
            f"/parties/{party_id}/work-orders/{wo_id}/delete",
            follow_redirects=True,
        )
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert "kesinleştirildiği" in html.lower() or "silinemez" in html.lower()


# ---------------------------------------------------------------------------
# TreatmentCategory.OTHER fallback tests
# ---------------------------------------------------------------------------

class TestCategoryFallback:
    def test_invoice_item_category_key_with_unknown_treatment_category(self, app):
        """Bilinmeyen treatment category'de raw category string dönmeli (label fallback template'de)."""
        with app.app_context():
            t = Treatment(
                name="Unknown Cat Treatment",
                category="unknown_category_xyz",
                price_eur=Decimal("25.00"),
            )
            db.session.add(t)
            db.session.flush()

            from app.models.models import Invoice, InvoiceItem, INVOICE_CATEGORY_LABELS, invoice_item_category_key
            inv = Invoice(
                invoice_number="CAT-FALLBACK-001",
                invoice_date=date.today(),
                total_eur=Decimal("25.00"),
                total_try=Decimal("1000.00"),
                exchange_rate=Decimal("40.0000"),
                status="pending",
            )
            db.session.add(inv)
            db.session.flush()

            item = InvoiceItem(
                invoice_id=inv.id,
                item_type=InvoiceItemType.TREATMENT,
                treatment_id=t.id,
                description="Test",
                quantity=1,
                unit_price_eur=Decimal("25.00"),
                unit_price_try=Decimal("1000.00"),
                vat_rate=Decimal("0.00"),
                discount_value=Decimal("0.00"),
            )
            db.session.add(item)
            db.session.commit()

            key = invoice_item_category_key(item)
            # Raw category string döner; label fallback Invoice.category_label'da yapılır
            assert key == "unknown_category_xyz"
            # Label lookup fallback'ı: bilinmeyen key için raw key döner
            assert INVOICE_CATEGORY_LABELS.get(key, key) == "unknown_category_xyz"

    def test_invoice_category_label_for_other(self, app):
        """OTHER category_key için label 'Diğer' olmalı."""
        from app.models.models import INVOICE_CATEGORY_LABELS, TreatmentCategory
        assert INVOICE_CATEGORY_LABELS.get(TreatmentCategory.OTHER) == "Diğer"


# Boundary test: vat_rate edge cases
class TestVatRateBoundary:
    def test_zero_vat_rate(self, app):
        """vat_rate=0 ile makbuz oluşturulabilmeli."""
        with app.app_context():
            party = Party(party_type=PartyType.DENTIST, name="Dr. Vat Zero", is_active=True)
            db.session.add(party)
            db.session.flush()

            makbuz = Makbuz(
                party_id=party.id,
                year=2026,
                month=6,
                work_order_count=1,
                subtotal=Decimal("100.00"),
                vat_applied=False,
                vat_rate=Decimal("0.00"),
                generated_at=datetime.now().astimezone(),
            )
            makbuz.recalculate_totals()
            assert makbuz.vat_amount == Decimal("0.00")
            assert makbuz.grand_total == Decimal("100.00")

    def test_high_vat_rate(self, app):
        """Yüksek vat_rate (örn. %50) ile makbuz hesabı doğru olmalı."""
        with app.app_context():
            party = Party(party_type=PartyType.DENTIST, name="Dr. Vat High", is_active=True)
            db.session.add(party)
            db.session.flush()

            makbuz = Makbuz(
                party_id=party.id,
                year=2026,
                month=7,
                work_order_count=1,
                subtotal=Decimal("200.00"),
                vat_applied=True,
                vat_rate=Decimal("50.00"),
                generated_at=datetime.now().astimezone(),
            )
            makbuz.recalculate_totals()
            assert makbuz.vat_amount == Decimal("100.00")
            assert makbuz.grand_total == Decimal("300.00")
