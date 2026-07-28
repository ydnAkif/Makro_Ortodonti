"""Kapsamlı alan testleri — kapsama alanını artıran dal ve ifade testleri.

NOT: Bu dosya adı tarihseldir. İçerik, alan mantığını test eden kapsamlı
testlerden oluşur; saf "coverage artırma" testleri içermez.
"""

from __future__ import annotations

import io
import json
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import bcrypt
import pytest

from conftest import login


def _make_invoice(session, party_id, items, invoice_date=None, due_date=None):
    from app.models.models import Invoice, InvoiceItem, InvoiceItemType
    invoice_date = invoice_date or date.today()
    invoice = Invoice(
        party_id=party_id,
        invoice_number=f"MKR-COV-{party_id}-{session.query(Invoice).count() + 1:04d}",
        invoice_date=invoice_date,
        due_date=due_date,
        exchange_rate=40.0,
    )
    session.add(invoice)
    session.flush()

    for item_data in items:
        unit_eur = Decimal(str(item_data.get("unit_price_eur", 50.0)))
        qty = item_data.get("quantity", 1)
        vat = Decimal(str(item_data.get("vat_rate", 0)))
        item = InvoiceItem(
            invoice_id=invoice.id,
            item_type=item_data.get("item_type", InvoiceItemType.TREATMENT),
            treatment_id=item_data.get("treatment_id"),
            description=item_data.get("description", "Test Item"),
            quantity=qty,
            unit_price_eur=unit_eur,
            unit_price_try=unit_eur * Decimal("40.0"),
            vat_rate=vat,
        )
        session.add(item)

    session.flush()
    invoice.recalculate_totals()
    session.commit()
    return invoice


# ============================================================
# database.py (0% → target 80%+)
# ============================================================


class TestDatabaseMigration:
    def test_migrate_patients_creates_party_for_unlinked(self, client, app):
        from app.extensions import db
        from app.models.models import Patient, Party, PartyType
        from app.models.database import migrate_patients_to_parties

        with app.app_context():
            p = Patient(first_name="Migrate", last_name="Me", phone="5550000001")
            db.session.add(p)
            db.session.commit()

            count = migrate_patients_to_parties()
            assert count >= 1

            linked = db.session.get(Patient, p.id)
            assert linked.party_id is not None
            party = db.session.get(Party, linked.party_id)
            assert party.party_type == PartyType.PATIENT
            assert party.first_name == "Migrate"

    def test_migrate_patients_links_to_existing_party(self, client, app):
        from app.extensions import db
        from app.models.models import Patient, Party, PartyType
        from app.models.database import migrate_patients_to_parties

        with app.app_context():
            party = Party(
                party_type=PartyType.PATIENT,
                name="Existing Party",
                first_name="Existing",
                last_name="Party",
                phone="5550000002",
            )
            db.session.add(party)
            db.session.flush()

            p = Patient(first_name="Existing", last_name="Party", phone="5550000002")
            db.session.add(p)
            db.session.commit()

            count = migrate_patients_to_parties()
            assert count >= 1
            assert db.session.get(Patient, p.id).party_id == party.id

    def test_migrate_patients_no_op_when_all_linked(self, client, app):
        from app.models.database import migrate_patients_to_parties
        with app.app_context():
            count = migrate_patients_to_parties()
            assert count == 0

    def test_link_invoices_to_parties(self, client, app):
        from app.extensions import db
        from app.models.models import Invoice, Patient, Party, PartyType
        from app.models.database import link_invoices_to_parties

        with app.app_context():
            patient = db.session.execute(
                db.select(Patient).limit(1)
            ).scalar_one()
            party = db.session.execute(
                db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
            ).scalar_one()
            patient.party_id = party.id
            db.session.flush()

            inv = Invoice(
                patient_id=patient.id,
                party_id=None,
                invoice_number="LINK-TEST-001",
                invoice_date=date.today(),
                total_eur=Decimal("100.00"),
                total_try=Decimal("4000.00"),
                exchange_rate=Decimal("40.0000"),
                status="pending",
            )
            db.session.add(inv)
            db.session.commit()

            count = link_invoices_to_parties()
            assert count >= 1
            assert db.session.get(Invoice, inv.id).party_id == party.id

    def test_link_invoices_no_op_when_all_linked(self, client, app):
        from app.models.database import link_invoices_to_parties
        with app.app_context():
            count = link_invoices_to_parties()
            assert count == 0

    def test_hash_password(self):
        from app.models.database import _hash_password
        h = _hash_password("testpass123")
        assert bcrypt.checkpw(b"testpass123", h.encode("utf-8"))

    def test_is_valid_bcrypt_hash_valid(self):
        from app.models.database import _is_valid_bcrypt_hash
        h = bcrypt.hashpw(b"test", bcrypt.gensalt()).decode("utf-8")
        assert _is_valid_bcrypt_hash(h) is True

    def test_is_valid_bcrypt_hash_none(self):
        from app.models.database import _is_valid_bcrypt_hash
        assert _is_valid_bcrypt_hash(None) is False
        assert _is_valid_bcrypt_hash("") is False

    def test_is_valid_bcrypt_hash_invalid(self):
        from app.models.database import _is_valid_bcrypt_hash
        assert _is_valid_bcrypt_hash("not-a-hash") is False

    def test_resolve_admin_password_from_env(self):
        from app.models.database import _resolve_admin_password
        with patch.dict(os.environ, {"DEFAULT_ADMIN_PASSWORD": "strongpassword123", "FLASK_DEBUG": "false"}, clear=False):
            pw, generated = _resolve_admin_password()
            assert pw == "strongpassword123"
            assert generated is False

    def test_resolve_admin_password_weak_rejected_in_production(self):
        from app.models.database import _resolve_admin_password
        with patch.dict(os.environ, {"DEFAULT_ADMIN_PASSWORD": "admin123", "FLASK_DEBUG": "false", "TESTING": "false"}, clear=False):
            os.environ.pop("PYTEST_CURRENT_TEST", None)
            pw, generated = _resolve_admin_password()
            assert generated is True
            assert len(pw) >= 8

    def test_resolve_admin_password_no_env(self):
        from app.models.database import _resolve_admin_password
        with patch.dict(os.environ, {"DEFAULT_ADMIN_PASSWORD": ""}, clear=False):
            pw, generated = _resolve_admin_password()
            assert generated is True
            assert len(pw) >= 8

    def test_seed_sample_data_fresh(self, client, app):
        from app.extensions import db
        from app.models.models import Treatment, User, Party, ExchangeRate, PatientTreatment, Invoice, InvoiceItem, Payment, Patient
        from app.models.database import seed_sample_data

        with app.app_context():
            db.session.execute(db.text("PRAGMA foreign_keys = OFF"))
            for model in [Payment, InvoiceItem, Invoice, PatientTreatment, Treatment, Patient, Party, ExchangeRate]:
                db.session.execute(db.delete(model))
            admin = db.session.execute(db.select(User).where(User.username == "admin")).scalar_one_or_none()
            if admin:
                db.session.delete(admin)
            db.session.commit()
            db.session.execute(db.text("PRAGMA foreign_keys = ON"))

            seed_sample_data()
            assert db.session.execute(db.select(Treatment).limit(1)).scalar_one_or_none() is not None
            assert db.session.execute(db.select(User).where(User.username == "admin")).scalar_one_or_none() is not None

    def test_seed_sample_data_creates_missing_admin(self, client, app):
        from app.extensions import db
        from app.models.models import User
        from app.models.database import seed_sample_data

        with app.app_context():
            admin = db.session.execute(db.select(User).where(User.username == "admin")).scalar_one()
            db.session.delete(admin)
            db.session.commit()

            seed_sample_data()
            assert db.session.execute(db.select(User).where(User.username == "admin")).scalar_one_or_none() is not None

    def test_seed_sample_data_fixes_invalid_hash(self, client, app):
        from app.extensions import db
        from app.models.models import User
        from app.models.database import seed_sample_data, _is_valid_bcrypt_hash

        with app.app_context():
            admin = db.session.execute(db.select(User).where(User.username == "admin")).scalar_one()
            admin.password_hash = "not-a-valid-hash"
            db.session.commit()

            seed_sample_data()
            admin2 = db.session.execute(db.select(User).where(User.username == "admin")).scalar_one()
            assert _is_valid_bcrypt_hash(admin2.password_hash)

    def test_init_db_calls_upgrade(self, app):
        import app.models.database as db_mod
        with patch.object(db_mod.os, "makedirs"):
            with patch("flask_migrate.upgrade") as mock_upgrade:
                db_mod.init_db()
                mock_upgrade.assert_called_once()


