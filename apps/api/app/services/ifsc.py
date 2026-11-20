"""Live IFSC lookup using Razorpay's free public IFSC API (https://ifsc.razorpay.com)."""

import httpx

from app.core.logging import log
from app.domain.validators import clean, valid_ifsc

_cache: dict[str, dict] = {}


async def lookup_ifsc(ifsc: str) -> dict:
    """Returns {"valid_format", "found" (True/False/None=unknown), "bank", "branch", "city", "state"}."""
    code = clean(ifsc)
    if not valid_ifsc(code):
        return {"ifsc": code, "valid_format": False, "found": False}
    if code in _cache:
        return _cache[code]
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"https://ifsc.razorpay.com/{code}")
        if r.status_code == 404:
            result = {"ifsc": code, "valid_format": True, "found": False}
        else:
            r.raise_for_status()
            d = r.json()
            result = {"ifsc": code, "valid_format": True, "found": True, "bank": d.get("BANK"),
                      "branch": d.get("BRANCH"), "city": d.get("CITY"), "state": d.get("STATE")}
        _cache[code] = result
        return result
    except Exception as exc:  # network failure must not block onboarding
        log.warning("ifsc_lookup_failed", error=str(exc)[:200])
        return {"ifsc": code, "valid_format": True, "found": None}
