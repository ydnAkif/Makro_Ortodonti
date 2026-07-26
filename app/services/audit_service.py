from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

from flask import g, has_request_context, request
from flask_login import current_user
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.models.models import AuditLog


REDACTED_FIELDS = {"password_hash", "value", "qr_code", "session_data"}


def _json_value(value):
    if isinstance(value, (date, datetime, Decimal)):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    return value if isinstance(value, (str, int, float, bool, type(None))) else repr(value)


@event.listens_for(Session, "before_flush")
def create_audit_rows(session: Session, _flush_context, _instances) -> None:
    """Capture ORM mutations in the same transaction as the business change."""
    if session.info.get("audit_in_progress"):
        return

    rows = []
    candidates = [("create", obj) for obj in session.new]
    candidates += [("update", obj) for obj in session.dirty if session.is_modified(obj, include_collections=False)]
    candidates += [("delete", obj) for obj in session.deleted]
    for action, obj in candidates:
        if isinstance(obj, AuditLog):
            continue
        state = inspect(obj)
        changes = {}
        for attr in state.mapper.column_attrs:
            key = attr.key
            history = state.attrs[key].history
            if action == "update" and not history.has_changes():
                continue
            if key in REDACTED_FIELDS:
                changes[key] = {"old": "[REDACTED]", "new": "[REDACTED]"}
            else:
                changes[key] = {
                    "old": [_json_value(v) for v in history.deleted],
                    "new": [_json_value(v) for v in history.added],
                }

        identity = state.identity
        rows.append(AuditLog(
            actor_user_id=int(current_user.id) if has_request_context() and current_user.is_authenticated else None,
            actor_username=current_user.username if has_request_context() and current_user.is_authenticated else "system",
            action=action,
            entity_type=obj.__class__.__name__,
            entity_id=str(identity[0]) if identity else None,
            request_id=getattr(g, "request_id", None) if has_request_context() else None,
            ip_address=request.remote_addr if has_request_context() else None,
            endpoint=request.endpoint if has_request_context() else None,
            changes_json=json.dumps(changes, ensure_ascii=False, sort_keys=True),
        ))

    if rows:
        session.info["audit_in_progress"] = True
        try:
            session.add_all(rows)
        finally:
            session.info.pop("audit_in_progress", None)
