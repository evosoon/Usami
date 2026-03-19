"""
Usami — LangGraph Escape Hatch (D1)
Thin abstraction for runtime portability.

These Protocol interfaces describe the minimal contract that Usami's
orchestration layer depends on. The current LangGraph-based implementation
satisfies these interfaces naturally.

v2 更新:
- 移除 aupdate_state（由 Command(resume=...) 模式替代）
- 添加 astream 用于流式输出

To migrate to a different runtime, implement these Protocols — no
changes needed in boss.py, nodes.py, or routes.py.
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class AgentRuntime(Protocol):
    """Top-level graph execution runtime.

    LangGraph's compiled StateGraph satisfies this via:
    - ainvoke(state, config) -> dict
    - aget_state(config) -> StateSnapshot
    - astream(state, config) -> AsyncIterator (v2)
    """

    async def ainvoke(self, state: dict | None, config: dict | None = None) -> dict: ...
    async def aget_state(self, config: dict) -> Any: ...
    def astream(self, state: dict | None, config: dict | None = None) -> AsyncIterator[Any]: ...


@runtime_checkable
class PersonaAgent(Protocol):
    """Individual persona execution agent.

    LangGraph's ReAct agent satisfies this via ainvoke(inputs, config).
    """

    async def ainvoke(self, inputs: dict, config: dict | None = None) -> dict: ...


@runtime_checkable
class Checkpointer(Protocol):
    """State persistence backend.

    LangGraph's AsyncPostgresSaver satisfies this via setup().
    """

    async def setup(self) -> None: ...
