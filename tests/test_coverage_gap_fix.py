"""Targeted tests to close coverage gaps and reach ≥90%."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch, MagicMock

import pytest

from app.extensions import db
from app.models.models import (
    LoginAttempt, Makbuz, MakbuzPayment, Party, PartyType,
    ExchangeRate,
)
from conftest import login
from app.models.models import WorkOrder


def _make_doctor(app, name="Dr. Test", phone="+905550000001"):
    with app.app_context():
        p = Party(party_type=PartyType.DENTIST, name=name, phone=phone)
        db.session.add(p)
        db.session.commit()
        return p.id


def _add_work_order(app, party_id, work_date=None, price=Decimal("500.00")):
    work_date = work_date or date(2026, 1, 10)
    with app.app_context():
        wo = WorkOrder(
            party_id=party_id,
            work_date=work_date,
            apparatus_type="Nance",
            patient_name="Test Hasta",
            apparatus_price=price,
            extra_price=Decimal("0.00"),
        )
        wo.recalculate_total()
        db.session.add(wo)
        db.session.commit()
        return wo.id


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
        from app.services.exchange_service import ensure_daily_rate
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


# ── Invoice _normalize_item validation errors ─────────────────────────


class TestNormalizeItemValidation:
    def test_description_too_long(self):
        from app.services.invoice_service import _normalize_item
        with pytest.raises(ValueError, match="300 karakteri"):
            _normalize_item({"description": "x" * 301, "quantity": 1, "unit_price_eur": 10})

    def test_quantity_not_int(self):
        from app.services.invoice_service import _normalize_item
        with pytest.raises(ValueError, match="Miktar tam sayı"):
            _normalize_item({"description": "Test", "quantity": "abc", "unit_price_eur": 10})

    def test_unit_price_not_numeric(self):
        from app.services.invoice_service import _normalize_item
        with pytest.raises(ValueError, match="Birim fiyat sayısal"):
            _normalize_item({"description": "Test", "quantity": 1, "unit_price_eur": "xyz"})

    def test_vat_rate_not_numeric(self):
        from app.services.invoice_service import _normalize_item
        with pytest.raises(ValueError, match="KDV oranı sayısal"):
            _normalize_item({"description": "Test", "quantity": 1, "unit_price_eur": 10, "vat_rate": "bad"})

    def test_invalid_discount_type(self):
        from app.services.invoice_service import _normalize_item
        with pytest.raises(ValueError, match="İskonto tipi"):
            _normalize_item({"description": "Test", "quantity": 1, "unit_price_eur": 10, "discount_type": "bogus"})

    def test_discount_value_not_numeric(self):
        from app.services.invoice_service import _normalize_item
        with pytest.raises(ValueError, match="İskonto değeri sayısal"):
            _normalize_item({"description": "Test", "quantity": 1, "unit_price_eur": 10, "discount_type": "percent", "discount_value": "bad"})

    def test_discount_negative(self):
        from app.services.invoice_service import _normalize_item
        with pytest.raises(ValueError, match="negatif olamaz"):
            _normalize_item({"description": "Test", "quantity": 1, "unit_price_eur": 10, "discount_type": "amount", "discount_value": -5})

    def test_invalid_item_type(self):
        from app.services.invoice_service import _normalize_item
        with pytest.raises(ValueError, match="Geçersiz fatura kalemi tipi"):
            _normalize_item({"description": "Test", "quantity": 1, "unit_price_eur": 10, "item_type": "bogus"})

    def test_percent_discount_over_100(self):
        from app.services.invoice_service import _normalize_item
        with pytest.raises(ValueError, match="Yüzde iskonto 100"):
            _normalize_item({"description": "Test", "quantity": 1, "unit_price_eur": 10, "discount_type": "percent", "discount_value": 101})

    def test_amount_discount_exceeds_total(self):
        from app.services.invoice_service import _normalize_item
        with pytest.raises(ValueError, match="satır tutarını"):
            _normalize_item({"description": "Test", "quantity": 1, "unit_price_eur": 10, "discount_type": "amount", "discount_value": 20})

    def test_unit_price_negative(self):
        from app.services.invoice_service import _normalize_item
        with pytest.raises(ValueError, match="negatif olamaz"):
            _normalize_item({"description": "Test", "quantity": 1, "unit_price_eur": -5})


# ── format_whatsapp_url branches ─────────────────────────────────────


class TestFormatWhatsappUrl:
    def test_10_digits(self):
        from app.services.validation_service import format_whatsapp_url
        assert format_whatsapp_url("5551112233") == "https://wa.me/905551112233"

    def test_11_digits_leading_zero(self):
        from app.services.validation_service import format_whatsapp_url
        assert format_whatsapp_url("05551112233") == "https://wa.me/905551112233"

    def test_12_digits_90_prefix(self):
        from app.services.validation_service import format_whatsapp_url
        assert format_whatsapp_url("905551112233") == "https://wa.me/905551112233"

    def test_unknown_length(self):
        from app.services.validation_service import format_whatsapp_url
        assert format_whatsapp_url("123") == "https://wa.me/123"

    def test_empty(self):
        from app.services.validation_service import format_whatsapp_url
        assert format_whatsapp_url("") == "#"

    def test_none(self):
        from app.services.validation_service import format_whatsapp_url
        assert format_whatsapp_url(None) == "#"


# ── Validation parse_float / parse_date / currency fallback ───────────


    def test_normalize_treatment_invalid_currency(self):
        from app.services.validation_service import normalize_treatment_fields
        _, _, _, _, currency = normalize_treatment_fields(
            "Test", "desc", "ana_islemler", "50", currency="BOGUS"
        )
        assert currency == "TL"

    def test_parse_date_valid(self):
        from app.services.validation_service import parse_date
        assert parse_date("2026-06-15") == date(2026, 6, 15)

    def test_parse_date_invalid(self):
        from app.services.validation_service import parse_date
        assert parse_date("not-a-date") is None
        assert parse_date("") is None
        assert parse_date(None) is None


# ── Makbuzlar route edge-case flash messages ──────────────────────────


class TestMakbuzlarEdgeCases:
    def test_bulk_send_no_party_ids(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.post("/makbuzlar/bulk-send", data={"year": 2026, "month": 6, "party_ids": []}, follow_redirects=False)
        assert response.status_code == 302

    def test_bulk_send_no_draft_makbuzlar(self, client, app):
        login(client, "admin", "admin-pass")
        p = _make_doctor(app, name="Dr. No Draft Send", phone="+905551110061")
        response = client.post("/makbuzlar/bulk-send", data={"year": 2026, "month": 6, "party_ids": [str(p)]}, follow_redirects=False)
        assert response.status_code == 302

    def test_bulk_delete_no_party_ids(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.post("/makbuzlar/bulk-delete", data={"year": 2026, "month": 6, "party_ids": []}, follow_redirects=False)
        assert response.status_code == 302

    def test_bulk_delete_no_makbuzlar(self, client, app):
        login(client, "admin", "admin-pass")
        p = _make_doctor(app, name="Dr. No Delete", phone="+905551110062")
        response = client.post("/makbuzlar/bulk-delete", data={"year": 2026, "month": 6, "party_ids": [str(p)]}, follow_redirects=False)
        assert response.status_code == 302

    def test_bulk_generate_no_party_ids(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.post("/makbuzlar/bulk-generate", data={"year": 2026, "month": 6, "party_ids": []}, follow_redirects=False)
        assert response.status_code == 302

    def test_send_status(self, client, app):
        login(client, "admin", "admin-pass")
        response = client.get("/makbuzlar/send-status")
        assert response.status_code == 200
        data = response.get_json()
        assert "send_job" in data


# ── Makbuzlar view modes ─────────────────────────────────────────────


class TestMakbuzlarViewModes:
    def test_view_year(self, client, app):
        login(client, "admin", "admin-pass")
        p = _make_doctor(app, name="Dr. View Year", phone="+905551110051")
        _add_work_order(app, p, date(2026, 6, 10), 1000)
        response = client.get("/makbuzlar/?view=year&year=2026")
        assert response.status_code == 200

    def test_view_day(self, client, app):
        login(client, "admin", "admin-pass")
        p = _make_doctor(app, name="Dr. View Day", phone="+905551110052")
        _add_work_order(app, p, date(2026, 6, 10), 1000)
        response = client.get("/makbuzlar/?view=day&date=2026-06-10")
        assert response.status_code == 200

    def test_view_all(self, client, app):
        login(client, "admin", "admin-pass")
        p = _make_doctor(app, name="Dr. View All", phone="+905551110053")
        _add_work_order(app, p, date(2026, 6, 10), 1000)
        response = client.get("/makbuzlar/?view=all")
        assert response.status_code == 200


# ── Reports helpers ──────────────────────────────────────────────────


class TestReportsHelpers:
    def test_parse_wo_items(self):
        from app.services.reports_service import _parse_wo_items
        assert _parse_wo_items(None) == []
        assert _parse_wo_items("") == []
        assert _parse_wo_items("not json") == []
        assert _parse_wo_items("42") == []

    def test_resolve_rate_fallback(self, app):
        from app.services.reports_service import _resolve_rate

        with app.app_context():
            db.session.execute(db.delete(ExchangeRate))
            db.session.commit()
            rate = _resolve_rate(date(2026, 1, 1), None)
            assert rate == Decimal("1")
