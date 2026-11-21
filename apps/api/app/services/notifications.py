"""Merchant notifications: in-app inbox (source of truth) + best-effort email via Resend."""

import html

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import log
from app.db.models import Notification, User
from app.jobs.queue import enqueue

settings = get_settings()


async def notify(session: AsyncSession, user_id: str, application_id: str | None, title: str, body: str) -> None:
    n = Notification(user_id=user_id, application_id=application_id, title=title, body=body,
                     email_status="queued" if settings.resend_api_key else "skipped")
    session.add(n)
    await session.flush()
    if settings.resend_api_key:
        await enqueue(session, "send_email", {"notification_id": n.id}, max_attempts=3)


async def send_email_job(session: AsyncSession, payload: dict) -> None:
    n = await session.get(Notification, payload["notification_id"])
    if n is None:
        return
    user = await session.get(User, n.user_id)
    if user is None:
        n.email_status = "skipped"
        return
    recipient = user.email
    to = settings.email_redirect_to.strip() or recipient
    redirected = to != recipient
    body_html = (
        "<div style='font-family:Inter,Arial,sans-serif;max-width:520px'>"
        "<p style='color:#D9480F;font-weight:600'>MapleLaunch</p>"
        f"<h2 style='color:#18181B'>{html.escape(n.title)}</h2>"
        f"<p style='color:#3F3F46;white-space:pre-line'>{html.escape(n.body)}</p>"
        f"<p><a href='{settings.cors_origins[0]}/merchant/' style='color:#D9480F'>Open your application</a></p>"
        + ("<p style='color:#A1A1AA;font-size:12px'>Demo environment: synthetic data only.</p>" if settings.is_demo
           else "")
        + (f"<p style='color:#A1A1AA;font-size:12px'>Delivered to you on behalf of {html.escape(recipient)}.</p>"
           if redirected else "")
        + "</div>"
    )
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post("https://api.resend.com/emails",
                         headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                         json={"from": settings.email_from, "to": [to], "subject": n.title, "html": body_html})
    if r.status_code >= 400:
        # Resend's free tier only delivers to the account owner's address without a verified domain.
        log.warning("email_failed", status=r.status_code, body=r.text[:200])
        n.email_status = "failed"
        if r.status_code >= 500:
            raise RuntimeError(f"Resend {r.status_code}")
        return
    n.email_status = "sent"
