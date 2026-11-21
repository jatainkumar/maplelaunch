"""Mock verification providers for MapleLaunch.

Behaves like real asynchronous KYC/KYB providers:
  * POST /v1/{pan,gst,bank,risk}/... -> 202 Accepted + provider_ref (idempotent on request_id)
  * shortly after: a signed "PENDING" progress callback, then the final result callback 2-8 s later
  * callbacks are retried with backoff if the receiver is down (e.g. a sleeping Render instance)
Outcomes come from magic test values (like card-network test numbers) or from scenarios set per application
via the admin API (scenario lab): success, fail, duplicate, late, late_once, outage, no_callback, out_of_order.
The merchant-ID service is synchronous and supports success, fail, fail_3 and timeout."""

import asyncio
import difflib
import hashlib
import hmac
import json
import random
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import JSON, DateTime, Integer, String, Text, UniqueConstraint, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    database_url: str = "pgserver"
    pgserver_dir: str = str(ROOT.parent / "api" / ".data" / "pg")
    webhook_secret: str = "dev-webhook-secret"
    provider_admin_token: str = "dev-provider-admin-token"
    late_delay_seconds: int = 75  # > the platform's default 45 s check timeout
    min_delay_seconds: float = 2.0
    max_delay_seconds: float = 8.0


settings = Settings()
if settings.database_url == "pgserver":
    try:
        import pgserver  # embedded Postgres for local development only
    except ImportError as exc:
        raise RuntimeError(
            "DATABASE_URL is not set. On Render, set it on this service to the same Supabase Session pooler URL "
            "as the API (port 5432).") from exc

    Path(settings.pgserver_dir).mkdir(parents=True, exist_ok=True)
    settings.database_url = pgserver.get_server(settings.pgserver_dir, cleanup_mode=None).get_uri()

url = settings.database_url
for prefix in ("postgres://", "postgresql://"):
    if url.startswith(prefix):
        url = "postgresql+psycopg://" + url[len(prefix):]
engine = create_async_engine(url, pool_size=3, pool_pre_ping=True, connect_args={"prepare_threshold": None})
Session = async_sessionmaker(engine, expire_on_commit=False)
J = JSON().with_variant(JSONB(), "postgresql")
TS = DateTime(timezone=True)


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class MockRequest(Base):
    __tablename__ = "mock_requests"
    request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(10))
    reference_id: Mapped[str] = mapped_column(String(64), index=True)
    provider_ref: Mapped[str] = mapped_column(String(40))
    data: Mapped[dict] = mapped_column(J)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


class MockCallback(Base):
    __tablename__ = "mock_callbacks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    url: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(J)
    send_at: Mapped[datetime] = mapped_column(TS, index=True)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)


class MockScenario(Base):
    __tablename__ = "mock_scenarios"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(10))
    reference_id: Mapped[str] = mapped_column(String(64), default="*")
    behavior: Mapped[str] = mapped_column(String(20))
    updated_at: Mapped[datetime] = mapped_column(TS, default=now)
    __table_args__ = (UniqueConstraint("provider", "reference_id", name="uq_mock_scenario"),)


class MockMid(Base):
    __tablename__ = "mock_mids"
    idempotency_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    mid: Mapped[str | None] = mapped_column(String(40))
    failures: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[dict] = mapped_column(J, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=now)


BEHAVIORS = {
    "PAN": ["auto", "success", "fail", "duplicate", "late", "late_once", "outage", "no_callback", "out_of_order"],
    "GST": ["auto", "success", "fail", "duplicate", "late", "late_once", "outage", "no_callback", "out_of_order"],
    "BANK": ["auto", "success", "fail", "duplicate", "late", "late_once", "outage", "no_callback", "out_of_order"],
    "RISK": ["auto", "success", "fail", "duplicate", "late", "late_once", "outage", "no_callback"],
    "MID": ["auto", "success", "fail", "fail_3", "timeout"],
}


async def scenario_for(session, provider: str, reference_id: str) -> str:
    rows = (await session.execute(select(MockScenario).where(
        MockScenario.provider == provider, MockScenario.reference_id.in_([reference_id, "*"])))).scalars().all()
    specific = next((r for r in rows if r.reference_id == reference_id), None)
    general = next((r for r in rows if r.reference_id == "*"), None)
    return (specific or general).behavior if (specific or general) else "auto"


