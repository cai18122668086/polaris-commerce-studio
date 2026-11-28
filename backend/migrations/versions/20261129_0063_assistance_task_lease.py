"""爆款文案 run 的租约（第三轮 F 线）：谁在跑、租到什么时候。

Additive only: two nullable columns on ``video_assistance_tasks``. A running
auto-writing run renews ``lease_until`` with its heartbeat; the sweeper turns a
run whose lease ran out into ``awaiting_resume`` and 「继续」 takes the lease
with a conditional UPDATE, so one run never has two executors (replaces the
per-process ``_RUNNING`` set). Other task kinds leave both NULL.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261129_0063"
down_revision = "20261129_0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("video_assistance_tasks") as batch:
        batch.add_column(sa.Column("lease_owner", sa.String(80), nullable=True))
        batch.add_column(
            sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True)
        )
    op.create_index(
        "ix_video_assistance_kind_status",
        "video_assistance_tasks",
        ["kind", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_video_assistance_kind_status", table_name="video_assistance_tasks"
    )
    with op.batch_alter_table("video_assistance_tasks") as batch:
        batch.drop_column("lease_until")
        batch.drop_column("lease_owner")
