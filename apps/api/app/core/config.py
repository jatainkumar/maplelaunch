"""Runtime configuration. Every value comes from environment variables (see .env.example)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

API_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(API_ROOT / ".env", API_ROOT.parents[1] / ".env"), extra="ignore")

    env: str = "local"  # local | production (deployment environment)
    # Product mode. "demo" adds one-click demo accounts, synthetic sample documents, the scenario lab and a reset
    # button for reviewers. "production" removes all of that: no demo routes, no seeded accounts, strict secrets.
    app_mode: str = "demo"
    # Production only: the first admin account, created on startup if it does not exist.
    admin_email: str = ""
    admin_password: str = ""
    public_api_url: str = "http://localhost:8000"  # where providers send webhooks
    web_origin: str = "http://localhost:3000"  # CORS; comma-separated list allowed

    database_url: str = "postgresql://maplelaunch:maplelaunch@localhost:5433/maplelaunch"

    # Auth: "local" (built-in users, HS256 tokens) or "supabase"
    auth_mode: str = "local"
    app_secret: str = "dev-only-change-me-dev-only-change-me"
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""  # only for legacy HS256 projects
    demo_password: str = "MapleLaunch@2026"

    # Storage: "local" or "supabase"
    storage_mode: str = "local"
    storage_bucket: str = "documents"
    local_storage_dir: str = str(API_ROOT / ".data" / "documents")

    # PII protection (base64-encoded 32-byte keys). Dev defaults are derived from app_secret.
    encryption_key: str = ""
    blind_index_key: str = ""

    # LLMs
    gemini_api_key: str = ""
    # Each Gemini model has its own free daily quota, so several are tried in order.
    gemini_models: str = "gemini-3.5-flash-lite,gemini-3.8-flash,gemini-2.5-flash"
    groq_api_key: str = ""
    groq_api_keys: str = ""  # optional extra keys (comma-separated), used in turn when one is rate-limited
    groq_vision_model: str = "qwen/qwen3.8-27b"
    groq_text_model: str = "openai/gpt-oss-120b"
    llm_timeout_seconds: float = 45.0
    llm_order: str = "groq,gemini"  # provider order; the next one is used on errors, rate limits or bad reads

    # Mock providers
    providers_base_url: str = "http://localhost:8001"
    webhook_secret: str = "dev-webhook-secret"
    provider_admin_token: str = "dev-provider-admin-token"

    # Email (Resend). Empty key = in-app inbox only.
    resend_api_key: str = ""
    email_from: str = "MapleLaunch <onboarding@resend.dev>"

    # Worker
    worker_enabled: bool = True
    worker_poll_seconds: float = 1.0
    worker_concurrency: int = 4

    @property
    def is_demo(self) -> bool:
        return self.app_mode != "production"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.web_origin.split(",") if o.strip()]

    @property
    def groq_keys(self) -> list[str]:
        keys = [self.groq_api_key, *self.groq_api_keys.split(",")]
        return list(dict.fromkeys(k.strip() for k in keys if k and k.strip()))

    @property
    def llm_enabled(self) -> bool:
        return bool(self.gemini_api_key or self.groq_keys)

    @property
    def psycopg_url(self) -> str:
        """Plain libpq URL (used by psycopg / LangGraph checkpointer)."""
        url = self.database_url
        for prefix in ("postgresql+psycopg://", "postgres://"):
            if url.startswith(prefix):
                url = "postgresql://" + url[len(prefix):]
        return url

    @property
    def sqlalchemy_url(self) -> str:
        return self.psycopg_url.replace("postgresql://", "postgresql+psycopg://", 1)


DEV_DEFAULTS = {
    "app_secret": "dev-only-change-me-dev-only-change-me",
    "webhook_secret": "dev-webhook-secret",
    "provider_admin_token": "dev-provider-admin-token",
}


def production_problems(s: "Settings") -> list[str]:
    """Production mode refuses to start with development secrets or missing keys."""
    problems = [f"{k.upper()} is still the development default" for k, v in DEV_DEFAULTS.items()
                if getattr(s, k) == v]
    problems += [f"{k.upper()} must be set" for k in ("encryption_key", "blind_index_key") if not getattr(s, k)]
    if s.database_url.startswith("postgresql://maplelaunch:maplelaunch@localhost"):
        problems.append("DATABASE_URL points at the local development database")
    return problems


def supabase_problems(s: "Settings") -> list[str]:
    """When Supabase handles auth or storage, its URL and keys must be present (and the right kind of key)."""
    if "supabase" not in (s.auth_mode, s.storage_mode):
        return []
    problems = []
    if not s.supabase_url.startswith("https://"):
        problems.append("SUPABASE_URL must be your project URL, e.g. https://<ref>.supabase.co")
    if s.auth_mode == "supabase" and not s.supabase_anon_key:
        problems.append("SUPABASE_ANON_KEY is empty (Supabase -> Project Settings -> API Keys -> publishable key)")
    service = s.supabase_service_role_key
    if not service:
        problems.append("SUPABASE_SERVICE_ROLE_KEY is empty (Supabase -> Project Settings -> API Keys -> secret key, "
                        "sb_secret_...)")
    elif service.startswith("sb_publishable_") or service == s.supabase_anon_key:
        problems.append("SUPABASE_SERVICE_ROLE_KEY is the publishable key; it must be the secret key (sb_secret_...)")
    return problems


def database_url_problem(url: str) -> str | None:
    """Catch the usual copy-paste mistakes in DATABASE_URL before they surface as a DNS error."""
    if any(p in url for p in ("<", ">", "[YOUR-PASSWORD]", "YOUR-PASSWORD")):
        return ("DATABASE_URL still contains a placeholder such as <region> or [YOUR-PASSWORD]. Copy the full URI from "
                "Supabase -> Connect -> Session pooler and put in your real database password.")
    rest = url.split("://", 1)[-1].split("/", 1)[0]
    if rest.count("@") > 1:
        return ("DATABASE_URL has more than one '@' before the host. If your database password contains '@', write "
                "it as %40 (and '#' as %23, '/' as %2F, '%' as %25).")
    return None


def _with_scheme(url: str) -> str:
    """Render's fromService 'host' gives a bare hostname; add https:// (http:// for localhost)."""
    out = []
    for part in url.split(","):
        part = part.strip().rstrip("/")
        if part and "://" not in part:
            part = ("http://" if part.startswith(("localhost", "127.")) else "https://") + part
        out.append(part)
    return ",".join(out)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.public_api_url = _with_scheme(s.public_api_url)
    s.providers_base_url = _with_scheme(s.providers_base_url)
    s.web_origin = _with_scheme(s.web_origin)
    if s.database_url == "pgserver":
        from app.core.devdb import resolve

        try:
            s.database_url = resolve(s.database_url)
        except ImportError as exc:  # pgserver is a dev-only dependency
            raise RuntimeError(
                "DATABASE_URL is 'pgserver' (or missing), which only works for local development. Set it to the "
                "Supabase Session pooler URL (port 5432).") from exc
    elif problem := database_url_problem(s.database_url):
        raise RuntimeError(problem)

    return s
