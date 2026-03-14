"""
Usami — Configuration Loader
从 YAML 配置文件加载所有系统配置
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).parent.parent / "config"


@dataclass
class AppConfig:
    """应用全局配置"""
    # Database
    database_url: str = ""
    redis_url: str = ""
    litellm_url: str = ""
    searxng_url: str = ""

    # Personas
    personas: dict[str, Any] = field(default_factory=dict)

    # Tools
    tools: dict[str, Any] = field(default_factory=dict)
    mcp_servers: dict[str, Any] = field(default_factory=dict)

    # Routing
    routing: dict[str, Any] = field(default_factory=dict)

    # Scheduler
    scheduler: dict[str, Any] = field(default_factory=dict)


def load_yaml(filename: str) -> dict:
    """加载 YAML 配置文件"""
    filepath = CONFIG_DIR / filename
    if not filepath.exists():
        return {}
    with open(filepath, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config() -> AppConfig:
    """加载全部配置，合并环境变量"""

    # 加载 YAML 配置
    personas_cfg = load_yaml("personas.yaml")
    tools_cfg = load_yaml("tools.yaml")
    routing_cfg = load_yaml("routing.yaml")

    return AppConfig(
        database_url=os.getenv("DATABASE_URL", "postgresql://agenticOS:agenticOS@localhost:5432/agenticOS"),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        litellm_url=os.getenv("LITELLM_PROXY_URL", "http://localhost:4000"),
        searxng_url=os.getenv("SEARXNG_URL", "http://searxng:8080"),
        personas=personas_cfg.get("personas", {}),
        tools=tools_cfg.get("builtin_tools", {}),
        mcp_servers=tools_cfg.get("mcp_servers", {}),
        routing=routing_cfg,
    )
