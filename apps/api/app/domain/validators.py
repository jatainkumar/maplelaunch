"""Deterministic validators for Indian onboarding identifiers."""

import re

from rapidfuzz import fuzz

PAN_RE = re.compile(r"^[A-Z]{3}[ABCFGHLJPT][A-Z]\d{4}[A-Z]$")
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
CIN_RE = re.compile(r"^[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}$")
ACCOUNT_RE = re.compile(r"^\d{9,18}$")
PHONE_RE = re.compile(r"^[6-9]\d{9}$")

_GST_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# 4th character of a PAN encodes the holder type.
PAN_HOLDER_TYPES = {
    "P": "Individual",
    "F": "Firm / LLP",
    "C": "Company",
    "H": "HUF",
    "A": "Association of persons",
    "T": "Trust",
    "B": "Body of individuals",
    "L": "Local authority",
    "J": "Artificial juridical person",
    "G": "Government",
}


def clean(value: str | None) -> str:
    return re.sub(r"\s+", "", (value or "")).upper()


def valid_pan(pan: str | None) -> bool:
    return bool(PAN_RE.match(clean(pan)))


def pan_holder_char(pan: str | None) -> str | None:
    p = clean(pan)
    return p[3] if len(p) == 10 else None


def gstin_checksum_char(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        product = _GST_CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return _GST_CHARS[(36 - total % 36) % 36]


def valid_gstin(gstin: str | None) -> bool:
    g = clean(gstin)
    if not GSTIN_RE.match(g):
        return False
    return gstin_checksum_char(g[:14]) == g[14]


def gstin_pan(gstin: str | None) -> str | None:
    g = clean(gstin)
    return g[2:12] if len(g) == 15 else None


def make_gstin(state_code: str, pan: str, entity: str = "1") -> str:
    """Build a checksum-valid GSTIN (used for synthetic sample data and tests)."""
    first14 = f"{state_code}{pan}{entity}Z"
    return first14 + gstin_checksum_char(first14)


def valid_ifsc(ifsc: str | None) -> bool:
    return bool(IFSC_RE.match(clean(ifsc)))


def valid_cin(cin: str | None) -> bool:
    return bool(CIN_RE.match(clean(cin)))


def valid_account(acc: str | None) -> bool:
    return bool(ACCOUNT_RE.match(clean(acc)))


def valid_phone(phone: str | None) -> bool:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    return bool(PHONE_RE.match(digits))


_NAME_NOISE = re.compile(
    r"\b(M/?S|MESSRS|PVT|PRIVATE|LTD|LIMITED|LLP|AND|CO|COMPANY|THE|SHRI|SMT|MR|MRS|MS)\b|[^A-Z0-9 ]"
)


def normalize_name(name: str | None) -> str:
    n = (name or "").upper().replace("&", " ")
    n = _NAME_NOISE.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


def name_similarity(a: str | None, b: str | None) -> int:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0
    return round(fuzz.token_set_ratio(na, nb))
