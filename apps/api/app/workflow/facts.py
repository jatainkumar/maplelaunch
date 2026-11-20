"""Builds the structured facts the decision agent sees. The agent never sees raw document text."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Application, Extraction, ValidationResult
from app.domain.policy import Facts, required_checks
from app.services.applications import active_documents
from app.services.checks import current_checks
from app.services.dedupe import open_duplicates
from app.services.validation import KEY_FIELDS


async def gather_facts(session: AsyncSession, app: Application, policy: dict) -> Facts:
    checks = await current_checks(session, app.id)
    vr = list((await session.execute(select(ValidationResult).where(ValidationResult.application_id == app.id)))
              .scalars())
    conflicts = [r.message for r in vr if r.outcome == "warn" and r.rule.startswith("conflict")]
    warnings = [r.message for r in vr if r.outcome == "warn" and not r.rule.startswith("conflict")]
    failures = [r.document_slot for r in vr if r.rule == "extraction_unavailable"]

    t = policy["thresholds"]
    confidences, low = [], []
    doc_ids = [d.id for d in await active_documents(session, app.id)]
    if doc_ids:
        rows = (await session.execute(select(Extraction).where(Extraction.document_id.in_(doc_ids))
                                      .order_by(Extraction.created_at))).scalars()
        latest = {}
        for e in rows:
            latest[e.document_id] = e
        for e in latest.values():
            if e.error:
                continue
            for name, item in (e.fields or {}).items():
                has_value = item.get("value") or item.get("value_enc")
                if name in KEY_FIELDS and has_value:
                    confidences.append(item.get("confidence", 0))
                    if item.get("confidence", 0) < t["min_extraction_confidence"]:
                        low.append(name)
    return Facts(
        business_type=app.business_type or "proprietorship",
        category=app.category,
        required_checks=required_checks(policy, app.business_type),
        checks={k: {"status": c.status, "reason_code": c.reason_code, "attempt": c.attempt, "late": c.late,
                    "result": c.result} for k, c in checks.items()},
        risk_score=app.risk_score,
        risk_band=app.risk_band,
        min_confidence=min(confidences) if confidences else (None if failures else 1.0),
        low_confidence_fields=low,
        conflicts=conflicts,
        warnings=warnings,
        open_duplicates=await open_duplicates(session, app.id),
        extraction_failures=[f for f in failures if f],
    )


def facts_for_prompt(f: Facts) -> dict:
    return {
        "business_type": f.business_type,
        "category": f.category,
        "required_checks": f.required_checks,
        "checks": {k: {kk: vv for kk, vv in v.items() if kk != "result"} | {"details": _safe(v.get("result"))}
                   for k, v in f.checks.items()},
        "risk": {"score": f.risk_score, "band": f.risk_band},
        "extraction": {"min_confidence": f.min_confidence, "low_confidence_fields": f.low_confidence_fields,
                       "unreadable_documents": f.extraction_failures},
        "conflicts": f.conflicts,
        "warnings": f.warnings,
        "possible_duplicates": [{"reference": d["matched_reference"], "status": d["matched_status"],
                                 "matched_on": d["matched_on"], "score": d["score"]} for d in f.open_duplicates],
    }


def _safe(result: dict | None) -> dict:
    """Only non-identifying result details are shown to the LLM."""
    if not result:
        return {}
    keep = {"name_match", "name_match_score", "status", "registration_status", "account_status", "band", "score",
            "signals", "error"}
    return {k: v for k, v in result.items() if k in keep}
