from datetime import date

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required
from sqlalchemy import extract

from app.authz import permissions_required
from app.extensions import db
from app.models.models import Makbuz, MakbuzSendLog, Party, Settings, WorkOrder
from app.constants import MONTHS, MAKBUZ_STATUS_LABELS

whatsapp_bp = Blueprint("whatsapp", __name__)


def _makbuz_candidates(year: int, month: int) -> list[dict]:
    """Doctors that have a makbuz for the period, ready to send over WhatsApp."""
    from app.services.search_service import tr_order

    rows = db.session.execute(
        db.select(Makbuz)
        .join(Party, Makbuz.party_id == Party.id)
        .where(Makbuz.year == year, Makbuz.month == month, Party.is_active.is_(True))
        .order_by(tr_order(Party.name))
    ).scalars().all()

    return [
        {
            "makbuz": makbuz,
            "party": makbuz.party,
            "has_phone": bool(makbuz.party and makbuz.party.phone),
            "sendable": bool(makbuz.party and makbuz.party.phone),
        }
        for makbuz in rows
    ]


def _current_send_job() -> dict | None:
    """Pick whichever background queue (makbuz batch or bulk message) is
    active or most recently finished, so the shared progress panel in the
    template can show either kind of job without needing two UIs."""
    from app.services.makbuz_send_queue import MakbuzSendQueue
    from app.services.bulk_message_queue import BulkMessageQueue

    makbuz_job = MakbuzSendQueue.current_job()
    bulk_job = BulkMessageQueue.current_job()

    if makbuz_job and makbuz_job["running"]:
        return makbuz_job
    if bulk_job and bulk_job["running"]:
        return bulk_job

    candidates = [job for job in (makbuz_job, bulk_job) if job is not None]
    if not candidates:
        return None
    return max(candidates, key=lambda job: job.get("finished_at") or job.get("started_at") or "")


def _doctors_without_makbuz(year: int, month: int) -> int:
    """Doctors with work orders in the period but no makbuz generated yet."""
    with_orders = db.session.execute(
        db.select(WorkOrder.party_id)
        .join(Party, WorkOrder.party_id == Party.id)
        .where(
            extract("year", WorkOrder.work_date) == year,
            extract("month", WorkOrder.work_date) == month,
            Party.is_active.is_(True),
        )
        .distinct()
    ).scalars().all()
    with_makbuz = db.session.execute(
        db.select(Makbuz.party_id).where(Makbuz.year == year, Makbuz.month == month)
    ).scalars().all()
    return len(set(with_orders) - set(with_makbuz))


@whatsapp_bp.route("/")
@login_required
@permissions_required("messaging.use")
def index():
    from app.services.scheduler_service import auto_send_enabled, payment_reminders_enabled
    from app.services.whatsapp_service import WhatsAppService

    status = WhatsAppService.get_status()

    today = date.today()
    year = request.args.get("year", today.year, type=int)
    month = request.args.get("month", today.month, type=int)

    candidates = _makbuz_candidates(year, month)
    missing_makbuz_count = _doctors_without_makbuz(year, month)

    send_history = db.session.execute(
        db.select(MakbuzSendLog).order_by(MakbuzSendLog.id.desc()).limit(25)
    ).scalars().all()

    from app.services.search_service import tr_order

    parties_with_phone = db.session.execute(
        db.select(Party).where(
            Party.is_active.is_(True),
            Party.phone.isnot(None),
            Party.phone != "",
        ).order_by(tr_order(Party.name))
    ).scalars().all()
    selected_party_id = request.args.get("message_party_id", type=int)
    selected_recipient = next(
        (party for party in parties_with_phone if party.id == selected_party_id),
        None,
    )

    return render_template(
        "whatsapp/index.html",
        status=status,
        patients=parties_with_phone,
        selected_recipient=selected_recipient,
        candidates=candidates,
        missing_makbuz_count=missing_makbuz_count,
        year=year,
        month=month,
        months=MONTHS,
        years=list(range(today.year - 2, today.year + 1)),
        status_labels=MAKBUZ_STATUS_LABELS,
        send_job=_current_send_job(),
        send_history=send_history,
        auto_send_on=auto_send_enabled(),
        payment_reminder_on=payment_reminders_enabled(),
    )


@whatsapp_bp.route("/send-makbuz-batch", methods=["POST"])
@login_required
@permissions_required("billing.edit")
def send_makbuz_batch():
    from app.services.makbuz_send_queue import MakbuzSendQueue

    year = request.form.get("year", date.today().year, type=int)
    month = request.form.get("month", date.today().month, type=int)
    makbuz_ids = request.form.getlist("makbuz_ids", type=int)

    started, message = MakbuzSendQueue.start_batch(makbuz_ids)
    flash(message, "info" if started else "danger")
    return redirect(url_for("whatsapp.index", year=year, month=month))


