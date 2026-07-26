"""Background send queue for monthly doctor receipts (makbuz) over WhatsApp.

One batch runs at a time in a daemon thread: for each makbuz the PDF is
generated and sent with WhatsAppService, with a delay between doctors so
WhatsApp does not rate-limit the account. Progress is queryable from any
request thread via ``current_job()`` and is exposed on /whatsapp/status so
the UI can follow the batch live.

State is in-memory, which is correct here because the WhatsApp client is
single-process by design (see whatsapp_service module docstring).
"""

import logging
import random
import threading
import time
import uuid
from datetime import datetime, timezone

from app.extensions import db
from app.models.models import Makbuz, MakbuzSendLog, WorkOrder

logger = logging.getLogger(__name__)


class MakbuzSendQueue:
    _app = None
    _lock = threading.Lock()
    _job: dict | None = None
    _thread = None
    _delay_seconds = 3.0  # base pause between doctors
    _delay_jitter = 2.0  # random extra seconds (0..jitter) added to base

    @classmethod
    def init_app(cls, app) -> None:
        cls._app = app

    # ------------------------------------------------------------------ state

    @classmethod
    def is_running(cls) -> bool:
        with cls._lock:
            return bool(cls._job and cls._job["running"])

    @classmethod
    def current_job(cls) -> dict | None:
        """A snapshot of the latest job (running or finished)."""
        with cls._lock:
            if cls._job is None:
                return None
            job = dict(cls._job)
            job["items"] = [dict(item) for item in cls._job["items"]]
            return job

    @classmethod
    def clear_finished(cls) -> None:
        with cls._lock:
            if cls._job is not None and not cls._job["running"]:
                cls._job = None

    # ------------------------------------------------------------------ start

    @classmethod
    def start_batch(
        cls, makbuz_ids: list[int], triggered_by: str = MakbuzSendLog.TRIGGER_MANUAL
    ) -> tuple[bool, str]:
        """Validate and launch a batch. Returns (started, message)."""
        from app.services.whatsapp_service import WhatsAppService

        if not makbuz_ids:
            return False, "Gönderilecek makbuz seçilmedi."
        if not WhatsAppService.get_status()["connected"]:
            return False, "WhatsApp bağlı değil. Önce bağlantıyı kurun."

        rows = db.session.execute(
            db.select(Makbuz).where(Makbuz.id.in_(makbuz_ids))
        ).scalars().all()
        by_id = {m.id: m for m in rows}

        items = []
        for mid in makbuz_ids:
            makbuz = by_id.get(mid)
            if makbuz is None:
                continue
            items.append({
                "makbuz_id": makbuz.id,
                "party_id": makbuz.party_id,
                "doctor": makbuz.party.display_name if makbuz.party else "?",
                "phone": makbuz.party.phone if makbuz.party else None,
                "year": makbuz.year,
                "month": makbuz.month,
                "status": "pending",  # pending -> sending -> sent | failed
                "message": None,
            })
        if not items:
            return False, "Seçilen makbuzlar bulunamadı."

        with cls._lock:
            if cls._job is not None and cls._job["running"]:
                return False, "Devam eden bir gönderim var. Bitmesini bekleyin."
            cls._job = {
                "id": uuid.uuid4().hex[:12],
                "running": True,
                "triggered_by": triggered_by,
                "total": len(items),
                "done": 0,
                "sent": 0,
                "failed": 0,
                "items": items,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None,
            }
            cls._thread = threading.Thread(
                target=cls._run,
                args=([item["makbuz_id"] for item in items],),
                name="makbuz-send-queue",
                daemon=True,
            )
            cls._thread.start()

        return True, f"{len(items)} makbuz için gönderim arka planda başlatıldı."

    # ------------------------------------------------------------------- run

    @classmethod
    def _run(cls, makbuz_ids: list[int]) -> None:
        try:
            if cls._app is not None:
                with cls._app.app_context():
                    cls._process_all(makbuz_ids)
            else:
                cls._process_all(makbuz_ids)
        except Exception:
            logger.exception("Makbuz gönderim kuyruğu beklenmedik şekilde durdu")
        finally:
            leftovers = []
            with cls._lock:
                if cls._job is not None:
                    for item in cls._job["items"]:
                        if item["status"] in ("pending", "sending"):
                            item["status"] = "failed"
                            item["message"] = "Gönderim tamamlanamadı."
                            cls._job["failed"] += 1
                            cls._job["done"] += 1
                            leftovers.append(dict(item))
                    cls._job["running"] = False
                    cls._job["finished_at"] = datetime.now(timezone.utc).isoformat()
            for item in leftovers:
                cls._persist_log(item)

    @classmethod
    def _process_all(cls, makbuz_ids: list[int]) -> None:
        for index, makbuz_id in enumerate(makbuz_ids):
            if index and cls._delay_seconds:
                delay = round(cls._delay_seconds + random.random() * cls._delay_jitter, 2)
                time.sleep(delay)
            ok, message = cls._send_one(makbuz_id)
            cls._mark_done(makbuz_id, ok, message)

    @classmethod
    def _mark_item(cls, makbuz_id: int, **fields) -> None:
        with cls._lock:
            if cls._job is None:
                return
            for item in cls._job["items"]:
                if item["makbuz_id"] == makbuz_id:
                    item.update(fields)
                    return

    @classmethod
    def _mark_done(cls, makbuz_id: int, ok: bool, message: str) -> None:
        cls._mark_item(
            makbuz_id, status="sent" if ok else "failed", message=message
        )
        snapshot = None
        with cls._lock:
            if cls._job is not None:
                cls._job["done"] += 1
                if ok:
                    cls._job["sent"] += 1
                else:
                    cls._job["failed"] += 1
                for item in cls._job["items"]:
                    if item["makbuz_id"] == makbuz_id:
                        snapshot = dict(item)
                        break
        if snapshot is not None:
            cls._persist_log(snapshot)

    @classmethod
    def _persist_log(cls, item: dict) -> None:
        """Write one history row; never raises into the queue thread."""

        def _write():
            with cls._lock:
                job = cls._job or {}
                batch_id = job.get("id", "?")
                triggered_by = job.get("triggered_by", MakbuzSendLog.TRIGGER_MANUAL)
            try:
                db.session.add(MakbuzSendLog(
                    batch_id=batch_id,
                    makbuz_id=item.get("makbuz_id"),
                    party_id=item.get("party_id"),
                    doctor_name=item.get("doctor") or "?",
                    phone=item.get("phone"),
                    year=item.get("year") or 0,
                    month=item.get("month") or 0,
                    success=item.get("status") == "sent",
                    message=item.get("message"),
                    triggered_by=triggered_by,
                ))
                db.session.commit()
            except Exception:
                db.session.rollback()
                raise

        try:
            if cls._app is not None:
                with cls._app.app_context():
                    _write()
            else:
                _write()
        except Exception:
            logger.exception("Makbuz gönderim geçmişi kaydedilemedi")

    @classmethod
    def _send_one(cls, makbuz_id: int) -> tuple[bool, str]:
        cls._mark_item(makbuz_id, status="sending")
        try:
            return send_makbuz_via_whatsapp(makbuz_id)
        except Exception as exc:
            logger.exception("Makbuz %s gönderilemedi", makbuz_id)
            try:
                db.session.rollback()
            except Exception:
                pass
            return False, f"Beklenmedik hata: {exc}"


