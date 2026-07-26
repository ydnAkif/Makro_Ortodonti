from __future__ import annotations

import json
import logging
import time
import uuid

from flask import Flask, g, request


access_logger = logging.getLogger("makro.access")


def init_observability(app: Flask) -> None:
    if app.config.get("SENTRY_DSN"):
        import sentry_sdk
        sentry_sdk.init(
            dsn=app.config["SENTRY_DSN"],
            send_default_pii=False,
            traces_sample_rate=float(app.config.get("SENTRY_TRACES_SAMPLE_RATE", 0.05)),
            environment=app.config.get("ENVIRONMENT", "production"),
        )

    @app.before_request
    def begin_request():
        incoming = request.headers.get("X-Request-ID", "").strip()
        g.request_id = incoming[:64] if incoming else uuid.uuid4().hex
        g.request_started_at = time.monotonic()

    @app.after_request
    def secure_and_log(response):
        request_id = getattr(g, "request_id", None) or uuid.uuid4().hex
        started_at = getattr(g, "request_started_at", time.monotonic())
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
            "img-src 'self' data:; font-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'"
        )
        if request.is_secure or app.config.get("FORCE_HSTS"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        elapsed_ms = round((time.monotonic() - started_at) * 1000, 2)
        access_logger.info(json.dumps({
            "event": "http_request", "request_id": request_id,
            "method": request.method, "path": request.path,
            "status": response.status_code, "duration_ms": elapsed_ms,
            "remote_addr": request.remote_addr,
        }, ensure_ascii=False))
        return response
