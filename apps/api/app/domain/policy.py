"""Approval policy (versioned, editable by admins) and the guardrail that gates automatic approval."""

import copy
from dataclasses import dataclass, field

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Policy

BUSINESS_TYPES = {
    "proprietorship": "Sole proprietorship",
    "partnership": "Partnership firm",
    "private_limited": "Private limited company",
}

CATEGORIES = {
    "retail": "Retail & general store",
    "food_beverage": "Food & beverage",
    "apparel": "Apparel & textiles",
    "electronics": "Electronics",
    "services": "Professional services",
    "education": "Education",
    "healthcare": "Healthcare & pharmacy",
    "travel": "Travel & hospitality",
    "software": "Software & SaaS",
    "jewellery": "Jewellery & bullion",
    "gaming": "Online gaming",
    "crypto": "Crypto & virtual assets",
}

DOC_TYPES = {
    "PAN_CARD": {
        "label": "PAN card",
        "hint": "PAN of the proprietor (individual), firm or company",
        "fields": ["pan_number", "name", "date_of_birth"],
    },
    "GST_CERTIFICATE": {
        "label": "GST registration certificate",
        "hint": "Form GST REG-06",
        "fields": ["gstin", "legal_name", "trade_name", "constitution", "registration_date", "address", "state"],
    },
    "BANK_PROOF": {
        "label": "Cancelled cheque or bank statement",
        "hint": "Must show account number, IFSC and account holder name",
        "fields": ["account_number", "ifsc", "account_holder_name", "bank_name"],
    },
    "INCORPORATION_CERTIFICATE": {
        "label": "Certificate of incorporation",
        "hint": "Issued by the Registrar of Companies",
        "fields": ["cin", "company_name", "incorporation_date"],
    },
    "PARTNERSHIP_DEED": {
        "label": "Partnership deed",
        "hint": "Signed deed listing all partners",
        "fields": ["firm_name", "partners", "execution_date"],
    },
}

# Extracted field name -> masking kind. These values are encrypted at rest.
SENSITIVE_FIELDS = {"pan_number": "pan", "gstin": "gstin", "account_number": "account_number", "cin": "cin"}

DEFAULT_POLICY: dict = {
    "business_types": {
        "proprietorship": {
            "required_documents": ["PAN_CARD", "GST_CERTIFICATE", "BANK_PROOF"],
            "required_checks": ["PAN", "GST", "BANK", "RISK"],
            "pan_holder_type": "P",
        },
        "partnership": {
            "required_documents": ["PAN_CARD", "PARTNERSHIP_DEED", "GST_CERTIFICATE", "BANK_PROOF"],
            "required_checks": ["PAN", "GST", "BANK", "RISK"],
            "pan_holder_type": "F",
        },
        "private_limited": {
            "required_documents": ["PAN_CARD", "INCORPORATION_CERTIFICATE", "GST_CERTIFICATE", "BANK_PROOF"],
            "required_checks": ["PAN", "GST", "BANK", "RISK"],
            "pan_holder_type": "C",
        },
    },
    "thresholds": {
        "min_extraction_confidence": 0.75,
        "min_document_quality": 0.6,
        "name_match_min": 85,
        "auto_approve_max_risk": 30,
    },
    "high_risk_categories": ["gaming", "crypto", "jewellery"],
    "auto_approve_enabled": True,
    "check_timeout_seconds": 45,
    "max_check_retries": 2,
    "mid_max_attempts": 3,
    "info_request_expiry_days": 7,
}


async def get_active_policy(session: AsyncSession) -> tuple[int, dict]:
    row = (await session.execute(select(Policy).where(Policy.is_active).order_by(Policy.version.desc()))).scalars().first()
    if row is None:
        row = Policy(data=copy.deepcopy(DEFAULT_POLICY), note="Initial default policy", created_by="system")
        session.add(row)
        await session.flush()
    return row.version, row.data


async def save_policy(session: AsyncSession, data: dict, note: str, actor: str) -> Policy:
    await session.execute(update(Policy).values(is_active=False))
    row = Policy(data=data, note=note, created_by=actor, is_active=True)
    session.add(row)
    await session.flush()
    return row


def business_rules(policy: dict, business_type: str | None) -> dict:
    return policy["business_types"].get(business_type or "", policy["business_types"]["proprietorship"])


def required_checks(policy: dict, business_type: str | None) -> list[str]:
    return list(business_rules(policy, business_type)["required_checks"])


def required_documents(policy: dict, business_type: str | None) -> list[str]:
    return list(business_rules(policy, business_type)["required_documents"])


# ---------------------------------------------------------------------------------------------
# Guardrail: the AI agent may only approve when this returns ok=True.
# ---------------------------------------------------------------------------------------------


@dataclass
class Facts:
    business_type: str
    category: str | None
    required_checks: list[str]
    checks: dict[str, dict]  # type -> {status, reason_code, attempt, result}
    risk_score: int | None
    risk_band: str | None
    min_confidence: float | None
    low_confidence_fields: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    open_duplicates: list[dict] = field(default_factory=list)
    extraction_failures: list[str] = field(default_factory=list)


