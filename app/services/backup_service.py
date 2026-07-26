"""Veritabanı yedekleme servisi.

SQLite veritabanını `data/backups/` klasörüne kopyalar.
Her yedeğin dosya adı: makroortodonti_YYYYMMDD_HHMMSS.db

Otomatik yedekleme:  her gece saat 02:00'de scheduler tarafından çağrılır.
Elle yedekleme:      /settings/backup/create  POST endpoint'inden tetiklenir.
İndirme:             /settings/backup/download/<filename> GET endpoint'inden.
"""

import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Yedek dosya adı güvenlik filtresi (path traversal engellemek için)
_SAFE_FILENAME_RE = re.compile(r'^makroortodonti_\d{8}_\d{6}\.db$')

BACKUP_KEEP = 30  # saklanacak maksimum yedek sayısı


def _data_dir() -> Path:
    """data/ klasörünün tam yolu."""
    return Path(__file__).resolve().parent.parent.parent / "data"


def _backup_dir() -> Path:
    d = _data_dir() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _db_path() -> Path | None:
    """SQLAlchemy URI'sinden SQLite dosya yolunu çıkar."""
    try:
        from app.extensions import db
        uri: str = db.engine.url.database or ""
        if uri and uri != ":memory:":
            return Path(uri).resolve()
    except Exception:
        pass
    # Fallback: varsayılan konum
    candidate = _data_dir() / "makroortodonti.db"
    return candidate if candidate.exists() else None


def create_backup() -> Path:
    """Veritabanının anlık yedeğini alır ve yedek dosyasının yolunu döndürür.

    SQLite'ın kendi backup API'sini (wal_checkpoint dahil) kullanmak yerine
    dosyayı doğrudan kopyalarız — SQLite WAL modunda bile güvenlidir çünkü
    SQLite'ın SQLITE_CHECKPOINT_PASSIVE moduyla çalışan shutil.copy2, tutarlı
    bir snapshot üretir.  Daha güvenli bir alternatif için sqlite3.connect +
    .backup() kullanılabilir.
    """
    source = _db_path()
    if not source or not source.exists():
        raise FileNotFoundError(
            f"Veritabanı dosyası bulunamadı: {source!s}"
        )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = _backup_dir() / f"makroortodonti_{stamp}.db"

    # sqlite3 modülünün .backup() API'si WAL journal'ını da flusher — en güvenli yol.
    import sqlite3
    src_conn = sqlite3.connect(str(source))
    dst_conn = sqlite3.connect(str(dest))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    logger.info("Veritabanı yedeği alındı: %s", dest.name)
    _prune_old_backups()
    return dest


def list_backups() -> list[dict]:
    """Mevcut yedekleri yeniden eskiye sıralar."""
    backup_dir = _backup_dir()
    files = sorted(
        [f for f in backup_dir.iterdir() if _SAFE_FILENAME_RE.match(f.name)],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    result = []
    for f in files:
        stat = f.stat()
        ts_str = f.name[len("makroortodonti_"):-len(".db")]
        try:
            ts = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
            label = ts.strftime("%d.%m.%Y %H:%M:%S")
        except ValueError:
            label = ts_str
        result.append({
            "filename": f.name,
            "label": label,
            "size_kb": round(stat.st_size / 1024, 1),
        })
    return result


def get_backup_path(filename: str) -> Path | None:
    """Güvenli dosya adı doğrulamasıyla yedek dosyasının yolunu döndürür."""
    if not _SAFE_FILENAME_RE.match(filename):
        return None
    p = _backup_dir() / filename
    return p if p.exists() else None


def _prune_old_backups() -> None:
    """BACKUP_KEEP adedinden fazla eski yedeği siler."""
    backup_dir = _backup_dir()
    files = sorted(
        [f for f in backup_dir.iterdir() if _SAFE_FILENAME_RE.match(f.name)],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    for old in files[BACKUP_KEEP:]:
        try:
            old.unlink()
            logger.debug("Eski yedek silindi: %s", old.name)
        except OSError:
            pass


def scheduled_backup(app) -> None:
    """Scheduler tarafından her gece çağrılan görev."""
    with app.app_context():
        try:
            dest = create_backup()
            logger.info("Otomatik yedekleme tamamlandı: %s", dest.name)
        except Exception:
            logger.exception("Otomatik yedekleme başarısız")
