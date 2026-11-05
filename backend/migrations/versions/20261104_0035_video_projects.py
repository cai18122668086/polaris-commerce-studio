"""Add isolated video projects and immutable version/task history."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261104_0035"
down_revision = "20261030_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "video_projects",
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
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content", json_type, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("revision >= 1", name="ck_video_project_revision"),
    )
    op.create_index(
        "ix_video_projects_scope",
        "video_projects",
        ["workspace_id", "owner_user_id", "updated_at"],
    )
    op.create_table(
        "video_script_versions",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(40),
            sa.ForeignKey("video_projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("snapshot", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('draft', 'library', 'confirmed')", name="ck_video_version_kind"
        ),
    )
    op.create_index(
        "ix_video_versions_project",
        "video_script_versions",
        ["project_id", "created_at"],
    )
    op.create_table(
        "video_tasks",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(40),
            sa.ForeignKey("video_projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "confirmed_version_id",
            sa.String(40),
            sa.ForeignKey("video_script_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status = 'demo'", name="ck_video_task_demo_only"),
    )
    op.create_index("ix_video_tasks_project_id", "video_tasks", ["project_id"])
    op.create_table(
        "video_mutations",
        sa.Column(
            "workspace_id",
            sa.String(40),
            sa.ForeignKey("workspaces.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "owner_user_id",
            sa.String(40),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("request_id", sa.String(64), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("result", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    raise RuntimeError(
        "Preserve video project and confirmed script history during rollback."
    )
