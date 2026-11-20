"""Background worker: claims due jobs with FOR UPDATE SKIP LOCKED and runs their handlers.
Failed jobs retry with exponential backoff; jobs that exhaust their attempts are marked 'dead' and raise an ops
exception (dead-letter)."""

import asyncio
import contextlib
import traceback
from datetime import timedelta

from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging import log
from app.db.models import Job, OpsException, utcnow
from app.db.session import SessionLocal, session_scope

settings = get_settings()

CLAIM_SQL = text("""
UPDATE jobs SET status = 'running', attempts = attempts + 1, updated_at = now()
WHERE id IN (
  SELECT id FROM jobs WHERE status = 'queued' AND run_at <= now()
  ORDER BY run_at LIMIT :n FOR UPDATE SKIP LOCKED
) RETURNING id
""")


class Retry(Exception):
    """Raise from a handler to re-run the job later without counting it as a failure."""

    def __init__(self, delay: float = 1.0):
        self.delay = delay


class Worker:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._running: set[asyncio.Task] = set()

    async def start(self) -> None:
        # Crash recovery: anything left 'running' by a previous process goes back to the queue.
        async with session_scope() as s:
            await s.execute(text("UPDATE jobs SET status='queued' WHERE status='running'"))
        self._task = asyncio.create_task(self._loop(), name="job-worker")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await asyncio.wait([self._task], timeout=5)
        if self._running:
            await asyncio.wait(self._running, timeout=10)

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                free = settings.worker_concurrency - len(self._running)
                ids: list[str] = []
                if free > 0:
                    async with session_scope() as s:
                        ids = list((await s.execute(CLAIM_SQL, {"n": free})).scalars())
                for job_id in ids:
                    t = asyncio.create_task(self._run(job_id))
                    self._running.add(t)
                    t.add_done_callback(self._running.discard)
            except Exception as exc:  # DB hiccup: keep the loop alive
                log.warning("worker_loop_error", error=str(exc)[:300])
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=settings.worker_poll_seconds)

    async def _run(self, job_id: str) -> None:
        from app.jobs.handlers import HANDLERS

        async with SessionLocal() as s:
            job = await s.get(Job, job_id)
            if job is None:
                return
            jtype, payload, app_id, attempts, max_attempts = (job.type, dict(job.payload), job.application_id,
                                                              job.attempts, job.max_attempts)
        handler = HANDLERS.get(jtype)
        try:
            if handler is None:
                raise RuntimeError(f"no handler for job type {jtype}")
            await handler(payload, app_id)
            async with session_scope() as s:
                job = await s.get(Job, job_id)
                job.status = "done"
                job.last_error = None
        except Retry as r:
            async with session_scope() as s:
                job = await s.get(Job, job_id)
                job.status = "queued"
                job.attempts = max(0, job.attempts - 1)
                job.run_at = utcnow() + timedelta(seconds=r.delay)
        except Exception as exc:
            err = "".join(traceback.format_exception_only(type(exc), exc)).strip()[:1000]
            log.warning("job_failed", job_type=jtype, attempt=attempts, error=err)
            async with session_scope() as s:
                job = await s.get(Job, job_id)
                job.last_error = err
                if attempts >= max_attempts:
                    job.status = "dead"
                    s.add(OpsException(application_id=app_id, kind="job_dead_lettered", severity="high",
                                       message=f"Background job '{jtype}' failed {attempts} times: {err[:300]}"))
                else:
                    job.status = "queued"
                    job.run_at = utcnow() + timedelta(seconds=min(2 ** attempts, 60))


worker = Worker()
