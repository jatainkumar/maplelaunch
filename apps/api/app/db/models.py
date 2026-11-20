"""Relational model. Postgres is the source of truth for application state; LangGraph checkpoints
(separate tables managed by langgraph-checkpoint-postgres) record where each workflow is paused."""

import uuid
from datetime import datetime, UTC

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


TS = DateTime(timezone=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(20), default="merchant")  # merchant | operator | admin
    password_hash: Mapped[str | None] = mapped_column(String(255))  # local auth mode only
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Application(Base):
    __tablename__ = "applications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    reference: Mapped[str] = mapped_column(String(20), unique=True)
    merchant_user_id: Mapped[str] = mapped_column(String(64), index=True)
    business_type: Mapped[str | None] = mapped_column(String(30))
    category: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    form_data: Mapped[dict] = mapped_column(JSONType, default=dict)  # non-sensitive fields only
    risk_score: Mapped[int | None] = mapped_column(Integer)
    risk_band: Mapped[str | None] = mapped_column(String(10))
    risk_signals: Mapped[list] = mapped_column(JSONType, default=list)
    risk_explanation: Mapped[str | None] = mapped_column(Text)
    decision: Mapped[str | None] = mapped_column(String(20))
    decided_by: Mapped[str | None] = mapped_column(String(120))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    mid: Mapped[str | None] = mapped_column(String(40))
    payouts_on_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    persona: Mapped[str | None] = mapped_column(String(40))
    policy_version: Mapped[int | None] = mapped_column(Integer)
    submitted_at: Mapped[datetime | None] = mapped_column(TS)
    decided_at: Mapped[datetime | None] = mapped_column(TS)
    live_at: Mapped[datetime | None] = mapped_column(TS)
    status_changed_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)

    # Optimistic locking: concurrent writers (two operators, callback vs operator) raise StaleDataError.
    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012


class ApplicationPII(Base):
    """Encrypted identifiers + blind indexes (HMAC) used for duplicate detection."""

    __tablename__ = "application_pii"
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True)
    pan_enc: Mapped[str | None] = mapped_column(Text)
    gstin_enc: Mapped[str | None] = mapped_column(Text)
    account_number_enc: Mapped[str | None] = mapped_column(Text)
    phone_enc: Mapped[str | None] = mapped_column(Text)
    email_enc: Mapped[str | None] = mapped_column(Text)
    cin_enc: Mapped[str | None] = mapped_column(Text)
    pan_bi: Mapped[str | None] = mapped_column(String(64), index=True)
    gstin_bi: Mapped[str | None] = mapped_column(String(64), index=True)
    account_bi: Mapped[str | None] = mapped_column(String(64), index=True)
    phone_bi: Mapped[str | None] = mapped_column(String(64), index=True)
    email_bi: Mapped[str | None] = mapped_column(String(64), index=True)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    slot: Mapped[str] = mapped_column(String(40))  # PAN_CARD | GST_CERTIFICATE | BANK_PROOF | ...
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="uploaded")  # uploaded|extracted|failed
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    quality: Mapped[float | None] = mapped_column(Float)
    detected_type: Mapped[str | None] = mapped_column(String(40))
    uploaded_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Extraction(Base):
    __tablename__ = "extractions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[str] = mapped_column(String(36), index=True)
    fields: Mapped[dict] = mapped_column(JSONType, default=dict)  # {name: {value|value_enc, masked, confidence}}
    quality: Mapped[dict] = mapped_column(JSONType, default=dict)
    detected_type: Mapped[str | None] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class ValidationResult(Base):
    __tablename__ = "validation_results"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(String(36), index=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    rule: Mapped[str] = mapped_column(String(60))
    outcome: Mapped[str] = mapped_column(String(10))  # pass | warn | fail
    blocking: Mapped[bool] = mapped_column(Boolean, default=False)
    field: Mapped[str | None] = mapped_column(String(60))
    document_slot: Mapped[str | None] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class VerificationCheck(Base):
    __tablename__ = "verification_checks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)  # == request_id
    application_id: Mapped[str] = mapped_column(String(36), index=True)
    check_type: Mapped[str] = mapped_column(String(10))  # PAN | GST | BANK | RISK
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="REQUESTED")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    provider_ref: Mapped[str | None] = mapped_column(String(64))
    input_hash: Mapped[str | None] = mapped_column(String(64))
    reason_code: Mapped[str | None] = mapped_column(String(60))
    result: Mapped[dict] = mapped_column(JSONType, default=dict)
    late: Mapped[bool] = mapped_column(Boolean, default=False)
    requested_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    deadline_at: Mapped[datetime | None] = mapped_column(TS)
    completed_at: Mapped[datetime | None] = mapped_column(TS)

    __table_args__ = (Index("ix_checks_app_type_current", "application_id", "check_type", "is_current"),)


