"""Provider callbacks. Signed with HMAC-SHA256 over "<timestamp>.<body>"; stale timestamps are rejected (replay
protection). Handling is idempotent: the same event may arrive any number of times."""

import hashlib
import hmac
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_session
from app.services.audit import audit
from app.services.checks import record_callback

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
settings = get_settings()
TOLERANCE_SECONDS = 300


def sign(body: bytes, ts: str, secret: str) -> str:
    return hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()


@router.post("/{provider}")
async def receive(provider: str, request: Request, s: AsyncSession = Depends(get_session)):
    provider = provider.upper()
    if provider not in ("PAN", "GST", "BANK", "RISK"):
        raise HTTPException(404, "Unknown provider")
    body = await request.body()
    ts = request.headers.get("X-ML-Timestamp", "")
    sig = request.headers.get("X-ML-Signature", "").removeprefix("sha256=")
    valid_sig = bool(ts and sig) and hmac.compare_digest(sign(body, ts, settings.webhook_secret), sig)
    fresh = ts.isdigit() and abs(time.time() - int(ts)) <= TOLERANCE_SECONDS
    if not (valid_sig and fresh):
        await audit(s, None, f"provider:{provider}", "callback_rejected",
                    {"reason": "bad signature" if not valid_sig else "stale timestamp", "ip": request.client.host
                     if request.client else None})
        await s.commit()
        raise HTTPException(401, "Invalid signature")
    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON") from None
    outcome = await record_callback(s, provider, event)
    return {"received": True, "outcome": outcome}
