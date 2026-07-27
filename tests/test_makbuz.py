from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from app.extensions import db
from app.models.models import Party, PartyType, WorkOrder, Makbuz, MakbuzPayment, PartyPayment

from conftest import login


def _make_doctor(app, name="Dr. Test Makbuz", phone="+905551110099"):
    with app.app_context():
        party = Party(party_type=PartyType.DENTIST, name=name, phone=phone)
        db.session.add(party)
        db.session.commit()
        return party.id


def _add_work_order(app, party_id, work_date, apparatus_price, extra_price=0):
    with app.app_context():
        wo = WorkOrder(
            party_id=party_id, work_date=work_date, apparatus_type="Nance",
            patient_name="Test Hasta", apparatus_price=apparatus_price,
            extra_price=extra_price, total_price=apparatus_price + extra_price,
        )
        db.session.add(wo)
        db.session.commit()
        return wo.id


def test_list_makbuzlar_aggregates_per_doctor(client, app):
    login(client, "admin", "admin-pass")
    party_id = _make_doctor(app)
    _add_work_order(app, party_id, date(2026, 6, 10), 1000, extra_price=200)
    _add_work_order(app, party_id, date(2026, 6, 20), 500)

    response = client.get("/makbuzlar/?year=2026&month=6")
    assert response.status_code == 200
    assert "Dr. Test Makbuz".encode() in response.data

    # Doctors without work orders in the period are not listed
    empty = client.get("/makbuzlar/?year=2020&month=1")
    assert empty.status_code == 200
    assert "Dr. Test Makbuz".encode() not in empty.data


