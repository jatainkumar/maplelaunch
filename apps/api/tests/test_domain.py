"""Pure unit tests (no database): state machine, validators, policy guardrails, PII protection, webhook signing."""

import copy
import itertools

import pytest

from app.core import crypto
from app.domain import validators as v
from app.domain.policy import DEFAULT_POLICY, Facts, can_auto_approve, rules_decision
from app.domain.states import TERMINAL, TRANSITIONS, S, can_transition
from app.routers.webhooks import sign
from app.workflow.agent import _validate

POLICY = copy.deepcopy(DEFAULT_POLICY)


def facts(**kw) -> Facts:
    base = dict(business_type="proprietorship", category="retail", required_checks=["PAN", "GST", "BANK", "RISK"],
                checks={t: {"status": "PASSED", "reason_code": None, "attempt": 1} for t in ("PAN", "GST", "BANK", "RISK")},
                risk_score=10, risk_band="LOW", min_confidence=0.95)
    base.update(kw)
    return Facts(**base)


# ---------------------------------------------------------------- state machine ---------------------------------
def test_happy_path_transitions_are_legal():
    path = [S.DRAFT, S.SUBMITTED, S.PROCESSING_DOCUMENTS, S.VERIFYING, S.DECISIONING, S.APPROVED, S.PROVISIONING,
            S.LIVE]
    for a, b in itertools.pairwise(path):
        assert can_transition(a, b), f"{a} -> {b}"


@pytest.mark.parametrize("a,b", [(S.DRAFT, S.APPROVED), (S.VERIFYING, S.APPROVED), (S.REJECTED, S.APPROVED),
                                 (S.LIVE, S.REJECTED), (S.PROVISIONING_FAILED, S.REJECTED),
                                 (S.DECISIONING, S.REJECTED)])
def test_illegal_transitions(a, b):
    assert not can_transition(a, b)


def test_only_humans_reject():
    # REJECTED is reachable only from MANUAL_REVIEW (an operator decision).
    sources = [src for src, targets in TRANSITIONS.items() if S.REJECTED in targets]
    assert sources == [S.MANUAL_REVIEW]


def test_terminal_states_have_no_exits():
    for t in TERMINAL:
        assert TRANSITIONS[t] == set()


def test_approval_never_revoked_by_mid_failure():
    assert S.REJECTED not in TRANSITIONS[S.PROVISIONING_FAILED]
    assert TRANSITIONS[S.PROVISIONING_FAILED] == {S.PROVISIONING}


# ---------------------------------------------------------------- validators ------------------------------------
def test_gstin_checksum():
    assert v.valid_gstin("27AAPFU0939F1ZV")
    assert not v.valid_gstin("27AAPFU0939F1ZX")
    g = v.make_gstin("29", "BQXPK4821M")
    assert v.valid_gstin(g) and v.gstin_pan(g) == "BQXPK4821M"


def test_pan_holder_type():
    assert v.valid_pan("BQXPK4821M") and v.pan_holder_char("BQXPK4821M") == "P"
    assert v.pan_holder_char("AADCN5521K") == "C"
    assert not v.valid_pan("BQXZK4821M")  # Z is not a valid holder type


def test_ifsc_cin_account_phone():
    assert v.valid_ifsc("SBIN0000813") and not v.valid_ifsc("SBIN1000813")
    assert v.valid_cin("U72200KA2019PTC123456")
    assert v.valid_account("50100234567812") and not v.valid_account("12345")
    assert v.valid_phone("+91 98450 12345") and not v.valid_phone("12345")


def test_name_similarity_ignores_noise():
    assert v.name_similarity("M/s Kumar Chai Corner", "KUMAR CHAI CORNER") >= 95
    assert v.name_similarity("Nexa Softworks Pvt Ltd", "NEXA SOFTWORKS PRIVATE LIMITED") >= 95
    assert v.name_similarity("Nexa Softworks", "Nexus Soft Solutions") < 85


# ---------------------------------------------------------------- policy / guardrails ---------------------------
def test_auto_approve_happy():
    ok, why = can_auto_approve(facts(), POLICY)
    assert ok, why
    assert rules_decision(facts(), POLICY)["action"] == "approve"


@pytest.mark.parametrize("change,needle", [
    ({"risk_score": 65, "risk_band": "HIGH"}, "Risk score"),
    ({"category": "gaming"}, "high-risk"),
    ({"min_confidence": 0.4}, "confidence"),
    ({"conflicts": ["Legal name only partly matches"]}, "conflicts"),
    ({"open_duplicates": [{"matched_status": "LIVE"}]}, "duplicate"),
])
def test_guardrail_blocks(change, needle):
    ok, why = can_auto_approve(facts(**change), POLICY)
    assert not ok and any(needle in w for w in why)


