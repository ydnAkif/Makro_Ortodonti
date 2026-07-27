from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from app.extensions import db
from app.models.models import Party, PartyType, WorkOrder, Makbuz
from conftest import login


def _make_doctor(app, name="Dr. Lock Test", phone="+905559990011"):
    with app.app_context():
        party = Party(party_type=PartyType.DENTIST, name=name, phone=phone)
        db.session.add(party)
        db.session.commit()
        return party.id


def _add_work_order(app, party_id, work_date, price=1000):
    with app.app_context():
        wo = WorkOrder(
            party_id=party_id,
            work_date=work_date,
            apparatus_type="Nance",
            patient_name="Lock Patient",
            apparatus_price=Decimal(price),
            extra_price=Decimal(0),
            total_price=Decimal(price),
        )
        db.session.add(wo)
        db.session.commit()
        return wo.id


def _create_locked_makbuz(app, party_id, year, month, status=Makbuz.STATUS_SENT):
    with app.app_context():
        makbuz = Makbuz(
            party_id=party_id,
            year=year,
            month=month,
            work_order_count=1,
            subtotal=Decimal("1000.00"),
            vat_applied=False,
            vat_rate=Decimal("0.00"),
            status=status,
            generated_at=datetime.now().astimezone(),
        )
        makbuz.recalculate_totals()
        db.session.add(makbuz)
        db.session.commit()
        return makbuz.id


def test_can_add_work_order_after_summary_is_sent(client, app):
    """A sent informational summary stays editable until a payment exists."""
    login(client, "admin", "admin-pass")
    party_id = _make_doctor(app)
    _create_locked_makbuz(app, party_id, 2026, 6)

    response = client.post(
        f"/parties/{party_id}/work-orders/add",
        data={
            "work_date": "2026-06-15",
            "patient_name": "E2E Hasta",
            "apparatus_type": "Nance",
            "apparatus_price": "100",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    with app.app_context():
        count = db.session.execute(
            db.select(db.func.count(WorkOrder.id)).where(
                WorkOrder.party_id == party_id,
                WorkOrder.work_date == date(2026, 6, 15)
            )
        ).scalar()
        assert count == 1
        summary = db.session.execute(
            db.select(Makbuz).where(
                Makbuz.party_id == party_id,
                Makbuz.year == 2026,
                Makbuz.month == 6,
            )
        ).scalar_one()
        assert summary.status == Makbuz.STATUS_DRAFT
        assert summary.subtotal == Decimal("100.00")


def test_can_edit_work_order_after_summary_is_sent(client, app):
    """Editing a sent informational summary period refreshes it as draft."""
    login(client, "admin", "admin-pass")
    party_id = _make_doctor(app)
    wo_id = _add_work_order(app, party_id, date(2026, 6, 10))
    _create_locked_makbuz(app, party_id, 2026, 6)

    response = client.post(
        f"/parties/{party_id}/work-orders/{wo_id}/edit",
        data={
            "work_date": "2026-06-10",
            "patient_name": "Updated Name",
            "apparatus_type": "Nance",
            "apparatus_price": "2000",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    with app.app_context():
        wo = db.session.get(WorkOrder, wo_id)
        assert wo.patient_name == "Updated Name"
        assert wo.apparatus_price == Decimal("2000.00")
        summary = db.session.execute(
            db.select(Makbuz).where(Makbuz.party_id == party_id)
        ).scalar_one()
        assert summary.status == Makbuz.STATUS_DRAFT
        assert summary.subtotal == Decimal("2000.00")


def test_can_move_work_order_to_sent_summary_period(client, app):
    login(client, "admin", "admin-pass")
    party_id = _make_doctor(app)
    wo_id = _add_work_order(app, party_id, date(2026, 5, 10))  # May (unlocked)
    _create_locked_makbuz(app, party_id, 2026, 6)  # June (locked)

    # Try POST update moving from May to June
    response = client.post(
        f"/parties/{party_id}/work-orders/{wo_id}/edit",
        data={
            "work_date": "2026-06-10",  # target is locked
            "patient_name": "Lock Patient",
            "apparatus_type": "Nance",
            "apparatus_price": "1000",
        },
        follow_redirects=True,
    )
    with app.app_context():
        wo = db.session.get(WorkOrder, wo_id)
        assert wo.work_date == date(2026, 6, 10)
        summary = db.session.execute(
            db.select(Makbuz).where(
                Makbuz.party_id == party_id,
                Makbuz.year == 2026,
                Makbuz.month == 6,
            )
        ).scalar_one()
        assert summary.status == Makbuz.STATUS_DRAFT


def test_cannot_add_work_order_with_negative_price(client, app):
    """Negative apparatus/extra prices are rejected, not silently stored."""
    login(client, "admin", "admin-pass")
    party_id = _make_doctor(app)

    response = client.post(
        f"/parties/{party_id}/work-orders/add",
        data={
            "work_date": "2026-06-15",
            "patient_name": "Negatif Test",
            "apparatus_type": "Nance",
            "apparatus_price": "-500",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "negatif olamaz".encode() in response.data

    with app.app_context():
        count = db.session.execute(
            db.select(db.func.count(WorkOrder.id)).where(WorkOrder.party_id == party_id)
        ).scalar()
        assert count == 0


def test_edit_work_order_rejects_mismatched_party_id(client, app):
    """A wo_id belonging to another party must not be reachable/editable
    through a different party's URL — this used to let a caller bypass
    that other party's own period-lock check (see PartyService.get_work_order_or_404)."""
    login(client, "admin", "admin-pass")
    owner_party_id = _make_doctor(app, name="Dr. Gerçek Sahip", phone="+905559990022")
    other_party_id = _make_doctor(app, name="Dr. Başka Hekim", phone="+905559990033")
    wo_id = _add_work_order(app, owner_party_id, date(2026, 6, 10))
    _create_locked_makbuz(app, owner_party_id, 2026, 6)

    response = client.get(f"/parties/{other_party_id}/work-orders/{wo_id}/edit")
    assert response.status_code == 404

    response = client.post(
        f"/parties/{other_party_id}/work-orders/{wo_id}/edit",
        data={
            "work_date": "2026-06-10",
            "patient_name": "Ele Geçirilmiş",
            "apparatus_type": "Nance",
            "apparatus_price": "1",
        },
    )
    assert response.status_code == 404

    with app.app_context():
        wo = db.session.get(WorkOrder, wo_id)
        assert wo.patient_name == "Lock Patient"
        assert wo.apparatus_price == Decimal("1000.00")


def test_can_delete_work_order_after_summary_is_sent(client, app):
    """Sent informational summaries do not lock their underlying work orders."""
    login(client, "admin", "admin-pass")
    party_id = _make_doctor(app)
    wo_id = _add_work_order(app, party_id, date(2026, 6, 10))
    _create_locked_makbuz(app, party_id, 2026, 6)

    response = client.post(
        f"/parties/{party_id}/work-orders/{wo_id}/delete",
        follow_redirects=True,
    )
    assert response.status_code == 200
    with app.app_context():
        assert db.session.get(WorkOrder, wo_id) is None
        summary = db.session.execute(
            db.select(Makbuz).where(Makbuz.party_id == party_id)
        ).scalar_one()
        assert summary.status == Makbuz.STATUS_DRAFT
        assert summary.subtotal == Decimal("0.00")
