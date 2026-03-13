"""
Usami — WebSocket 单元测试
测试 ConnectionManager + WebSocket 事件处理
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from api.websocket import ConnectionManager


# ============================================
# ConnectionManager 测试
# ============================================

@pytest.mark.asyncio
async def test_connection_manager_connect():
    """测试连接管理"""
    manager = ConnectionManager()
    mock_ws = AsyncMock()

    await manager.connect(mock_ws, "client_1")

    assert "client_1" in manager.active_connections
    assert manager.active_connections["client_1"] == mock_ws
    mock_ws.accept.assert_called_once()


def test_connection_manager_disconnect():
    """测试断开连接"""
    manager = ConnectionManager()
    mock_ws = MagicMock()
    manager.active_connections["client_1"] = mock_ws

    manager.disconnect("client_1")

    assert "client_1" not in manager.active_connections


def test_connection_manager_disconnect_nonexistent():
    """测试断开不存在的连接（不应报错）"""
    manager = ConnectionManager()

    manager.disconnect("nonexistent_client")

    assert "nonexistent_client" not in manager.active_connections


@pytest.mark.asyncio
async def test_send_event_to_existing_client():
    """测试向已连接客户端发送事件"""
    manager = ConnectionManager()
    mock_ws = AsyncMock()
    manager.active_connections["client_1"] = mock_ws

    event = {"type": "task.created", "thread_id": "test_123"}
    await manager.send_event("client_1", event)

    mock_ws.send_json.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_send_event_to_nonexistent_client():
    """测试向不存在的客户端发送事件（不应报错）"""
    manager = ConnectionManager()

    event = {"type": "task.created", "thread_id": "test_123"}
    await manager.send_event("nonexistent_client", event)

    # 不应抛出异常


@pytest.mark.asyncio
async def test_broadcast_to_multiple_clients():
    """测试广播事件给所有客户端"""
    manager = ConnectionManager()
    mock_ws1 = AsyncMock()
    mock_ws2 = AsyncMock()
    manager.active_connections["client_1"] = mock_ws1
    manager.active_connections["client_2"] = mock_ws2

    event = {"type": "task.completed", "thread_id": "test_123"}
    await manager.broadcast(event)

    mock_ws1.send_json.assert_called_once_with(event)
    mock_ws2.send_json.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_broadcast_handles_send_failure():
    """测试广播时某个客户端发送失败不影响其他客户端"""
    manager = ConnectionManager()
    mock_ws1 = AsyncMock()
    mock_ws2 = AsyncMock()
    mock_ws1.send_json.side_effect = Exception("Connection lost")
    manager.active_connections["client_1"] = mock_ws1
    manager.active_connections["client_2"] = mock_ws2

    event = {"type": "task.completed", "thread_id": "test_123"}
    await manager.broadcast(event)

    # ws1 失败但 ws2 应该成功
    mock_ws2.send_json.assert_called_once_with(event)
