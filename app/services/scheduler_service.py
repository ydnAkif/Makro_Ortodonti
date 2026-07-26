"""Ayın 1'inde çalışan makbuz arkaplan görevleri.

06:00 — bir önceki ayın makbuz taslaklarını oluşturur (KDV gerektiren
doktorlar makbuzlar ekranında elle işaretlenir; bu görev göndermez).
09:30 — "Otomatik gönderim" ayarı açıksa ve WhatsApp bağlıysa, önceki aya
ait iş emirlerinden güncellenen makbuzları WhatsApp gönderim kuyruğuna verir.
"""

import logging
import os
from datetime import date, timedelta
from decimal import Decimal

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None

SETTINGS_KEY = "makbuz_auto_run_date"
AUTO_SEND_RUN_KEY = "makbuz_auto_send_run_date"
AUTO_SEND_TOGGLE_KEY = "whatsapp_auto_send_makbuz"


def _previous_month(today: date) -> tuple[int, int]:
    first_of_this_month = today.replace(day=1)
    last_day_of_prev_month = first_of_this_month - timedelta(days=1)
    return last_day_of_prev_month.year, last_day_of_prev_month.month


def _claim_todays_run(key: str = SETTINGS_KEY, description: str | None = None) -> bool:
    """Atomically mark today as run so only one process/worker executes the job."""
    from app.extensions import db
    from app.models.models import Settings

    today_str = date.today().isoformat()

    row = db.session.execute(
        db.select(Settings).where(Settings.key == key)
    ).scalar_one_or_none()
    if row is None:
        db.session.add(Settings(
            key=key, value="",
            description=description
            or "Otomatik makbuz taslağı üretiminin en son çalıştığı gün (YYYY-MM-DD)",
        ))
        db.session.commit()

    result = db.session.execute(
        db.update(Settings)
        .where(Settings.key == key, Settings.value != today_str)
        .values(value=today_str)
    )
    db.session.commit()
    return result.rowcount == 1


def auto_send_enabled() -> bool:
    """Read the auto-send toggle from Settings (default: off)."""
    from app.extensions import db
    from app.models.models import Settings

    value = db.session.execute(
        db.select(Settings.value).where(Settings.key == AUTO_SEND_TOGGLE_KEY)
    ).scalar_one_or_none()
    return value == "true"


def _generate_monthly_drafts(app) -> None:
    with app.app_context():
        today = date.today()
        if today.day != 1:
            return
        if not _claim_todays_run():
            return

        from app.extensions import db
        from app.models.models import Party, WorkOrder, Makbuz
        from app.services.makbuz_service import generate_makbuz
        from sqlalchemy import extract

        year, month = _previous_month(today)

        party_ids = db.session.execute(
            db.select(WorkOrder.party_id)
            .join(Party, WorkOrder.party_id == Party.id)
            .where(
                extract("year", WorkOrder.work_date) == year,
                extract("month", WorkOrder.work_date) == month,
                Party.is_active.is_(True),
            )
            .distinct()
        ).scalars().all()

        created = 0
        for party_id in party_ids:
            existing = db.session.execute(
                db.select(Makbuz).where(
                    Makbuz.party_id == party_id, Makbuz.year == year, Makbuz.month == month
                )
            ).scalar_one_or_none()
            if existing:
                continue
            try:
                generate_makbuz(party_id, year, month, vat_applied=False, vat_rate=Decimal("0"))
                db.session.commit()
                created += 1
            except ValueError:
                db.session.rollback()

        logger.info(
            "Otomatik makbuz taslağı üretimi tamamlandı: %s doktor, dönem %s-%02d",
            created, year, month,
        )


