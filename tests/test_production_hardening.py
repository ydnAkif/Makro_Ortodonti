from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.models.models import AuditLog, Invoice, Party, PartyType
from conftest import login


def test_mutation_creates_actor_and_request_correlated_audit_log(client, app):
    login(client, "admin", "admin-pass")
    with app.app_context():
        party = db.session.execute(db.select(Party).where(Party.party_type == PartyType.DENTIST)).scalar_one()
        party_id = party.id

    response = client.post(
        f"/parties/{party_id}/edit",
        headers={"X-Request-ID": "audit-correlation-test"},
        data={
            "party_type": "dentist", "name": "Denetimli Hekim",
            "phone": "5551112233", "is_active": "on",
        },
    )
    assert response.status_code == 302
    with app.app_context():
        row = db.session.execute(
            db.select(AuditLog).where(
                AuditLog.entity_type == "Party",
                AuditLog.request_id == "audit-correlation-test",
            ).order_by(AuditLog.id.desc())
        ).scalars().first()
        assert row is not None
        assert row.actor_username == "admin"
        assert row.action == "update"
        assert "name" in row.changes_json


def test_security_headers_and_request_id_are_present(client):
    response = client.get("/health", headers={"X-Request-ID": "health-correlation"})
    assert response.headers["X-Request-ID"] == "health-correlation"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_kvkk_export_is_admin_only_and_contains_financial_record(client, app):
    login(client, "admin", "admin-pass")
    with app.app_context():
        party_id = db.session.execute(db.select(Party).where(Party.party_type == PartyType.DENTIST)).scalar_one().id
    response = client.get(f"/privacy/parties/{party_id}/export")
    assert response.status_code == 200
    assert response.mimetype == "application/json"
    assert response.get_json()["party"]["id"] == party_id


def test_whatsapp_connected_send_formats_jid(monkeypatch, app):
    from app.services.whatsapp_service import WhatsAppService

    class Client:
        sent = None
        def send_message(self, jid, message):
            self.sent = (jid, message)

    fake = Client()
    monkeypatch.setattr(WhatsAppService, "_connected", True)
    monkeypatch.setattr(WhatsAppService, "_client", fake)
    with app.app_context():
        result = WhatsAppService.send_message("+90 555-111-22-33", "Merhaba")
    assert result["success"] is True
    jid, message = fake.sent
    assert jid.User == "905551112233"
    assert jid.Server == "s.whatsapp.net"
    assert message == "Merhaba"


def test_email_success_path_uses_tls_login_and_pdf(monkeypatch, app):
    from app.services import email_service

    class SMTP:
        sent = False
        def __init__(self, host, port):
            assert (host, port) == ("smtp.test", 587)
        def starttls(self): pass
        def login(self, username, password): assert (username, password) == ("u@test", "secret")
        def send_message(self, _message): self.sent = True
        def quit(self): pass

    monkeypatch.setattr(email_service, "get_smtp_config", lambda: {
        "smtp_server": "smtp.test", "smtp_port": "587",
        "smtp_username": "u@test", "smtp_password": "secret",
    })
    monkeypatch.setattr("app.services.pdf_service.generate_invoice_pdf", lambda _invoice: b"%PDF-test")
    monkeypatch.setattr(email_service.smtplib, "SMTP", SMTP)
    with app.app_context():
        invoice = db.session.execute(db.select(Invoice).limit(1)).scalar_one_or_none()
        if invoice is None:
            party = db.session.execute(db.select(Party).where(Party.party_type == PartyType.DENTIST)).scalar_one()
            party.email = "patient@test"
            invoice = Invoice(
                party=party, invoice_number="TEST-EMAIL", invoice_date=__import__("datetime").date.today(),
                total_eur=Decimal("10.00"), total_try=Decimal("400.00"),
                exchange_rate=Decimal("40.0000"), status="pending",
            )
            db.session.add(invoice)
            db.session.commit()
        else:
            invoice.party.email = "patient@test"
        ok, message = email_service.send_invoice_email(invoice)
    assert ok is True
    assert "başarıyla" in message