# ------------------------------------------------------------------ provider logic ------------------------------
def similarity(a: str | None, b: str | None) -> int:
    na = " ".join((a or "").upper().replace("PRIVATE", "").replace("LIMITED", "").replace("PVT", "").replace("LTD", "")
                  .split())
    nb = " ".join((b or "").upper().replace("PRIVATE", "").replace("LIMITED", "").replace("PVT", "").replace("LTD", "")
                  .split())
    return int(difflib.SequenceMatcher(None, na, nb).ratio() * 100)


def evaluate(provider: str, data: dict, forced: str) -> tuple[str, str | None, dict]:
    """Returns (status, reason_code, result)."""
    if provider == "PAN":
        pan = (data.get("pan") or "").upper()
        if forced == "fail" or pan[5:9] == "0000":
            return "FAILED", "PAN_INVALID", {"status": "INVALID"}
        if pan[5:9] == "9999":
            return "FAILED", "PAN_DEACTIVATED", {"status": "DEACTIVATED"}
        return "PASSED", None, {"status": "VALID", "holder_type": pan[3:4], "name_match": True,
                                "name_match_score": 100}
    if provider == "GST":
        gstin = (data.get("gstin") or "").upper()
        if forced == "fail" or gstin[12:13] == "9":
            return "FAILED", "GSTIN_CANCELLED", {"registration_status": "Cancelled", "cancelled_on": "2024-01-31"}
        if gstin[12:13] == "8":
            return "FAILED", "GSTIN_NOT_FOUND", {"registration_status": "Not found"}
        return "PASSED", None, {"registration_status": "Active", "legal_name": data.get("legal_name"),
                                "state_code": gstin[:2]}
    if provider == "BANK":
        acc = data.get("account_number") or ""
        holder = (data.get("account_holder_name") or "").upper()
        if forced == "fail" or acc.endswith("0000"):
            return "FAILED", "ACCOUNT_INVALID", {"account_status": "INVALID"}
        beneficiary = "NEXUS SOFT SOLUTIONS" if acc.endswith("1111") else holder
        score = similarity(beneficiary, data.get("expected_name"))
        if score < 80:
            return "FAILED", "BENEFICIARY_NAME_MISMATCH", {"account_status": "ACTIVE",
                                                           "beneficiary_name": beneficiary,
                                                           "name_match": False, "name_match_score": score}
        return "PASSED", None, {"account_status": "ACTIVE", "beneficiary_name": beneficiary, "name_match": True,
                                "name_match_score": score}
    # RISK
    signals = []
    category = data.get("category")
    if category in ("gaming", "crypto"):
        signals.append({"code": "high_risk_category", "weight": 45})
    elif category == "jewellery":
        signals.append({"code": "high_risk_category", "weight": 25})
    reg = data.get("gst_registration_date")
    age_days = None
    try:
        age_days = (date.today() - date.fromisoformat(reg)).days if reg else None
    except ValueError:
        pass
    if age_days is not None and age_days < 180:
        signals.append({"code": "new_gst_registration", "weight": 15})
    s = data.get("signals") or {}
    if s.get("duplicate_matches"):
        signals.append({"code": "duplicate_matches", "weight": 25})
    if s.get("name_conflicts"):
        signals.append({"code": "name_conflicts", "weight": 10})
    if s.get("bank_changed_after_approval"):
        signals.append({"code": "bank_changed_after_approval", "weight": 20})
    if (data.get("monthly_volume") or 0) > 5_000_000 and (age_days is None or age_days < 730):
        signals.append({"code": "high_volume_new_business", "weight": 12})
    if forced == "fail":
        signals.append({"code": "watchlist_hit", "weight": 80})
    score = min(100, 8 + sum(x["weight"] for x in signals))
    band = "LOW" if score <= 30 else "MEDIUM" if score <= 60 else "HIGH"
    return "PASSED", None, {"score": score, "band": band, "signals": signals}