# ============================================================
# exchange_service.py (32% → target 85%+)
# ============================================================

class TestExchangeService:
    def test_fetch_eur_try_rate_first_provider(self, app):
        from app.services.exchange_service import fetch_eur_try_rate

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"rate": 38.5}
        mock_resp.raise_for_status = MagicMock()

        with patch("app.services.exchange_service.requests.get", return_value=mock_resp):
            rate = fetch_eur_try_rate()
            assert rate == Decimal("38.5")

    def test_fetch_eur_try_rate_second_provider(self, app):
        from app.services.exchange_service import fetch_eur_try_rate

        def side_effect(url, timeout):
            mock = MagicMock()
            if "frankfurter.dev" in url:
                raise Exception("Provider 1 down")
            mock.json.return_value = {"rates": {"TRY": 39.2}}
            mock.raise_for_status = MagicMock()
            return mock

        with patch("app.services.exchange_service.requests.get", side_effect=side_effect):
            rate = fetch_eur_try_rate()
            assert rate == Decimal("39.2")

    def test_fetch_eur_try_rate_all_fail(self, app):
        from app.services.exchange_service import fetch_eur_try_rate

        with patch("app.services.exchange_service.requests.get", side_effect=Exception("Network error")):
            with pytest.raises(RuntimeError):
                fetch_eur_try_rate()

    def test_fetch_eur_try_rate_unexpected_schema(self, app):
        from app.services.exchange_service import fetch_eur_try_rate

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"unexpected": "schema"}
        mock_resp.raise_for_status = MagicMock()

        with patch("app.services.exchange_service.requests.get", return_value=mock_resp):
            with pytest.raises(RuntimeError):
                fetch_eur_try_rate()

    def test_fetch_and_store_rate_new(self, app):
        from app.services.exchange_service import fetch_and_store_rate

        with app.app_context():
            with patch("app.services.exchange_service.fetch_eur_try_rate", return_value=Decimal("42.0")):
                rate = fetch_and_store_rate()
                assert rate == Decimal("42.0")

    def test_fetch_and_store_rate_update_existing(self, app):
        from app.extensions import db
        from app.models.models import ExchangeRate
        from app.services.exchange_service import fetch_and_store_rate

        with app.app_context():
            existing = db.session.execute(
                db.select(ExchangeRate).where(ExchangeRate.source == "ecb")
            ).scalar_one()

            with patch("app.services.exchange_service.fetch_eur_try_rate", return_value=Decimal("55.5")):
                rate = fetch_and_store_rate()
                assert rate == Decimal("55.5")
                updated = db.session.get(ExchangeRate, existing.id)
                assert updated.eur_to_try == Decimal("55.5")

    def test_get_latest_rate_with_data(self, app):
        from app.services.exchange_service import get_latest_rate
        with app.app_context():
            rate = get_latest_rate()
            assert rate is not None
            assert rate > 0

    def test_get_latest_rate_empty(self, app):
        from app.extensions import db
        from app.models.models import ExchangeRate
        from app.services.exchange_service import get_latest_rate

        with app.app_context():
            db.session.execute(db.delete(ExchangeRate))
            db.session.commit()
            assert get_latest_rate() is None

    def test_get_rate_health_no_rate(self, app):
        from app.extensions import db
        from app.models.models import ExchangeRate
        from app.services.exchange_service import get_rate_health

        with app.app_context():
            db.session.execute(db.delete(ExchangeRate))
            db.session.commit()
            h = get_rate_health()
            assert h["exists"] is False
            assert h["is_stale"] is True

    def test_get_rate_health_fresh(self, app):
        from app.services.exchange_service import get_rate_health
        with app.app_context():
            h = get_rate_health(max_age_days=30)
            assert h["exists"] is True
            assert h["is_stale"] is False

    def test_get_rate_health_stale(self, app):
        from app.extensions import db
        from app.models.models import ExchangeRate
        from app.services.exchange_service import get_rate_health
        from datetime import timedelta

        with app.app_context():
            db.session.execute(db.delete(ExchangeRate))
            db.session.commit()
            old = ExchangeRate(rate_date=date.today() - timedelta(days=10), eur_to_try=40.0, source="ecb-old")
            db.session.add(old)
            db.session.commit()

            h = get_rate_health(max_age_days=2)
            assert h["age_days"] >= 2

    def test_ensure_daily_rate_first_check(self, app):
        from app.services.exchange_service import ensure_daily_rate
        import app.services.exchange_service as es

        with app.app_context():
            es._last_auto_check_date = None
            with patch("app.services.exchange_service.get_rate_health") as mock_health:
                mock_health.return_value = {"exists": True, "is_stale": False}
                result = ensure_daily_rate()
                assert "updated_today" in result

    def test_ensure_daily_rate_already_checked(self, app):
        from app.services.exchange_service import ensure_daily_rate
        import app.services.exchange_service as es

        with app.app_context():
            es._last_auto_check_date = date.today()
            with patch("app.services.exchange_service.get_rate_health") as mock_health:
                mock_health.return_value = {"exists": True, "is_stale": False}
                ensure_daily_rate()
                mock_health.assert_called_once()


