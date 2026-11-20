"""Decision agent: an LLM with four tools, wrapped in hard guardrails.

* approve_application   -> only executes if policy.can_auto_approve() is true (code, not the model, decides)
* request_merchant_info -> asks the merchant for specific documents/fields
* retry_checks          -> only for checks that timed out / errored and still have retries left
* escalate_to_human     -> always allowed
There is deliberately NO reject tool: only humans can reject.
If the LLM is unavailable or misbehaves, the deterministic rules engine decides instead."""

import json
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.logging import log
from app.domain.policy import DOC_TYPES, FIXABLE_REASONS, Facts, can_auto_approve, rules_decision
from app.services import llm
from app.workflow.facts import facts_for_prompt

settings = get_settings()
AGENT_PROMPT_VERSION = "agent-v1"


class approve_application(BaseModel):
    """Approve the merchant. Only call when every required check passed and nothing needs human judgement."""

    justification: str = Field(description="One or two sentences citing the evidence")


class InfoItem(BaseModel):
    kind: Literal["document", "field", "confirm"]
    key: str = Field(description="Document slot (e.g. GST_CERTIFICATE) or field key (gstin, bank, legal_name, pan)")
    label: str
    reason: str


class request_merchant_info(BaseModel):
    """Ask the merchant to fix or provide something they can fix themselves (e.g. a wrong GSTIN)."""

    items: list[InfoItem]
    message: str = Field(description="Short, polite, specific message to the merchant")


class retry_checks(BaseModel):
    """Re-run verification checks that timed out or hit a provider error."""

    checks: list[Literal["PAN", "GST", "BANK", "RISK"]]
    reason: str


class escalate_to_human(BaseModel):
    """Send the application to the human review queue."""

    reason: str
    recommendation: Literal["approve", "reject", "review"]
    priority: Literal["high", "normal"] = "normal"


TOOLS = [approve_application, request_merchant_info, retry_checks, escalate_to_human]

SYSTEM = """You are MapleLaunch's onboarding decision agent for a payments company in India.
You decide the NEXT STEP for one merchant application by calling exactly one tool.

Policy (version {policy_version}):
- Auto-approve only when all required checks PASSED, risk score <= {max_risk}, category is not high-risk
  ({high_risk}), extraction confidence >= {min_conf}, and there are no conflicts or possible duplicates.
  The platform enforces this; an approval that violates it will be refused.
- If a check TIMED_OUT or returned ERROR and attempt <= {max_retries}, prefer retry_checks.
- If a failure is something the merchant can fix (wrong/cancelled GSTIN on first attempt, invalid bank account on
  first attempt, unreadable document), call request_merchant_info with precise items.
- Invalid or deactivated PAN, repeated failures, duplicates of rejected merchants, high risk, conflicts, or anything
  uncertain -> escalate_to_human. Use recommendation "reject" only for clear-cut critical failures.
- You cannot reject. Be concise and factual. Never include identifiers like PAN or account numbers in text.
Valid document slots: {slots}. Valid field keys: gstin, pan, bank, legal_name, cin."""


