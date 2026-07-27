from flask import Blueprint, render_template, redirect, url_for, flash, request, send_file
from flask_login import login_required, current_user
from datetime import date

from app.extensions import db
from app.models.models import Settings, ExchangeRate
from app.authz import permissions_required

settings_bp = Blueprint("settings", __name__)


@settings_bp.route("/")
@login_required
@permissions_required("settings.manage")
def index():
    settings = db.session.execute(db.select(Settings)).scalars().all()
    settings_dict = {s.key: s.value for s in settings}

    exchange_rates = db.session.execute(
        db.select(ExchangeRate).order_by(ExchangeRate.rate_date.desc()).limit(30)
    ).scalars().all()

    smtp_password_configured = bool(settings_dict.get("smtp_password"))

    from app.services.backup_service import list_backups
    backups = list_backups()

    return render_template(
        "settings/index.html",
        settings=settings_dict,
        smtp_password_configured=smtp_password_configured,
        exchange_rates=exchange_rates,
        today=date.today(),
        backups=backups,
        api_token_configured=bool(current_user.api_token_hash),
    )


@settings_bp.route("/api-token/generate", methods=["POST"])
@login_required
@permissions_required("settings.manage")
def generate_api_token():
    """Issue a new /api/v1/* bearer token for the current admin, replacing
    any previous one. The raw token is shown exactly once — only its hash
    is kept, so it can't be recovered later, only regenerated."""
    import secrets
    from app.authz import hash_api_token

    raw_token = secrets.token_urlsafe(32)
    current_user.api_token_hash = hash_api_token(raw_token)
    db.session.commit()

    flash(
        f"Yeni API token'ınız (bir daha gösterilmeyecek): {raw_token}",
        "success",
    )
    return redirect(url_for("settings.index"))


@settings_bp.route("/api-token/revoke", methods=["POST"])
@login_required
@permissions_required("settings.manage")
def revoke_api_token():
    current_user.api_token_hash = None
    db.session.commit()
    flash("API token iptal edildi.", "success")
    return redirect(url_for("settings.index"))


@settings_bp.route("/update", methods=["POST"])
@login_required
@permissions_required("settings.manage")
def update_settings():
    allowed_keys = {
        "clinic_name", "clinic_address", "clinic_phone", "clinic_email",
        "tax_id", "invoice_prefix", "invoice_footer_text",
        "smtp_server", "smtp_port", "smtp_username", "smtp_password",
    }

    submitted_keys = [key for key in request.form.keys() if key in allowed_keys]
    if not submitted_keys:
        flash("Güncellenecek ayar bulunamadı.", "warning")
        return redirect(url_for("settings.index"))

    for key in submitted_keys:
        value = request.form.get(key, "").strip()
        
        if key == "smtp_password":
            if not value:
                continue
            from app.services.security_service import encrypt_value
            value = encrypt_value(value)

        setting = db.session.execute(
            db.select(Settings).where(Settings.key == key)
        ).scalar_one_or_none()
        if setting:
            setting.value = value
        else:
            db.session.add(Settings(key=key, value=value))

    db.session.commit()

    # Önbelleklenen ayarlar değişti — cache'i temizle
    from app import invalidate_settings_cache
    for key in submitted_keys:
        invalidate_settings_cache(key)

    flash("Ayarlar güncellendi.", "success")
    return redirect(url_for("settings.index"))


@settings_bp.route("/exchange-rate/add", methods=["POST"])
@login_required
@permissions_required("settings.manage")
def add_exchange_rate():
    rate_date_str = request.form.get("rate_date", "")
    eur_try_rate_str = request.form.get("eur_try_rate", "")
    usd_try_rate_str = request.form.get("usd_try_rate", "")

    if not rate_date_str or not eur_try_rate_str:
        flash("Tarih ve EUR/TRY kur değeri zorunludur.", "danger")
        return redirect(url_for("settings.index"))

    from app.services.validation_service import parse_date, parse_decimal
    rate_date = parse_date(rate_date_str)
    eur_try_rate = parse_decimal(eur_try_rate_str, "0.0001")
    usd_try_rate = parse_decimal(usd_try_rate_str, "0.0001") if usd_try_rate_str else None

    if not rate_date or eur_try_rate is None or eur_try_rate <= 0:
        flash("Geçersiz tarih veya kur değeri girildi.", "danger")
        return redirect(url_for("settings.index"))

    existing = db.session.execute(
        db.select(ExchangeRate).where(
            ExchangeRate.rate_date == rate_date,
            ExchangeRate.source == "ecb"
        )
    ).scalar_one_or_none()

    if existing:
        existing.eur_to_try = eur_try_rate
        if usd_try_rate is not None and usd_try_rate > 0:
            existing.usd_to_try = usd_try_rate
    else:
        db.session.add(ExchangeRate(
            rate_date=rate_date,
            eur_to_try=eur_try_rate,
            usd_to_try=usd_try_rate,
            source="ecb",
        ))

    db.session.commit()
    flash(f"{rate_date} tarihli kur eklendi/güncellendi.", "success")
    return redirect(url_for("settings.index"))


