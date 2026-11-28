"""Work items: soft delete (B1) and the merchant's own "published" mark (C10).

Additive only: two nullable timestamp columns on ``video_work_items``. Deleting
an item hides it from lists; its talking/editing tasks and files are kept.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261128_0061"
down_revision = "20261128_m0060w3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("video_work_items") as batch:
        batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("published_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    with op.batch_alter_table("video_work_items") as batch:
        batch.drop_column("published_at")
        batch.drop_column("deleted_at")
