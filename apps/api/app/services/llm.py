"""LLM access with provider fallback, in LLM_ORDER (default: Groq, then several Gemini models).

Rate-limited models are skipped for a while. Callers handle the "no LLM available" case with deterministic logic,
so the platform keeps working during outages."""

import asyncio
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.messages import BaseMessage

from app.core.config import get_settings
from app.core.logging import log

settings = get_settings()

# Free tiers have tight per-minute limits; keep concurrency low.
_semaphore = asyncio.Semaphore(4)


class LLMUnavailable(Exception):
    pass


@dataclass
class LLMResult:
    content: str
    model: str
    latency_ms: int
    message: BaseMessage


# Provider/model -> monotonic time until which it is skipped (free-tier rate limits and daily quotas).
_cooldown: dict[str, float] = {}
COOLDOWN_SECONDS = 600


def _gemini_factory(model: str):
    def make():
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(model=model, google_api_key=settings.gemini_api_key, temperature=0,
                                      max_retries=0, timeout=settings.llm_timeout_seconds)
    return make


def _groq_factory(model: str, key: str):
    def make():
        from langchain_groq import ChatGroq

        return ChatGroq(model=model, api_key=key, temperature=0, max_retries=0,
                        timeout=settings.llm_timeout_seconds)
    return make


def _candidates(kind: str) -> list[tuple[str, object]]:
    """Ordered (label, factory) pairs for 'vision' or 'text' tasks, following LLM_ORDER."""
    out = []
    for provider in [p.strip() for p in settings.llm_order.split(",") if p.strip()]:
        if provider == "groq" and settings.groq_keys:
            model = settings.groq_vision_model if kind == "vision" else settings.groq_text_model
            keys = settings.groq_keys
            for i, key in enumerate(keys):  # each key has its own cooldown; labels never include the key itself
                label = f"groq:{model}" if len(keys) == 1 else f"groq:{model}#{i + 1}"
                out.append((label, _groq_factory(model, key)))
        elif provider == "gemini" and settings.gemini_api_key:
            for model in [m.strip() for m in settings.gemini_models.split(",") if m.strip()]:
                out.append((f"gemini:{model}", _gemini_factory(model)))
    return out


def _blocked(exc: Exception) -> bool:
    """401/403: bad key, or the provider refuses this network (e.g. Groq blocks VPN and hosting IPs)."""
    text = f"{type(exc).__name__} {exc}"
    return any(k in text for k in ("Error code: 401", "Error code: 403", "PermissionDenied", "Access denied"))


def _rate_limited(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}"
    return any(k in text for k in ("429", "RESOURCE_EXHAUSTED", "RateLimit", "rate_limit", "quota"))


async def invoke(messages: list, kind: str = "text", tools: list | None = None,
                 accept: Callable[[LLMResult], bool] | None = None) -> LLMResult:
    """Try each configured model in order. `accept` lets the caller reject a well-formed but wrong answer (for
    example an extracted GSTIN that fails its checksum); the next model then gets a turn. If no answer is accepted,
    the first one is returned and the caller's own validation flags it."""
    errors: list[str] = []
    rejected: LLMResult | None = None
    rejected_models: set[str] = set()
    now = time.monotonic()
    candidates = _candidates(kind)
    for label, factory in candidates:
        if label.split("#")[0] in rejected_models:  # same model, different key: it would misread the same way
            continue
        if _cooldown.get(label, 0) > now:
            errors.append(f"{label}: cooling down after a rate limit")
            continue
        try:
            model = factory()
            if tools:
                model = model.bind_tools(tools)
            started = time.perf_counter()
            async with _semaphore:
                msg = await asyncio.wait_for(model.ainvoke(messages), timeout=settings.llm_timeout_seconds + 5)
            content = msg.content if isinstance(msg.content, str) else _flatten(msg.content)
            result = LLMResult(content=content, model=label, latency_ms=int((time.perf_counter() - started) * 1000),
                               message=msg)
        except Exception as exc:  # rate limit, outage, bad request -> try the next model
            if _blocked(exc) and "Access denied" in str(exc):
                # A network-level block applies to every key of this provider: skip all of them for a while.
                provider = label.split(":")[0] + ":"
                for other, _ in candidates:
                    if other.startswith(provider):
                        _cooldown[other] = time.monotonic() + COOLDOWN_SECONDS
            elif _rate_limited(exc) or _blocked(exc):
                _cooldown[label] = time.monotonic() + COOLDOWN_SECONDS
            log.warning("llm_provider_failed", provider=label, error=str(exc)[:300])
            errors.append(f"{label}: {type(exc).__name__}")
            continue
        if accept is None or accept(result):
            return result
        log.info("llm_answer_rejected", provider=label)
        rejected = rejected or result
        rejected_models.add(label.split("#")[0])
    if rejected is not None:
        return rejected
    if candidates and all(_cooldown.get(label, 0) > now for label, _ in candidates):
        _cooldown.clear()  # everything is cooling down: give them all another chance next time
    raise LLMUnavailable("; ".join(errors) or "No LLM provider configured")


def _flatten(content) -> str:
    parts = []
    for p in content or []:
        if isinstance(p, str):
            parts.append(p)
        elif isinstance(p, dict) and p.get("type") == "text":
            parts.append(p.get("text", ""))
    return "".join(parts)


def parse_json(text: str) -> dict:
    """Tolerant JSON extraction (handles code fences and leading prose)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()  # reasoning models (Qwen) emit these
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


STYLE = ("\nWrite plain text for a web page: no markdown (no **, #, backticks or tables) and no em or en dashes. "
         "Use short sentences or '- ' bullets.")
_DASHES = "\u2014\u2013"  # em dash, en dash


def plain_text(text: str | None) -> str:
    """Make model-written text safe to show as plain text: strip markdown emphasis/headings and dashes."""
    t = text or ""
    t = re.sub(r"(\*\*|__|`)", "", t)
    t = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", t)
    t = re.sub(rf"\s+[{_DASHES}]\s+", ", ", t)
    t = re.sub(rf"[{_DASHES}]", "-", t)
    return t.strip()


async def complete_text(system: str, user: str) -> LLMResult:
    from langchain_core.messages import HumanMessage, SystemMessage

    result = await invoke([SystemMessage(system + STYLE), HumanMessage(user)], kind="text")
    result.content = plain_text(result.content)
    return result