@settings_bp.route("/backup/create", methods=["POST"])
@login_required
@permissions_required("settings.manage")
def create_backup():
    from app.services.backup_service import create_backup as _create_backup
    try:
        dest = _create_backup()
        flash(f"Yedek alındı: {dest.name}", "success")
    except Exception as exc:
        flash(f"Yedekleme başarısız: {exc}", "danger")
    return redirect(url_for("settings.index") + "#backup")


@settings_bp.route("/backup/download/<filename>")
@login_required
@permissions_required("settings.manage")
def download_backup(filename):
    from app.services.backup_service import get_backup_path
    path = get_backup_path(filename)
    if not path:
        flash("Yedek dosyası bulunamadı.", "danger")
        return redirect(url_for("settings.index") + "#backup")
    return send_file(path, as_attachment=True, download_name=filename)


@settings_bp.route("/reset-defaults", methods=["POST"])
@login_required
@permissions_required("settings.manage")
def reset_defaults():
    """Klinik kimlik ayarlarını varsayılan değerlere sıfırlar."""
    # Yalnızca klinik bilgisi alanlarını sıfırla; SMTP, WhatsApp, kur kayıtları dokunulmaz.
    resettable = {
        "clinic_name", "clinic_address", "clinic_phone", "clinic_email",
        "tax_id", "invoice_prefix", "invoice_footer_text",
    }
    for key in resettable:
        default_val = Settings.DEFAULTS.get(key, "")
        setting = db.session.execute(
            db.select(Settings).where(Settings.key == key)
        ).scalar_one_or_none()
        if setting:
            setting.value = default_val
        else:
            db.session.add(Settings(key=key, value=default_val))
    db.session.commit()

    from app import invalidate_settings_cache
    invalidate_settings_cache()

    flash("Klinik bilgileri varsayılan değerlere sıfırlandı.", "warning")
    return redirect(url_for("settings.index"))


@settings_bp.route("/purge-demo-data", methods=["POST"])
@login_required
@permissions_required("settings.manage")
def purge_demo_data():
    """Doktor/işlem kataloğu ve kullanıcılara dokunmadan tüm operasyonel veriyi siler."""
    from app.models.models import (
        WorkOrder, Makbuz, MakbuzPayment, MakbuzSendLog, Payment, ExchangeRate,
        AuditLog, Invoice, InvoiceItem,
    )

    if request.form.get("confirm_phrase", "").strip().upper() != "SİL":
        flash('Onaylamak için "SİL" yazmanız gerekiyor. Hiçbir veri silinmedi.', "warning")
        return redirect(url_for("settings.index"))

    # Sıralama önemli: FK bağımlılıkları aşağıdan yukarıya silinir
    db.session.execute(db.delete(MakbuzPayment))
    db.session.execute(db.delete(MakbuzSendLog))
    db.session.execute(db.delete(Makbuz))
    db.session.execute(db.delete(Payment))
    db.session.execute(db.delete(InvoiceItem))
    db.session.execute(db.delete(Invoice))
    db.session.execute(db.delete(WorkOrder))
    db.session.execute(db.delete(ExchangeRate))
    db.session.execute(db.delete(AuditLog))
    db.session.commit()

    flash(
        "Demo veriler temizlendi. Döviz kuru bir sonraki istekte otomatik çekilecek.",
        "success",
    )
    return redirect(url_for("settings.index"))


@settings_bp.route("/exchange-rate/fetch", methods=["POST"])
@login_required
@permissions_required("settings.manage")
def fetch_exchange_rate():
    from app.services.exchange_service import fetch_and_store_rate
    try:
        rate = fetch_and_store_rate()
        flash(f"Güncel kur: 1 EUR = {rate:.4f} TRY", "success")
    except Exception as e:
        flash(f"Kur çekilirken hata oluştu: {str(e)}", "danger")
    return redirect(url_for("settings.index"))
