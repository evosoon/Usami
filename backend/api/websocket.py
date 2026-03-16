"""
Usami — WebSocket Handler
实时通信: Agent 执行状态推送 + HiTL 交互
"""

from __future__ import annotations

import asyncio
import json

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.auth import decode_token

logger = structlog.get_logger()

router = APIRouter()


class ConnectionManager:
    """WebSocket 连接管理"""

    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        logger.info("ws_connected", client_id=client_id)

    def disconnect(self, client_id: str):
        self.active_connections.pop(client_id, None)
        logger.info("ws_disconnected", client_id=client_id)

    async def send_event(self, client_id: str, event: dict):
        """发送事件给指定客户端"""
        ws = self.active_connections.get(client_id)
        if ws:
            await ws.send_json(event)

    async def broadcast(self, event: dict):
        """广播事件给所有连接"""
        for cid, ws in self.active_connections.items():
            try:
                await ws.send_json(event)
            except Exception as e:
                logger.warning("ws_send_failed", client_id=cid, error=str(e))


@router.websocket("/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """
    WebSocket 主端点

    Event Types (Server → Client):
    - task.created, task.planning, task.plan_ready
    - task.executing, task.progress, task.completed, task.failed
    - hitl.request, hitl.resolved

    Event Types (Client → Server):
    - hitl.response: 用户回应 HiTL 请求
    - task.cancel: 取消任务
    """
    manager = websocket.app.state.ws_manager

    # Validate JWT token from query params
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing authentication token")
        return
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            await websocket.close(code=4001, reason="Invalid token type")
            return
    except Exception:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    await manager.connect(websocket, client_id)

    try:
        while True:
            data = await websocket.receive_text()
            event = json.loads(data)
            event_type = event.get("type", "")

            if event_type == "hitl.response":
                # 用户回应 HiTL — 记录决定 + 恢复 Graph 执行
                request_id = event.get("request_id", "")
                decision = event.get("decision", "")
                feedback = event.get("feedback", "")
                thread_id = event.get("thread_id")

                logger.info(
                    "hitl_response_received",
                    client_id=client_id,
                    request_id=request_id,
                )

                hitl_gateway = websocket.app.state.hitl_gateway
                hitl_gateway.record_response(
                    request_id=request_id,
                    decision=decision,
                    feedback=feedback,
                )

                if thread_id:
                    boss_graph = websocket.app.state.boss_graph
                    config = {"configurable": {"thread_id": thread_id}}
                    await boss_graph.aupdate_state(config, {
                        "hitl_pending": [],
                        "current_phase": "executing",
                    })

                    async def _resume(graph=boss_graph, cfg=config):
                        try:
                            await graph.ainvoke(None, config=cfg)
                        except Exception as e:
                            logger.error("ws_hitl_resume_failed", error=str(e))

                    _task = asyncio.create_task(_resume())  # noqa: RUF006

            elif event_type == "task.cancel":
                thread_id = event.get("thread_id")
                logger.info("task_cancel_requested", thread_id=thread_id)
                # 取消后台任务
                if thread_id:
                    active = websocket.app.state.active_tasks.get(thread_id)
                    if active and not active.done():
                        active.cancel()

            else:
                logger.warning("unknown_ws_event", type=event_type)

    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception as e:
        logger.error("ws_error", error=str(e))
        manager.disconnect(client_id)
