from __future__ import annotations

from functools import wraps

from flask import flash, redirect, url_for
from flask_login import current_user


ADMIN_PERMISSIONS = frozenset({"*"})
STAFF_PERMISSIONS = frozenset({
    "clinical.view", "clinical.edit",
    "billing.view", "billing.edit",
    "reports.view", "messaging.use",
})

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


def roles_required(*roles: str):
    """Restrict endpoint access to users with one of the given roles."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login"))

            user_role = getattr(current_user, "role", None)
            if user_role not in roles:
                flash("Bu işlem için yetkiniz bulunmuyor.", "danger")
                return redirect(url_for("dashboard.index"))

            return view_func(*args, **kwargs)

        return wrapped

    return decorator
