"""AI 润色候选 video_avatar_polishes（W6）。纯新增表。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261128_0059b"
down_revision = "20261128_0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "video_avatar_polishes",
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
        sa.Column("request_id", sa.String(40), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("result_path", sa.Text()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("consent_version", sa.String(40), nullable=False),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checks", json_type, nullable=False),
        sa.Column("receipt", json_type, nullable=False),
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
            "workspace_id",
            "owner_user_id",
            "request_id",
            "slot",
            name="uq_video_avatar_polish_slot",
        ),
    )
    op.create_index(
        "ix_video_avatar_polish_scope",
        "video_avatar_polishes",
        ["workspace_id", "owner_user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_video_avatar_polish_scope", table_name="video_avatar_polishes")
    op.drop_table("video_avatar_polishes")
