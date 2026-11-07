"""Durable video recovery ownership and retry scheduling.

Revision ID: 20261107_0041
Revises: 20261107_0040
"""

import sqlalchemy as sa
from alembic import op

revision = "20261107_0041"
down_revision = "20261107_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "video_generation_runs",
        sa.Column(
            "job_id",
            sa.String(40),
            sa.ForeignKey("video_generations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("owner_token", sa.String(40)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_video_generation_runs_retry_at", "video_generation_runs", ["retry_at"]
    )


def downgrade() -> None:
    op.drop_table("video_generation_runs")
