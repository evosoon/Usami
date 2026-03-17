"""
Usami — Push Notification Utility
Web Push via pywebpush for browser push notifications
"""
from __future__ import annotations

import json

import structlog
from pywebpush import WebPushException, webpush
from sqlalchemy import select

from core.memory import PushSubscription, get_session

logger = structlog.get_logger()

# Module-level VAPID config — set once during startup via init_push()
_vapid_public_key: str = ""
_vapid_private_key: str = ""
_vapid_mailto: str = ""


def init_push(config) -> None:
    """Initialize push notification module from AppConfig."""
    global _vapid_public_key, _vapid_private_key, _vapid_mailto
    _vapid_public_key = config.vapid_public_key
    _vapid_private_key = config.vapid_private_key
    _vapid_mailto = config.vapid_mailto


def get_vapid_public_key() -> str:
    return _vapid_public_key


async def send_push(user_id: str, title: str, body: str, url: str = "/chat") -> None:
    """Send push notification to all of a user's subscribed devices."""
    if not _vapid_private_key:
        return

    async with get_session() as session:
        result = await session.execute(
            select(PushSubscription).where(PushSubscription.user_id == user_id)
        )
        subscriptions = result.scalars().all()

    payload = json.dumps({"title": title, "body": body, "url": url})

    for sub in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth_key},
                },
                data=payload,
                vapid_private_key=_vapid_private_key,
                vapid_claims={"sub": _vapid_mailto},
            )
        except WebPushException as e:
            logger.warning("push_failed", user_id=user_id, endpoint=sub.endpoint, error=str(e))
            # Remove expired/invalid subscriptions (410 Gone)
            if e.response and e.response.status_code == 410:
                async with get_session() as del_session:
                    await del_session.delete(sub)
                    await del_session.commit()
