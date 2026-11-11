"""Store the observation attested with an uploaded editing evidence image."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261110_0050"
down_revision = "20261109_0049"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "video_editing_materials",
        sa.Column(
            "feedback_observation",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
        ),
    )


def downgrade():
    op.drop_column("video_editing_materials", "feedback_observation")
