# Makro Ortodonti (v2.2.1) 🌟

[![Python Version](https://img.shields.io/badge/python-3.13%20%7C%203.14-blue.svg)](https://www.python.org/)
[![Flask Version](https://img.shields.io/badge/flask-3.x-green.svg)](https://flask.palletsprojects.com/)
[![Test Suite](https://img.shields.io/badge/pytest-passing-success.svg)]()

Makro Ortodonti; hasta ve diş hekimi müşteri kayıtlarını, iş emri ve aparey takiplerini, **TRY (₺)**, **EUR (€)** ve **USD ($)** çoklu para birimli dinamik/sabit kurlu faturalandırmayı, günlük/aylık/yıllık otomatik makbuzları, devreden borç takibini, WhatsApp bildirimlerini ve klinik raporlamayı tek noktadan yöneten Flask tabanlı klinik operasyon yazılımıdır.

---

## 📐 v2.2.1 Hassas Tablo Hizalaması & Header Dönüşümü

- **📐 Evrensel Header & Hizalama Sistemi**: Tüm tablolarda başlık hücreleri (`<th>`) ile gövde hücreleri (`<td>`) jilet gibi dikey çizgide eşlendi.
- **🔢 `tabular-nums` Basamak Hizalaması**: Finansal kolonlardaki sayılar (`text-end`) basamak ve virgül hizasına göre dikeyde kusursuz sıralandı.
- **📌 Sabit Sütun Genişlikleri**: Tarih (`110px`), Telefon (`150px`), Bakiye (`140px`) ve Eylem (`160px`) sütunlarına korumalı genişlikler atandı.

---

## 💎 v2.2.0 Modern Doktorlar UI & Kart Izgarası (Redesign)

- **🎴 Doktor Kart Izgarası (Card Grid View)**: Hekim kayıtları için dairesel gradient başharf balonları (**AN** -> Aklen Anıl), doğrudan WhatsApp erişimi ve borç durumu rozetleri içeren modern 3-kolonlu kart tasarımı.
- **📑 Sadeleştirilmiş Modern Tablo**: Tekrarlayan hantal butonlar ve sıfır sütunları yerine birleştirilmiş akıllı finans hücresi ve temiz satır hover'ları.
- **📊 Üst Metrik Kartları**: Doktorlar listesinin üzerinde 3 adet canlı istatistik kartı (Toplam Hekim, Toplam İş Hacmi, Açık Bakiye).
- **🔀 Görünüm Değiştirici (Toggle)**: Kart ve Tablo görünüm modları arasında tek tıkla geçiş ve `localStorage` tercihi saklama.

---

## 🚀 v2.1.0 Yeni Tasarım & UX Dönüşümü

- **🏷️ Soft Tint Badges & İkonlar**: Durum rozetleri yumuşak HSL saydam renk tonları, ikonlar ve mikro parlama efektleriyle yenilendi.
- **🔔 Glassmorphic Notice Strips**: Canlı yanıp sönen uyarı noktaları (`status-pulse-dot`) ve cam efektli duyuru bantları.
- **📊 İş Emri Süreç Steppers**: 4 adımlı görsel iş emri durum ilerleme göstergesi (`Sipariş` ➔ `Üretim` ➔ `Kontrol` ➔ `Teslim`).
- **💳 Makbuz Ödeme Doluluk Çubukları**: Makbuz listesinde tahsilat oranını gösteren canlı yeşil gradient progress bar.
- **🔍 `Cmd + K` Hızlı Arama Paleti**: Tüm sistemde `Cmd+K` / `Ctrl+K` kısayoluyla tetiklenen modal arama ekranı.
- **📱 Mobilde Floating Action Button (FAB)**: Mobil cihazlarda hızlı erişim sağlayan dairesel `+` eylem butonu.

---

## 🚀 v2.0.0 Önceki Özellikler & İyileştirmeler

- **🔌 JSON API Katmanı (`/api/v1/`)**: Salt okunur REST API endpoint'leri eklendi — parties, work-orders, makbuzlar, treatments, exchange-rate, dashboard. Gelecekteki mobil uygulama ve dış entegrasyonlar için hazır altyapı.
- **⚡ Arka Plan PDF Üretim Kuyruğu**: `PdfQueue` servisi ile büyük PDF'ler (çok sayıda makbuz/is emri) arka plan iş parçacığında üretilir; HTTP istek yanıtı engellenmez.
- **🌙 Dark Mode Toggle**: Navbar'daki tema değiştirme düğmesi ile açık/koyu tema geçişi. Tercih `localStorage`'da saklanır.
- **🧪 Kapsamlı Sınır Durumu Testleri**: Permission boundary, kilitli dönem bypass, stale kur uyarıları, category fallback ve KDV sınır testleri (23 yeni test).

### v2.0.0 Hata Düzeltmeleri & Kod Kalitesi

- **🔗 `whatsapp.py` Import Düzeltmesi**: `MONTHS` artık `app.constants`'dan, `STATUS_LABELS` yerine `MAKBUZ_STATUS_LABELS` kullanılıyor.
- **📦 `parties.py` Refactoring**: `_compute_monthly_totals()` ve `_compute_previous_debt()` helper fonksiyonları çıkarıldı; `detail_party` fonksiyonu sadeleştirildi.
- **🔑 ENCRYPTION_KEY Dokümantasyonu**: `config.py`'da Fernet şifreleme kullanımı açıklandı.
- **🔒 Brute Force Koruması Dokümantasyonu**: `auth.py` login fonksiyonuna koruma detayları eklendi.
- **🧬 Party/Patient Mimari Kararı**: `Party` (STI) ve `Patient` (legacy) modelleri docstring'ler ile dokümante edildi.
- **📝 `Treatment.price_eur` İsim Karmaşası**: Sütun adının historical olduğu, `base_price` property'sinin kullanılması gerektiği açıklandı.
- **🗂️ Test Dosyası Birleştirme**: `test_makbuz_fixes.py` → `test_makbuz.py`'a taşındı.
- **📦 requirements-dev.txt Genişletme**: `ruff`, `mypy`, `pre-commit` eklendi.
- **🔗 `__version__`**: 1.8.0 → 2.0.0

---

## ✨ Öne Çıkan Özellikler

- **Hekim ve İş Emri Yönetimi**: Diş hekimleri, aparey türleri (Ana / Ekstra İşlemler) ve hasta takibi.
- **TRY / EUR / USD Çoklu Para Birimi**: Sabit fatura kuru, günlük TCMB/ECB otomatik kur güncellemesi.
- **Aylık / Yıllık Otomatik Makbuz & Dönem Kilidi**: Otomatik taslak makbuz üretimi, kesinleşen dönemlerin kilitlenmesi.
- **WhatsApp Web Entegrasyonu (Neonize)**: Ücretsiz Go/Neonize altyapısı ile makbuz ve mesaj gönderimi.
- **Türkçe Karakter / Akıllı Arama (`tr_fold` & `tr_order`)**: İ/ı, Ş/ş, Ğ/ğ harflerine duyarlı sıralama ve canlı arama.
- **Güvenlik & KVKK Uyumu**: CSRF koruması, bcrypt parola şifreleme, Fernet SMTP şifrelemesi, audit kayıtları ve KVKK anonimleştirme.

---

## 🛠️ Kurulum ve Çalıştırma

Proje `FLASK_APP` ortam değişkeni veya `.flaskenv` kullanmaz; bu yüzden her `flask ...`
komutunda uygulamayı **`--app run:app`** ile açıkça belirtmek gerekir — aksi hâlde
`flask` komutu "Could not locate a Flask application" hatası verir.

### 1. Yerel Geliştirme Ortamı

```bash
# Depoyu klonlayın ve içine girin
git clone https://github.com/ydnAkif/Makro_Ortodonti.git
cd Makro_Ortodonti

# Sanal ortam oluşturun ve etkinleştirin
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Bağımlılıkları yükleyin
python -m pip install -r requirements-dev.txt

# Çevre değişkenlerini kopyalayın
cp .env.example .env
```

`.env` dosyasını açıp **`SECRET_KEY`** ve **`ENCRYPTION_KEY`** için gerçek, rastgele
değerler üretip yapıştırın (placeholder değerle bırakırsanız aşağıdaki `flask ...`
komutlarının hiçbiri çalışmaz — `FLASK_DEBUG=true` bu kontrolü *yalnızca*
`python run.py` ile başlatırken atlatır, `flask` CLI komutlarında atlatmaz):

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'   # SECRET_KEY için
python -c 'import secrets; print(secrets.token_urlsafe(48))'   # ENCRYPTION_KEY için
```

Üretilen iki değeri `.env` içindeki `SECRET_KEY=` ve `ENCRYPTION_KEY=` satırlarına yazın.

> **Not:** Bu depo `data/makroortodonti.db` dosyasını (örnek/demo verisiyle birlikte)
> doğrudan sürüm kontrolüne dahil eder. Yani depoyu klonladığınızda veritabanı zaten
> dolu gelir ve `flask db-tools seed` var olan `admin` hesabını bulup **yeni bir şifre
> üretmez** (idempotent seed — mevcut kullanıcıya dokunmaz). Kendi admin şifrenizi
> bilmeden başlamak isterseniz önce bu dosyayı silin:
> ```bash
> rm -f data/makroortodonti.db data/makroortodonti.db-wal data/makroortodonti.db-shm
> ```

```bash
# Veritabanını (yeniden) oluşturun ve seed verilerini yükleyin
# (üretilen admin şifresi yalnızca bu ilk çalıştırmada terminale yazdırılır — not edin)
flask --app run:app db-tools seed

# Uygulamayı başlatın
FLASK_DEBUG=true python run.py
```

Uygulama varsayılan olarak `http://127.0.0.1:5001` adresinde açılır; `admin` kullanıcı adı
ve az önce terminale yazdırılan şifreyle giriş yapabilirsiniz.

### 2. CLI Komutları

```bash
# Veritabanı ve katalog verilerini yükleme
flask --app run:app db-tools seed

# Şema güncellemelerini uygulama (yeni migration eklendiğinde)
flask --app run:app db upgrade

# Günlük döviz kurunu güncelleme
flask --app run:app refresh-exchange-rate

# Süresi dolmuş denetim kayıtlarını temizleme
flask --app run:app purge-expired-audit-logs
```

### 3. Production Dağıtımı

```bash
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export ENCRYPTION_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export SESSION_COOKIE_SECURE=true
export FORCE_HSTS=true

flask --app run:app db upgrade
gunicorn --workers 1 --bind 0.0.0.0:8000 "run:app"
```

> **Önemli Not:** WhatsApp entegrasyonu nedeniyle Gunicorn `--workers 1` ile çalıştırılmalıdır.
>
> **Diskte şifreleme:** Uygulama, SQLite veritabanı dosyasını kendisi şifrelemez (yalnızca SMTP şifresi gibi belirli hassas alanlar `ENCRYPTION_KEY` ile Fernet şifrelenir — bkz. `security_service.py`). KVKK kapsamındaki verinin diskte şifrelenmesi gerekiyorsa işletim sistemi seviyesinde tam disk şifrelemesi (LUKS/FileVault/BitLocker) veya SQLCipher gibi bir çözüm operatör tarafından ayrıca kurulmalıdır.

---

## 🧪 Testler ve Kapsama (Coverage)

Tüm iş mantığı, servis katmanı ve kilit kontrolleri Pytest ile kapsanmıştır (%90+ coverage):

```bash
# Tüm testler (e2e/Playwright dahil)
pytest

# Hızlı yol: yalnızca birim/entegrasyon testleri (e2e hariç)
pytest -m "not e2e"

# Coverage raporu ve baraj kontrolü (%90)
pytest --cov=app --cov-report=term-missing --cov-fail-under=90

# Yalnızca E2E testleri — iki eşdeğer yol:
pytest -m e2e --browser chromium          # marker tabanlı (auto-marker ile)
pytest tests/e2e --browser chromium       # dizin tabanlı
```

> **Not:** `tests/e2e/` altındaki tüm testlere `e2e` marker'ı `conftest.py` içindeki
> `pytest_collection_modifyitems` hook'u tarafından **otomatik olarak uygulanır** —
> tek tek `@pytest.mark.e2e` yazmak gerekmez. Her iki çalıştırma yöntemi de aynı
> testleri kapsar.

---

## 📁 Proje Klasör Yapısı

```
MakroOrtoDonti/
├── app/
│   ├── cli.py                    # CLI komut grupları (db-tools)
│   ├── authz.py                  # Merkezi yetki matrisi
│   ├── constants.py              # Uygulama sabitleri (MONTHS, STATUS_LABELS)
│   ├── models/                   # SQLAlchemy 2.0 Mapped modelleri
│   ├── routes/                   # Thin Controller (Blueprints)
│   │   └── api.py                # JSON API (/api/v1/)
│   ├── services/                 # İş mantığı ve Domain servisleri
│   │   ├── party_service.py      # Hekim & İş Emri domain servisi
│   │   ├── pdf_queue.py          # Arka plan PDF üretim kuyruğu
│   │   ├── makbuz_pdf_service.py # Makbuz PDF üretimi
│   │   ├── whatsapp_service.py   # WhatsApp Neonize entegrasyonu
│   │   └── search_service.py     # Türkçe duyarlı arama/sıralama
│   ├── static/                   # HSL tasarım sistemi, CSS ve Vanilla JS
│   └── templates/                # Jinja2 HTML şablonları & bileşenler
├── data/                         # SQLite veritabanı ve oturum dosyaları
├── migrations/                   # Alembic şema taşıma geçmişi
├── tests/                        # Pytest test suitleri (484+ test)
├── run.py                        # Uygulama başlatıcı
└── README.md                     # Proje dokümantasyonu
```
