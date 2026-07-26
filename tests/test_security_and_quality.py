"""
Security, invariant, and quality-gate tests.

These tests complement the existing suites with:
- CSRF-protection verification (WTF_CSRF_ENABLED=True fixture)
- Financial invariant enforcement via InvoiceService
- Health endpoint
- Secret management (Fernet round-trip, fail-closed behaviour)
- PartyType input validation (no 500 on bad enum value)
"""
from __future__ import annotations

import json
import pytest
from datetime import date
from unittest.mock import patch

import bcrypt

from app import create_app
from app.config import DEFAULT_DEV_SECRET, PLACEHOLDER_SECRET
from app.extensions import db
from app.models.base import Base
from app.models.models import (
    ExchangeRate, Party, PartyType, Settings, Treatment, User,
)
from app.models.invoice_service import InvoiceService
from conftest import login


# ──────────────────────────────────────────────
# CSRF-enabled fixture
# ──────────────────────────────────────────────

class CsrfConfig:
    TESTING = True
    SECRET_KEY = "csrf-test-secret"
    WTF_CSRF_ENABLED = True  # CSRF is ON for these tests
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_TIME_LIMIT = None  # Disable token expiry so tests are stable


class InsecureProductionConfig:
    TESTING = False
    DEBUG = False
    SECRET_KEY = DEFAULT_DEV_SECRET
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class MissingEncryptionKeyProductionConfig:
    TESTING = False
    DEBUG = False
    SECRET_KEY = "session-key-that-is-longer-than-thirty-two-characters"
    ENCRYPTION_KEY = PLACEHOLDER_SECRET
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False


@pytest.fixture()
def csrf_app():
    app = create_app(CsrfConfig)
    with app.app_context():
        Base.metadata.create_all(bind=db.engine)
        admin_hash = bcrypt.hashpw(b"admin-pass", bcrypt.gensalt()).decode()
        db.session.add(User(username="admin", password_hash=admin_hash,
                            full_name="Admin", role=User.ROLE_ADMIN))
        db.session.add(ExchangeRate(rate_date=date.today(), eur_to_try=40.0, source="ecb"))
        db.session.commit()
    yield app

    with app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture()
def csrf_client(csrf_app):
    return csrf_app.test_client()


def test_production_rejects_default_secret():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(InsecureProductionConfig)


def test_production_requires_separate_encryption_key():
    with pytest.raises(RuntimeError, match="ENCRYPTION_KEY"):
        create_app(MissingEncryptionKeyProductionConfig)


# ──────────────────────────────────────────────
# CSRF tests
# ──────────────────────────────────────────────

def test_csrf_rejects_missing_token_on_post(csrf_client):
    """POST without CSRF token must be rejected (400)."""
    response = csrf_client.post(
        "/login",
        data={"username": "admin", "password": "admin-pass"},
    )
    assert response.status_code == 400


