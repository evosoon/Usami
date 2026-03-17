"""add events table for SSE event persistence

Revision ID: 005
Revises: 004
Create Date: 2026-03-16
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_events_thread_id", "events", ["thread_id"])
    op.create_index("ix_events_user_id", "events", ["user_id"])
    op.create_unique_constraint("uq_events_thread_seq", "events", ["thread_id", "seq"])


def downgrade() -> None:
    op.drop_constraint("uq_events_thread_seq", "events", type_="unique")
    op.drop_index("ix_events_user_id", table_name="events")
    op.drop_index("ix_events_thread_id", table_name="events")
    op.drop_table("events")
