"""Background send queue for free-text WhatsApp broadcasts to multiple parties.

Mirrors the makbuz_send_queue module's pattern (one batch at a time in a
daemon thread, with a delay between recipients so WhatsApp does not
rate-limit the account) but for the ad-hoc "send-bulk" message form instead
of makbuz PDFs. Kept as a separate, smaller class rather than folding into
MakbuzSendQueue because the two jobs carry different item shapes (free text
vs. makbuz/PDF) and different persistence targets.
"""

import logging
import random
import threading
import time
import uuid
from datetime import datetime, timezone

from app.extensions import db
from app.models.models import Party

logger = logging.getLogger(__name__)


class BulkMessageQueue:
    _app = None
    _lock = threading.Lock()
    _job: dict | None = None
    _thread = None
    _delay_seconds = 3.0
    _delay_jitter = 2.0

    @classmethod
    def init_app(cls, app) -> None:
        cls._app = app

    @classmethod
    def is_running(cls) -> bool:
        with cls._lock:
            return bool(cls._job and cls._job["running"])

    @classmethod
    def current_job(cls) -> dict | None:
        with cls._lock:
            if cls._job is None:
                return None
            job = dict(cls._job)
            job["items"] = [dict(item) for item in cls._job["items"]]
            return job

    @classmethod
    def start_batch(cls, party_ids: list[int], message: str) -> tuple[bool, str]:
        """Validate and launch a broadcast. Returns (started, message)."""
        from app.services.whatsapp_service import WhatsAppService

        if not message:
            return False, "Mesaj metni zorunludur."
        if not party_ids:
            return False, "Gönderilecek en az bir kişi seçilmelidir."
        if not WhatsAppService.get_status()["connected"]:
            return False, "WhatsApp bağlı değil. Önce bağlantıyı kurun."

        rows = db.session.execute(
            db.select(Party).where(Party.id.in_(party_ids))
        ).scalars().all()
        by_id = {p.id: p for p in rows}

        items = []
        for pid in party_ids:
            party = by_id.get(pid)
            if party is None or not party.phone:
                continue
            items.append({
                "party_id": party.id,
                "doctor": party.display_name if hasattr(party, "display_name") else party.name,
                "phone": party.phone,
                "status": "pending",  # pending -> sending -> sent | failed
                "message": None,
            })
        if not items:
            return False, "Seçilen kişilerin telefon numarası bulunamadı."

        with cls._lock:
            if cls._job is not None and cls._job["running"]:
                return False, "Devam eden bir gönderim var. Bitmesini bekleyin."
            cls._job = {
                "id": uuid.uuid4().hex[:12],
                "kind": "bulk_message",
                "running": True,
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
                args=(message,),
                name="bulk-message-queue",
                daemon=True,
            )
            cls._thread.start()

        return True, f"{len(items)} kişiye gönderim arka planda başlatıldı."

    @classmethod
    def _run(cls, message: str) -> None:
        try:
            if cls._app is not None:
                with cls._app.app_context():
                    cls._process_all(message)
            else:
                cls._process_all(message)
        except Exception:
            logger.exception("Toplu mesaj kuyruğu beklenmedik şekilde durdu")
        finally:
            with cls._lock:
                if cls._job is not None:
                    for item in cls._job["items"]:
                        if item["status"] in ("pending", "sending"):
                            item["status"] = "failed"
                            item["message"] = "Gönderim tamamlanamadı."
                            cls._job["failed"] += 1
                            cls._job["done"] += 1
                    cls._job["running"] = False
                    cls._job["finished_at"] = datetime.now(timezone.utc).isoformat()

    @classmethod
    def _process_all(cls, message: str) -> None:
        from app.services.whatsapp_service import WhatsAppService

        with cls._lock:
            party_ids = [item["party_id"] for item in cls._job["items"]] if cls._job else []

        for index, party_id in enumerate(party_ids):
            if index and cls._delay_seconds:
                delay = round(cls._delay_seconds + random.random() * cls._delay_jitter, 2)
                time.sleep(delay)
            cls._mark_item(party_id, status="sending")
            phone = None
            with cls._lock:
                if cls._job is not None:
                    for item in cls._job["items"]:
                        if item["party_id"] == party_id:
                            phone = item["phone"]
                            break
            try:
                result = WhatsAppService.send_message(phone, message) if phone else {
                    "success": False, "message": "Telefon numarası yok.",
                }
            except Exception as exc:
                logger.exception("Toplu mesaj gönderilemedi: party=%s", party_id)
                result = {"success": False, "message": f"Beklenmedik hata: {exc}"}

            with cls._lock:
                if cls._job is None:
                    return
                for item in cls._job["items"]:
                    if item["party_id"] == party_id:
                        item["status"] = "sent" if result["success"] else "failed"
                        item["message"] = result["message"]
                        break
                cls._job["done"] += 1
                if result["success"]:
                    cls._job["sent"] += 1
                else:
                    cls._job["failed"] += 1

    @classmethod
    def _mark_item(cls, party_id: int, **fields) -> None:
        with cls._lock:
            if cls._job is None:
                return
            for item in cls._job["items"]:
                if item["party_id"] == party_id:
                    item.update(fields)
                    return
