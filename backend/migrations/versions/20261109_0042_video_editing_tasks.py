"""Independent editing sources, fenced tasks, attempts and verified artifacts.

Revision ID: 20261109_0042
Revises: 20261107_0041
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261109_0042"
down_revision = "20261107_0041"
branch_labels = None
depends_on = None
json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def scope_columns():
    return [
        sa.Column(
            "workspace_id",
            sa.String(40),
            sa.ForeignKey("workspaces.id"),
            nullable=False,
        ),
        sa.Column(
            "owner_user_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "project_id",
            sa.String(40),
            sa.ForeignKey("video_projects.id"),
            nullable=False,
        ),
    ]


def timestamps():
    return [
        sa.Column(name, sa.DateTime(timezone=True), nullable=False)
        for name in ("created_at", "updated_at")
    ]


def upgrade():
    op.create_table(
        "video_editing_sources",
        sa.Column("id", sa.String(40), primary_key=True),
        *scope_columns(),
        sa.Column(
            "confirmed_version_id",
            sa.String(40),
            sa.ForeignKey("video_script_versions.id"),
        ),
        sa.Column(
            "generation_task_id", sa.String(40), sa.ForeignKey("video_generations.id")
        ),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("media_path", sa.Text(), nullable=False),
        sa.Column("media_sha256", sa.String(64), nullable=False),
        sa.Column("details", json_type, nullable=False),
        *timestamps(),
    )
    op.create_table(
        "video_editing_tasks",
        sa.Column("id", sa.String(40), primary_key=True),
        *scope_columns(),
        sa.Column(
            "source_id",
            sa.String(40),
            sa.ForeignKey("video_editing_sources.id"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(40), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("library_release", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("owner_token", sa.String(40)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("options", json_type, nullable=False),
        sa.Column("checkpoint", json_type, nullable=False),
        sa.Column("error_code", sa.String(80)),
        *timestamps(),
        sa.UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "request_id",
            name="uq_video_editing_task_request",
        ),
    )
    op.create_index(
        "ix_video_editing_task_queue", "video_editing_tasks", ["status", "lease_until"]
    )
    op.create_table(
        "video_editing_attempts",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(40),
            sa.ForeignKey("video_editing_tasks.id"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(80)),
    )
    op.create_index(
        "ix_video_editing_attempts_task_id", "video_editing_attempts", ["task_id"]
    )
    op.create_table(
        "video_editing_artifacts",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(40),
            sa.ForeignKey("video_editing_tasks.id"),
            nullable=False,
        ),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("mime", sa.String(80), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("validation", json_type, nullable=False),
        *timestamps(),
        sa.UniqueConstraint("task_id", "role", name="uq_video_editing_artifact_role"),
    )
    op.create_index(
        "ix_video_editing_artifacts_task_id", "video_editing_artifacts", ["task_id"]
    )


def downgrade():
    for name in ("artifacts", "attempts", "tasks", "sources"):
        op.drop_table("video_editing_" + name)
