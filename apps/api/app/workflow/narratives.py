"""LLM-written text for humans (reviewer summary, risk explanation, merchant request), with template fallbacks."""

import json

from app.core.logging import log
from app.domain.policy import Facts
from app.services import llm
from app.workflow.facts import facts_for_prompt

SIGNAL_TEXT = {
    "high_risk_category": "business category is classed as high-risk",
    "new_gst_registration": "GST registration is less than 6 months old",
    "duplicate_matches": "details overlap with another application",
    "name_conflicts": "names differ across documents",
    "bank_changed_after_approval": "bank account changed after approval",
    "high_volume_new_business": "high expected volume for a new business",
}


async def risk_explanation(score: int | None, band: str | None, signals: list) -> str:
    fallback = (f"Risk score {score} ({band}). " + ("Signals: " + "; ".join(
        SIGNAL_TEXT.get(s.get("code"), s.get("code", "")) + f" (+{s.get('weight', 0)})" for s in signals)
        if signals else "No adverse signals."))
    try:
        r = await llm.complete_text(
            "You explain merchant risk scores to payment-operations reviewers in 2-3 plain sentences. "
            "No identifiers. Do not speculate beyond the signals.",
            json.dumps({"score": score, "band": band, "signals": signals}))
        return r.content.strip() or fallback
    except Exception as exc:
        log.info("risk_explanation_fallback", reason=str(exc)[:120])
        return fallback


async def review_summary(facts: Facts, reasons: list[str], recommendation: str) -> str:
    lines = [f"Recommendation: {recommendation.upper()}.", "Why this needs a human:"]
    lines += [f"• {r}" for r in reasons if r]
    for k, c in facts.checks.items():
        lines.append(f"• {k}: {c['status']}{' (' + c['reason_code'] + ')' if c.get('reason_code') else ''}"
                     f"{' (late result)' if c.get('late') else ''}")
    if facts.risk_score is not None:
        lines.append(f"• Risk score {facts.risk_score} ({facts.risk_band})")
    fallback = "\n".join(lines)
    try:
        r = await llm.complete_text(
            "You brief a payments-onboarding reviewer. Write 3-5 short bullet points: what passed, what failed or "
            "is uncertain, and what the reviewer should look at first. End with the recommendation. "
            "No identifiers (PAN, GSTIN, account numbers). Plain text bullets starting with '• '.",
            json.dumps({"facts": facts_for_prompt(facts), "escalation_reasons": reasons,
                        "recommendation": recommendation}, default=str))
        return r.content.strip() or fallback
    except Exception as exc:
        log.info("review_summary_fallback", reason=str(exc)[:120])
        return fallback


async def merchant_message(items: list[dict], business_name: str | None) -> str:
    bullet = "\n".join(f"• {i['label']}: {i['reason']}" for i in items)
    fallback = (f"Hi{(' ' + business_name) if business_name else ''}, we need a little more to finish your "
                f"onboarding:\n{bullet}\nOnce you update these, we'll continue verification automatically.")
    try:
        r = await llm.complete_text(
            "You write short, friendly, specific messages to small-business merchants in India who are being "
            "onboarded to a payments platform. Plain text, max 80 words, list each item on its own line starting "
            "with '• '. No identifiers. Do not promise approval.",
            json.dumps({"business_name": business_name, "items": items}))
        return r.content.strip() or fallback
    except Exception as exc:
        log.info("merchant_message_fallback", reason=str(exc)[:120])
        return fallback
