import json
import logging
import os
import time

from flask import Flask, request, url_for

from .config import Config, is_insecure_secret
from .extensions import db, login_manager, csrf, migrate
from . import user_loader  # noqa: F401 - registers user_loader


__version__ = "2.0.0"


logger = logging.getLogger(__name__)

# ── Request-scoped cache for settings that rarely change ──────────────
_settings_cache: dict[str, tuple[float, str]] = {}
_SETTINGS_CACHE_TTL = 300  # 5 minutes


def _get_cached_setting(key: str, default: str = "") -> str:
    """Return a Settings value with a short in-process TTL cache."""
    now = time.monotonic()
    cached = _settings_cache.get(key)
    if cached and (now - cached[0]) < _SETTINGS_CACHE_TTL:
        return cached[1]
    try:
        from .models.models import Settings
        row = db.session.execute(
            db.select(Settings.value).where(Settings.key == key)
        ).scalar_one_or_none()
        value = row if row else default
    except Exception:
        logger.debug("Settings '%s' okunamadı", key, exc_info=True)
        value = default
    _settings_cache[key] = (now, value)
    return value


def invalidate_settings_cache(key: str | None = None) -> None:
    """Clear the settings cache. If *key* is given, only that entry."""
    if key:
        _settings_cache.pop(key, None)
    else:
        _settings_cache.clear()


def _page_url(page: int) -> str:
    """Build a URL for the current endpoint with a different page number."""
    args = request.args.to_dict(flat=True)
    args.pop("partial", None)
    args["page"] = page
    return url_for(request.endpoint, **(request.view_args or {}), **args)


def create_app(config_class=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    if not app.testing and not app.debug:
        invalid_keys = [
            key
            for key in ("SECRET_KEY", "ENCRYPTION_KEY")
            if is_insecure_secret(app.config.get(key))
        ]
        if invalid_keys:
            names = ", ".join(invalid_keys)
            raise RuntimeError(
                f"{names} eksik, kısa veya güvenli olmayan varsayılan değeri kullanıyor. "
                "Production başlamadan önce her anahtar için ayrı, kalıcı ve güçlü "
                "bir değer tanımlayın."
            )

    if app.config.get("TRUST_PROXY"):
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    os.makedirs(os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"), exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)

    def _fromjson(s):
        if not s:
            return []
        try:
            return json.loads(s)
        except (json.JSONDecodeError, TypeError):
            return []

    app.jinja_env.filters["fromjson"] = _fromjson

    from .services.validation_service import normalize_optional_text

    app.jinja_env.filters["clean_optional"] = normalize_optional_text

    def _currency_symbol(currency):
        return {"TL": "₺", "EUR": "€", "USD": "$"}.get(currency, "₺")

    app.jinja_env.filters["currency_symbol"] = _currency_symbol

    from .services.validation_service import format_tr_phone
    app.jinja_env.filters["phone_display"] = format_tr_phone

    # Register transactional audit listeners before handling requests.
    from .services import audit_service  # noqa: F401
    # Registers the Turkish-aware tr_fold() function on SQLite connections.
    from .services import search_service  # noqa: F401
    from .services.observability import init_observability
    init_observability(app)

    # Auto-fetch exchange rates once per calendar day (non-blocking background).
    # ensure_daily_rate() itself no-ops on every call after the first one for
    # the current day (see its own _last_auto_check_date guard), so this must
    # run on every request rather than being gated again here — a per-process
    # "only once, ever" guard would mean the rate never refreshes past day 1
    # on a long-lived gunicorn worker.
    @app.before_request
    def _auto_fetch_rates():
        try:
            from .services.exchange_service import ensure_daily_rate
            ensure_daily_rate(max_age_days=2)
        except Exception:
            logger.debug("Auto-fetch exchange rates failed", exc_info=True)

    from .routes.auth import auth_bp
    from .routes.dashboard import dashboard_bp
    from .routes.parties import parties_bp
    from .routes.patients import patients_bp
    from .routes.treatments import treatments_bp
    from .routes.makbuzlar import makbuzlar_bp
    from .routes.payments import payments_bp
    from .routes.settings import settings_bp
    from .routes.whatsapp import whatsapp_bp
    from .routes.reports import reports_bp
    from .routes.health import health_bp
    from .routes.privacy import privacy_bp
    from .routes.api import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(parties_bp, url_prefix="/parties")
    app.register_blueprint(patients_bp, url_prefix="/patients")
    app.register_blueprint(treatments_bp, url_prefix="/treatments")
    app.register_blueprint(makbuzlar_bp, url_prefix="/makbuzlar")
    app.register_blueprint(payments_bp, url_prefix="/payments")
    app.register_blueprint(settings_bp, url_prefix="/settings")
    app.register_blueprint(whatsapp_bp, url_prefix="/whatsapp")
    app.register_blueprint(reports_bp, url_prefix="/reports")
    app.register_blueprint(health_bp)
    app.register_blueprint(privacy_bp, url_prefix="/privacy")
    app.register_blueprint(api_bp)

    @app.context_processor
    def inject_globals():
        from .services.exchange_service import get_rate_health

        clinic_name = _get_cached_setting("clinic_name", "Makro Ortodonti")

        try:
            rate_health = get_rate_health(max_age_days=2)
        except Exception:
            logger.debug("Kur sağlık bilgisi okunamadı", exc_info=True)
            rate_health = None

        try:
            from .services.whatsapp_service import WhatsAppService
            whatsapp_state = WhatsAppService.quick_state()
        except Exception:
            whatsapp_state = "disconnected"

        return {
            "app_version": f"v{__version__}",
            "clinic_name": clinic_name,
            "rate_health": rate_health,
            "page_url": _page_url,
            "whatsapp_state": whatsapp_state,
            "party_type_labels": {
                "dentist": "Diş Hekimleri",
                "": "Diş Hekimleri",
            },
        }

    @app.cli.command("refresh-exchange-rate")
    def refresh_exchange_rate_command():
        """Scheduler-safe daily exchange-rate job."""
        from .services.exchange_service import fetch_and_store_rate
        rate = fetch_and_store_rate()
        print(f"EUR/TRY rate stored: {rate}")

    @app.cli.command("purge-expired-audit-logs")
    def purge_expired_audit_logs_command():
        """Delete audit rows older than the configured retention period."""
        from datetime import datetime, timedelta, timezone
        from .models.models import AuditLog
        days = int(app.config.get("AUDIT_RETENTION_DAYS", 3650))
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        result = db.session.execute(db.delete(AuditLog).where(AuditLog.occurred_at < cutoff))
        db.session.commit()
        print(f"Purged {result.rowcount or 0} audit rows older than {days} days")

    from .services.scheduler_service import init_scheduler
    init_scheduler(app)

    from .cli import register_cli_commands
    register_cli_commands(app)

    # Auto-reconnect WhatsApp in the background if a paired session exists.
    from .services.whatsapp_service import WhatsAppService
    WhatsAppService.init_app(app)

    from .services.makbuz_send_queue import MakbuzSendQueue
    MakbuzSendQueue.init_app(app)

    from .services.bulk_message_queue import BulkMessageQueue
    BulkMessageQueue.init_app(app)

    from .services.pdf_queue import PdfQueue
    PdfQueue.init_app(app)

    return app
