"""Owned planning, rewriting and source-transcription tasks."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261105_0037"
down_revision = "20261104_0036"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "video_assistance_tasks",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(40),
            sa.ForeignKey("workspaces.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "owner_user_id",
            sa.String(40),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.String(40),
            sa.ForeignKey("video_projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        *[
            sa.Column(name, sa.String(size), nullable=False)
            for name, size in [
                ("request_id", 40),
                ("request_hash", 64),
                ("kind", 16),
                ("status", 24),
                ("stage", 32),
            ]
        ],
        sa.Column("provider_task_id", sa.String(160)),
        *[
            sa.Column(
                name,
                sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
                nullable=False,
            )
            for name in ["inputs", "result", "receipt"]
        ],
        sa.Column("error_code", sa.String(80)),
        *[
            sa.Column(
                name,
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
            for name in ["created_at", "updated_at"]
        ],
        sa.UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "request_id",
            name="uq_video_assistance_request",
        ),
    )
    op.create_index(
        "ix_video_assistance_scope",
        "video_assistance_tasks",
        ["workspace_id", "owner_user_id", "project_id", "created_at"],
    )


def downgrade():
    raise RuntimeError("Preserve source, planning receipts and script task history.")
