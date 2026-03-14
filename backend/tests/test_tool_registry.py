"""
Usami — Tool Registry 单元测试
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from core.tool_registry import BUILTIN_TOOL_MAP, ToolRegistry, file_write, web_search

# ============================================
# web_search 测试
# ============================================

class TestWebSearch:
    """web_search 工具测试"""

    def test_web_search_success(self):
        """测试 web_search 成功返回结果"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"title": "Test Result", "url": "https://example.com", "content": "Test content"}
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            result = web_search.invoke({"query": "test query"})

        assert "[web_search] 搜索结果" in result
        assert "Test Result" in result

    def test_web_search_no_results(self):
        """测试 web_search 无结果"""
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            result = web_search.invoke({"query": "nonexistent"})

        assert "未找到" in result

    def test_web_search_timeout(self):
        """测试 web_search 超时处理 (配置指向不存在的服务)"""
        import core.tool_registry as _tr

        old = _tr._searxng_url
        _tr._searxng_url = "http://nonexistent-host:9999"
        try:
            result = web_search.invoke({"query": "test"})
        finally:
            _tr._searxng_url = old

        assert result is not None
        assert "[web_search]" in result
        # Should contain error message (either connection error or timeout)
        assert "失败" in result or "异常" in result or "超时" in result

    def test_web_search_http_error(self):
        """测试 web_search HTTP 错误处理"""
        import core.tool_registry as _tr

        old = _tr._searxng_url
        _tr._searxng_url = "http://127.0.0.1:1"
        try:
            result = web_search.invoke({"query": "test"})
        finally:
            _tr._searxng_url = old

        assert result is not None
        assert "[web_search]" in result


# ============================================
# file_write 测试
# ============================================

class TestFileWrite:
    """file_write 工具测试"""

    def test_file_write_invalid_filename_special_chars(self):
        """测试 file_write 拒绝特殊字符"""
        result = file_write.invoke({"filename": "file;rm -rf /", "content": "test"})
        assert "文件名无效" in result

    def test_file_write_path_traversal_dotdot(self):
        """测试 file_write 拒绝路径遍历 (../)"""
        result = file_write.invoke({"filename": "../../../etc/passwd", "content": "hack"})
        assert "不允许路径遍历" in result

    def test_file_write_path_traversal_absolute(self):
        """测试 file_write 拒绝绝对路径"""
        result = file_write.invoke({"filename": "/etc/passwd", "content": "hack"})
        assert "不允许路径遍历" in result

    def test_file_write_invalid_extension(self):
        """测试 file_write 拒绝非法扩展名"""
        result = file_write.invoke({"filename": "script.exe", "content": "malware"})
        assert "不允许的文件类型" in result

    def test_file_write_invalid_extension_py(self):
        """测试 file_write 拒绝 Python 文件"""
        result = file_write.invoke({"filename": "evil.py", "content": "import os"})
        assert "不允许的文件类型" in result

    def test_file_write_valid_md(self, tmp_path):
        """测试 file_write 允许 Markdown 文件"""
        # This test validates that valid filenames pass validation
        # The actual file write will fail in test environment since /app/outputs doesn't exist
        # but we're testing the validation logic, not the file I/O

        result = file_write.invoke({"filename": "test.md", "content": "# Hello"})

        # Either success or file system error (not validation error)
        assert "file_write" in result
        # Should not be a validation error
        assert "文件名无效" not in result
        assert "不允许路径遍历" not in result
        assert "不允许的文件类型" not in result


# ============================================
# ToolRegistry 测试
# ============================================

class TestToolRegistry:
    """ToolRegistry 测试"""

    def test_tool_registry_load_builtin(self):
        """测试 ToolRegistry 加载内置工具"""
        registry = ToolRegistry()
        registry.load_builtin_tools({
            "web_search": {"description": "搜索", "permission_level": 1},
            "file_write": {"description": "写入", "permission_level": 2},
        })

        tools = registry.list_tools()
        assert len(tools) == 2
        assert any(t.name == "web_search" for t in tools)
        assert any(t.name == "file_write" for t in tools)

    def test_tool_registry_permission_filter(self):
        """测试 ToolRegistry 权限过滤"""
        registry = ToolRegistry()
        registry.load_builtin_tools({
            "web_search": {"description": "搜索", "permission_level": 1},
            "file_write": {"description": "写入", "permission_level": 2},
        })

        # Only L1 tools allowed
        tools = registry.get_tools_for_persona("researcher", ["web_search", "file_write"], max_level=1)
        assert len(tools) == 1

        # L2 tools allowed
        tools = registry.get_tools_for_persona("researcher", ["web_search", "file_write"], max_level=2)
        assert len(tools) == 2

    def test_tool_registry_missing_tool(self):
        """测试 ToolRegistry 处理缺失工具"""
        registry = ToolRegistry()
        registry.load_builtin_tools({
            "nonexistent_tool": {"description": "不存在"},
        })

        tools = registry.list_tools()
        assert len(tools) == 0  # Tool not in BUILTIN_TOOL_MAP

    def test_tool_registry_partial_match(self):
        """测试 ToolRegistry 部分工具匹配"""
        registry = ToolRegistry()
        registry.load_builtin_tools({
            "web_search": {"description": "搜索", "permission_level": 1},
            "nonexistent": {"description": "不存在"},
        })

        tools = registry.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "web_search"

    def test_tool_registry_get_tools_for_persona_missing(self):
        """测试获取不存在的工具"""
        registry = ToolRegistry()
        registry.load_builtin_tools({
            "web_search": {"description": "搜索", "permission_level": 1},
        })

        tools = registry.get_tools_for_persona("researcher", ["nonexistent_tool"], max_level=2)
        assert len(tools) == 0


# ============================================
# BUILTIN_TOOL_MAP 测试
# ============================================

class TestBuiltinToolMap:
    """BUILTIN_TOOL_MAP 测试"""

    def test_all_tools_registered(self):
        """测试所有工具都已注册"""
        assert "web_search" in BUILTIN_TOOL_MAP
        assert "knowledge_search" in BUILTIN_TOOL_MAP
        assert "file_write" in BUILTIN_TOOL_MAP

    def test_tools_are_langchain_tools(self):
        """测试工具是 LangChain BaseTool 实例"""
        from langchain_core.tools import BaseTool

        for name, tool in BUILTIN_TOOL_MAP.items():
            assert isinstance(tool, BaseTool), f"{name} is not a BaseTool"
