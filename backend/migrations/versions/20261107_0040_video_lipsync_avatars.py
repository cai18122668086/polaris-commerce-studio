"""Durable, owner-scoped backup avatar registrations.

Revision ID: 20261107_0040
Revises: 20261105_0039
"""

import sqlalchemy as sa
from alembic import op

revision = "20261107_0040"
down_revision = "20261105_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "video_lipsync_avatars",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(),
            sa.ForeignKey("workspaces.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "owner_user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("model_id", sa.String(80), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("provider_task_id", sa.String(160)),
        sa.Column("avatar_code", sa.String(160)),
        sa.Column("error_code", sa.String(80)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "model_id",
            name="uq_video_lipsync_avatar_model",
        ),
    )


def downgrade() -> None:
    op.drop_table("video_lipsync_avatars")
