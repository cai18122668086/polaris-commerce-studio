"""Freeze adopted writing provenance with the project and each script version."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261110_0051"
down_revision = "20261110_0050"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("video_projects", "video_script_versions"):
        op.add_column(
            table,
            sa.Column(
                "writing_origin",
                sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            ),
        )


def downgrade():
    for table in ("video_script_versions", "video_projects"):
        op.drop_column(table, "writing_origin")