def test_csrf_accepts_valid_token(csrf_client):
    """POST with a valid CSRF token must be accepted."""
    # GET the login page to obtain a token
    get_resp = csrf_client.get("/login")
    assert get_resp.status_code == 200

    # Extract the CSRF token from the meta tag
    html = get_resp.get_data(as_text=True)
    import re
    match = re.search(r'name="csrf-token" content="([^"]+)"', html)
    if not match:
        # Try hidden input fallback
        match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert match, "CSRF token not found in login page HTML"
    token = match.group(1)

    response = csrf_client.post(
        "/login",
        data={"username": "admin", "password": "admin-pass", "csrf_token": token},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Giriş başarılı" in response.get_data(as_text=True)


# ──────────────────────────────────────────────
# Financial invariant tests
# ──────────────────────────────────────────────

def _make_valid_item(**overrides):
    base = {
        "item_type": "custom",
        "description": "Test kalemi",
        "quantity": 1,
        "unit_price_eur": 100.0,
        "vat_rate": 20.0,
        "discount_type": None,
        "discount_value": 0.0,
    }
    base.update(overrides)
    return base


def test_invoice_service_rejects_zero_quantity(app):
    with app.app_context():
        party = db.session.execute(
            db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
        ).scalar_one()
        with pytest.raises(ValueError, match="sıfırdan büyük"):
            InvoiceService.create_invoice(
                session=db.session,
                party_id=party.id,
                items=[_make_valid_item(quantity=0)],
            )


def test_invoice_service_rejects_negative_quantity(app):
    with app.app_context():
        party = db.session.execute(
            db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
        ).scalar_one()
        with pytest.raises(ValueError, match="sıfırdan büyük"):
            InvoiceService.create_invoice(
                session=db.session,
                party_id=party.id,
                items=[_make_valid_item(quantity=-1)],
            )


def test_invoice_service_rejects_negative_unit_price(app):
    with app.app_context():
        party = db.session.execute(
            db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
        ).scalar_one()
        with pytest.raises(ValueError, match="negatif olamaz"):
            InvoiceService.create_invoice(
                session=db.session,
                party_id=party.id,
                items=[_make_valid_item(unit_price_eur=-50.0)],
            )


def test_invoice_service_rejects_vat_over_100(app):
    with app.app_context():
        party = db.session.execute(
            db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
        ).scalar_one()
        with pytest.raises(ValueError, match="KDV oranı"):
            InvoiceService.create_invoice(
                session=db.session,
                party_id=party.id,
                items=[_make_valid_item(vat_rate=150.0)],
            )


def test_invoice_service_rejects_percent_discount_over_100(app):
    with app.app_context():
        party = db.session.execute(
            db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
        ).scalar_one()
        with pytest.raises(ValueError, match="100"):
            InvoiceService.create_invoice(
                session=db.session,
                party_id=party.id,
                items=[_make_valid_item(discount_type="percent", discount_value=110.0)],
            )


def test_invoice_service_rejects_amount_discount_exceeding_line_total(app):
    with app.app_context():
        party = db.session.execute(
            db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
        ).scalar_one()
        with pytest.raises(ValueError, match="satır tutarını"):
            InvoiceService.create_invoice(
                session=db.session,
                party_id=party.id,
                items=[_make_valid_item(
                    unit_price_eur=50.0,
                    quantity=1,
                    discount_type="amount",
                    discount_value=200.0,  # 200 > 50 * 1
                )],
            )


def test_invoice_service_rejects_empty_description(app):
    with app.app_context():
        party = db.session.execute(
            db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
        ).scalar_one()
        with pytest.raises(ValueError, match="boş olamaz"):
            InvoiceService.create_invoice(
                session=db.session,
                party_id=party.id,
                items=[_make_valid_item(description="")],
            )


def test_invoice_service_rejects_unknown_party(app):
    with app.app_context():
        with pytest.raises(ValueError, match="Müşteri bulunamadı"):
            InvoiceService.create_invoice(
                session=db.session,
                party_id=99999,
                items=[_make_valid_item()],
            )


def test_invoice_service_rejects_empty_items_list(app):
    with app.app_context():
        party = db.session.execute(
            db.select(Party).where(Party.party_type == PartyType.DENTIST).limit(1)
        ).scalar_one()
        with pytest.raises(ValueError, match="en az bir kalem"):
            InvoiceService.create_invoice(
                session=db.session,
                party_id=party.id,
                items=[],
            )


# ──────────────────────────────────────────────
# Security service tests
# ──────────────────────────────────────────────

def test_fernet_encrypt_decrypt_roundtrip(app):
    """encrypt_value → decrypt_value must round-trip correctly."""
    with app.app_context():
        from app.services.security_service import encrypt_value, decrypt_value

        secret = "super-secret-smtp-password!@#"
        token = encrypt_value(secret)

        # Token must be a Fernet token
        assert token.startswith("gAAAAA")
        assert token != secret

        assert decrypt_value(token) == secret


def test_fernet_decrypt_raises_on_invalid_token(app):
    """decrypt_value must raise ValueError for non-Fernet input."""
    with app.app_context():
        from app.services.security_service import decrypt_value

        with pytest.raises(ValueError, match="Failed to decrypt"):
            decrypt_value("not-a-fernet-token")


def test_fernet_encrypt_empty_returns_empty(app):
    with app.app_context():
        from app.services.security_service import encrypt_value, decrypt_value

        assert encrypt_value("") == ""
        assert decrypt_value("") == ""


# ──────────────────────────────────────────────
# Health endpoint
# ──────────────────────────────────────────────

def test_health_endpoint_returns_ok(client):
    """GET /health must return 200 with status=ok."""
    login(client, "admin", "admin-pass")
    response = client.get("/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"
    assert data["db"] is True


def test_health_endpoint_accessible_without_login(client):
    """Health endpoint must not require authentication."""
    response = client.get("/health")
    assert response.status_code == 200


# ──────────────────────────────────────────────
# Input validation (APP-002)
# ──────────────────────────────────────────────

def test_invalid_party_type_param_returns_redirect_not_500(client):
    """GET /parties/?type=invalid must redirect gracefully, not 500."""
    login(client, "admin", "admin-pass")
    response = client.get("/parties/?type=invalid_value")
    # Should redirect (302) or return a flash warning page (200), never 500
    assert response.status_code in (200, 302)


def test_parties_list_all_types_render(client):
    """Each valid party type filter must render without error."""
    login(client, "admin", "admin-pass")
    for ptype in ("patient", "dentist_customer", "company_customer", ""):
        url = f"/parties/?type={ptype}" if ptype else "/parties/"
        resp = client.get(url)
        assert resp.status_code == 200, f"Failed for type={ptype!r}"


def test_roles_required_redirects_anonymous_user(app):
    from app.authz import roles_required

    protected = roles_required("admin")(lambda: "allowed")
    with app.test_request_context("/protected"):
        response = protected()

    assert response.status_code == 302
    assert response.location.endswith("/login")


def test_roles_required_rejects_wrong_role(app):
    from app.authz import roles_required

    user = type("User", (), {"is_authenticated": True, "role": "staff"})()
    protected = roles_required("admin")(lambda: "allowed")
    with app.test_request_context("/protected"), patch("app.authz.current_user", user):
        response = protected()

    assert response.status_code == 302
    assert response.location.endswith("/")


def test_roles_required_allows_matching_role(app):
    from app.authz import roles_required

    user = type("User", (), {"is_authenticated": True, "role": "admin"})()
    protected = roles_required("admin")(lambda: "allowed")
    with app.test_request_context("/protected"), patch("app.authz.current_user", user):
        assert protected() == "allowed"


def test_force_hsts_and_request_id_headers(app):
    app.config["FORCE_HSTS"] = True
    client = app.test_client()

    response = client.get("/health", headers={"X-Request-ID": "review-request"})

    assert response.headers["X-Request-ID"] == "review-request"
    assert response.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"
