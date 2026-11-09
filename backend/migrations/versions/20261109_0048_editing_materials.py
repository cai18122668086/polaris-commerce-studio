"""Immutable project-owned supplemental editing media."""

import sqlalchemy as sa
from alembic import op

revision = "20261109_0048"
down_revision = "20261109_0047"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "video_editing_materials",
        sa.Column("id", sa.String(40), primary_key=True),
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
        sa.Column("request_id", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("mime", sa.String(64), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("description", sa.String(400), nullable=False),
        *[
            sa.Column(name, sa.Integer(), nullable=False)
            for name in ("bytes", "width", "height")
        ],
        sa.Column("duration_ms", sa.Integer()),
        *[
            sa.Column(name, sa.DateTime(timezone=True), nullable=False)
            for name in ("created_at", "updated_at")
        ],
        sa.UniqueConstraint(
            "project_id",
            "owner_user_id",
            "request_id",
            name="uq_editing_material_request",
        ),
    )
    op.create_index(
        "ix_editing_material_project",
        "video_editing_materials",
        ["project_id", "workspace_id", "owner_user_id", "created_at"],
    )


def downgrade():
    op.drop_index("ix_editing_material_project", table_name="video_editing_materials")
    op.drop_table("video_editing_materials")
