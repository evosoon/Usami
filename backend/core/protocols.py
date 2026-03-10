"""
AgenticOS — Runtime Protocol (薄抽象层)
Pre-mortem F1 修正: 依赖抽象，不依赖 LangGraph 实现

这一层定义了 AgenticOS 核心运行时的接口契约。
当前唯一实现是 LangGraph，但未来可替换为任何
符合协议的 Runtime（OpenAI Agents SDK、自建等）。

这是你的「逃生舱」— 约 100 行代码，换来架构自由度。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from core.state import AgentState, TaskPlan


# ============================================
# Agent Runtime Protocol
# ============================================

class AgentRuntimeProtocol(ABC):
    """Agent 执行运行时的抽象接口"""

    @abstractmethod
    async def execute(
        self,
        user_intent: str,
        config: dict[str, Any] | None = None,
    ) -> AgentState:
        """
        执行完整的任务链路:
        用户意图 → Boss 分解 → Persona 执行 → 汇总交付
        
        Returns: 最终的 AgentState
        """
        ...

    @abstractmethod
    async def stream(
        self,
        user_intent: str,
        config: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        流式执行，实时推送中间状态
        用于 WebSocket 实时通信
        
        Yields: 每一步的状态更新事件
        """
        ...

    @abstractmethod
    async def resume(
        self,
        thread_id: str,
        hitl_response: dict[str, Any],
    ) -> AgentState:
        """
        HiTL 恢复: 人类做出决定后，从中断点继续执行
        
        Args:
            thread_id: 任务线程 ID
            hitl_response: 人类的决定
        """
        ...

    @abstractmethod
    async def get_state(self, thread_id: str) -> AgentState | None:
        """获取指定线程的当前状态（断点续传）"""
        ...

    @abstractmethod
    async def list_threads(self) -> list[dict[str, Any]]:
        """列出所有任务线程"""
        ...


# ============================================
# State Store Protocol
# ============================================

class StateStoreProtocol(ABC):
    """状态持久化的抽象接口"""

    @abstractmethod
    async def save_checkpoint(
        self, thread_id: str, state: AgentState
    ) -> None:
        """保存检查点"""
        ...

    @abstractmethod
    async def load_checkpoint(
        self, thread_id: str
    ) -> AgentState | None:
        """加载检查点"""
        ...

    @abstractmethod
    async def list_checkpoints(
        self, thread_id: str
    ) -> list[dict[str, Any]]:
        """列出线程的所有检查点（时间旅行）"""
        ...


# ============================================
# Plan Validator Protocol (F2 修正)
# ============================================

class PlanValidatorProtocol(ABC):
    """任务计划验证器的抽象接口"""

    @abstractmethod
    def validate(
        self, plan: TaskPlan
    ) -> tuple[bool, list[str]]:
        """
        验证 Boss 生成的任务计划

        Returns: (is_valid, error_messages)

        检查项:
        - DAG 无循环依赖
        - 目标 Persona 存在
        - 预估 token 在预算内
        """
        ...
