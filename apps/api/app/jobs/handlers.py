"""Job handlers. Workflow jobs run under a per-application lock; if it's busy the job is re-queued shortly."""

from app.db.models import InfoRequest
from app.db.session import session_scope
from app.jobs.worker import Retry
from app.services import checks
from app.services.documents import ensure_extracted
from app.services.notifications import send_email_job
from app.workflow import runner


async def _locked(app_id: str, fn):
    lock = runner.local_lock(app_id)
    if lock.locked():
        raise Retry(1.0)
    async with lock, runner.app_lock(app_id) as acquired:
        if not acquired:
            raise Retry(1.0)
        await fn()


async def start_workflow(payload: dict, app_id: str | None) -> None:
    await _locked(app_id, lambda: runner.start(app_id))


async def resume_workflow(payload: dict, app_id: str | None) -> None:
    kind = payload.get("kind", "")
    await _locked(app_id, lambda: runner.resume(app_id, kind, payload.get("data") or {}))


async def check_timeout(payload: dict, app_id: str | None) -> None:
    async with session_scope() as s:
        await checks.handle_timeout(s, payload["check_id"])


async def info_request_expiry(payload: dict, app_id: str | None) -> None:
    async with session_scope() as s:
        ir = await s.get(InfoRequest, payload["info_request_id"])
        if ir is None or ir.status != "open":
            return
        ir.status = "expired"
    await _locked(app_id, lambda: runner.resume(app_id, "expired"))


async def send_email(payload: dict, app_id: str | None) -> None:
    async with session_scope() as s:
        await send_email_job(s, payload)


async def extract_document(payload: dict, app_id: str | None) -> None:
    await ensure_extracted(payload["document_id"], payload.get("actor", "system"))


HANDLERS = {
    "extract_document": extract_document,
    "start_workflow": start_workflow,
    "resume_workflow": resume_workflow,
    "check_timeout": check_timeout,
    "info_request_expiry": info_request_expiry,
    "send_email": send_email,
}
