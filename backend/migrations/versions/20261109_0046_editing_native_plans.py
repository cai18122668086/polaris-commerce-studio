"""Freeze operator/model candidate plans separately from render attempts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261109_0046"
down_revision = "20261109_0045"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "video_editing_native_plans",
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
        *[
            sa.Column(name, sa.String(64), nullable=False)
            for name in (
                "base_transcript_sha256",
                "library_release",
                "request_hash",
                "semantic_sha256",
                "recipes_sha256",
            )
        ],
        sa.Column("request_id", sa.String(40), nullable=False),
        sa.Column("origin", sa.String(24), nullable=False),
        *[
            sa.Column(
                name,
                sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
                nullable=False,
            )
            for name in ("semantic", "recipes", "choice_snapshot", "details")
        ],
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "request_id",
            name="uq_editing_native_plan_request",
        ),
    )
    op.create_index(
        "ix_editing_native_plan_project",
        "video_editing_native_plans",
        ["workspace_id", "owner_user_id", "project_id"],
    )


def downgrade():
    op.drop_index(
        "ix_editing_native_plan_project", table_name="video_editing_native_plans"
    )
    op.drop_table("video_editing_native_plans")
