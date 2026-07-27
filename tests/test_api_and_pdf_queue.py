"""PDF kuyruğu ve API endpoint testleri."""

from __future__ import annotations



from app.extensions import db
from app.models.models import Party, PartyType
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

    def test_worker_thread_has_app_context(self, app):
        """Regression test: the worker thread must push app.app_context()
        like every other background service (whatsapp_service,
        makbuz_send_queue), otherwise any submitted job that touches the DB
        or current_app raises "working outside of application context"."""
        from app.services.pdf_queue import PdfQueue
        from flask import current_app

        def _needs_app_context():
            # Raises RuntimeError outside an app context.
            return current_app.name

        job_id = PdfQueue.submit(_needs_app_context)
        import time
        time.sleep(0.3)

        job = PdfQueue.get_result(job_id)
        assert job is not None
        assert job.status == "completed", job.error
        assert job.result == app.name


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


class TestApiBearerTokenAuth:
    """/api/v1/* used to redirect (302) an unauthenticated caller to the
    HTML login page — useless for a script or mobile client. It now
    returns 401/403 JSON, and accepts a per-user Bearer token as an
    alternative to a browser session."""

    def test_no_credentials_returns_401_json(self, client, app):
        res = client.get("/api/v1/parties")
        assert res.status_code == 401
        assert res.get_json() == {"error": "unauthorized"}

    def test_garbage_bearer_token_returns_401_json(self, client, app):
        res = client.get(
            "/api/v1/parties",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert res.status_code == 401

    def test_valid_bearer_token_grants_access(self, client, app):
        from app.authz import hash_api_token
        from app.models.models import User

        raw_token = "test-token-abc123"
        with app.app_context():
            admin = db.session.execute(
                db.select(User).where(User.username == "admin")
            ).scalar_one()
            admin.api_token_hash = hash_api_token(raw_token)
            db.session.commit()

        res = client.get(
            "/api/v1/parties",
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        assert res.status_code == 200
        assert isinstance(res.get_json(), list)

    def test_bearer_token_respects_role_permissions(self, client, app):
        """A staff token should still work for clinical.view but be denied
        wherever authz.STAFF_PERMISSIONS doesn't include the permission."""
        from app.authz import hash_api_token
        from app.models.models import User

        raw_token = "staff-token-xyz789"
        with app.app_context():
            staff = db.session.execute(
                db.select(User).where(User.username == "staff")
            ).scalar_one()
            staff.api_token_hash = hash_api_token(raw_token)
            db.session.commit()

        headers = {"Authorization": f"Bearer {raw_token}"}
        res = client.get("/api/v1/parties", headers=headers)
        assert res.status_code == 200

    def test_generate_and_revoke_api_token(self, client, app):
        from app.models.models import User

        login(client, "admin", "admin-pass")
        resp = client.post("/settings/api-token/generate", follow_redirects=True)
        assert resp.status_code == 200
        assert "Yeni API token".encode() in resp.data

        with app.app_context():
            admin = db.session.execute(
                db.select(User).where(User.username == "admin")
            ).scalar_one()
            assert admin.api_token_hash is not None

        resp = client.post("/settings/api-token/revoke", follow_redirects=True)
        assert "iptal edildi".encode() in resp.data
        with app.app_context():
            admin = db.session.execute(
                db.select(User).where(User.username == "admin")
            ).scalar_one()
            assert admin.api_token_hash is None
