from __future__ import annotations

import hashlib
from functools import wraps

from flask import flash, jsonify, redirect, request, url_for
from flask_login import current_user


ADMIN_PERMISSIONS = frozenset({"*"})
STAFF_PERMISSIONS = frozenset({
    "clinical.view", "clinical.edit",
    "billing.view", "billing.edit",
    "reports.view", "messaging.use",
})
# Deliberately admin-only, not part of STAFF_PERMISSIONS above: reversing a
# makbuz's paid status (billing.cancel_makbuz) and deleting an individual
# collection entry (payments.delete_payment) both destroy financial history
# that a receptionist/bookkeeper role shouldn't be able to erase alone —
# see TODO.md's v2.0 "staff role restrictions" item.

ROLE_PERMISSIONS = {
    "admin": ADMIN_PERMISSIONS,
    "staff": STAFF_PERMISSIONS,
}


def has_permission(user, permission: str) -> bool:
    permissions = ROLE_PERMISSIONS.get(getattr(user, "role", None), frozenset())
    return "*" in permissions or permission in permissions


def permissions_required(*permissions: str):
    """Require every named permission from the centralized role matrix."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login"))
            if not all(has_permission(current_user, permission) for permission in permissions):
                flash("Bu işlem için yetkiniz bulunmuyor.", "danger")
                return redirect(url_for("dashboard.index"))
            return view_func(*args, **kwargs)

        return wrapped

    return decorator


def hash_api_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def resolve_api_user():
    """Identify the caller of an /api/v1/* request.

    Accepts either an `Authorization: Bearer <token>` header (looked up by
    SHA-256 hash against User.api_token_hash) or, as a fallback, an existing
    authenticated browser session — so the API also works if someone is
    just poking at it from a logged-in tab. Returns None if neither applies.
    """
    from app.extensions import db
    from app.models.models import User

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        raw_token = auth_header[len("Bearer "):].strip()
        if not raw_token:
            return None
        token_hash = hash_api_token(raw_token)
        return db.session.execute(
            db.select(User).where(
                User.api_token_hash == token_hash, User.is_active.is_(True)
            )
        ).scalar_one_or_none()

    if current_user.is_authenticated:
        return current_user
    return None


def api_permissions_required(*permissions: str):
    """Like permissions_required, but for the JSON API: 401/403 JSON
    instead of a redirect to the HTML login page, since a script or mobile
    client has no use for an HTML redirect."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            user = resolve_api_user()
            if user is None:
                return jsonify({"error": "unauthorized"}), 401
            if not all(has_permission(user, permission) for permission in permissions):
                return jsonify({"error": "forbidden"}), 403
            return view_func(*args, **kwargs)

        return wrapped

    return decorator


