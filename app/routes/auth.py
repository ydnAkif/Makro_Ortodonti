from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
import bcrypt
from urllib.parse import urlparse, urljoin

from app.extensions import db
from app.models.models import User

auth_bp = Blueprint("auth", __name__)


def _is_safe_redirect_url(target: str) -> bool:
    if not target:
        return False
    host_url = urlparse(request.host_url)
    redirect_url = urlparse(urljoin(request.host_url, target))
    return redirect_url.scheme in ("http", "https") and host_url.netloc == redirect_url.netloc


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Brute-force korumalı giriş noktası.

    IP bazlı kilit: Aynı IP veya kullanıcı adından 15 dakika içinde 5 başarısız
    deneme yapılırsa hesap geçici olarak kilitlenir. Başarılı giriş deneme
    sayacını sıfırlamaz; sayaç zaman aşımı ile otomatik düşer.

    Koruma detayları:
    - X-Forwarded-For header'ı TRUST_PROXY etkinleştirilmeden okunmaz (spoofing koruması)
    - Her deneme (başarılı/başarısız) LoginAttempt tablosuna kaydedilir
    - purge-old-login-logs CLI komutu veya scheduler ile eski kayıtlar temizlenir
    """
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        # ProxyFix normalizes remote_addr only when TRUST_PROXY is explicitly enabled.
        # Reading X-Forwarded-For directly would let clients spoof the lockout key.
        ip_address = request.remote_addr or "127.0.0.1"

        from datetime import datetime, timezone, timedelta
        from app.models.models import LoginAttempt

        # Check for 5 failed attempts in the last 15 minutes
        lockout_time = datetime.now(timezone.utc) - timedelta(minutes=15)
        failed_count = db.session.execute(
            db.select(db.func.count(LoginAttempt.id)).where(
                db.or_(LoginAttempt.ip_address == ip_address, LoginAttempt.username == username),
                LoginAttempt.is_successful == False,
                LoginAttempt.created_at >= lockout_time
            )
        ).scalar() or 0

        if failed_count >= 5:
            flash("Çok fazla başarısız giriş denemesi. Lütfen 15 dakika sonra tekrar deneyin.", "danger")
            return render_template("auth/login.html")

        user = db.session.execute(
            db.select(User).where(User.username == username)
        ).scalar_one_or_none()

        is_success = False
        if user and user.is_active:
            try:
                password_matches = bcrypt.checkpw(
                    password.encode("utf-8"),
                    user.password_hash.encode("utf-8"),
                )
            except ValueError:
                password_matches = False

            if password_matches:
                is_success = True
                login_user(user)

        # Record this attempt
        attempt = LoginAttempt(
            ip_address=ip_address,
            username=username,
            is_successful=is_success
        )
        db.session.add(attempt)
        db.session.commit()

        if is_success:
            next_page = request.args.get("next")
            flash("Giriş başarılı!", "success")
            if next_page and _is_safe_redirect_url(next_page):
                return redirect(next_page)
            return redirect(url_for("dashboard.index"))

        flash("Kullanıcı adı veya şifre hatalı.", "danger")

    return render_template("auth/login.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Çıkış yapıldı.", "info")
    return redirect(url_for("auth.login"))