@whatsapp_bp.route("/auto-send-toggle", methods=["POST"])
@login_required
@permissions_required("billing.edit")
def auto_send_toggle():
    from app.services.scheduler_service import AUTO_SEND_TOGGLE_KEY

    enabled = request.form.get("enabled") == "on"
    row = db.session.execute(
        db.select(Settings).where(Settings.key == AUTO_SEND_TOGGLE_KEY)
    ).scalar_one_or_none()
    if row is None:
        row = Settings(
            key=AUTO_SEND_TOGGLE_KEY,
            value="false",
            description="Ayın 1'inde önceki aya ait iş emirlerinin makbuzlarını WhatsApp'tan otomatik gönder",
        )
        db.session.add(row)
    row.value = "true" if enabled else "false"
    db.session.commit()

    flash(
        "Otomatik makbuz gönderimi açıldı. Her ayın 1'inde saat 09:30'da, "
        "yalnızca önceki aya ait iş emirlerinin makbuzları otomatik gönderilecek."
        if enabled
        else "Otomatik makbuz gönderimi kapatıldı.",
        "success",
    )
    return redirect(url_for("whatsapp.index"))


@whatsapp_bp.route("/payment-reminder-toggle", methods=["POST"])
@login_required
@permissions_required("billing.edit")
def payment_reminder_toggle():
    from app.services.scheduler_service import PAYMENT_REMINDER_TOGGLE_KEY

    enabled = request.form.get("enabled") == "on"
    row = db.session.execute(
        db.select(Settings).where(Settings.key == PAYMENT_REMINDER_TOGGLE_KEY)
    ).scalar_one_or_none()
    if row is None:
        row = Settings(
            key=PAYMENT_REMINDER_TOGGLE_KEY,
            value="false",
            description="Vadesi geçmiş, ödenmemiş makbuzlar için günlük WhatsApp hatırlatması gönder",
        )
        db.session.add(row)
    row.value = "true" if enabled else "false"
    db.session.commit()

    flash(
        "Ödeme hatırlatıcı açıldı. Gönderildikten sonra 15+ gündür ödenmemiş "
        "makbuzlar için günde bir kez otomatik WhatsApp hatırlatması gönderilecek."
        if enabled
        else "Ödeme hatırlatıcı kapatıldı.",
        "success",
    )
    return redirect(url_for("whatsapp.index"))


@whatsapp_bp.route("/connect", methods=["POST"])
@login_required
@permissions_required("messaging.use")
def connect():
    from app.services.whatsapp_service import WhatsAppService
    phone = request.form.get("phone_number", "").strip()
    result = WhatsAppService.connect(phone_number=phone if phone else None)
    flash(result["message"], "success" if result["success"] else "danger")
    return redirect(url_for("whatsapp.index"))


@whatsapp_bp.route("/disconnect", methods=["POST"])
@login_required
@permissions_required("messaging.use")
def disconnect():
    from app.services.whatsapp_service import WhatsAppService
    result = WhatsAppService.disconnect()
    flash(result["message"], "success" if result["success"] else "danger")
    return redirect(url_for("whatsapp.index"))


@whatsapp_bp.route("/send", methods=["POST"])
@login_required
@permissions_required("messaging.use")
def send_message():
    from app.services.whatsapp_service import WhatsAppService
    phone = request.form.get("phone_number", "").strip()
    message = request.form.get("message", "").strip()

    if not phone or not message:
        flash("Telefon numarası ve mesaj zorunludur.", "danger")
        return redirect(url_for("whatsapp.index"))

    result = WhatsAppService.send_message(phone, message)
    flash(result["message"], "success" if result["success"] else "danger")
    return redirect(url_for("whatsapp.index"))


@whatsapp_bp.route("/send-bulk", methods=["POST"])
@login_required
@permissions_required("messaging.use")
def send_bulk():
    from app.services.bulk_message_queue import BulkMessageQueue

    message_template = request.form.get("message", "").strip()
    party_ids = request.form.getlist("patient_ids", type=int)

    started, message = BulkMessageQueue.start_batch(party_ids, message_template)
    flash(message, "info" if started else "danger")
    return redirect(url_for("whatsapp.index"))


@whatsapp_bp.route("/status")
@login_required
@permissions_required("messaging.use")
def status():
    from app.services.whatsapp_service import WhatsAppService

    status = WhatsAppService.get_status()
    if status.get("connected_at") is not None:
        status["connected_at"] = status["connected_at"].isoformat()
    status["send_job"] = _current_send_job()
    return jsonify(status)