# ============================================================
# whatsapp_service.py (42% → target 85%+)
# ============================================================

class TestWhatsAppService:
    def test_get_client_success(self, app):
        from app.services.whatsapp_service import WhatsAppService
        WhatsAppService._client = None

        mock_new_client = MagicMock()
        mock_neonize = MagicMock()
        mock_neonize.client.NewClient = mock_new_client
        with patch.dict("sys.modules", {"neonize": mock_neonize, "neonize.client": mock_neonize.client}):
            client = WhatsAppService.get_client()
            assert client is not None

    def test_get_client_import_error(self, app):
        from app.services.whatsapp_service import WhatsAppService
        WhatsAppService._client = None

        with patch("builtins.__import__", side_effect=ImportError("no neonize")):
            result = WhatsAppService.get_client()
            assert result is None

    def test_connect_with_phone_pair_code(self, app):
        from app.services.whatsapp_service import WhatsAppService
        WhatsAppService._client = None
        WhatsAppService._connected = False

        mock_client = MagicMock()
        with patch.object(WhatsAppService, "get_client", return_value=mock_client):
            with patch("app.services.whatsapp_service.db") as mock_db:
                mock_session = MagicMock()
                mock_session.scalar_one_or_none.return_value = None
                mock_db.session.execute.return_value = mock_session
                mock_db.session.commit = MagicMock()
                mock_db.session.add = MagicMock()
                result = WhatsAppService.connect(phone_number="+905551234567")
                assert result["success"] is True

    def test_connect_start_failure(self, app):
        from app.services.whatsapp_service import WhatsAppService
        WhatsAppService._client = None

        with patch.object(WhatsAppService, "start", return_value=False):
            with patch("app.services.whatsapp_service.db") as mock_db:
                mock_session = MagicMock()
                mock_db.session.execute.return_value = mock_session
                result = WhatsAppService.connect(phone_number="+905551234567")
                assert result["success"] is False

    def test_connect_without_phone_qr(self, app):
        from app.services.whatsapp_service import WhatsAppService
        WhatsAppService._client = None

        mock_client = MagicMock()
        with patch.object(WhatsAppService, "get_client", return_value=mock_client):
            with patch("app.services.whatsapp_service.db") as mock_db:
                mock_session = MagicMock()
                mock_db.session.execute.return_value = mock_session
                mock_db.session.commit = MagicMock()
                result = WhatsAppService.connect()
                assert result["success"] is True

    def test_connect_client_none(self, app):
        from app.services.whatsapp_service import WhatsAppService
        WhatsAppService._client = None

        with patch.object(WhatsAppService, "get_client", return_value=None):
            result = WhatsAppService.connect()
            assert result["success"] is False

    def test_connect_exception(self, app):
        from app.services.whatsapp_service import WhatsAppService
        WhatsAppService._client = None

        with patch.object(WhatsAppService, "get_client", side_effect=Exception("boom")):
            result = WhatsAppService.connect()
            assert result["success"] is False

    def test_disconnect(self, app):
        from app.services.whatsapp_service import WhatsAppService
        WhatsAppService._connected = True
        with patch("app.services.whatsapp_service.db") as mock_db:
            mock_session = MagicMock()
            mock_db.session.execute.return_value = mock_session
            mock_db.session.commit = MagicMock()
            result = WhatsAppService.disconnect()
            assert result["success"] is True
            assert WhatsAppService._connected is False

    def test_disconnect_stops_client(self, app):
        from app.services.whatsapp_service import WhatsAppService
        mock_client = MagicMock()
        WhatsAppService._client = mock_client
        WhatsAppService._connected = True
        with patch("app.services.whatsapp_service.db") as mock_db:
            mock_session = MagicMock()
            mock_db.session.execute.return_value = mock_session
            result = WhatsAppService.disconnect()
            assert result["success"] is True
            assert WhatsAppService._connected is False
            mock_client.stop.assert_called_once()

    def test_get_status_with_session(self, app):
        from app.extensions import db
        from app.models.models import WhatsAppSession
        from app.services.whatsapp_service import WhatsAppService

        with app.app_context():
            s = WhatsAppSession(session_id="default", status="connected", phone_number="+905551112222")
            db.session.add(s)
            db.session.commit()
            WhatsAppService._connected = True

            status = WhatsAppService.get_status()
            assert status["connected"] is True
            assert status["phone_number"] == "+905551112222"

    def test_get_status_no_session(self, app):
        from app.services.whatsapp_service import WhatsAppService
        WhatsAppService._connected = False
        status = WhatsAppService.get_status()
        assert status["connected"] is False
        assert status["status"] == "disconnected"

    def test_get_status_exception(self, app):
        from app.services.whatsapp_service import WhatsAppService
        with patch("app.services.whatsapp_service.db") as mock_db:
            mock_db.session.execute.side_effect = Exception("db error")
            status = WhatsAppService.get_status()
            assert status["connected"] is False

    def test_send_message_not_connected(self, app):
        from app.services.whatsapp_service import WhatsAppService
        WhatsAppService._connected = False
        result = WhatsAppService.send_message("+905551112222", "test")
        assert result["success"] is False

    def test_send_message_client_none(self, app):
        from app.services.whatsapp_service import WhatsAppService
        WhatsAppService._connected = True
        with patch.object(WhatsAppService, "get_client", return_value=None):
            result = WhatsAppService.send_message("+905551112222", "test")
            assert result["success"] is False

    def test_send_message_success(self, app):
        from app.services.whatsapp_service import WhatsAppService
        WhatsAppService._connected = True

        mock_client = MagicMock()
        with patch.object(WhatsAppService, "get_client", return_value=mock_client):
            result = WhatsAppService.send_message("+905551112222", "hello")
            assert result["success"] is True
            mock_client.send_message.assert_called_once()

    def test_send_message_with_jid(self, app):
        from app.services.whatsapp_service import WhatsAppService
        WhatsAppService._connected = True

        mock_client = MagicMock()
        with patch.object(WhatsAppService, "get_client", return_value=mock_client):
            result = WhatsAppService.send_message("905551112222@s.whatsapp.net", "hello")
            assert result["success"] is True

    def test_send_message_exception(self, app):
        from app.services.whatsapp_service import WhatsAppService
        WhatsAppService._connected = True

        mock_client = MagicMock()
        mock_client.send_message.side_effect = Exception("send fail")
        with patch.object(WhatsAppService, "get_client", return_value=mock_client):
            result = WhatsAppService.send_message("+905551112222", "hello")
            assert result["success"] is False

    def test_send_invoice_message_party_phone(self, client, app):
        from app.extensions import db
        from app.models.models import Party, PartyType
        from app.services.whatsapp_service import WhatsAppService

        with app.app_context():
            party = db.session.execute(
                db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
            ).scalar_one()
            invoice = _make_invoice(
                session=db.session,
                party_id=party.id,
                items=[{"item_type": "service", "description": "Test", "quantity": 1, "unit_price_eur": 100}],
                invoice_date=date.today(),
            )
            WhatsAppService._connected = False
            result = WhatsAppService.send_invoice_message(invoice)
            assert result["success"] is False
            assert "telefon" in result["message"] or "bağlı" in result["message"]

    def test_send_invoice_message_no_phone(self, client, app):
        from app.extensions import db
        from app.models.models import Party, PartyType
        from app.services.whatsapp_service import WhatsAppService

        with app.app_context():
            party = Party(party_type=PartyType.COMPANY_CUSTOMER, name="No Phone Corp")
            db.session.add(party)
            db.session.flush()
            invoice = _make_invoice(
                session=db.session,
                party_id=party.id,
                items=[{"item_type": "service", "description": "Test", "quantity": 1, "unit_price_eur": 100}],
                invoice_date=date.today(),
            )
            WhatsAppService._connected = False
            result = WhatsAppService.send_invoice_message(invoice)
            assert result["success"] is False

    def test_send_reminder_with_phone(self, app):
        from app.services.whatsapp_service import WhatsAppService
        WhatsAppService._connected = False
        patient = MagicMock()
        patient.phone = "+905551112222"
        result = WhatsAppService.send_reminder(patient, "reminder msg")
        assert result["success"] is False

    def test_send_reminder_no_phone(self, app):
        from app.services.whatsapp_service import WhatsAppService
        patient = MagicMock()
        patient.phone = None
        result = WhatsAppService.send_reminder(patient, "reminder msg")
        assert result["success"] is False


