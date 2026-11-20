"""Postgres-backed durable job queue. Jobs survive restarts; timers are jobs with a future run_at."""

from datetime import datetime, timedelta

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, new_id, utcnow


async def enqueue(session: AsyncSession, type_: str, payload: dict, application_id: str | None = None,
                  run_at: datetime | None = None, delay_seconds: float = 0, dedupe_key: str | None = None,
                  max_attempts: int = 5) -> None:
    when = run_at or (utcnow() + timedelta(seconds=delay_seconds))
    stmt = insert(Job).values(id=new_id(), type=type_, payload=payload, application_id=application_id, run_at=when,
                              status="queued", attempts=0, max_attempts=max_attempts, dedupe_key=dedupe_key,
                              created_at=utcnow(), updated_at=utcnow())
    if dedupe_key:
        stmt = stmt.on_conflict_do_nothing(index_elements=["dedupe_key"])
    await session.execute(stmt)
