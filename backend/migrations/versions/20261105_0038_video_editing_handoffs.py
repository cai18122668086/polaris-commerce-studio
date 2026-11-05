"""Scoped expiring editing grants and idempotent callbacks."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261105_0038"
down_revision = "20261105_0037"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "video_editing_handoffs",
        sa.Column("id", sa.String(40), primary_key=True),
        *[
            sa.Column(
                name,
                sa.String(40),
                sa.ForeignKey(target, ondelete="RESTRICT"),
                nullable=False,
            )
            for name, target in [
                ("workspace_id", "workspaces.id"),
                ("owner_user_id", "users.id"),
                ("generation_task_id", "video_generations.id"),
            ]
        ],
        sa.Column("request_id", sa.String(40), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "events",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("result_reference", sa.String(1000)),
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
            name="uq_video_editing_request",
        ),
    )
    op.create_index(
        "ix_video_editing_scope",
        "video_editing_handoffs",
        ["workspace_id", "owner_user_id", "generation_task_id"],
    )


def downgrade():
    raise RuntimeError("Preserve delegated access history and editing receipts.")
