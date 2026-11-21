"""The onboarding workflow as a LangGraph state graph.

One graph thread per application (thread_id = application_id), checkpointed in Postgres, so the workflow survives
restarts. Every wait (provider callbacks, merchant replies, human review, ops retry, post-live events) is an
`interrupt()`; the job worker resumes the thread with `Command(resume=...)` when the matching event arrives.

Nodes never write Application.status directly; they go through domain.states.transition()."""

import asyncio
from datetime import timedelta
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from sqlalchemy import update

from app.core.config import get_settings
from app.db.models import AgentDecision, Application, InfoRequest, OpsException, ReviewTask, utcnow
from app.db.session import session_scope
from app.domain.policy import get_active_policy, required_checks
from app.domain.states import CHECK_IN_FLIGHT, C, S, transition
from app.jobs.queue import enqueue
from app.services import checks as checks_svc
from app.services import providers
from app.services.applications import active_documents, latest_extraction
from app.services.audit import audit
from app.services.dedupe import find_duplicates
from app.services.documents import ensure_extracted
from app.services.notifications import notify
from app.services.validation import info_items_from_issues, validate_application
from app.workflow import agent
from app.workflow.facts import gather_facts
from app.workflow.narratives import merchant_message, review_summary, risk_explanation


class WF(TypedDict, total=False):
    application_id: str
    route: str
    info_items: list
    info_message: str | None
    info_by: str
    force_checks: list
    decision: dict
    approver: str
    review: dict
    bank_changed: bool


async def _load(s, state) -> Application:
    return await s.get(Application, state["application_id"])


# ------------------------------------------------------------------ documents ------------------------------------
async def extract(state: WF) -> WF:
    app_id = state["application_id"]
    async with session_scope() as s:
        app = await _load(s, state)
        if app.status in (S.SUBMITTED, S.AWAITING_MERCHANT):
            await transition(s, app, S.PROCESSING_DOCUMENTS, "system", "Reading and validating documents")
        pending = [d.id for d in await active_documents(s, app_id) if await latest_extraction(s, d.id) is None]
    # All unread documents in parallel, each in its own short transaction (LLM calls are slow). Documents already
    # being read by a background job are waited for, not read twice.
    await asyncio.gather(*(ensure_extracted(doc_id) for doc_id in pending))
    return {"route": ""}


async def validate(state: WF) -> WF:
    async with session_scope() as s:
        app = await _load(s, state)
        _, policy = await get_active_policy(s)
        report = await validate_application(s, app, policy)
        await audit(s, app.id, "system", "validation_completed",
                    {"blocking": [i.rule for i in report.blocking], "flags": [i.rule for i in report.flags]})
        if report.blocking:
            return {"route": "request_info", "info_items": info_items_from_issues(report.blocking),
                    "info_message": None, "info_by": "system:validation"}
    return {"route": "dedupe"}


async def dedupe(state: WF) -> WF:
    async with session_scope() as s:
        app = await _load(s, state)
        matches = await find_duplicates(s, app)
        await audit(s, app.id, "system", "duplicate_check_completed",
                    {"matches": [{"on": m.matched_on, "score": m.score} for m in matches]})
    return {"route": ""}


# ------------------------------------------------------------------ verification ---------------------------------
async def dispatch(state: WF) -> WF:
    async with session_scope() as s:
        app = await _load(s, state)
        _, policy = await get_active_policy(s)
        if app.status in (S.PROCESSING_DOCUMENTS, S.DECISIONING, S.MANUAL_REVIEW):
            await transition(s, app, S.VERIFYING, "system", "Running verification checks")
        required = required_checks(policy, app.business_type)
        timeout = int(policy.get("check_timeout_seconds", 45))
        post_live = app.status == S.LIVE
    await checks_svc.dispatch(state["application_id"], required, state.get("force_checks") or [], timeout,
                              bank_changed_after_approval=bool(post_live and state.get("bank_changed")))
    return {"force_checks": [], "route": ""}


async def await_checks(state: WF) -> WF:
    async with session_scope() as s:
        app = await _load(s, state)
        _, policy = await get_active_policy(s)
        required = required_checks(policy, app.business_type)
        cur = await checks_svc.current_checks(s, app.id)
        status = app.status
    missing = [t for t in required if t not in cur or cur[t].status == C.INVALIDATED]
    in_flight = [t for t in required if t in cur and cur[t].status in CHECK_IN_FLIGHT]
    if missing:
        return {"route": "dispatch"}
    if in_flight:
        interrupt({"wait": "checks", "pending": in_flight})
        return {"route": "recheck"}
    return {"route": "post_live" if status == S.LIVE else "decide"}


