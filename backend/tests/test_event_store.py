"""
Usami — Event Store Tests
Tests persist_event, get_thread_events, list_user_threads.
Uses in-memory SQLite for isolation.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from core.event_store import persist_event, get_thread_events, list_user_threads
from core.memory import init_database_for_tests


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Initialize in-memory database for each test."""
    await init_database_for_tests("sqlite+aiosqlite:///:memory:")
    yield


# ============================================
# persist_event
# ============================================

@pytest.mark.asyncio
async def test_persist_event_basic():
    event = await persist_event("thread_1", "user_1", "task.created", {"intent": "test"})
    assert event.thread_id == "thread_1"
    assert event.user_id == "user_1"
    assert event.event_type == "task.created"
    assert event.seq == 1
    assert event.payload["intent"] == "test"
    assert event.id  # Should have a UUID


@pytest.mark.asyncio
async def test_persist_event_increments_seq():
    e1 = await persist_event("thread_1", "user_1", "task.created", {"intent": "test"})
    e2 = await persist_event("thread_1", "user_1", "task.planning", {})
    e3 = await persist_event("thread_1", "user_1", "task.completed", {"result": "done"})
    assert e1.seq == 1
    assert e2.seq == 2
    assert e3.seq == 3


@pytest.mark.asyncio
async def test_persist_event_separate_threads_independent_seq():
    e1 = await persist_event("thread_1", "user_1", "task.created", {"intent": "a"})
    e2 = await persist_event("thread_2", "user_1", "task.created", {"intent": "b"})
    assert e1.seq == 1
    assert e2.seq == 1  # Separate threads have independent seq


# ============================================
# get_thread_events
# ============================================

@pytest.mark.asyncio
async def test_get_thread_events_ordered():
    await persist_event("thread_1", "user_1", "task.created", {"intent": "test"})
    await persist_event("thread_1", "user_1", "task.planning", {})
    await persist_event("thread_1", "user_1", "task.completed", {"result": "done"})

    events = await get_thread_events("thread_1")
    assert len(events) == 3
    assert events[0].event_type == "task.created"
    assert events[1].event_type == "task.planning"
    assert events[2].event_type == "task.completed"
    assert events[0].seq < events[1].seq < events[2].seq


@pytest.mark.asyncio
async def test_get_thread_events_after_seq_filter():
    await persist_event("thread_1", "user_1", "task.created", {"intent": "test"})
    await persist_event("thread_1", "user_1", "task.planning", {})
    await persist_event("thread_1", "user_1", "task.completed", {"result": "done"})

    events = await get_thread_events("thread_1", after_seq=1)
    assert len(events) == 2
    assert events[0].event_type == "task.planning"
    assert events[1].event_type == "task.completed"


@pytest.mark.asyncio
async def test_get_thread_events_empty():
    events = await get_thread_events("nonexistent")
    assert events == []


@pytest.mark.asyncio
async def test_get_thread_events_isolation():
    await persist_event("thread_1", "user_1", "task.created", {"intent": "a"})
    await persist_event("thread_2", "user_1", "task.created", {"intent": "b"})

    events = await get_thread_events("thread_1")
    assert len(events) == 1
    assert events[0].payload["intent"] == "a"


# ============================================
# list_user_threads
# Note: list_user_threads uses PostgreSQL-specific JSON operators (->>'key').
# These tests require PostgreSQL and are skipped in SQLite test environments.
# ============================================

@pytest.mark.asyncio
@pytest.mark.skipif(True, reason="list_user_threads uses PostgreSQL-specific JSON operators; requires PostgreSQL")
async def test_list_user_threads_basic():
    await persist_event("thread_1", "user_1", "task.created", {"intent": "research AI"})
    await persist_event("thread_1", "user_1", "task.completed", {"result": "done"})

    threads = await list_user_threads("user_1")
    assert len(threads) == 1
    assert threads[0]["thread_id"] == "thread_1"
    assert threads[0]["intent"] == "research AI"
    assert threads[0]["latest_phase"] == "task.completed"
    assert threads[0]["result"] == "done"


@pytest.mark.asyncio
@pytest.mark.skipif(True, reason="list_user_threads uses PostgreSQL-specific JSON operators; requires PostgreSQL")
async def test_list_user_threads_multiple():
    await persist_event("thread_1", "user_1", "task.created", {"intent": "a"})
    await persist_event("thread_2", "user_1", "task.created", {"intent": "b"})
    await persist_event("thread_3", "user_2", "task.created", {"intent": "c"})

    threads = await list_user_threads("user_1")
    assert len(threads) == 2
    thread_ids = {t["thread_id"] for t in threads}
    assert thread_ids == {"thread_1", "thread_2"}


@pytest.mark.asyncio
@pytest.mark.skipif(True, reason="list_user_threads uses PostgreSQL-specific JSON operators; requires PostgreSQL")
async def test_list_user_threads_empty():
    threads = await list_user_threads("nonexistent")
    assert threads == []
