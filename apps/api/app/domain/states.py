"""Explicit application state machine. This module is the ONLY place that changes Application.status."""

from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Application, StateTransition, utcnow
from app.services.audit import audit


class S(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PROCESSING_DOCUMENTS = "PROCESSING_DOCUMENTS"
    AWAITING_MERCHANT = "AWAITING_MERCHANT"
    VERIFYING = "VERIFYING"
    DECISIONING = "DECISIONING"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    APPROVED = "APPROVED"
    PROVISIONING = "PROVISIONING"
    PROVISIONING_FAILED = "PROVISIONING_FAILED"
    LIVE = "LIVE"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


TRANSITIONS: dict[S, set[S]] = {
    S.DRAFT: {S.SUBMITTED, S.WITHDRAWN},
    S.SUBMITTED: {S.PROCESSING_DOCUMENTS, S.WITHDRAWN},
    S.PROCESSING_DOCUMENTS: {S.AWAITING_MERCHANT, S.VERIFYING, S.WITHDRAWN},
    S.AWAITING_MERCHANT: {S.PROCESSING_DOCUMENTS, S.WITHDRAWN},
    S.VERIFYING: {S.DECISIONING, S.AWAITING_MERCHANT, S.WITHDRAWN},
    S.DECISIONING: {S.APPROVED, S.MANUAL_REVIEW, S.AWAITING_MERCHANT, S.VERIFYING, S.WITHDRAWN},
    S.MANUAL_REVIEW: {S.APPROVED, S.REJECTED, S.AWAITING_MERCHANT, S.VERIFYING, S.WITHDRAWN},
    S.APPROVED: {S.PROVISIONING},
    S.PROVISIONING: {S.LIVE, S.PROVISIONING_FAILED},
    S.PROVISIONING_FAILED: {S.PROVISIONING},
    S.LIVE: set(),
    S.REJECTED: set(),
    S.WITHDRAWN: set(),
}

TERMINAL = {S.REJECTED, S.WITHDRAWN}

# A merchant may withdraw any time before approval. Once approved, the merchant ID is being or has been issued.
MERCHANT_WITHDRAWABLE = {S.DRAFT, S.SUBMITTED, S.PROCESSING_DOCUMENTS, S.AWAITING_MERCHANT, S.VERIFYING,
                         S.DECISIONING, S.MANUAL_REVIEW}

# States where the merchant may edit bank details through a change request.
BANK_CHANGE_ALLOWED = {S.AWAITING_MERCHANT, S.VERIFYING, S.MANUAL_REVIEW, S.LIVE}

# Human-friendly labels used by UI and notifications.
LABELS = {
    S.DRAFT: "Draft",
    S.SUBMITTED: "Submitted",
    S.PROCESSING_DOCUMENTS: "Reading documents",
    S.AWAITING_MERCHANT: "Action needed",
    S.VERIFYING: "Verifying",
    S.DECISIONING: "Deciding",
    S.MANUAL_REVIEW: "Under review",
    S.APPROVED: "Approved",
    S.PROVISIONING: "Creating merchant ID",
    S.PROVISIONING_FAILED: "Merchant ID delayed",
    S.LIVE: "Live",
    S.REJECTED: "Rejected",
    S.WITHDRAWN: "Withdrawn",
}


class IllegalTransition(Exception):
    def __init__(self, current: str, target: str):
        super().__init__(f"Illegal transition {current} -> {target}")
        self.current, self.target = current, target


def can_transition(current: str, target: str) -> bool:
    return S(target) in TRANSITIONS[S(current)]


async def transition(session: AsyncSession, app: Application, target: S, actor: str, reason: str = "") -> bool:
    """Move the application to `target`. Idempotent (no-op if already there); raises on illegal moves."""
    current = S(app.status)
    if current == target:
        return False
    if target not in TRANSITIONS[current]:
        raise IllegalTransition(current, target)
    now = utcnow()
    app.status = target.value
    app.status_changed_at = now
    if target == S.SUBMITTED:
        app.submitted_at = now
    if target in (S.APPROVED, S.REJECTED):
        app.decided_at = now
    if target == S.LIVE:
        app.live_at = now
    session.add(StateTransition(application_id=app.id, from_status=current.value, to_status=target.value,
                                actor=actor, reason=reason))
    await audit(session, app.id, actor, "state_changed", {"from": current.value, "to": target.value, "reason": reason})
    await session.flush()
    return True


class C(StrEnum):
    """Per-check status. Within one attempt the status only moves forward."""

    REQUESTED = "REQUESTED"
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    ERROR = "ERROR"
    INVALIDATED = "INVALIDATED"


CHECK_RANK = {C.REQUESTED: 0, C.PENDING: 1, C.PASSED: 2, C.FAILED: 2, C.TIMED_OUT: 2, C.ERROR: 2, C.INVALIDATED: 3}
CHECK_TERMINAL = {C.PASSED, C.FAILED, C.TIMED_OUT, C.ERROR}
CHECK_IN_FLIGHT = {C.REQUESTED, C.PENDING}
CHECK_TYPES = ("PAN", "GST", "BANK", "RISK")
