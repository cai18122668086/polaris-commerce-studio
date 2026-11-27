"""Supplement materials: provenance for stock/AI media and AI image requests.

Additive only: two nullable columns on ``video_editing_materials`` (legacy
rows stay owner uploads) and one new table. ``down_revision`` points at 0053
by v3 convention; the integration branch adds the merge revision.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261128_0057"
down_revision = "20261125_0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("video_editing_materials") as batch:
        batch.add_column(sa.Column("origin", sa.String(24), nullable=True))
        batch.add_column(sa.Column("provenance", sa.JSON(), nullable=True))
    op.create_table(
        "video_editing_image_requests",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("request_id", sa.String(40), nullable=False),
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
        sa.Column("work_item_ref", sa.String(64), nullable=True),
        sa.Column("sentence_index", sa.Integer(), nullable=False),
        sa.Column("sentence", sa.String(400), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("purpose", sa.String(24), nullable=False),
        sa.Column("style", sa.String(24), nullable=False),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("material_id", sa.String(40), nullable=True),
        sa.Column("reused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "project_id", "owner_user_id", "request_id", name="uq_editing_image_request"
        ),
    )
    op.create_index(
        "ix_editing_image_request_status",
        "video_editing_image_requests",
        ["status", "updated_at"],
    )
    op.create_index(
        "ix_editing_image_request_cache",
        "video_editing_image_requests",
        ["workspace_id", "cache_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_editing_image_request_cache", table_name="video_editing_image_requests"
    )
    op.drop_index(
        "ix_editing_image_request_status", table_name="video_editing_image_requests"
    )
    op.drop_table("video_editing_image_requests")
    with op.batch_alter_table("video_editing_materials") as batch:
        batch.drop_column("provenance")
        batch.drop_column("origin")
