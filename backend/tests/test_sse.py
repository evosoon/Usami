"""
Usami — SSE Format Helpers Tests (v2)

v2 架构: SSE 连接管理由 pg_notify 端点处理，此处仅测试 SSE 格式化函数。
"""

from __future__ import annotations

import pytest

from api.sse import SSEConnectionManager, format_sse_persistent, format_keepalive


# ============================================
# SSEConnectionManager (minimal stub)
# ============================================

def test_sse_manager_active_connections():
    """SSEConnectionManager 返回 active_connections 属性"""
    manager = SSEConnectionManager()
    assert manager.active_connections == 0


# ============================================
# SSE Format Helpers
# ============================================

def test_format_sse_persistent():
    """Test format_sse_persistent helper with raw parameters (v2 API)."""
    result = format_sse_persistent(1, "task.created", '{"intent": "test"}')
    assert "id: 1\n" in result
    assert "event: task.created\n" in result
    assert "data: " in result
    assert result.endswith("\n\n")


def test_format_keepalive():
    result = format_keepalive()
    assert result == ": keepalive\n\n"
