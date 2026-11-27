"""Cover candidates for the 成片 step (W5): one table, additive.

Revision ID: 20261128_0058
"""

import sqlalchemy as sa
from alembic import op

from sqlalchemy.dialects import postgresql


def json_type() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

revision = "20261128_0058"
down_revision = "20261125_0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "video_cover_candidates",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("workspace_id", sa.String(40), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("owner_user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_id", sa.String(40), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column("work_item_id", sa.String(40), nullable=True),
        sa.Column("source_kind", sa.String(16), nullable=False),
        sa.Column("source_id", sa.String(40), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("cover_text", sa.Text(), nullable=False),
        sa.Column("highlight", sa.Text(), nullable=True),
        sa.Column("background", sa.String(8), nullable=False),
        sa.Column("layout", sa.String(16), nullable=True),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.String(40), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("params", json_type(), nullable=False),
        sa.Column("checks", json_type(), nullable=False),
        sa.Column("files", json_type(), nullable=False),
        sa.Column("receipt", json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("workspace_id", "owner_user_id", "request_id", "slot", name="uq_video_cover_request_slot"),
    )
    op.create_index(
        "ix_video_cover_item", "video_cover_candidates",
        ["workspace_id", "owner_user_id", "work_item_id", "created_at"],
    )
    op.create_index(
        "ix_video_cover_source", "video_cover_candidates",
        ["workspace_id", "owner_user_id", "source_kind", "source_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_video_cover_source", table_name="video_cover_candidates")
    op.drop_index("ix_video_cover_item", table_name="video_cover_candidates")
    op.drop_table("video_cover_candidates")
