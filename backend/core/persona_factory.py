"""
AgenticOS — Persona Factory
Pre-mortem F5 修正: 配置驱动，一个工厂函数 + YAML = 无限 Persona

设计原则:
- 不为每个 Persona 写单独文件
- 从 personas.yaml 读取配置，动态创建 LangGraph SubGraph
- 新增 Persona 只需加配置
"""

from __future__ import annotations

import structlog
from typing import Any

from langchain_core.messages import SystemMessage
from langgraph.prebuilt import create_react_agent

from core.tool_registry import ToolRegistry
from core.model_router import ModelRouter

logger = structlog.get_logger()


class PersonaFactory:
    """
    Persona 工厂 — 配置驱动的 Agent 创建
    
    从 personas.yaml 读取定义，动态创建可执行的 Agent。
    每个 Persona 是一个 LangGraph ReAct Agent (SubGraph)。
    """

    def __init__(
        self,
        personas_config: dict[str, Any],
        tool_registry: ToolRegistry,
        model_router_config: dict[str, Any],
    ):
        self._configs = personas_config
        self._tool_registry = tool_registry
        self._model_router = ModelRouter(model_router_config)
        self._personas: dict[str, Any] = {}
        
        # 预创建所有 Persona
        self._build_all()

    def _build_all(self) -> None:
        """从配置构建所有 Persona"""
        for name, config in self._configs.items():
            try:
                persona = self._build_one(name, config)
                self._personas[name] = persona
                logger.info("persona_created", name=name, role=config.get("role"))
            except Exception as e:
                logger.error("persona_creation_failed", name=name, error=str(e))

    def _build_one(self, name: str, config: dict) -> Any:
        """构建单个 Persona"""
        # 获取工具
        tool_names = config.get("tools", [])
        tools = self._tool_registry.get_tools_for_persona(
            persona_name=name,
            tool_names=tool_names,
        )

        # 获取模型
        model = self._model_router.get_model_for_persona(config)

        # 获取 System Prompt
        system_prompt = config.get("system_prompt", f"You are {name}.")

        # 创建 ReAct Agent (LangGraph SubGraph)
        # Boss 没有工具 — 纯推理 Agent
        if config.get("role") == "orchestrator":
            # Boss 用 structured output，不用工具
            agent = create_react_agent(
                model=model,
                tools=[],  # Boss 纯推理
                prompt=system_prompt,
            )
        else:
            agent = create_react_agent(
                model=model,
                tools=tools,
                prompt=system_prompt,
            )

        return agent

    def get_persona(self, name: str) -> Any:
        """获取指定 Persona"""
        persona = self._personas.get(name)
        if persona is None:
            raise KeyError(f"Persona not found: {name}. Available: {list(self._personas.keys())}")
        return persona

    def list_personas(self) -> dict[str, dict]:
        """列出所有 Persona 及其配置"""
        return {
            name: {
                "name": config.get("name", name),
                "role": config.get("role", "specialist"),
                "description": config.get("description", ""),
                "tools": config.get("tools", []),
                "model": config.get("model", "medium"),
            }
            for name, config in self._configs.items()
        }

    @property
    def model_router(self) -> ModelRouter:
        return self._model_router
