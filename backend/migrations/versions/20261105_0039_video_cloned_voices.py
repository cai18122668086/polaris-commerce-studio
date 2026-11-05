"""Private voice enrollment, consent evidence and cached preview state."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261105_0039"
down_revision = "20261105_0038"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "video_cloned_voices",
        sa.Column("id", sa.String(80), primary_key=True),
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
        sa.Column("request_id", sa.String(40), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("name", sa.String(30), nullable=False),
        sa.Column("prefix", sa.String(10), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("provider_workspace", sa.String(120), nullable=False),
        sa.Column("provider_voice_id", sa.String(240)),
        sa.Column("sample_path", sa.Text(), nullable=False),
        sa.Column("sample_sha256", sa.String(64), nullable=False),
        sa.Column("consent_version", sa.String(40), nullable=False),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("preview_status", sa.String(24), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column(
            "details",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        *[
            sa.Column(
                name,
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
            for name in ["created_at", "updated_at"]
        ],
        sa.UniqueConstraint(
            "workspace_id", "owner_user_id", "request_id", name="uq_video_clone_request"
        ),
        sa.UniqueConstraint("prefix", name="uq_video_clone_prefix"),
        sa.UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "sample_sha256",
            name="uq_video_clone_sample",
        ),
    )
    op.create_index(
        "ix_video_clone_scope",
        "video_cloned_voices",
        ["workspace_id", "owner_user_id", "created_at"],
    )


def downgrade():
    raise RuntimeError(
        "Preserve voice consent, enrollment history and preview receipts."
    )
