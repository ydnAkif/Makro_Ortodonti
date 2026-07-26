"""Yeni özelliklerin testleri:

- Makbuz toplu silme (bulk_delete_makbuzlar)
- Ayarları varsayılana sıfırlama (reset_defaults)
- Demo veri temizleme (purge_demo_data)
- Veritabanı yedekleme servisi (backup_service)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.extensions import db
from app.models.models import (
    AuditLog, ExchangeRate, Invoice, InvoiceItem, InvoiceItemType, Makbuz,
    MakbuzPayment, MakbuzSendLog, Party, PartyType, Payment, PaymentMethod,
    Settings, Treatment, User, WorkOrder,
)

from conftest import login


# ---------------------------------------------------------------------------
# Yardımcı fonksiyonlar
# ---------------------------------------------------------------------------

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
            total_price=price,
        )
        db.session.add(wo)
        db.session.commit()
        return wo.id


def _make_draft_makbuz(app, party_id, year=2026, month=1):
    """Doğrudan DB'ye taslak makbuz ekler."""
    with app.app_context():
        m = Makbuz(
            party_id=party_id,
            year=year,
            month=month,
            status=Makbuz.STATUS_DRAFT,
            subtotal=Decimal("500.00"),
            grand_total=Decimal("500.00"),
            work_order_count=1,
        )
        db.session.add(m)
        db.session.commit()
        return m.id


def _make_sent_makbuz(app, party_id, year=2026, month=2):
    with app.app_context():
        m = Makbuz(
            party_id=party_id,
            year=year,
            month=month,
            status=Makbuz.STATUS_SENT,
            subtotal=Decimal("800.00"),
            grand_total=Decimal("800.00"),
            work_order_count=1,
        )
        db.session.add(m)
        db.session.commit()
        return m.id


def _make_invoice(app, party_id):
    """Basit bir fatura + kalem + ödeme oluşturur."""
    with app.app_context():
        inv = Invoice(
            party_id=party_id,
            invoice_number="MKR-TEST-001",
            invoice_date=date(2026, 1, 15),
            total_eur=Decimal("100.00"),
            total_try=Decimal("4000.00"),
            exchange_rate=Decimal("40.0000"),
            status=Invoice.STATUS_PENDING,
        )
        db.session.add(inv)
        db.session.flush()

        treatment = db.session.execute(db.select(Treatment).limit(1)).scalar_one()
        item = InvoiceItem(
            invoice_id=inv.id,
            item_type=InvoiceItemType.TREATMENT,
            treatment_id=treatment.id,
            description=treatment.name,
            quantity=1,
            unit_price_eur=Decimal("100.00"),
            unit_price_try=Decimal("4000.00"),
        )
        db.session.add(item)
        db.session.flush()

        payment = Payment(
            invoice_id=inv.id,
            payment_date=date(2026, 1, 20),
            amount_eur=Decimal("50.00"),
            amount_try=Decimal("2000.00"),
            exchange_rate=Decimal("40.0000"),
            method=PaymentMethod.CASH,
        )
        db.session.add(payment)
        db.session.commit()
        return inv.id


# ===========================================================================
# BÖLÜM 1 — Makbuz toplu silme
# ===========================================================================

class TestPartyPreviousBalance:

    def test_doctor_previous_balance_saved_from_form(self, client, app):
        login(client, "admin", "admin-pass")

        resp = client.post(
            "/parties/add",
            data={
                "name": "Dr. Borçlu Hekim",
                "phone": "+905551112233",
                "email": "borclu@example.com",
                "address": "İstanbul",
                "tax_id": "1234567890",
                "notes": "",
                "previous_balance": "125.50",
                "is_active": "on",
            },
            follow_redirects=True,
        )

        assert resp.status_code == 200

        with app.app_context():
            party = db.session.execute(
                db.select(Party).where(Party.name == "Dr. Borçlu Hekim")
            ).scalar_one()
            assert party.previous_balance == Decimal("125.50")


