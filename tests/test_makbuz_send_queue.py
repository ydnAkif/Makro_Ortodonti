"""Tests for the WhatsApp makbuz send queue and the WhatsApp page makbuz panel.

WhatsApp/Neonize and PDF generation are always mocked.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from conftest import login

from app.extensions import db
from app.models.models import Makbuz, MakbuzSendLog, Party, PartyType, WorkOrder, money
from app.services.makbuz_send_queue import MakbuzSendQueue, send_makbuz_via_whatsapp
from app.services.whatsapp_service import WhatsAppService


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _seed_doctor_with_makbuz(app, name="Dr. Kuyruk", phone="+905551110001", status="draft"):
    with app.app_context():
        party = Party(party_type=PartyType.DENTIST, name=name, phone=phone)
        db.session.add(party)
        db.session.flush()
        db.session.add(WorkOrder(
            party_id=party.id, work_date=date(2026, 6, 12), apparatus_type="Nance",
            patient_name="Hasta", apparatus_price=Decimal("1000"),
            extra_price=Decimal("0"), total_price=Decimal("1000"),
        ))
        makbuz = Makbuz(
            party_id=party.id, year=2026, month=6, work_order_count=1,
            subtotal=money(Decimal("1000")), vat_applied=False,
            vat_rate=Decimal("0"), status=status,
            generated_at=datetime.now().astimezone(),
        )
        makbuz.recalculate_totals()
        db.session.add(makbuz)
        db.session.commit()
        return party.id, makbuz.id


class TestSendMakbuzViaWhatsApp:
    def test_success_marks_makbuz_sent(self, app):
        _, makbuz_id = _seed_doctor_with_makbuz(app)
        with app.app_context():
            with patch("app.services.makbuz_pdf_service.generate_makbuz_pdf", return_value=b"%PDF"):
                with patch.object(
                    WhatsAppService, "send_makbuz_message",
                    return_value={"success": True, "message": "ok"},
                ):
                    ok, message = send_makbuz_via_whatsapp(makbuz_id)
            assert ok is True
            makbuz = db.session.get(Makbuz, makbuz_id)
            assert makbuz.status == Makbuz.STATUS_SENT
            assert makbuz.sent_at is not None

    def test_failure_keeps_draft(self, app):
        _, makbuz_id = _seed_doctor_with_makbuz(app)
        with app.app_context():
            with patch("app.services.makbuz_pdf_service.generate_makbuz_pdf", return_value=b"%PDF"):
                with patch.object(
                    WhatsAppService, "send_makbuz_message",
                    return_value={"success": False, "message": "WhatsApp bağlı değil."},
                ):
                    ok, _ = send_makbuz_via_whatsapp(makbuz_id)
            assert ok is False
            assert db.session.get(Makbuz, makbuz_id).status == Makbuz.STATUS_DRAFT

    def test_missing_makbuz(self, app):
        with app.app_context():
            ok, message = send_makbuz_via_whatsapp(999999)
        assert ok is False
        assert "bulunamadı" in message


class TestQueue:
    def test_rejects_when_not_connected(self, app):
        _, makbuz_id = _seed_doctor_with_makbuz(app)
        with app.app_context():
            started, message = MakbuzSendQueue.start_batch([makbuz_id])
        assert started is False
        assert "bağlı değil" in message

    def test_rejects_empty_selection(self, app):
        with app.app_context():
            started, message = MakbuzSendQueue.start_batch([])
        assert started is False

    def test_rejects_unknown_ids(self, app):
        WhatsAppService._connected = True
        with app.app_context():
            started, message = MakbuzSendQueue.start_batch([987654])
        assert started is False
        assert "bulunamadı" in message

    def test_batch_processes_all_and_tracks_progress(self, app):
        WhatsAppService._connected = True
        MakbuzSendQueue._app = app
        _, m1 = _seed_doctor_with_makbuz(app, name="Dr. Bir", phone="+905551110001")
        _, m2 = _seed_doctor_with_makbuz(app, name="Dr. İki", phone="+905551110002")

        def fake_send(makbuz_id):
            return (makbuz_id == m1), "ok" if makbuz_id == m1 else "hata"

        with app.app_context():
            with patch(
                "app.services.makbuz_send_queue.send_makbuz_via_whatsapp",
                side_effect=fake_send,
            ):
                started, message = MakbuzSendQueue.start_batch([m1, m2])
                assert started is True
                assert "2 makbuz" in message
                assert _wait_until(lambda: not MakbuzSendQueue.is_running())

        job = MakbuzSendQueue.current_job()
        assert job["total"] == 2
        assert job["done"] == 2
        assert job["sent"] == 1
        assert job["failed"] == 1
        assert job["finished_at"] is not None
        by_doctor = {item["doctor"]: item for item in job["items"]}
        assert by_doctor["Dr. Bir"]["status"] == "sent"
        assert by_doctor["Dr. İki"]["status"] == "failed"
        assert by_doctor["Dr. İki"]["message"] == "hata"

    def test_only_one_batch_at_a_time(self, app):
        WhatsAppService._connected = True
        MakbuzSendQueue._app = app
        _, m1 = _seed_doctor_with_makbuz(app, name="Dr. Uzun", phone="+905551110003")

        import threading
        release = threading.Event()

        def slow_send(makbuz_id):
            release.wait(5)
            return True, "ok"

        with app.app_context():
            with patch(
                "app.services.makbuz_send_queue.send_makbuz_via_whatsapp",
                side_effect=slow_send,
            ):
                assert MakbuzSendQueue.start_batch([m1])[0] is True
                started, message = MakbuzSendQueue.start_batch([m1])
                assert started is False
                assert "Devam eden" in message
                release.set()
                assert _wait_until(lambda: not MakbuzSendQueue.is_running())

    def test_crash_marks_remaining_failed(self, app):
        WhatsAppService._connected = True
        MakbuzSendQueue._app = app
        _, m1 = _seed_doctor_with_makbuz(app, name="Dr. Kaza", phone="+905551110004")

        with app.app_context():
            with patch(
                "app.services.makbuz_send_queue.send_makbuz_via_whatsapp",
                side_effect=RuntimeError("beklenmedik"),
            ):
                assert MakbuzSendQueue.start_batch([m1])[0] is True
                assert _wait_until(lambda: not MakbuzSendQueue.is_running())

        job = MakbuzSendQueue.current_job()
        assert job["failed"] == 1
        assert job["items"][0]["status"] == "failed"

    def test_clear_finished(self, app):
        MakbuzSendQueue._job = {"running": False, "items": []}
        MakbuzSendQueue.clear_finished()
        assert MakbuzSendQueue.current_job() is None


class TestSendHistory:
    def test_batch_persists_log_rows(self, app):
        WhatsAppService._connected = True
        MakbuzSendQueue._app = app
        _, m1 = _seed_doctor_with_makbuz(app, name="Dr. Log Bir", phone="+905551110011")
        _, m2 = _seed_doctor_with_makbuz(app, name="Dr. Log İki", phone="+905551110012")

        def fake_send(makbuz_id):
            return (makbuz_id == m1), "ok" if makbuz_id == m1 else "telefon kapalı"

        with app.app_context():
            with patch(
                "app.services.makbuz_send_queue.send_makbuz_via_whatsapp",
                side_effect=fake_send,
            ):
                MakbuzSendQueue.start_batch([m1, m2])
                assert _wait_until(lambda: not MakbuzSendQueue.is_running())

        job = MakbuzSendQueue.current_job()
        with app.app_context():
            logs = db.session.execute(
                db.select(MakbuzSendLog).order_by(MakbuzSendLog.id)
            ).scalars().all()
            assert len(logs) == 2
            by_doctor = {log.doctor_name: log for log in logs}
            ok_log = by_doctor["Dr. Log Bir"]
            fail_log = by_doctor["Dr. Log İki"]
            assert ok_log.success is True
            assert fail_log.success is False
            assert fail_log.message == "telefon kapalı"
            assert ok_log.batch_id == job["id"]
            assert ok_log.triggered_by == MakbuzSendLog.TRIGGER_MANUAL
            assert ok_log.year == 2026 and ok_log.month == 6
            assert ok_log.phone == "+905551110011"

    def test_crash_leftovers_are_logged(self, app):
        WhatsAppService._connected = True
        MakbuzSendQueue._app = app
        _, m1 = _seed_doctor_with_makbuz(app, name="Dr. Log Kaza", phone="+905551110013")

        with app.app_context():
            with patch(
                "app.services.makbuz_send_queue.send_makbuz_via_whatsapp",
                side_effect=RuntimeError("çöktü"),
            ):
                MakbuzSendQueue.start_batch([m1])
                assert _wait_until(lambda: not MakbuzSendQueue.is_running())

        with app.app_context():
            logs = db.session.execute(db.select(MakbuzSendLog)).scalars().all()
            assert len(logs) == 1
            assert logs[0].success is False

    def test_history_rendered_on_page(self, client, app):
        login(client, "admin", "admin-pass")
        with app.app_context():
            db.session.add(MakbuzSendLog(
                batch_id="abc", doctor_name="Dr. Geçmiş", phone="+905551110014",
                year=2026, month=6, success=True, triggered_by="scheduler",
            ))
            db.session.commit()
        response = client.get("/whatsapp/")
        assert "Gönderim Geçmişi".encode() in response.data
        assert "Dr. Geçmiş".encode() in response.data
        assert b"Otomatik" in response.data


class TestAutoSendScheduler:
    def _fix_today(self, sched, day):
        from datetime import date as real_date

        class FixedDate(real_date):
            @classmethod
            def today(cls):
                return real_date(2026, 7, day)

        original = sched.date
        sched.date = FixedDate
        return original

    def _enable_auto_send(self, app):
        from app.models.models import Settings
        from app.services.scheduler_service import AUTO_SEND_TOGGLE_KEY

        with app.app_context():
            db.session.add(Settings(key=AUTO_SEND_TOGGLE_KEY, value="true"))
            db.session.commit()

    def test_scheduler_registers_auto_send_for_first_day_at_0930(self, app):
        import app.services.scheduler_service as sched

        original_scheduler = sched._scheduler
        original_testing = app.testing
        original_debug = app.debug
        fake_scheduler = MagicMock()
        try:
            sched._scheduler = None
            app.testing = False
            app.debug = False
            with patch.object(sched, "BackgroundScheduler", return_value=fake_scheduler):
                sched.init_scheduler(app)

            auto_send_call = next(
                call for call in fake_scheduler.add_job.call_args_list
                if call.kwargs["id"] == "makbuz_monthly_auto_send"
            )
            assert auto_send_call.kwargs["day"] == 1
            assert auto_send_call.kwargs["hour"] == 9
            assert auto_send_call.kwargs["minute"] == 30
        finally:
            sched._scheduler = original_scheduler
            app.testing = original_testing
            app.debug = original_debug

    def test_sends_previous_month_drafts(self, app):
        import app.services.scheduler_service as sched

        _, m1 = _seed_doctor_with_makbuz(app, name="Dr. Oto Bir", phone="+905551110021")
        # sent makbuz and phoneless doctor must be excluded
        _seed_doctor_with_makbuz(app, name="Dr. Oto Gönderilmiş", phone="+905551110022", status="sent")
        _seed_doctor_with_makbuz(app, name="Dr. Oto Telefonsuz", phone=None)

        self._enable_auto_send(app)
        WhatsAppService._connected = True

        original = self._fix_today(sched, day=1)
        try:
            with patch.object(
                MakbuzSendQueue, "start_batch", return_value=(True, "başladı")
            ) as mock_start:
                sched._auto_send_monthly_makbuzlar(app)
            mock_start.assert_called_once_with(
                [m1], triggered_by=MakbuzSendLog.TRIGGER_SCHEDULER
            )
        finally:
            sched.date = original

    def test_refreshes_receipt_from_only_the_target_month_work_orders(self, app):
        import app.services.scheduler_service as sched

        party_id, makbuz_id = _seed_doctor_with_makbuz(
            app, name="Dr. Dönem", phone="+905551110026"
        )
        with app.app_context():
            makbuz = db.session.get(Makbuz, makbuz_id)
            makbuz.work_order_count = 99
            makbuz.subtotal = money(Decimal("9999"))
            makbuz.recalculate_totals()
            db.session.add(WorkOrder(
                party_id=party_id, work_date=date(2026, 7, 1),
                apparatus_type="Temmuz plağı", patient_name="Başka ay",
                apparatus_price=Decimal("2500"), extra_price=Decimal("0"),
                total_price=Decimal("2500"),
            ))
            db.session.commit()

        self._enable_auto_send(app)
        WhatsAppService._connected = True
        original = self._fix_today(sched, day=1)
        try:
            with patch.object(
                MakbuzSendQueue, "start_batch", return_value=(True, "başladı")
            ) as mock_start:
                sched._auto_send_monthly_makbuzlar(app)
            mock_start.assert_called_once_with(
                [makbuz_id], triggered_by=MakbuzSendLog.TRIGGER_SCHEDULER
            )
            with app.app_context():
                refreshed = db.session.get(Makbuz, makbuz_id)
                assert refreshed.work_order_count == 1
                assert refreshed.subtotal == money(Decimal("1000"))
        finally:
            sched.date = original

    def test_runs_once_per_day(self, app):
        import app.services.scheduler_service as sched

        _seed_doctor_with_makbuz(app, name="Dr. Oto Tek", phone="+905551110023")
        self._enable_auto_send(app)
        WhatsAppService._connected = True

        original = self._fix_today(sched, day=1)
        try:
            with patch.object(
                MakbuzSendQueue, "start_batch", return_value=(True, "başladı")
            ) as mock_start:
                sched._auto_send_monthly_makbuzlar(app)
                sched._auto_send_monthly_makbuzlar(app)
            assert mock_start.call_count == 1
        finally:
            sched.date = original

    def test_skips_when_disabled(self, app):
        import app.services.scheduler_service as sched

        _seed_doctor_with_makbuz(app, name="Dr. Oto Kapalı", phone="+905551110024")
        WhatsAppService._connected = True

        original = self._fix_today(sched, day=1)
        try:
            with patch.object(MakbuzSendQueue, "start_batch") as mock_start:
                sched._auto_send_monthly_makbuzlar(app)
            assert not mock_start.called
        finally:
            sched.date = original

    def test_skips_when_not_connected(self, app):
        import app.services.scheduler_service as sched

        _seed_doctor_with_makbuz(app, name="Dr. Oto Bağsız", phone="+905551110025")
        self._enable_auto_send(app)

        original = self._fix_today(sched, day=1)
        try:
            with patch.object(MakbuzSendQueue, "start_batch") as mock_start:
                sched._auto_send_monthly_makbuzlar(app)
            assert not mock_start.called
        finally:
            sched.date = original

    def test_skips_when_not_first_of_month(self, app):
        import app.services.scheduler_service as sched

        self._enable_auto_send(app)
        WhatsAppService._connected = True

        original = self._fix_today(sched, day=15)
        try:
            with patch.object(MakbuzSendQueue, "start_batch") as mock_start:
                sched._auto_send_monthly_makbuzlar(app)
            assert not mock_start.called
        finally:
            sched.date = original

    def test_noop_when_no_drafts(self, app):
        import app.services.scheduler_service as sched

        self._enable_auto_send(app)
        WhatsAppService._connected = True

        original = self._fix_today(sched, day=1)
        try:
            with patch.object(MakbuzSendQueue, "start_batch") as mock_start:
                sched._auto_send_monthly_makbuzlar(app)
            assert not mock_start.called
        finally:
            sched.date = original


class TestAutoSendToggle:
    def test_disabled_by_default(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/whatsapp/")
        assert b"wa-auto-send" in response.data
        switch_markup = response.data.split(b'id="wa-auto-send"')[1].split(b"/>")[0]
        assert b"checked" not in switch_markup

    def test_toggle_on_and_off(self, client, app):
        from app.services.scheduler_service import auto_send_enabled

        login(client, "admin", "admin-pass")
        response = client.post(
            "/whatsapp/auto-send-toggle", data={"enabled": "on"}, follow_redirects=True
        )
        assert "açıldı".encode() in response.data
        assert b"09:30" in response.data
        assert "yalnızca önceki aya ait iş emirlerinin".encode() in response.data
        with app.app_context():
            assert auto_send_enabled() is True

        response = client.post(
            "/whatsapp/auto-send-toggle", data={}, follow_redirects=True
        )
        assert "kapatıldı".encode() in response.data
        with app.app_context():
            assert auto_send_enabled() is False


class TestWhatsAppMakbuzPanel:
    def test_doctor_phone_opens_message_form_with_recipient_selected(self, client, app):
        login(client, "admin", "admin-pass")
        party_id, _ = _seed_doctor_with_makbuz(
            app, name="Dr. Mesaj Kısayolu", phone="+905551110055"
        )

        doctor_list = client.get("/parties/").get_data(as_text=True)
        assert f"/whatsapp/?message_party_id={party_id}#message-compose" in doctor_list

        whatsapp_html = client.get(
            f"/whatsapp/?message_party_id={party_id}"
        ).get_data(as_text=True)
        disclosure = whatsapp_html.split(
            '<details class="disclosure-panel mt-3"', 1
        )[1].split(">", 1)[0]
        option = whatsapp_html.split(
            '<option value="+905551110055"', 1
        )[1].split(">", 1)[0]
        assert "open" in disclosure
        assert "selected" in option
        assert 'id="message-compose"' in whatsapp_html

    def test_index_lists_candidates_for_period(self, client, app):
        login(client, "admin", "admin-pass")
        _seed_doctor_with_makbuz(app, name="Dr. Panel", phone="+905551110005")
        response = client.get("/whatsapp/?year=2026&month=6")
        assert response.status_code == 200
        assert "Dr. Panel".encode() in response.data
        assert b"wa-select-all" in response.data
        assert "Makbuz Gönderimi".encode() in response.data

    def test_bulk_message_recipients_default_to_all_selected(self, client, app):
        login(client, "admin", "admin-pass")
        _seed_doctor_with_makbuz(
            app, name="Dr. Toplu Bir", phone="+905551110061"
        )
        _seed_doctor_with_makbuz(
            app, name="Dr. Toplu İki", phone="+905551110062"
        )

        html = client.get("/whatsapp/").get_data(as_text=True)
        bulk_section = html.split("Toplu Mesaj Gönderimi", 1)[1]
        recipient_inputs = bulk_section.split('name="message"', 1)[0]
        assert 'id="bulk-select-all"' in bulk_section
        assert 'id="bulk-select-none"' in bulk_section
        assert "Seçimi temizle" in bulk_section
        assert recipient_inputs.count('name="patient_ids"') >= 2
        for markup in recipient_inputs.split('name="patient_ids"')[1:]:
            assert "checked" in markup.split("/>", 1)[0]

    def test_index_empty_period_shows_hint(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/whatsapp/?year=2020&month=2")
        assert response.status_code == 200
        assert "oluşturulmuş makbuz bulunmuyor".encode() in response.data

    def test_index_counts_doctors_without_makbuz(self, client, app):
        login(client, "admin", "admin-pass")
        with app.app_context():
            party = Party(party_type=PartyType.DENTIST, name="Dr. Makbuzsuz", phone="+905551110006")
            db.session.add(party)
            db.session.flush()
            db.session.add(WorkOrder(
                party_id=party.id, work_date=date(2026, 5, 5), apparatus_type="Nance",
                patient_name="Hasta", apparatus_price=Decimal("500"),
                extra_price=Decimal("0"), total_price=Decimal("500"),
            ))
            db.session.commit()
        response = client.get("/whatsapp/?year=2026&month=5")
        assert "makbuzu henüz".encode() in response.data

    def test_batch_route_starts_queue(self, client, app):
        login(client, "admin", "admin-pass")
        with patch.object(
            MakbuzSendQueue, "start_batch", return_value=(True, "3 makbuz için gönderim arka planda başlatıldı.")
        ) as mock_start:
            response = client.post(
                "/whatsapp/send-makbuz-batch",
                data={"year": "2026", "month": "6", "makbuz_ids": ["1", "2", "3"]},
                follow_redirects=True,
            )
        assert response.status_code == 200
        mock_start.assert_called_once_with([1, 2, 3])
        assert "arka planda".encode() in response.data

    def test_batch_route_reports_failure(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.post(
            "/whatsapp/send-makbuz-batch",
            data={"year": "2026", "month": "6"},
            follow_redirects=True,
        )
        assert "makbuz seçilmedi".encode() in response.data

    def test_status_endpoint_includes_job(self, client, app):
        login(client, "admin", "admin-pass")
        MakbuzSendQueue._job = {
            "id": "x", "running": True, "total": 2, "done": 1, "sent": 1,
            "failed": 0, "items": [], "started_at": "", "finished_at": None,
        }
        data = client.get("/whatsapp/status").get_json()
        assert data["send_job"]["total"] == 2
        assert data["send_job"]["running"] is True


class TestStatusIndicators:
    def test_quick_state_disconnected_by_default(self, app):
        assert WhatsAppService.quick_state() == "disconnected"

    def test_quick_state_connected(self, app):
        WhatsAppService._connected = True
        assert WhatsAppService.quick_state() == "connected"

    def test_sidebar_shows_status_dot(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/whatsapp/")
        assert b"wa-status-dot" in response.data
        assert b"wa-status-disconnected" in response.data

    def test_dashboard_banner_when_disconnected(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/")
        assert b"wa-connect-banner" in response.data
        assert "WhatsApp bağlı değil".encode() in response.data

    def test_dashboard_banner_hidden_when_connected(self, client, app):
        login(client, "admin", "admin-pass")
        WhatsAppService._connected = True
        response = client.get("/")
        assert b"wa-connect-banner" not in response.data
        assert b"wa-status-connected" in response.data
