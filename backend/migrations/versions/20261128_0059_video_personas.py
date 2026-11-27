"""固定形象 video_personas（W6，契约 C3）。纯新增表，不改已有数据。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261128_0059"
down_revision = "20261125_0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "video_personas",
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
        sa.Column("name", sa.String(30), nullable=False),
        sa.Column("avatar_id", sa.String(80), nullable=False),
        sa.Column("voice_id", sa.String(80), nullable=False),
        sa.Column("avatar_name", sa.String(120), nullable=False),
        sa.Column("voice_name", sa.String(120), nullable=False),
        sa.Column(
            "voice_settings",
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
            "workspace_id",
            "owner_user_id",
            "request_id",
            name="uq_video_persona_request",
        ),
        sa.UniqueConstraint(
            "workspace_id", "owner_user_id", "name", name="uq_video_persona_name"
        ),
    )
    op.create_index(
        "ix_video_persona_scope",
        "video_personas",
        ["workspace_id", "owner_user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_video_persona_scope", table_name="video_personas")
    op.drop_table("video_personas")