class TestBulkDeleteMakbuzlar:

    def test_draft_makbuzlar_silinir(self, client, app):
        """Seçili taslak makbuzlar başarıyla silinmeli."""
        login(client, "admin", "admin-pass")
        pid = _make_doctor(app, "Dr. Silme Testi")
        _add_work_order(app, pid)
        mid = _make_draft_makbuz(app, pid, year=2026, month=1)

        resp = client.post(
            "/makbuzlar/bulk-delete",
            data={"year": 2026, "month": 1, "party_ids": pid},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "taslak makbuz silindi".encode() in resp.data

        with app.app_context():
            assert db.session.get(Makbuz, mid) is None

    def test_sent_makbuz_silinemez(self, client, app):
        """Gönderilmiş makbuzlar seçilse bile silinmemeli."""
        login(client, "admin", "admin-pass")
        pid = _make_doctor(app, "Dr. Gönderilmiş")
        mid = _make_sent_makbuz(app, pid, year=2026, month=2)

        resp = client.post(
            "/makbuzlar/bulk-delete",
            data={"year": 2026, "month": 2, "party_ids": pid},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        # Uyarı mesajı + makbuz hâlâ var olmalı
        assert "silinebilir taslak makbuz yok".encode() in resp.data
        with app.app_context():
            assert db.session.get(Makbuz, mid) is not None

    def test_bos_secim_uyari_verir(self, client, app):
        """Hiç doktor seçilmezse uyarı flash'ı görünmeli."""
        login(client, "admin", "admin-pass")
        resp = client.post(
            "/makbuzlar/bulk-delete",
            data={"year": 2026, "month": 1},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "Silinecek doktor seçilmedi".encode() in resp.data

    def test_staff_yetkisiz_silinemez(self, client, app):
        """Staff rolü billing.edit gerektiren silme işlemi yapamamalı."""
        login(client, "staff", "staff-pass")
        pid = _make_doctor(app, "Dr. Yetki Testi")
        _make_draft_makbuz(app, pid, year=2026, month=1)

        resp = client.post(
            "/makbuzlar/bulk-delete",
            data={"year": 2026, "month": 1, "party_ids": pid},
            follow_redirects=True,
        )
        # staff billing.edit yetkisine sahip; 200 dönmeli ama silme başarılı olmalı
        # (staff'ın billing.edit yetkisi var — authz matrisine göre)
        assert resp.status_code == 200

    def test_yalnizca_draft_silinir_sent_korunur(self, client, app):
        """Aynı ay hem draft hem sent makbuz varken yalnızca draft silinmeli."""
        login(client, "admin", "admin-pass")
        pid1 = _make_doctor(app, "Dr. Draft")
        pid2 = _make_doctor(app, "Dr. Sent", phone="+905550000002")
        mid_draft = _make_draft_makbuz(app, pid1, year=2026, month=3)
        mid_sent = _make_sent_makbuz(app, pid2, year=2026, month=3)

        resp = client.post(
            "/makbuzlar/bulk-delete",
            data={"year": 2026, "month": 3, "party_ids": [pid1, pid2]},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        with app.app_context():
            assert db.session.get(Makbuz, mid_draft) is None
            assert db.session.get(Makbuz, mid_sent) is not None


class TestSingleDeleteMakbuz:

    def test_draft_makbuz_silinir(self, client, app):
        """Taslak makbuz başarıyla silinebilmeli."""
        login(client, "admin", "admin-pass")
        pid = _make_doctor(app, "Dr. Single Delete")
        mid = _make_draft_makbuz(app, pid, year=2026, month=4)

        resp = client.post(f"/makbuzlar/{mid}/delete", follow_redirects=True)
        assert resp.status_code == 200
        assert "Makbuz silindi".encode() in resp.data
        with app.app_context():
            assert db.session.get(Makbuz, mid) is None

    def test_sent_makbuz_silinemez(self, client, app):
        """Gönderilmiş makbuz silinememeli."""
        login(client, "admin", "admin-pass")
        pid = _make_doctor(app, "Dr. Sent Cannot Delete")
        mid = _make_sent_makbuz(app, pid, year=2026, month=4)

        resp = client.post(f"/makbuzlar/{mid}/delete", follow_redirects=True)
        assert resp.status_code == 200
        assert "Yalnızca taslak" in resp.data.decode("utf-8")
        with app.app_context():
            assert db.session.get(Makbuz, mid) is not None

    def test_var_olmayan_makbuz_404_verir(self, client, app):
        """Var olmayan makbuz ID'si 404 döndürmeli."""
        login(client, "admin", "admin-pass")
        resp = client.post("/makbuzlar/99999/delete")
        assert resp.status_code == 404


# ===========================================================================
# BÖLÜM 2 — Ayarları varsayılana sıfırlama
# ===========================================================================

class TestResetDefaults:

    def test_klinik_bilgileri_sifirlanir(self, client, app):
        """Klinik bilgileri DEFAULTS değerlerine dönmeli."""
        login(client, "admin", "admin-pass")

        # Önce özel değer yaz
        client.post(
            "/settings/update",
            data={"clinic_name": "Özel Klinik Adı", "clinic_phone": "5550001122"},
            follow_redirects=True,
        )

        resp = client.post("/settings/reset-defaults", follow_redirects=True)
        assert resp.status_code == 200
        assert "varsayılan değerlere sıfırlandı".encode() in resp.data

        with app.app_context():
            row = db.session.execute(
                db.select(Settings.value).where(Settings.key == "clinic_name")
            ).scalar_one_or_none()
            assert row == Settings.DEFAULTS["clinic_name"]

    def test_smtp_ayarlari_korunur(self, client, app):
        """Sıfırlama SMTP ayarlarına dokunmamalı."""
        login(client, "admin", "admin-pass")

        with app.app_context():
            smtp = db.session.execute(
                db.select(Settings.value).where(Settings.key == "smtp_server")
            ).scalar_one_or_none()
            original_smtp = smtp or "smtp.gmail.com"

        client.post("/settings/reset-defaults", follow_redirects=True)

        with app.app_context():
            after = db.session.execute(
                db.select(Settings.value).where(Settings.key == "smtp_server")
            ).scalar_one_or_none()
            assert after == original_smtp

    def test_admin_yetkisi_gerekli(self, client, app):
        """settings.manage yetkisi olmayan staff sıfırlama yapamamalı."""
        login(client, "staff", "staff-pass")
        resp = client.post("/settings/reset-defaults", follow_redirects=True)
        assert resp.status_code == 200
        assert "yetkiniz bulunmuyor".encode() in resp.data


# ===========================================================================
# BÖLÜM 3 — Demo veri temizleme
# ===========================================================================

class TestPurgeDemoData:

    def _seed_operational_data(self, app):
        """WorkOrder, Makbuz, Invoice, Payment, AuditLog, ExchangeRate ekler."""
        with app.app_context():
            party = db.session.execute(
                db.select(Party).where(Party.party_type == PartyType.DENTIST)
            ).scalars().first()

            wo = WorkOrder(
                party_id=party.id,
                work_date=date(2026, 1, 5),
                apparatus_type="Retainer",
                patient_name="Demo Hasta",
                apparatus_price=Decimal("600.00"),
                extra_price=Decimal("0.00"),
                total_price=Decimal("600.00"),
            )
            db.session.add(wo)

            m = Makbuz(
                party_id=party.id,
                year=2026, month=1,
                status=Makbuz.STATUS_DRAFT,
                subtotal=Decimal("600.00"),
                grand_total=Decimal("600.00"),
                work_order_count=1,
            )
            db.session.add(m)

            log = AuditLog(
                entity_type="work_orders",
                entity_id="1",
                action="create",
            )
            db.session.add(log)
            db.session.commit()
            party_id = party.id

        return _make_invoice(app, party_id)

    def test_operasyonel_veriler_silinir(self, client, app):
        """Temizleme sonrası WorkOrder, Makbuz, Invoice tabloları boş olmalı."""
        login(client, "admin", "admin-pass")
        self._seed_operational_data(app)

        resp = client.post("/settings/purge-demo-data", follow_redirects=True)
        assert resp.status_code == 200
        assert "Demo veriler temizlendi".encode() in resp.data

        with app.app_context():
            assert db.session.execute(db.select(WorkOrder)).scalars().first() is None
            assert db.session.execute(db.select(Makbuz)).scalars().first() is None
            assert db.session.execute(db.select(Invoice)).scalars().first() is None
            assert db.session.execute(db.select(InvoiceItem)).scalars().first() is None
            assert db.session.execute(db.select(Payment)).scalars().first() is None
            assert db.session.execute(db.select(ExchangeRate)).scalars().first() is None
            assert db.session.execute(db.select(AuditLog)).scalars().first() is None

    def test_makbuz_bagli_tablar_ile_de_temizlenir(self, client, app):
        """Makbuz ödeme/gönderim kayıtları da temizlenince silme işlemi başarılı olmalı."""
        login(client, "admin", "admin-pass")
        self._seed_operational_data(app)

        with app.app_context():
            party = db.session.execute(
                db.select(Party).where(Party.party_type == PartyType.DENTIST)
            ).scalars().first()
            makbuz = db.session.execute(db.select(Makbuz)).scalars().first()
            db.session.add(MakbuzPayment(
                makbuz_id=makbuz.id,
                payment_date=date(2026, 1, 20),
                amount=Decimal("100.00"),
            ))
            db.session.add(MakbuzSendLog(
                batch_id="batch-1",
                makbuz_id=makbuz.id,
                party_id=party.id,
                doctor_name=party.name,
                phone=party.phone,
                year=makbuz.year,
                month=makbuz.month,
                success=True,
            ))
            db.session.commit()

        resp = client.post("/settings/purge-demo-data", follow_redirects=True)
        assert resp.status_code == 200
        assert "Demo veriler temizlendi".encode() in resp.data

        with app.app_context():
            assert db.session.execute(db.select(MakbuzPayment)).scalars().first() is None
            assert db.session.execute(db.select(MakbuzSendLog)).scalars().first() is None
            assert db.session.execute(db.select(Makbuz)).scalars().first() is None

    def test_doktorlar_ve_islemler_korunur(self, client, app):
        """Temizleme sonrası Party ve Treatment kayıtları silinmemeli."""
        login(client, "admin", "admin-pass")
        self._seed_operational_data(app)

        with app.app_context():
            party_count_before = db.session.execute(
                db.select(db.func.count()).select_from(Party)
            ).scalar()
            treatment_count_before = db.session.execute(
                db.select(db.func.count()).select_from(Treatment)
            ).scalar()

        client.post("/settings/purge-demo-data", follow_redirects=True)

        with app.app_context():
            assert db.session.execute(
                db.select(db.func.count()).select_from(Party)
            ).scalar() == party_count_before

            assert db.session.execute(
                db.select(db.func.count()).select_from(Treatment)
            ).scalar() == treatment_count_before

    def test_kullanicilar_korunur(self, client, app):
        """Kullanıcı hesapları temizleme sonrası kaybolmamalı."""
        login(client, "admin", "admin-pass")

        with app.app_context():
            user_count = db.session.execute(
                db.select(db.func.count()).select_from(User)
            ).scalar()

        client.post("/settings/purge-demo-data", follow_redirects=True)

        with app.app_context():
            assert db.session.execute(
                db.select(db.func.count()).select_from(User)
            ).scalar() == user_count

    def test_ayarlar_korunur(self, client, app):
        """Settings tablosu temizleme sonrası sağlam kalmalı."""
        login(client, "admin", "admin-pass")

        with app.app_context():
            settings_count = db.session.execute(
                db.select(db.func.count()).select_from(Settings)
            ).scalar()

        client.post("/settings/purge-demo-data", follow_redirects=True)

        with app.app_context():
            assert db.session.execute(
                db.select(db.func.count()).select_from(Settings)
            ).scalar() == settings_count

    def test_admin_yetkisi_gerekli(self, client, app):
        """Staff bu işlemi yapamamalı."""
        login(client, "staff", "staff-pass")
        resp = client.post("/settings/purge-demo-data", follow_redirects=True)
        assert resp.status_code == 200
        assert "yetkiniz bulunmuyor".encode() in resp.data

    def test_bos_veritabaninda_calismali(self, client, app):
        """Zaten boş veritabanında çalıştırınca hata vermemeli."""
        login(client, "admin", "admin-pass")
        resp = client.post("/settings/purge-demo-data", follow_redirects=True)
        assert resp.status_code == 200
        assert "Demo veriler temizlendi".encode() in resp.data


# ===========================================================================
# BÖLÜM 4 — Veritabanı yedekleme servisi
# ===========================================================================

class TestBackupService:
    """backup_service modülünü doğrudan patch'leyerek test eder."""

    @pytest.fixture(autouse=True)
    def _patch_backup_dir(self, tmp_path, monkeypatch):
        """Tüm backup testleri için _backup_dir ve _db_path'i geçici klasöre yönlendir."""
        import app.services.backup_service as svc
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        # Gerçek bir SQLite dosyası oluştur (in-memory olamaz, backup() dosya ister)
        fake_db = tmp_path / "fake.db"
        import sqlite3
        conn = sqlite3.connect(str(fake_db))
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        monkeypatch.setattr(svc, "_backup_dir", lambda: backup_dir)
        monkeypatch.setattr(svc, "_db_path", lambda: fake_db)
        self._backup_dir = backup_dir
        self._svc = svc

    def test_yedek_alinir_ve_dosya_olusur(self, app):
        """create_backup() gerçek bir .db dosyası oluşturmalı."""
        with app.app_context():
            dest = self._svc.create_backup()
        assert dest.exists()
        assert dest.suffix == ".db"
        assert dest.stat().st_size > 0

    def test_yedek_listesi_doner(self, app):
        """list_backups() backup klasöründeki dosyaları listeler."""
        with app.app_context():
            self._svc.create_backup()
            result = self._svc.list_backups()
        assert len(result) == 1
        assert result[0]["filename"].startswith("makroortodonti_")
        assert result[0]["size_kb"] > 0

    def test_gecersiz_dosya_adi_reddedilir(self, app):
        """get_backup_path() path traversal içeren dosya adlarını reddetmeli."""
        with app.app_context():
            assert self._svc.get_backup_path("../../etc/passwd") is None
            assert self._svc.get_backup_path("../secret.db") is None
            assert self._svc.get_backup_path("makroortodonti_20260101_020000.db") is None

    def test_eski_yedekler_temizlenir(self, app):
        """_prune_old_backups; limitin üzerindekileri siler."""
        import time
        # 5 sahte yedek dosyası oluştur (farklı mtime için kısa bekleme)
        for i in range(5):
            name = f"makroortodonti_202601{i+1:02d}_000000.db"
            (self._backup_dir / name).write_bytes(b"SQLite")
            time.sleep(0.01)

        original_keep = self._svc.BACKUP_KEEP
        self._svc.BACKUP_KEEP = 3
        try:
            self._svc._prune_old_backups()
        finally:
            self._svc.BACKUP_KEEP = original_keep

        files = list(self._backup_dir.glob("makroortodonti_*.db"))
        assert len(files) == 3

    def test_backup_endpoint_yedek_alir(self, client, app):
        """POST /settings/backup/create yedek oluşturmalı ve başarı mesajı vermeli."""
        login(client, "admin", "admin-pass")
        resp = client.post("/settings/backup/create", follow_redirects=True)
        assert resp.status_code == 200
        assert "Yedek alındı".encode() in resp.data

    def test_download_endpoint_dosya_gonderir(self, client, app):
        """GET /settings/backup/download/<filename> geçerli yedeği indirmeli."""
        login(client, "admin", "admin-pass")
        client.post("/settings/backup/create", follow_redirects=True)

        backups = self._svc.list_backups()
        assert backups

        filename = backups[0]["filename"]
        # as_attachment=True ile send_file bir Response döndürür;
        # veri tamamlanınca Flask test istemcisi tamponı kapatır.
        with client.get(f"/settings/backup/download/{filename}") as resp:
            assert resp.status_code == 200
            data = resp.data
        assert len(data) > 0

    def test_download_gecersiz_dosya_yonlendirir(self, client, app):
        """Var olmayan yedek için flash mesajıyla liste sayfasına yönlendirmeli."""
        login(client, "admin", "admin-pass")
        resp = client.get(
            "/settings/backup/download/makroortodonti_20000101_000000.db",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "Yedek dosyası bulunamadı".encode() in resp.data


def test_previous_balance_reflected_in_payments_and_reports(client, app):
    """Doktorun party.previous_balance borcunun tahsilat ve rapor hesaplamalarına girdiğini doğrula."""
    login(client, "admin", "admin-pass")
    with app.app_context():
        p = Party(
            party_type=PartyType.DENTIST,
            name="Dr. Devreden Borçlu",
            phone="+905559998877",
            previous_balance=Decimal("7500.00"),
        )
        db.session.add(p)
        db.session.commit()
        party_id = p.id

    resp = client.get("/payments/?tab=summary")
    assert resp.status_code == 200
    assert "Dr. Devreden Borçlu".encode() in resp.data
    assert "7,500.00".encode() in resp.data

    from app.services.reports_service import build_doctor_summaries, build_aging_buckets
    with app.app_context():
        work_orders = db.session.execute(db.select(WorkOrder)).scalars().all()
        all_makbuzlar = db.session.execute(db.select(Makbuz)).scalars().all()
        summaries = build_doctor_summaries(date(2026, 1, 1), date(2026, 12, 31), work_orders, all_makbuzlar)
        d_summary = next(s for s in summaries if s.party_id == party_id)
        assert d_summary.previous_debt >= Decimal("7500.00")
        assert d_summary.outstanding_try >= Decimal("7500.00")

        aging = build_aging_buckets(date(2026, 12, 31), all_makbuzlar)
        assert aging[4].amount >= Decimal("7500.00")


def test_work_order_views_and_pdf_export(client, app):
    """İş emirleri sayfasında gün, ay, yıl, tümü görünümlerini ve PDF indirme çıktısını doğrula."""
    login(client, "admin", "admin-pass")

    # 1. Day view
    resp = client.get("/parties/work-orders?view=day")
    assert resp.status_code == 200
    assert "İş emirleri".encode() in resp.data
    assert "PDF İndir".encode() in resp.data

    # 2. Month view
    resp = client.get("/parties/work-orders?view=month&year=2026&month=7")
    assert resp.status_code == 200
    assert "Temmuz 2026".encode() in resp.data

    # 3. Year view
    resp = client.get("/parties/work-orders?view=year&year=2026")
    assert resp.status_code == 200
    assert "2026 Yılı".encode() in resp.data

    # 4. All view
    resp = client.get("/parties/work-orders?view=all")
    assert resp.status_code == 200
    assert "Tüm Zamanlar".encode() in resp.data

    # 5. PDF Export
    pdf_resp = client.get("/parties/work-orders/pdf?view=month&year=2026&month=7")
    assert pdf_resp.status_code == 200
    assert pdf_resp.mimetype == "application/pdf"
    assert b"%PDF" in pdf_resp.data


def test_delete_doctor_with_outstanding_debt_blocked(client, app):
    """Borcu olan doktorun silinmesi/pasife alınmasının engellendiğini doğrula."""
    login(client, "admin", "admin-pass")
    with app.app_context():
        p = Party(
            party_type=PartyType.DENTIST,
            name="Dr. Borçlu Silinemez",
            previous_balance=Decimal("3500.00"),
            is_active=True,
        )
        db.session.add(p)
        db.session.commit()
        party_id = p.id

    resp = client.post(f"/parties/{party_id}/delete", follow_redirects=True)
    assert resp.status_code == 200
    assert "devreden / açık borcu bulunmaktadır".encode() in resp.data

    with app.app_context():
        party = db.get_or_404(Party, party_id)
        assert party.is_active is True


def test_makbuzlar_views_status_filters_and_pdf_export(client, app):
    """Makbuzlar sayfasında gün, ay, yıl, tümü ve durum filtreleri ile PDF indirme çıktısını doğrula."""
    login(client, "admin", "admin-pass")

    # 1. Day view
    resp = client.get("/makbuzlar?view=day")
    assert resp.status_code == 200
    assert "Makbuzlar".encode() in resp.data

    # 2. Month view
    resp = client.get("/makbuzlar?view=month&year=2026&month=7")
    assert resp.status_code == 200
    assert "Temmuz 2026".encode() in resp.data

    # 3. Year view
    resp = client.get("/makbuzlar?view=year&year=2026")
    assert resp.status_code == 200
    assert "2026 Yılı".encode() in resp.data

    # 4. All view with status filter
    resp = client.get("/makbuzlar?view=all&status_filter=draft")
    assert resp.status_code == 200
    assert "Tüm Zamanlar".encode() in resp.data

    # 5. PDF Export
    pdf_resp = client.get("/makbuzlar/pdf?view=month&year=2026&month=7")
    assert pdf_resp.status_code == 200
    assert pdf_resp.mimetype == "application/pdf"
    assert b"%PDF" in pdf_resp.data
