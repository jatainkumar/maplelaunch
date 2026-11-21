"""Authentication & roles.

AUTH_MODE=supabase: Supabase Auth issues the access tokens (verified via JWKS, or the legacy HS256 secret); our
`users` table holds the role profile. AUTH_MODE=local: built-in users with scrypt password hashes and HS256 tokens,
so the project runs fully offline. The frontend talks to /auth/* either way."""

import base64
import hashlib
import hmac
import os
import time
from functools import lru_cache

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import User
from app.db.session import ReadSession, get_session

settings = get_settings()
bearer = HTTPBearer(auto_error=False)

DEMO_USERS = [
    {"email": "merchant@example.com", "name": "Demo Merchant", "role": "merchant"},
    {"email": "operator@example.com", "name": "Asha (Onboarding Ops)", "role": "operator"},
    {"email": "admin@example.com", "name": "Admin", "role": "admin"},
]


# ---------------------------------------------------------------- local mode -------------------------------------
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        return False
    _, salt_b64, dk_b64 = stored.split("$")
    dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), n=2**14, r=8, p=1)
    return hmac.compare_digest(dk, base64.b64decode(dk_b64))


def issue_local_token(user: User) -> str:
    now = int(time.time())
    return jwt.encode({"sub": user.id, "email": user.email, "role": user.role, "iat": now, "exp": now + 12 * 3600,
                       "iss": "maplelaunch-local"}, settings.app_secret, algorithm="HS256")


# ---------------------------------------------------------------- supabase mode ----------------------------------
@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json", cache_keys=True)


def _decode_supabase(token: str) -> dict:
    alg = jwt.get_unverified_header(token).get("alg")
    if alg == "HS256":
        return jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated")
    key = _jwks_client().get_signing_key_from_jwt(token).key
    return jwt.decode(token, key, algorithms=[alg], audience="authenticated")


def _sb_headers(service: bool = False) -> dict:
    key = settings.supabase_service_role_key if service else settings.supabase_anon_key
    return {"apikey": key, "Authorization": f"Bearer {key}"}


async def supabase_password_login(email: str, password: str) -> dict | None:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{settings.supabase_url.rstrip('/')}/auth/v1/token?grant_type=password",
                         headers=_sb_headers(), json={"email": email, "password": password})
    return r.json() if r.status_code == 200 else None


async def supabase_create_user(email: str, password: str, name: str) -> str | None:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{settings.supabase_url.rstrip('/')}/auth/v1/admin/users", headers=_sb_headers(True),
                         json={"email": email, "password": password, "email_confirm": True,
                               "user_metadata": {"name": name}})
    if r.status_code in (200, 201):
        return r.json()["id"]
    return None


# ---------------------------------------------------------------- shared -----------------------------------------
async def login(session: AsyncSession, email: str, password: str) -> tuple[str, User] | None:
    email = email.strip().lower()
    if settings.auth_mode == "supabase":
        data = await supabase_password_login(email, password)
        if not data:
            return None
        uid = data["user"]["id"]
        user = await session.get(User, uid)
        if user is None:
            user = User(id=uid, email=email, name=(data["user"].get("user_metadata") or {}).get("name", ""),
                        role="merchant")
            session.add(user)
            await session.flush()
        return data["access_token"], user
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        return None
    return issue_local_token(user), user


async def signup(session: AsyncSession, email: str, password: str, name: str) -> tuple[str, User]:
    email = email.strip().lower()
    existing = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "An account with this email already exists")
    if settings.auth_mode == "supabase":
        uid = await supabase_create_user(email, password, name)
        if uid is None:
            raise HTTPException(400, "Could not create account (password must be at least 6 characters)")
        session.add(User(id=uid, email=email, name=name, role="merchant"))
        await session.flush()
        result = await login(session, email, password)
        if result is None:
            raise HTTPException(500, "Account created but sign-in failed")
        return result
    user = User(email=email, name=name, role="merchant", password_hash=hash_password(password))
    session.add(user)
    await session.flush()
    return issue_local_token(user), user


def demo_only() -> None:
    """Route dependency: demo helpers do not exist in production mode."""
    if not settings.is_demo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


async def seed_users(session: AsyncSession) -> None:
    """Demo mode: the three one-click demo accounts. Production: only the bootstrap admin from ADMIN_EMAIL."""
    if settings.is_demo:
        await _ensure_users(session, DEMO_USERS, settings.demo_password)
    elif settings.admin_email and settings.admin_password:
        await _ensure_users(session, [{"email": settings.admin_email.lower(), "name": "Administrator",
                                       "role": "admin"}], settings.admin_password)


async def _ensure_users(session: AsyncSession, users: list[dict], password: str) -> None:
    for d in users:
        user = (await session.execute(select(User).where(User.email == d["email"]))).scalar_one_or_none()
        if user is not None:
            if user.role != d["role"]:
                user.role = d["role"]
            continue
        if settings.auth_mode == "supabase":
            uid = await supabase_create_user(d["email"], password, d["name"])
            if uid is None:  # already exists in Supabase: sign in to learn the id
                data = await supabase_password_login(d["email"], password)
                uid = data["user"]["id"] if data else None
            if uid:
                session.add(User(id=uid, email=d["email"], name=d["name"], role=d["role"]))
        else:
            session.add(User(email=d["email"], name=d["name"], role=d["role"],
                             password_hash=hash_password(password)))
    await session.flush()


# Signed-in users are looked up once a minute at most; roles change rarely and every lookup is a database round trip.
USER_CACHE_SECONDS = 60
_user_cache: dict[str, tuple[User, float]] = {}


async def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                       session: AsyncSession = Depends(get_session)) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    try:
        if settings.auth_mode == "supabase":
            claims = _decode_supabase(creds.credentials)
        else:
            claims = jwt.decode(creds.credentials, settings.app_secret, algorithms=["HS256"], issuer="maplelaunch-local")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, please sign in again") from None
    cached = _user_cache.get(claims["sub"])
    if cached and cached[1] > time.monotonic():
        return cached[0]
    async with ReadSession() as rs:  # autocommit lookup: one round trip, no transaction
        user = await rs.get(User, claims["sub"])
    if user is not None:
        _user_cache[claims["sub"]] = (user, time.monotonic() + USER_CACHE_SECONDS)
        return user
    if user is None:
        if settings.auth_mode != "supabase":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
        user = User(id=claims["sub"], email=claims.get("email", ""), role="merchant")
        session.add(user)
        await session.flush()
    return user


def require_role(*roles: str):
    async def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have access to this area")
        return user

    return dep


def actor(user: User) -> str:
    return f"{user.role}:{user.email}"