# ------------------------------------------------------------------ decision -------------------------------------
async def decide(state: WF) -> WF:
    async with session_scope() as s:
        app = await _load(s, state)
        version, policy = await get_active_policy(s)
        if app.status == S.VERIFYING:
            await transition(s, app, S.DECISIONING, "system", "All checks complete")
        app.policy_version = version
        facts = await gather_facts(s, app, policy)
        needs_explanation = app.risk_score is not None and not app.risk_explanation
        risk = (app.risk_score, app.risk_band, list(app.risk_signals or []))
    explanation = await risk_explanation(*risk) if needs_explanation else None
    d = await agent.decide(facts, policy, version)
    async with session_scope() as s:
        app = await _load(s, state)
        if explanation:
            app.risk_explanation = explanation
        s.add(AgentDecision(application_id=app.id, action=d["action"], args=d.get("args", {}), reasoning=d.get("reason", ""),
                            model=d["model"], used_fallback=d["used_fallback"], guardrail=d.get("guardrail", {}),
                            rules_action=d.get("rules_action")))
        await audit(s, app.id, "agent" if not d["used_fallback"] else "rules-engine", "decision_made",
                    {"action": d["action"], "reason": d.get("reason"), "model": d["model"],
                     "rules_engine_would": d.get("rules_action"), "policy_version": version})
    out: WF = {"decision": d, "route": d["action"]}
    if d["action"] == "request_info":
        out |= {"info_items": d["args"]["items"], "info_message": d["args"].get("message"), "info_by": "agent"}
    if d["action"] == "retry_check":
        out |= {"force_checks": d["args"]["checks"]}
    if d["action"] == "approve":
        out |= {"approver": "agent" if not d["used_fallback"] else "rules-engine"}
    return out


async def approve(state: WF) -> WF:
    async with session_scope() as s:
        app = await _load(s, state)
        approver = state.get("approver") or "agent"
        app.decision = "approved"
        app.decided_by = approver
        reason = (state.get("review") or {}).get("note") or (state.get("decision") or {}).get("reason") or ""
        app.decision_reason = reason
        await transition(s, app, S.APPROVED, approver, reason or "Approved")
        await notify(s, app.merchant_user_id, app.id, "Your application is approved",
                     "Great news! Your business passed verification. We're now creating your merchant ID.")
    return {"route": ""}


async def reject(state: WF) -> WF:
    review = state.get("review") or {}
    async with session_scope() as s:
        app = await _load(s, state)
        app.decision = "rejected"
        app.decided_by = review.get("actor", "operator")
        app.decision_reason = review.get("note", "")
        await transition(s, app, S.REJECTED, app.decided_by, review.get("note", "Rejected by reviewer"))
        await notify(s, app.merchant_user_id, app.id, "Update on your application",
                     "We're unable to approve your application at this time.\n"
                     f"Reason: {review.get('note') or 'did not meet onboarding requirements'}\n"
                     "You can reply from your dashboard if you believe this is a mistake.")
    return {"route": ""}


# ------------------------------------------------------------------ merchant loop --------------------------------
async def request_info(state: WF) -> WF:
    items = state.get("info_items") or []
    async with session_scope() as s:
        app = await _load(s, state)
        name = (app.form_data or {}).get("trade_name") or (app.form_data or {}).get("legal_name")
    message = state.get("info_message") or await merchant_message(items, name)
    async with session_scope() as s:
        app = await _load(s, state)
        _, policy = await get_active_policy(s)
        await s.execute(update(InfoRequest).where(InfoRequest.application_id == app.id, InfoRequest.status == "open")
                        .values(status="superseded"))
        due = utcnow() + timedelta(days=int(policy.get("info_request_expiry_days", 7)))
        ir = InfoRequest(application_id=app.id, items=items, message=message,
                         created_by=state.get("info_by", "system"), due_at=due)
        s.add(ir)
        await s.flush()
        await transition(s, app, S.AWAITING_MERCHANT, state.get("info_by", "system"),
                         "Waiting for merchant: " + ", ".join(i.get("label", "") for i in items))
        await notify(s, app.merchant_user_id, app.id, "Action needed on your application", message)
        await enqueue(s, "info_request_expiry", {"info_request_id": ir.id}, application_id=app.id, run_at=due,
                      dedupe_key=f"expire:{ir.id}")
    return {"route": ""}


