from __future__ import annotations

from datetime import date
from decimal import Decimal
import threading

import bcrypt
import pytest
from sqlalchemy.pool import NullPool
from werkzeug.serving import make_server

from app import create_app
from app.extensions import db
from app.models.base import Base
from app.models.models import (
    ExchangeRate, Patient, PatientTreatment, Party, PartyType, Settings, Treatment, User
)


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-secret"
    ENCRYPTION_KEY = "test-encryption-key-longer-than-thirty-two"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False


@pytest.fixture(autouse=True)
def _reset_whatsapp_state(tmp_path_factory, monkeypatch):
    """Isolate WhatsAppService class state per test: no real Neonize client,
    no session/lock files in the repo's data/ directory."""
    from app.services.whatsapp_service import WhatsAppService

    monkeypatch.setattr(
        WhatsAppService, "_session_dir", str(tmp_path_factory.mktemp("whatsapp"))
    )
    monkeypatch.setattr(WhatsAppService, "_app", None)
    monkeypatch.setattr(WhatsAppService, "_client", None)
    monkeypatch.setattr(WhatsAppService, "_thread", None)
    monkeypatch.setattr(WhatsAppService, "_connected", False)
    monkeypatch.setattr(WhatsAppService, "_qr_code", None)
    monkeypatch.setattr(WhatsAppService, "_pair_code", None)
    monkeypatch.setattr(WhatsAppService, "_pair_wait_seconds", 0.5)

    from app.services.makbuz_send_queue import MakbuzSendQueue

    monkeypatch.setattr(MakbuzSendQueue, "_app", None)
    monkeypatch.setattr(MakbuzSendQueue, "_job", None)
    monkeypatch.setattr(MakbuzSendQueue, "_thread", None)
    monkeypatch.setattr(MakbuzSendQueue, "_delay_seconds", 0)

    from app.services.bulk_message_queue import BulkMessageQueue

    monkeypatch.setattr(BulkMessageQueue, "_app", None)
    monkeypatch.setattr(BulkMessageQueue, "_job", None)
    monkeypatch.setattr(BulkMessageQueue, "_thread", None)
    monkeypatch.setattr(BulkMessageQueue, "_delay_seconds", 0)
    yield
    handle = WhatsAppService._process_lock_handle
    if handle is not None:
        try:
            handle.close()
        except OSError:
            pass
        WhatsAppService._process_lock_handle = None


@pytest.fixture()
def app(tmp_path):
    class IsolatedTestConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'test.db'}"
        SQLALCHEMY_ENGINE_OPTIONS = {"poolclass": NullPool}

    app = create_app(IsolatedTestConfig)

    with app.app_context():
        # NOT: Testlerde Base.metadata.create_all() kullanılır; flask db upgrade
        # (Alembic) kullanılmaz. Bu kasıtlıdır: testler hızlı olmalı ve migration
        # geçmişinden bağımsız olmalıdır. Model tanımları ile migration'lar arasındaki
        # uyumluluk CI'da migrate kontrolü ile sağlanır.
        Base.metadata.create_all(bind=db.engine)

        default_settings = {
            "clinic_name": "Makro Ortodonti",
            "invoice_prefix": "MKR",
            "invoice_next_number": "1",
            "smtp_server": "smtp.gmail.com",
            "smtp_port": "587",
            "smtp_username": "old-user@example.com",
            "smtp_password": "old-pass",
        }
        for key, value in default_settings.items():
            db.session.add(Settings(key=key, value=value))

        admin_hash = bcrypt.hashpw(b"admin-pass", bcrypt.gensalt()).decode("utf-8")
        staff_hash = bcrypt.hashpw(b"staff-pass", bcrypt.gensalt()).decode("utf-8")

        db.session.add(
            User(
                username="admin",
                password_hash=admin_hash,
                full_name="Admin User",
                role=User.ROLE_ADMIN,
            )
        )
        db.session.add(
            User(
                username="staff",
                password_hash=staff_hash,
                full_name="Staff User",
                role=User.ROLE_STAFF,
            )
        )

        patient = Patient(first_name="Ayse", last_name="Yilmaz", phone="5551112233")
        db.session.add(patient)
        db.session.flush()

        treatments_seed = [
            Treatment(name="Consultation", category="ana_islemler", price_eur=50.0),
            Treatment(name="Crown", category="ekstra_islemler", price_eur=200.0),
            Treatment(name="Extraction", category="ana_islemler", price_eur=100.0),
        ]
        for t in treatments_seed:
            db.session.add(t)
        db.session.flush()

        # Test fixture: Hasta verisiyle ilişkili bir diş hekimi (DENTIST) oluştur.
        # Patient → Party ilişkisi: hasta, bu diş hekimine yönlendirilmiştir (referred_by_id).
        dentist_party = Party(
            party_type=PartyType.DENTIST,
            name="Dr. Ayse Yilmaz",
            phone="5551112233",
            email="dr.ayse@example.com",
            is_active=True,
        )
        db.session.add(dentist_party)
        db.session.flush()

        patient.party_id = dentist_party.id

        db.session.add(
            PatientTreatment(
                patient_id=patient.id,
                party_id=dentist_party.id,
                treatment_id=treatments_seed[0].id,
                treatment_date=date.today(),
                price_override_eur=55.0,
            )
        )

        db.session.add(
            ExchangeRate(rate_date=date.today(), eur_to_try=40.0, source="ecb")
        )
        db.session.commit()

    yield app

    with app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, username: str, password: str):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


