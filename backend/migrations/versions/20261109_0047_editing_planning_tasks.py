"""Durable semantic preparation and single-submit model tasks."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261109_0047"
down_revision = "20261109_0046"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "video_editing_planning_tasks",
        sa.Column("id", sa.String(40), primary_key=True),
        *[
            sa.Column(name, sa.String(40), sa.ForeignKey(target), nullable=False)
            for name, target in (
                ("workspace_id", "workspaces.id"),
                ("owner_user_id", "users.id"),
                ("project_id", "video_projects.id"),
                ("source_id", "video_editing_sources.id"),
                ("base_task_id", "video_editing_tasks.id"),
                ("base_transcript_artifact_id", "video_editing_artifacts.id"),
            )
        ],
        sa.Column(
            "prepared_task_id",
            sa.String(40),
            sa.ForeignKey("video_editing_planning_tasks.id"),
        ),
        *[
            sa.Column(name, sa.String(64), nullable=False)
            for name in ("base_transcript_sha256", "request_hash", "library_release")
        ],
        sa.Column("request_id", sa.String(40), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        *[
            sa.Column(name, sa.Integer(), nullable=False)
            for name in ("revision", "attempts")
        ],
        sa.Column("owner_token", sa.String(40)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        *[
            sa.Column(
                name,
                sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
                nullable=False,
            )
            for name in ("snapshot", "checkpoint", "result")
        ],
        sa.Column("error_code", sa.String(80)),
        *[
            sa.Column(name, sa.DateTime(timezone=True), nullable=False)
            for name in ("created_at", "updated_at")
        ],
        sa.UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "request_id",
            name="uq_editing_planning_request",
        ),
        sa.UniqueConstraint("prepared_task_id", name="uq_editing_prepared_execution"),
    )
    op.create_index(
        "ix_editing_planning_queue",
        "video_editing_planning_tasks",
        ["status", "lease_until"],
    )
    op.create_index(
        "ix_editing_planning_project",
        "video_editing_planning_tasks",
        ["workspace_id", "owner_user_id", "project_id"],
    )
    op.create_table(
        "video_editing_planning_attempts",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(40),
            sa.ForeignKey("video_editing_planning_tasks.id"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(80)),
    )
    op.create_index(
        "ix_video_editing_planning_attempts_task_id",
        "video_editing_planning_attempts",
        ["task_id"],
    )


def downgrade():
    op.drop_index(
        "ix_video_editing_planning_attempts_task_id",
        table_name="video_editing_planning_attempts",
    )
    op.drop_table("video_editing_planning_attempts")
    op.drop_index(
        "ix_editing_planning_project", table_name="video_editing_planning_tasks"
    )
    op.drop_index(
        "ix_editing_planning_queue", table_name="video_editing_planning_tasks"
    )
    op.drop_table("video_editing_planning_tasks")
