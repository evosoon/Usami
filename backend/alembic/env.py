"""
Usami — Alembic env.py
使用同步 psycopg 驱动执行迁移
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# 将 backend/ 加入 sys.path 以便 import core.memory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.memory import Base

# Alembic Config 对象
config = context.config

# 日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# SQLAlchemy MetaData
target_metadata = Base.metadata


def get_url() -> str:
    """从环境变量获取数据库 URL，转换为 psycopg 同步驱动格式"""
    url = os.getenv(
        "DATABASE_URL",
        "postgresql://agenticOS:agenticOS@localhost:5432/agenticOS",
    )
    # Alembic 使用同步 psycopg 驱动
    return url.replace("postgresql://", "postgresql+psycopg://")


def run_migrations_offline() -> None:
    """离线模式: 仅生成 SQL 脚本，不连接数据库"""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式: 连接数据库执行迁移"""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
