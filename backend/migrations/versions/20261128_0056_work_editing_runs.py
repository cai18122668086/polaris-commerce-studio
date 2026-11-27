"""Editing runs of work items (W3, video v3): one additive table.

down_revision stays on the shared base 0053 (per the v3 rules); the merge
revision is added on the integration branch. It depends on the C2 work item
tables (0055), so alembic orders it after them.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261128_0056"
down_revision = "20261125_0053"
branch_labels = None
depends_on = "20261128_0055"

PHASES = (
    "queued",
    "transcribing",
    "preparing",
    "planning",
    "rendering",
    "done",
    "failed",
)


def _json() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "video_work_editing_runs",
        sa.Column(
            "item_id",
            sa.String(40),
            sa.ForeignKey("video_work_items.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
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
        sa.Column("request_id", sa.String(40), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.String(64), nullable=False),
        sa.Column("options", _json(), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("transcript_task_id", sa.String(40)),
        sa.Column("prepare_task_id", sa.String(40)),
        sa.Column("generate_task_id", sa.String(40)),
        sa.Column("render_task_id", sa.String(40)),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error", sa.Text()),
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
        sa.CheckConstraint(
            "phase IN (" + ", ".join(f"'{p}'" for p in PHASES) + ")",
            name="ck_video_work_editing_run_phase",
        ),
        sa.CheckConstraint("attempt >= 1", name="ck_video_work_editing_run_attempt"),
    )
    op.create_index(
        "ix_video_work_editing_runs_batch_id", "video_work_editing_runs", ["batch_id"]
    )
    op.create_index(
        "ix_video_work_editing_runs_owner_phase",
        "video_work_editing_runs",
        ["owner_user_id", "phase", "created_at"],
    )
    op.create_index(
        "ix_video_work_editing_runs_phase",
        "video_work_editing_runs",
        ["phase", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("video_work_editing_runs")
