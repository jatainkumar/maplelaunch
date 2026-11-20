"""PII protection: AES-GCM field encryption, blind indexes for matching, and display masking."""

import base64
import hashlib
import hmac
import os
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


def _key(raw: str, purpose: str) -> bytes:
    if raw:
        try:
            key = base64.b64decode(raw, validate=True)
            if len(key) == 32:
                return key
        except ValueError:
            pass
        # Any other secret string (e.g. a Render-generated value) is stretched to 32 bytes.
        return hashlib.sha256(f"{purpose}:{raw}".encode()).digest()
    # Development fallback: derive from APP_SECRET so local runs work out of the box.
    return hashlib.sha256(f"{purpose}:{get_settings().app_secret}".encode()).digest()


def _enc_key() -> bytes:
    return _key(get_settings().encryption_key, "encryption")


def _bi_key() -> bytes:
    return _key(get_settings().blind_index_key, "blind-index")


def encrypt(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    nonce = os.urandom(12)
    ct = AESGCM(_enc_key()).encrypt(nonce, value.encode(), b"maplelaunch-pii-v1")
    return "v1:" + base64.b64encode(nonce + ct).decode()


def decrypt(token: str | None) -> str | None:
    if not token:
        return None
    if not token.startswith("v1:"):
        raise ValueError("unknown ciphertext version")
    raw = base64.b64decode(token[3:])
    return AESGCM(_enc_key()).decrypt(raw[:12], raw[12:], b"maplelaunch-pii-v1").decode()


def normalize_identifier(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def blind_index(kind: str, value: str | None) -> str | None:
    """Deterministic keyed hash so equal identifiers can be matched without decrypting."""
    if not value:
        return None
    msg = f"{kind}:{normalize_identifier(value)}".encode()
    return hmac.new(_bi_key(), msg, hashlib.sha256).hexdigest()


def mask(kind: str, value: str | None) -> str | None:
    if not value:
        return value
    v = value.strip()
    if kind == "pan" and len(v) == 10:
        return v[:5] + "••••" + v[-1]
    if kind == "gstin" and len(v) == 15:
        return v[:2] + "•••••" + v[7:12] + "•••"
    if kind == "account_number":
        return "•" * max(len(v) - 4, 2) + v[-4:]
    if kind == "phone":
        return "••••••" + v[-4:]
    if kind == "email" and "@" in v:
        user, domain = v.split("@", 1)
        return user[:1] + "•••@" + domain
    if kind == "cin" and len(v) == 21:
        return v[:6] + "•••••••••" + v[-6:]
    return v[:2] + "•••" if len(v) > 4 else "•••"


# Patterns for scrubbing free text (logs, raw callback payloads).
_PATTERNS = [
    (re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b"), "gstin"),
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "pan"),
    (re.compile(r"\b\d{9,18}\b"), "account_number"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "email"),
]


def redact_text(text: str) -> str:
    for pattern, kind in _PATTERNS:
        text = pattern.sub(lambda m, k=kind: mask(k, m.group(0)) or "", text)
    return text


def redact_obj(obj):
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(v) for v in obj]
    return obj
