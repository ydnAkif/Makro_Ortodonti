"""Authenticated encryption for sensitive application settings."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def _get_fernet() -> Fernet:
    """Derive a stable Fernet key from the dedicated encryption secret."""
    secret = current_app.config.get("ENCRYPTION_KEY") or ""
    if not secret:
        raise RuntimeError(
            "ENCRYPTION_KEY yapılandırılmadan hassas değerler şifrelenemez. "
            "Lütfen .env dosyasında güçlü bir ENCRYPTION_KEY tanımlayın."
        )
    raw_key = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(raw_key))


def encrypt_value(value: str) -> str:
    """Encrypt a non-empty string and return an authenticated Fernet token."""
    if not value:
        return ""
    return _get_fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_value(value: str) -> str:
    """Decrypt a Fernet token, failing closed on invalid or legacy ciphertext."""
    if not value:
        return ""
    try:
        return _get_fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError) as exc:
        raise ValueError(
            "Failed to decrypt stored value. ENCRYPTION_KEY değişmiş olabilir veya "
            "kayıt eski/güvenli olmayan şifreleme biçimindedir."
        ) from exc