class CallbackEvent(Base):
    __tablename__ = "callback_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(10))
    event_id: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(36), index=True)
    application_id: Mapped[str | None] = mapped_column(String(36), index=True)
    outcome: Mapped[str] = mapped_column(String(30))
    reported_status: Mapped[str | None] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)  # PII-redacted
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    received_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_callback_provider_event"),)


class StateTransition(Base):
    __tablename__ = "state_transitions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(String(36), index=True)
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    actor: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class AuditLog(Base):
    """Append-only, hash-chained per application (tamper-evident)."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    application_id: Mapped[str | None] = mapped_column(String(36), index=True)
    actor: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(60))
    details: Mapped[dict] = mapped_column(JSONType, default=dict)
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class ReviewTask(Base):
    __tablename__ = "review_tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="pre_approval")  # pre_approval | post_live
    reason_codes: Mapped[list] = mapped_column(JSONType, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    recommendation: Mapped[str] = mapped_column(String(20), default="review")  # approve | reject | review
    priority: Mapped[str] = mapped_column(String(10), default="normal")  # high | normal
    status: Mapped[str] = mapped_column(String(10), default="open")
    assignee: Mapped[str | None] = mapped_column(String(255))
    decision: Mapped[str | None] = mapped_column(String(20))
    decision_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(TS)


class InfoRequest(Base):
    __tablename__ = "info_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(String(36), index=True)
    items: Mapped[list] = mapped_column(JSONType, default=list)  # [{kind, key, label, reason}]
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="open")  # open|responded|expired
    created_by: Mapped[str] = mapped_column(String(120))
    due_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    responded_at: Mapped[datetime | None] = mapped_column(TS)


class DuplicateMatch(Base):
    __tablename__ = "duplicate_matches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(String(36), index=True)
    matched_application_id: Mapped[str] = mapped_column(String(36))
    matched_on: Mapped[list] = mapped_column(JSONType, default=list)
    score: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12), default="open")  # open | cleared | confirmed
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    application_id: Mapped[str | None] = mapped_column(String(36))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    email_status: Mapped[str] = mapped_column(String(12), default="skipped")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class Policy(Base):
    __tablename__ = "policies"
    version: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    data: Mapped[dict] = mapped_column(JSONType)
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class AgentDecision(Base):
    __tablename__ = "agent_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(30))
    args: Mapped[dict] = mapped_column(JSONType, default=dict)
    reasoning: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(80))
    used_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    guardrail: Mapped[dict] = mapped_column(JSONType, default=dict)
    rules_action: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class OpsException(Base):
    __tablename__ = "ops_exceptions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str | None] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10), default="medium")
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="open")
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(TS)


class Job(Base):
    """Durable background work and timers (Postgres queue, SKIP LOCKED)."""

    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    application_id: Mapped[str | None] = mapped_column(String(36), index=True)
    run_at: Mapped[datetime] = mapped_column(TS, default=utcnow, index=True)
    status: Mapped[str] = mapped_column(String(10), default="queued", index=True)  # queued|running|done|dead
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    last_error: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str | None] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)
