# Makro Ortodonti (v1.8.0) 🌟

[![Python Version](https://img.shields.io/badge/python-3.13%20%7C%203.14-blue.svg)](https://www.python.org/)
[![Flask Version](https://img.shields.io/badge/flask-3.x-green.svg)](https://flask.palletsprojects.com/)
[![Test Suite](https://img.shields.io/badge/pytest-passing-success.svg)]()

Makro Ortodonti; hasta ve diş hekimi müşteri kayıtlarını, iş emri ve aparey takiplerini, **TRY (₺)**, **EUR (€)** ve **USD ($)** çoklu para birimli dinamik/sabit kurlu faturalandırmayı, günlük/aylık/yıllık otomatik makbuzları, devreden borç takibini, WhatsApp bildirimlerini ve klinik raporlamayı tek noktadan yöneten Flask tabanlı klinik operasyon yazılımıdır.

---

## 🚀 v1.8.0 Yeni Özellikler & İyileştirmeler

- **🔌 JSON API Katmanı (`/api/v1/`)**: Salt okunur REST API endpoint'leri eklendi — parties, work-orders, makbuzlar, treatments, exchange-rate, dashboard. Gelecekteki mobil uygulama ve dış entegrasyonlar için hazır altyapı.
- **⚡ Arka Plan PDF Üretim Kuyruğu**: `PdfQueue` servisi ile büyük PDF'ler (çok sayıda makbuz/is emri) arka plan iş parçacığında üretilir; HTTP istek yanıtı engellenmez.
- **🌙 Dark Mode Toggle**: Navbar'daki tema değiştirme düğmesi ile açık/koyu tema geçişi. Tercih `localStorage`'da saklanır.
- **🧪 Kapsamlı Sınır Durumu Testleri**: Permission boundary, kilitli dönem bypass, stale kur uyarıları, category fallback ve KDV sınır testleri (23 yeni test).

### v1.8.0 Hata Düzeltmeleri & Kod Kalitesi

- **🔗 `whatsapp.py` Import Düzeltmesi**: `MONTHS` artık `app.constants`'dan, `STATUS_LABELS` yerine `MAKBUZ_STATUS_LABELS` kullanılıyor.
- **📦 `parties.py` Refactoring**: `_compute_monthly_totals()` ve `_compute_previous_debt()` helper fonksiyonları çıkarıldı; `detail_party` fonksiyonu sadeleştirildi.
- **🔑 ENCRYPTION_KEY Dokümantasyonu**: `config.py`'da Fernet şifreleme kullanımı açıklandı.
- **🔒 Brute Force Koruması Dokümantasyonu**: `auth.py` login fonksiyonuna koruma detayları eklendi.
- **🧬 Party/Patient Mimari Kararı**: `Party` (STI) ve `Patient` (legacy) modelleri docstring'ler ile dokümante edildi.
- **📝 `Treatment.price_eur` İsim Karmaşası**: Sütun adının historical olduğu, `base_price` property'sinin kullanılması gerektiği açıklandı.
- **🗂️ Test Dosyası Birleştirme**: `test_makbuz_fixes.py` → `test_makbuz.py`'a taşındı.
- **📦 requirements-dev.txt Genişletme**: `ruff`, `mypy`, `pre-commit` eklendi.
- **🔗 `__version__`**: 1.6.0 → 1.8.0

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

### 1. Yerel Geliştirme Ortamı

```bash
# Depoyu klonlayın ve sanal ortam oluşturun
python3 -m venv .venv
source .venv/bin/activate

# Bağımlılıkları yükleyin
python -m pip install -r requirements-dev.txt

# Çevre değişkenlerini kopyalayın
cp .env.example .env

# İlk kurulumda veritabanını oluşturun ve seed verilerini yükleyin
flask db-tools seed

# Uygulamayı başlatın
FLASK_DEBUG=true python run.py
```

Uygulama varsayılan olarak `http://127.0.0.1:5001` adresinde açılır.

### 2. CLI Komutları

```bash
# Veritabanı ve katalog verilerini yükleme
flask db-tools seed

# Günlük döviz kurunu güncelleme
flask refresh-exchange-rate

# Süresi dolmuş denetim kayıtlarını temizleme
flask purge-expired-audit-logs
```

### 3. Production Dağıtımı

```bash
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export ENCRYPTION_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export SESSION_COOKIE_SECURE=true
export FORCE_HSTS=true
export DATABASE_ENCRYPTION_AT_REST=true

flask db upgrade
gunicorn --workers 1 --bind 0.0.0.0:8000 "run:app"
```

> **Önemli Not:** WhatsApp entegrasyonu nedeniyle Gunicorn `--workers 1` ile çalıştırılmalıdır.

---

## 🧪 Testler ve Kapsama (Coverage)

Tüm iş mantığı, servis katmanı ve kilit kontrolleri Pytest ile kapsanmıştır (%90+ coverage):

```bash
# Birim ve entegrasyon testlerini çalıştırma
pytest

# Coverage raporu ve baraj kontrolü (%90)
pytest --cov=app --cov-report=term-missing --cov-fail-under=90

# E2E testleri (Playwright Chromium)
pytest tests/e2e --browser chromium
```

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
