# Makro Ortodonti — Codebase Guide

## What this application is

**Makro Ortodonti** is a private-clinic operations application for a Turkish orthodontic lab. It manages the complete billing lifecycle between the lab and its referring dentist customers: work orders for orthodontic appliances, monthly doctor receipts (makbuzlar), collections, EUR-based invoicing with TRY conversion, and WhatsApp delivery of those receipts.

It is not a generic clinic or hospital system. There are no appointment slots, no patient scheduling, and no insurance workflows. The primary actors are:

- **Diş hekimleri (dentists)** — `Party` rows with `party_type = DENTIST`; the lab's paying customers
- **Ortodonti hastası (orthodontic patient)** — `patient_name` field on `WorkOrder`; the dentist's patient, not the lab's direct customer
- **Admin / Staff** — internal users operating the system

---

## Project layout

```
app/
  models/        SQLAlchemy models + invoice domain service
  routes/        Flask blueprints (one file per domain area)
  services/      PDF, e-mail, exchange-rate, security, WhatsApp services
  templates/     Jinja2 views
  static/        Design system CSS, JS, brand SVG, self-hosted vendor assets
tests/           Pytest unit + integration + Playwright e2e tests
migrations/      Alembic/Flask-Migrate schema history
data/            SQLite database, WhatsApp session DB, backups
run.py           Application entry point (dev + seed bootstrap)
```

---

## Critical files

| File | Role |
|---|---|
| `run.py` | Entry point; seeds DB on first run (44 Ana İşlemler + 10 Ekstra İşlemler, exchange rate, demo doctor + admin) |
| `app/__init__.py` | Application factory; registers blueprints, CSRF, Login, Migrate, security headers |
| `app/config.py` | All environment-variable configuration (`SECRET_KEY`, `ENCRYPTION_KEY`, `DATABASE_URL`, `TRUST_PROXY`, etc.) |
| `app/models/models.py` | **All domain models** — `Party`, `Treatment`, `WorkOrder`, `Invoice`, `InvoiceItem`, `Payment`, `Makbuz`, `MakbuzSendLog`, `ExchangeRate`, `Settings`, `User`, `WhatsAppSession`, `AuditLog`, `LoginAttempt` |
| `app/models/invoice_service.py` | EUR↔TRY arithmetic, invoice totals, KDV/discount calculation |
| `app/authz.py` | Central permission matrix (`admin = *`; `staff = clinical.view/edit, billing.view/edit, reports.view, messaging.use`) |
| `app/routes/dashboard.py` | Overview metrics: active dentist count, monthly work orders, monthly EUR total, draft/sent makbuz counts |
| `app/routes/parties.py` | Dentist CRUD + live Turkish-aware search + work order list |
| `app/routes/makbuzlar.py` | Monthly receipt generation, status transitions (draft → sent → paid) |
| `app/routes/payments.py` | Partial collection recording, overpayment guard |
| `app/routes/whatsapp.py` | QR-code connect flow, batch receipt send with 3 s inter-doctor delay, send log |
| `app/routes/reports.py` | Period receivables, aging, category breakdown |
| `app/services/search_service.py` | `tr_fold` (Turkish ASCII fold for search) + `tr_sort_key` (correct Turkish alphabet ordering) |
| `app/static/css/style.css` | **Design system** — all CSS custom properties live here |
| `app/templates/base.html` | Shell: topbar, sidebar, mobile bottom-nav, flash messages, exchange-rate staleness banner |
| `app/templates/components/sidebar.html` | Navigation sections: Çalışma alanı / İzleme / Araçlar |
| `migrations/` | Alembic history; `20260720_02` repopulates treatment catalogue (non-idempotent, run once) |

---

## Domain model quick reference

### Core flow

```
WorkOrder (apparatus built for a patient of a dentist)
  └─► Makbuz (monthly snapshot per dentist — draft → sent → paid)
        └─► MakbuzSendLog (each WhatsApp delivery attempt)

Invoice (EUR-denominated invoice to any Party)
  └─► InvoiceItem (treatment / product / service / lab / custom)
        └─► Payment (partial or full collection, EUR + TRY amounts)
```

### Key enums / constants (from `models.py`)

| Symbol | Values |
|---|---|
| `PartyType` | `DENTIST`, `PATIENT`, `DENTIST_CUSTOMER`, `COMPANY_CUSTOMER` |
| `TreatmentCategory` | `ana_islemler`, `ekstra_islemler` |
| `InvoiceItemType` | `TREATMENT`, `PRODUCT`, `SERVICE`, `LAB`, `CUSTOM` |
| `PaymentMethod` | `CASH`, `CARD`, `TRANSFER`, `CHECK`, `OTHER` |
| `Invoice.STATUS_*` | `pending`, `paid`, `overdue`, `cancelled` |
| `Makbuz.STATUS_*` | `draft`, `sent`, `paid` |
| `MONEY_SCALE` | `Decimal("0.01")` — all monetary values quantized here |
| `RATE_SCALE` | `Decimal("0.0001")` — exchange rates |

### `Settings.DEFAULTS` keys (clinic identity, used in PDF + UI)

`clinic_name`, `clinic_address`, `clinic_phone`, `clinic_email`, `clinic_logo_path`, `tax_id`, `invoice_prefix` (`"MKR"`), `invoice_next_number`, `invoice_footer_text`, `default_exchange_rate_source` (`"ecb"`), `currency_symbol_eur` (`"€"`), `currency_symbol_try` (`"₺"`), `whatsapp_session_id`, `whatsapp_phone_number`

---

## Design system

All tokens live in `app/static/css/style.css` `:root`.

