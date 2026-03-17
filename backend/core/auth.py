"""
Usami — Authentication
Password hashing, JWT tokens, FastAPI dependencies, admin seeding
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
import structlog
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from core.memory import User, get_session
from core.state import UserProfile, UserRole

logger = structlog.get_logger()

# Module-level config holder — set once during app startup via init_auth().
_jwt_secret: str = ""
_jwt_algorithm: str = "HS256"
_access_token_expire_minutes: int = 15
_refresh_token_expire_days: int = 7
_admin_email: str = ""
_admin_password: str = ""


def init_auth(config) -> None:
    """Initialize auth module from AppConfig. Called once at startup."""
    global _jwt_secret, _access_token_expire_minutes, _refresh_token_expire_days
    global _admin_email, _admin_password
    _jwt_secret = config.jwt_secret
    _access_token_expire_minutes = config.access_token_expire_minutes
    _refresh_token_expire_days = config.refresh_token_expire_days
    _admin_email = config.admin_email
    _admin_password = config.admin_password


# ============================================
# Password Hashing
# ============================================

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


# ============================================
# JWT Tokens
# ============================================

def create_access_token(user_id: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=_access_token_expire_minutes),
    }
    return jwt.encode(payload, _jwt_secret, algorithm=_jwt_algorithm)


def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "type": "refresh",
        "exp": datetime.now(timezone.utc) + timedelta(days=_refresh_token_expire_days),
    }
    return jwt.encode(payload, _jwt_secret, algorithm=_jwt_algorithm)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Raises HTTPException on failure."""
    try:
        return jwt.decode(token, _jwt_secret, algorithms=[_jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="令牌已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效的令牌")


# ============================================
# FastAPI Dependencies
# ============================================

async def get_current_user(request: Request) -> UserProfile:
    """Extract and validate user from Authorization header or access_token cookie."""
    token = None

    # Try Authorization header first
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]

    # Fall back to cookie
    if not token:
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(status_code=401, detail="未提供认证凭证")

    payload = decode_token(token)
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="无效的令牌类型")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="无效的令牌")

    async with get_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账户已被禁用")

    return UserProfile(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=UserRole(user.role),
        is_active=user.is_active,
    )


async def require_admin(user: UserProfile = Depends(get_current_user)) -> UserProfile:
    """Require admin role."""
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


# ============================================
# Admin Seeding
# ============================================

async def seed_admin_user() -> None:
    """Create default admin user from config if not exists."""
    if not _admin_email or not _admin_password:
        logger.warning("admin_seed_skipped", reason="ADMIN_EMAIL or ADMIN_PASSWORD not set")
        return

    async with get_session() as session:
        result = await session.execute(select(User).where(User.email == _admin_email))
        existing = result.scalar_one_or_none()

        if existing:
            logger.info("admin_user_exists", email=_admin_email)
            return

        admin = User(
            id=f"user_{uuid.uuid4().hex[:12]}",
            email=_admin_email,
            display_name="Admin",
            hashed_password=hash_password(_admin_password),
            role="admin",
            is_active=True,
        )
        session.add(admin)
        await session.commit()
        logger.info("admin_user_created", email=_admin_email)
