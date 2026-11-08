"""Separate reference/analysis/facts/draft objects and version adoption lineage."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261109_0043"
down_revision = "20261109_0042"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "video_writing_documents",
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
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("request_id", sa.String(40), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column(
            "body",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("body_sha256", sa.String(64), nullable=False),
        sa.Column("rules_release", sa.String(64), nullable=False),
        *[
            sa.Column(name, sa.String(40), sa.ForeignKey("video_writing_documents.id"))
            for name in (
                "reference_document_id",
                "analysis_document_id",
                "facts_document_id",
            )
        ],
        sa.Column(
            "assistance_task_id",
            sa.String(40),
            sa.ForeignKey("video_assistance_tasks.id"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "request_id",
            name="uq_video_writing_document_request",
        ),
    )
    op.create_index(
        "ix_video_writing_scope",
        "video_writing_documents",
        ["workspace_id", "owner_user_id", "project_id", "created_at"],
    )
    op.create_table(
        "video_writing_adoptions",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(40),
            sa.ForeignKey("video_writing_documents.id"),
            nullable=False,
        ),
        sa.Column(
            "script_version_id",
            sa.String(40),
            sa.ForeignKey("video_script_versions.id"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "document_id", "request_id", name="uq_video_writing_adoption_request"
        ),
    )


def downgrade():
    op.drop_table("video_writing_adoptions")
    op.drop_index("ix_video_writing_scope", table_name="video_writing_documents")
    op.drop_table("video_writing_documents")
