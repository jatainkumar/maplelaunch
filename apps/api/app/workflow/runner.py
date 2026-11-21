"""Starts and resumes workflow threads. Resumes are matched to what the thread is actually waiting for,
and serialised per application with a Postgres advisory lock (safe across processes)."""

import asyncio
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging import log
from app.db.models import Application
from app.db.session import engine, session_scope
from app.domain.states import TERMINAL, S
from app.workflow.graph import build_graph

settings = get_settings()

# Event kind -> the interrupt "wait" values it may resume.
KIND_TO_WAIT = {
    "check_updated": {"checks"},
    "merchant_responded": {"merchant"},
    "expired": {"merchant"},
    "review_decision": {"review"},
    "inputs_changed": {"review", "checks"},
    "retry_provisioning": {"ops"},
    "bank_changed": {"post_live"},
}

_pool: AsyncConnectionPool | None = None
_graph = None


async def init_workflow() -> None:
    global _pool, _graph
    _pool = AsyncConnectionPool(settings.psycopg_url, min_size=1, max_size=3, open=False,
                                kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row})
    await _pool.open()
    saver = AsyncPostgresSaver(_pool)
    await saver.setup()
    _graph = build_graph().compile(checkpointer=saver)


async def close_workflow() -> None:
    if _pool is not None:
        await _pool.close()


def graph():
    if _graph is None:
        raise RuntimeError("workflow not initialised")
    return _graph


def _config(app_id: str) -> dict:
    return {"configurable": {"thread_id": app_id}, "recursion_limit": 60}


@asynccontextmanager
async def app_lock(app_id: str):
    """Non-blocking per-application lock. Yields True if acquired."""
    async with engine.connect() as conn:
        got = (await conn.execute(text("SELECT pg_try_advisory_lock(hashtext(:k))"), {"k": f"wf:{app_id}"})).scalar()
        try:
            yield bool(got)
        finally:
            if got:
                await conn.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": f"wf:{app_id}"})
            await conn.commit()


async def waiting_for(app_id: str) -> str | None:
    state = await graph().aget_state(_config(app_id))
    if state.interrupts:
        return (state.interrupts[0].value or {}).get("wait")
    return None


async def _closed(app_id: str) -> bool:
    """A withdrawn or rejected application never runs again, even if callbacks keep arriving."""
    async with session_scope() as s:
        app = await s.get(Application, app_id)
        return app is None or S(app.status) in TERMINAL


async def start(app_id: str) -> None:
    if await _closed(app_id):
        return
    g = graph()
    cfg = _config(app_id)
    state = await g.aget_state(cfg)
    if not state.values:
        await g.ainvoke({"application_id": app_id}, cfg)
    elif not state.interrupts and state.next:
        await g.ainvoke(None, cfg)  # crashed mid-run earlier: continue from the last checkpoint


async def resume(app_id: str, kind: str, payload: dict | None = None) -> bool:
    if await _closed(app_id):
        log.info("resume_skipped_closed", app=app_id, kind=kind)
        return False
    g = graph()
    cfg = _config(app_id)
    state = await g.aget_state(cfg)
    if not state.values:
        return False
    if not state.interrupts:
        if state.next:
            await g.ainvoke(None, cfg)  # recover an interrupted run, then re-evaluate
            state = await g.aget_state(cfg)
            if not state.interrupts:
                return True
        else:
            log.info("resume_skipped_finished", app=app_id, kind=kind)
            return False
    wait = (state.interrupts[0].value or {}).get("wait")
    if wait not in KIND_TO_WAIT.get(kind, set()):
        log.info("resume_skipped_not_waiting", app=app_id, kind=kind, waiting_for=wait)
        return False
    await g.ainvoke(Command(resume={"kind": kind, **(payload or {})}), cfg)
    return True


_local_locks: dict[str, asyncio.Lock] = {}


def local_lock(app_id: str) -> asyncio.Lock:
    return _local_locks.setdefault(app_id, asyncio.Lock())
