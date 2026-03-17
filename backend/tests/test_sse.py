"""
Usami — SSE Connection Manager Tests
Tests SSEConnectionManager: connect/disconnect, send_to_user, multi-tab, user isolation.
"""

from __future__ import annotations

import asyncio

import pytest

from api.sse import SSEConnectionManager, format_sse, format_keepalive
from core.state import PersistedEvent


@pytest.fixture
def sse_manager() -> SSEConnectionManager:
    return SSEConnectionManager()


@pytest.fixture
def sample_event() -> PersistedEvent:
    return PersistedEvent(
        id="evt_001",
        thread_id="thread_abc",
        user_id="user_1",
        seq=1,
        event_type="task.created",
        payload={"intent": "test", "thread_id": "thread_abc"},
        created_at="2024-01-01T00:00:00",
    )


# ============================================
# Connect / Disconnect
# ============================================

def test_connect_returns_queue(sse_manager):
    queue = sse_manager.connect("user_1")
    assert isinstance(queue, asyncio.Queue)
    assert sse_manager.active_connections == 1


def test_disconnect_removes_queue(sse_manager):
    queue = sse_manager.connect("user_1")
    sse_manager.disconnect("user_1", queue)
    assert sse_manager.active_connections == 0


def test_disconnect_nonexistent_user(sse_manager):
    queue = asyncio.Queue()
    # Should not raise
    sse_manager.disconnect("nonexistent", queue)
    assert sse_manager.active_connections == 0


# ============================================
# Multi-tab Support
# ============================================

def test_multi_tab_same_user(sse_manager):
    q1 = sse_manager.connect("user_1")
    q2 = sse_manager.connect("user_1")
    assert sse_manager.active_connections == 2


@pytest.mark.asyncio
async def test_multi_tab_both_receive_events(sse_manager, sample_event):
    q1 = sse_manager.connect("user_1")
    q2 = sse_manager.connect("user_1")

    await sse_manager.send_to_user("user_1", sample_event)

    event1 = await asyncio.wait_for(q1.get(), timeout=1)
    event2 = await asyncio.wait_for(q2.get(), timeout=1)
    assert event1.id == "evt_001"
    assert event2.id == "evt_001"


def test_disconnect_one_tab_keeps_other(sse_manager):
    q1 = sse_manager.connect("user_1")
    q2 = sse_manager.connect("user_1")
    sse_manager.disconnect("user_1", q1)
    assert sse_manager.active_connections == 1


# ============================================
# User Isolation
# ============================================

@pytest.mark.asyncio
async def test_user_isolation(sse_manager, sample_event):
    q_user1 = sse_manager.connect("user_1")
    q_user2 = sse_manager.connect("user_2")

    await sse_manager.send_to_user("user_1", sample_event)

    # user_1 should receive the event
    event = await asyncio.wait_for(q_user1.get(), timeout=1)
    assert event.id == "evt_001"

    # user_2 should NOT have any events
    assert q_user2.empty()


@pytest.mark.asyncio
async def test_send_to_nonexistent_user(sse_manager, sample_event):
    # Should not raise
    await sse_manager.send_to_user("nonexistent", sample_event)


# ============================================
# SSE Format Helpers
# ============================================

def test_format_sse(sample_event):
    result = format_sse(sample_event)
    assert "id: evt_001\n" in result
    assert "event: task.created\n" in result
    assert "data: " in result
    assert result.endswith("\n\n")


def test_format_keepalive():
    result = format_keepalive()
    assert result == ": keepalive\n\n"