async def wait_merchant(state: WF) -> WF:
    v = interrupt({"wait": "merchant"})
    return {"route": "expired" if (v or {}).get("kind") == "expired" else "responded"}


async def withdraw(state: WF) -> WF:
    async with session_scope() as s:
        app = await _load(s, state)
        await transition(s, app, S.WITHDRAWN, "system", "No response from merchant before the deadline")
        await notify(s, app.merchant_user_id, app.id, "Application closed",
                     "We closed your application because we didn't hear back. You can start a new one any time.")
    return {"route": ""}


# ------------------------------------------------------------------ human review ---------------------------------
async def open_review(state: WF) -> WF:
    d = state.get("decision") or {}
    args = d.get("args") or {}
    reasons = [r for r in (args.get("reason_codes") or [d.get("reason")]) if r]
    recommendation = args.get("recommendation", "review")
    async with session_scope() as s:
        app = await _load(s, state)
        _, policy = await get_active_policy(s)
        facts = await gather_facts(s, app, policy)
    summary = await review_summary(facts, reasons, recommendation)
    async with session_scope() as s:
        app = await _load(s, state)
        await s.execute(update(ReviewTask).where(ReviewTask.application_id == app.id, ReviewTask.status == "open",
                                                 ReviewTask.kind == "pre_approval").values(status="superseded"))
        s.add(ReviewTask(application_id=app.id, kind="pre_approval", reason_codes=reasons, summary=summary,
                         recommendation=recommendation, priority=args.get("priority", "normal")))
        await transition(s, app, S.MANUAL_REVIEW, "agent", "; ".join(reasons)[:500] or "Needs human review")
        await notify(s, app.merchant_user_id, app.id, "Your application is being reviewed",
                     "A member of our onboarding team is reviewing your application. You can expect a decision within "
                     f"{get_settings().review_sla_hours} hours. No action is needed right now.")
    return {"route": ""}


async def await_review(state: WF) -> WF:
    v = interrupt({"wait": "review"}) or {}
    kind = v.get("kind")
    if kind == "inputs_changed":
        return {"route": "dispatch", "review": v}
    decision = v.get("decision")
    out: WF = {"review": v, "route": decision}
    if decision == "approve":
        out["approver"] = v.get("actor", "operator")
    if decision == "request_info":
        out |= {"info_items": v.get("items", []), "info_message": v.get("message"), "info_by": v.get("actor")}
    if decision == "retry_check":
        out |= {"force_checks": v.get("checks", [])}
    return out


# ------------------------------------------------------------------ activation -----------------------------------
async def provision(state: WF) -> WF:
    app_id = state["application_id"]
    async with session_scope() as s:
        app = await _load(s, state)
        _, policy = await get_active_policy(s)
        await transition(s, app, S.PROVISIONING, "system", "Creating merchant ID")
        data = {"reference": app.reference, "legal_name": (app.form_data or {}).get("legal_name"),
                "trade_name": (app.form_data or {}).get("trade_name"), "category": app.category,
                "business_type": app.business_type}
    max_attempts = int(policy.get("mid_max_attempts", 3))
    mid, errors = None, []
    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            await asyncio.sleep(min(2 ** (attempt - 1), 8))
            existing = await providers.get_mid(app_id)  # never create twice: check status before retrying
            if existing:
                mid = existing["mid"]
                break
        try:
            mid = (await providers.create_mid(app_id, data))["mid"]
            break
        except providers.ProviderUnavailable as exc:
            errors.append(str(exc))
            async with session_scope() as s:
                await audit(s, app_id, "system", "mid_attempt_failed", {"attempt": attempt, "error": str(exc)})
    async with session_scope() as s:
        app = await _load(s, state)
        if mid:
            app.mid = mid
            app.payouts_on_hold = False
            await transition(s, app, S.LIVE, "system", "Merchant ID created")
            await s.execute(update(OpsException).where(OpsException.application_id == app_id,
                                                       OpsException.kind == "mid_creation_failed",
                                                       OpsException.status == "open")
                            .values(status="resolved", resolved_at=utcnow()))
            await notify(s, app.merchant_user_id, app.id, "You're live on MapleLaunch",
                         f"Your merchant ID is {mid}. You can start accepting payments.")
            return {"route": "live"}
        await transition(s, app, S.PROVISIONING_FAILED, "system", f"MID creation failed after {max_attempts} attempts")
        s.add(OpsException(application_id=app_id, kind="mid_creation_failed", severity="high",
                           message=f"Merchant ID creation failed {max_attempts}x: {errors[-1] if errors else ''}"))
        await notify(s, app.merchant_user_id, app.id, "Approved: merchant ID on its way",
                     "Your application is approved. Creating your merchant ID is taking longer than usual; "
                     "our team is on it and you don't need to do anything.")
    return {"route": "failed"}


