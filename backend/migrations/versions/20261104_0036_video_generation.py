"""Provider catalogue, owned audio and durable generation jobs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261104_0036"
down_revision = "20261104_0035"
branch_labels = None
depends_on = None


def timestamps():
    return [
        sa.Column(
            name,
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        )
        for name in ["created_at", "updated_at"]
    ]


def upgrade() -> None:
    op.create_table(
        "video_avatars",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("gender", sa.String(12), nullable=False),
        sa.Column("cover_path", sa.Text()),
        sa.Column("video_url", sa.Text()),
        sa.Column("provider_model_id", sa.Integer()),
        sa.Column("active", sa.Boolean(), nullable=False),
        *timestamps(),
    )
    op.create_table(
        "video_generations",
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
        ),
        sa.Column(
            "confirmed_version_id",
            sa.String(40),
            sa.ForeignKey("video_script_versions.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "avatar_id",
            sa.String(80),
            sa.ForeignKey("video_avatars.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(40), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("provider_task_id", sa.String(160)),
        sa.Column(
            "details",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(80)),
        *timestamps(),
        sa.UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "request_id",
            name="uq_video_generation_request",
        ),
    )
    op.create_index(
        "ix_video_generation_scope",
        "video_generations",
        ["workspace_id", "owner_user_id", "created_at"],
    )
    op.create_table(
        "video_audio_files",
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
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("mime", sa.String(80), nullable=False),
        *timestamps(),
    )


def downgrade() -> None:
    raise RuntimeError("Keep generated videos, provider IDs and audio during rollback.")