def sign(body: bytes) -> dict:
    ts = str(int(time.time()))
    sig = hmac.new(settings.webhook_secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    return {"X-ML-Timestamp": ts, "X-ML-Signature": f"sha256={sig}", "Content-Type": "application/json"}


def event(provider: str, request_id: str, provider_ref: str, status: str, reason: str | None, result: dict,
          event_id: str | None = None) -> dict:
    return {"event_id": event_id or f"evt_{uuid.uuid4().hex[:16]}", "provider": provider, "request_id": request_id,
            "provider_ref": provider_ref, "status": status, "reason_code": reason, "result": result,
            "occurred_at": now().isoformat()}


# ------------------------------------------------------------------ app ------------------------------------------
class VerifyIn(BaseModel):
    request_id: str
    reference_id: str
    callback_url: str
    data: dict


class MidIn(BaseModel):
    idempotency_key: str
    data: dict = {}


class ScenarioIn(BaseModel):
    provider: str
    behavior: str
    reference_id: str | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    task = asyncio.create_task(deliver_loop())
    yield
    task.cancel()


app = FastAPI(title="MapleLaunch Mock Providers", lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


async def _verify(provider: str, body: VerifyIn):
    async with Session() as s:
        existing = await s.get(MockRequest, body.request_id)
        if existing:  # idempotent: same request id -> same job, nothing re-scheduled
            return {"provider_ref": existing.provider_ref, "status": "PENDING", "idempotent_replay": True}
        behavior = await scenario_for(s, provider, body.reference_id)
        if behavior == "outage":
            raise HTTPException(503, f"{provider} provider temporarily unavailable")
        prior = (await s.execute(select(MockRequest).where(MockRequest.provider == provider,
                                                           MockRequest.reference_id == body.reference_id))).first()
        ref = f"{provider.lower()}_{uuid.uuid4().hex[:10]}"
        s.add(MockRequest(request_id=body.request_id, provider=provider, reference_id=body.reference_id,
                          provider_ref=ref, data=body.data))
        status, reason, result = evaluate(provider, body.data, "fail" if behavior == "fail" else "auto")
        if behavior == "success" and status == "FAILED":
            status, reason = "PASSED", None
            result = {**result, "forced": "success"}
        t0 = now()
        delay = random.uniform(settings.min_delay_seconds, settings.max_delay_seconds)
        if behavior == "late" or (behavior == "late_once" and prior is None):
            delay = settings.late_delay_seconds
        cbs = [(t0 + timedelta(seconds=0.5), event(provider, body.request_id, ref, "PENDING", None, {}))]
        if behavior != "no_callback":
            final = event(provider, body.request_id, ref, status, reason, result)
            cbs.append((t0 + timedelta(seconds=delay), final))
            if behavior == "duplicate":  # identical event delivered three times
                cbs += [(t0 + timedelta(seconds=delay + 1.5), final), (t0 + timedelta(seconds=delay + 3), final)]
            if behavior == "out_of_order":  # a stale progress event after the final result
                cbs.append((t0 + timedelta(seconds=delay + 2), event(provider, body.request_id, ref, "PENDING",
                                                                     None, {"note": "stale progress update"})))
        for at, payload in cbs:
            s.add(MockCallback(url=body.callback_url, payload=payload, send_at=at))
        await s.commit()
    return {"provider_ref": ref, "status": "PENDING"}


@app.post("/v1/pan/verify", status_code=202)
async def pan(body: VerifyIn):
    return await _verify("PAN", body)


@app.post("/v1/gst/verify", status_code=202)
async def gst(body: VerifyIn):
    return await _verify("GST", body)


@app.post("/v1/bank/penny-drop", status_code=202)
async def bank(body: VerifyIn):
    return await _verify("BANK", body)


@app.post("/v1/risk/assess", status_code=202)
async def risk(body: VerifyIn):
    return await _verify("RISK", body)


def _new_mid() -> str:
    return "MLN" + "".join(random.choice("0123456789") for _ in range(9))


@app.post("/v1/mid")
async def create_mid(body: MidIn):
    async with Session() as s:
        row = await s.get(MockMid, body.idempotency_key)
        if row and row.mid:
            return {"mid": row.mid, "idempotent_replay": True}
        if row is None:
            row = MockMid(idempotency_key=body.idempotency_key, data=body.data, failures=0)
            s.add(row)
        behavior = await scenario_for(s, "MID", body.idempotency_key)
        if behavior == "fail" or (behavior == "fail_3" and row.failures < 3):
            row.failures += 1
            await s.commit()
            raise HTTPException(500, f"MID service internal error (failure #{row.failures})")
        row.mid = _new_mid()
        await s.commit()
        mid = row.mid
    if behavior == "timeout":  # created, but the response is too slow: caller must check status before retrying
        await asyncio.sleep(12)
    return {"mid": mid}


@app.get("/v1/mid/{key}")
async def get_mid(key: str):
    async with Session() as s:
        row = await s.get(MockMid, key)
        if row is None or not row.mid:
            raise HTTPException(404, "No merchant ID for this key")
        return {"mid": row.mid}


def _admin(token: str | None):
    if token != settings.provider_admin_token:
        raise HTTPException(401, "Bad admin token")


@app.get("/v1/admin/scenarios")
async def list_scenarios(x_admin_token: str | None = Header(default=None)):
    _admin(x_admin_token)
    async with Session() as s:
        rows = (await s.execute(select(MockScenario).order_by(MockScenario.updated_at.desc()))).scalars()
        pending = (await s.execute(text("SELECT count(*) FROM mock_callbacks WHERE status='pending'"))).scalar()
        return {"behaviors": BEHAVIORS, "pending_callbacks": pending,
                "scenarios": [{"provider": r.provider, "reference_id": None if r.reference_id == "*" else r.reference_id,
                               "behavior": r.behavior, "updated_at": r.updated_at.isoformat()} for r in rows]}


@app.put("/v1/admin/scenarios")
async def set_scenario(body: ScenarioIn, x_admin_token: str | None = Header(default=None)):
    _admin(x_admin_token)
    provider = body.provider.upper()
    if provider not in BEHAVIORS or body.behavior not in BEHAVIORS[provider]:
        raise HTTPException(422, "Unknown provider or behaviour")
    ref = body.reference_id or "*"
    async with Session() as s:
        row = (await s.execute(select(MockScenario).where(MockScenario.provider == provider,
                                                          MockScenario.reference_id == ref))).scalar_one_or_none()
        if body.behavior == "auto":
            if row:
                await s.delete(row)
        elif row:
            row.behavior, row.updated_at = body.behavior, now()
        else:
            s.add(MockScenario(provider=provider, reference_id=ref, behavior=body.behavior))
        await s.commit()
    return {"ok": True}


@app.delete("/v1/admin/scenarios")
async def reset(x_admin_token: str | None = Header(default=None)):
    _admin(x_admin_token)
    async with Session() as s:
        await s.execute(text("DELETE FROM mock_scenarios WHERE reference_id = '*'"))
        await s.commit()
    return {"ok": True}


# ------------------------------------------------------------------ delivery -------------------------------------
async def deliver_loop():
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=70.0)) as client:
        while True:
            try:
                async with Session() as s:
                    due = (await s.execute(select(MockCallback).where(MockCallback.status == "pending",
                                                                      MockCallback.send_at <= now())
                                           .order_by(MockCallback.send_at).limit(10)
                                           .with_for_update(skip_locked=True))).scalars().all()
                    for cb in due:
                        body = json.dumps(cb.payload).encode()
                        cb.attempts += 1
                        try:
                            r = await client.post(cb.url, content=body, headers=sign(body))
                            if r.status_code >= 500:
                                raise RuntimeError(f"receiver returned {r.status_code}")
                            cb.status = "sent" if r.status_code < 400 else "rejected"
                            cb.last_error = None if r.status_code < 400 else r.text[:300]
                        except Exception as exc:  # receiver asleep/down: retry with backoff, like real providers
                            cb.last_error = str(exc)[:300]
                            if cb.attempts >= 8:
                                cb.status = "failed"
                            else:
                                cb.send_at = now() + timedelta(seconds=min(2 ** cb.attempts, 60))
                    await s.commit()
            except Exception as exc:
                print("deliver_loop error:", exc)
            await asyncio.sleep(0.5)
