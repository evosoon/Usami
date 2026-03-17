"""
Usami — LangGraph Escape Hatch (D1)
Thin abstraction for runtime portability.

These Protocol interfaces describe the minimal contract that Usami's
orchestration layer depends on. The current LangGraph-based implementation
satisfies these interfaces naturally (ainvoke, aget_state, aupdate_state).

To migrate to a different runtime, implement these 3 Protocols — no
changes needed in boss.py, nodes.py, or routes.py.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AgentRuntime(Protocol):
    """Top-level graph execution runtime.

    LangGraph's compiled StateGraph satisfies this via:
    - ainvoke(state, config) -> dict
    - aget_state(config) -> StateSnapshot
    - aupdate_state(config, updates) -> None
    """

    async def ainvoke(self, state: dict | None, config: dict | None = None) -> dict: ...
    async def aget_state(self, config: dict) -> Any: ...
    async def aupdate_state(self, config: dict, updates: dict) -> None: ...


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
