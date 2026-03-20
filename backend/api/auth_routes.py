"""
Usami — Auth API Routes
Login, refresh, logout endpoints
"""
from __future__ import annotations

import os

import structlog
from fastapi import APIRouter, HTTPException, Response
from fastapi.requests import Request
from pydantic import BaseModel
from sqlalchemy import select

from core.auth import (
    blacklist_token,
    create_access_token,
    create_refresh_token,
    decode_token,
    decode_token_unsafe,
    hash_password,
    verify_password,
)
from core.memory import User, get_session
from core.state import UserProfile, UserRole

logger = structlog.get_logger()

router = APIRouter()

_IS_PRODUCTION = os.environ.get("APP_ENV", "development") != "development"
_DUMMY_HASH = hash_password("__timing_safe_dummy__")


# ============================================
# Request / Response Models
# ============================================

class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    user: UserProfile


# ============================================
# Routes
# ============================================

@router.post("/auth/login", response_model=LoginResponse)
async def login(request: Request, response: Response, req: LoginRequest):
    """Authenticate user with email and password."""
    async with get_session() as session:
        result = await session.execute(select(User).where(User.email == req.email))
        user = result.scalar_one_or_none()

    # Constant-time comparison: always run verify_password even if user is None
    if not user:
        verify_password(req.password, _DUMMY_HASH)
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    if not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账户已被禁用")

    access_token = create_access_token(user.id, user.role)
    refresh_token = create_refresh_token(user.id)

    # Set access token as httpOnly cookie (7d, aligned with refresh token lifecycle).
    # Cookie outlives JWT expiry intentionally — middleware only checks cookie presence,
    # backend validates JWT signature + expiry. Expired JWT triggers auto-refresh via
    # api-client 401 interceptor.
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=_IS_PRODUCTION,
        samesite="lax",
        max_age=7 * 24 * 3600,  # 7 days (matches refresh token lifecycle)
        path="/",
    )

    # Set refresh token as httpOnly cookie (7d)
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=_IS_PRODUCTION,
        samesite="lax",
        max_age=7 * 24 * 3600,  # 7 days
        path="/api/v1/auth",
    )

    profile = UserProfile(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=UserRole(user.role),
        is_active=user.is_active,
    )

    logger.info("user_login", email=user.email)
    return LoginResponse(user=profile)


@router.post("/auth/refresh")
async def refresh(request: Request, response: Response):
    """Refresh access token using refresh token cookie."""
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="未提供刷新令牌")

    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="无效的令牌类型")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="无效的令牌")

    async with get_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用")

    access_token = create_access_token(user.id, user.role)
    new_refresh_token = create_refresh_token(user.id)

    # Update access token cookie (7d, aligned with refresh token lifecycle)
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=_IS_PRODUCTION,
        samesite="lax",
        max_age=7 * 24 * 3600,  # 7 days (matches refresh token lifecycle)
        path="/",
    )

    # Rotate refresh token (7d)
    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=_IS_PRODUCTION,
        samesite="lax",
        max_age=7 * 24 * 3600,  # 7 days
        path="/api/v1/auth",
    )

    profile = UserProfile(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=UserRole(user.role),
        is_active=user.is_active,
    )

    return {"user": profile.model_dump()}


@router.post("/auth/logout")
async def logout(request: Request, response: Response):
    """Clear auth cookies and blacklist access token."""
    # Blacklist the current access token so it can't be reused
    access_token = request.cookies.get("access_token")
    if access_token:
        payload = decode_token_unsafe(access_token)
        if payload:
            redis_client = getattr(request.app.state, "redis_client", None)
            if redis_client:
                await blacklist_token(redis_client, payload)

    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/api/v1/auth")
    return {"status": "ok"}
