"""Türkçe duyarlı arama yardımcıları.

SQLite'ın LIKE'ı yalnızca ASCII harflerde büyük/küçük harf bağımsızdır:
"şahin" araması "Şahin"i, "pinar" araması "Pınar"ı bulamaz. Burada hem
sorgu hem kolon değeri ortak bir ASCII iskelete indirgenir (İ/ı→i, Ş/ş→s,
Ğ/ğ→g, Ü/ü→u, Ö/ö→o, Ç/ç→c), böylece Türkçe karakterli isimler klavye
düzeninden bağımsız bulunur. SQLite bağlantılarına ``tr_fold`` fonksiyonu
otomatik kaydedilir; başka bir veritabanına geçilirse ``lower()`` tabanlı
yaklaşık davranışa düşülür.
"""

import sqlite3

from sqlalchemy import event, func
from sqlalchemy.engine import Engine

_FOLD_MAP = str.maketrans({
    "İ": "i", "I": "i", "ı": "i",
    "Ş": "s", "ş": "s",
    "Ğ": "g", "ğ": "g",
    "Ü": "u", "ü": "u",
    "Ö": "o", "ö": "o",
    "Ç": "c", "ç": "c",
    "Â": "a", "â": "a",
    "Î": "i", "î": "i",
    "Û": "u", "û": "u",
})


def tr_fold(value) -> str:
    """Metni aramaya uygun ASCII iskelete indirger (Türkçe harf eşlemesiyle)."""
    if value is None:
        return ""
    return str(value).translate(_FOLD_MAP).lower()


# --- Türkçe alfabetik sıralama --------------------------------------------
# Aramanın aksine sıralama harfleri KATLAMAZ; her harf Türk alfabesindeki
# gerçek yerine yerleştirilir: ç, c'den SONRA; ı, i'den ÖNCE; ğ>g, ö>o, ş>s,
# ü>u. Türkçede olmayan q/w/x Latin komşularına eklenir.
_TR_LOWER = str.maketrans({"İ": "i", "I": "ı"})

# Sıralama önceliği: boşluk < rakam < Türk alfabesi (yabancı q/w/x dahil).
_TR_ALPHABET = "abcçdefgğhıijklmnoöpqrsştuüvwxyz"
_SORT_MASTER = " 0123456789" + _TR_ALPHABET
_SORT_RANK = {ch: idx for idx, ch in enumerate(_SORT_MASTER)}
# Bilinmeyen karakterler (noktalama, aksanlı harfler) harflerden sonra gelsin.
_UNKNOWN_RANK = len(_SORT_MASTER)


def tr_collation_key(value) -> str:
    """Metni, ikili (binary) karşılaştırmayla Türk alfabesi sırasını veren bir
    anahtara dönüştürür. Her karakter, Türkçe sıradaki konumuna göre tek bir
    ASCII bayta eşlenir; böylece SQLite'ın varsayılan BINARY harmanı doğru
    Türkçe sırayı üretir."""
    if value is None:
        return ""
    text = str(value).translate(_TR_LOWER).lower()
    out = []
    for ch in text:
        rank = _SORT_RANK.get(ch)
        if rank is None:
            out.append(chr(0x30 + _UNKNOWN_RANK))
            out.append(ch)
        else:
            out.append(chr(0x30 + rank))
    return "".join(out)


def _sqlite_tr_fold(value):
    if value is None:
        return None
    return tr_fold(value)


def _sqlite_tr_sort_key(value):
    if value is None:
        return None
    return tr_collation_key(value)


@event.listens_for(Engine, "connect")
def _register_sqlite_functions(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        dbapi_connection.create_function(
            "tr_fold", 1, _sqlite_tr_fold, deterministic=True
        )
        dbapi_connection.create_function(
            "tr_sort_key", 1, _sqlite_tr_sort_key, deterministic=True
        )


def _is_sqlite() -> bool:
    from app.extensions import db

    return db.engine.dialect.name == "sqlite"


def tr_contains(column, query_text: str):
    """Türkçe duyarlı, büyük/küçük harf bağımsız ``LIKE %...%`` koşulu."""
    folded = tr_fold(query_text)
    if _is_sqlite():
        return func.tr_fold(column).contains(folded, autoescape=True)
    return func.lower(column).contains(folded, autoescape=True)


def tr_equals(column, query_text: str):
    """Türkçe duyarlı, büyük/küçük harf bağımsız eşitlik koşulu."""
    folded = tr_fold(query_text)
    if _is_sqlite():
        return func.tr_fold(column) == folded
    return func.lower(column) == folded


def tr_order(column):
    """Türkçe alfabetik ORDER BY ifadesi.

    SQLite kod noktasına göre sıraladığından Ç/Ö/Ş/Ü/Ğ/İ gibi harfler 'z'den
    sonra gelip liste sonuna yığılır. ``tr_sort_key`` her harfi Türk
    alfabesindeki gerçek konumuna yerleştirir: Canan < Çağla (ç, c'den sonra),
    Irmak < İpek (ı, i'den önce), o < ö, s < ş, u < ü, g < ğ. SQLite dışı bir
    veritabanında ``lower()`` tabanlı yaklaşık davranışa düşülür.
    """
    if _is_sqlite():
        return func.tr_sort_key(column)
    return func.lower(column)
