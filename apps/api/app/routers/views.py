"""Response builders shared by merchant and ops endpoints. PII is masked unless reveal=True."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AgentDecision,
    Application,
    AuditLog,
    CallbackEvent,
    Document,
    Extraction,
    InfoRequest,
    Notification,
    OpsException,
    ReviewTask,
    StateTransition,
    ValidationResult,
    VerificationCheck,
)
from app.domain.policy import BUSINESS_TYPES, CATEGORIES, DOC_TYPES
from app.domain.states import LABELS, S
from app.services.applications import extraction_value, public_fields
from app.services.dedupe import open_duplicates

AUTOFILL_MAP = [  # (slot, extracted field, form key)
    ("PAN_CARD", "pan_number", "pan"),
    ("PAN_CARD", "name", "legal_name"),
    ("GST_CERTIFICATE", "gstin", "gstin"),
    ("GST_CERTIFICATE", "legal_name", "legal_name"),
    ("GST_CERTIFICATE", "trade_name", "trade_name"),
    ("GST_CERTIFICATE", "address", "address"),
    ("GST_CERTIFICATE", "state", "state"),
    ("BANK_PROOF", "account_number", "account_number"),
    ("BANK_PROOF", "ifsc", "ifsc"),
    ("BANK_PROOF", "account_holder_name", "account_holder_name"),
    ("BANK_PROOF", "bank_name", "bank_name"),
    ("INCORPORATION_CERTIFICATE", "cin", "cin"),
    ("INCORPORATION_CERTIFICATE", "company_name", "legal_name"),
    ("PARTNERSHIP_DEED", "firm_name", "legal_name"),
]


def iso(dt):
    return dt.isoformat() if dt else None


def app_summary(app: Application) -> dict:
    form = app.form_data or {}
    return {
        "id": app.id, "reference": app.reference, "status": app.status, "status_label": LABELS[S(app.status)],
        "business_type": app.business_type, "business_type_label": BUSINESS_TYPES.get(app.business_type or "", ""),
        "category": app.category, "category_label": CATEGORIES.get(app.category or "", ""),
        "legal_name": form.get("legal_name"), "trade_name": form.get("trade_name"),
        "risk_score": app.risk_score, "risk_band": app.risk_band, "mid": app.mid,
        "payouts_on_hold": app.payouts_on_hold, "decision": app.decision, "decided_by": app.decided_by,
        "decision_reason": app.decision_reason, "persona": app.persona, "version": app.version,
        "created_at": iso(app.created_at), "updated_at": iso(app.updated_at), "submitted_at": iso(app.submitted_at),
        "status_changed_at": iso(app.status_changed_at), "live_at": iso(app.live_at),
    }


async def latest_extractions(session: AsyncSession, doc_ids: list[str]) -> dict[str, Extraction]:
    if not doc_ids:
        return {}
    rows = (await session.execute(select(Extraction).where(Extraction.document_id.in_(doc_ids))
                                  .order_by(Extraction.created_at))).scalars()
    out = {}
    for e in rows:
        out[e.document_id] = e
    return out


async def documents_view(session: AsyncSession, app_id: str, reveal: bool, include_inactive: bool = False) -> list:
    q = select(Document).where(Document.application_id == app_id)
    if not include_inactive:
        q = q.where(Document.is_active)
    docs = list((await session.execute(q.order_by(Document.uploaded_at))).scalars())
    exts = await latest_extractions(session, [d.id for d in docs])
    out = []
    for d in docs:
        e = exts.get(d.id)
        out.append({
            "id": d.id, "slot": d.slot, "label": DOC_TYPES.get(d.slot, {}).get("label", d.slot), "filename": d.filename,
            "mime": d.mime, "size": d.size, "status": d.status, "quality": d.quality, "detected_type": d.detected_type,
            "is_active": d.is_active, "uploaded_at": iso(d.uploaded_at),
            "extraction": None if e is None else {
                "fields": public_fields(e.fields, reveal), "quality": e.quality, "model": e.model,
                "error": e.error, "latency_ms": e.latency_ms, "prompt_version": e.prompt_version,
            },
        })
    return out


async def autofill(session: AsyncSession, app_id: str) -> dict:
    docs = list((await session.execute(select(Document).where(Document.application_id == app_id,
                                                              Document.is_active))).scalars())
    exts = await latest_extractions(session, [d.id for d in docs])
    by_slot = {d.slot: exts.get(d.id) for d in docs}
    out: dict[str, dict] = {}
    for slot, name, key in AUTOFILL_MAP:
        e = by_slot.get(slot)
        if e is None or e.error:
            continue
        value = extraction_value(e.fields, name)
        conf = (e.fields.get(name) or {}).get("confidence", 0)
        if value and (key not in out or conf > out[key]["confidence"]):
            if key in ("legal_name", "trade_name", "account_holder_name"):
                value = value.title() if value.isupper() else value
            out[key] = {"value": value, "confidence": conf, "source": DOC_TYPES[slot]["label"]}
    return out


async def checks_view(session: AsyncSession, app_id: str, all_attempts: bool = True) -> list:
    q = select(VerificationCheck).where(VerificationCheck.application_id == app_id)
    if not all_attempts:
        q = q.where(VerificationCheck.is_current)
    rows = (await session.execute(q.order_by(VerificationCheck.requested_at))).scalars()
    return [{"id": c.id, "type": c.check_type, "attempt": c.attempt, "status": c.status, "is_current": c.is_current,
             "reason_code": c.reason_code, "result": c.result, "late": c.late, "requested_at": iso(c.requested_at),
             "deadline_at": iso(c.deadline_at), "completed_at": iso(c.completed_at)} for c in rows]


async def info_requests_view(session: AsyncSession, app_id: str) -> list:
    rows = (await session.execute(select(InfoRequest).where(InfoRequest.application_id == app_id)
                                  .order_by(InfoRequest.created_at.desc()))).scalars()
    return [{"id": r.id, "items": r.items, "message": r.message, "status": r.status, "created_by": r.created_by,
             "due_at": iso(r.due_at), "created_at": iso(r.created_at), "responded_at": iso(r.responded_at)}
            for r in rows]


async def merchant_timeline(session: AsyncSession, app_id: str) -> list:
    rows = (await session.execute(select(StateTransition).where(StateTransition.application_id == app_id)
                                  .order_by(StateTransition.created_at))).scalars()
    return [{"at": iso(r.created_at), "to": r.to_status, "label": LABELS[S(r.to_status)]} for r in rows]


async def notifications_view(session: AsyncSession, user_id: str, app_id: str | None = None) -> list:
    q = select(Notification).where(Notification.user_id == user_id)
    if app_id:
        q = q.where(Notification.application_id == app_id)
    rows = (await session.execute(q.order_by(Notification.created_at.desc()).limit(50))).scalars()
    return [{"id": n.id, "application_id": n.application_id, "title": n.title, "body": n.body, "read": n.read,
             "email_status": n.email_status, "created_at": iso(n.created_at)} for n in rows]


async def ops_detail(session: AsyncSession, app: Application) -> dict:
    app_id = app.id
    from app.services.applications import app_data

    validations = (await session.execute(select(ValidationResult).where(ValidationResult.application_id == app_id)
                                         .order_by(ValidationResult.outcome))).scalars()
    callbacks = (await session.execute(select(CallbackEvent).where(CallbackEvent.application_id == app_id)
                                       .order_by(CallbackEvent.received_at))).scalars()
    transitions = (await session.execute(select(StateTransition).where(StateTransition.application_id == app_id)
                                         .order_by(StateTransition.created_at))).scalars()
    audit_rows = (await session.execute(select(AuditLog).where(AuditLog.application_id == app_id)
                                        .order_by(AuditLog.id))).scalars()
    reviews = (await session.execute(select(ReviewTask).where(ReviewTask.application_id == app_id)
                                     .order_by(ReviewTask.created_at.desc()))).scalars()
    decisions = (await session.execute(select(AgentDecision).where(AgentDecision.application_id == app_id)
                                       .order_by(AgentDecision.created_at))).scalars()
    exceptions = (await session.execute(select(OpsException).where(OpsException.application_id == app_id)
                                        .order_by(OpsException.created_at.desc()))).scalars()
    return {
        "application": app_summary(app),
        "data": await app_data(session, app, reveal=False),
        "risk": {"score": app.risk_score, "band": app.risk_band, "signals": app.risk_signals,
                 "explanation": app.risk_explanation},
        "documents": await documents_view(session, app_id, reveal=False, include_inactive=True),
        "validations": [{"rule": v.rule, "outcome": v.outcome, "blocking": v.blocking, "field": v.field,
                         "slot": v.document_slot, "message": v.message} for v in validations],
        "checks": await checks_view(session, app_id),
        "callbacks": [{"provider": c.provider, "event_id": c.event_id, "outcome": c.outcome,
                       "status": c.reported_status, "duplicates": c.duplicate_count, "received_at": iso(c.received_at)}
                      for c in callbacks],
        "transitions": [{"from": t.from_status, "to": t.to_status, "actor": t.actor, "reason": t.reason,
                         "at": iso(t.created_at)} for t in transitions],
        "audit": [{"id": a.id, "actor": a.actor, "action": a.action, "details": a.details, "at": iso(a.created_at),
                   "hash": a.hash[:12]} for a in audit_rows],
        "reviews": [{"id": r.id, "kind": r.kind, "status": r.status, "summary": r.summary,
                     "reason_codes": r.reason_codes, "recommendation": r.recommendation, "priority": r.priority,
                     "decision": r.decision, "decision_note": r.decision_note, "assignee": r.assignee,
                     "created_at": iso(r.created_at), "resolved_at": iso(r.resolved_at)} for r in reviews],
        "decisions": [{"action": d.action, "reasoning": d.reasoning, "model": d.model, "used_fallback": d.used_fallback,
                       "rules_action": d.rules_action, "guardrail": d.guardrail, "args": d.args,
                       "at": iso(d.created_at)} for d in decisions],
        "duplicates": await open_duplicates(session, app_id),
        "info_requests": await info_requests_view(session, app_id),
        "exceptions": [{"id": e.id, "kind": e.kind, "severity": e.severity, "message": e.message, "status": e.status,
                        "created_at": iso(e.created_at)} for e in exceptions],
    }