# ============================================================
# whatsapp routes (31% → target 85%+)
# ============================================================

class TestWhatsAppRoutes:
    def test_index(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/whatsapp/")
        assert response.status_code == 200

    def test_connect(self, client, app):
        login(client, "admin", "admin-pass")
        with patch("app.services.whatsapp_service.WhatsAppService.connect", return_value={"success": True, "message": "OK"}):
            response = client.post("/whatsapp/connect", data={"phone_number": "+905551234567"}, follow_redirects=False)
            assert response.status_code == 302

    def test_connect_without_phone(self, client, app):
        login(client, "admin", "admin-pass")
        with patch("app.services.whatsapp_service.WhatsAppService.connect", return_value={"success": True, "message": "QR bekleniyor"}):
            response = client.post("/whatsapp/connect", data={"phone_number": ""}, follow_redirects=False)
            assert response.status_code == 302

    def test_disconnect(self, client, app):
        login(client, "admin", "admin-pass")
        with patch("app.services.whatsapp_service.WhatsAppService.disconnect", return_value={"success": True, "message": "Kesildi"}):
            response = client.post("/whatsapp/disconnect", follow_redirects=False)
            assert response.status_code == 302

    def test_send_message(self, client, app):
        login(client, "admin", "admin-pass")
        with patch("app.services.whatsapp_service.WhatsAppService.send_message", return_value={"success": True, "message": "Gonderildi"}):
            response = client.post("/whatsapp/send", data={
                "phone_number": "+905551234567",
                "message": "Test mesaj",
            }, follow_redirects=False)
            assert response.status_code == 302

    def test_send_message_missing_fields(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.post("/whatsapp/send", data={
            "phone_number": "",
            "message": "",
        }, follow_redirects=False)
        assert response.status_code == 302

    def test_send_makbuz(self, client, app):
        from app.extensions import db
        from app.models.models import Party, PartyType, WorkOrder, Makbuz

        login(client, "admin", "admin-pass")
        with app.app_context():
            party = db.session.execute(
                db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
            ).scalar_one()
            party_id = party.id
            db.session.add(WorkOrder(
                party_id=party_id, work_date=date.today(), apparatus_type="Nance",
                patient_name="Test Hasta", apparatus_price=500, extra_price=0, total_price=500,
            ))
            db.session.commit()

        response = client.post(
            f"/makbuzlar/{party_id}/generate",
            data={"year": date.today().year, "month": date.today().month},
            follow_redirects=False,
        )
        assert response.status_code == 302

        with app.app_context():
            makbuz = db.session.execute(
                db.select(Makbuz).where(Makbuz.party_id == party_id)
            ).scalar_one()
            makbuz_id = makbuz.id
            assert makbuz.grand_total == 500

        with patch("app.services.whatsapp_service.WhatsAppService.send_makbuz_message", return_value={"success": True, "message": "Gonderildi"}):
            response = client.post(f"/makbuzlar/{makbuz_id}/send", follow_redirects=False)
            assert response.status_code == 302

        with app.app_context():
            makbuz = db.session.get(Makbuz, makbuz_id)
            assert makbuz.status == Makbuz.STATUS_SENT

    def test_send_bulk(self, client, app):
        from app.extensions import db
        from app.models.models import Party, PartyType
        from app.services.bulk_message_queue import BulkMessageQueue
        from app.services.whatsapp_service import WhatsAppService

        login(client, "admin", "admin-pass")
        with app.app_context():
            party = db.session.execute(
                db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
            ).scalar_one()
            pid = party.id

        WhatsAppService._connected = True
        with patch("app.services.whatsapp_service.WhatsAppService.send_message", return_value={"success": True, "message": "OK"}):
            response = client.post("/whatsapp/send-bulk", data={
                "message": "Toplu mesaj",
                "patient_ids": [pid],
            }, follow_redirects=False)
            assert response.status_code == 302
            if BulkMessageQueue._thread is not None:
                BulkMessageQueue._thread.join(timeout=2)
            job = BulkMessageQueue.current_job()
            assert job is not None
            assert job["sent"] == 1

    def test_send_bulk_validation(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.post("/whatsapp/send-bulk", data={
            "message": "",
            "patient_ids": [],
        }, follow_redirects=False)
        assert response.status_code == 302

    def test_status(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/whatsapp/status")
        assert response.status_code == 200
        data = response.get_json()
        assert "connected" in data


# ============================================================
# privacy routes (53% → target 85%+)
# ============================================================

class TestPrivacyRoutes:
    def test_audit_index(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/privacy/audit")
        assert response.status_code == 200

    def test_anonymize_success(self, client, app):
        from app.extensions import db
        from app.models.models import Party, PartyType

        login(client, "admin", "admin-pass")
        with app.app_context():
            party = Party(party_type=PartyType.COMPANY_CUSTOMER, name="Anon Co", phone="5559990000")
            db.session.add(party)
            db.session.commit()
            pid = party.id

        response = client.post(f"/privacy/parties/{pid}/anonymize", content_type="application/json")
        assert response.status_code == 200
        data = response.get_json()
        assert data["ok"] is True

    def test_anonymize_409_with_active_invoices(self, client, app):
        from app.extensions import db
        from app.models.models import Party, PartyType, Makbuz

        login(client, "admin", "admin-pass")
        with app.app_context():
            party = db.session.execute(
                db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
            ).scalar_one()
            makbuz = Makbuz(
                party_id=party.id,
                year=2026,
                month=1,
                status="draft",
            )
            db.session.add(makbuz)
            db.session.commit()
            pid = party.id

        response = client.post(f"/privacy/parties/{pid}/anonymize", content_type="application/json")
        assert response.status_code == 409

    def test_export_party(self, client, app):
        from app.extensions import db
        from app.models.models import Party, PartyType

        login(client, "admin", "admin-pass")
        with app.app_context():
            party = db.session.execute(
                db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
            ).scalar_one()
            pid = party.id

        response = client.get(f"/privacy/parties/{pid}/export")
        assert response.status_code == 200
        assert response.content_type == "application/json"
        data = response.get_json()
        assert "party" in data
        assert "makbuzlar" in data
        assert "work_orders" in data



# ============================================================
# email_service.py (66% → target 85%+)
# ============================================================

class TestEmailService:
    def test_get_smtp_config(self, app):
        from app.services.email_service import get_smtp_config
        with app.app_context():
            with patch("app.services.security_service.decrypt_value", return_value="decrypted_pass"):
                config = get_smtp_config()
                assert "smtp_server" in config
                assert "smtp_port" in config

    def test_send_email_no_recipient(self, client, app):
        from app.extensions import db
        from app.models.models import Party, PartyType
        from app.services.email_service import send_invoice_email

        with app.app_context():
            party = Party(party_type=PartyType.COMPANY_CUSTOMER, name="No Email Co")
            db.session.add(party)
            db.session.flush()
            inv = _make_invoice(
                session=db.session,
                party_id=party.id,
                items=[{"item_type": "service", "description": "Test", "quantity": 1, "unit_price_eur": 100}],
                invoice_date=date.today(),
            )
            success, msg = send_invoice_email(inv)
            assert not success

    def test_send_email_smtp_not_configured(self, client, app):
        from app.extensions import db
        from app.models.models import Party, PartyType, Settings
        from app.services.email_service import send_invoice_email

        with app.app_context():
            party = Party(party_type=PartyType.COMPANY_CUSTOMER, name="Email Party", email="test@example.com")
            db.session.add(party)
            db.session.flush()

            for key in ("smtp_username", "smtp_password"):
                s = db.session.execute(db.select(Settings).where(Settings.key == key)).scalar_one()
                s.value = ""
            db.session.commit()

            inv = _make_invoice(
                session=db.session,
                party_id=party.id,
                items=[{"item_type": "service", "description": "Test", "quantity": 1, "unit_price_eur": 100}],
                invoice_date=date.today(),
            )
            success, msg = send_invoice_email(inv)
            assert not success
            assert "SMTP" in msg

    def test_send_email_smtp_connection_error(self, client, app):
        from app.extensions import db
        from app.models.models import Party, PartyType, Settings
        from app.services.email_service import send_invoice_email

        with app.app_context():
            s = db.session.execute(db.select(Settings).where(Settings.key == "smtp_username")).scalar_one()
            s.value = "test@example.com"
            s2 = db.session.execute(db.select(Settings).where(Settings.key == "smtp_password")).scalar_one()
            s2.value = "testpass"
            db.session.commit()

            party = db.session.execute(
                db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
            ).scalar_one()
            inv = _make_invoice(
                session=db.session,
                party_id=party.id,
                items=[{"item_type": "service", "description": "Test", "quantity": 1, "unit_price_eur": 100}],
                invoice_date=date.today(),
            )

            with patch("app.services.email_service.smtplib.SMTP", side_effect=Exception("Connection refused")):
                success, msg = send_invoice_email(inv)
                assert not success


# ============================================================
# validation_service.py (66% → target 85%+)
# ============================================================

class TestValidationService:

    def test_parse_decimal_valid(self):
        from app.services.validation_service import parse_decimal
        result = parse_decimal("123.456")
        assert result == Decimal("123.46")

    def test_parse_decimal_comma(self):
        from app.services.validation_service import parse_decimal
        result = parse_decimal("123,45")
        assert result == Decimal("123.45")

    def test_parse_decimal_empty(self):
        from app.services.validation_service import parse_decimal
        assert parse_decimal("") is None
        assert parse_decimal(None) is None

    def test_parse_decimal_infinite(self):
        from app.services.validation_service import parse_decimal
        assert parse_decimal("inf") is None

    def test_parse_decimal_invalid(self):
        from app.services.validation_service import parse_decimal
        assert parse_decimal("not-a-number") is None

    def test_parse_int_valid(self):
        from app.services.validation_service import parse_int
        assert parse_int("42") == 42
        assert parse_int(" 42 ") == 42

    def test_parse_int_empty(self):
        from app.services.validation_service import parse_int
        assert parse_int("") is None
        assert parse_int(None) is None

    def test_parse_int_invalid(self):
        from app.services.validation_service import parse_int
        assert parse_int("abc") is None

    def test_parse_enum_valid(self):
        from app.models.models import PartyType
        from app.services.validation_service import parse_enum
        assert parse_enum(PartyType, "dentist") == PartyType.DENTIST

    def test_parse_enum_invalid(self):
        from app.models.models import PartyType
        from app.services.validation_service import parse_enum
        assert parse_enum(PartyType, "nonexistent") is None

    def test_parse_enum_empty(self):
        from app.models.models import PartyType
        from app.services.validation_service import parse_enum
        assert parse_enum(PartyType, "") is None
        assert parse_enum(PartyType, None) is None


# ============================================================
# settings routes — extra coverage
# ============================================================

class TestSettingsExtra:
    def test_update_smtp_password_encrypted(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.post("/settings/update", data={
            "clinic_name": "Test Clinic",
            "smtp_password": "new-secret-password",
        }, follow_redirects=False)
        assert response.status_code == 302

        from app.extensions import db
        from app.models.models import Settings
        from app.services.security_service import decrypt_value
        with app.app_context():
            pw = db.session.execute(
                db.select(Settings.value).where(Settings.key == "smtp_password")
            ).scalar_one()
            assert decrypt_value(pw) == "new-secret-password"

    def test_update_smtp_password_empty_skipped(self, client, app):
        login(client, "admin", "admin-pass")
        from app.extensions import db
        from app.models.models import Settings
        with app.app_context():
            s = db.session.execute(db.select(Settings).where(Settings.key == "smtp_password")).scalar_one()
            s.value = "existing-encrypted"
            db.session.commit()

        response = client.post("/settings/update", data={
            "smtp_password": "",
        }, follow_redirects=False)
        assert response.status_code == 302

        with app.app_context():
            s2 = db.session.execute(db.select(Settings).where(Settings.key == "smtp_password")).scalar_one()
            assert s2.value == "existing-encrypted"

    def test_update_no_allowed_keys(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.post("/settings/update", data={
            "not_a_key": "value",
        }, follow_redirects=False)
        assert response.status_code == 302

    def test_exchange_rate_update_existing(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.post("/settings/exchange-rate/add", data={
            "rate_date": date.today().isoformat(),
            "eur_try_rate": "42.1234",
        }, follow_redirects=False)
        assert response.status_code == 302

        from app.extensions import db
        from app.models.models import ExchangeRate
        with app.app_context():
            rate = db.session.execute(
                db.select(ExchangeRate).where(
                    ExchangeRate.rate_date == date.today(),
                    ExchangeRate.source == "ecb",
                )
            ).scalar_one()
            assert rate.eur_to_try == Decimal("42.1234")

    def test_fetch_exchange_rate_error(self, client, app):
        login(client, "admin", "admin-pass")
        with patch("app.services.exchange_service.fetch_and_store_rate", side_effect=Exception("Network error")):
            response = client.post("/settings/exchange-rate/fetch", follow_redirects=False)
            assert response.status_code == 302


# ============================================================
# auth routes — extra coverage
# ============================================================

class TestAuthExtra:
    def test_login_already_authenticated_redirects(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/login", follow_redirects=False)
        assert response.status_code == 302
        assert "/" in response.headers["Location"]

    def test_login_with_safe_next(self, client, app):
        response = client.post("/login?next=/invoices/", data={
            "username": "admin",
            "password": "admin-pass",
        }, follow_redirects=False)
        assert response.status_code == 302
        assert "/invoices/" in response.headers["Location"]

    def test_login_with_unsafe_next(self, client, app):
        response = client.post("/login?next=http://evil.com", data={
            "username": "admin",
            "password": "admin-pass",
        }, follow_redirects=False)
        assert response.status_code == 302
        assert "evil.com" not in response.headers["Location"]

    def test_login_inactive_user(self, client, app):
        from app.extensions import db
        from app.models.models import User

        with app.app_context():
            user = db.session.execute(db.select(User).where(User.username == "admin")).scalar_one()
            user.is_active = False
            db.session.commit()

        response = client.post("/login", data={
            "username": "admin",
            "password": "admin-pass",
        }, follow_redirects=True)
        assert response.status_code == 200


# ============================================================
# makbuzlar routes — extra coverage
# ============================================================

class TestMakbuzApiExtra:
    def test_api_exchange_rate_valid_date(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get(f"/makbuzlar/api/exchange-rate?date={date.today().isoformat()}")
        assert response.status_code == 200
        assert response.get_json()["rate"] == 40.0

    def test_api_exchange_rate_invalid_date(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/makbuzlar/api/exchange-rate?date=invalid")
        assert response.status_code == 400

    def test_api_exchange_rate_no_rate_for_date(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/makbuzlar/api/exchange-rate?date=1990-01-01")
        assert response.status_code == 404


# ============================================================
# treatments routes — extra coverage
# ============================================================

class TestTreatmentsExtra:
    def test_get_add_form(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/treatments/add")
        assert response.status_code == 200

    def test_get_edit_form(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/treatments/1/edit")
        assert response.status_code == 200

    def test_add_empty_name(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.post("/treatments/add", data={
            "name": "",
            "category": "ana_islemler",
            "price_eur": "50",
        }, follow_redirects=False)
        assert response.status_code == 302

    def test_add_invalid_category(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.post("/treatments/add", data={
            "name": "Bad Cat",
            "category": "invalid_category",
            "price_eur": "50",
        }, follow_redirects=False)
        assert response.status_code == 302

    def test_add_long_description(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.post("/treatments/add", data={
            "name": "Long Desc",
            "category": "ana_islemler",
            "price_eur": "50",
            "description": "x" * 2001,
        }, follow_redirects=False)
        assert response.status_code == 302

    def test_import_no_file(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.post("/treatments/import", data={}, follow_redirects=False)
        assert response.status_code == 302

    def test_import_invalid_extension(self, client, app):
        login(client, "admin", "admin-pass")
        data = {"file": (io.BytesIO(b"test"), "test.txt")}
        response = client.post("/treatments/import", data=data, content_type="multipart/form-data", follow_redirects=False)
        assert response.status_code == 302

    def test_api_update_invalid_json(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.post("/treatments/api/update",
            data="not json",
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_api_update_missing_id(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.post("/treatments/api/update",
            data=json.dumps({"name": "Test"}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_api_update_invalid_price(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.post("/treatments/api/update",
            data=json.dumps({"id": 1, "price_eur": "not-a-number"}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_api_update_category_mapping(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.post("/treatments/api/update",
            data=json.dumps({"id": 1, "category": "ana_islemler"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["treatment"]["category"] == "ana_islemler"

    def test_import_get_form(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/treatments/import")
        assert response.status_code == 200


# ============================================================
# reports routes — extra coverage
# ============================================================

class TestReportsExtra:
    def test_reports_last_30(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/reports/?period=last_30")
        assert response.status_code == 200

    def test_reports_this_year(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/reports/?period=this_year")
        assert response.status_code == 200

    def test_reports_last_year(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/reports/?period=last_year")
        assert response.status_code == 200

    def test_reports_custom_period(self, client, app):
        login(client, "admin", "admin-pass")
        start = (date.today() - timedelta(days=30)).isoformat()
        end = date.today().isoformat()
        response = client.get(f"/reports/?period=custom&start_date={start}&end_date={end}")
        assert response.status_code == 200

    def test_reports_custom_only_start(self, client, app):
        login(client, "admin", "admin-pass")
        start = (date.today() - timedelta(days=10)).isoformat()
        response = client.get(f"/reports/?period=custom&start_date={start}")
        assert response.status_code == 200

    def test_reports_custom_only_end(self, client, app):
        login(client, "admin", "admin-pass")
        end = date.today().isoformat()
        response = client.get(f"/reports/?period=custom&end_date={end}")
        assert response.status_code == 200

    def test_reports_custom_dates_swapped(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/reports/?period=custom&start_date=2026-12-31&end_date=2026-01-01")
        assert response.status_code == 200


# ============================================================
# models — extra coverage
# ============================================================

class TestModelsExtra:
    def test_money_none(self):
        from app.models.models import money
        assert money(None) == Decimal("0.00")

    def test_money_value(self):
        from app.models.models import money
        assert money(100) == Decimal("100.00")


    def test_party_repr(self, client, app):
        from app.extensions import db
        from app.models.models import Party
        with app.app_context():
            party = db.session.execute(db.select(Party).limit(1)).scalar_one()
            r = repr(party)
            assert "Party" in r

    def test_party_full_name(self, client, app):
        from app.extensions import db
        from app.models.models import Party, PartyType
        with app.app_context():
            party = db.session.execute(
                db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
            ).scalar_one()
            assert party.display_name == party.name

    def test_treatment_repr(self, client, app):
        from app.extensions import db
        from app.models.models import Treatment
        with app.app_context():
            t = db.session.execute(db.select(Treatment).limit(1)).scalar_one()
            assert "Treatment" in repr(t)

    def test_invoice_repr(self, client, app):
        from app.extensions import db
        from app.models.models import Party, PartyType
        with app.app_context():
            party = db.session.execute(db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)).scalar_one()
            inv = _make_invoice(
                session=db.session, party_id=party.id,
                items=[{"item_type": "service", "description": "Repr Test", "quantity": 1, "unit_price_eur": 100}],
                invoice_date=date.today(),
            )
            assert "Invoice" in repr(inv)

    def test_invoice_item_repr(self, client, app):
        from app.extensions import db
        from app.models.models import Party, PartyType
        with app.app_context():
            party = db.session.execute(db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)).scalar_one()
            inv = _make_invoice(
                session=db.session, party_id=party.id,
                items=[{"item_type": "service", "description": "Item Repr", "quantity": 2, "unit_price_eur": 50}],
                invoice_date=date.today(),
            )
            item = inv.items[0]
            assert "InvoiceItem" in repr(item)

    def test_settings_repr(self, client, app):
        from app.extensions import db
        from app.models.models import Settings
        with app.app_context():
            s = db.session.execute(db.select(Settings).limit(1)).scalar_one()
            assert "Settings" in repr(s)

    def test_exchange_rate_repr(self, client, app):
        from app.extensions import db
        from app.models.models import ExchangeRate
        with app.app_context():
            er = db.session.execute(db.select(ExchangeRate).limit(1)).scalar_one()
            assert "ExchangeRate" in repr(er)

    def test_whatsapp_session_repr(self, client, app):
        from app.extensions import db
        from app.models.models import WhatsAppSession
        with app.app_context():
            ws = WhatsAppSession(session_id="repr-test", status="disconnected")
            db.session.add(ws)
            db.session.commit()
            assert "WhatsAppSession" in repr(ws)

    def test_login_attempt_repr(self, client, app):
        from app.models.models import LoginAttempt
        with app.app_context():
            la = LoginAttempt(ip_address="127.0.0.1", username="test", is_successful=True)
            assert "LoginAttempt" in repr(la)

    def test_user_repr(self, client, app):
        from app.extensions import db
        from app.models.models import User
        with app.app_context():
            u = db.session.execute(db.select(User).limit(1)).scalar_one()
            assert "User" in repr(u)

    def test_patient_treatment_repr(self, client, app):
        from app.extensions import db
        from app.models.models import PatientTreatment
        with app.app_context():
            pt = db.session.execute(db.select(PatientTreatment).limit(1)).scalar_one()
            assert "PatientTreatment" in repr(pt)

    def test_invoice_category_mixed(self, client, app):
        from app.extensions import db
        from app.models.models import Party, PartyType
        with app.app_context():
            party = db.session.execute(db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)).scalar_one()
            inv = _make_invoice(
                session=db.session, party_id=party.id,
                items=[
                    {"item_type": "service", "description": "Svc", "quantity": 1, "unit_price_eur": 100},
                    {"item_type": "product", "description": "Prod", "quantity": 1, "unit_price_eur": 50},
                ],
                invoice_date=date.today(),
            )
            _ = inv.category_keys
            _ = inv.category_key
            _ = inv.category_label

    def test_invoice_item_no_discount(self, client, app):
        from app.extensions import db
        from app.models.models import InvoiceItem
        with app.app_context():
            items = db.session.execute(db.select(InvoiceItem)).scalars().all()
            for item in items:
                _ = item.line_total_eur
                _ = item.line_total_try
                _ = item.vat_amount_eur
                _ = item.vat_amount_try

    def test_invoice_item_with_amount_discount(self, client, app):
        from app.extensions import db
        from app.models.models import InvoiceItem
        with app.app_context():
            items = db.session.execute(db.select(InvoiceItem).where(InvoiceItem.discount_type == "amount")).scalars().all()
            for item in items:
                _ = item.line_total_eur
                _ = item.line_total_try

    def test_patient_treatment_effective_price(self, client, app):
        from app.extensions import db
        from app.models.models import PatientTreatment
        with app.app_context():
            pt = db.session.execute(db.select(PatientTreatment).limit(1)).scalar_one()
            _ = pt.effective_price_eur


# ============================================================
# invoice_service — extra coverage
# ============================================================

class TestPdfServiceExtra:
    def test_pdf_with_due_date(self, client, app):
        from app.extensions import db
        from app.models.models import Party, PartyType
        from app.services.pdf_service import generate_invoice_pdf
        with app.app_context():
            party = db.session.execute(db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)).scalar_one()
            inv = _make_invoice(
                session=db.session, party_id=party.id,
                items=[{"item_type": "service", "description": "PDF Test", "quantity": 1, "unit_price_eur": 100}],
                invoice_date=date.today(),
            )
            inv.due_date = date.today() + timedelta(days=30)
            db.session.flush()
            pdf = generate_invoice_pdf(inv)
            assert len(pdf) > 0
            assert pdf[:4] == b"%PDF"


# ============================================================
# app/__init__.py — extra coverage
# ============================================================

class TestAppInitExtra:
    def test_trust_proxy(self):
        from app import create_app

        class TrustProxyConfig:
            TESTING = True
            SECRET_KEY = "test-trust-proxy"
            SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            WTF_CSRF_ENABLED = False
            TRUST_PROXY = True
            ENCRYPTION_KEY = "test-encryption-key-1234567890"
            DEBUG = False

        app = create_app(TrustProxyConfig)
        assert app.wsgi_app is not None

    def test_context_processor(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/")
        assert response.status_code == 200

    def test_purge_audit_logs_cli(self, client, app):
        from app.extensions import db
        from app.models.models import AuditLog
        from datetime import timedelta

        with app.app_context():
            old_log = AuditLog(
                occurred_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=4000),
                action="test",
                entity_type="test",
            )
            db.session.add(old_log)
            db.session.commit()

            count_before = db.session.execute(db.select(db.func.count(AuditLog.id))).scalar()
            assert count_before >= 1