def _validate(name: str, args: dict, facts: Facts, policy: dict) -> str | None:
    """Return an error string if the tool call violates a guardrail."""
    if name == "approve_application":
        ok, why = can_auto_approve(facts, policy)
        return None if ok else "Guardrail refused approval: " + "; ".join(why)
    if name == "retry_checks":
        bad = [c for c in args.get("checks", [])
               if facts.checks.get(c, {}).get("status") not in ("TIMED_OUT", "ERROR")
               or facts.checks.get(c, {}).get("attempt", 1) > policy.get("max_check_retries", 2)]
        if not args.get("checks") or bad:
            return f"Cannot retry {bad or 'nothing'}: only TIMED_OUT/ERROR checks with retries left can be retried"
        return None
    if name == "request_merchant_info":
        items = args.get("items") or []
        if not items:
            return "items must not be empty"
        for it in items:
            if it.get("kind") == "document" and it.get("key") not in DOC_TYPES:
                return f"Unknown document slot {it.get('key')}"
        # Only merchant-fixable failures (e.g. a cancelled GSTIN, an invalid account) may go back to the merchant,
        # and only once. Anything else (a beneficiary-name mismatch, an invalid PAN, a repeat failure, a possible
        # duplicate) needs a human decision.
        for check, c in facts.checks.items():
            if c.get("status") != "FAILED":
                continue
            reason = c.get("reason_code")
            if reason not in FIXABLE_REASONS.get(check, set()) or c.get("attempt", 1) > 1:
                return (f"{check} failed with {reason}, which the merchant cannot fix on their own: "
                        "use escalate_to_human instead")
        if facts.open_duplicates:
            return "Possible duplicate merchant: use escalate_to_human instead"
        return None
    if name == "escalate_to_human":
        return None
    return f"Unknown tool {name}"


def _to_decision(name: str, args: dict, reasoning: str) -> dict:
    reasoning = llm.plain_text(reasoning)
    args = {k: llm.plain_text(v) if isinstance(v, str) else v for k, v in args.items()}
    if name == "approve_application":
        return {"action": "approve", "args": {}, "reason": args.get("justification") or reasoning}
    if name == "request_merchant_info":
        return {"action": "request_info", "args": {"items": args["items"], "message": args.get("message")},
                "reason": reasoning or args.get("message", "")}
    if name == "retry_checks":
        return {"action": "retry_check", "args": {"checks": args["checks"]}, "reason": args.get("reason", "")}
    return {"action": "escalate", "args": {"reason_codes": [args.get("reason", "")],
                                           "recommendation": args.get("recommendation", "review"),
                                           "priority": args.get("priority", "normal")},
            "reason": args.get("reason", "")}


async def decide(facts: Facts, policy: dict, policy_version: int) -> dict:
    rules = rules_decision(facts, policy)
    base = {"rules_action": rules["action"]}
    if not settings.llm_enabled:
        return {**rules, **base, "model": "rules-engine", "used_fallback": True, "guardrail": {}}

    t = policy["thresholds"]
    system = SYSTEM.format(policy_version=policy_version, max_risk=t["auto_approve_max_risk"],
                           high_risk=", ".join(policy.get("high_risk_categories", [])),
                           min_conf=t["min_extraction_confidence"], max_retries=policy.get("max_check_retries", 2),
                           slots=", ".join(DOC_TYPES))
    messages = [SystemMessage(system),
                HumanMessage("Application facts (JSON):\n" + json.dumps(facts_for_prompt(facts), indent=1, default=str)
                             + "\n\nCall exactly one tool.")]
    refusals = []
    try:
        for _ in range(3):
            result = await llm.invoke(messages, kind="text", tools=TOOLS)
            calls = getattr(result.message, "tool_calls", None) or []
            if not calls:
                messages += [result.message, HumanMessage("You must call exactly one tool.")]
                continue
            call = calls[0]
            error = _validate(call["name"], call["args"], facts, policy)
            if error:
                refusals.append({"tool": call["name"], "error": error})
                messages += [result.message, ToolMessage(content=error, tool_call_id=call.get("id") or "call")]
                continue
            decision = _to_decision(call["name"], call["args"], result.content)
            return {**decision, **base, "model": result.model, "used_fallback": False,
                    "guardrail": {"refusals": refusals, "prompt_version": AGENT_PROMPT_VERSION}}
    except llm.LLMUnavailable as exc:
        log.warning("agent_llm_unavailable", error=str(exc))
    except Exception as exc:  # never let the agent break the workflow
        log.warning("agent_error", error=str(exc)[:300])
    return {**rules, **base, "model": "rules-engine", "used_fallback": True,
            "guardrail": {"refusals": refusals, "prompt_version": AGENT_PROMPT_VERSION}}
