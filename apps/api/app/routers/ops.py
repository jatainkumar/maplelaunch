"""Operator console: queue, application detail, human decisions, PII reveal, exceptions."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt
from app.core.security import actor, require_role
from app.db.models import (
    AgentDecision,
    Application,
    CallbackEvent,
    DuplicateMatch,
    OpsException,
    ReviewTask,
    User,
    utcnow,
)
from app.db.session import get_session
from app.domain.states import CHECK_IN_FLIGHT, TERMINAL, S
from app.jobs.queue import enqueue
from app.routers import views
from app.services.applications import PII_FIELDS, get_pii
from app.services.audit import audit, verify_chain
from app.services.checks import current_checks
from app.workflow import runner

router = APIRouter(prefix="/ops", tags=["ops"])
staff = require_role("operator", "admin")


def _minutes(a: datetime | None, b: datetime | None) -> float | None:
    return round((b - a).total_seconds() / 60, 1) if a and b else None


@router.get("/overview")
async def overview(user: User = Depends(staff), s: AsyncSession = Depends(get_session)):
    by_status = dict((await s.execute(select(Application.status, func.count()).group_by(Application.status))).all())
    open_exc = (await s.execute(select(func.count()).select_from(OpsException)
                                .where(OpsException.status == "open"))).scalar()
    open_reviews = (await s.execute(select(func.count()).select_from(ReviewTask)
                                    .where(ReviewTask.status == "open"))).scalar()
    decided = list((await s.execute(select(Application).where(Application.decided_at.is_not(None)))).scalars())
    auto = sum(1 for a in decided if a.decided_by in ("agent", "rules-engine"))
    times = [m for a in decided if (m := _minutes(a.submitted_at, a.decided_at)) is not None]
    dup_callbacks = (await s.execute(select(func.coalesce(func.sum(CallbackEvent.duplicate_count), 0)))).scalar()
    late = (await s.execute(select(func.count()).select_from(CallbackEvent)
                            .where(CallbackEvent.outcome.in_(["late_accepted", "stale_superseded"])))).scalar()
    submitted = sum(c for st, c in by_status.items() if st not in ("DRAFT",))
    with_exceptions = (await s.execute(select(func.count(func.distinct(OpsException.application_id))))).scalar()
    return {
        "by_status": by_status, "open_exceptions": open_exc, "open_reviews": open_reviews,
        "decided": len(decided), "auto_decided": auto,
        "auto_approval_rate": round(auto / len(decided), 2) if decided else None,
        "median_minutes_to_decision": sorted(times)[len(times) // 2] if times else None,
        "duplicate_callbacks_ignored": int(dup_callbacks or 0), "late_callbacks": late,
        "exception_rate": round(with_exceptions / submitted, 2) if submitted else None,
    }


@router.get("/applications")
async def queue(status: str | None = None, q: str | None = None, attention: bool = False,
                user: User = Depends(staff), s: AsyncSession = Depends(get_session)):
    stmt = select(Application).where(Application.status != S.DRAFT).order_by(Application.updated_at.desc()).limit(200)
    if status:
        stmt = stmt.where(Application.status.in_(status.split(",")))
    apps = list((await s.execute(stmt)).scalars())
    ids = [a.id for a in apps]
    exc = dict((await s.execute(select(OpsException.application_id, func.count()).where(
        OpsException.application_id.in_(ids), OpsException.status == "open").group_by(OpsException.application_id))).all())
    reviews = {r.application_id: r for r in (await s.execute(select(ReviewTask).where(
        ReviewTask.application_id.in_(ids), ReviewTask.status == "open"))).scalars()}
    dups = dict((await s.execute(select(DuplicateMatch.application_id, func.count()).where(
        DuplicateMatch.application_id.in_(ids), DuplicateMatch.status == "open")
        .group_by(DuplicateMatch.application_id))).all())
    out = []
    now = utcnow()
    for a in apps:
        row = views.app_summary(a) | {
            "open_exceptions": exc.get(a.id, 0), "open_duplicates": dups.get(a.id, 0),
            "review": None if a.id not in reviews else {"priority": reviews[a.id].priority,
                                                        "recommendation": reviews[a.id].recommendation,
                                                        "kind": reviews[a.id].kind},
            "minutes_in_state": _minutes(a.status_changed_at, now),
        }
        needs = row["open_exceptions"] or row["review"] or a.status in (S.PROVISIONING_FAILED,)
        if attention and not needs:
            continue
        if q and q.lower() not in " ".join(filter(None, [a.reference, row["legal_name"], row["trade_name"]])).lower():
            continue
        out.append(row)
    return out


@router.get("/applications/{app_id}")
async def detail(app_id: str, user: User = Depends(staff), s: AsyncSession = Depends(get_session)):
    app = await s.get(Application, app_id)
    if app is None:
        raise HTTPException(404, "Not found")
    out = await views.ops_detail(s, app)
    out["audit_chain"] = await verify_chain(s, app_id)
    try:
        # A closed (withdrawn / rejected) application is not waiting for anyone, whatever the checkpoint says.
        out["waiting_for"] = None if S(app.status) in TERMINAL else await runner.waiting_for(app_id)
    except Exception:
        out["waiting_for"] = None
    return out


class RevealIn(BaseModel):
    field: Literal["pan", "gstin", "account_number", "phone", "email", "cin"]
    reason: str


@router.post("/applications/{app_id}/reveal")
async def reveal(app_id: str, body: RevealIn, user: User = Depends(staff), s: AsyncSession = Depends(get_session)):
    if len(body.reason.strip()) < 5:
        raise HTTPException(422, "Give a short reason for revealing this value")
    pii = await get_pii(s, app_id)
    value = decrypt(getattr(pii, f"{PII_FIELDS[body.field][0]}_enc"))
    await audit(s, app_id, actor(user), "pii_revealed", {"field": body.field, "reason": body.reason})
    return {"field": body.field, "value": value}


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "request_info", "retry_check"]
    note: str = ""
    items: list[dict] = []
    message: str | None = None
    checks: list[Literal["PAN", "GST", "BANK", "RISK"]] = []
    version: int | None = None


@router.post("/applications/{app_id}/decision")
async def decide(app_id: str, body: DecisionIn, user: User = Depends(staff), s: AsyncSession = Depends(get_session)):
    app = await s.get(Application, app_id)
    if app is None:
        raise HTTPException(404, "Not found")
    if body.version is not None and body.version != app.version:
        raise HTTPException(409, "This application changed while you were looking at it. Refresh and try again")
    if app.status != S.MANUAL_REVIEW:
        raise HTTPException(409, f"Application is {app.status}, not in manual review")
    if await runner.waiting_for(app_id) != "review":
        raise HTTPException(409, "The workflow is busy (e.g. re-verifying after a change). Try again in a moment.")
    if body.decision == "reject" and len(body.note.strip()) < 5:
        raise HTTPException(422, "A rejection needs a reason; it is shared with the merchant")
    if body.decision == "approve":
        in_flight = [t for t, c in (await current_checks(s, app_id)).items() if c.status in CHECK_IN_FLIGHT]
        if in_flight:
            raise HTTPException(409, f"Wait for {', '.join(in_flight)} to finish before approving")
    if body.decision == "request_info" and not body.items:
        raise HTTPException(422, "Choose at least one item to request")
    if body.decision == "retry_check" and not body.checks:
        raise HTTPException(422, "Choose at least one check to retry")
    await s.execute(update(ReviewTask).where(ReviewTask.application_id == app_id, ReviewTask.status == "open",
                                             ReviewTask.kind == "pre_approval")
                    .values(status="resolved", decision=body.decision, decision_note=body.note, assignee=user.email,
                            resolved_at=utcnow()))
    s.add(AgentDecision(application_id=app_id, action=f"human:{body.decision}", reasoning=body.note, model="human",
                        args={"items": body.items, "checks": body.checks}))
    await audit(s, app_id, actor(user), "review_decision", {"decision": body.decision, "note": body.note})
    await enqueue(s, "resume_workflow", {"kind": "review_decision", "data": {
        "decision": body.decision, "note": body.note, "actor": actor(user), "items": body.items,
        "message": body.message, "checks": body.checks}}, application_id=app_id)
    return {"ok": True}


@router.post("/applications/{app_id}/retry-provisioning")
async def retry_provisioning(app_id: str, user: User = Depends(staff), s: AsyncSession = Depends(get_session)):
    app = await s.get(Application, app_id)
    if app is None or app.status != S.PROVISIONING_FAILED:
        raise HTTPException(409, "Only failed provisioning can be retried")
    await audit(s, app_id, actor(user), "provisioning_retry_requested", {})
    await enqueue(s, "resume_workflow", {"kind": "retry_provisioning"}, application_id=app_id)
    return {"ok": True}


class NoteIn(BaseModel):
    note: str = ""


@router.post("/applications/{app_id}/release-hold")
async def release_hold(app_id: str, body: NoteIn, user: User = Depends(staff), s: AsyncSession = Depends(get_session)):
    app = await s.get(Application, app_id)
    if app is None or not app.payouts_on_hold:
        raise HTTPException(409, "Payouts are not on hold")
    checks = await current_checks(s, app_id)
    if checks.get("BANK") and checks["BANK"].status in CHECK_IN_FLIGHT:
        raise HTTPException(409, "Bank re-verification is still running")
    app.payouts_on_hold = False
    await s.execute(update(ReviewTask).where(ReviewTask.application_id == app_id, ReviewTask.status == "open",
                                             ReviewTask.kind == "post_live")
                    .values(status="resolved", decision="release_hold", decision_note=body.note,
                            assignee=user.email, resolved_at=utcnow()))
    await s.execute(update(OpsException).where(OpsException.application_id == app_id,
                                               OpsException.kind == "post_live_bank_change",
                                               OpsException.status == "open")
                    .values(status="resolved", resolved_at=utcnow()))
    await audit(s, app_id, actor(user), "payouts_released", {"note": body.note})
    return {"ok": True}


class DuplicateIn(BaseModel):
    status: Literal["cleared", "confirmed"]


@router.post("/duplicates/{match_id}")
async def resolve_duplicate(match_id: str, body: DuplicateIn, user: User = Depends(staff),
                            s: AsyncSession = Depends(get_session)):
    m = await s.get(DuplicateMatch, match_id)
    if m is None:
        raise HTTPException(404, "Not found")
    m.status = body.status
    await audit(s, m.application_id, actor(user), "duplicate_" + body.status,
                {"matched_application_id": m.matched_application_id})
    return {"ok": True}


@router.post("/exceptions/{exc_id}/resolve")
async def resolve_exception(exc_id: str, body: NoteIn, user: User = Depends(staff),
                            s: AsyncSession = Depends(get_session)):
    e = await s.get(OpsException, exc_id)
    if e is None:
        raise HTTPException(404, "Not found")
    e.status = "resolved"
    e.resolved_at = utcnow()
    await audit(s, e.application_id, actor(user), "exception_resolved", {"kind": e.kind, "note": body.note})
    return {"ok": True}


@router.get("/exceptions")
async def list_exceptions(user: User = Depends(staff), s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(OpsException, Application.reference)
                            .outerjoin(Application, Application.id == OpsException.application_id)
                            .where(OpsException.status == "open").order_by(OpsException.created_at.desc()))).all()
    return [{"id": e.id, "application_id": e.application_id, "reference": ref, "kind": e.kind,
             "severity": e.severity, "message": e.message, "created_at": views.iso(e.created_at)} for e, ref in rows]
