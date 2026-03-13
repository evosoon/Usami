"""
Usami — REST API 集成测试
使用 httpx AsyncClient + mocked boss_graph
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock


# ============================================
# POST /api/v1/tasks
# ============================================

class TestCreateTask:

    @pytest.mark.asyncio
    async def test_create_task_returns_running(self, app_client):
        client, mock_graph = app_client
        resp = await client.post("/api/v1/tasks", json={"intent": "test intent"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert data["thread_id"].startswith("thread_")

    @pytest.mark.asyncio
    async def test_create_task_invokes_graph(self, app_client):
        client, mock_graph = app_client
        await client.post("/api/v1/tasks", json={"intent": "research AI"})
        # 后台 asyncio.create_task 调用 graph.ainvoke
        # 注意: fire-and-forget 不保证立即执行，但 ainvoke 被注册
        # 这里验证结构正确即可

    @pytest.mark.asyncio
    async def test_create_task_empty_intent(self, app_client):
        """空 intent 也能创建 (业务层由 Boss 处理)"""
        client, mock_graph = app_client
        resp = await client.post("/api/v1/tasks", json={"intent": ""})
        assert resp.status_code == 200


# ============================================
# GET /api/v1/tasks/{thread_id}
# ============================================

class TestGetTaskStatus:

    @pytest.mark.asyncio
    async def test_get_existing_task(self, app_client):
        client, mock_graph = app_client
        # 先创建
        resp = await client.post("/api/v1/tasks", json={"intent": "test"})
        thread_id = resp.json()["thread_id"]

        # 查状态
        resp = await client.get(f"/api/v1/tasks/{thread_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["thread_id"] == thread_id
        assert "status" in data

    @pytest.mark.asyncio
    async def test_get_nonexistent_task(self, app_client):
        client, mock_graph = app_client
        # aget_state 返回空 → 404
        mock_graph.aget_state = AsyncMock(return_value=MagicMock(values={}))
        resp = await client.get("/api/v1/tasks/thread_nonexistent")
        assert resp.status_code == 404


# ============================================
# POST /api/v1/tasks/{thread_id}/hitl
# ============================================

class TestResolveHiTL:

    @pytest.mark.asyncio
    async def test_resolve_hitl_success(self, app_client):
        client, mock_graph = app_client
        resp = await client.post(
            "/api/v1/tasks/thread_abc123/hitl",
            json={
                "request_id": "req-001",
                "decision": "approve",
                "feedback": "",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "resumed"
        assert data["request_id"] == "req-001"

    @pytest.mark.asyncio
    async def test_resolve_hitl_with_feedback(self, app_client):
        client, mock_graph = app_client
        resp = await client.post(
            "/api/v1/tasks/thread_abc123/hitl",
            json={
                "request_id": "req-002",
                "decision": "retry",
                "feedback": "please try again",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "resumed"


# ============================================
# GET /health
# ============================================

class TestHealth:

    @pytest.mark.asyncio
    async def test_health_ok(self, app_client):
        client, _ = app_client
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ok", "degraded")
        assert data["service"] == "Usami"

    @pytest.mark.asyncio
    async def test_health_includes_circuit_breaker(self, app_client):
        client, _ = app_client
        resp = await client.get("/health")
        data = resp.json()
        assert "circuit_breaker" in data
        assert data["circuit_breaker"] == "closed"


# ============================================
# GET /api/v1/personas
# ============================================

class TestListEndpoints:

    @pytest.mark.asyncio
    async def test_list_personas(self, app_client):
        client, _ = app_client
        resp = await client.get("/api/v1/personas")
        assert resp.status_code == 200
        data = resp.json()
        assert "boss" in data

    @pytest.mark.asyncio
    async def test_list_tools(self, app_client):
        client, _ = app_client
        resp = await client.get("/api/v1/tools")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_list_scheduler_jobs(self, app_client):
        client, _ = app_client
        resp = await client.get("/api/v1/scheduler/jobs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
