"""Admin: versioned policy editor, dead-letter jobs and (demo mode only) the scenario lab and demo reset."""

import copy

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import actor, demo_only, require_role
from app.db.models import Job, Policy, User
from app.db.session import get_session
from app.domain.policy import CATEGORIES, DEFAULT_POLICY, DOC_TYPES, get_active_policy, save_policy
from app.domain.states import CHECK_TYPES
from app.routers.views import iso
from app.services import providers
from app.services.audit import audit

router = APIRouter(prefix="/admin", tags=["admin"])
admin_only = require_role("admin")
staff = require_role("operator", "admin")


@router.get("/policy")
async def get_policy(user: User = Depends(staff), s: AsyncSession = Depends(get_session)):
    version, data = await get_active_policy(s)
    rows = (await s.execute(select(Policy).order_by(Policy.version.desc()).limit(20))).scalars()
    return {"version": version, "data": data,
            "history": [{"version": p.version, "note": p.note, "created_by": p.created_by,
                         "created_at": iso(p.created_at), "is_active": p.is_active} for p in rows]}


class PolicyIn(BaseModel):
    data: dict
    note: str


def _validate_policy(d: dict) -> None:
    try:
        for bt in ("proprietorship", "partnership", "private_limited"):
            rules = d["business_types"][bt]
            if not set(rules["required_documents"]) <= set(DOC_TYPES):
                raise ValueError(f"{bt}: unknown document type")
            if not set(rules["required_checks"]) <= set(CHECK_TYPES):
                raise ValueError(f"{bt}: unknown check")
            if "PAN_CARD" not in rules["required_documents"] or "PAN" not in rules["required_checks"]:
                raise ValueError(f"{bt}: PAN document and PAN check are always required")
        t = d["thresholds"]
        if not 0 <= t["min_extraction_confidence"] <= 1 or not 0 <= t["min_document_quality"] <= 1:
            raise ValueError("confidence/quality thresholds must be between 0 and 1")
        if not 50 <= t["name_match_min"] <= 100:
            raise ValueError("name match threshold must be 50-100")
        if not 0 <= t["auto_approve_max_risk"] <= 100:
            raise ValueError("risk threshold must be 0-100")
        if not set(d.get("high_risk_categories", [])) <= set(CATEGORIES):
            raise ValueError("unknown category in high-risk list")
        if not 10 <= int(d["check_timeout_seconds"]) <= 3600:
            raise ValueError("check timeout must be 10-3600 seconds")
        if not 0 <= int(d["max_check_retries"]) <= 5 or not 1 <= int(d["mid_max_attempts"]) <= 6:
            raise ValueError("retry limits out of range")
    except (KeyError, TypeError) as exc:
        raise HTTPException(422, f"Policy is missing a field: {exc}") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.put("/policy")
async def put_policy(body: PolicyIn, user: User = Depends(admin_only), s: AsyncSession = Depends(get_session)):
    _validate_policy(body.data)
    if len(body.note.strip()) < 3:
        raise HTTPException(422, "Describe the change")
    _, before = await get_active_policy(s)
    row = await save_policy(s, copy.deepcopy(body.data), body.note, actor(user))
    await audit(s, None, actor(user), "policy_changed", {"version": row.version, "note": body.note,
                                                         "before_thresholds": before.get("thresholds"),
                                                         "after_thresholds": body.data.get("thresholds")})
    return {"version": row.version}


# ------------------------------------------------------------------ scenario lab ---------------------------------
class ScenarioIn(BaseModel):
    provider: str
    behavior: str
    reference_id: str | None = None


@router.get("/scenarios", dependencies=[Depends(demo_only)])
async def get_scenarios(user: User = Depends(staff)):
    try:
        return await providers.admin("GET", "/v1/admin/scenarios")
    except Exception as exc:
        raise HTTPException(502, f"Mock providers unreachable: {exc}") from exc


@router.put("/scenarios", dependencies=[Depends(demo_only)])
async def put_scenario(body: ScenarioIn, user: User = Depends(admin_only), s: AsyncSession = Depends(get_session)):
    try:
        result = await providers.admin("PUT", "/v1/admin/scenarios", body.model_dump())
    except Exception as exc:
        raise HTTPException(502, f"Mock providers unreachable: {exc}") from exc
    await audit(s, body.reference_id, actor(user), "scenario_set", body.model_dump())
    return result


@router.delete("/scenarios", dependencies=[Depends(demo_only)])
async def reset_scenarios(user: User = Depends(admin_only)):
    return await providers.admin("DELETE", "/v1/admin/scenarios")


# ------------------------------------------------------------------ demo reset -----------------------------------
APP_TABLES = ["agent_decisions", "audit_log", "callback_events", "duplicate_matches", "extractions", "info_requests",
              "jobs", "notifications", "ops_exceptions", "review_tasks", "state_transitions", "validation_results",
              "verification_checks", "documents", "application_pii", "applications"]
CHECKPOINT_TABLES = ["checkpoint_writes", "checkpoint_blobs", "checkpoints"]


@router.post("/reset-demo", dependencies=[Depends(demo_only)])
async def reset_demo(user: User = Depends(admin_only), s: AsyncSession = Depends(get_session)):
    """Wipe all applications (and their workflow checkpoints) so reviewers get a clean demo. Users are kept, and the
    default policy is restored as a new version if it was edited (the history stays)."""
    from sqlalchemy import text

    await s.execute(text("TRUNCATE " + ", ".join(APP_TABLES + CHECKPOINT_TABLES)))
    _, active = await get_active_policy(s)
    restored = active != DEFAULT_POLICY
    if restored:
        await save_policy(s, copy.deepcopy(DEFAULT_POLICY), "Restored defaults (demo reset)", actor(user))
    await audit(s, None, actor(user), "demo_data_reset", {"policy_restored": restored})
    return {"ok": True, "policy_restored": restored}


# ------------------------------------------------------------------ dead-letter jobs -----------------------------
@router.get("/jobs")
async def dead_jobs(user: User = Depends(staff), s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(Job).where(Job.status == "dead").order_by(Job.updated_at.desc()).limit(50))).scalars()
    return [{"id": j.id, "type": j.type, "application_id": j.application_id, "attempts": j.attempts,
             "last_error": j.last_error, "updated_at": iso(j.updated_at)} for j in rows]


@router.post("/jobs/{job_id}/replay")
async def replay(job_id: str, user: User = Depends(staff), s: AsyncSession = Depends(get_session)):
    job = await s.get(Job, job_id)
    if job is None or job.status != "dead":
        raise HTTPException(409, "Only dead jobs can be replayed")
    job.status, job.attempts, job.last_error = "queued", 0, None
    from app.db.models import utcnow

    job.run_at = utcnow()
    await audit(s, job.application_id, actor(user), "job_replayed", {"type": job.type})
    return {"ok": True}
