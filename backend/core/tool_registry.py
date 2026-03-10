"""
AgenticOS — Tool Registry (多源加载)
Pre-mortem F5 修正: 扩展性评估中的关键升级

设计原则:
- 统一接口: 内置工具、MCP 工具、Skill 工具对 Agent 透明
- 多源加载: 静态注册 + MCP 动态发现 + Skill 插件
- 权限分层: L1(读取) → L2(API) → L3(代码) → L4(系统)
- 作用域隔离: 工具可绑定到特定 Persona
"""

from __future__ import annotations

import structlog
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from langchain_core.tools import BaseTool, tool

logger = structlog.get_logger()


# ============================================
# Tool Spec
# ============================================

@dataclass
class ToolSpec:
    """统一工具规格"""
    name: str
    description: str
    permission_level: int = 1        # L1-L4
    requires_approval: bool = False  # 是否需要 HiTL 审批
    source: str = "builtin"          # builtin | mcp | skill
    scope: Optional[str] = None      # None=全局, "researcher"=仅该 Persona
    handler: Optional[BaseTool] = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ============================================
# Built-in Tools (MVP)
# ============================================

@tool
def web_search(query: str) -> str:
    """搜索互联网获取最新信息"""
    # MVP: 简单实现，后续替换为真实搜索 API
    # TODO: 接入 Brave Search / SearXNG / Tavily
    return f"[web_search] 搜索结果 for: {query} — MVP 占位，请接入真实搜索 API"


@tool
def knowledge_search(query: str) -> str:
    """从知识库中检索相关信息"""
    # MVP: 简单实现，后续接入 pgvector RAG
    return f"[knowledge_search] 知识库检索: {query} — MVP 占位，请接入 RAG 管道"


@tool
def file_write(filename: str, content: str) -> str:
    """写入文件"""
    # MVP: 写到本地文件系统
    from pathlib import Path
    output_dir = Path("/app/outputs")
    output_dir.mkdir(exist_ok=True)
    filepath = output_dir / filename
    filepath.write_text(content, encoding="utf-8")
    return f"[file_write] 已写入: {filepath}"


BUILTIN_TOOL_MAP: dict[str, BaseTool] = {
    "web_search": web_search,
    "knowledge_search": knowledge_search,
    "file_write": file_write,
}


# ============================================
# Tool Registry
# ============================================

class ToolRegistry:
    """
    统一工具注册中心
    
    支持三种来源:
    1. 内置工具 (builtin) — 代码定义
    2. MCP 工具 (mcp) — 运行时动态发现
    3. Skill 工具 (skill) — 插件加载
    """

    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def load_builtin_tools(self, tools_config: dict[str, Any]) -> None:
        """从配置加载内置工具"""
        for name, config in tools_config.items():
            handler = BUILTIN_TOOL_MAP.get(name)
            if handler is None:
                logger.warning("builtin_tool_not_found", name=name)
                continue
            
            spec = ToolSpec(
                name=name,
                description=config.get("description", ""),
                permission_level=config.get("permission_level", 1),
                requires_approval=config.get("requires_approval", False),
                source="builtin",
                handler=handler,
            )
            self._tools[name] = spec
            logger.info("tool_registered", name=name, source="builtin")

    async def load_mcp_tools(self, mcp_config: dict[str, Any]) -> None:
        """从 MCP Server 动态加载工具"""
        if not mcp_config:
            return
        
        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
            
            async with MultiServerMCPClient(mcp_config) as client:
                tools = client.get_tools()
                for t in tools:
                    spec = ToolSpec(
                        name=t.name,
                        description=t.description,
                        permission_level=mcp_config.get(t.name, {}).get("permission_level", 2),
                        requires_approval=mcp_config.get(t.name, {}).get("requires_approval", False),
                        source="mcp",
                        handler=t,
                    )
                    self._tools[f"mcp:{t.name}"] = spec
                    logger.info("tool_registered", name=t.name, source="mcp")
        except ImportError:
            logger.warning("mcp_adapters_not_installed")
        except Exception as e:
            logger.error("mcp_load_failed", error=str(e))

    def load_skill_tools(self, skill_name: str, tools: list[ToolSpec]) -> None:
        """加载 Skill 提供的工具"""
        for t in tools:
            t.source = "skill"
            t.scope = skill_name
            self._tools[f"skill:{skill_name}:{t.name}"] = t
            logger.info("tool_registered", name=t.name, source="skill", scope=skill_name)

    def get_tools_for_persona(
        self,
        persona_name: str,
        tool_names: list[str],
        max_level: int = 2,
    ) -> list[BaseTool]:
        """获取指定 Persona 可用的工具列表"""
        result = []
        for name in tool_names:
            # 按优先级查找: 精确名 → mcp:名 → skill:persona:名
            spec = (
                self._tools.get(name)
                or self._tools.get(f"mcp:{name}")
                or self._tools.get(f"skill:{persona_name}:{name}")
            )
            if spec is None:
                logger.warning("tool_not_found", name=name, persona=persona_name)
                continue
            if spec.permission_level > max_level:
                logger.warning("tool_permission_denied", name=name, level=spec.permission_level, max=max_level)
                continue
            if spec.handler:
                result.append(spec.handler)
        
        return result

    def list_tools(self) -> list[ToolSpec]:
        """列出所有已注册工具"""
        return list(self._tools.values())
