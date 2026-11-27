"""文案库：标题 + 发布正文 + 口播稿，自动入库、可编辑、可多选去口播。

Additive: one new table. Existing ``video_script_versions`` rows of kind
``library`` are not moved; the API mirrors them into this table the first time
the owner lists the library (``legacy_version_id``), so rolling the
application back leaves the old library exactly as it was.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261128_0054"
down_revision = "20261125_0053"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "video_script_library",
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
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False, server_default=""),
        sa.Column("publish_title", sa.String(80), nullable=False, server_default=""),
        sa.Column("publish_body", sa.Text(), nullable=False, server_default=""),
        sa.Column("script", sa.Text(), nullable=False),
        sa.Column("benchmark_refs", JSON, nullable=False),
        sa.Column("dedupe_key", sa.String(160), nullable=True),
        sa.Column(
            "project_id",
            sa.String(40),
            sa.ForeignKey("video_projects.id"),
            nullable=True,
        ),
        sa.Column(
            "writing_document_id",
            sa.String(40),
            sa.ForeignKey("video_writing_documents.id"),
            nullable=True,
        ),
        sa.Column(
            "legacy_version_id",
            sa.String(40),
            sa.ForeignKey("video_script_versions.id"),
            nullable=True,
        ),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("history", JSON, nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "dedupe_key",
            name="uq_video_script_library_dedupe",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "writing_document_id",
            name="uq_video_script_library_document",
        ),
        sa.UniqueConstraint("legacy_version_id", name="uq_video_script_library_legacy"),
    )
    op.create_index(
        "ix_video_script_library_scope",
        "video_script_library",
        ["workspace_id", "owner_user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_video_script_library_scope", table_name="video_script_library")
    op.drop_table("video_script_library")
