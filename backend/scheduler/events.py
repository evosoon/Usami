"""
Usami — Event Bus
Redis Pub/Sub 事件驱动触发

MVP: Webhook → Redis Pub/Sub → Agent 唤醒
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

logger = structlog.get_logger()


class EventBus:
    """
    事件总线 — Redis Pub/Sub

    外部事件 (Webhook) → 发布到 Redis → 订阅者匹配规则 → 唤醒 Agent
    """

    def __init__(self, redis_client):
        self._redis = redis_client
        self._handlers: dict[str, list[Callable]] = {}

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        """发布事件"""
        message = json.dumps({
            "type": event_type,
            "payload": payload,
        })
        await self._redis.publish(f"agenticOS:events:{event_type}", message)
        logger.info("event_published", type=event_type)

    def subscribe(self, event_type: str, handler: Callable[..., Awaitable]) -> None:
        """订阅事件"""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        logger.info("event_subscribed", type=event_type)

    async def start_listening(self) -> None:
        """开始监听 Redis Pub/Sub"""
        pubsub = self._redis.pubsub()

        for event_type in self._handlers:
            await pubsub.subscribe(f"agenticOS:events:{event_type}")

        logger.info("event_bus_listening", channels=list(self._handlers.keys()))

        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    event_type = data.get("type", "")
                    handlers = self._handlers.get(event_type, [])

                    for handler in handlers:
                        await handler(data.get("payload", {}))

                except Exception as e:
                    logger.error("event_handling_failed", error=str(e))
