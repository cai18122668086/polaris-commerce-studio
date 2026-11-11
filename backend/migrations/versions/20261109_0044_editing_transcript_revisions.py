"""Immutable correction revisions; original ASR and completed tasks are preserved."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261109_0044"
down_revision = "20261109_0043"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "video_editing_transcript_revisions",
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
        sa.Column("base_transcript_sha256", sa.String(64), nullable=False),
        sa.Column(
            "parent_revision_id",
            sa.String(40),
            sa.ForeignKey("video_editing_transcript_revisions.id"),
        ),
        sa.Column("request_id", sa.String(40), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("corrected_text", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.Column("text_status", sa.String(24), nullable=False),
        sa.Column(
            "details",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "request_id",
            name="uq_video_editing_transcript_request",
        ),
    )
    op.create_index(
        "ix_video_editing_transcript_source",
        "video_editing_transcript_revisions",
        ["source_id", "created_at"],
    )


def downgrade():
    op.drop_index(
        "ix_video_editing_transcript_source",
        table_name="video_editing_transcript_revisions",
    )
    op.drop_table("video_editing_transcript_revisions")