def test_edit_work_order_route(client, app):
    login(client, "admin", "admin-pass")
    party_id = _make_doctor(app, name="Dr. WO Edit", phone="+905551110098")
    wo_id = _add_work_order(app, party_id, date(2026, 6, 10), 1000)

    response = client.get(f"/parties/{party_id}/work-orders/{wo_id}/edit")
    assert response.status_code == 200

    response = client.post(
        f"/parties/{party_id}/work-orders/{wo_id}/edit",
        data={"work_date": "gecersiz-tarih"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    response = client.post(
        f"/parties/{party_id}/work-orders/{wo_id}/edit",
        data={
            "work_date": "2026-06-15",
            "apparatus_type": "Hyrax",
            "patient_name": "yENİ hASTA",
            "apparatus_price": "1500",
            "extra_price": "100",
            "exchange_rate_applied": "40",
            "notes": "güncellendi",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    with app.app_context():
        wo = db.session.get(WorkOrder, wo_id)
        assert wo.apparatus_type == "Hyrax"
        assert wo.patient_name == "Yeni Hasta"
        assert float(wo.total_price) == 1600.0


def test_work_orders_are_listed_newest_first_with_same_date_tiebreaker(client, app):
    login(client, "admin", "admin-pass")
    party_id = _make_doctor(app, name="Dr. Sıralama", phone="+905551110097")
    first_id = _add_work_order(app, party_id, date(2026, 6, 10), 1000)
    second_id = _add_work_order(app, party_id, date(2026, 6, 10), 1200)
    with app.app_context():
        db.session.get(WorkOrder, first_id).patient_name = "Aynı Gün İlk Kayıt"
        db.session.get(WorkOrder, second_id).patient_name = "Aynı Gün Son Kayıt"
        db.session.commit()

    html = client.get(f"/parties/{party_id}?year=2026&month=6").get_data(as_text=True)
    assert html.index("Aynı Gün Son Kayıt") < html.index("Aynı Gün İlk Kayıt")

    filtered_html = client.get(
        f"/parties/{party_id}?year=2026&month=6&search=son+kayit"
    ).get_data(as_text=True)
    assert "Aynı Gün Son Kayıt" in filtered_html
    assert "Aynı Gün İlk Kayıt" not in filtered_html


def test_generate_makbuz_computes_vat(client, app):
    login(client, "admin", "admin-pass")
    party_id = _make_doctor(app)
    _add_work_order(app, party_id, date(2026, 6, 10), 1000)
    _add_work_order(app, party_id, date(2026, 6, 20), 500)

    response = client.post(
        f"/makbuzlar/{party_id}/generate",
        data={"year": 2026, "month": 6, "vat_applied": "on", "vat_rate": "99"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        makbuz = db.session.execute(
            db.select(Makbuz).where(Makbuz.party_id == party_id, Makbuz.year == 2026, Makbuz.month == 6)
        ).scalar_one()
        assert makbuz.status == Makbuz.STATUS_DRAFT
        assert makbuz.work_order_count == 2
        assert makbuz.subtotal == Decimal("1500.00")
        assert makbuz.vat_rate == Decimal("10.00")
        assert makbuz.vat_amount == Decimal("150.00")
        assert makbuz.grand_total == Decimal("1650.00")


def test_adding_work_order_creates_draft_makbuz(client, app):
    login(client, "admin", "admin-pass")
    party_id = _make_doctor(app, name="Dr. Auto Makbuz")

    response = client.post(
        f"/parties/{party_id}/work-orders/add",
        data={
            "work_date": "2026-06-15",
            "apparatus_type": "Nance",
            "patient_name": "Test Hasta",
            "apparatus_price": "1000",
            "extra_price": "200",
            "notes": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        makbuz = db.session.execute(
            db.select(Makbuz).where(Makbuz.party_id == party_id, Makbuz.year == 2026, Makbuz.month == 6)
        ).scalar_one()
        assert makbuz.status == Makbuz.STATUS_DRAFT
        assert makbuz.work_order_count == 1
        assert makbuz.subtotal == Decimal("1200.00")


def test_party_detail_reflects_persisted_receipt_vat_and_formats_phone(client, app):
    login(client, "admin", "admin-pass")
    party_id = _make_doctor(
        app, name="Dr. KDV Özeti", phone="+905337694469"
    )
    with app.app_context():
        db.session.get(Party, party_id).previous_balance = Decimal("320.00")
        db.session.commit()
    _add_work_order(app, party_id, date(2026, 6, 10), 1000)
    client.post(
        f"/makbuzlar/{party_id}/generate",
        data={"year": 2026, "month": 6, "vat_applied": "on", "vat_rate": "99"},
        follow_redirects=False,
    )

    html = client.get(f"/parties/{party_id}?year=2026&month=6").get_data(as_text=True)
    assert "+90 533 769 44 69" in html
    # Label and amount render in separate <span> elements, not one string.
    assert html.count("KDV (aylık özetler):") == 2
    assert html.count("₺100.00") >= 2
    assert "₺1,100.00" in html
    assert html.count("₺1,420.00") >= 2

    year_html = client.get(
        f"/parties/{party_id}?view=year&year=2026"
    ).get_data(as_text=True)
    # Aylık satır ile yıl toplamı aynı KDV dahil tutarı göstermeli.
    assert year_html.count("₺1,100.00") >= 2


def test_generate_makbuz_without_vat(client, app):
    login(client, "admin", "admin-pass")
    party_id = _make_doctor(app, name="Dr. No VAT")
    _add_work_order(app, party_id, date(2026, 6, 5), 750)

    client.post(
        f"/makbuzlar/{party_id}/generate",
        data={"year": 2026, "month": 6},
        follow_redirects=False,
    )

    with app.app_context():
        makbuz = db.session.execute(
            db.select(Makbuz).where(Makbuz.party_id == party_id)
        ).scalar_one()
        assert makbuz.vat_applied is False
        assert makbuz.vat_amount == Decimal("0.00")
        assert makbuz.grand_total == Decimal("750.00")


def test_makbuz_pdf_preview_and_download(client, app):
    login(client, "admin", "admin-pass")
    party_id = _make_doctor(app, name="Dr. PDF Önizleme")
    _add_work_order(app, party_id, date(2026, 6, 12), 1200, extra_price=300)
    client.post(f"/makbuzlar/{party_id}/generate", data={"year": 2026, "month": 6}, follow_redirects=False)

    with app.app_context():
        makbuz_id = db.session.execute(
            db.select(Makbuz.id).where(Makbuz.party_id == party_id)
        ).scalar_one()

    response = client.get(f"/makbuzlar/{makbuz_id}/pdf")
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/pdf"
    assert "inline" in response.headers["Content-Disposition"]
    assert response.data.startswith(b"%PDF")

    response = client.get(f"/makbuzlar/{makbuz_id}/pdf?download=1")
    assert response.status_code == 200
    assert "attachment" in response.headers["Content-Disposition"]
    assert f"aylik_hesap_ozeti_2026_06_{party_id}.pdf" in response.headers["Content-Disposition"]


def test_can_update_sent_makbuz(client, app):
    login(client, "admin", "admin-pass")
    party_id = _make_doctor(app, name="Dr. Lock Test")
    _add_work_order(app, party_id, date(2026, 6, 1), 1000)
    client.post(f"/makbuzlar/{party_id}/generate", data={"year": 2026, "month": 6}, follow_redirects=False)

    with app.app_context():
        makbuz = db.session.execute(db.select(Makbuz).where(Makbuz.party_id == party_id)).scalar_one()
        makbuz.status = Makbuz.STATUS_SENT
        db.session.commit()

    # Sent makbuzlar can be regenerated/updated when new work orders are added.
    _add_work_order(app, party_id, date(2026, 6, 15), 5000)
    response = client.post(
        f"/makbuzlar/{party_id}/generate",
        data={"year": 2026, "month": 6},
        follow_redirects=True,
    )
    assert response.status_code == 200

    with app.app_context():
        makbuz = db.session.execute(db.select(Makbuz).where(Makbuz.party_id == party_id)).scalar_one()
        assert makbuz.subtotal == Decimal("6000.00")


def test_send_and_mark_paid_flow(client, app):
    login(client, "admin", "admin-pass")
    party_id = _make_doctor(app, name="Dr. Paid Flow")
    _add_work_order(app, party_id, date(2026, 6, 1), 2000)
    client.post(f"/makbuzlar/{party_id}/generate", data={"year": 2026, "month": 6}, follow_redirects=False)

    with app.app_context():
        makbuz_id = db.session.execute(db.select(Makbuz).where(Makbuz.party_id == party_id)).scalar_one().id

    with patch("app.services.whatsapp_service.WhatsAppService.send_makbuz_message", return_value={"success": True, "message": "ok"}):
        response = client.post(f"/makbuzlar/{makbuz_id}/send", follow_redirects=False)
        assert response.status_code == 302

    with app.app_context():
        assert db.session.get(Makbuz, makbuz_id).status == Makbuz.STATUS_SENT

    payments_html = client.get("/payments/").get_data(as_text=True)
    assert "Dr. Paid Flow" in payments_html
    assert "Ödeme Bekleyen Dönemler" in payments_html

    response = client.post(
        f"/payments/{makbuz_id}/mark-paid",
        data={"paid_at": date.today().isoformat(), "paid_amount": "2000.00", "payment_method": "cash"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "tab=paid" in response.location

    with app.app_context():
        makbuz = db.session.get(Makbuz, makbuz_id)
        assert makbuz.status == Makbuz.STATUS_PAID
        assert makbuz.paid_amount == Decimal("2000.00")

    response = client.get("/payments/")
    assert response.status_code == 200
    paid_html = response.get_data(as_text=True)
    assert "Dr. Paid Flow" in paid_html
    assert "Tahsil edilenler" in paid_html
    assert f"/payments/{makbuz_id}/unmark-paid" in paid_html

    response = client.post(f"/payments/{makbuz_id}/unmark-paid", follow_redirects=False)
    assert response.status_code == 302
    with app.app_context():
        makbuz = db.session.get(Makbuz, makbuz_id)
        assert makbuz.status == Makbuz.STATUS_SENT
        assert makbuz.paid_amount is None


def test_partial_payment_stays_open_and_carries_to_next_period(client, app):
    login(client, "admin", "admin-pass")
    party_id = _make_doctor(app, name="Dr. Kısmi Tahsilat")
    _add_work_order(app, party_id, date(2026, 6, 1), Decimal("2641.52"))
    client.post(f"/makbuzlar/{party_id}/generate", data={"year": 2026, "month": 6})

    with app.app_context():
        june = db.session.execute(
            db.select(Makbuz).where(Makbuz.party_id == party_id, Makbuz.month == 6)
        ).scalar_one()
        june.status = Makbuz.STATUS_SENT
        june.sent_at = datetime.now().astimezone()
        june_id = june.id
        db.session.commit()

    response = client.post(
        f"/payments/{june_id}/mark-paid",
        data={
            "paid_at": "2026-07-05",
            "paid_amount": "2500.00",
            "payment_method": "transfer",
            "payment_reference": "EFT-123",
            "notes": "Kısmi tahsilat",
        },
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    assert "Kısmi ödeme kaydedildi" in html
    assert "141.52" in html

    with app.app_context():
        june = db.session.get(Makbuz, june_id)
        assert june.status == Makbuz.STATUS_SENT
        assert june.collected_amount == Decimal("2500.00")
        assert june.outstanding_amount == Decimal("141.52")
        payment = db.session.execute(
            db.select(MakbuzPayment).where(MakbuzPayment.makbuz_id == june_id)
        ).scalar_one()
        assert payment.reference == "EFT-123"

    _add_work_order(app, party_id, date(2026, 7, 1), Decimal("100.00"))
    client.post(f"/makbuzlar/{party_id}/generate", data={"year": 2026, "month": 7})

    with app.app_context():
        from app.services.makbuz_account_service import account_statement

        july = db.session.execute(
            db.select(Makbuz).where(Makbuz.party_id == party_id, Makbuz.month == 7)
        ).scalar_one()
        statement = account_statement(july)
        assert statement.previous_balance == Decimal("141.52")
        assert statement.previous_periods[0].period_label == "Haziran 2026"
        assert statement.previous_periods[0].original_total == Decimal("2641.52")
        assert statement.previous_periods[0].collected == Decimal("2500.00")
        assert statement.total_due == Decimal("241.52")

        from app.services.whatsapp_service import WhatsAppService

        with (
            patch.object(WhatsAppService, "send_message", return_value={"success": True, "message": "ok"}) as send_text,
            patch.object(WhatsAppService, "send_document", return_value={"success": True, "message": "ok"}),
        ):
            WhatsAppService.send_makbuz_message(july, b"pdf")
        message = send_text.call_args.args[1]
        assert "Haziran 2026: ₺2,641.52 hesap özeti - ₺2,500.00 tahsilat = ₺141.52 kalan" in message
        assert "TOPLAM ÖDENECEK BAKİYE: ₺241.52" in message

    response = client.post(
        f"/payments/{june_id}/mark-paid",
        data={
            "paid_at": "2026-07-10",
            "paid_amount": "141.52",
            "payment_method": "cash",
        },
        follow_redirects=False,
    )
    assert "tab=paid" in response.location
    with app.app_context():
        june = db.session.get(Makbuz, june_id)
        assert june.status == Makbuz.STATUS_PAID
        assert june.collected_amount == Decimal("2641.52")
        assert june.outstanding_amount == Decimal("0.00")
        assert len(june.payment_entries) == 2


def test_payment_cannot_exceed_remaining_balance(client, app):
    login(client, "admin", "admin-pass")
    party_id = _make_doctor(app, name="Dr. Fazla Tahsilat")
    _add_work_order(app, party_id, date(2026, 6, 1), Decimal("100.00"))
    client.post(f"/makbuzlar/{party_id}/generate", data={"year": 2026, "month": 6})

    with app.app_context():
        makbuz = db.session.execute(
            db.select(Makbuz).where(Makbuz.party_id == party_id)
        ).scalar_one()
        makbuz.status = Makbuz.STATUS_SENT
        makbuz.sent_at = datetime.now().astimezone()
        makbuz_id = makbuz.id
        db.session.commit()

    response = client.post(
        f"/payments/{makbuz_id}/mark-paid",
        data={"paid_amount": "100.01", "payment_method": "cash"},
        follow_redirects=True,
    )
    assert "bakiyeyi aşamaz" in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(MakbuzPayment.id))) == 0


def test_send_failure_keeps_status(client, app):
    login(client, "admin", "admin-pass")
    party_id = _make_doctor(app, name="Dr. Send Fail")
    _add_work_order(app, party_id, date(2026, 6, 1), 500)
    client.post(f"/makbuzlar/{party_id}/generate", data={"year": 2026, "month": 6}, follow_redirects=False)

    with app.app_context():
        makbuz_id = db.session.execute(db.select(Makbuz).where(Makbuz.party_id == party_id)).scalar_one().id

    with patch("app.services.whatsapp_service.WhatsAppService.send_makbuz_message", return_value={"success": False, "message": "WhatsApp bağlı değil."}):
        client.post(f"/makbuzlar/{makbuz_id}/send", follow_redirects=False)

    with app.app_context():
        assert db.session.get(Makbuz, makbuz_id).status == Makbuz.STATUS_DRAFT


def test_bulk_generate_creates_drafts_without_sending(client, app):
    login(client, "admin", "admin-pass")
    p1 = _make_doctor(app, name="Dr. Bulk One", phone="+905551110001")
    p2 = _make_doctor(app, name="Dr. Bulk Two", phone="+905551110002")
    _add_work_order(app, p1, date(2026, 6, 3), 1000)
    _add_work_order(app, p2, date(2026, 6, 4), 2000)

    with patch("app.services.whatsapp_service.WhatsAppService.send_makbuz_message") as mock_send:
        response = client.post(
            "/makbuzlar/bulk-generate",
            data={
                "year": 2026, "month": 6,
                "party_ids": [str(p1), str(p2)],
                f"vat_{p1}_vat_applied": "on",
                f"vat_{p1}_vat_rate": "10",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        mock_send.assert_not_called()

    with app.app_context():
        m1 = db.session.execute(db.select(Makbuz).where(Makbuz.party_id == p1)).scalar_one()
        m2 = db.session.execute(db.select(Makbuz).where(Makbuz.party_id == p2)).scalar_one()
        assert m1.status == Makbuz.STATUS_DRAFT
        assert m1.vat_applied is True
        assert m1.grand_total == Decimal("1100.00")
        assert m2.status == Makbuz.STATUS_DRAFT
        assert m2.vat_applied is False

    list_html = client.get("/makbuzlar/?year=2026&month=6").get_data(as_text=True)
    p1_vat_control = list_html.split(f'id="vat-{p1}"', 1)[1].split(">", 1)[0]
    p2_vat_control = list_html.split(f'id="vat-{p2}"', 1)[1].split(">", 1)[0]
    assert "checked" in p1_vat_control
    assert "checked" not in p2_vat_control
    assert f'name="vat_{p1}_vat_rate" value="10.00"' in list_html
    assert "₺3,100.00" in list_html
    assert "Seçilenleri WhatsApp'tan gönder" in list_html
    assert list_html.count("Seçilenleri WhatsApp'tan gönder") == 1


def test_bulk_send_uses_selected_doctors_ready_drafts(client, app):
    from app.services.makbuz_send_queue import MakbuzSendQueue

    login(client, "admin", "admin-pass")
    p1 = _make_doctor(app, name="Dr. Send One", phone="+905551110041")
    p2 = _make_doctor(app, name="Dr. Send Two", phone="+905551110042")
    p3 = _make_doctor(app, name="Dr. No Draft", phone="+905551110043")
    for party_id in (p1, p2, p3):
        _add_work_order(app, party_id, date(2026, 6, 8), 500)
    for party_id in (p1, p2):
        client.post(
            f"/makbuzlar/{party_id}/generate",
            data={"year": 2026, "month": 6},
            follow_redirects=False,
        )

    with app.app_context():
        expected_ids = db.session.execute(
            db.select(Makbuz.id)
            .where(Makbuz.party_id.in_([p1, p2]))
            .order_by(Makbuz.id)
        ).scalars().all()

    with patch.object(
        MakbuzSendQueue,
        "start_batch",
        return_value=(True, "2 makbuz için gönderim başlatıldı."),
    ) as start_batch:
        response = client.post(
            "/makbuzlar/bulk-send",
            data={
                "year": "2026",
                "month": "6",
                "party_ids": [str(p1), str(p2), str(p3)],
            },
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert "sending=1" in response.location
    start_batch.assert_called_once()
    assert sorted(start_batch.call_args.args[0]) == expected_ids


def test_makbuz_list_send_returns_to_list_and_exposes_collection_action(client, app):
    login(client, "admin", "admin-pass")
    party_id = _make_doctor(app, name="Dr. List Send", phone="+905551110033")
    _add_work_order(app, party_id, date(2026, 6, 7), 1200)
    client.post(
        f"/makbuzlar/{party_id}/generate",
        data={"year": 2026, "month": 6},
        follow_redirects=False,
    )

    with app.app_context():
        makbuz_id = db.session.execute(
            db.select(Makbuz.id).where(Makbuz.party_id == party_id)
        ).scalar_one()

    with patch(
        "app.services.whatsapp_service.WhatsAppService.send_makbuz_message",
        return_value={"success": True, "message": "ok"},
    ):
        response = client.post(
            f"/makbuzlar/{makbuz_id}/send",
            data={"return_to": "list"},
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert "/makbuzlar/?year=2026&month=6" in response.location
    html = client.get(response.location).get_data(as_text=True)
    assert "Tahsilat bekliyor" in html
    assert f"/payments/{makbuz_id}/mark-paid" in html


def test_scheduler_generates_previous_month_drafts_once(app):
    from app.services.scheduler_service import _generate_monthly_drafts, _previous_month

    party_id = _make_doctor(app, name="Dr. Scheduler")
    _add_work_order(app, party_id, date(2026, 6, 12), 900)

    assert _previous_month(date(2026, 7, 1)) == (2026, 6)

    import app.services.scheduler_service as sched

    class FixedDate(date):
        @classmethod
        def today(cls):
            return date(2026, 7, 1)

    original_date = sched.date
    sched.date = FixedDate
    try:
        _generate_monthly_drafts(app)
        with app.app_context():
            rows = db.session.execute(db.select(Makbuz).where(Makbuz.party_id == party_id)).scalars().all()
            assert len(rows) == 1
            assert rows[0].subtotal == Decimal("900.00")

        # Second call the same day must not duplicate the draft (atomic run-guard).
        _generate_monthly_drafts(app)
        with app.app_context():
            rows = db.session.execute(db.select(Makbuz).where(Makbuz.party_id == party_id)).scalars().all()
            assert len(rows) == 1
    finally:
        sched.date = original_date


def test_scheduler_noop_when_not_first_of_month(app):
    from app.services.scheduler_service import _generate_monthly_drafts

    party_id = _make_doctor(app, name="Dr. Scheduler NoOp")
    _add_work_order(app, party_id, date(2026, 6, 12), 900)

    import app.services.scheduler_service as sched

    class FixedDate(date):
        @classmethod
        def today(cls):
            return date(2026, 7, 15)

    original_date = sched.date
    sched.date = FixedDate
    try:
        _generate_monthly_drafts(app)
        with app.app_context():
            count = db.session.execute(
                db.select(db.func.count(Makbuz.id)).where(Makbuz.party_id == party_id)
            ).scalar_one()
            assert count == 0
    finally:
        sched.date = original_date


def test_makbuz_detail_renders_catalog_item_names_not_raw_json(client, app):
    """apparatus_type/extra_addons store a JSON catalog selection; the page
    must show item names, not the raw JSON (regression: was displayed as-is)."""
    login(client, "admin", "admin-pass")
    party_id = _make_doctor(app, name="Fatma Aydın")
    apparatus = json.dumps([{"id": 31, "name": "Activator (FKO)", "price": 2500, "currency": "TL"}])
    extra = json.dumps([{"id": 49, "name": "Lingual Sheat", "price": 4, "currency": "USD"}])
    with app.app_context():
        db.session.add(WorkOrder(
            party_id=party_id, work_date=date(2026, 7, 20), apparatus_type=apparatus,
            extra_addons=extra, patient_name="Fatma Aydın",
            apparatus_price=2500, extra_price=Decimal("188.57"), total_price=Decimal("2688.57"),
        ))
        db.session.commit()

    response = client.get(f"/makbuzlar/{party_id}?year=2026&month=7")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '[{"id"' not in html
    assert "Activator (FKO)" in html
    assert "Lingual Sheat" in html

    response = client.get("/")
    html = response.get_data(as_text=True)
    assert '[{"id"' not in html
    assert "Activator (FKO)" in html


def test_format_items_parses_catalog_json_and_falls_back_to_plain_text():
    from app.services.makbuz_pdf_service import _format_items

    catalog_json = json.dumps([{"id": 31, "name": "Activator (FKO)", "price": 2500, "currency": "TL"}])
    assert _format_items(catalog_json) == "Activator (FKO) (₺2,500.00)"

    multi_json = json.dumps([
        {"id": 1, "name": "A", "price": 10, "currency": "USD"},
        {"id": 2, "name": "B", "price": 20, "currency": "TL"},
    ])
    assert _format_items(multi_json) == "A ($10.00), B (₺20.00)"

    assert _format_items("Lingual Ark") == "Lingual Ark"
    assert _format_items(None) == ""
    assert _format_items("") == ""


def test_whatsapp_message_includes_party_carried_forward_balance(app):
    from app.services.whatsapp_service import WhatsAppService

    party_id = _make_doctor(app, name="Dr. WhatsApp Devreden")
    with app.app_context():
        party = db.session.get(Party, party_id)
        party.previous_balance = Decimal("125.50")

        makbuz = Makbuz(
            party_id=party_id,
            year=2026,
            month=7,
            work_order_count=1,
            subtotal=Decimal("1500.00"),
            generated_at=datetime.now(),
        )
        makbuz.recalculate_totals()
        db.session.add(makbuz)
        db.session.commit()

        with (
            patch.object(WhatsAppService, "send_message", return_value={"success": True, "message": "ok"}) as send_text,
            patch.object(WhatsAppService, "send_document", return_value={"success": True, "message": "ok"}),
        ):
            WhatsAppService.send_makbuz_message(makbuz, b"pdf")

        message = send_text.call_args.args[1]
        assert "Devreden Borç: ₺125.50" in message


def test_makbuz_pdf_generation_does_not_crash_with_catalog_json(app):
    from app.services.makbuz_pdf_service import generate_makbuz_pdf

    party_id = _make_doctor(app, name="Fatma Aydın PDF")
    apparatus = json.dumps([{"id": 31, "name": "Activator (FKO)", "price": 2500, "currency": "TL"}])
    with app.app_context():
        wo = WorkOrder(
            party_id=party_id, work_date=date(2026, 7, 20), apparatus_type=apparatus,
            patient_name="Fatma Aydın", apparatus_price=2500, extra_price=0, total_price=2500,
        )
        db.session.add(wo)
        makbuz = Makbuz(
            party_id=party_id, year=2026, month=7, work_order_count=1,
            subtotal=Decimal("2500.00"), generated_at=datetime.now(),
        )
        makbuz.recalculate_totals()
        db.session.add(makbuz)
        db.session.commit()

        pdf_bytes = generate_makbuz_pdf(makbuz, [wo])
        assert pdf_bytes[:4] == b"%PDF"
        assert len(pdf_bytes) > 1000


def test_makbuz_pdf_includes_previous_balance_line(app):
    from app.services.makbuz_pdf_service import generate_makbuz_pdf, MakbuzPDF

    party_id = _make_doctor(app, name="Dr. Önceki Borç")
    with app.app_context():
        party = db.session.get(Party, party_id)
        party.previous_balance = Decimal("125.50")

        prior = Makbuz(
            party_id=party_id, year=2026, month=6, work_order_count=1,
            subtotal=Decimal("1000.00"), grand_total=Decimal("1000.00"),
            status=Makbuz.STATUS_SENT, generated_at=datetime.now(), sent_at=datetime.now(),
        )
        prior.recalculate_totals()
        db.session.add(prior)
        db.session.flush()

        current = Makbuz(
            party_id=party_id, year=2026, month=7, work_order_count=1,
            subtotal=Decimal("1500.00"), generated_at=datetime.now(),
        )
        current.recalculate_totals()
        db.session.add(current)
        db.session.commit()

        previous_payment = MakbuzPayment(makbuz=prior, payment_date=date(2026, 6, 20), amount=Decimal("200.00"), method="cash")
        db.session.add(previous_payment)
        db.session.commit()

        rendered_texts: list[str] = []
        _orig_cell = MakbuzPDF.cell

        def _capture_cell(self, w=0, h=0, text="", *args, **kwargs):
            rendered_texts.append(str(text))
            return _orig_cell(self, w, h, text, *args, **kwargs)

        with patch.object(MakbuzPDF, "cell", _capture_cell):
            pdf_bytes = generate_makbuz_pdf(current, [])

        assert pdf_bytes[:4] == b"%PDF"
        joined = " ".join(rendered_texts)
        assert "Devreden borç" in joined or "Devreden borc" in joined


# ---------------------------------------------------------------------------
# Migrated from test_makbuz_fixes.py
# ---------------------------------------------------------------------------


def _make_doctor_fix(app, name="Dr. Fix Test", phone="+905559990033"):
    with app.app_context():
        party = Party(party_type=PartyType.DENTIST, name=name, phone=phone)
        db.session.add(party)
        db.session.commit()
        return party.id


def test_send_makbuz_preserves_paid_status(app, monkeypatch):
    from app.services.makbuz_send_queue import send_makbuz_via_whatsapp
    from app.services.whatsapp_service import WhatsAppService

    monkeypatch.setattr(
        WhatsAppService,
        "send_makbuz_message",
        lambda makbuz, pdf_bytes: {"success": True, "message": "Gönderildi"}
    )

    party_id = _make_doctor_fix(app)
    with app.app_context():
        makbuz = Makbuz(
            party_id=party_id,
            year=2026,
            month=6,
            work_order_count=1,
            subtotal=Decimal("100.00"),
            vat_applied=False,
            vat_rate=Decimal("0.00"),
            status=Makbuz.STATUS_PAID,
            paid_at=date(2026, 6, 20),
            paid_amount=Decimal("100.00"),
            generated_at=datetime.now().astimezone(),
        )
        makbuz.recalculate_totals()
        db.session.add(makbuz)
        db.session.commit()
        makbuz_id = makbuz.id

    with app.app_context():
        ok, msg = send_makbuz_via_whatsapp(makbuz_id)
        assert ok is True

        m = db.session.get(Makbuz, makbuz_id)
        assert m.status == Makbuz.STATUS_PAID
        assert m.sent_at is not None


def test_unmark_paid_status_logic(client, app):
    login(client, "admin", "admin-pass")
    party_id = _make_doctor_fix(app)

    with app.app_context():
        m1 = Makbuz(
            party_id=party_id,
            year=2026,
            month=5,
            work_order_count=1,
            subtotal=Decimal("200.00"),
            status=Makbuz.STATUS_PAID,
            sent_at=datetime.now().astimezone(),
            paid_at=date(2026, 5, 10),
            paid_amount=Decimal("200.00"),
            generated_at=datetime.now().astimezone(),
        )
        m1.recalculate_totals()
        db.session.add(m1)

        m2 = Makbuz(
            party_id=party_id,
            year=2026,
            month=4,
            work_order_count=1,
            subtotal=Decimal("300.00"),
            status=Makbuz.STATUS_PAID,
            sent_at=None,
            paid_at=date(2026, 4, 10),
            paid_amount=Decimal("300.00"),
            generated_at=datetime.now().astimezone(),
        )
        m2.recalculate_totals()
        db.session.add(m2)
        db.session.commit()
        m1_id, m2_id = m1.id, m2.id

    res1 = client.post(f"/payments/{m1_id}/unmark-paid", follow_redirects=True)
    assert res1.status_code == 200

    res2 = client.post(f"/payments/{m2_id}/unmark-paid", follow_redirects=True)
    assert res2.status_code == 200

    with app.app_context():
        m1_db = db.session.get(Makbuz, m1_id)
        assert m1_db.status == Makbuz.STATUS_SENT

        m2_db = db.session.get(Makbuz, m2_id)
        assert m2_db.status == Makbuz.STATUS_DRAFT


def test_list_makbuzlar_includes_orphan_makbuz(client, app):
    login(client, "admin", "admin-pass")
    party_id = _make_doctor_fix(app, name="Dr. Orphan Test")

    with app.app_context():
        makbuz = Makbuz(
            party_id=party_id,
            year=2026,
            month=3,
            work_order_count=1,
            subtotal=Decimal("500.00"),
            status=Makbuz.STATUS_SENT,
            generated_at=datetime.now().astimezone(),
        )
        makbuz.recalculate_totals()
        db.session.add(makbuz)
        db.session.commit()

    response = client.get("/makbuzlar/?year=2026&month=3")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Dr. Orphan Test" in html
    assert "500.00" in html


def test_overpayment_does_not_double_deduct_outstanding(client, app):
    login(client, "admin", "admin-pass")
    with app.app_context():
        p = Party(party_type=PartyType.DENTIST, name="Dr. Overpay Test", phone="+905559998877", previous_balance=Decimal("1000.00"))
        db.session.add(p)
        db.session.commit()
        party_id = p.id

    _add_work_order(app, party_id, date(2026, 7, 1), 1320)
    client.post(f"/makbuzlar/{party_id}/generate", data={"year": 2026, "month": 7}, follow_redirects=False)

    with app.app_context():
        m = db.session.execute(db.select(Makbuz).where(Makbuz.party_id == party_id, Makbuz.year == 2026, Makbuz.month == 7)).scalar_one()
        m.status = Makbuz.STATUS_SENT
        mid = m.id

        from app.services.makbuz_account_service import record_payment
        record_payment(m, payment_date=date(2026, 7, 27), amount=Decimal("2000.00"), method="cash")
        db.session.commit()

        m_after = db.session.get(Makbuz, mid)
        p_after = db.session.get(Party, party_id)
        assert m_after.collected_amount == Decimal("1320.00")
        assert m_after.outstanding_amount == Decimal("0.00")
        assert p_after.previous_balance == Decimal("320.00")

    resp_list = client.get("/payments/")
    assert resp_list.status_code == 200
    html = resp_list.get_data(as_text=True)
    assert "-360" not in html
    assert "₺1,320.00" in html
    assert "1 Doktor" in html
    assert "Toplam <strong>₺320.00</strong> açık bakiye" in html

    parties_html = client.get("/parties/").get_data(as_text=True)
    assert "₺-360.00" not in parties_html
    assert "Toplam Açık Bakiye" in parties_html
    assert parties_html.count("₺320.00") >= 1
    assert "₺1,320.00" in parties_html


def test_partial_payment_on_draft_is_included_in_all_balance_totals(client, app):
    """A payment-bearing draft is financial even before its WhatsApp send."""
    login(client, "admin", "admin-pass")
    carry_party_id = _make_doctor(app, name="Dr. Devreden 320")
    partial_party_id = _make_doctor(app, name="Dr. Kısmi Taslak")

    with app.app_context():
        db.session.get(Party, carry_party_id).previous_balance = Decimal("320.00")
        summary = Makbuz(
            party_id=partial_party_id,
            year=2026,
            month=7,
            work_order_count=1,
            subtotal=Decimal("1783.88"),
            vat_applied=True,
            vat_rate=Decimal("10.00"),
            status=Makbuz.STATUS_DRAFT,
            generated_at=datetime.now().astimezone(),
        )
        summary.recalculate_totals()
        db.session.add(summary)
        db.session.flush()

        from app.services.makbuz_account_service import record_payment

        record_payment(
            summary,
            payment_date=date(2026, 7, 27),
            amount=Decimal("1500.00"),
            method="cash",
        )
        db.session.commit()
        assert summary.status == Makbuz.STATUS_DRAFT
        assert summary.affects_balance is True
        assert summary.outstanding_amount == Decimal("462.27")

    html = client.get("/payments/").get_data(as_text=True)
    assert "₺1,962.27" in html
    assert "₺1,500.00" in html
    assert "₺462.27" in html
    assert "2 Doktor" in html
    assert "Toplam <strong>₺782.27</strong> açık bakiye" in html

    parties_html = client.get("/parties/").get_data(as_text=True)
    assert "₺782.27" in parties_html


def test_previous_balance_only_doctor_can_be_collected_and_reopened(client, app):
    login(client, "admin", "admin-pass")
    party_id = _make_doctor(app, name="Dr. Sadece Devreden")
    with app.app_context():
        db.session.get(Party, party_id).previous_balance = Decimal("320.00")
        db.session.commit()

    pending_html = client.get("/payments/").get_data(as_text=True)
    assert "Dr. Sadece Devreden" in pending_html
    assert "Devreden borç" in pending_html
    assert f"/payments/parties/{party_id}/previous-balance" in pending_html

    response = client.post(
        f"/payments/parties/{party_id}/previous-balance",
        data={
            "paid_at": "2026-07-27",
            "paid_amount": "320.00",
            "payment_method": "cash",
            "notes": "Başlangıç borcu kapandı",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Devreden borç tamamen kapatıldı" in response.get_data(as_text=True)

    with app.app_context():
        party = db.session.get(Party, party_id)
        payment = db.session.execute(
            db.select(PartyPayment).where(PartyPayment.party_id == party_id)
        ).scalar_one()
        payment_id = payment.id
        assert party.previous_balance == Decimal("320.00")
        assert party.previous_balance_outstanding == Decimal("0.00")

    paid_html = client.get("/payments/?tab=paid").get_data(as_text=True)
    assert "Başlangıç borcu kapandı" in paid_html
    assert "₺320.00" in paid_html

    client.post(f"/payments/party-entries/{payment_id}/delete", follow_redirects=True)
    with app.app_context():
        assert db.session.get(Party, party_id).previous_balance_outstanding == Decimal("320.00")


def test_new_work_order_after_partial_payment_preserves_collection(client, app):
    login(client, "admin", "admin-pass")
    party_id = _make_doctor(app, name="Dr. Ay İçinde Ödeyen")
    _add_work_order(app, party_id, date(2026, 7, 5), 100)
    client.post(
        f"/makbuzlar/{party_id}/generate",
        data={"year": 2026, "month": 7},
    )

    with app.app_context():
        summary = db.session.execute(
            db.select(Makbuz).where(
                Makbuz.party_id == party_id,
                Makbuz.year == 2026,
                Makbuz.month == 7,
            )
        ).scalar_one()
        from app.services.makbuz_account_service import record_payment

        record_payment(
            summary,
            payment_date=date(2026, 7, 10),
            amount=Decimal("50.00"),
            method="cash",
        )
        db.session.commit()
        summary_id = summary.id
        payment_id = summary.payment_entries[0].id

    response = client.post(
        f"/parties/{party_id}/work-orders/add",
        data={
            "work_date": "2026-07-20",
            "patient_name": "Yeni Hasta",
            "apparatus_type": "Yeni işlem",
            "apparatus_price": "75.00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "tahsilat kaydını geri alın" not in response.get_data(as_text=True)

    with app.app_context():
        summary = db.session.get(Makbuz, summary_id)
        assert summary.work_order_count == 2
        assert summary.grand_total == Decimal("175.00")
        assert summary.collected_amount == Decimal("50.00")
        assert summary.outstanding_amount == Decimal("125.00")
        assert [entry.id for entry in summary.payment_entries] == [payment_id]
