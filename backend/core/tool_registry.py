"""
Usami — Tool Registry (多源加载)
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
    """搜索互联网获取最新信息（通过 SearXNG）"""
    import asyncio
    import concurrent.futures

    async def _search() -> str:
        import httpx
        import os

        searxng_url = os.getenv("SEARXNG_URL", "http://searxng:8080")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{searxng_url}/search",
                    params={
                        "q": query,
                        "format": "json",
                        "categories": "general",
                        "language": "zh-CN",
                    },
                )
                response.raise_for_status()
                data = response.json()

                results = data.get("results", [])[:5]
                if not results:
                    return f"[web_search] 未找到与 '{query}' 相关的结果"

                formatted = []
                for i, r in enumerate(results, 1):
                    title = r.get("title", "无标题")
                    url = r.get("url", "")
                    snippet = r.get("content", "")[:200]
                    formatted.append(f"{i}. {title}\n   URL: {url}\n   摘要: {snippet}")

                return "[web_search] 搜索结果:\n" + "\n\n".join(formatted)

        except httpx.TimeoutException:
            logger.warning("web_search_timeout", query=query)
            return "[web_search] 搜索超时，请稍后重试"
        except httpx.HTTPStatusError as e:
            logger.error("web_search_http_error", query=query, status=e.response.status_code)
            return f"[web_search] 搜索服务异常 (HTTP {e.response.status_code})"
        except Exception as e:
            logger.error("web_search_error", query=query, error=str(e))
            return f"[web_search] 搜索失败: {str(e)}"

    try:
        # Handle running inside async context (LangGraph)
        try:
            loop = asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _search())
                return future.result(timeout=35.0)
        except RuntimeError:
            # No running loop, run directly
            return asyncio.run(_search())
    except Exception as e:
        logger.error("web_search_execution_error", error=str(e))
        return f"[web_search] 执行失败: {str(e)}"


@tool
def knowledge_search(query: str) -> str:
    """从知识库中检索相关信息（RAG 向量检索）"""
    import asyncio
    import concurrent.futures

    async def _search() -> str:
        import httpx
        import os

        litellm_url = os.getenv("LITELLM_PROXY_URL", "http://litellm:4000")
        top_k = 5

        try:
            # Step 1: Get embedding for query via LiteLLM
            litellm_key = os.getenv("LITELLM_MASTER_KEY", "sk-agenticOS-dev")
            async with httpx.AsyncClient(timeout=30.0) as client:
                embed_response = await client.post(
                    f"{litellm_url}/v1/embeddings",
                    json={
                        "model": "embedding",
                        "input": query,
                    },
                    headers={"Authorization": f"Bearer {litellm_key}"},
                )
                embed_response.raise_for_status()
                embed_data = embed_response.json()
                query_embedding = embed_data["data"][0]["embedding"]

            # Step 2: Vector similarity search via pgvector
            from core.memory import get_session
            from sqlalchemy import text

            async with get_session() as session:
                stmt = text("""
                    SELECT id, title, content, source,
                           1 - (embedding <=> :query_vec::vector) as similarity
                    FROM documents
                    WHERE embedding IS NOT NULL
                    ORDER BY embedding <=> :query_vec::vector
                    LIMIT :limit
                """)

                result = await session.execute(
                    stmt,
                    {"query_vec": str(query_embedding), "limit": top_k}
                )
                rows = result.fetchall()

                if not rows:
                    return f"[knowledge_search] 知识库中未找到与 '{query}' 相关的文档"

                formatted = []
                for i, row in enumerate(rows, 1):
                    similarity_pct = row.similarity * 100
                    content_preview = row.content[:300] + "..." if len(row.content) > 300 else row.content
                    formatted.append(
                        f"{i}. [{row.title}] (相似度: {similarity_pct:.1f}%)\n"
                        f"   来源: {row.source or '未知'}\n"
                        f"   内容: {content_preview}"
                    )

                return "[knowledge_search] 知识库检索结果:\n" + "\n\n".join(formatted)

        except httpx.HTTPStatusError as e:
            logger.error("knowledge_search_embedding_error", status=e.response.status_code)
            return "[knowledge_search] 向量化服务异常，无法检索知识库"
        except Exception as e:
            logger.error("knowledge_search_error", query=query, error=str(e))
            return f"[knowledge_search] 检索失败: {str(e)}"

    try:
        try:
            loop = asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _search())
                return future.result(timeout=35.0)
        except RuntimeError:
            return asyncio.run(_search())
    except Exception as e:
        logger.error("knowledge_search_execution_error", error=str(e))
        return f"[knowledge_search] 执行失败: {str(e)}"


@tool
def file_write(filename: str, content: str) -> str:
    """写入文件（限制 Markdown/JSON/YAML/TXT/CSV）"""
    from pathlib import Path
    import re

    # Security: Validate filename - only allow safe characters
    if not re.match(r'^[\w\-./]+$', filename):
        logger.warning("file_write_invalid_filename", filename=filename)
        return "[file_write] 文件名无效: 包含非法字符"

    # Security: Prevent path traversal
    if '..' in filename or filename.startswith('/'):
        logger.warning("file_write_path_traversal", filename=filename)
        return "[file_write] 文件名无效: 不允许路径遍历"

    # Security: Restrict file extensions
    allowed_extensions = {'.md', '.json', '.txt', '.yaml', '.yml', '.csv'}
    suffix = Path(filename).suffix.lower()
    if suffix and suffix not in allowed_extensions:
        logger.warning("file_write_disallowed_extension", filename=filename, suffix=suffix)
        return f"[file_write] 不允许的文件类型: {suffix}"

    try:
        output_dir = Path("/app/outputs")
        output_dir.mkdir(exist_ok=True)

        # Resolve to prevent any remaining path tricks
        filepath = (output_dir / filename).resolve()

        # Ensure file is still under output_dir
        if not str(filepath).startswith(str(output_dir.resolve())):
            logger.warning("file_write_escape_attempt", filename=filename)
            return "[file_write] 安全错误: 文件必须在输出目录内"

        # Create subdirectories if needed
        filepath.parent.mkdir(parents=True, exist_ok=True)

        filepath.write_text(content, encoding="utf-8")
        logger.info("file_write_success", filepath=str(filepath), size=len(content))
        return f"[file_write] 已写入: {filepath}"

    except PermissionError:
        logger.error("file_write_permission_denied", filename=filename)
        return "[file_write] 权限不足，无法写入文件"
    except Exception as e:
        logger.error("file_write_error", filename=filename, error=str(e))
        return f"[file_write] 写入失败: {str(e)}"


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
