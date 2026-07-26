"""Kapsamlı muhasebe raporları için testler."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
import json
import pytest

from app.extensions import db
from app.models.models import (
    ExchangeRate, Makbuz, MakbuzPayment, Party, PartyType, WorkOrder,
)
from conftest import login


def _make_doctor(app, name="Dr. Rapor Test", phone="+905559990099"):
    with app.app_context():
        party = Party(party_type=PartyType.DENTIST, name=name, phone=phone)
        db.session.add(party)
        db.session.commit()
        return party.id


def _add_work_order(app, party_id, work_date, app_items, ext_items, rate=40.0):
    with app.app_context():
        wo = WorkOrder(
            party_id=party_id,
            work_date=work_date,
            apparatus_type=json.dumps(app_items),
            extra_addons=json.dumps(ext_items),
            patient_name="Rapor Hasta",
            apparatus_price=Decimal(sum(item["price"] for item in app_items)),
            extra_price=Decimal(sum(item["price"] for item in ext_items)),
            total_price=Decimal(sum(item["price"] for item in app_items) + sum(item["price"] for item in ext_items)),
            exchange_rate_applied=Decimal(str(rate)),
        )
        db.session.add(wo)
        db.session.commit()
        return wo.id


def _create_makbuz(app, party_id, year, month, status=Makbuz.STATUS_SENT, paid_at=None, paid_amount=None):
    with app.app_context():
        makbuz = Makbuz(
            party_id=party_id,
            year=year,
            month=month,
            work_order_count=1,
            subtotal=Decimal("200.00"),
            vat_applied=True,
            vat_rate=Decimal("20.00"),
            status=status,
            generated_at=datetime.now().astimezone(),
            paid_at=paid_at,
            paid_amount=paid_amount,
        )
        makbuz.recalculate_totals()
        db.session.add(makbuz)
        db.session.commit()
        return makbuz.id


# ---------------------------------------------------------------------------
# Reports Service Tests
# ---------------------------------------------------------------------------

class TestReportsService:
    """reports_service modülü unit testleri."""

    def test_resolve_period_this_month(self):
        from app.services.reports_service import resolve_period
        today = date(2026, 7, 15)
        start, end, period = resolve_period(today, "this_month", "", "")
        assert start == date(2026, 7, 1)
        assert end == date(2026, 7, 15)
        assert period == "this_month"

    def test_resolve_period_last_30(self):
        from app.services.reports_service import resolve_period
        today = date(2026, 7, 15)
        start, end, period = resolve_period(today, "last_30", "", "")
        assert start == today - timedelta(days=29)
        assert end == today

    def test_resolve_period_this_year(self):
        from app.services.reports_service import resolve_period
        today = date(2026, 7, 15)
        start, end, period = resolve_period(today, "this_year", "", "")
        assert start == date(2026, 1, 1)
        assert end == today

    def test_resolve_period_last_year(self):
        from app.services.reports_service import resolve_period
        today = date(2026, 7, 15)
        start, end, period = resolve_period(today, "last_year", "", "")
        assert start == date(2025, 1, 1)
        assert end == date(2025, 12, 31)

    def test_resolve_period_daily(self):
        from app.services.reports_service import resolve_period
        today = date(2026, 7, 15)
        start, end, period = resolve_period(today, "daily", "", "")
        assert start == today
        assert end == today

    def test_resolve_period_monthly(self):
        from app.services.reports_service import resolve_period
        today = date(2026, 7, 15)
        start, end, period = resolve_period(today, "monthly", "", "")
        assert start == date(2026, 7, 1)
        assert end == today

    def test_resolve_period_custom(self):
        from app.services.reports_service import resolve_period
        today = date(2026, 7, 15)
        start, end, period = resolve_period(today, "custom", "2026-03-01", "2026-05-31")
        assert start == date(2026, 3, 1)
        assert end == date(2026, 5, 31)
        assert period == "custom"

    def test_resolve_period_swap_dates(self):
        from app.services.reports_service import resolve_period
        today = date(2026, 7, 15)
        start, end, _ = resolve_period(today, "custom", "2026-05-31", "2026-03-01")
        assert start == date(2026, 3, 1)
        assert end == date(2026, 5, 31)

    def test_build_treatment_stats_empty(self):
        from app.services.reports_service import build_treatment_stats
        result = build_treatment_stats([])
        assert result == []

    def test_build_category_stats_empty(self):
        from app.services.reports_service import build_category_stats
        result = build_category_stats([])
        assert result == []

    def test_build_vat_summary_empty(self):
        from app.services.reports_service import build_vat_summary
        result = build_vat_summary([])
        assert result == []

    def test_build_daily_rows_empty(self):
        from app.services.reports_service import build_daily_rows
        result = build_daily_rows(date(2026, 7, 1), date(2026, 7, 5), [], [])
        assert len(result) == 5

    def test_build_monthly_trend_empty(self):
        from app.services.reports_service import build_monthly_trend
        result = build_monthly_trend(date(2026, 1, 1), date(2026, 12, 31), [], [])
        assert result == []

    def test_build_aging_buckets_empty(self):
        from app.services.reports_service import build_aging_buckets
        result = build_aging_buckets(date(2026, 7, 15), [])
        assert len(result) == 5
        assert all(b.count == 0 for b in result)

    def test_build_period_overview_zero(self):
        from app.services.reports_service import build_period_overview
        result = build_period_overview(
            date(2026, 7, 1), date(2026, 7, 31),
            [], [], [], [], [],
        )
        assert result.issued_try == Decimal("0.00")
        assert result.collected_try == Decimal("0.00")
        assert result.work_order_count == 0


# ---------------------------------------------------------------------------
# Reports Route Tests
# ---------------------------------------------------------------------------

class TestReportsRoutes:
    """Rapor rotaları HTTP testleri."""

    def test_index_requires_login(self, client):
        response = client.get("/reports/")
        assert response.status_code == 302

    def test_index_page(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/reports/?period=this_month")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Muhasebe Raporları" in html

    def test_index_all_periods(self, client, app):
        login(client, "admin", "admin-pass")
        for period in ["daily", "this_month", "last_30", "this_year", "last_year"]:
            response = client.get(f"/reports/?period={period}")
            assert response.status_code == 200

    def test_index_with_custom_dates(self, client, app):
        login(client, "admin", "admin-pass")
        today = date.today()
        start = (today - timedelta(days=30)).isoformat()
        end = today.isoformat()
        response = client.get(f"/reports/?period=custom&start_date={start}&end_date={end}")
        assert response.status_code == 200

    def test_index_with_work_orders(self, client, app):
        login(client, "admin", "admin-pass")
        party_id = _make_doctor(app, "Dr. Rota Test")
        today = date.today()
        _add_work_order(
            app, party_id, today,
            [{"name": "Hawley Retainer", "price": 100.0, "currency": "TL"}],
            [{"name": "Screw", "price": 10.0, "currency": "TL"}],
        )
        response = client.get("/reports/?period=this_month")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Hawley Retainer" in html
        assert "Screw" in html

    def test_index_with_makbuz(self, client, app):
        login(client, "admin", "admin-pass")
        party_id = _make_doctor(app, "Dr. Makbuz Test")
        today = date.today()
        _add_work_order(
            app, party_id, today,
            [{"name": "Activator", "price": 200.0, "currency": "TL"}],
            [],
        )
        _create_makbuz(app, party_id, today.year, today.month, status=Makbuz.STATUS_SENT)
        response = client.get("/reports/?period=this_month")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "200.00" in html or "Activator" in html

    def test_index_with_paid_makbuz(self, client, app):
        login(client, "admin", "admin-pass")
        party_id = _make_doctor(app, "Dr. Odenen Test")
        today = date.today()
        _add_work_order(
            app, party_id, today,
            [{"name": "RPE", "price": 300.0, "currency": "TL"}],
            [],
        )
        _create_makbuz(
            app, party_id, today.year, today.month,
            status=Makbuz.STATUS_PAID,
            paid_at=today,
            paid_amount=Decimal("360.00"),
        )
        response = client.get("/reports/?period=this_month")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "RPE" in html

    def test_doctor_detail_page(self, client, app):
        login(client, "admin", "admin-pass")
        party_id = _make_doctor(app, "Dr. Detay Test")
        today = date.today()
        _add_work_order(
            app, party_id, today,
            [{"name": "Forsus", "price": 500.0, "currency": "TL"}],
            [{"name": "Wire", "price": 50.0, "currency": "TL"}],
        )
        _create_makbuz(app, party_id, today.year, today.month, status=Makbuz.STATUS_SENT)
        response = client.get(f"/reports/doctor/{party_id}?period=this_month")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Dr. Detay Test" in html
        assert "Forsus" in html

    def test_doctor_detail_aging(self, client, app):
        login(client, "admin", "admin-pass")
        party_id = _make_doctor(app, "Dr. Yaslandirma Test")
        today = date.today()
        old_date = today - timedelta(days=90)
        _add_work_order(
            app, party_id, old_date,
            [{"name": "Bracket", "price": 250.0, "currency": "TL"}],
            [],
        )
        _create_makbuz(app, party_id, old_date.year, old_date.month, status=Makbuz.STATUS_SENT)
        response = client.get(f"/reports/doctor/{party_id}?period=this_year")
        assert response.status_code == 200

    def test_doctor_pdf(self, client, app):
        login(client, "admin", "admin-pass")
        party_id = _make_doctor(app, "Dr. PDF Test")
        today = date.today()
        _add_work_order(
            app, party_id, today,
            [{"name": "Lingual", "price": 800.0, "currency": "TL"}],
            [],
        )
        _create_makbuz(app, party_id, today.year, today.month, status=Makbuz.STATUS_SENT)
        response = client.get(f"/reports/pdf/doctor/{party_id}?period=this_month")
        assert response.status_code == 200
        assert response.content_type == "application/pdf"

    def test_period_pdf(self, client, app):
        login(client, "admin", "admin-pass")
        party_id = _make_doctor(app, "Dr. Donem PDF Test")
        today = date.today()
        _add_work_order(
            app, party_id, today,
            [{"name": "Aligner", "price": 1500.0, "currency": "TL"}],
            [],
        )
        _create_makbuz(app, party_id, today.year, today.month, status=Makbuz.STATUS_SENT)
        response = client.get("/reports/pdf/period?period=this_month")
        assert response.status_code == 200
        assert response.content_type == "application/pdf"

    def test_staff_can_access(self, client, app):
        login(client, "staff", "staff-pass")
        response = client.get("/reports/?period=this_month")
        assert response.status_code == 200

    def test_multiple_doctors(self, client, app):
        login(client, "admin", "admin-pass")
        pid1 = _make_doctor(app, "Dr. Birinci", "+905551112233")
        pid2 = _make_doctor(app, "Dr. İkinci", "+905551112244")
        today = date.today()
        _add_work_order(app, pid1, today, [{"name": "A", "price": 100.0, "currency": "TL"}], [])
        _add_work_order(app, pid2, today, [{"name": "B", "price": 200.0, "currency": "TL"}], [])

        response = client.get("/reports/?period=this_month")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Dr. Birinci" in html
        assert "Dr. İkinci" in html

    def test_devcaden_borc(self, client, app):
        login(client, "admin", "admin-pass")
        party_id = _make_doctor(app, "Dr. Devir Test")
        today = date.today()
        old_date = today - timedelta(days=60)
        _add_work_order(
            app, party_id, old_date,
            [{"name": "Torus", "price": 400.0, "currency": "TL"}],
            [],
        )
        _create_makbuz(app, party_id, old_date.year, old_date.month, status=Makbuz.STATUS_SENT)
        _add_work_order(
            app, party_id, today,
            [{"name": "New", "price": 150.0, "currency": "TL"}],
            [],
        )
        response = client.get(f"/reports/doctor/{party_id}?period=this_month")
        assert response.status_code == 200

    def test_pdf_requires_auth(self, client):
        response = client.get("/reports/pdf/period?period=this_month")
        assert response.status_code == 302


# ---------------------------------------------------------------------------
# PDF Service Tests
# ---------------------------------------------------------------------------

class TestReportsPDF:
    """PDF rapor üretim testleri."""

    def test_doctor_report_pdf_generation(self):
        from app.services.reports_pdf_service import generate_doctor_report_pdf
        pdf_bytes = generate_doctor_report_pdf(
            clinic_name="Test Klinik",
            clinic_phone="02121234567",
            clinic_email="test@test.com",
            title="TEST RAPORU",
            subtitle="01.07.2026 – 31.07.2026",
            doctor_name="Dr. Test Hekim",
            period_label="Temmuz 2026",
            summary_rows=[
                ("İş emri sayısı", "5"),
                ("Toplam (₺)", "1.500,00"),
            ],
            work_orders=[],
            makbuzlar=[],
            aging_rows=[],
            vat_summary=[],
        )
        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 100
        assert b"%PDF" in pdf_bytes

    def test_period_report_pdf_generation(self):
        from app.services.reports_pdf_service import generate_period_report_pdf
        pdf_bytes = generate_period_report_pdf(
            clinic_name="Test Klinik",
            clinic_phone="",
            clinic_email="",
            title="DÖNEMSEL RAPOR",
            period_label="Temmuz 2026",
            summary_rows=[("Toplam", "₺5.000,00")],
            doctor_rows=[],
            aging_rows=[],
            vat_summary=[],
        )
        assert isinstance(pdf_bytes, bytes)
        assert b"%PDF" in pdf_bytes

    def test_pdf_with_vat_summary(self):
        from app.services.reports_pdf_service import generate_doctor_report_pdf
        pdf_bytes = generate_doctor_report_pdf(
            clinic_name="Test Klinik",
            clinic_phone="",
            clinic_email="",
            title="KDV TEST",
            subtitle="Test",
            doctor_name="Dr. KDV",
            period_label="Test",
            summary_rows=[],
            vat_summary=[
                {"label": "%20", "gross": Decimal("1000.00"), "vat_amount": Decimal("200.00"), "net": Decimal("1000.00")},
                {"label": "%10", "gross": Decimal("500.00"), "vat_amount": Decimal("50.00"), "net": Decimal("500.00")},
            ],
        )
        assert isinstance(pdf_bytes, bytes)
        assert b"%PDF" in pdf_bytes

    def test_pdf_with_aging(self):
        from app.services.reports_pdf_service import generate_doctor_report_pdf
        pdf_bytes = generate_doctor_report_pdf(
            clinic_name="Test Klinik",
            clinic_phone="",
            clinic_email="",
            title="AGING TEST",
            subtitle="Test",
            doctor_name="Dr. Aging",
            period_label="Test",
            summary_rows=[],
            aging_rows=[
                {"label": "Vadesi henüz gelmedi", "count": 2, "amount": Decimal("500.00")},
                {"label": "31-60 gün gecikmiş", "count": 1, "amount": Decimal("300.00")},
            ],
        )
        assert isinstance(pdf_bytes, bytes)
        assert b"%PDF" in pdf_bytes


# ---------------------------------------------------------------------------
# Edge Case Tests
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Sınır durumları ve hata testleri."""

    def test_empty_period_no_crash(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/reports/?period=this_month")
        assert response.status_code == 200

    def test_nonexistent_doctor(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/reports/doctor/99999?period=this_month")
        assert response.status_code == 200

    def test_vat_zero_rate(self, client, app):
        login(client, "admin", "admin-pass")
        party_id = _make_doctor(app, "Dr. Sifir KDV")
        today = date.today()
        _add_work_order(
            app, party_id, today,
            [{"name": "Muaf Is", "price": 100.0, "currency": "TL"}],
            [],
        )
        with app.app_context():
            makbuz = Makbuz(
                party_id=party_id,
                year=today.year,
                month=today.month,
                work_order_count=1,
                subtotal=Decimal("100.00"),
                vat_applied=True,
                vat_rate=Decimal("0.00"),
                status=Makbuz.STATUS_SENT,
                generated_at=datetime.now().astimezone(),
            )
            makbuz.recalculate_totals()
            db.session.add(makbuz)
            db.session.commit()

        response = client.get("/reports/?period=this_month")
        assert response.status_code == 200

    def test_large_date_range(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/reports/?period=this_year")
        assert response.status_code == 200

    def test_daily_period(self, client, app):
        login(client, "admin", "admin-pass")
        party_id = _make_doctor(app, "Dr. Gunluk Test")
        today = date.today()
        _add_work_order(
            app, party_id, today,
            [{"name": "Gunluk Is", "price": 50.0, "currency": "TL"}],
            [],
        )
        response = client.get("/reports/?period=daily")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Gunluk Is" in html

    def test_summary_tab_structure(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/reports/?period=this_month")
        html = response.get_data(as_text=True)
        assert "tab-overview" in html
        assert "tab-doctors" in html
        assert "tab-daily" in html
        assert "tab-aging" in html
        assert "tab-vat" in html

    def test_pdf_nonexistent_doctor(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/reports/pdf/doctor/99999?period=this_month")
        assert response.status_code == 200
        assert response.content_type == "application/pdf"
