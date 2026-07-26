"""Health / readiness endpoint for load-balancers and monitoring."""
from flask import Blueprint, jsonify
from sqlalchemy import text

from app.extensions import db

health_bp = Blueprint("health", __name__)


@health_bp.route("/health")
def health_check():
    """Return 200 OK with basic status when the application is healthy."""
    try:
        db.session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db.session.rollback()
        db_ok = False

    status = "ok" if db_ok else "degraded"
    http_code = 200 if db_ok else 503
    return jsonify({"status": status, "db": db_ok}), http_code
