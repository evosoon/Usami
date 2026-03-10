"""
AgenticOS — ModelRouter + CircuitBreaker 单元测试
"""

from __future__ import annotations

import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.model_router import ModelRouter, CircuitBreaker, _retry_with_backoff


# ============================================
# CircuitBreaker 状态转换
# ============================================

class TestCircuitBreaker:

    def test_initial_state_closed(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitBreaker.CLOSED

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitBreaker.CLOSED

    def test_opens_at_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN

    def test_open_blocks_execution(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN
        assert cb.can_execute() is False

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        # 刚失败，recovery_timeout 未到 → OPEN
        assert cb.state == CircuitBreaker.OPEN
        # 等待超过 recovery_timeout → HALF_OPEN
        time.sleep(0.15)
        assert cb.state == CircuitBreaker.HALF_OPEN

    def test_half_open_allows_limited_calls(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.0, half_open_max_calls=1)
        cb.record_failure()
        time.sleep(0.01)
        assert cb.state == CircuitBreaker.HALF_OPEN
        assert cb.can_execute() is True   # 第 1 次
        assert cb.can_execute() is False  # 超过 half_open_max_calls

    def test_half_open_success_closes(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.0)
        cb.record_failure()
        time.sleep(0.01)
        assert cb.state == CircuitBreaker.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitBreaker.CLOSED

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        # 重新计数
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitBreaker.CLOSED  # 2 < 3


# ============================================
# _retry_with_backoff()
# ============================================

class TestRetryWithBackoff:

    @pytest.mark.asyncio
    async def test_success_first_try(self):
        factory = AsyncMock(return_value="ok")
        result = await _retry_with_backoff(factory, max_retries=3)
        assert result == "ok"
        assert factory.call_count == 1

    @pytest.mark.asyncio
    async def test_success_after_retries(self):
        factory = AsyncMock(side_effect=[Exception("e1"), Exception("e2"), "ok"])
        result = await _retry_with_backoff(
            factory, max_retries=3, base_delay=0.01,
        )
        assert result == "ok"
        assert factory.call_count == 3

    @pytest.mark.asyncio
    async def test_all_retries_exhausted(self):
        factory = AsyncMock(side_effect=Exception("fail"))
        with pytest.raises(Exception, match="fail"):
            await _retry_with_backoff(factory, max_retries=2, base_delay=0.01)
        assert factory.call_count == 3  # 1 initial + 2 retries

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_raises(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()  # → OPEN
        factory = AsyncMock(return_value="ok")
        with pytest.raises(RuntimeError, match="断路器已打开"):
            await _retry_with_backoff(factory, circuit_breaker=cb)
        assert factory.call_count == 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_on_success(self):
        cb = CircuitBreaker()
        factory = AsyncMock(return_value="ok")
        await _retry_with_backoff(factory, circuit_breaker=cb)
        assert cb._failure_count == 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_on_failure(self):
        cb = CircuitBreaker(failure_threshold=10)
        factory = AsyncMock(side_effect=Exception("err"))
        with pytest.raises(Exception):
            await _retry_with_backoff(
                factory, max_retries=2, base_delay=0.01, circuit_breaker=cb,
            )
        assert cb._failure_count == 3  # 1 initial + 2 retries


# ============================================
# ModelRouter 路由规则
# ============================================

class TestModelRouter:

    def _make_router(self, rules: dict | None = None) -> ModelRouter:
        config = {
            "routing_rules": rules or {
                "planning": {"model": "strong"},
                "research": {"model": "medium"},
                "writing": {"model": "strong"},
                "analysis": {"model": "medium"},
            },
            "budget": {"max_cost_per_task_usd": 0.50},
            "logging": {"enabled": True},
        }
        return ModelRouter(config)

    def test_planning_routes_to_strong(self):
        router = self._make_router()
        model = router.get_model("planning")
        assert model.model_name == "strong"

    def test_research_routes_to_medium(self):
        router = self._make_router()
        model = router.get_model("research")
        assert model.model_name == "medium"

    def test_unknown_type_defaults_to_medium(self):
        router = self._make_router()
        model = router.get_model("some_unknown_type")
        assert model.model_name == "medium"

    def test_routing_log_recorded(self):
        router = self._make_router()
        router.get_model("planning")
        router.get_model("research")
        log = router.get_routing_log()
        assert len(log) == 2
        assert log[0].task_type == "planning"
        assert log[0].model_tier == "strong"
        assert log[1].task_type == "research"
        assert log[1].model_tier == "medium"

    def test_circuit_breaker_exposed(self):
        router = self._make_router()
        assert router.circuit_breaker is not None
        assert router.circuit_breaker.state == CircuitBreaker.CLOSED

    def test_budget_config(self):
        router = self._make_router()
        assert router.get_budget() == {"max_cost_per_task_usd": 0.50}
