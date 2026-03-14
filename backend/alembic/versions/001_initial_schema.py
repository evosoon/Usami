"""initial schema

Revision ID: 001
Revises: None
Create Date: 2026-03-10
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task_logs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("thread_id", sa.String(), index=True),
        sa.Column("task_id", sa.String()),
        sa.Column("persona", sa.String()),
        sa.Column("status", sa.String()),
        sa.Column("summary", sa.Text()),
        sa.Column("full_result", sa.Text()),
        sa.Column("confidence", sa.Float()),
        sa.Column("cost_usd", sa.Float(), default=0.0),
        sa.Column("metadata", sa.JSON(), default={}),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "hitl_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("request_id", sa.String(), unique=True, index=True),
        sa.Column("hitl_type", sa.String()),
        sa.Column("trigger", sa.String()),
        sa.Column("context", sa.JSON()),
        sa.Column("response", sa.String(), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("response_time_ms", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "routing_logs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("task_type", sa.String()),
        sa.Column("model_tier", sa.String()),
        sa.Column("model_name", sa.String()),
        sa.Column("prompt_tokens", sa.Float(), default=0),
        sa.Column("completion_tokens", sa.Float(), default=0),
        sa.Column("latency_ms", sa.Float(), default=0),
        sa.Column("cost_usd", sa.Float(), default=0),
        sa.Column("success", sa.String(), default="true"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("routing_logs")
    op.drop_table("hitl_events")
    op.drop_table("task_logs")
