"""Add durable Aurora detail-page harness sessions.

Revision ID: 20260811_0100
Revises: 20260808_0006
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0100"
down_revision: str | None = "20260808_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "aurora_detail_sessions",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("workspace_id", sa.String(40), nullable=False),
        sa.Column("job_id", sa.String(40), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("state", sa.String(48), nullable=False),
        sa.Column("skill_version", sa.String(16), nullable=False),
        sa.Column("skill_content_hash", sa.String(64), nullable=False),
        sa.Column(
            "session_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "active_request_payload",
            postgresql.JSONB(astext_type=sa.Text()),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_aurora_detail_sessions_revision_positive"
        ),
        sa.UniqueConstraint("job_id", name="uq_aurora_detail_sessions_job"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "job_id"],
            ["jobs.workspace_id", "jobs.id"],
            name="fk_aurora_detail_sessions_workspace_job",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_aurora_detail_sessions_job_id",
        "aurora_detail_sessions",
        ["job_id"],
    )
    op.create_index(
        "ix_aurora_detail_sessions_workspace_state",
        "aurora_detail_sessions",
        ["workspace_id", "state", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_aurora_detail_sessions_workspace_state",
        table_name="aurora_detail_sessions",
    )
    op.drop_index(
        "ix_aurora_detail_sessions_job_id",
        table_name="aurora_detail_sessions",
    )
    op.drop_table("aurora_detail_sessions")
