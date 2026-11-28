"""文案库条目补「来自哪次生成」和「角度」两个展示用字段（第三轮 D 线）。

Additive only: two nullable columns on ``video_script_library`` and an index
for the 按生成批次 view. Old entries keep NULL (no backfill): they are grouped
as 「更早的」.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261129_0062"
down_revision = "20261128_0061"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("video_script_library") as batch:
        batch.add_column(sa.Column("run_id", sa.String(40), nullable=True))
        batch.add_column(sa.Column("angle", JSON, nullable=True))
    op.create_index(
        "ix_video_script_library_run",
        "video_script_library",
        ["workspace_id", "owner_user_id", "run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_video_script_library_run", table_name="video_script_library")
    with op.batch_alter_table("video_script_library") as batch:
        batch.drop_column("angle")
        batch.drop_column("run_id")
