"""Arka plan PDF üretim kuyruğu.

Büyük PDF'ler (çok sayıda makbuz veya iş emri) senkron olarak生成
yapıldığında HTTP isteğini uzun süre bloke eder. Bu servis, PDF
üretimini arka plan iş parçacığına taşıyarak istek yanıt süresini
kısaltır.

Kullanım::

    from app.services.pdf_queue import PdfQueue

    job_id = PdfQueue.submit(generate_makbuz_pdf, makbuz, work_orders)
    # ... sonradan kontrol et ...
    result = PdfQueue.get_result(job_id)

Not: Bu servis uygulama Process ile sınırlıdır; birden fazla worker
(gunicorn --workers N) kullanılıyorsa her worker kendi kuyruğunu tutar.
Mevcut kısıt: ``--workers 1`` (WhatsApp ve PDF kuyruğu için).
"""

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class PdfJob:
    job_id: str
    status: str = "pending"  # pending | running | completed | failed
    result: bytes | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.monotonic)


class PdfQueue:
    _jobs: dict[str, PdfJob] = {}
    _queue: list[tuple[str, Callable, tuple, dict]] = []
    _lock = threading.Lock()
    _worker_thread: threading.Thread | None = None
    _max_jobs = 50  # en eski tamamlanmış job'ları temizle

    @classmethod
    def submit(cls, fn: Callable, *args: Any, **kwargs: Any) -> str:
        """Yeni bir PDF üretim işi başlat ve job ID döndür."""
        job_id = uuid.uuid4().hex[:12]
        job = PdfJob(job_id=job_id)
        with cls._lock:
            cls._jobs[job_id] = job
            cls._queue.append((job_id, fn, args, kwargs))
            cls._cleanup_old_jobs()
            if cls._worker_thread is None or not cls._worker_thread.is_alive():
                cls._worker_thread = threading.Thread(
                    target=cls._worker, daemon=True, name="pdf-queue-worker"
                )
                cls._worker_thread.start()
        logger.info("PDF kuyruğuna iş eklendi: %s", job_id)
        return job_id

    @classmethod
    def get_result(cls, job_id: str) -> PdfJob | None:
        """Job sonucunu döndür (None = job bulunamadı)."""
        return cls._jobs.get(job_id)

    @classmethod
    def _worker(cls) -> None:
        """Kuyruktaki işleri sırayla çalıştır."""
        while True:
            item = None
            with cls._lock:
                if cls._queue:
                    item = cls._queue.pop(0)
            if item is None:
                break

            job_id, fn, args, kwargs = item
            job = cls._jobs.get(job_id)
            if job is None:
                continue

            job.status = "running"
            try:
                result = fn(*args, **kwargs)
                job.result = result
                job.status = "completed"
                logger.info("PDF tamamlandı: %s", job_id)
            except Exception as exc:
                job.error = str(exc)
                job.status = "failed"
                logger.error("PDF üretimi başarısız: %s — %s", job_id, exc)

    @classmethod
    def _cleanup_old_jobs(cls) -> None:
        """Tamamlanmış eski job'ları temizle (bellek sızıntısı önleme)."""
        now = time.monotonic()
        stale = [
            jid for jid, j in cls._jobs.items()
            if j.status in ("completed", "failed") and (now - j.created_at) > 600
        ]
        for jid in stale:
            del cls._jobs[jid]