def send_makbuz_via_whatsapp(makbuz_id: int) -> tuple[bool, str]:
    """Generate the PDF for a makbuz and send it over WhatsApp.

    On success the makbuz is marked as sent. Shared by the makbuzlar routes
    and the background queue; must be called inside an app context.
    """
    from sqlalchemy import extract

    from app.services.makbuz_pdf_service import generate_makbuz_pdf
    from app.services.whatsapp_service import WhatsAppService

    makbuz = db.session.get(Makbuz, makbuz_id)
    if makbuz is None:
        return False, "Makbuz bulunamadı."

    work_orders = db.session.execute(
        db.select(WorkOrder)
        .where(
            WorkOrder.party_id == makbuz.party_id,
            extract("year", WorkOrder.work_date) == makbuz.year,
            extract("month", WorkOrder.work_date) == makbuz.month,
        )
        .order_by(WorkOrder.work_date.desc())
    ).scalars().all()

    pdf_bytes = generate_makbuz_pdf(makbuz, work_orders)
    result = WhatsAppService.send_makbuz_message(makbuz, pdf_bytes)
    if result["success"]:
        if makbuz.status != Makbuz.STATUS_PAID:
            makbuz.status = Makbuz.STATUS_SENT
        makbuz.sent_at = datetime.now().astimezone()
        db.session.commit()
    return result["success"], result["message"]
