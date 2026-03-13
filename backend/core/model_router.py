"""
AgenticOS — Model Router
按任务类型路由到不同模型，优化成本

Pre-mortem F4 修正: 每次路由决策记录日志，为未来智能路由埋数据管道
HA 加固: 指数退避重试 + 断路器
"""

from __future__ import annotations

import os
import time
import asyncio
import structlog
from typing import Any
from dataclasses import dataclass

from langchain_openai import ChatOpenAI

logger = structlog.get_logger()


# ============================================
# Routing Decision (数据管道)
# ============================================

@dataclass
class RoutingDecision:
    """路由决策记录（为智能路由埋点）"""
    task_type: str
    model_tier: str
    model_name: str
    timestamp: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0
    cost_usd: float = 0
    success: bool = True


# ============================================
# Circuit Breaker (手动实现, MVP 最小依赖)
# ============================================

class CircuitBreaker:
    """
    断路器 — 防止对故障下游的雪崩调用

    状态: CLOSED → OPEN → HALF_OPEN → CLOSED
    - CLOSED: 正常，允许调用
    - OPEN: 故障，拒绝调用，等待 recovery_timeout
    - HALF_OPEN: 试探，允许少量调用，成功则关闭
    """
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 1,
    ):
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max_calls = half_open_max_calls
        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0
        self._half_open_calls = 0

    @property
    def state(self) -> str:
        if self._state == self.OPEN:
            if time.time() - self._last_failure_time >= self._recovery_timeout:
                self._state = self.HALF_OPEN
                self._half_open_calls = 0
        return self._state

    def record_success(self) -> None:
        """记录成功调用"""
        if self._state == self.HALF_OPEN:
            self._state = self.CLOSED
            logger.info("circuit_breaker_closed")
        self._failure_count = 0

    def record_failure(self) -> None:
        """记录失败调用"""
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self._failure_threshold:
            self._state = self.OPEN
            logger.warning("circuit_breaker_opened", failures=self._failure_count)

    def can_execute(self) -> bool:
        """是否允许执行"""
        s = self.state  # 触发 HALF_OPEN 检查
        if s == self.CLOSED:
            return True
        if s == self.HALF_OPEN:
            if self._half_open_calls < self._half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False
        return False  # OPEN


# ============================================
# Retry with Backoff
# ============================================

async def _retry_with_backoff(
    coro_factory,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    circuit_breaker: CircuitBreaker | None = None,
):
    """
    指数退避重试 — 配合断路器使用

    coro_factory: 无参 async callable，每次重试创建新协程
    """
    last_error = None
    for attempt in range(max_retries + 1):
        if circuit_breaker and not circuit_breaker.can_execute():
            raise RuntimeError("LiteLLM 断路器已打开，暂停调用")

        try:
            result = await coro_factory()
            if circuit_breaker:
                circuit_breaker.record_success()
            return result
        except Exception as e:
            last_error = e
            if circuit_breaker:
                circuit_breaker.record_failure()
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.warning(
                    "litellm_retry",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    delay=delay,
                    error=str(e),
                )
                await asyncio.sleep(delay)

    raise last_error


# ============================================
# Model Router
# ============================================

class ModelRouter:
    """
    Model Router — 按任务类型路由到不同模型

    当前: 静态规则 + 重试 + 断路器
    未来: 基于 routing log 训练的智能路由
    """

    TIER_MAP = {
        "strong": "strong",
        "medium": "medium",
        "light": "light",
    }

    def __init__(self, routing_config: dict[str, Any]):
        self._rules = routing_config.get("routing_rules", {})
        self._budget = routing_config.get("budget", {})
        self._log_enabled = routing_config.get("logging", {}).get("enabled", True)
        self._routing_log: list[RoutingDecision] = []
        self._litellm_url = os.getenv("LITELLM_PROXY_URL", "http://localhost:4000")
        # HA: 断路器
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60.0,
        )
        # HA: 重试配置
        self._max_retries = 3
        self._base_delay = 1.0

    def get_model(self, task_type: str) -> ChatOpenAI:
        """根据任务类型获取对应模型"""
        rule = self._rules.get(task_type, {"model": "medium"})
        tier = rule.get("model", "medium")
        model_name = self.TIER_MAP.get(tier, "medium")

        # 记录路由决策
        decision = RoutingDecision(
            task_type=task_type,
            model_tier=tier,
            model_name=model_name,
            timestamp=time.time(),
        )
        self._routing_log.append(decision)

        if self._log_enabled:
            logger.info(
                "model_routed",
                task_type=task_type,
                tier=tier,
                model=model_name,
            )

        # 通过 LiteLLM Proxy 统一调用
        return ChatOpenAI(
            model=model_name,
            base_url=f"{self._litellm_url}/v1",
            api_key=os.getenv("LITELLM_MASTER_KEY", "sk-agenticOS-dev"),
            temperature=0.7,
        )

    def get_model_for_persona(self, persona_config: dict) -> ChatOpenAI:
        """根据 Persona 配置获取模型"""
        model_pref = persona_config.get("model", "medium")
        return self.get_model(model_pref)

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        """暴露断路器供健康检查使用"""
        return self._circuit_breaker

    async def ainvoke_with_retry(self, model: ChatOpenAI, messages: list) -> Any:
        """带重试 + 断路器的模型调用"""
        return await _retry_with_backoff(
            coro_factory=lambda: model.ainvoke(messages),
            max_retries=self._max_retries,
            base_delay=self._base_delay,
            circuit_breaker=self._circuit_breaker,
        )

    def get_routing_log(self) -> list[RoutingDecision]:
        """获取路由日志（为未来智能路由提供数据）"""
        return self._routing_log

    def get_budget(self) -> dict:
        """获取成本预算配置"""
        return self._budget
