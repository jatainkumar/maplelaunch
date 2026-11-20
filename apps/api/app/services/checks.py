"""Verification checks: dispatch to providers, idempotent callback handling, timeouts and late callbacks."""

import asyncio
import hashlib
import json
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import redact_obj
from app.db.models import Application, CallbackEvent, Extraction, VerificationCheck, new_id, utcnow
from app.db.session import session_scope
from app.domain.states import CHECK_IN_FLIGHT, CHECK_RANK, CHECK_TERMINAL, C
from app.jobs.queue import enqueue
from app.services import providers
from app.services.applications import app_data, extraction_value
from app.services.audit import audit
from app.services.dedupe import open_duplicates


async def current_checks(session: AsyncSession, app_id: str) -> dict[str, VerificationCheck]:
    rows = (await session.execute(select(VerificationCheck).where(VerificationCheck.application_id == app_id,
                                                                  VerificationCheck.is_current))).scalars()
    return {r.check_type: r for r in rows}


async def attempts_by_type(session: AsyncSession, app_id: str) -> dict[str, int]:
    rows = (await session.execute(select(VerificationCheck.check_type, VerificationCheck.attempt)
                                  .where(VerificationCheck.application_id == app_id))).all()
    out: dict[str, int] = {}
    for t, a in rows:
        out[t] = max(out.get(t, 0), a)
    return out


def _hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


async def build_payloads(session: AsyncSession, app: Application, bank_changed_after_approval: bool = False) -> dict:
    d = await app_data(session, app, reveal=True)
    exts = (await session.execute(select(Extraction).where(Extraction.application_id == app.id)
                                  .order_by(Extraction.created_at))).scalars()
    gst_reg_date = None
    for e in exts:
        gst_reg_date = extraction_value(e.fields, "registration_date") or gst_reg_date
    dups = await open_duplicates(session, app.id)
    payloads = {
        "PAN": {"pan": d.get("pan"), "name": d.get("legal_name")},
        "GST": {"gstin": d.get("gstin"), "legal_name": d.get("legal_name"), "trade_name": d.get("trade_name")},
        "BANK": {"account_number": d.get("account_number"), "ifsc": d.get("ifsc"),
                 "account_holder_name": d.get("account_holder_name"), "expected_name": d.get("legal_name")},
    }
    from app.db.models import ValidationResult  # local import to avoid cycles

    conflicts = (await session.execute(select(ValidationResult.rule).where(
        ValidationResult.application_id == app.id, ValidationResult.outcome == "warn",
        ValidationResult.rule.like("conflict%")))).scalars().all()
    payloads["RISK"] = {
        "category": app.category, "business_type": app.business_type,
        "monthly_volume": (app.form_data or {}).get("monthly_volume"),
        "gst_registration_date": gst_reg_date, "pincode": (app.form_data or {}).get("pincode"),
        "signals": {"duplicate_matches": len(dups), "name_conflicts": len(conflicts),
                    "bank_changed_after_approval": bank_changed_after_approval},
        "depends_on": {k: _hash(v) for k, v in payloads.items()},
    }
    return payloads


async def dispatch(app_id: str, required: list[str], force: list[str], timeout_s: int,
                   bank_changed_after_approval: bool = False) -> list[str]:
    """Create new check attempts where needed and call the providers in parallel.
    Phase 1 commits the attempt rows (so an instant callback can always find them); phase 2 calls providers."""
    to_call: list[tuple[str, str, dict]] = []
    async with session_scope() as s:
        app = await s.get(Application, app_id)
        payloads = await build_payloads(s, app, bank_changed_after_approval)
        current = await current_checks(s, app_id)
        dispatched_types = []
        order = [t for t in ("PAN", "GST", "BANK", "RISK") if t in required]
        for t in order:
            cur = current.get(t)
            h = _hash(payloads[t])
            if t == "RISK":
                need = (cur is None or cur.status != C.PASSED or cur.input_hash != h or bool(dispatched_types)
                        or t in force)
            else:
                need = cur is None or cur.status != C.PASSED or cur.input_hash != h or t in force
            if cur is not None and cur.status in CHECK_IN_FLIGHT and cur.input_hash == h and t not in force:
                need = False
            if not need:
                continue
            attempt = 1
            if cur is not None:
                cur.is_current = False
                if cur.status in CHECK_IN_FLIGHT:
                    cur.status = C.INVALIDATED
                    cur.reason_code = "SUPERSEDED"
                prev_max = (await attempts_by_type(s, app_id)).get(t, 0)
                attempt = prev_max + 1
            check = VerificationCheck(id=new_id(), application_id=app_id, check_type=t, attempt=attempt,
                                      status=C.REQUESTED, input_hash=h,
                                      deadline_at=utcnow() + timedelta(seconds=timeout_s))
            s.add(check)
            await s.flush()
            await audit(s, app_id, "system", "check_dispatched", {"check": t, "attempt": attempt,
                                                                  "request_id": check.id})
            await enqueue(s, "check_timeout", {"check_id": check.id}, application_id=app_id,
                          run_at=check.deadline_at, dedupe_key=f"timeout:{check.id}")
            to_call.append((t, check.id, payloads[t]))
            dispatched_types.append(t)

    async def call(t: str, request_id: str, payload: dict):
        try:
            resp = await providers.request_check(t, request_id, app_id, payload)
            return request_id, C.PENDING, resp.get("provider_ref"), None
        except providers.ProviderUnavailable as exc:
            return request_id, C.ERROR, None, ("PROVIDER_UNAVAILABLE", str(exc))
        except providers.ProviderRejected as exc:
            return request_id, C.ERROR, None, ("PROVIDER_REJECTED", str(exc))

    results = await asyncio.gather(*(call(*x) for x in to_call))  # parallel fan-out
    async with session_scope() as s:
        for request_id, status, ref, err in results:
            check = await s.get(VerificationCheck, request_id)
            if check is None or check.status != C.REQUESTED:
                continue  # a callback already moved it forward
            check.provider_ref = ref
            check.status = status
            if err:
                check.reason_code, msg = err
                check.completed_at = utcnow()
                check.result = {"error": msg}
                await audit(s, app_id, "system", "check_provider_error", {"check": check.check_type,
                                                                          "reason": err[0]})
    return [t for t, _, _ in to_call]