@pytest.fixture(scope="session")
def live_server_url(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("e2e") / "makro.db"

    class E2EConfig:
        TESTING = True
        DEBUG = False
        SECRET_KEY = "e2e-session-key-longer-than-thirty-two-characters"
        ENCRYPTION_KEY = "e2e-encryption-key-longer-than-thirty-two-characters"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        WTF_CSRF_ENABLED = True
        SESSION_COOKIE_SECURE = False
        TRUST_PROXY = False
        FORCE_HSTS = False
        MAX_CONTENT_LENGTH = 16 * 1024 * 1024
        AUDIT_RETENTION_DAYS = 3650

    e2e_app = create_app(E2EConfig)
    with e2e_app.app_context():
        Base.metadata.create_all(bind=db.engine)
        db.session.add(User(
            username="admin", full_name="E2E Admin", role="admin",
            password_hash=bcrypt.hashpw(b"admin-pass", bcrypt.gensalt()).decode(),
        ))
        db.session.add(Party(
            party_type=PartyType.DENTIST, name="Dr. E2E Hekim",
            phone="5551112233",
        ))
        db.session.add(Party(
            party_type=PartyType.DENTIST, name="Dr. Pınar Şahin",
            phone="5551114455",
        ))
        db.session.add(Treatment(name="E2E Muayene", category="ana_islemler", price_eur=Decimal("50.00")))
        db.session.add(ExchangeRate(rate_date=date.today(), eur_to_try=Decimal("40.0000"), source="ecb"))
        db.session.add(Settings(key="invoice_prefix", value="MKR"))
        db.session.add(Settings(key="invoice_next_number", value="1"))
        db.session.commit()

    try:
        server = make_server("127.0.0.1", 0, e2e_app)
    except (PermissionError, OSError, SystemExit) as exc:
        pytest.skip(f"Port binding not permitted in current sandbox environment: {exc}")

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join(timeout=5)
    with e2e_app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def authenticated_page(page, live_server_url):
    page.goto(f"{live_server_url}/login")
    page.get_by_label("Kullanıcı Adı").fill("admin")
    page.get_by_label("Şifre").fill("admin-pass")
    page.get_by_role("button", name="Giriş Yap").click()
    page.wait_for_url(f"{live_server_url}/")
    return page


def pytest_collection_modifyitems(items):
    """Auto-apply the ``e2e`` marker to everything under tests/e2e/ so
    ``pytest -m "not e2e"`` has a real fast path without every test file
    having to remember to mark itself."""
    for item in items:
        if "e2e" in item.fspath.dirname.split("/"):
            item.add_marker(pytest.mark.e2e)
