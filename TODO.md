# Makro Ortodonti — Yapılacaklar (TODO) ve v2.0 Yol Haritası

> **Sürüm**: v1.8.0  
> **Mimari Seviye**: A+ (95+)  
> **Test Durumu**: 484 Passed | 0 Error | 0 Warning | %89+ Coverage

---

## ✅ v1.8.0 Sürümünde Tamamlananlar

- [x] **JSON API Katmanı (`/api/v1/`)**: Parties, work-orders, makbuzlar, treatments, exchange-rate, dashboard endpoint'leri eklendi.
- [x] **Arka Plan PDF Üretim Kuyruğı**: `PdfQueue` servisi ile büyük PDF'ler threading ile arka planda üretilir.
- [x] **Dark Mode Toggle**: Navbar tema değiştirme düğmesi + localStorage tercih saklama.
- [x] **Sınır Durumu Testleri**: Permission boundary, kilitli dönem bypass, stale kur, category fallback, KDV sınır testleri (23 yeni test).
- [x] **whatsapp.py Import Düzeltmesi**: `MONTHS` artık `app.constants`'dan import ediliyor.
- [x] **parties.py Refactoring**: Helper fonksiyonları çıkarıldı, `detail_party` sadeleştirildi.
- [x] **Dokümantasyon İyileştirmeleri**: ENCRYPTION_KEY, brute force koruması, Party/Patient mimarisi, price_eur isim karmaşası dokümante edildi.
- [x] **Test Dosyası Birleştirme**: `test_makbuz_fixes.py` → `test_makbuz.py`'a taşındı.
- [x] **requirements-dev.txt**: `ruff`, `mypy`, `pre-commit` eklendi.
- [x] **conftest.py Fixture Düzeltmesi**: DENTIST partisi test fixture'ı iyileştirildi.

---

## 🚀 Gelecek Yol Haritası (v2.0 Planları)

### 🔐 1. Detaylı Kullanıcı & Rol Yetkilendirme Sistemi (Staff Role Restrictions)
- [ ] **Admin ve Kullanıcı (Staff) Rol Kısıtlamaları**:
  - Şu anda Admin tüm yetkilere (`*`) sahip olup sınırsız işlem yapabilmektedir.
  - İleride eklenecek `staff` (sekreter/muhasebeci) rolü için:
    - Manuel ödeme hareketi silme ve geçmiş makbuz iptali yetkileri sınırlandırılacak.
    - Sadece onaylı süreçlerde kayıt girebilme imkanı sunulacak.

### 🎨 1. Arayüz ve Kullanıcı Deneyimi (UI/UX)
- [ ] **Diğer Listelerde Mobil Kart Dönüşümü**:
  - `makbuzlar/list.html` ve `reports/index.html` sayfalarındaki geniş tablolar için mobilde dikey kart görünümü eklenecek.
- [x] **Dark Mode Tema Değiştirici Düğmesi (UI Toggle)**: ✅ v1.8.0'da tamamlandı.
- [ ] **Ciro & Tahsilat Trend Grafikleri**:
  - Raporlar paneline Chart.js / ApexCharts entegrasyonu ile grafiksel görselleştirme eklenecek.

---

### ⚡ 2. Altyapı ve Veritabanı (Infrastructure & Database)
- [ ] **WorkOrder JSON Column Dönüşümü**:
  - `apparatus_type` ve `extra_addons` alanları Text → JSON sütununa dönüştürülecek. `tr_contains` LIKE araması SQL JSON fonksiyonlarına taşınacak.
- [ ] **PostgreSQL Migration Desteği (İsteğe Bağlı)**:
  - Laboratuvar eşzamanlı personel ve hekim sayısı arttığında SQLite'tan PostgreSQL'e geçiş ve `pg_trgm` indeksleme desteği sağlanacak.
- [ ] **Dağıtık WhatsApp Kilit Yapısı (Redis Lock)**:
  - Multi-node Gunicorn/Kubernetes ortamına geçilirse `flock` yerine Redis Distributed Lock entegrasyonu sağlanacak.

---

### 📱 3. Müşteri Portalı ve Bildirimler (Customer Portal & Reminders)
- [ ] **Diş Hekimi Müşteri Portalı (Dentist Self-Service)**:
  - Diş hekimlerinin kendi kullanıcı hesaplarıyla sisteme girip iş emirlerini ve makbuzlarını izleyebilecekleri müşteri portalı eklenecek.
- [ ] **Otomatik Ödeme Hatırlatıcı Cron Job**:
  - Vadesi geçen alacaklar için periyodik otomatik WhatsApp / SMS hatırlatma altyapısı kurulacak.
