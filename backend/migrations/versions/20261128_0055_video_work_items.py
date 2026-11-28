"""Work batches and work items for the video v3 pipeline (contract C2).

Additive only: two new tables, nothing existing is altered.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261128_0055"
down_revision = "20261125_0053"
branch_labels = None
depends_on = None

BATCH_SOURCES = ("talking", "editing_upload")
DRIVE_MODES = ("text", "audio", "uploaded_video")
STAGES = ("talking", "editing", "finishing", "done")
STATUSES = ("pending", "queued", "running", "succeeded", "failed", "canceled")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def _json() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "video_work_batches",
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
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("request_id", sa.String(40), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "workspace_id",
            "owner_user_id",
            "request_id",
            name="uq_video_work_batch_request",
        ),
        sa.CheckConstraint(
            _in("source", BATCH_SOURCES), name="ck_video_work_batch_source"
        ),
    )
    op.create_index(
        "ix_video_work_batches_scope",
        "video_work_batches",
        ["workspace_id", "owner_user_id", "created_at"],
    )
    op.create_table(
        "video_work_items",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "batch_id",
            sa.String(40),
            sa.ForeignKey("video_work_batches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
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
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("script_document_id", sa.String(40), nullable=True),
        sa.Column("publish_title", sa.Text, nullable=False),
        sa.Column("publish_body", sa.Text, nullable=False),
        sa.Column("script_text", sa.Text, nullable=False),
        sa.Column("persona_id", sa.String(80), nullable=True),
        sa.Column("avatar_id", sa.String(80), nullable=True),
        sa.Column("voice_id", sa.String(80), nullable=True),
        sa.Column("drive_mode", sa.String(24), nullable=False),
        sa.Column("audio_file_id", sa.String(40), nullable=True),
        sa.Column("generation_task_id", sa.String(40), nullable=True),
        sa.Column("source_video_ref", _json(), nullable=True),
        sa.Column("editing_task_id", sa.String(40), nullable=True),
        sa.Column("cover_asset_id", sa.String(80), nullable=True),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("history", _json(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("batch_id", "position", name="uq_video_work_item_position"),
        sa.CheckConstraint(
            _in("drive_mode", DRIVE_MODES), name="ck_video_work_item_drive"
        ),
        sa.CheckConstraint(_in("stage", STAGES), name="ck_video_work_item_stage"),
        sa.CheckConstraint(_in("status", STATUSES), name="ck_video_work_item_status"),
        sa.CheckConstraint("version >= 1", name="ck_video_work_item_version"),
    )
    op.create_index("ix_video_work_items_batch_id", "video_work_items", ["batch_id"])
    op.create_index(
        "ix_video_work_items_generation_task_id",
        "video_work_items",
        ["generation_task_id"],
    )
    op.create_index(
        "ix_video_work_items_editing_task_id", "video_work_items", ["editing_task_id"]
    )
    op.create_index(
        "ix_video_work_items_scope",
        "video_work_items",
        ["workspace_id", "owner_user_id", "stage", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_video_work_items_scope", table_name="video_work_items")
    op.drop_index("ix_video_work_items_editing_task_id", table_name="video_work_items")
    op.drop_index(
        "ix_video_work_items_generation_task_id", table_name="video_work_items"
    )
    op.drop_index("ix_video_work_items_batch_id", table_name="video_work_items")
    op.drop_table("video_work_items")
    op.drop_index("ix_video_work_batches_scope", table_name="video_work_batches")
    op.drop_table("video_work_batches")
