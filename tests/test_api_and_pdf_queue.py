"""PDF kuyruğu ve API endpoint testleri."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.extensions import db
from app.models.models import Makbuz, Party, PartyType, Treatment, WorkOrder
from conftest import login


def _make_dentist(app, name="Dr. API Test", phone="+905550001234"):
    with app.app_context():
        party = Party(party_type=PartyType.DENTIST, name=name, phone=phone, is_active=True)
        db.session.add(party)
        db.session.commit()
        return party.id


# ---------------------------------------------------------------------------
# PDF Queue tests
# ---------------------------------------------------------------------------

class TestPdfQueue:
    def test_submit_and_complete(self):
        from app.services.pdf_queue import PdfQueue

        def _success():
            return b"%PDF-fake"

        job_id = PdfQueue.submit(_success)
        import time
        time.sleep(0.3)

        job = PdfQueue.get_result(job_id)
        assert job is not None
        assert job.status == "completed"
        assert job.result == b"%PDF-fake"

    def test_submit_and_fail(self):
        from app.services.pdf_queue import PdfQueue

        def _fail():
            raise RuntimeError("boom")

        job_id = PdfQueue.submit(_fail)
        import time
        time.sleep(0.3)

        job = PdfQueue.get_result(job_id)
        assert job is not None
        assert job.status == "failed"
        assert "boom" in job.error

    def test_get_nonexistent_job(self):
        from app.services.pdf_queue import PdfQueue
        assert PdfQueue.get_result("nonexistent") is None


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

class TestApiParties:
    def test_list_parties(self, client, app):
        login(client, "admin", "admin-pass")
        res = client.get("/api/v1/parties")
        assert res.status_code == 200
        data = res.get_json()
        assert isinstance(data, list)
        assert len(data) > 0
        assert "name" in data[0]
        assert "party_type" in data[0]

    def test_get_party(self, client, app):
        login(client, "admin", "admin-pass")
        party_id = _make_dentist(app, name="Dr. API Detail")
        res = client.get(f"/api/v1/parties/{party_id}")
        assert res.status_code == 200
        data = res.get_json()
        assert data["party"]["name"] == "Dr. API Detail"
        assert "work_orders" in data
        assert "makbuz" in data

    def test_get_party_not_found(self, client, app):
        login(client, "admin", "admin-pass")
        res = client.get("/api/v1/parties/999999")
        assert res.status_code == 404


class TestApiWorkOrders:
    def test_list_work_orders(self, client, app):
        login(client, "admin", "admin-pass")
        res = client.get("/api/v1/work-orders")
        assert res.status_code == 200
        data = res.get_json()
        assert "work_orders" in data
        assert "period" in data
        assert "total" in data


class TestApiMakbuzlar:
    def test_list_makbuzlar(self, client, app):
        login(client, "admin", "admin-pass")
        res = client.get("/api/v1/makbuzlar")
        assert res.status_code == 200
        data = res.get_json()
        assert "makbuzlar" in data

    def test_get_makbuz_not_found(self, client, app):
        login(client, "admin", "admin-pass")
        res = client.get("/api/v1/makbuzlar/999999")
        assert res.status_code == 404


class TestApiTreatments:
    def test_list_treatments(self, client, app):
        login(client, "admin", "admin-pass")
        res = client.get("/api/v1/treatments")
        assert res.status_code == 200
        data = res.get_json()
        assert isinstance(data, list)
        assert len(data) > 0
        assert "name" in data[0]
        assert "category" in data[0]

    def test_list_treatments_by_category(self, client, app):
        login(client, "admin", "admin-pass")
        res = client.get("/api/v1/treatments?category=ana_islemler")
        assert res.status_code == 200
        data = res.get_json()
        for t in data:
            assert t["category"] == "ana_islemler"


class TestApiExchangeRate:
    def test_get_exchange_rate(self, client, app):
        login(client, "admin", "admin-pass")
        res = client.get("/api/v1/exchange-rate")
        assert res.status_code == 200
        data = res.get_json()
        assert "eur_to_try" in data
        assert data["eur_to_try"] > 0


class TestApiDashboard:
    def test_dashboard_summary(self, client, app):
        login(client, "admin", "admin-pass")
        res = client.get("/api/v1/dashboard")
        assert res.status_code == 200
        data = res.get_json()
        assert "active_dentists" in data
        assert "monthly_work_orders" in data
        assert "monthly_total_try" in data
        assert "eur_to_try" in data
