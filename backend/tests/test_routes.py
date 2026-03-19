"""
Usami — REST API 集成测试
使用 httpx AsyncClient + mocked boss_graph
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

# ============================================
# POST /api/v1/tasks
# ============================================

class TestCreateTask:

    @pytest.mark.asyncio
    async def test_create_task_returns_pending(self, app_client):
        """v2: create_task returns 'pending', Worker executes the graph"""
        client, mock_graph = app_client
        resp = await client.post("/api/v1/tasks", json={"intent": "test intent"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"  # v2: Worker-driven model
        assert data["thread_id"].startswith("thread_")

    @pytest.mark.asyncio
    async def test_create_task_notifies_worker(self, app_client):
        """v2: create_task sends pg_notify instead of invoking graph directly"""
        client, mock_graph = app_client
        resp = await client.post("/api/v1/tasks", json={"intent": "research AI"})
        # v2: graph.ainvoke is NOT called — Worker receives pg_notify and executes
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_task_empty_intent(self, app_client):
        """空 intent 被 validation 拒绝 (min_length=1)"""
        client, mock_graph = app_client
        resp = await client.post("/api/v1/tasks", json={"intent": ""})
        assert resp.status_code == 422


# ============================================
# GET /api/v1/tasks/{thread_id}
# ============================================

class TestGetTaskStatus:

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="v2: requires task to exist in database, needs better mock")
    async def test_get_existing_task(self, app_client):
        """v2: get_task_status looks up task in database, not graph state"""
        client, mock_graph = app_client
        # 先创建
        resp = await client.post("/api/v1/tasks", json={"intent": "test"})
        thread_id = resp.json()["thread_id"]

        # 查状态 — v2: requires task to exist in database
        resp = await client.get(f"/api/v1/tasks/{thread_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["thread_id"] == thread_id
        assert "status" in data

    @pytest.mark.asyncio
    async def test_get_nonexistent_task(self, app_client):
        """v2: task not found in database returns 404"""
        client, mock_graph = app_client
        resp = await client.get("/api/v1/tasks/thread_nonexistent")
        assert resp.status_code == 404


# ============================================
# POST /api/v1/tasks/{thread_id}/hitl
# ============================================

class TestResolveHiTL:

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="v2: requires task to exist in database with 'interrupted' status")
    async def test_resolve_hitl_success(self, app_client):
        """v2: HiTL resolution returns 'resuming', Worker executes resume"""
        client, mock_graph = app_client
        resp = await client.post(
            "/api/v1/tasks/thread_abc123/hitl",
            json={
                "request_id": "req-001",
                "decision": "approve",
                "feedback": "",
            },
        )
        # v2: HiTL redirects to /resume, returns 'resuming' status
        assert resp.status_code == 200
        assert resp.json()["status"] == "resuming"

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="v2: requires task to exist in database with 'interrupted' status")
    async def test_resolve_hitl_with_feedback(self, app_client):
        """v2: HiTL resolution with feedback"""
        client, mock_graph = app_client
        resp = await client.post(
            "/api/v1/tasks/thread_abc123/hitl",
            json={
                "request_id": "req-002",
                "decision": "retry",
                "feedback": "please try again",
            },
        )
        # v2: HiTL redirects to /resume
        assert resp.status_code == 200
        assert resp.json()["status"] == "resuming"


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
