"""Duplicate application detection and entity matching.
Exact matches use blind indexes (no decryption needed); fuzzy matches compare business names within the same pincode."""

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Application, ApplicationPII, Document, DuplicateMatch
from app.domain.validators import name_similarity
from app.services.applications import get_pii

WEIGHTS = {"pan": 1.0, "gstin": 1.0, "account_number": 0.9, "document_hash": 0.9, "name_and_pincode": 0.7,
           "phone": 0.6, "email": 0.6}


async def find_duplicates(session: AsyncSession, app: Application) -> list[DuplicateMatch]:
    pii = await get_pii(session, app.id)
    hits: dict[str, set[str]] = {}

    def add(other_id: str, reason: str):
        if other_id != app.id:
            hits.setdefault(other_id, set()).add(reason)

    pairs = [("pan", ApplicationPII.pan_bi, pii.pan_bi), ("gstin", ApplicationPII.gstin_bi, pii.gstin_bi),
             ("account_number", ApplicationPII.account_bi, pii.account_bi),
             ("phone", ApplicationPII.phone_bi, pii.phone_bi), ("email", ApplicationPII.email_bi, pii.email_bi)]
    conditions = [col == val for _, col, val in pairs if val]
    if conditions:
        rows = (await session.execute(select(ApplicationPII).where(or_(*conditions)))).scalars()
        for row in rows:
            for reason, col, val in pairs:
                if val and getattr(row, col.key) == val:
                    add(row.application_id, reason)

    # Same file uploaded to another application.
    my_hashes = select(Document.sha256).where(Document.application_id == app.id)
    rows = (await session.execute(select(Document.application_id).where(Document.sha256.in_(my_hashes),
                                                                         Document.application_id != app.id))).scalars()
    for other in rows:
        add(other, "document_hash")

    # Fuzzy business name within the same pincode.
    form = app.form_data or {}
    if form.get("pincode") and (form.get("trade_name") or form.get("legal_name")):
        others = (await session.execute(select(Application).where(Application.id != app.id,
                                                                  Application.status != "DRAFT"))).scalars()
        for other in others:
            of = other.form_data or {}
            if of.get("pincode") != form.get("pincode"):
                continue
            score = max(name_similarity(form.get("trade_name"), of.get("trade_name")),
                        name_similarity(form.get("legal_name"), of.get("legal_name")))
            if score >= 92:
                add(other.id, "name_and_pincode")

    # Replace previous open matches; keep ones an operator already cleared.
    cleared = set((await session.execute(select(DuplicateMatch.matched_application_id).where(
        DuplicateMatch.application_id == app.id, DuplicateMatch.status == "cleared"))).scalars())
    await session.execute(delete(DuplicateMatch).where(DuplicateMatch.application_id == app.id,
                                                       DuplicateMatch.status == "open"))
    matches = []
    for other_id, reasons in hits.items():
        if other_id in cleared:
            continue
        score = min(1.0, max(WEIGHTS[r] for r in reasons) + 0.05 * (len(reasons) - 1))
        m = DuplicateMatch(application_id=app.id, matched_application_id=other_id, matched_on=sorted(reasons),
                           score=round(score, 2))
        session.add(m)
        matches.append(m)
    await session.flush()
    return matches


async def open_duplicates(session: AsyncSession, app_id: str) -> list[dict]:
    rows = (await session.execute(
        select(DuplicateMatch, Application.status, Application.reference)
        .join(Application, Application.id == DuplicateMatch.matched_application_id)
        .where(DuplicateMatch.application_id == app_id, DuplicateMatch.status == "open")
    )).all()
    return [{"id": m.id, "matched_application_id": m.matched_application_id, "matched_reference": ref,
             "matched_status": status, "matched_on": m.matched_on, "score": m.score} for m, status, ref in rows]