def _auto_send_monthly_makbuzlar(app) -> None:
    """Ayın 1'inde yalnızca önceki aya ait iş emirlerinin makbuzlarını gönderir."""
    with app.app_context():
        today = date.today()
        if today.day != 1:
            return
        if not auto_send_enabled():
            return

        from app.services.whatsapp_service import WhatsAppService

        if not WhatsAppService.get_status()["connected"]:
            logger.warning(
                "Otomatik makbuz gönderimi atlandı: WhatsApp bağlı değil. "
                "Taslaklar WhatsApp sayfasından elle gönderilebilir."
            )
            return

        from app.extensions import db
        from app.models.models import Makbuz, MakbuzSendLog, Party, WorkOrder
        from app.services.makbuz_service import generate_makbuz
        from sqlalchemy import extract

        year, month = _previous_month(today)
        makbuzlar = db.session.execute(
            db.select(Makbuz)
            .join(Party, Makbuz.party_id == Party.id)
            .where(
                Makbuz.year == year,
                Makbuz.month == month,
                Makbuz.status == Makbuz.STATUS_DRAFT,
                Party.is_active.is_(True),
                Party.phone.isnot(None),
                Party.phone != "",
                db.exists().where(
                    WorkOrder.party_id == Makbuz.party_id,
                    extract("year", WorkOrder.work_date) == year,
                    extract("month", WorkOrder.work_date) == month,
                ),
            )
        ).scalars().all()

        if not makbuzlar:
            logger.info("Otomatik makbuz gönderimi: döneme ait iş emri yok (%s-%02d).", year, month)
            return

        if not _claim_todays_run(
            AUTO_SEND_RUN_KEY,
            "Otomatik makbuz gönderiminin en son çalıştığı gün (YYYY-MM-DD)",
        ):
            return

        makbuz_ids = []
        for makbuz in makbuzlar:
            refreshed = generate_makbuz(
                makbuz.party_id,
                year,
                month,
                vat_applied=makbuz.vat_applied,
                vat_rate=makbuz.vat_rate,
            )
            makbuz_ids.append(refreshed.id)
        db.session.commit()

        from app.services.makbuz_send_queue import MakbuzSendQueue

        started, message = MakbuzSendQueue.start_batch(
            list(makbuz_ids), triggered_by=MakbuzSendLog.TRIGGER_SCHEDULER
        )
        if started:
            logger.info("Otomatik makbuz gönderimi başlatıldı: %s", message)
        else:
            logger.warning("Otomatik makbuz gönderimi başlatılamadı: %s", message)


def _purge_old_login_attempts(app) -> None:
    """30 günden eski LoginAttempt kayıtlarını siler (tablo büyümesini önler)."""
    with app.app_context():
        from datetime import timedelta
        from app.extensions import db
        from app.models.models import LoginAttempt

        cutoff = date.today() - timedelta(days=30)
        try:
            result = db.session.execute(
                db.delete(LoginAttempt).where(LoginAttempt.created_at < cutoff)
            )
            db.session.commit()
            logger.info("LoginAttempt temizliği: %s kayıt silindi (>30 gün).", result.rowcount)
        except Exception as exc:
            db.session.rollback()
            logger.warning("LoginAttempt temizliği başarısız: %s", exc)


def _purge_old_audit_logs(app) -> None:
    """AuditLog tablosunu AUDIT_RETENTION_DAYS kadar eski kayıtlardan temizler."""
    with app.app_context():
        from datetime import timedelta, datetime, timezone
        from app.extensions import db
        from app.models.models import AuditLog

        days = int(app.config.get("AUDIT_RETENTION_DAYS", 3650))
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        try:
            result = db.session.execute(
                db.delete(AuditLog).where(AuditLog.occurred_at < cutoff)
            )
            db.session.commit()
            logger.info("AuditLog temizliği: %s kayıt silindi (%s günden eski).", result.rowcount, days)
        except Exception as exc:
            db.session.rollback()
            logger.warning("AuditLog temizliği başarısız: %s", exc)


def init_scheduler(app) -> None:

    """Start the background scheduler once per running process."""
    global _scheduler
    if _scheduler is not None:
        return
    if app.testing:
        return
    # Werkzeug'un debug reloader'ı ana süreci bir kez, alt süreci bir kez başlatır;
    # yalnızca gerçekten sunum yapan (child) süreçte başlat.
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        _generate_monthly_drafts,
        trigger="cron",
        day=1,
        hour=6,
        minute=0,
        args=[app],
        id="makbuz_monthly_drafts",
        replace_existing=True,
    )
    scheduler.add_job(
        _auto_send_monthly_makbuzlar,
        trigger="cron",
        day=1,
        hour=9,
        minute=30,
        args=[app],
        id="makbuz_monthly_auto_send",
        replace_existing=True,
    )

    from app.services.backup_service import scheduled_backup
    scheduler.add_job(
        scheduled_backup,
        trigger="cron",
        hour=2,
        minute=0,
        args=[app],
        id="nightly_db_backup",
        replace_existing=True,
    )

    # LoginAttempt tablosu büyümeye devam eder, haftalık temizle.
    scheduler.add_job(
        _purge_old_login_attempts,
        trigger="cron",
        day_of_week="sun",
        hour=3,
        minute=0,
        args=[app],
        id="weekly_login_attempt_purge",
        replace_existing=True,
    )

    # AuditLog tablosu sınırsız büyür, aylık temizle.
    scheduler.add_job(
        _purge_old_audit_logs,
        trigger="cron",
        day=1,
        hour=3,
        minute=30,
        args=[app],
        id="monthly_audit_log_purge",
        replace_existing=True,
    )

    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "Zamanlayıcı başlatıldı: ayın 1'i 06:00 taslaklar, "
        "09:30 otomatik gönderim (ayar açıksa), her gece 02:00 yedekleme, "
        "Pazar 03:00 login kayıtları temizliği, ayın 1'i 03:30 audit log temizliği."
    )
