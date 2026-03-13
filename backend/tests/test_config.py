"""
Usami — Config 单元测试
测试 YAML 加载 + 环境变量回退
"""

from __future__ import annotations

import os
import pytest
from pathlib import Path
from unittest.mock import patch, mock_open
from core.config import load_yaml, load_config, AppConfig


# ============================================
# load_yaml 测试
# ============================================

def test_load_yaml_existing_file():
    """测试加载存在的 YAML 文件"""
    yaml_content = """
personas:
  researcher:
    name: "Researcher"
    role: specialist
"""
    with patch("builtins.open", mock_open(read_data=yaml_content)):
        with patch("pathlib.Path.exists", return_value=True):
            result = load_yaml("personas.yaml")

    assert "personas" in result
    assert "researcher" in result["personas"]
    assert result["personas"]["researcher"]["name"] == "Researcher"


def test_load_yaml_nonexistent_file():
    """测试加载不存在的文件返回空字典"""
    with patch("pathlib.Path.exists", return_value=False):
        result = load_yaml("nonexistent.yaml")

    assert result == {}


def test_load_yaml_empty_file():
    """测试加载空文件返回空字典"""
    with patch("builtins.open", mock_open(read_data="")):
        with patch("pathlib.Path.exists", return_value=True):
            result = load_yaml("empty.yaml")

    assert result == {}


def test_load_yaml_invalid_yaml():
    """测试加载无效 YAML 抛出异常"""
    invalid_yaml = "invalid: yaml: content: ["
    with patch("builtins.open", mock_open(read_data=invalid_yaml)):
        with patch("pathlib.Path.exists", return_value=True):
            with pytest.raises(Exception):
                load_yaml("invalid.yaml")


# ============================================
# load_config 测试
# ============================================

def test_load_config_with_defaults():
    """测试 load_config 使用默认环境变量"""
    personas_yaml = """
personas:
  researcher:
    name: "Researcher"
"""
    tools_yaml = """
builtin_tools:
  web_search:
    description: "搜索"
"""
    routing_yaml = """
routing_rules:
  research:
    model: strong
"""

    with patch("core.config.load_yaml") as mock_load:
        def side_effect(filename):
            if filename == "personas.yaml":
                return {"personas": {"researcher": {"name": "Researcher"}}}
            elif filename == "tools.yaml":
                return {"builtin_tools": {"web_search": {"description": "搜索"}}}
            elif filename == "routing.yaml":
                return {"routing_rules": {"research": {"model": "strong"}}}
            return {}

        mock_load.side_effect = side_effect

        config = load_config()

    assert isinstance(config, AppConfig)
    assert config.database_url == "postgresql://agenticOS:agenticOS@localhost:5432/agenticOS"
    assert config.redis_url == "redis://localhost:6379/0"
    assert config.litellm_url == "http://localhost:4000"
    assert "researcher" in config.personas
    assert "web_search" in config.tools


def test_load_config_with_env_overrides():
    """测试环境变量覆盖默认值"""
    env_vars = {
        "DATABASE_URL": "postgresql://custom:custom@db:5432/custom",
        "REDIS_URL": "redis://custom-redis:6379/1",
        "LITELLM_PROXY_URL": "http://custom-litellm:4000",
    }

    with patch("core.config.load_yaml", return_value={}):
        with patch.dict(os.environ, env_vars):
            config = load_config()

    assert config.database_url == "postgresql://custom:custom@db:5432/custom"
    assert config.redis_url == "redis://custom-redis:6379/1"
    assert config.litellm_url == "http://custom-litellm:4000"


def test_load_config_empty_yaml_files():
    """测试所有 YAML 文件为空时的行为"""
    with patch("core.config.load_yaml", return_value={}):
        config = load_config()

    assert isinstance(config, AppConfig)
    assert config.personas == {}
    assert config.tools == {}
    assert config.mcp_servers == {}
    assert config.routing == {}


def test_load_config_partial_yaml():
    """测试部分 YAML 文件缺失时的行为"""
    with patch("core.config.load_yaml") as mock_load:
        def side_effect(filename):
            if filename == "personas.yaml":
                return {"personas": {"researcher": {"name": "Researcher"}}}
            return {}

        mock_load.side_effect = side_effect

        config = load_config()

    assert "researcher" in config.personas
    assert config.tools == {}
    assert config.routing == {}


# ============================================
# AppConfig 数据类测试
# ============================================

def test_app_config_default_values():
    """测试 AppConfig 默认值"""
    config = AppConfig()

    assert config.database_url == ""
    assert config.redis_url == ""
    assert config.litellm_url == ""
    assert config.personas == {}
    assert config.tools == {}
    assert config.mcp_servers == {}
    assert config.routing == {}


def test_app_config_custom_values():
    """测试 AppConfig 自定义值"""
    config = AppConfig(
        database_url="postgresql://test:test@localhost:5432/test",
        personas={"test": {"name": "Test"}},
        tools={"test_tool": {"description": "Test"}},
    )

    assert config.database_url == "postgresql://test:test@localhost:5432/test"
    assert "test" in config.personas
    assert "test_tool" in config.tools