**Colours**
| Token | Hex | Usage |
|---|---|---|
| `--ink-950` | `#102e3a` | Primary text, headings |
| `--ink-800` | `#244653` | Secondary text |
| `--ink-600` / `--ink-400` | `#58717b` | Muted / label text |
| `--canvas` | `#f4f7f7` | Page background |
| `--surface` | `#ffffff` | Cards, topbar |
| `--line` | `#dce8e9` | Borders |
| `--aqua-700` | `#0b6f70` | Primary action, active nav, icons |
| `--aqua-600` | `#20a6a2` | Hover |
| `--aqua-500` | `#39bfb3` | Focus ring fill, gradient |
| `--aqua-100` | `#def5f1` | Tint backgrounds |
| `--sky-500` | `#35afd0` | Exchange-rate strip, secondary accent |
| `--coral-500` | `#e27c67` | Aging bar, destructive |
| `--amber-500` | `#d8a03b` | Warnings |
| `--success-500` | `#176a4a` | Success states |
| `--danger-500` | `#cf5b62` | Error states |
| `--report-invoice` | `#39758c` | Report bar — issued |
| `--report-collected` | `#278468` | Report bar — collected |

**Layout**
- `--sidebar-width: 224px` (fixed left, desktop)
- `--topbar-height: 64px` (fixed top)
- `--radius-sm: 8px` / `--radius-md: 12px` / `--radius-lg: 18px`
- `--shadow-sm` / `--shadow-md`

**Typography**
- Body: `Manrope` (variable, 200–800), self-hosted at `vendor/fonts/manrope-variable.ttf`
- Display / headings / brand: `Familjen Grotesk` (variable, 400–700), self-hosted
- Bootstrap primary overridden to `--aqua-700`

**Component patterns**
- `.metric-card` — KPI tiles with decorative circle `::after`, `.metric-icon`, `.metric-label`, `.metric-value`
- `.rate-strip` — exchange-rate context strip with `.rate-strip-icon`
- `.page-eyebrow` — uppercased aqua section label above page titles
- `.report-trend-row` — 3-column grid: label / bar / value
- `.aging-row` — receivables aging rows with coral progress bar

---

## Technology stack

- **Python 3.13 / 3.14** (both CI-tested)
- **Flask + Flask-Login + Flask-WTF + Flask-SQLAlchemy**
- **SQLite** via SQLAlchemy 2, Alembic/Flask-Migrate; `Numeric` columns for all money
- **Jinja2 + Bootstrap 5** (self-hosted) + custom design system
- **fpdf2** for Turkish PDF invoice output
- **OpenPyXL** for Excel import of treatment catalogue and doctors
- **Neonize** for WhatsApp Web protocol (no paid API)
- **Gunicorn** production server — **must run with `--workers 1`** due to WhatsApp in-process thread
- **Pytest + branch coverage ≥ 90%** + Playwright Chromium e2e

---

## Authorization model

Defined in `app/authz.py`. Two roles:

- `admin` — full access (`*`)
- `staff` — `clinical.view`, `clinical.edit`, `billing.view`, `billing.edit`, `reports.view`, `messaging.use`

Admin-only: delete party/invoice/payment, all settings, KVKK export/anonymize (`privacy.audit`, `privacy.export`, `privacy.anonymize`), `settings.manage`.

---

## Goals and non-goals

**Goals:**
1. Complete monthly billing cycle for a Turkish orthodontic lab: work order entry → monthly receipt generation → WhatsApp delivery → collection recording
2. EUR-primary pricing with live ECB exchange rate, TRY equivalent on every document
3. KVKK compliance: audit log on all mutations, data export per person, anonymisation with open-invoice guard
4. Operate reliably for a small clinical team on SQLite without external services beyond SMTP

**Non-goals:**
- Multi-clinic / multi-tenant
- PostgreSQL / high-concurrency scale
- Appointment scheduling or clinical workflow beyond treatment cataloguing
- Paid WhatsApp Business API

---

## Key operational commands

```bash
# Dev
FLASK_DEBUG=true python run.py

# Schema upgrade
flask --app run:app db upgrade

# Scheduled jobs (cron/platform scheduler)
flask --app run:app refresh-exchange-rate
flask --app run:app purge-expired-audit-logs

# Tests
pytest
pytest --cov=app --cov-report=term-missing --cov-fail-under=90
pytest tests/e2e --browser chromium

# Production
gunicorn --workers 1 --bind 0.0.0.0:8000 "run:app"
```

---

## Turkish-language specifics

- All UI text, navigation labels, flash messages, and form labels are in **Turkish**.
- Search uses `tr_fold`: İ/ı→i, Ş/ş→s, Ğ/ğ→g, Ü/ü→u, Ö/ö→o, Ç/ç→c (registered as `tr_fold` SQLite function).
- Sorting uses `tr_sort_key` for correct Turkish alphabet order (ç after c, ı before i, etc.).
- Live search on the doctor list uses `?partial=1` to return only the `parties/_results.html` fragment without a full page reload.

---

## Security posture

- CSRF on all forms (Flask-WTF)
- Passwords: bcrypt; SMTP password: Fernet + `ENCRYPTION_KEY`
- Login lockout on failed attempts (`LoginAttempt` table)
- `AuditLog` records every ORM create/update/delete with actor, IP, `X-Request-ID`, and diff JSON
- CSP / `X-Content-Type-Options` / Referrer-Policy / Permissions-Policy on every response; HSTS only when `FORCE_HSTS=true`
- No third-party CDN calls at runtime (all vendor assets self-hosted)
- Production refuses to start if `SECRET_KEY` or `ENCRYPTION_KEY` is missing, < 32 chars, or equals the dev placeholder
