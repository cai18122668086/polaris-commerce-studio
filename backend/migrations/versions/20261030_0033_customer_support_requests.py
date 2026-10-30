"""Connect customer requests to the existing support console."""

import sqlalchemy as sa
from alembic import op

revision = "20261030_0033"
down_revision = "20261030_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("customer_support_cases") as batch:
        batch.add_column(sa.Column("created_by", sa.String(40), nullable=True))
        batch.add_column(sa.Column("request_key", sa.String(128), nullable=True))
        batch.create_foreign_key(
            "fk_customer_support_creator",
            "users",
            ["created_by"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_unique_constraint(
            "uq_customer_support_request", ["workspace_id", "request_key"]
        )


def downgrade() -> None:
    raise RuntimeError("Retain customer support requests during application rollback.")
