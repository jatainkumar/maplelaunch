"""Upload + extraction persistence. Sensitive extracted values are encrypted before they touch the database."""

import hashlib

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt, mask
from app.db.models import Document, Extraction
from app.domain.policy import SENSITIVE_FIELDS
from app.services.audit import audit
from app.services.extraction import PROMPT_VERSION, extract_document
from app.services.storage import storage

ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp", "application/pdf"}
MAX_BYTES = 8 * 1024 * 1024


async def save_document(session: AsyncSession, app_id: str, slot: str, filename: str, mime: str, data: bytes,
                        actor: str) -> Document:
    digest = hashlib.sha256(data).hexdigest()
    # A new upload for a slot supersedes the previous one (kept for audit, no longer active).
    await session.execute(update(Document).where(Document.application_id == app_id, Document.slot == slot,
                                                 Document.is_active).values(is_active=False))
    ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "application/pdf": "pdf"}[mime]
    doc = Document(application_id=app_id, slot=slot, filename=filename[:200], mime=mime, size=len(data), sha256=digest,
                   storage_path="")
    session.add(doc)
    await session.flush()
    doc.storage_path = f"{app_id}/{doc.id}.{ext}"
    await storage.put(doc.storage_path, data, mime)
    await audit(session, app_id, actor, "document_uploaded", {"slot": slot, "sha256": digest[:16], "size": len(data)})
    return doc


async def run_extraction(session: AsyncSession, doc: Document, actor: str = "system") -> Extraction:
    data = await storage.get(doc.storage_path)
    outcome = await extract_document(data, doc.mime, doc.slot)
    stored = {}
    for name, item in outcome.fields.items():
        if name in SENSITIVE_FIELDS and item.get("value"):
            stored[name] = {"value_enc": encrypt(item["value"]), "masked": mask(SENSITIVE_FIELDS[name], item["value"]),
                            "confidence": item["confidence"]}
        else:
            stored[name] = item
    ext = Extraction(document_id=doc.id, application_id=doc.application_id, fields=stored, quality=outcome.quality,
                     detected_type=outcome.detected_type, model=outcome.model, prompt_version=PROMPT_VERSION,
                     latency_ms=outcome.latency_ms, error=outcome.error)
    session.add(ext)
    doc.status = "failed" if outcome.error else "extracted"
    doc.quality = outcome.quality.get("score") if outcome.quality else None
    doc.detected_type = outcome.detected_type
    await session.flush()
    await audit(session, doc.application_id, actor, "document_extracted",
                {"slot": doc.slot, "model": outcome.model, "quality": doc.quality, "error": outcome.error,
                 "fields": {k: v.get("confidence") for k, v in outcome.fields.items()}})
    return ext
