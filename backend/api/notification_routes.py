"""
Usami — Notification API Routes
Push subscription management endpoints
"""
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from core.auth import get_current_user
from core.memory import PushSubscription, get_session
from core.push import get_vapid_public_key
from core.state import UserProfile

logger = structlog.get_logger()

router = APIRouter()


class SubscribeRequest(BaseModel):
    endpoint: str
    p256dh: str
    auth: str


class UnsubscribeRequest(BaseModel):
    endpoint: str


@router.get("/notifications/vapid-public-key")
async def vapid_public_key():
    """Return VAPID public key for push subscription."""
    key = get_vapid_public_key()
    if not key:
        raise HTTPException(status_code=503, detail="推送通知未配置")
    return {"vapid_public_key": key}


@router.post("/notifications/subscribe")
async def subscribe_push(
    req: SubscribeRequest,
    user: UserProfile = Depends(get_current_user),
):
    """Save push subscription for the current user."""
    async with get_session() as session:
        # Check if subscription already exists
        result = await session.execute(
            select(PushSubscription).where(PushSubscription.endpoint == req.endpoint)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return {"status": "already_subscribed"}

        sub = PushSubscription(
            id=f"push_{uuid.uuid4().hex[:12]}",
            user_id=user.id,
            endpoint=req.endpoint,
            p256dh=req.p256dh,
            auth_key=req.auth,
        )
        session.add(sub)
        await session.commit()
        logger.info("push_subscribed", user_id=user.id)
        return {"status": "subscribed"}


@router.delete("/notifications/subscribe")
async def unsubscribe_push(
    req: UnsubscribeRequest,
    user: UserProfile = Depends(get_current_user),
):
    """Remove push subscription."""
    async with get_session() as session:
        result = await session.execute(
            select(PushSubscription).where(
                PushSubscription.endpoint == req.endpoint,
                PushSubscription.user_id == user.id,
            )
        )
        sub = result.scalar_one_or_none()
        if sub:
            await session.delete(sub)
            await session.commit()
            logger.info("push_unsubscribed", user_id=user.id)
        return {"status": "unsubscribed"}
