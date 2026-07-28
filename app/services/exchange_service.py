import logging
import threading

import requests
from datetime import date
from decimal import Decimal
from threading import Event, Lock

from app.extensions import db
from app.models.models import ExchangeRate

logger = logging.getLogger(__name__)

_auto_check_lock = Lock()
_last_auto_check_date: date | None = None
_shutdown_event = Event()


def fetch_tcmb_rates() -> dict[str, Decimal]:
    """Fetch EUR/TRY and USD/TRY exchange rates from TCMB official XML service."""
    import xml.etree.ElementTree as ET

    url = "https://www.tcmb.gov.tr/kurlar/today.xml"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    rates: dict[str, Decimal] = {}

    for currency_elem in root.findall("Currency"):
        code = currency_elem.get("CurrencyCode")
        if code in ("EUR", "USD"):
            buying = currency_elem.findtext("ForexBuying") or currency_elem.findtext("BanknoteBuying")
            if buying:
                cleaned = buying.strip().replace(",", ".")
                if cleaned:
                    rates[code] = Decimal(cleaned)

    return rates


def fetch_eur_try_rate() -> Decimal:
    """Fetch current EUR/TRY rate from public providers with fallback."""
    providers = [
        "https://api.frankfurter.dev/v2/rate/EUR/TRY",
        "https://api.frankfurter.app/latest?from=EUR&to=TRY",
    ]

    last_error: Exception | None = None
    for url in providers:
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            if "rate" in data:
                return Decimal(str(data["rate"]))

            if "rates" in data and "TRY" in data["rates"]:
                return Decimal(str(data["rates"]["TRY"]))

            raise ValueError(f"Unexpected response schema from provider: {url}")
        except Exception as exc:
            last_error = exc

    # TCMB fallback
    try:
        tcmb_rates = fetch_tcmb_rates()
        if "EUR" in tcmb_rates:
            return tcmb_rates["EUR"]
    except Exception as exc:
        last_error = exc

    raise RuntimeError(f"Failed to fetch EUR/TRY from providers and TCMB: {last_error}")


def fetch_usd_try_rate() -> Decimal | None:
    """Fetch current USD/TRY rate from public providers with fallback."""
    providers = [
        "https://api.frankfurter.dev/v2/rate/USD/TRY",
        "https://api.frankfurter.app/latest?from=USD&to=TRY",
    ]

    for url in providers:
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            if "rate" in data:
                return Decimal(str(data["rate"]))

            if "rates" in data and "TRY" in data["rates"]:
                return Decimal(str(data["rates"]["TRY"]))
        except Exception:
            continue

    # TCMB fallback
    try:
        tcmb_rates = fetch_tcmb_rates()
        if "USD" in tcmb_rates:
            return tcmb_rates["USD"]
    except Exception:
        pass

    return None


def fetch_and_store_rate() -> Decimal:
    """Fetch and store today's EUR/TRY and USD/TRY rates."""
    rate_value = fetch_eur_try_rate()
    usd_rate = fetch_usd_try_rate()
    today = date.today()

    existing = db.session.execute(
        db.select(ExchangeRate).where(
            ExchangeRate.rate_date == today,
            ExchangeRate.source == "ecb",
        )
    ).scalar_one_or_none()

    if existing:
        existing.eur_to_try = rate_value
        if usd_rate is not None:
            existing.usd_to_try = usd_rate
    else:
        db.session.add(ExchangeRate(
            rate_date=today,
            eur_to_try=rate_value,
            usd_to_try=usd_rate,
            source="ecb",
        ))

    db.session.commit()
    return rate_value


def get_rate_for_date(target_date: date) -> ExchangeRate | None:
    """Return the exchange rate row effective on or before target_date."""
    return db.session.execute(
        db.select(ExchangeRate)
        .where(ExchangeRate.rate_date <= target_date)
        .order_by(ExchangeRate.rate_date.desc())
        .limit(1)
    ).scalar_one_or_none()


def get_latest_rate() -> Decimal | None:
    """Get the most recent EUR/TRY rate."""
    rate = db.session.execute(
        db.select(ExchangeRate)
        .order_by(ExchangeRate.rate_date.desc())
        .limit(1)
    ).scalar_one_or_none()
    return Decimal(str(rate.eur_to_try)) if rate else None


def get_latest_usd_rate() -> Decimal | None:
    """Get the most recent USD/TRY rate, fetching live if DB is missing it."""
    rate = db.session.execute(
        db.select(ExchangeRate)
        .order_by(ExchangeRate.rate_date.desc())
        .limit(1)
    ).scalar_one_or_none()
    if rate and rate.usd_to_try is not None:
        return Decimal(str(rate.usd_to_try))

    # DB'de kayit var ama USD kuru yoksa veya hic kayit yoksa canli çek
    try:
        usd_rate = fetch_usd_try_rate()
        if usd_rate is not None:
            if rate and rate.usd_to_try is None:
                rate.usd_to_try = usd_rate
                db.session.commit()
            return usd_rate
    except Exception:
        pass

    return None


def get_rate_health(max_age_days: int = 2) -> dict:
    """Return current rate health information for UI warnings."""
    latest = db.session.execute(
        db.select(ExchangeRate)
        .order_by(ExchangeRate.rate_date.desc())
        .limit(1)
    ).scalar_one_or_none()

    if latest is None:
        return {
            "exists": False,
            "is_stale": True,
            "age_days": None,
            "last_date": None,
            "last_rate": None,
        }

    age_days = (date.today() - latest.rate_date).days
    return {
        "exists": True,
        "is_stale": age_days > max_age_days,
        "age_days": age_days,
        "last_date": latest.rate_date,
        "last_rate": Decimal(str(latest.eur_to_try)),
    }


def ensure_daily_rate(max_age_days: int = 2) -> dict:
    """Fetch today's rate once per process day asynchronously and return current health snapshot immediately."""
    global _last_auto_check_date

    today = date.today()
    if _last_auto_check_date == today:
        return get_rate_health(max_age_days=max_age_days)

    with _auto_check_lock:
        if _last_auto_check_date == today:
            return get_rate_health(max_age_days=max_age_days)

        _last_auto_check_date = today

        # Start asynchronous fetch in background thread so it doesn't block request
        from flask import current_app
        # Retrieve the real App object from current_app proxy
        app = current_app._get_current_object()

        def worker():
            with app.app_context():
                try:
                    fetch_and_store_rate()
                except Exception as exc:
                    logger.warning("Arka plan kur güncelleme başarısız: %s", exc)

        t = threading.Thread(target=worker, daemon=True, name="exchange-rate-fetch")
        t.start()
        # Uygulama kapanırken thread'in commit tamamlaması için kısa süre bekle
        t.join(timeout=5)

        # Return status based on what is currently in DB immediately, no waiting!
        status = get_rate_health(max_age_days=max_age_days)
        status["updated_today"] = False
        return status
