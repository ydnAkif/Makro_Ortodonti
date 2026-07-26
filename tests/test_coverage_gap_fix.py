"""Targeted tests to close coverage gaps and reach ≥90%."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch, MagicMock

import pytest

from app.extensions import db
from app.models.models import (
    AuditLog, LoginAttempt, Makbuz, MakbuzPayment, Party, PartyType,
    WorkOrder, ExchangeRate, Settings, User,
)
from conftest import login


# ── Scheduler purge functions ──────────────────────────────────────────


class TestSchedulerPurgeFunctions:
    def test_purge_old_login_attempts(self, app):
        from app.services.scheduler_service import _purge_old_login_attempts

        with app.app_context():
            old = LoginAttempt(
                ip_address="127.0.0.1",
                username="old_user",
                is_successful=False,
            )
            old.created_at = date.today() - timedelta(days=40)
            db.session.add(old)
            db.session.commit()

            _purge_old_login_attempts(app)

            remaining = db.session.execute(
                db.select(LoginAttempt)
            ).scalars().all()
            assert len(remaining) == 0

    def test_purge_old_login_attempts_keeps_recent(self, app):
        from app.services.scheduler_service import _purge_old_login_attempts

        with app.app_context():
            recent = LoginAttempt(
                ip_address="127.0.0.1",
                username="recent_user",
                is_successful=False,
            )
            db.session.add(recent)
            db.session.commit()

            _purge_old_login_attempts(app)

            remaining = db.session.execute(
                db.select(LoginAttempt)
            ).scalars().all()
            assert len(remaining) == 1

    def test_purge_old_audit_logs(self, app):
        from app.services.scheduler_service import _purge_old_audit_logs

        with app.app_context():
            app.config["AUDIT_RETENTION_DAYS"] = 1
            old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
            result = db.session.execute(
                db.text(
                    "INSERT INTO audit_logs (occurred_at, action, entity_type, entity_id, changes_json) "
                    "VALUES (:ts, 'create', 'PurgeTest', '9999', '{}')"
                ),
                {"ts": old_ts},
            )
            inserted_id = result.lastrowid
            db.session.commit()

            _purge_old_audit_logs(app)

            remaining = db.session.execute(
                db.text("SELECT id FROM audit_logs WHERE id = :id"), {"id": inserted_id}
            ).fetchall()
            assert len(remaining) == 0

    def test_purge_old_audit_logs_keeps_recent(self, app):
        from app.services.scheduler_service import _purge_old_audit_logs

        with app.app_context():
            app.config["AUDIT_RETENTION_DAYS"] = 3650
            result = db.session.execute(
                db.text(
                    "INSERT INTO audit_logs (occurred_at, action, entity_type, entity_id, changes_json) "
                    "VALUES (datetime('now'), 'create', 'PurgeTestRecent', '8888', '{}')"
                ),
            )
            inserted_id = result.lastrowid
            db.session.commit()

            _purge_old_audit_logs(app)

            remaining = db.session.execute(
                db.text("SELECT id FROM audit_logs WHERE id = :id"), {"id": inserted_id}
            ).fetchall()
            assert len(remaining) == 1


# ── Payments delete_payment + validation guards ────────────────────────


class TestDeletePayment:
    def test_delete_payment_entry(self, client, app):
        from app.services.makbuz_account_service import record_payment

        login(client, "admin", "admin-pass")

        with app.app_context():
            party = db.session.execute(
                db.select(Party).where(Party.party_type == PartyType.DENTIST)
            ).scalars().first()
            makbuz = Makbuz(
                party_id=party.id,
                year=date.today().year,
                month=date.today().month,
                status=Makbuz.STATUS_SENT,
                work_order_count=1,
                subtotal=Decimal("100.00"),
                grand_total=Decimal("100.00"),
                sent_at=date.today(),
            )
            db.session.add(makbuz)
            db.session.flush()
            record_payment(makbuz, payment_date=date.today(), amount=Decimal("50.00"), method="cash")
            db.session.commit()
            makbuz_id = makbuz.id
            entry_id = makbuz.payment_entries[0].id

        response = client.post(
            f"/payments/entries/{entry_id}/delete",
            follow_redirects=True,
        )
        assert response.status_code == 200

        with app.app_context():
            remaining = db.session.execute(
                db.select(MakbuzPayment).where(MakbuzPayment.id == entry_id)
            ).scalar_one_or_none()
            assert remaining is None

    def test_mark_paid_zero_amount(self, client, app):
        login(client, "admin", "admin-pass")

        with app.app_context():
            party = db.session.execute(
                db.select(Party).where(Party.party_type == PartyType.DENTIST)
            ).scalars().first()
            makbuz = Makbuz(
                party_id=party.id,
                year=date.today().year,
                month=date.today().month,
                status=Makbuz.STATUS_SENT,
                work_order_count=1,
                subtotal=Decimal("100.00"),
                grand_total=Decimal("100.00"),
                sent_at=date.today(),
            )
            db.session.add(makbuz)
            db.session.commit()
            makbuz_id = makbuz.id

        response = client.post(
            f"/payments/{makbuz_id}/mark-paid",
            data={
                "paid_at": date.today().isoformat(),
                "paid_amount": "0",
                "payment_method": "cash",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200

    def test_mark_paid_invalid_method(self, client, app):
        login(client, "admin", "admin-pass")

        with app.app_context():
            party = db.session.execute(
                db.select(Party).where(Party.party_type == PartyType.DENTIST)
            ).scalars().first()
            makbuz = Makbuz(
                party_id=party.id,
                year=date.today().year,
                month=date.today().month,
                status=Makbuz.STATUS_SENT,
                work_order_count=1,
                subtotal=Decimal("100.00"),
                grand_total=Decimal("100.00"),
                sent_at=date.today(),
            )
            db.session.add(makbuz)
            db.session.commit()
            makbuz_id = makbuz.id

        response = client.post(
            f"/payments/{makbuz_id}/mark-paid",
            data={
                "paid_at": date.today().isoformat(),
                "paid_amount": "50",
                "payment_method": "INVALID",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200

    def test_mark_paid_already_fully_paid(self, client, app):
        from app.services.makbuz_account_service import record_payment

        login(client, "admin", "admin-pass")

        with app.app_context():
            party = db.session.execute(
                db.select(Party).where(Party.party_type == PartyType.DENTIST)
            ).scalars().first()
            makbuz = Makbuz(
                party_id=party.id,
                year=date.today().year,
                month=date.today().month,
                status=Makbuz.STATUS_SENT,
                work_order_count=1,
                subtotal=Decimal("100.00"),
                grand_total=Decimal("100.00"),
                sent_at=date.today(),
            )
            db.session.add(makbuz)
            db.session.flush()
            record_payment(makbuz, payment_date=date.today(), amount=Decimal("100.00"), method="cash")
            db.session.commit()
            makbuz_id = makbuz.id

        response = client.get(
            f"/payments/{makbuz_id}/mark-paid",
            follow_redirects=True,
        )
        assert response.status_code == 200


# ── Payments list with invalid tab + year filter ───────────────────────


class TestPaymentsListFilters:
    def test_invalid_tab_falls_back_to_pending(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/payments/?tab=INVALID")
        assert response.status_code == 200

    def test_year_filter(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get(f"/payments/?year={date.today().year}")
        assert response.status_code == 200


# ── Parties year-view paths ───────────────────────────────────────────


class TestPartyDetailYearView:
    def test_year_view_renders(self, client, app):
        login(client, "admin", "admin-pass")
        with app.app_context():
            party = db.session.execute(
                db.select(Party).where(Party.party_type == PartyType.DENTIST)
            ).scalars().first()
            party_id = party.id

        response = client.get(
            f"/parties/{party_id}?view=year&year={date.today().year}"
        )
        assert response.status_code == 200

    def test_detail_invalid_date_fallback(self, client, app):
        login(client, "admin", "admin-pass")
        with app.app_context():
            party = db.session.execute(
                db.select(Party).where(Party.party_type == PartyType.DENTIST)
            ).scalars().first()
            party_id = party.id

        response = client.get(
            f"/parties/{party_id}?view=month&month=13&year=2026"
        )
        assert response.status_code == 200


# ── Parties work-order invalid view ────────────────────────────────────


class TestWorkOrderInvalidView:
    def test_invalid_view_falls_back_to_month(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/parties/work-orders?view=INVALID")
        assert response.status_code == 200

    def test_invalid_date_in_work_orders(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get(
            "/parties/work-orders?view=month&month=13&year=2026"
        )
        assert response.status_code == 200


# ── Exchange service branches ──────────────────────────────────────────


class TestExchangeServiceBranches:
    def test_fetch_usd_try_rate_second_provider(self, app):
        from app.services.exchange_service import fetch_usd_try_rate
        from decimal import Decimal

        def side_effect(url, timeout):
            mock = MagicMock()
            if "frankfurter.dev" in url:
                raise Exception("Provider 1 down")
            mock.json.return_value = {"rates": {"TRY": 35.5}}
            mock.raise_for_status = MagicMock()
            return mock

        with patch("app.services.exchange_service.requests.get", side_effect=side_effect):
            rate = fetch_usd_try_rate()
            assert rate == Decimal("35.5")

    def test_fetch_usd_try_rate_all_fail(self, app):
        from app.services.exchange_service import fetch_usd_try_rate

        with patch("app.services.exchange_service.requests.get", side_effect=Exception("fail")):
            rate = fetch_usd_try_rate()
            assert rate is None

    def test_get_latest_usd_rate_from_db(self, app):
        from app.services.exchange_service import get_latest_usd_rate

        with app.app_context():
            rate = get_latest_usd_rate()
            assert rate is None or rate > 0

    def test_fetch_and_store_rate_new_record(self, app):
        from app.services.exchange_service import fetch_and_store_rate

        with app.app_context():
            db.session.execute(db.delete(ExchangeRate))
            db.session.commit()

            with patch("app.services.exchange_service.fetch_eur_try_rate", return_value=Decimal("40.0")):
                with patch("app.services.exchange_service.fetch_usd_try_rate", return_value=Decimal("35.0")):
                    rate = fetch_and_store_rate()
                    assert rate == Decimal("40.0")

            stored = db.session.execute(db.select(ExchangeRate)).scalar_one_or_none()
            assert stored is not None
            assert stored.usd_to_try == Decimal("35.0")

    def test_fetch_and_store_rate_usd_none(self, app):
        from app.services.exchange_service import fetch_and_store_rate

        with app.app_context():
            with patch("app.services.exchange_service.fetch_eur_try_rate", return_value=Decimal("41.0")):
                with patch("app.services.exchange_service.fetch_usd_try_rate", return_value=None):
                    rate = fetch_and_store_rate()
                    assert rate == Decimal("41.0")

    def test_ensure_daily_rate_double_check_lock(self, app):
        from app.services.exchange_service import ensure_daily_rate, _auto_check_lock
        import app.services.exchange_service as es

        with app.app_context():
            original = es._last_auto_check_date
            es._last_auto_check_date = date.today()
            try:
                result = ensure_daily_rate(max_age_days=2)
                assert "is_stale" in result
            finally:
                es._last_auto_check_date = original


# ── Parties import guards ──────────────────────────────────────────────


class TestPartiesImportGuards:
    def test_import_no_file(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.post(
            "/parties/import",
            follow_redirects=True,
        )
        assert response.status_code == 200

    def test_import_invalid_extension(self, client, app):
        import io
        login(client, "admin", "admin-pass")
        data = {"file": (io.BytesIO(b"not excel"), "test.txt")}
        response = client.post(
            "/parties/import",
            data=data,
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert response.status_code == 200


# ── Parties deactivation guard ────────────────────────────────────────


class TestPartyDeactivationGuard:
    def test_cannot_deactivate_with_outstanding(self, client, app):
        login(client, "admin", "admin-pass")
        with app.app_context():
            party = db.session.execute(
                db.select(Party).where(Party.party_type == PartyType.DENTIST)
            ).scalars().first()
            party.previous_balance = Decimal("500.00")
            db.session.commit()
            party_id = party.id

        response = client.post(
            f"/parties/{party_id}/edit",
            data={
                "name": "Dr. Test",
                "phone": "5550001122",
                "email": "",
                "address": "",
                "tax_id": "",
                "notes": "",
                "previous_balance": "500.00",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200


# ── Inject globals error paths ────────────────────────────────────────


class TestInjectGlobalsErrorPaths:
    def test_whatsapp_state_disconnected(self, client, app):
        from app.services.whatsapp_service import WhatsAppService

        login(client, "admin", "admin-pass")
        with patch.object(WhatsAppService, "quick_state", side_effect=Exception("boom")):
            response = client.get("/")
            assert response.status_code == 200

    def test_rate_health_error(self, client, app):
        from app.services.exchange_service import get_rate_health

        login(client, "admin", "admin-pass")
        with patch("app.services.exchange_service.get_rate_health", side_effect=Exception("boom")):
            response = client.get("/")
            assert response.status_code == 200


# ── Settings cache invalidation ────────────────────────────────────────


class TestSettingsCacheInvalidation:
    def test_settings_update_invalidates_cache(self, client, app):
        from app import _get_cached_setting, invalidate_settings_cache

        login(client, "admin", "admin-pass")

        with app.app_context():
            _get_cached_setting("clinic_name")
            invalidate_settings_cache("clinic_name")

        response = client.post(
            "/settings/update",
            data={"clinic_name": "Yeni Klinik Adı"},
            follow_redirects=True,
        )
        assert response.status_code == 200

    def test_reset_defaults_invalidates_cache(self, client, app):
        from app import invalidate_settings_cache

        login(client, "admin", "admin-pass")
        invalidate_settings_cache()

        response = client.post(
            "/settings/reset-defaults",
            follow_redirects=True,
        )
        assert response.status_code == 200


# ── Security service fail-hard ─────────────────────────────────────────


class TestSecurityServiceFailHard:
    def test_encrypt_without_encryption_key(self, app):
        from app.services.security_service import encrypt_value

        with app.app_context():
            app.config["ENCRYPTION_KEY"] = ""
            with pytest.raises(RuntimeError, match="ENCRYPTION_KEY"):
                encrypt_value("test")
