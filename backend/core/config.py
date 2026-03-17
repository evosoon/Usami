"""
Usami — Configuration Loader
从 YAML 配置文件加载所有系统配置

Environment loading chain:
  1. .env (user overrides, git-ignored)
  2. .env.example (defaults, committed to repo)
Any variable set in .env takes precedence over .env.example.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent  # Usami/
CONFIG_DIR = Path(__file__).parent.parent / "config"

# Load .env.example first (defaults), then .env (overrides).
# override=False means existing env vars won't be replaced,
# so we load .env.example first, then .env with override=True.
load_dotenv(PROJECT_ROOT / ".env.example", override=False)
load_dotenv(PROJECT_ROOT / ".env", override=True)


@dataclass
class AppConfig:
    """应用全局配置"""
    # Infrastructure
    database_url: str = ""
    redis_url: str = ""
    litellm_url: str = ""
    litellm_master_key: str = ""
    searxng_url: str = ""

    # Auth
    jwt_secret: str = ""
    access_token_expire_minutes: int = 1440  # 24 hours
    refresh_token_expire_days: int = 7
    admin_email: str = ""
    admin_password: str = ""

    # Push notifications
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_mailto: str = ""

    # Personas
    personas: dict[str, Any] = field(default_factory=dict)

    # Tools
    tools: dict[str, Any] = field(default_factory=dict)
    mcp_servers: dict[str, Any] = field(default_factory=dict)

    # Routing
    routing: dict[str, Any] = field(default_factory=dict)

    # Scheduler
    scheduler: dict[str, Any] = field(default_factory=dict)

    # Environment
    app_env: str = "development"


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

    app_env = os.environ.get("APP_ENV", "development")

    config = AppConfig(
        database_url=os.environ["DATABASE_URL"],
        redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        litellm_url=os.environ.get("LITELLM_PROXY_URL", "http://localhost:4000"),
        litellm_master_key=os.environ.get("LITELLM_MASTER_KEY", "sk-usami-dev"),
        searxng_url=os.environ.get("SEARXNG_URL", "http://searxng:8080"),
        jwt_secret=os.environ.get("JWT_SECRET", "usami-dev-secret-change-in-production"),
        access_token_expire_minutes=int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "1440")),
        refresh_token_expire_days=int(os.environ.get("REFRESH_TOKEN_EXPIRE_DAYS", "7")),
        admin_email=os.environ.get("ADMIN_EMAIL", ""),
        admin_password=os.environ.get("ADMIN_PASSWORD", ""),
        vapid_public_key=os.environ.get("VAPID_PUBLIC_KEY", ""),
        vapid_private_key=os.environ.get("VAPID_PRIVATE_KEY", ""),
        vapid_mailto=os.environ.get("VAPID_MAILTO", "mailto:admin@usami.local"),
        personas=personas_cfg.get("personas", {}),
        tools=tools_cfg.get("builtin_tools", {}),
        mcp_servers=tools_cfg.get("mcp_servers", {}),
        routing=routing_cfg,
        app_env=app_env,
    )

    # Reject weak JWT secrets in non-development environments
    if app_env != "development":
        _WEAK = {"usami-dev-secret-change-in-production", "change-me-in-production", "secret"}
        if config.jwt_secret in _WEAK or len(config.jwt_secret) < 32:
            raise ValueError("JWT_SECRET is too weak for production. Use a random string of at least 32 characters.")

    return config
