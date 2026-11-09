"""Record where an imported editing image was delivered."""

import sqlalchemy as sa
from alembic import op

revision = "20261109_0049"
down_revision = "20261109_0048"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("source_job_id", "source_asset_id"):
        op.add_column("video_editing_materials", sa.Column(name, sa.String(40)))


def downgrade():
    for name in ("source_asset_id", "source_job_id"):
        op.drop_column("video_editing_materials", name)
