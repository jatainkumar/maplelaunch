"""Helpers to read/write an application's data. Sensitive identifiers live encrypted in application_pii;
everything else is plain JSON in applications.form_data."""

import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import blind_index, decrypt, encrypt, mask
from app.db.models import Application, ApplicationPII, Document, Extraction

PII_FIELDS = {  # form key -> (pii column prefix, mask kind)
    "pan": ("pan", "pan"),
    "gstin": ("gstin", "gstin"),
    "account_number": ("account_number", "account_number"),
    "phone": ("phone", "phone"),
    "email": ("email", "email"),
    "cin": ("cin", "cin"),
}
_BI_COLUMN = {"pan": "pan_bi", "gstin": "gstin_bi", "account_number": "account_bi", "phone": "phone_bi",
              "email": "email_bi"}

FORM_FIELDS = {
    "legal_name", "trade_name", "contact_name", "address", "city", "state", "pincode", "monthly_volume",
    "website", "description", "ifsc", "account_holder_name", "bank_name", "bank_branch", "confirmations",
}


def new_reference() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "ML-" + "".join(secrets.choice(alphabet) for _ in range(6))


async def get_pii(session: AsyncSession, app_id: str) -> ApplicationPII:
    pii = await session.get(ApplicationPII, app_id)
    if pii is None:
        pii = ApplicationPII(application_id=app_id)
        session.add(pii)
        await session.flush()
    return pii


async def set_fields(session: AsyncSession, app: Application, data: dict) -> list[str]:
    """Apply a partial update of form/PII fields. Returns the list of keys that actually changed."""
    changed = []
    pii = await get_pii(session, app.id)
    form = dict(app.form_data or {})
    for key, value in data.items():
        if key in PII_FIELDS:
            col = PII_FIELDS[key][0]
            norm = (value or "").strip().upper() if key in ("pan", "gstin", "cin") else (value or "").strip()
            if key == "email":
                norm = norm.lower()
            current = decrypt(getattr(pii, f"{col}_enc"))
            if (current or "") != norm:
                setattr(pii, f"{col}_enc", encrypt(norm) if norm else None)
                if key in _BI_COLUMN:
                    setattr(pii, _BI_COLUMN[key], blind_index(key, norm) if norm else None)
                changed.append(key)
        elif key in FORM_FIELDS:
            if key == "ifsc" and value:
                value = value.strip().upper()
            if form.get(key) != value:
                form[key] = value
                changed.append(key)
    if changed:
        app.form_data = form
    return changed


async def app_data(session: AsyncSession, app: Application, reveal: bool = True) -> dict:
    """Merged view of form + PII. With reveal=False sensitive values are masked."""
    pii = await get_pii(session, app.id)
    data = dict(app.form_data or {})
    for key, (col, kind) in PII_FIELDS.items():
        value = decrypt(getattr(pii, f"{col}_enc"))
        data[key] = value if reveal else mask(kind, value)
    data["business_type"] = app.business_type
    data["category"] = app.category
    return data


async def active_documents(session: AsyncSession, app_id: str) -> list[Document]:
    return list((await session.execute(
        select(Document).where(Document.application_id == app_id, Document.is_active).order_by(Document.uploaded_at)
    )).scalars())


async def latest_extraction(session: AsyncSession, document_id: str) -> Extraction | None:
    return (await session.execute(
        select(Extraction).where(Extraction.document_id == document_id).order_by(Extraction.created_at.desc()).limit(1)
    )).scalars().first()


def extraction_value(fields: dict, name: str, reveal: bool = True):
    """Read one extracted field (handles encrypted sensitive values)."""
    item = fields.get(name) or {}
    if "value_enc" in item:
        return decrypt(item["value_enc"]) if reveal else item.get("masked")
    return item.get("value")


def public_fields(fields: dict, reveal: bool) -> dict:
    out = {}
    for name, item in (fields or {}).items():
        out[name] = {"value": extraction_value(fields, name, reveal), "confidence": item.get("confidence", 0)}
    return out
