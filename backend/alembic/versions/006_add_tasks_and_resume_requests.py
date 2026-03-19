"""Add tasks and resume_requests tables for v2 refactor

Revision ID: 006
Revises: 005_add_events_table
Create Date: 2026-03-19

This migration supports the LangGraph infrastructure refactor:
- tasks: Persistent task state (replaces in-memory active_tasks)
- resume_requests: Persistent HiTL resume requests
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tasks table - persistent task state
    op.create_table(
        "tasks",
        sa.Column("thread_id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("intent", sa.Text, nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'interrupted', 'resuming', 'completed', 'failed')",
            name="ck_tasks_status",
        ),
    )

    # Indexes for tasks
    op.create_index("idx_tasks_user_status", "tasks", ["user_id", "status"])
    op.create_index("idx_tasks_status", "tasks", ["status"])

    # Resume requests table - persistent HiTL resume requests
    op.create_table(
        "resume_requests",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("resume_value", sa.JSON, nullable=False),
        sa.Column("consumed", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Index for resume_requests
    op.create_index("idx_resume_thread_consumed", "resume_requests", ["thread_id", "consumed"])

    # Add index on events table for user+seq queries (if not exists)
    # This is idempotent - will fail silently if already exists
    try:
        op.create_index("idx_events_user_seq", "events", ["user_id", "seq"])
    except Exception:
        pass  # Index may already exist


def downgrade() -> None:
    op.drop_index("idx_resume_thread_consumed", table_name="resume_requests")
    op.drop_table("resume_requests")

    op.drop_index("idx_tasks_status", table_name="tasks")
    op.drop_index("idx_tasks_user_status", table_name="tasks")
    op.drop_table("tasks")

    try:
        op.drop_index("idx_events_user_seq", table_name="events")
    except Exception:
        pass
