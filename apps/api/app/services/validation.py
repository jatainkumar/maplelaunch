"""Deterministic validation: completeness, document quality, identifier formats and cross-document consistency."""

import uuid
from dataclasses import dataclass
from dataclasses import field as dc_field

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Application, ValidationResult
from app.domain import validators as v
from app.domain.policy import DOC_TYPES, business_rules
from app.services.applications import active_documents, app_data, extraction_value, latest_extraction
from app.services.ifsc import lookup_ifsc

KEY_FIELDS = {"pan_number", "gstin", "account_number", "ifsc", "name", "legal_name", "cin", "company_name",
              "firm_name", "account_holder_name"}


@dataclass
class Issue:
    rule: str
    message: str
    blocking: bool
    field: str | None = None
    slot: str | None = None
    details: dict = dc_field(default_factory=dict)


@dataclass
class ValidationReport:
    run_id: str
    blocking: list[Issue]
    flags: list[Issue]
    passed: list[Issue]
    min_confidence: float | None
    low_confidence_fields: list[str]
    extraction_failures: list[str]

    @property
    def conflicts(self) -> list[str]:
        return [i.message for i in self.flags if i.rule.startswith("conflict")]


async def validate_application(session: AsyncSession, app: Application, policy: dict) -> ValidationReport:
    rules = business_rules(policy, app.business_type)
    t = policy["thresholds"]
    data = await app_data(session, app, reveal=True)
    confirmations = (app.form_data or {}).get("confirmations") or {}
    blocking: list[Issue] = []
    flags: list[Issue] = []
    passed: list[Issue] = []
    confidences: list[float] = []
    low_conf: list[str] = []
    failures: list[str] = []

    def ok(rule, message, field=None, slot=None):
        passed.append(Issue(rule, message, False, field, slot))

    # ---- Documents: presence, readability, type -------------------------------------------------
    docs = {d.slot: d for d in await active_documents(session, app.id)}
    extracted: dict[str, dict] = {}
    for slot in rules["required_documents"]:
        label = DOC_TYPES[slot]["label"]
        doc = docs.get(slot)
        if doc is None:
            blocking.append(Issue("missing_document", f"{label} is missing", True, slot=slot))
            continue
        ext = await latest_extraction(session, doc.id)
        if ext is None or ext.error:
            failures.append(label)
            flags.append(Issue("extraction_unavailable", f"{label} could not be read automatically", False, slot=slot,
                               details={"error": ext.error if ext else "not extracted"}))
            continue
        extracted[slot] = ext.fields
        q = ext.quality or {}
        if (q.get("score", 1) < t["min_document_quality"]) or q.get("legible") is False:
            blocking.append(Issue("document_unreadable",
                                  f"{label} is blurred or unreadable ({q.get('notes') or 'low image quality'})", True,
                                  slot=slot, details={"quality": q.get("score")}))
            continue
        if ext.detected_type and ext.detected_type not in (slot, None) and ext.detected_type in DOC_TYPES | {"OTHER": 1}:
            blocking.append(Issue("wrong_document", f"The file uploaded as {label} looks like "
                                  f"{DOC_TYPES.get(ext.detected_type, {}).get('label', 'a different document')}",
                                  True, slot=slot))
            continue
        if q.get("suspicious"):
            flags.append(Issue("possible_tampering", f"{label}: {q.get('suspicion_notes') or 'possible tampering'}",
                               False, slot=slot))
        ok("document_ok", f"{label} received and legible", slot=slot)
        for name, item in ext.fields.items():
            if name in KEY_FIELDS and item.get("confidence") is not None and (item.get("value") or item.get("value_enc")):
                confidences.append(item["confidence"])
                if item["confidence"] < t["min_extraction_confidence"]:
                    low_conf.append(f"{label}: {name}")

    def ext_val(slot, name):
        return extraction_value(extracted[slot], name) if slot in extracted else None

    # ---- Identifier formats ----------------------------------------------------------------------
    pan = v.clean(data.get("pan"))
    if not v.valid_pan(pan):
        blocking.append(Issue("pan_format", "PAN is missing or not in a valid format", True, field="pan"))
    else:
        expected = rules.get("pan_holder_type")
        if expected and v.pan_holder_char(pan) != expected:
            blocking.append(Issue(
                "pan_holder_type",
                f"PAN belongs to a {v.PAN_HOLDER_TYPES.get(v.pan_holder_char(pan), 'different holder type')}, "
                f"but a {v.PAN_HOLDER_TYPES[expected]} PAN is required for this business type", True, field="pan"))
        else:
            ok("pan_format", "PAN format and holder type are valid", field="pan")

    if "GST" in rules["required_checks"]:
        gstin = v.clean(data.get("gstin"))
        if not v.valid_gstin(gstin):
            blocking.append(Issue("gstin_format", "GSTIN is missing or fails the checksum", True, field="gstin"))
        elif v.valid_pan(pan) and v.gstin_pan(gstin) != pan:
            blocking.append(Issue("gstin_pan_mismatch", "The PAN embedded in the GSTIN does not match the PAN", True,
                                  field="gstin"))
        else:
            ok("gstin_format", "GSTIN checksum valid and linked to the PAN", field="gstin")

    if not v.valid_account(data.get("account_number")):
        blocking.append(Issue("account_format", "Bank account number must be 9-18 digits", True, field="bank"))
    ifsc = await lookup_ifsc(data.get("ifsc") or "")
    if not ifsc["valid_format"]:
        blocking.append(Issue("ifsc_format", "IFSC is not in a valid format", True, field="bank"))
    elif ifsc["found"] is False:
        blocking.append(Issue("ifsc_not_found", "IFSC does not exist", True, field="bank"))
    elif ifsc["found"] is None:
        flags.append(Issue("ifsc_unverified", "IFSC lookup service unavailable; format is valid", False, field="bank"))
    else:
        ok("ifsc_found", f"IFSC belongs to {ifsc.get('bank')}, {ifsc.get('branch')}", field="bank")

    if app.business_type == "private_limited" and not v.valid_cin(data.get("cin")):
        blocking.append(Issue("cin_format", "CIN is missing or not in a valid format", True, field="cin"))

    # ---- Cross-document consistency --------------------------------------------------------------
    def exact(field_key, slot, ext_name, label):
        form_value = v.clean(data.get(field_key))
        doc_value = v.clean(ext_val(slot, ext_name))
        if not doc_value or not form_value:
            return
        if form_value != doc_value:
            if confirmations.get(field_key):
                flags.append(Issue("conflict_" + field_key,
                                   f"{label} on the form differs from the {DOC_TYPES[slot]['label']} "
                                   "(merchant confirmed the form value)", False, field=field_key, slot=slot))
            else:
                blocking.append(Issue("conflict_" + field_key,
                                      f"{label} on the form differs from the {DOC_TYPES[slot]['label']}", True,
                                      field=field_key, slot=slot))
        else:
            ok("match_" + field_key, f"{label} matches the {DOC_TYPES[slot]['label']}", field=field_key, slot=slot)

    exact("pan", "PAN_CARD", "pan_number", "PAN")
    exact("gstin", "GST_CERTIFICATE", "gstin", "GSTIN")
    exact("account_number", "BANK_PROOF", "account_number", "Account number")
    exact("ifsc", "BANK_PROOF", "ifsc", "IFSC")
    if app.business_type == "private_limited":
        exact("cin", "INCORPORATION_CERTIFICATE", "cin", "CIN")

    legal = data.get("legal_name")
    name_sources = [("PAN_CARD", "name"), ("GST_CERTIFICATE", "legal_name"),
                    ("INCORPORATION_CERTIFICATE", "company_name"), ("PARTNERSHIP_DEED", "firm_name")]
    for slot, name in name_sources:
        doc_name = ext_val(slot, name)
        if not doc_name or not legal:
            continue
        score = v.name_similarity(legal, doc_name)
        label = DOC_TYPES[slot]["label"]
        if score >= t["name_match_min"]:
            ok("name_match", f"Legal name matches the {label} ({score}%)", field="legal_name", slot=slot)
        elif score >= 70 or confirmations.get("legal_name"):
            flags.append(Issue("conflict_name", f"Legal name only partly matches the {label} ({score}%)", False,
                               field="legal_name", slot=slot, details={"score": score}))
        else:
            blocking.append(Issue("conflict_name", f"Legal name '{legal}' does not match the {label} ({score}%)",
                                  True, field="legal_name", slot=slot, details={"score": score}))

    constitution = (ext_val("GST_CERTIFICATE", "constitution") or "").lower()
    expected_word = {"proprietorship": "propriet", "partnership": "partner", "private_limited": "private"}.get(
        app.business_type or "", "")
    if constitution and expected_word and expected_word not in constitution:
        flags.append(Issue("constitution_mismatch",
                           f"GST certificate says '{constitution}', which differs from the chosen business type",
                           False, field="business_type"))

    # ---- Persist ---------------------------------------------------------------------------------
    run_id = str(uuid.uuid4())
    await session.execute(delete(ValidationResult).where(ValidationResult.application_id == app.id))
    for issue, outcome in [*[(i, "fail") for i in blocking], *[(i, "warn") for i in flags],
                           *[(i, "pass") for i in passed]]:
        session.add(ValidationResult(application_id=app.id, run_id=run_id, rule=issue.rule, outcome=outcome,
                                     blocking=issue.blocking, field=issue.field, document_slot=issue.slot,
                                     message=issue.message, details=issue.details))
    if ifsc.get("found"):
        form = dict(app.form_data or {})
        form.update({"bank_name": ifsc.get("bank"), "bank_branch": ifsc.get("branch")})
        app.form_data = form
    await session.flush()
    return ValidationReport(run_id=run_id, blocking=blocking, flags=flags, passed=passed,
                            min_confidence=min(confidences) if confidences else (None if failures else 1.0),
                            low_confidence_fields=low_conf, extraction_failures=failures)


def info_items_from_issues(issues: list[Issue]) -> list[dict]:
    """Turn blocking validation issues into concrete things to ask the merchant for (deduplicated)."""
    items: dict[str, dict] = {}
    for i in issues:
        if i.rule in ("missing_document", "document_unreadable", "wrong_document"):
            key = f"document:{i.slot}"
            items[key] = {"kind": "document", "key": i.slot, "label": DOC_TYPES[i.slot]["label"], "reason": i.message}
        elif i.rule.startswith("conflict"):
            fkey = i.field or "legal_name"
            items[f"confirm:{fkey}"] = {"kind": "confirm", "key": fkey, "label": fkey.replace("_", " ").title(),
                                       "reason": i.message, "slot": i.slot}
        else:
            fkey = i.field or i.rule
            items[f"field:{fkey}"] = {"kind": "field", "key": fkey, "label": fkey.replace("_", " ").upper()
                                     if fkey in ("pan", "gstin", "cin") else fkey.replace("_", " ").title(),
                                     "reason": i.message}
    return list(items.values())
