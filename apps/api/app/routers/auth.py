from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import DEMO_USERS, current_user, demo_only, login, signup
from app.db.models import User
from app.db.session import get_session

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _user(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role}


class LoginIn(BaseModel):
    email: str
    password: str


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str = Field(min_length=2, max_length=100)


class DemoIn(BaseModel):
    role: Literal["merchant", "operator", "admin"]


@router.post("/login")
async def do_login(body: LoginIn, s: AsyncSession = Depends(get_session)):
    result = await login(s, body.email, body.password)
    if result is None:
        raise HTTPException(401, "Incorrect email or password")
    token, user = result
    return {"access_token": token, "user": _user(user)}


@router.post("/signup")
async def do_signup(body: SignupIn, s: AsyncSession = Depends(get_session)):
    token, user = await signup(s, body.email, body.password, body.name)
    return {"access_token": token, "user": _user(user)}


@router.post("/demo", dependencies=[Depends(demo_only)])
async def demo_login(body: DemoIn, s: AsyncSession = Depends(get_session)):
    """One-click sign-in to the seeded demo accounts (reviewers don't need to type passwords)."""
    email = next(d["email"] for d in DEMO_USERS if d["role"] == body.role)
    result = await login(s, email, settings.demo_password)
    if result is None:
        raise HTTPException(503, "Demo accounts are not ready yet, try again in a moment")
    token, user = result
    return {"access_token": token, "user": _user(user)}


@router.get("/me")
async def me(user: User = Depends(current_user)):
    return _user(user)