def test_gst_cancelled_first_time_requests_info_then_escalates():
    f = facts(checks={**facts().checks, "GST": {"status": "FAILED", "reason_code": "GSTIN_CANCELLED", "attempt": 1}})
    d = rules_decision(f, POLICY)
    assert d["action"] == "request_info" and any(i["key"] == "gstin" for i in d["args"]["items"])
    f.checks["GST"]["attempt"] = 2
    d = rules_decision(f, POLICY)
    assert d["action"] == "escalate" and d["args"]["recommendation"] == "reject"


def test_invalid_pan_escalates_with_reject_recommendation():
    f = facts(checks={**facts().checks, "PAN": {"status": "FAILED", "reason_code": "PAN_INVALID", "attempt": 1}})
    d = rules_decision(f, POLICY)
    assert d["action"] == "escalate" and d["args"]["recommendation"] == "reject"


def test_timeout_retries_until_limit():
    f = facts(checks={**facts().checks, "GST": {"status": "TIMED_OUT", "reason_code": "CALLBACK_TIMEOUT",
                                                "attempt": 1}})
    assert rules_decision(f, POLICY)["action"] == "retry_check"
    f.checks["GST"]["attempt"] = POLICY["max_check_retries"] + 1
    assert rules_decision(f, POLICY)["action"] == "escalate"


def test_agent_cannot_bypass_guardrail():
    f = facts(category="crypto")
    assert _validate("approve_application", {"justification": "looks fine"}, f, POLICY) is not None
    assert _validate("approve_application", {"justification": "ok"}, facts(), POLICY) is None
    assert _validate("retry_checks", {"checks": ["PAN"]}, facts(), POLICY) is not None  # PAN already passed
    assert _validate("reject_application", {}, facts(), POLICY) is not None  # no such tool


def test_agent_can_only_send_fixable_failures_back_to_the_merchant():
    ask = {"items": [{"kind": "field", "key": "bank", "label": "Bank", "reason": "fix"}]}
    mismatch = facts(checks={**facts().checks, "BANK": {"status": "FAILED", "reason_code": "BENEFICIARY_NAME_MISMATCH",
                                                        "attempt": 1}})
    assert _validate("request_merchant_info", ask, mismatch, POLICY) is not None
    invalid = facts(checks={**facts().checks, "BANK": {"status": "FAILED", "reason_code": "ACCOUNT_INVALID",
                                                       "attempt": 1}})
    assert _validate("request_merchant_info", ask, invalid, POLICY) is None
    invalid.checks["BANK"]["attempt"] = 2
    assert _validate("request_merchant_info", ask, invalid, POLICY) is not None


# ---------------------------------------------------------------- PII ---------------------------------------------
def test_encryption_roundtrip_and_blind_index():
    token = crypto.encrypt("BQXPK4821M")
    assert token != "BQXPK4821M" and crypto.decrypt(token) == "BQXPK4821M"
    assert crypto.encrypt("BQXPK4821M") != token  # random nonce
    assert crypto.blind_index("pan", "bqxpk4821m") == crypto.blind_index("pan", "BQXPK 4821M")


def test_masking_and_redaction():
    assert crypto.mask("pan", "BQXPK4821M") == "BQXPK••••M"
    assert crypto.mask("account_number", "50100234567812").endswith("7812")
    text = crypto.redact_text("PAN BQXPK4821M acct 50100234567812 mail ravi@example.com")
    assert "BQXPK4821M" not in text and "50100234567812" not in text and "ravi@example.com" not in text


# ---------------------------------------------------------------- webhooks ----------------------------------------
def test_webhook_signature_depends_on_body_and_timestamp():
    s1 = sign(b'{"a":1}', "1700000000", "secret")
    assert s1 == sign(b'{"a":1}', "1700000000", "secret")
    assert s1 != sign(b'{"a":2}', "1700000000", "secret")
    assert s1 != sign(b'{"a":1}', "1700000001", "secret")


# ---------------------------------------------------------------- demo / production separation -------------------
def test_production_mode_refuses_development_secrets():
    from app.core.config import Settings, production_problems

    dev = Settings(_env_file=None, app_mode="production")
    problems = production_problems(dev)
    assert not dev.is_demo
    assert any("APP_SECRET" in p for p in problems) and any("ENCRYPTION_KEY" in p for p in problems)
    ready = Settings(_env_file=None, app_mode="production", app_secret="a" * 40, webhook_secret="b" * 32,
                     provider_admin_token="c" * 32, encryption_key="k", blind_index_key="i",
                     database_url="postgresql://user:pass@db.example.com:5432/postgres")
    assert production_problems(ready) == []