async def record_callback(session: AsyncSession, provider: str, event: dict) -> str:
    """Apply one provider callback. Returns the outcome; safe under duplicates, reordering and lateness."""
    provider = provider.upper()
    event_id = str(event.get("event_id") or "")
    request_id = str(event.get("request_id") or "")
    reported = str(event.get("status") or "").upper()
    stmt = insert(CallbackEvent).values(
        id=new_id(), provider=provider, event_id=event_id, request_id=request_id, outcome="received",
        reported_status=reported, payload=redact_obj(event), duplicate_count=0, received_at=utcnow(),
    ).on_conflict_do_nothing(constraint="uq_callback_provider_event").returning(CallbackEvent.id)
    inserted = (await session.execute(stmt)).scalar_one_or_none()
    if inserted is None:
        await session.execute(update(CallbackEvent).where(CallbackEvent.provider == provider,
                                                          CallbackEvent.event_id == event_id)
                              .values(duplicate_count=CallbackEvent.duplicate_count + 1))
        app_id = (await session.execute(select(CallbackEvent.application_id).where(
            CallbackEvent.provider == provider, CallbackEvent.event_id == event_id))).scalar_one_or_none()
        await audit(session, app_id, f"provider:{provider}", "callback_duplicate_ignored", {"event_id": event_id})
        return "duplicate"
    cb = await session.get(CallbackEvent, inserted)

    check = await session.get(VerificationCheck, request_id) if request_id else None
    if check is None or check.check_type != provider:
        cb.outcome = "unknown_request"
        await audit(session, None, f"provider:{provider}", "callback_unknown_request", {"event_id": event_id})
        return cb.outcome
    cb.application_id = check.application_id

    try:
        new = C(reported)
    except ValueError:
        cb.outcome = "invalid_status"
        return cb.outcome

    def apply():
        check.status = new
        check.reason_code = event.get("reason_code")
        check.result = redact_obj(event.get("result") or {})
        if new in CHECK_TERMINAL:
            check.completed_at = utcnow()

    if not check.is_current:
        cb.outcome = "stale_superseded"
        await audit(session, check.application_id, f"provider:{provider}", "callback_stale_ignored",
                    {"check": provider, "attempt": check.attempt, "status": reported,
                     "note": "Result for an older attempt arrived after a newer attempt was dispatched"})
        return cb.outcome
    if check.status == C.TIMED_OUT and new in CHECK_TERMINAL:
        apply()
        check.late = True
        cb.outcome = "late_accepted"
    elif CHECK_RANK[new] > CHECK_RANK[C(check.status)]:
        apply()
        cb.outcome = "applied"
    elif new == C(check.status) and new not in CHECK_TERMINAL:
        cb.outcome = "progress"  # provider confirms it's still working; nothing to change
        return cb.outcome
    else:
        cb.outcome = "ignored_out_of_order"
        await audit(session, check.application_id, f"provider:{provider}", "callback_out_of_order_ignored",
                    {"check": provider, "current": check.status, "reported": reported})
        return cb.outcome

    await audit(session, check.application_id, f"provider:{provider}", "callback_applied",
                {"check": provider, "attempt": check.attempt, "status": reported,
                 "reason": event.get("reason_code"), "late": check.late})
    if provider == "RISK" and new == C.PASSED:
        app = await session.get(Application, check.application_id)
        result = event.get("result") or {}
        app.risk_score = result.get("score")
        app.risk_band = result.get("band")
        app.risk_signals = result.get("signals") or []
        app.risk_explanation = None  # regenerated for the new score
    if new in CHECK_TERMINAL:
        await enqueue(session, "resume_workflow", {"kind": "check_updated"}, application_id=check.application_id)
    return cb.outcome


async def handle_timeout(session: AsyncSession, check_id: str) -> None:
    check = await session.get(VerificationCheck, check_id)
    if check is None or not check.is_current or check.status not in CHECK_IN_FLIGHT:
        return
    check.status = C.TIMED_OUT
    check.reason_code = "CALLBACK_TIMEOUT"
    check.completed_at = utcnow()
    await audit(session, check.application_id, "system", "check_timed_out",
                {"check": check.check_type, "attempt": check.attempt})
    await enqueue(session, "resume_workflow", {"kind": "check_updated"}, application_id=check.application_id)


async def invalidate(session: AsyncSession, app_id: str, check_type: str, reason: str) -> None:
    current = (await current_checks(session, app_id)).get(check_type)
    if current is not None and current.status != C.INVALIDATED:
        current.status = C.INVALIDATED
        current.reason_code = reason
        await audit(session, app_id, "system", "check_invalidated", {"check": check_type, "reason": reason})
