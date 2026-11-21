"""MapleLaunch API: autonomous merchant onboarding (FastAPI + LangGraph)."""

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm.exc import StaleDataError

from app.core.config import get_settings, production_problems, supabase_problems
from app.core.logging import configure_logging, log
from app.core.security import seed_users
from app.db.session import init_db, session_scope
from app.domain.policy import get_active_policy
from app.domain.states import IllegalTransition
from app.jobs.worker import worker
from app.routers import admin, auth, demo, merchant, ops, webhooks
from app.services.storage import storage, verify_local_signature
from app.workflow import runner

settings = get_settings()
configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not settings.is_demo and (problems := production_problems(settings)):
        raise RuntimeError("Refusing to start in production mode: " + "; ".join(problems))
    if problems := supabase_problems(settings):
        raise RuntimeError("Supabase is not configured: " + "; ".join(problems))
    await init_db()
    async with session_scope() as s:
        await get_active_policy(s)
        await seed_users(s)
    await storage.ensure_bucket()
    await runner.init_workflow()
    if settings.worker_enabled:
        await worker.start()
    warmer = asyncio.create_task(_keep_providers_warm())
    log.info("startup_complete", mode=settings.app_mode, env=settings.env, auth=settings.auth_mode, storage=settings.storage_mode,
             llm=settings.llm_enabled)
    yield
    warmer.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await warmer
    await worker.stop()
    await runner.close_workflow()


async def _keep_providers_warm() -> None:
    """On free hosting the provider service sleeps on its own. While the API is awake, ping it so verification
    requests and the scenario lab don't wait for its cold start."""
    import httpx

    while True:
        with contextlib.suppress(Exception):
            async with httpx.AsyncClient(timeout=90) as c:
                await c.get(f"{settings.providers_base_url}/healthz")
        await asyncio.sleep(600)


app = FastAPI(title="MapleLaunch API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(IllegalTransition)
async def illegal_transition(_: Request, exc: IllegalTransition):
    return JSONResponse({"detail": f"Not allowed while the application is {exc.current}"}, status_code=409)


@app.exception_handler(StaleDataError)
async def stale(_: Request, __: StaleDataError):
    return JSONResponse({"detail": "This application was updated by someone else. Refresh and try again"},
                        status_code=409)


@app.get("/healthz", tags=["meta"])
async def healthz():
    return {"ok": True, "mode": settings.app_mode, "llm": settings.llm_enabled, "auth": settings.auth_mode}


@app.get("/files/{path:path}", include_in_schema=False)
async def local_file(path: str, exp: int, sig: str):
    if settings.storage_mode != "local" or not verify_local_signature(path, exp, sig):
        raise HTTPException(403, "Link expired")
    data = await storage.get(path)
    mime = "application/pdf" if path.endswith(".pdf") else "image/png" if path.endswith(".png") else "image/jpeg"
    return Response(data, media_type=mime, headers={"Cache-Control": "private, max-age=60"})


for r in (auth.router, merchant.router, merchant.notifications, merchant.meta, webhooks.router, ops.router,
          admin.router):
    app.include_router(r)
if settings.is_demo:  # personas, sample documents and "apply the fix" shortcuts exist only in the demo build
    app.include_router(demo.router)
