"""Merchant-facing endpoints: draft → upload (with instant AI autofill) → submit → respond to requests → bank change."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import actor, current_user
from app.db.models import (Application, Document, InfoRequest, Notification, OpsException, ReviewTask, User,
                           utcnow)
from app.db.session import get_session, session_scope
from app.domain import validators as v
from app.domain.policy import BUSINESS_TYPES, CATEGORIES, DOC_TYPES, get_active_policy, required_documents
from app.domain.states import BANK_CHANGE_ALLOWED, MERCHANT_WITHDRAWABLE, S, transition
from app.jobs.queue import enqueue
from app.routers import views
from app.services import checks as checks_svc
from app.services.applications import app_data, new_reference, set_fields
from app.services.audit import audit
from app.services.documents import ALLOWED_MIME, MAX_BYTES, run_extraction, save_document
from app.services.storage import storage

router = APIRouter(prefix="/applications", tags=["merchant"])


async def own_app(session: AsyncSession, app_id: str, user: User) -> Application:
    app = await session.get(Application, app_id)
    if app is None or (app.merchant_user_id != user.id and user.role not in ("operator", "admin")):
        raise HTTPException(404, "Application not found")
    return app


class CreateIn(BaseModel):
    business_type: Literal["proprietorship", "partnership", "private_limited"]
    category: str


@router.post("")
async def create(body: CreateIn, user: User = Depends(current_user), s: AsyncSession = Depends(get_session)):
    if body.category not in CATEGORIES:
        raise HTTPException(422, "Unknown category")
    app = Application(reference=new_reference(), merchant_user_id=user.id, business_type=body.business_type,
                      category=body.category, form_data={})
    s.add(app)
    await s.flush()
    await set_fields(s, app, {"email": user.email})
    await audit(s, app.id, actor(user), "application_created", {"business_type": body.business_type})
    return views.app_summary(app)


@router.get("")
async def list_mine(user: User = Depends(current_user), s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(Application).where(Application.merchant_user_id == user.id)
                            .order_by(Application.created_at.desc()))).scalars()
    return [views.app_summary(a) for a in rows]


@router.get("/{app_id}")
async def detail(app_id: str, user: User = Depends(current_user), s: AsyncSession = Depends(get_session)):
    app = await own_app(s, app_id, user)
    _, policy = await get_active_policy(s)
    open_request = next((r for r in await views.info_requests_view(s, app.id) if r["status"] == "open"), None)
    return {
        "application": views.app_summary(app),
        "data": await app_data(s, app, reveal=True),  # the merchant sees their own data
        "required_documents": required_documents(policy, app.business_type),
        "documents": await views.documents_view(s, app.id, reveal=True),
        "autofill": await views.autofill(s, app.id),
        "checks": [{"type": c["type"], "status": c["status"], "attempt": c["attempt"]}
                   for c in await views.checks_view(s, app.id, all_attempts=False)],
        "open_request": open_request,
        "timeline": await views.merchant_timeline(s, app.id),
        "notifications": await views.notifications_view(s, user.id, app.id),
        "can_change_bank": app.status in BANK_CHANGE_ALLOWED,
    }


class FieldsIn(BaseModel):
    legal_name: str | None = None
    trade_name: str | None = None
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    pincode: str | None = None
    monthly_volume: int | None = Field(default=None, ge=0)
    website: str | None = None
    pan: str | None = None
    gstin: str | None = None
    cin: str | None = None
    account_number: str | None = None
    ifsc: str | None = None
    account_holder_name: str | None = None
    category: str | None = None


@router.patch("/{app_id}")
async def update_fields(app_id: str, body: FieldsIn, user: User = Depends(current_user),
                        s: AsyncSession = Depends(get_session)):
    app = await own_app(s, app_id, user)
    if app.status != S.DRAFT:
        raise HTTPException(409, "Submitted applications can only be changed through a request or bank change")
    data = body.model_dump(exclude_none=True)
    if "category" in data:
        if data["category"] not in CATEGORIES:
            raise HTTPException(422, "Unknown category")
        app.category = data.pop("category")
    changed = await set_fields(s, app, data)
    return {"changed": changed, "data": await app_data(s, app, reveal=True)}


@router.post("/{app_id}/documents")
async def upload(app_id: str, slot: str = Form(...), file: UploadFile = File(...),
                 user: User = Depends(current_user), s: AsyncSession = Depends(get_session)):
    app = await own_app(s, app_id, user)
    if app.status not in (S.DRAFT, S.AWAITING_MERCHANT):
        raise HTTPException(409, "Documents can be uploaded while drafting or when we've asked for them")
    if slot not in DOC_TYPES:
        raise HTTPException(422, "Unknown document type")
    data = await file.read()
    mime = file.content_type or ""
    if mime not in ALLOWED_MIME:
        raise HTTPException(415, "Upload a PNG, JPG, WEBP or PDF file")
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File is larger than 8 MB")
    doc = await save_document(s, app.id, slot, file.filename or slot, mime, data, actor(user))
    await s.commit()  # keep the upload even if extraction is slow or fails
    ext = await run_extraction(s, doc, actor(user))
    return {
        "document": next(d for d in await views.documents_view(s, app.id, reveal=True) if d["id"] == doc.id),
        "autofill": await views.autofill(s, app.id),
        "extraction_error": ext.error,
    }


@router.get("/{app_id}/documents/{doc_id}/url")
async def document_url(app_id: str, doc_id: str, user: User = Depends(current_user),
                       s: AsyncSession = Depends(get_session)):
    app = await own_app(s, app_id, user)
    doc = await s.get(Document, doc_id)
    if doc is None or doc.application_id != app.id:
        raise HTTPException(404, "Document not found")
    if user.role != "merchant":
        await audit(s, app.id, actor(user), "document_viewed", {"slot": doc.slot})
    return {"url": await storage.signed_url(doc.storage_path, 60), "mime": doc.mime}


class SubmitIn(BaseModel):
    consent: bool


@router.post("/{app_id}/submit")
async def submit(app_id: str, body: SubmitIn, user: User = Depends(current_user),
                 s: AsyncSession = Depends(get_session)):
    app = await own_app(s, app_id, user)
    if app.status != S.DRAFT:
        raise HTTPException(409, "Already submitted")
    if not body.consent:
        raise HTTPException(422, "Please confirm the declaration and consent to verification")
    data = await app_data(s, app, reveal=True)
    missing = [k for k in ("legal_name", "phone", "pan", "account_number", "ifsc", "account_holder_name", "pincode")
               if not data.get(k)]
    if missing:
        raise HTTPException(422, f"Please complete: {', '.join(missing)}")
    if not v.valid_phone(data.get("phone")):
        raise HTTPException(422, "Enter a valid 10-digit Indian mobile number")
    await audit(s, app.id, actor(user), "consent_recorded",
                {"text": "Merchant consented to identity, tax, bank and risk verification", "at": utcnow().isoformat()})
    await transition(s, app, S.SUBMITTED, actor(user), "Submitted by merchant")
    await enqueue(s, "start_workflow", {}, application_id=app.id, dedupe_key=f"start:{app.id}")
    return views.app_summary(app)


class RespondIn(BaseModel):
    info_request_id: str
    fields: FieldsIn = FieldsIn()
    confirmations: list[str] = []
    note: str | None = None


@router.post("/{app_id}/respond")
async def respond(app_id: str, body: RespondIn, user: User = Depends(current_user),
                  s: AsyncSession = Depends(get_session)):
    app = await own_app(s, app_id, user)
    ir = await s.get(InfoRequest, body.info_request_id)
    if ir is None or ir.application_id != app.id or ir.status != "open":
        raise HTTPException(409, "This request is no longer open")
    if app.status != S.AWAITING_MERCHANT:
        raise HTTPException(409, "We're not waiting for anything right now")
    data = body.fields.model_dump(exclude_none=True)
    data.pop("category", None)
    changed = await set_fields(s, app, data)
    if body.confirmations:
        form = dict(app.form_data or {})
        form["confirmations"] = {**(form.get("confirmations") or {}), **{k: True for k in body.confirmations}}
        app.form_data = form
    ir.status = "responded"
    ir.responded_at = utcnow()
    await audit(s, app.id, actor(user), "merchant_responded",
                {"changed_fields": changed, "confirmed": body.confirmations, "note": body.note})
    await enqueue(s, "resume_workflow", {"kind": "merchant_responded"}, application_id=app.id)
    return {"ok": True, "changed": changed}


class BankChangeIn(BaseModel):
    account_number: str
    ifsc: str
    account_holder_name: str
    reason: str = ""


@router.post("/{app_id}/bank-change")
async def bank_change(app_id: str, body: BankChangeIn, user: User = Depends(current_user),
                      s: AsyncSession = Depends(get_session)):
    app = await own_app(s, app_id, user)
    status = S(app.status)
    if status not in BANK_CHANGE_ALLOWED:
        raise HTTPException(409, f"Bank details can't be changed while the application is '{status.value}'")
    if not v.valid_account(body.account_number) or not v.valid_ifsc(body.ifsc):
        raise HTTPException(422, "Enter a valid account number (9-18 digits) and IFSC")
    changed = await set_fields(s, app, body.model_dump(exclude={"reason"}))
    if not changed:
        return {"ok": True, "changed": []}
    await checks_svc.invalidate(s, app.id, "BANK", "BANK_DETAILS_CHANGED")
    await audit(s, app.id, actor(user), "bank_details_changed", {"fields": changed, "reason": body.reason,
                                                                 "status": status.value})
    if status == S.LIVE:
        app.payouts_on_hold = True
        await audit(s, app.id, "system", "payouts_on_hold", {"reason": "Bank details changed after go-live"})
        await enqueue(s, "resume_workflow", {"kind": "bank_changed"}, application_id=app.id)
    elif status in (S.VERIFYING, S.MANUAL_REVIEW):
        await enqueue(s, "resume_workflow", {"kind": "inputs_changed"}, application_id=app.id)
    return {"ok": True, "changed": changed, "payouts_on_hold": app.payouts_on_hold}


class WithdrawIn(BaseModel):
    reason: str | None = Field(None, max_length=500)


@router.post("/{app_id}/withdraw")
async def withdraw(app_id: str, body: WithdrawIn | None = None, user: User = Depends(current_user),
                   s: AsyncSession = Depends(get_session)):
    """Merchant withdraws an application at any point before approval.

    Takes the same per-application lock as the workflow, so it can never interleave with a running step. Open review
    tasks, information requests and exceptions are closed; late provider callbacks are recorded but never resume a
    withdrawn application."""
    from app.workflow import runner

    app = await own_app(s, app_id, user)
    if app.merchant_user_id != user.id:
        raise HTTPException(403, "Only the merchant can withdraw an application")
    if S(app.status) not in MERCHANT_WITHDRAWABLE:
        raise HTTPException(409, "This application is already approved or closed and can no longer be withdrawn")
    reason = ((body.reason if body else None) or "").strip() or None
    for _ in range(20):
        lock = runner.local_lock(app_id)
        if not lock.locked():
            async with lock, runner.app_lock(app_id) as acquired:
                if acquired:
                    await _withdraw(app_id, user, reason)
                    await s.refresh(app)
                    return views.app_summary(app)
        await asyncio.sleep(0.5)
    raise HTTPException(409, "We're processing an update on this application. Try again in a few seconds")


async def _withdraw(app_id: str, user: User, reason: str | None) -> None:
    async with session_scope() as s:
        app = await s.get(Application, app_id)
        status = S(app.status)
        if status not in MERCHANT_WITHDRAWABLE:
            raise HTTPException(409, "This application can no longer be withdrawn")
        note = "Draft discarded by merchant" if status == S.DRAFT else "Withdrawn by merchant"
        await transition(s, app, S.WITHDRAWN, actor(user), f"{note}: {reason}" if reason else note)
        await s.execute(update(ReviewTask).where(ReviewTask.application_id == app_id, ReviewTask.status == "open")
                        .values(status="cancelled"))
        await s.execute(update(InfoRequest).where(InfoRequest.application_id == app_id, InfoRequest.status == "open")
                        .values(status="withdrawn"))
        await s.execute(update(OpsException).where(OpsException.application_id == app_id,
                                                   OpsException.status == "open").values(status="resolved"))
        if status != S.DRAFT:
            from app.services.notifications import notify

            await notify(s, app.merchant_user_id, app.id, "Application withdrawn",
                         "You withdrew your application. Nothing else will happen with it, and you can start a new "
                         "one any time.")


notifications = APIRouter(prefix="/notifications", tags=["merchant"])


@notifications.get("")
async def my_notifications(user: User = Depends(current_user), s: AsyncSession = Depends(get_session)):
    return await views.notifications_view(s, user.id)


@notifications.post("/read")
async def mark_read(user: User = Depends(current_user), s: AsyncSession = Depends(get_session)):
    await s.execute(update(Notification).where(Notification.user_id == user.id).values(read=True))
    return {"ok": True}


meta = APIRouter(tags=["meta"])


@meta.get("/meta")
async def get_meta(s: AsyncSession = Depends(get_session)):
    version, policy = await get_active_policy(s)
    from app.domain.states import LABELS

    return {
        "business_types": BUSINESS_TYPES, "categories": CATEGORIES,
        "documents": {k: {"label": d["label"], "hint": d["hint"]} for k, d in DOC_TYPES.items()},
        "required_documents": {bt: r["required_documents"] for bt, r in policy["business_types"].items()},
        "high_risk_categories": policy.get("high_risk_categories", []),
        "status_labels": {k.value: lbl for k, lbl in LABELS.items()}, "policy_version": version,
        "mode": get_settings().app_mode,
    }


@meta.get("/ifsc/{code}")
async def ifsc(code: str):
    from app.services.ifsc import lookup_ifsc

    return await lookup_ifsc(code)