async def await_ops(state: WF) -> WF:
    interrupt({"wait": "ops"})
    return {"route": ""}


# ------------------------------------------------------------------ after go-live --------------------------------
async def monitor(state: WF) -> WF:
    v = interrupt({"wait": "post_live"}) or {}
    if v.get("kind") == "bank_changed":
        return {"route": "dispatch", "bank_changed": True}
    return {"route": "monitor"}


async def post_live_review(state: WF) -> WF:
    async with session_scope() as s:
        app = await _load(s, state)
        cur = await checks_svc.current_checks(s, app.id)
        bank = cur.get("BANK")
        if bank is not None and bank.status == C.PASSED and app.risk_band != "HIGH":
            app.payouts_on_hold = False
            await audit(s, app.id, "system", "payouts_released", {"reason": "New bank account verified"})
            await notify(s, app.merchant_user_id, app.id, "New bank account verified",
                         "Your new bank account is verified and payouts have resumed.")
        else:
            reasons = []
            if bank is None or bank.status != C.PASSED:
                reasons.append(f"New bank account verification {bank.status if bank else 'missing'}"
                               f"{' (' + bank.reason_code + ')' if bank and bank.reason_code else ''}")
            if app.risk_band == "HIGH":
                reasons.append(f"Risk score rose to {app.risk_score} after the bank change")
            s.add(ReviewTask(application_id=app.id, kind="post_live", reason_codes=reasons, recommendation="review",
                             priority="high", summary="Bank details changed after go-live.\n" +
                             "\n".join(f"• {r}" for r in reasons) + "\nPayouts remain on hold until resolved."))
            s.add(OpsException(application_id=app.id, kind="post_live_bank_change", severity="high",
                               message="; ".join(reasons)))
            await audit(s, app.id, "system", "post_live_review_opened", {"reasons": reasons})
    return {"route": "", "bank_changed": False}


# ------------------------------------------------------------------ wiring ---------------------------------------
def build_graph() -> StateGraph:
    g = StateGraph(WF)
    for name, fn in [("extract", extract), ("validate", validate), ("dedupe", dedupe), ("dispatch", dispatch),
                     ("await_checks", await_checks), ("decide", decide), ("approve", approve), ("reject", reject),
                     ("request_info", request_info), ("wait_merchant", wait_merchant), ("withdraw", withdraw),
                     ("open_review", open_review), ("await_review", await_review), ("provision", provision),
                     ("await_ops", await_ops), ("monitor", monitor), ("post_live_review", post_live_review)]:
        g.add_node(name, fn)
    route = lambda s: s.get("route", "")  # noqa: E731

    g.add_edge(START, "extract")
    g.add_edge("extract", "validate")
    g.add_conditional_edges("validate", route, {"request_info": "request_info", "dedupe": "dedupe"})
    g.add_edge("dedupe", "dispatch")
    g.add_edge("dispatch", "await_checks")
    g.add_conditional_edges("await_checks", route, {"dispatch": "dispatch", "recheck": "await_checks",
                                                    "decide": "decide", "post_live": "post_live_review"})
    g.add_conditional_edges("decide", route, {"approve": "approve", "request_info": "request_info",
                                              "retry_check": "dispatch", "escalate": "open_review"})
    g.add_edge("request_info", "wait_merchant")
    g.add_conditional_edges("wait_merchant", route, {"responded": "extract", "expired": "withdraw"})
    g.add_edge("withdraw", END)
    g.add_edge("open_review", "await_review")
    g.add_conditional_edges("await_review", route, {"approve": "approve", "reject": "reject",
                                                    "request_info": "request_info", "retry_check": "dispatch",
                                                    "dispatch": "dispatch"})
    g.add_edge("reject", END)
    g.add_edge("approve", "provision")
    g.add_conditional_edges("provision", route, {"live": "monitor", "failed": "await_ops"})
    g.add_edge("await_ops", "provision")
    g.add_conditional_edges("monitor", route, {"dispatch": "dispatch", "monitor": "monitor"})
    g.add_edge("post_live_review", "monitor")
    return g
