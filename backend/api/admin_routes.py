"""
Usami — Admin API Routes
User management endpoints (admin only)
"""
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from core.auth import hash_password, require_admin
from core.memory import User, get_session
from core.state import UserProfile, UserRole

logger = structlog.get_logger()

router = APIRouter()


# ============================================
# Request / Response Models
# ============================================

class CreateUserRequest(BaseModel):
    email: str
    password: str
    display_name: str
    role: str = "user"


class UpdateUserRequest(BaseModel):
    display_name: str | None = None
    role: str | None = None
    is_active: bool | None = None


# ============================================
# Routes
# ============================================

@router.get("/admin/users")
async def list_users(_admin: UserProfile = Depends(require_admin)):
    """List all users (admin only)."""
    session = get_session()
    try:
        result = await session.execute(select(User).order_by(User.created_at.desc()))
        users = result.scalars().all()
    finally:
        await session.close()

    return [
        {
            "id": u.id,
            "email": u.email,
            "display_name": u.display_name,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": str(u.created_at) if u.created_at else None,
        }
        for u in users
    ]


@router.post("/admin/users")
async def create_user(req: CreateUserRequest, _admin: UserProfile = Depends(require_admin)):
    """Create a new user (admin only)."""
    session = get_session()
    try:
        # Check if email already exists
        result = await session.execute(select(User).where(User.email == req.email))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="邮箱已被注册")

        user = User(
            id=f"user_{uuid.uuid4().hex[:12]}",
            email=req.email,
            display_name=req.display_name,
            hashed_password=hash_password(req.password),
            role=req.role,
            is_active=True,
        )
        session.add(user)
        await session.commit()

        logger.info("user_created", email=req.email, role=req.role)
        return {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role,
            "is_active": user.is_active,
        }
    finally:
        await session.close()


@router.patch("/admin/users/{user_id}")
async def update_user(
    user_id: str,
    req: UpdateUserRequest,
    _admin: UserProfile = Depends(require_admin),
):
    """Update user role or active status (admin only)."""
    session = get_session()
    try:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        if req.display_name is not None:
            user.display_name = req.display_name
        if req.role is not None:
            if req.role not in (UserRole.ADMIN, UserRole.USER):
                raise HTTPException(status_code=400, detail="无效的角色")
            user.role = req.role
        if req.is_active is not None:
            user.is_active = req.is_active

        await session.commit()

        logger.info("user_updated", user_id=user_id)
        return {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role,
            "is_active": user.is_active,
        }
    finally:
        await session.close()