def can_auto_approve(facts: Facts, policy: dict) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    t = policy["thresholds"]
    if not policy.get("auto_approve_enabled", True):
        reasons.append("Automatic approval is disabled by policy")
    for check in facts.required_checks:
        status = facts.checks.get(check, {}).get("status")
        if status != "PASSED":
            reasons.append(f"{check} check is {status or 'missing'}")
    if facts.risk_score is None:
        reasons.append("No risk score")
    elif facts.risk_score > t["auto_approve_max_risk"]:
        reasons.append(f"Risk score {facts.risk_score} above auto-approve limit {t['auto_approve_max_risk']}")
    if facts.category in policy.get("high_risk_categories", []):
        reasons.append(f"Category '{facts.category}' is high-risk")
    if facts.min_confidence is None or facts.min_confidence < t["min_extraction_confidence"]:
        reasons.append("Some extracted fields are below the confidence threshold")
    if facts.conflicts:
        reasons.append("Unresolved conflicts: " + "; ".join(facts.conflicts))
    if facts.open_duplicates:
        reasons.append(f"{len(facts.open_duplicates)} possible duplicate application(s)")
    if facts.extraction_failures:
        reasons.append("Documents could not be read automatically: " + ", ".join(facts.extraction_failures))
    return (not reasons, reasons)


# Check failure reasons the merchant can fix themselves (first occurrence -> request info).
FIXABLE_REASONS = {
    "GST": {"GSTIN_NOT_FOUND", "GSTIN_CANCELLED"},
    "BANK": {"ACCOUNT_INVALID", "ACCOUNT_CLOSED"},
}
# Failures that warrant a "recommend reject" escalation.
CRITICAL_REASONS = {
    "PAN": {"PAN_INVALID", "PAN_DEACTIVATED"},
}

REASON_TEXT = {
    "GSTIN_CANCELLED": "the GST portal shows this GSTIN as cancelled, so please share your active GSTIN",
    "GSTIN_NOT_FOUND": "we couldn't find this GSTIN on the GST portal, so please check it for typos",
    "ACCOUNT_INVALID": "the bank says this account number isn't valid",
    "ACCOUNT_CLOSED": "the bank says this account is closed",
}

INFO_FOR_CHECK = {
    "GST": [
        {"kind": "field", "key": "gstin", "label": "GSTIN"},
        {"kind": "document", "key": "GST_CERTIFICATE", "label": "Current GST registration certificate"},
    ],
    "BANK": [
        {"kind": "field", "key": "bank", "label": "Bank account details"},
        {"kind": "document", "key": "BANK_PROOF", "label": "Cancelled cheque or bank statement"},
    ],
}


def rules_decision(facts: Facts, policy: dict) -> dict:
    """Deterministic decision used as the agent's fallback and as a cross-check of the agent's choice."""
    # 1. Critical failures -> escalate with a reject recommendation (humans make the final call).
    critical = []
    for check, reasons in CRITICAL_REASONS.items():
        c = facts.checks.get(check)
        if c and c["status"] == "FAILED" and c.get("reason_code") in reasons:
            critical.append(f"{check}: {c['reason_code']}")
    for check, reasons in FIXABLE_REASONS.items():
        c = facts.checks.get(check)
        if c and c["status"] == "FAILED" and c.get("reason_code") in reasons and c.get("attempt", 1) > 1:
            critical.append(f"{check}: {c['reason_code']} again after the merchant's correction")
    if any(d.get("matched_status") == "REJECTED" for d in facts.open_duplicates):
        critical.append("Matches a previously rejected merchant")
    if critical:
        return {"action": "escalate", "args": {"reason_codes": critical, "recommendation": "reject", "priority": "high"},
                "reason": "Critical verification failure: " + "; ".join(critical)}

    # 2. Transient problems with retries left -> retry those checks.
    retry = [
        t for t in facts.required_checks
        if facts.checks.get(t, {}).get("status") in ("TIMED_OUT", "ERROR")
        and facts.checks[t].get("attempt", 1) <= policy.get("max_check_retries", 2)
    ]
    if retry:
        return {"action": "retry_check", "args": {"checks": retry}, "reason": f"Transient provider issue on {', '.join(retry)}"}

    # 3. Fixable by the merchant (first failure) -> request specific information.
    items = []
    for check, reasons in FIXABLE_REASONS.items():
        c = facts.checks.get(check)
        if c and c["status"] == "FAILED" and c.get("reason_code") in reasons and c.get("attempt", 1) == 1:
            for item in INFO_FOR_CHECK[check]:
                items.append({**item, "reason": REASON_TEXT.get(c["reason_code"], f"{check} verification failed")})
    if items:
        return {"action": "request_info", "args": {"items": items}, "reason": "Merchant can fix the failed verification"}

    # 4. All guardrails satisfied -> approve.
    ok, why_not = can_auto_approve(facts, policy)
    if ok:
        return {"action": "approve", "args": {}, "reason": "All required checks passed within policy thresholds"}

    # 5. Otherwise a human decides.
    recommendation = "review"
    return {"action": "escalate", "args": {"reason_codes": why_not, "recommendation": recommendation, "priority": "normal"},
            "reason": "; ".join(why_not)}
