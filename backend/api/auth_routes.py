"""
Usami — Auth API Routes
Login, refresh, logout endpoints
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Response
from fastapi.requests import Request
from pydantic import BaseModel
from sqlalchemy import select

from core.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from core.memory import User, get_session
from core.state import UserProfile, UserRole

logger = structlog.get_logger()

router = APIRouter()


# ============================================
# Request / Response Models
# ============================================

class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    user: UserProfile


# ============================================
# Routes
# ============================================

@router.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest, response: Response):
    """Authenticate user with email and password."""
    session = get_session()
    try:
        result = await session.execute(select(User).where(User.email == req.email))
        user = result.scalar_one_or_none()
    finally:
        await session.close()

    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账户已被禁用")

    access_token = create_access_token(user.id, user.role)
    refresh_token = create_refresh_token(user.id)

    # Set refresh token as httpOnly cookie
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="lax",
        max_age=7 * 24 * 3600,  # 7 days
        path="/api/v1/auth",
    )

    # Also set access token as cookie for Next.js middleware
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=False,  # Readable by Next.js middleware
        samesite="lax",
        max_age=15 * 60,  # 15 minutes
        path="/",
    )

    profile = UserProfile(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=UserRole(user.role),
        is_active=user.is_active,
    )

    logger.info("user_login", email=user.email)
    return LoginResponse(access_token=access_token, user=profile)


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

    session = get_session()
    try:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
    finally:
        await session.close()

    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用")

    access_token = create_access_token(user.id, user.role)

    # Update access token cookie
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=False,
        samesite="lax",
        max_age=15 * 60,
        path="/",
    )

    profile = UserProfile(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=UserRole(user.role),
        is_active=user.is_active,
    )

    return {"access_token": access_token, "user": profile.model_dump()}


@router.post("/auth/logout")
async def logout(response: Response):
    """Clear auth cookies."""
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/api/v1/auth")
    return {"status": "ok"}
