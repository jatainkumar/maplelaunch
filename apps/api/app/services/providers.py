"""Client for the (simulated) external verification providers and the merchant-ID service.

Verification calls are asynchronous: the provider answers 202 with a reference, then calls our webhook later.
Requests carry our request_id as idempotency key, so retries never create duplicate provider jobs."""

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.config import get_settings

settings = get_settings()

ENDPOINTS = {"PAN": "/v1/pan/verify", "GST": "/v1/gst/verify", "BANK": "/v1/bank/penny-drop",
             "RISK": "/v1/risk/assess"}

# Render free instances can take ~50 s to wake up; wait for them rather than failing.
TIMEOUT = httpx.Timeout(70.0, connect=70.0)


class ProviderUnavailable(Exception):
    pass


class ProviderRejected(Exception):
    pass


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    return isinstance(exc, httpx.TransportError)


async def request_check(check_type: str, request_id: str, application_id: str, data: dict) -> dict:
    payload = {"request_id": request_id, "reference_id": application_id,
               "callback_url": f"{settings.public_api_url}/webhooks/{check_type.lower()}", "data": data}
    try:
        async for attempt in AsyncRetrying(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=4),
                                           retry=retry_if_exception(_retryable), reraise=True):
            with attempt:
                async with httpx.AsyncClient(base_url=settings.providers_base_url, timeout=TIMEOUT) as c:
                    r = await c.post(ENDPOINTS[check_type], json=payload)
                    r.raise_for_status()
                    return r.json()
    except httpx.HTTPStatusError as exc:
        if _retryable(exc):
            raise ProviderUnavailable(f"{check_type} provider returned {exc.response.status_code}") from exc
        raise ProviderRejected(f"{check_type} provider rejected request: {exc.response.text[:200]}") from exc
    except httpx.TransportError as exc:
        raise ProviderUnavailable(f"{check_type} provider unreachable: {type(exc).__name__}") from exc
    raise ProviderUnavailable("unreachable")


async def create_mid(idempotency_key: str, data: dict) -> dict:
    """Single attempt. Raises ProviderUnavailable on 5xx/timeout (caller decides how to retry)."""
    try:
        async with httpx.AsyncClient(base_url=settings.providers_base_url, timeout=httpx.Timeout(8.0, connect=70.0)) as c:
            r = await c.post("/v1/mid", json={"idempotency_key": idempotency_key, "data": data})
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as exc:
        raise ProviderUnavailable(f"MID service returned {exc.response.status_code}") from exc
    except httpx.TransportError as exc:
        raise ProviderUnavailable(f"MID service unreachable or timed out: {type(exc).__name__}") from exc


async def get_mid(idempotency_key: str) -> dict | None:
    """Status check before retrying, so a timed-out-but-successful creation is never duplicated."""
    try:
        async with httpx.AsyncClient(base_url=settings.providers_base_url, timeout=httpx.Timeout(8.0, connect=70.0)) as c:
            r = await c.get(f"/v1/mid/{idempotency_key}")
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
    except (httpx.HTTPStatusError, httpx.TransportError):
        return None


async def admin(method: str, path: str, json: dict | None = None) -> dict:
    """Scenario controls on the provider service. Retries briefly, because on free hosting the service may be waking
    up or restarting (Render answers 502/503 meanwhile)."""
    async for attempt in AsyncRetrying(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, max=10),
                                       retry=retry_if_exception(_retryable), reraise=True):
        with attempt:
            async with httpx.AsyncClient(base_url=settings.providers_base_url, timeout=TIMEOUT) as c:
                r = await c.request(method, path, json=json, headers={"X-Admin-Token": settings.provider_admin_token})
                r.raise_for_status()
                return r.json()
    raise RuntimeError("unreachable")
