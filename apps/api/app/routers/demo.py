"""Demo helpers: persona catalogue, sample documents, one-click persona runs and 'apply the fix' shortcuts."""

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import actor, current_user, require_role
from app.db.models import Application, InfoRequest, User, utcnow
from app.db.session import get_session
from app.demo.personas import PERSONAS, sample_filename
from app.domain.states import S, transition
from app.jobs.queue import enqueue
from app.routers import views
from app.services import providers
from app.services.applications import new_reference, set_fields
from app.services.audit import audit
from app.services.documents import save_document

router = APIRouter(prefix="/demo", tags=["demo"])
SAMPLES = Path(__file__).resolve().parents[2] / "samples"
staff = require_role("operator", "admin")


def _files(key: str, fixed: bool = False) -> dict[str, str]:
    p = PERSONAS[key]
    docs = p["fix"]["documents"] if fixed else p["documents"]
    return {slot: sample_filename(slot, spec, fixed) for slot, spec in docs.items()}


@router.get("/personas")
async def personas():
    out = []
    for key, p in PERSONAS.items():
        form = {k: v for k, v in p["form"].items()}
        out.append({"key": key, "title": p["title"], "story": p["story"], "business_type": p["business_type"],
                    "category": p["category"], "form": form, "files": _files(key),
                    "fix_files": _files(key, True) if p.get("fix") else {}, "scenarios": p.get("scenarios", {})})
    return out


@router.get("/samples/{key}/{filename}")
async def sample_file(key: str, filename: str):
    if key not in PERSONAS:
        raise HTTPException(404, "Unknown persona")
    path = (SAMPLES / key / filename).resolve()
    if SAMPLES.resolve() not in path.parents or not path.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")


async def _apply_scenarios(app_id: str, scenarios: dict) -> None:
    for provider, behavior in scenarios.items():
        await providers.admin("PUT", "/v1/admin/scenarios",
                              {"provider": provider, "behavior": behavior, "reference_id": app_id})


@router.post("/personas/{key}/run")
async def run_persona(key: str, user: User = Depends(staff), s: AsyncSession = Depends(get_session)):
    """Creates and submits a complete application for the persona, owned by the demo merchant account."""
    p = PERSONAS.get(key)
    if p is None:
        raise HTTPException(404, "Unknown persona")
    merchant = (await s.execute(select(User).where(User.email == "merchant@example.com"))).scalar_one_or_none()
    if merchant is None:
        raise HTTPException(503, "Demo merchant not seeded yet")
    app = Application(reference=new_reference(), merchant_user_id=merchant.id, business_type=p["business_type"],
                      category=p["category"], persona=key, form_data={})
    s.add(app)
    await s.flush()
    await set_fields(s, app, p["form"])
    for slot, filename in _files(key).items():
        path = SAMPLES / key / filename
        mime = "application/pdf" if filename.endswith(".pdf") else "image/png"
        await save_document(s, app.id, slot, filename, mime, path.read_bytes(), "merchant:" + merchant.email)
    try:
        await _apply_scenarios(app.id, p.get("scenarios", {}))
    except Exception as exc:
        raise HTTPException(502, f"Mock providers unreachable: {exc}") from exc
    await audit(s, app.id, actor(user), "persona_started", {"persona": key})
    await audit(s, app.id, "merchant:" + merchant.email, "consent_recorded",
                {"text": "Merchant consented to identity, tax, bank and risk verification"})
    await transition(s, app, S.SUBMITTED, "merchant:" + merchant.email, f"Demo persona: {p['title']}")
    await enqueue(s, "start_workflow", {}, application_id=app.id, dedupe_key=f"start:{app.id}")
    return views.app_summary(app)


@router.post("/applications/{app_id}/apply-fix")
async def apply_fix(app_id: str, user: User = Depends(current_user), s: AsyncSession = Depends(get_session)):
    """Merchant shortcut for demo personas: upload the corrected sample documents and reply to the open request."""
    app = await s.get(Application, app_id)
    if app is None or (app.merchant_user_id != user.id and user.role == "merchant"):
        raise HTTPException(404, "Not found")
    p = PERSONAS.get(app.persona or "")
    if not p or not p.get("fix"):
        raise HTTPException(409, "This application has no sample fix")
    ir = (await s.execute(select(InfoRequest).where(InfoRequest.application_id == app.id,
                                                    InfoRequest.status == "open"))).scalars().first()
    if ir is None or app.status != S.AWAITING_MERCHANT:
        raise HTTPException(409, "Nothing is being requested right now")
    for slot, filename in _files(app.persona, True).items():
        path = SAMPLES / app.persona / filename
        mime = "application/pdf" if filename.endswith(".pdf") else "image/png"
        await save_document(s, app.id, slot, filename, mime, path.read_bytes(), actor(user))
    changed = await set_fields(s, app, p["fix"]["form"])
    ir.status, ir.responded_at = "responded", utcnow()
    await audit(s, app.id, actor(user), "merchant_responded", {"changed_fields": changed, "via": "sample fix"})
    await enqueue(s, "resume_workflow", {"kind": "merchant_responded"}, application_id=app.id)
    return {"ok": True}
