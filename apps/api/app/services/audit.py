"""Append-only, hash-chained audit log. Each entry hashes the previous entry of the same application,
so any edit or deletion breaks the chain and is detectable via verify_chain()."""

import hashlib
import json
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import redact_obj
from app.db.models import AuditLog, utcnow


def _digest(prev_hash: str | None, app_id: str | None, actor: str, action: str, details: dict, ts: datetime) -> str:
    body = json.dumps(
        {"prev": prev_hash, "app": app_id, "actor": actor, "action": action, "details": details, "ts": ts.isoformat()},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(body.encode()).hexdigest()


async def audit(session: AsyncSession, application_id: str | None, actor: str, action: str, details: dict | None = None):
    details = redact_obj(details or {})
    # Serialise chain appends per application within this transaction.
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"audit:{application_id}"})
    prev = (
        await session.execute(
            select(AuditLog.hash)
            .where(AuditLog.application_id == application_id)
            .order_by(AuditLog.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    ts = utcnow()
    entry = AuditLog(
        application_id=application_id,
        actor=actor,
        action=action,
        details=details,
        prev_hash=prev,
        hash=_digest(prev, application_id, actor, action, details, ts),
        created_at=ts,
    )
    session.add(entry)
    await session.flush()
    return entry


async def verify_chain(session: AsyncSession, application_id: str) -> dict:
    rows = (
        await session.execute(select(AuditLog).where(AuditLog.application_id == application_id).order_by(AuditLog.id))
    ).scalars()
    prev = None
    count = 0
    for row in rows:
        expected = _digest(prev, row.application_id, row.actor, row.action, row.details, row.created_at)
        if row.prev_hash != prev or row.hash != expected:
            return {"valid": False, "entries": count, "broken_at": row.id}
        prev = row.hash
        count += 1
    return {"valid": True, "entries": count, "head": prev}
