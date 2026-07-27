"""Tests for the Neonize-backed WhatsApp connection flow.

Neonize is always mocked — no real WhatsApp account or network is used.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import types
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from conftest import login

from app.extensions import db
from app.models.models import WhatsAppSession
from app.services.whatsapp_service import WhatsAppService


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


class TestStart:
    def test_start_registers_handlers_and_connects(self, app):
        mock_client = MagicMock()
        with patch.object(WhatsAppService, "get_client", return_value=mock_client):
            assert WhatsAppService.start() is True

        assert _wait_until(lambda: mock_client.connect.called)
        # Raw QR callback + Connected/PairStatus/Disconnected/LoggedOut events
        mock_client.event.qr.assert_called_once_with(WhatsAppService._on_qr)
        registered = [call.args[0].__name__ for call in mock_client.event.call_args_list]
        assert "Connected" in registered
        assert "PairStatus" in registered
        assert "Disconnected" in registered
        assert "LoggedOut" in registered

    def test_start_is_idempotent_while_thread_alive(self, app):
        mock_client = MagicMock()
        release = threading.Event()
        mock_client.connect.side_effect = lambda: release.wait(5)
        with patch.object(WhatsAppService, "get_client", return_value=mock_client):
            assert WhatsAppService.start() is True
            assert WhatsAppService.start() is True
        assert mock_client.connect.call_count <= 1 or _wait_until(
            lambda: mock_client.connect.call_count == 1
        )
        release.set()

    def test_start_refused_without_process_lock(self, app):
        with patch.object(WhatsAppService, "_acquire_process_lock", return_value=False):
            assert WhatsAppService.start() is False

    def test_process_lock_reentrant_in_same_process(self, app):
        assert WhatsAppService._acquire_process_lock() is True
        assert WhatsAppService._acquire_process_lock() is True

    def test_process_lock_falls_back_when_fcntl_is_unavailable(self, app, monkeypatch):
        fake_fcntl = types.SimpleNamespace(LOCK_EX=0, LOCK_NB=0)

        def fake_flock(handle, flags):
            return None

        fake_fcntl.flock = fake_flock
        monkeypatch.setitem(sys.modules, "fcntl", fake_fcntl)
        monkeypatch.setattr("app.services.whatsapp_service.fcntl", fake_fcntl, raising=False)
        monkeypatch.setattr(WhatsAppService, "_process_lock_handle", None)

        assert WhatsAppService._acquire_process_lock() is True


class TestEventHandlers:
    def test_on_qr_stores_payload_and_db_row(self, app):
        WhatsAppService._app = app
        WhatsAppService._on_qr(MagicMock(), b"2@qr-payload-data")

        assert WhatsAppService._qr_code == "2@qr-payload-data"
        with app.app_context():
            row = db.session.execute(
                db.select(WhatsAppSession).where(WhatsAppSession.session_id == "default")
            ).scalar_one()
            assert row.status == WhatsAppSession.STATUS_CONNECTING
            assert row.qr_code == "2@qr-payload-data"

    def test_on_connected_marks_session_connected(self, app):
        WhatsAppService._app = app
        WhatsAppService._qr_code = "2@old-qr"
        client = MagicMock()
        client.me.JID.User = "905551112233"

        WhatsAppService._on_connected(client, None)

        assert WhatsAppService._connected is True
        assert WhatsAppService._qr_code is None
        with app.app_context():
            row = db.session.execute(
                db.select(WhatsAppSession).where(WhatsAppSession.session_id == "default")
            ).scalar_one()
            assert row.status == WhatsAppSession.STATUS_CONNECTED
            assert row.connected_at is not None
            assert row.qr_code is None
            assert row.phone_number == "905551112233"

    def test_on_logged_out_resets_session(self, app):
        WhatsAppService._app = app
        WhatsAppService._connected = True
        WhatsAppService._on_logged_out(MagicMock(), None)

        assert WhatsAppService._connected is False
        with app.app_context():
            row = db.session.execute(
                db.select(WhatsAppSession).where(WhatsAppSession.session_id == "default")
            ).scalar_one()
            assert row.status == WhatsAppSession.STATUS_DISCONNECTED
            assert row.disconnected_at is not None

    def test_on_disconnected_blocks_sends(self, app):
        WhatsAppService._connected = True
        WhatsAppService._on_disconnected(MagicMock(), None)
        assert WhatsAppService._connected is False
        result = WhatsAppService.send_message("+905551112233", "test")
        assert result["success"] is False


class TestStatus:
    def test_status_includes_qr_image_data_uri(self, app):
        WhatsAppService._qr_code = "2@qr-payload"
        with app.app_context():
            status = WhatsAppService.get_status()
        assert status["qr"] == "2@qr-payload"
        assert status["qr_image"].startswith("data:image/png;base64,")
        assert status["connected"] is False

    def test_status_endpoint_returns_qr_json(self, client, app):
        login(client, "admin", "admin-pass")
        WhatsAppService._qr_code = "2@qr-payload"
        response = client.get("/whatsapp/status")
        assert response.status_code == 200
        data = response.get_json()
        assert data["qr"] == "2@qr-payload"
        assert data["qr_image"].startswith("data:image/png;base64,")
        assert data["connected"] is False

    def test_status_endpoint_when_connected(self, client, app):
        login(client, "admin", "admin-pass")
        WhatsAppService._app = app
        client_mock = MagicMock()
        client_mock.me.JID.User = "905551112233"
        WhatsAppService._on_connected(client_mock, None)

        response = client.get("/whatsapp/status")
        data = response.get_json()
        assert data["connected"] is True
        assert data["status"] == "connected"
        assert data["qr"] is None
        assert data["phone_number"] == "905551112233"
        assert data["connected_at"]  # isoformat string

    def test_index_page_renders_qr_polling(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/whatsapp/")
        assert response.status_code == 200
        assert b"wa-qr-area" in response.data
        assert b"/whatsapp/status" in response.data


class TestAutoReconnect:
    def test_init_app_starts_when_session_db_exists(self, app):
        with open(WhatsAppService.session_db_path(), "wb") as f:
            f.write(b"")
        app.testing = False
        old_debug = app.debug
        app.debug = False  # debug without WERKZEUG_RUN_MAIN means reloader parent
        try:
            with patch.object(WhatsAppService, "start") as mock_start:
                WhatsAppService.init_app(app)
                assert _wait_until(lambda: mock_start.called)
        finally:
            app.testing = True
            app.debug = old_debug

    def test_init_app_skips_without_session_db(self, app):
        assert not os.path.exists(WhatsAppService.session_db_path())
        app.testing = False
        try:
            with patch.object(WhatsAppService, "start") as mock_start:
                WhatsAppService.init_app(app)
                time.sleep(0.2)
                assert not mock_start.called
        finally:
            app.testing = True

    def test_init_app_skips_in_testing_mode(self, app):
        with open(WhatsAppService.session_db_path(), "wb") as f:
            f.write(b"")
        with patch.object(WhatsAppService, "start") as mock_start:
            WhatsAppService.init_app(app)
            time.sleep(0.2)
            assert not mock_start.called


class TestConnectFlow:
    def test_connect_without_phone_starts_qr_flow(self, app):
        with app.app_context():
            with patch.object(WhatsAppService, "start", return_value=True) as mock_start:
                result = WhatsAppService.connect()
        assert result["success"] is True
        assert "QR" in result["message"]
        mock_start.assert_called_once()

    def test_connect_with_phone_requests_pair_code(self, app):
        mock_client = MagicMock()
        mock_client.PairPhone.return_value = "ABCD-1234"
        WhatsAppService._client = mock_client
        WhatsAppService._qr_code = "2@qr"  # socket already in pairing mode
        WhatsAppService._app = app

        with app.app_context():
            with patch.object(WhatsAppService, "start", return_value=True):
                result = WhatsAppService.connect(phone_number="+90 555 123 45 67")
        assert result["success"] is True
        assert _wait_until(lambda: WhatsAppService._pair_code == "ABCD-1234")
        mock_client.PairPhone.assert_called_once_with(
            "905551234567", show_push_notification=True
        )
        with app.app_context():
            status = WhatsAppService.get_status()
            assert status["pair_code"] == "ABCD-1234"


class TestErrorPaths:
    def test_init_app_skips_reloader_parent(self, app):
        with open(WhatsAppService.session_db_path(), "wb") as f:
            f.write(b"")
        app.testing = False
        old_debug = app.debug
        app.debug = True  # debug without WERKZEUG_RUN_MAIN == reloader parent
        try:
            with patch.object(WhatsAppService, "start") as mock_start:
                WhatsAppService.init_app(app)
                time.sleep(0.2)
                assert not mock_start.called
        finally:
            app.testing = True
            app.debug = old_debug

    def test_init_app_respects_auto_connect_config(self, app):
        with open(WhatsAppService.session_db_path(), "wb") as f:
            f.write(b"")
        app.testing = False
        app.config["WHATSAPP_AUTO_CONNECT"] = False
        try:
            with patch.object(WhatsAppService, "start") as mock_start:
                WhatsAppService.init_app(app)
                time.sleep(0.2)
                assert not mock_start.called
        finally:
            app.testing = True
            app.config.pop("WHATSAPP_AUTO_CONNECT")

    def test_process_lock_flock_failure(self, app, monkeypatch):
        fake_fcntl = types.ModuleType("fcntl")
        fake_fcntl.LOCK_EX = 0
        fake_fcntl.LOCK_NB = 0

        def fake_flock(handle, flags):
            raise OSError("locked by other worker")

        fake_fcntl.flock = fake_flock
        monkeypatch.setitem(sys.modules, "fcntl", fake_fcntl)
        monkeypatch.setattr("app.services.whatsapp_service.fcntl", fake_fcntl, raising=False)
        monkeypatch.setattr(WhatsAppService, "_process_lock_handle", None)

        assert WhatsAppService._acquire_process_lock() is False
        assert WhatsAppService._process_lock_handle is None

    def test_run_survives_connect_exception(self, app):
        mock_client = MagicMock()
        mock_client.connect.side_effect = RuntimeError("socket error")
        WhatsAppService._app = app
        with patch.object(WhatsAppService, "get_client", return_value=mock_client):
            assert WhatsAppService.start() is True
        assert _wait_until(lambda: WhatsAppService._client is None)
        assert WhatsAppService._connected is False

    def test_on_pair_status_stores_phone(self, app):
        WhatsAppService._app = app
        WhatsAppService._qr_code = "2@qr"
        event = MagicMock()
        event.ID.User = "905551112233"
        WhatsAppService._on_pair_status(MagicMock(), event)

        assert WhatsAppService._qr_code is None
        with app.app_context():
            row = db.session.execute(
                db.select(WhatsAppSession).where(WhatsAppSession.session_id == "default")
            ).scalar_one()
            assert row.phone_number == "905551112233"

    def test_on_pair_status_tolerates_bad_event(self, app):
        WhatsAppService._app = app
        event = MagicMock()
        type(event).ID = property(lambda self: (_ for _ in ()).throw(ValueError()))
        WhatsAppService._on_pair_status(MagicMock(), event)  # must not raise

    def test_on_connected_without_me_info(self, app):
        WhatsAppService._app = app
        client = MagicMock()
        client.me = None
        WhatsAppService._on_connected(client, None)
        assert WhatsAppService._connected is True
        with app.app_context():
            row = db.session.execute(
                db.select(WhatsAppSession).where(WhatsAppSession.session_id == "default")
            ).scalar_one()
            assert row.status == WhatsAppSession.STATUS_CONNECTED
            assert row.phone_number is None

    def test_on_connected_me_access_error(self, app):
        WhatsAppService._app = app
        client = MagicMock()
        type(client.me).JID = property(lambda self: (_ for _ in ()).throw(ValueError()))
        WhatsAppService._on_connected(client, None)
        assert WhatsAppService._connected is True

    def test_update_session_row_commit_failure_is_logged(self, app):
        WhatsAppService._app = app
        with patch("app.services.whatsapp_service.db.session.commit", side_effect=RuntimeError("db gone")):
            WhatsAppService._update_session_row(status="connecting")  # must not raise

    def test_update_session_row_without_app_context(self):
        WhatsAppService._app = None
        WhatsAppService._update_session_row(status="connecting")  # must not raise

    def test_request_pair_code_without_client(self, app):
        WhatsAppService._client = None
        WhatsAppService._qr_code = "2@qr"
        WhatsAppService._request_pair_code("905551234567")
        assert WhatsAppService._pair_code is None

    def test_request_pair_code_skipped_when_already_connected(self, app):
        mock_client = MagicMock()
        WhatsAppService._client = mock_client
        WhatsAppService._connected = True
        WhatsAppService._request_pair_code("905551234567")
        assert not mock_client.PairPhone.called

    def test_request_pair_code_failure_logged(self, app):
        mock_client = MagicMock()
        mock_client.PairPhone.side_effect = RuntimeError("pair refused")
        WhatsAppService._client = mock_client
        WhatsAppService._qr_code = "2@qr"
        WhatsAppService._app = app
        WhatsAppService._request_pair_code("905551234567")
        assert WhatsAppService._pair_code is None

    def test_disconnect_survives_stop_failure(self, app):
        mock_client = MagicMock()
        mock_client.stop.side_effect = RuntimeError("already stopped")
        WhatsAppService._client = mock_client
        WhatsAppService._app = app
        with app.app_context():
            result = WhatsAppService.disconnect()
        assert result["success"] is True

    def test_disconnect_reports_unexpected_error(self, app):
        with patch.object(WhatsAppService, "_update_session_row", side_effect=RuntimeError("boom")):
            result = WhatsAppService.disconnect()
        assert result["success"] is False

    def test_get_status_connecting_while_thread_alive(self, app):
        release = threading.Event()
        thread = threading.Thread(target=release.wait, args=(5,), daemon=True)
        thread.start()
        WhatsAppService._thread = thread
        try:
            with app.app_context():
                status = WhatsAppService.get_status()
            assert status["connecting"] is True
            assert status["status"] == "connecting"
        finally:
            release.set()

    def test_get_status_qr_image_generation_failure(self, app):
        WhatsAppService._qr_code = "2@qr"
        with patch("segno.make_qr", side_effect=RuntimeError("no qr")):
            with app.app_context():
                status = WhatsAppService.get_status()
        assert status["qr"] == "2@qr"
        assert status["qr_image"] is None

    def test_send_document_not_connected(self, app):
        result = WhatsAppService.send_document("+905551112233", b"%PDF", "a.pdf")
        assert result["success"] is False

    def test_send_document_client_none(self, app):
        WhatsAppService._connected = True
        with patch.object(WhatsAppService, "get_client", return_value=None):
            result = WhatsAppService.send_document("+905551112233", b"%PDF", "a.pdf")
        assert result["success"] is False

    def test_send_document_error(self, app):
        mock_client = MagicMock()
        mock_client.send_document.side_effect = RuntimeError("upload failed")
        WhatsAppService._client = mock_client
        WhatsAppService._connected = True
        result = WhatsAppService.send_document("+905551112233", b"%PDF", "a.pdf")
        assert result["success"] is False


class TestSending:
    def test_send_message_serialized_and_uses_jid(self, app):
        mock_client = MagicMock()
        WhatsAppService._client = mock_client
        WhatsAppService._connected = True

        result = WhatsAppService.send_message("+90 555-111-22-33", "Merhaba")
        assert result["success"] is True
        jid = mock_client.send_message.call_args.args[0]
        assert jid.User == "905551112233"

    def test_send_makbuz_message_sends_text_and_pdf(self, app):
        mock_client = MagicMock()
        WhatsAppService._client = mock_client
        WhatsAppService._connected = True

        makbuz = MagicMock()
        makbuz.party.name = "Dr. Test"
        makbuz.party.phone = "+905551112233"
        makbuz.party.id = 7
        makbuz.party.previous_balance = Decimal("0.00")
        makbuz.month = 6
        makbuz.year = 2026
        makbuz.work_order_count = 3
        makbuz.subtotal = 1000.0
        makbuz.vat_applied = False
        makbuz.grand_total = 1000.0

        result = WhatsAppService.send_makbuz_message(makbuz, b"%PDF-fake")
        assert result["success"] is True
        mock_client.send_message.assert_called_once()
        mock_client.send_document.assert_called_once()
        doc_kwargs = mock_client.send_document.call_args.kwargs
        assert doc_kwargs["filename"] == "makbuz_2026_06_7.pdf"
        assert doc_kwargs["mimetype"] == "application/pdf"

    def _makbuz_mock(self, vat_applied=False):
        makbuz = MagicMock()
        makbuz.party.name = "Dr. Test"
        makbuz.party.phone = "+905551112233"
        makbuz.party.id = 7
        makbuz.party.previous_balance = Decimal("0.00")
        makbuz.month = 6
        makbuz.year = 2026
        makbuz.work_order_count = 3
        makbuz.subtotal = 1000.0
        makbuz.vat_applied = vat_applied
        makbuz.vat_rate = 20.0
        makbuz.vat_amount = 200.0
        makbuz.grand_total = 1200.0 if vat_applied else 1000.0
        return makbuz

    def test_send_makbuz_message_with_vat_line(self, app):
        mock_client = MagicMock()
        WhatsAppService._client = mock_client
        WhatsAppService._connected = True

        result = WhatsAppService.send_makbuz_message(self._makbuz_mock(vat_applied=True), b"%PDF")
        assert result["success"] is True
        text = mock_client.send_message.call_args.args[1]
        assert "KDV" in text

    def test_send_makbuz_message_stops_when_text_fails(self, app):
        mock_client = MagicMock()
        mock_client.send_message.side_effect = RuntimeError("offline")
        WhatsAppService._client = mock_client
        WhatsAppService._connected = True

        result = WhatsAppService.send_makbuz_message(self._makbuz_mock(), b"%PDF")
        assert result["success"] is False
        assert not mock_client.send_document.called

    def test_send_invoice_message_legacy_patient_phone(self, app):
        mock_client = MagicMock()
        WhatsAppService._client = mock_client
        WhatsAppService._connected = True

        invoice = MagicMock()
        invoice.party = None
        invoice.patient.phone = "+905551112233"
        invoice.patient.full_name = "Ayşe Yılmaz"
        invoice.invoice_date = date(2026, 7, 1)
        invoice.invoice_number = "MKR-1"
        invoice.total_try = 4000.0
        invoice.total_eur = 100.0
        invoice.status = "pending"
        invoice.due_date = date(2026, 7, 15)

        result = WhatsAppService.send_invoice_message(invoice)
        assert result["success"] is True
        text = mock_client.send_message.call_args.args[1]
        assert "Ayşe Yılmaz" in text
        assert "Son Ödeme: 15.07.2026" in text

    def test_send_reminder_success(self, app):
        mock_client = MagicMock()
        WhatsAppService._client = mock_client
        WhatsAppService._connected = True
        patient = MagicMock()
        patient.phone = "+905551112233"
        result = WhatsAppService.send_reminder(patient, "Randevu hatırlatması")
        assert result["success"] is True


class TestRoutes:
    def test_send_bulk_counts_failures(self, client, app):
        login(client, "admin", "admin-pass")
        from app.models.models import Party
        from app.services.bulk_message_queue import BulkMessageQueue

        with app.app_context():
            party_id = db.session.execute(db.select(Party.id).limit(1)).scalar_one()

        WhatsAppService._connected = True
        with patch(
            "app.services.whatsapp_service.WhatsAppService.send_message",
            return_value={"success": False, "message": "WhatsApp bağlı değil."},
        ):
            response = client.post(
                "/whatsapp/send-bulk",
                # party_id 999999 doesn't exist and is dropped before any send
                # is attempted, so only the real party contributes to the count.
                data={"message": "test", "patient_ids": [str(party_id), "999999"]},
                follow_redirects=True,
            )
        assert response.status_code == 200
        if BulkMessageQueue._thread is not None:
            BulkMessageQueue._thread.join(timeout=2)
        job = BulkMessageQueue.current_job()
        assert job is not None
        assert job["failed"] == 1
