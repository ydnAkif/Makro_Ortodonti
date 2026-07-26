"""Uygulama genelinde paylaşılan sabitler.

Bu modül tek doğru kaynak (single source of truth) olarak tasarlanmıştır;
aynı sabitin birden fazla dosyada tanımlanmasını (DRY ihlali) önler.
"""

# ---------------------------------------------------------------------------
# Türkçe ay isimleri  (numara, isim) çifti
# ---------------------------------------------------------------------------
MONTHS: list[tuple[int, str]] = [
    (1, "Ocak"), (2, "Şubat"), (3, "Mart"), (4, "Nisan"),
    (5, "Mayıs"), (6, "Haziran"), (7, "Temmuz"), (8, "Ağustos"),
    (9, "Eylül"), (10, "Ekim"), (11, "Kasım"), (12, "Aralık"),
]

# İndeks tabanlı erişim için tuple versiyonu: MONTH_NAMES[ay_no] → "Ocak"
# 0 indeksli boşluk kasıtlıdır; ay numaraları 1'den başlar.
MONTH_NAMES: tuple[str, ...] = ("", ) + tuple(name for _, name in MONTHS)

# ---------------------------------------------------------------------------
# Durum etiketleri
# ---------------------------------------------------------------------------
MAKBUZ_STATUS_LABELS: dict[str, str] = {
    "draft": "Taslak",
    "sent": "Tahsilat bekliyor",
    "paid": "Ödendi",
}