def test_demo_routes_are_hidden_in_production(monkeypatch):
    from fastapi import HTTPException

    from app.core import security

    monkeypatch.setattr(security.settings, "app_mode", "production")
    with pytest.raises(HTTPException) as exc:
        security.demo_only()
    assert exc.value.status_code == 404
    monkeypatch.setattr(security.settings, "app_mode", "demo")
    security.demo_only()


def test_model_text_is_made_plain():
    from app.services.llm import plain_text

    out = plain_text("**Reviewer focus:** check the bank \u2013 name differs\n## Next\nRetry in 2\u20138 s")
    assert out == "Reviewer focus: check the bank, name differs\nNext\nRetry in 2-8 s"


def test_database_url_copy_paste_mistakes_are_caught():
    from app.core.config import database_url_problem

    host = "aws-0-ap-south-1.pooler.supabase.com:5432/postgres"
    assert database_url_problem(f"postgresql://postgres.ref:secret@{host}") is None
    assert "placeholder" in database_url_problem("postgresql://postgres.ref:secret@aws-0-<region>.pooler.supabase.com")
    assert "%40" in database_url_problem(f"postgresql://postgres.ref:se@cret@{host}")
    assert database_url_problem(f"postgresql://postgres.ref:se%40cret@{host}") is None


def test_supabase_settings_are_checked_at_startup():
    from app.core.config import Settings, supabase_problems

    base = dict(_env_file=None, auth_mode="supabase", storage_mode="supabase", supabase_url="https://x.supabase.co",
                supabase_anon_key="sb_publishable_abc")
    assert any("SECRET" in p.upper() for p in supabase_problems(Settings(**base)))
    assert any("publishable" in p for p in supabase_problems(Settings(**base, supabase_service_role_key="sb_publishable_abc")))
    assert supabase_problems(Settings(**base, supabase_service_role_key="sb_secret_xyz")) == []
    assert supabase_problems(Settings(_env_file=None, auth_mode="local", storage_mode="local")) == []


def test_render_service_names_become_public_urls():
    from app.core.config import _with_scheme

    assert _with_scheme("maplelaunch-api") == "https://maplelaunch-api.onrender.com"
    assert _with_scheme("maplelaunch-web.onrender.com") == "https://maplelaunch-web.onrender.com"
    assert _with_scheme("localhost:3000") == "http://localhost:3000"
    assert _with_scheme("https://example.com/") == "https://example.com"


def test_extracted_capitals_are_made_readable():
    from app.routers.views import pretty_text

    assert pretty_text("KUMAR CHAI CORNER") == "Kumar Chai Corner"
    assert pretty_text("14, 5TH CROSS, MG ROAD 560034") == "14, 5th Cross, MG Road 560034"
    assert pretty_text("STATE BANK OF INDIA") == "State Bank of India"
    assert pretty_text("ICICI BANK") == "ICICI Bank"
    assert pretty_text("Ravi Kumar") == "Ravi Kumar"


async def test_network_block_skips_every_key_of_that_provider(monkeypatch):
    from langchain_core.messages import AIMessage

    from app.services import llm

    calls = []

    class Blocked:
        def __init__(self, name):
            self.name = name

        async def ainvoke(self, _):
            calls.append(self.name)
            raise RuntimeError("Error code: 403 - {'error': {'message': 'Access denied. Please check your network settings.'}}")

    class Works:
        async def ainvoke(self, _):
            calls.append("gemini")
            return AIMessage(content="ok")

    monkeypatch.setattr(llm, "_candidates", lambda kind: [("groq:m#1", lambda: Blocked("groq#1")),
                                                         ("groq:m#2", lambda: Blocked("groq#2")),
                                                         ("gemini:x", Works)])
    llm._cooldown.clear()
    try:
        result = await llm.invoke([], kind="text")
        assert result.content == "ok" and calls == ["groq#1", "gemini"]  # groq#2 was never tried
    finally:
        llm._cooldown.clear()


def test_llm_cooldown_matches_the_limit():
    from app.services.llm import COOLDOWN_SECONDS, MINUTE_COOLDOWN_SECONDS, cooldown_for

    groq_minute = Exception("Error code: 429 - Rate limit reached for model `m` on input tokens per minute (ITPM): "
                            "Limit 30000, Used 29000. Please try again in 4.25s.")
    assert 5 <= cooldown_for(groq_minute) < 6
    assert cooldown_for(Exception("429 rate limit ... Please try again in 2m3.5s")) == 2 * 60 + 3.5 + 1
    assert cooldown_for(Exception("429 tokens per minute (TPM) exceeded")) == MINUTE_COOLDOWN_SECONDS
    assert cooldown_for(Exception("RESOURCE_EXHAUSTED quota GenerateRequestsPerDay exceeded")) == COOLDOWN_SECONDS
    assert cooldown_for(Exception("429 Too Many Requests")) == COOLDOWN_SECONDS
