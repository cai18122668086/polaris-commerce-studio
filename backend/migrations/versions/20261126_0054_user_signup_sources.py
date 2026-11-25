"""Record which ``?from=`` link a new account signed up through.

Additive: one new table keyed by user. Existing users are untouched and get no row.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261126_0054"
down_revision = "20261125_0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_signup_sources",
        sa.Column(
            "user_id",
            sa.String(40),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_signup_sources")
