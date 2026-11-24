"""Let video tasks hold workspace credits next to image jobs.

Additive: three nullable owner columns, ``job_id`` becomes nullable, and a
check keeps every hold tied to either a job or a video task. Existing image
reservations are unchanged.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261125_0053"
down_revision = "20261116_0052"
branch_labels = None
depends_on = None

ACTIVE_OWNER = "status = 'active' AND owner_type IS NOT NULL"


def upgrade() -> None:
    with op.batch_alter_table("credit_reservations") as batch:
        batch.add_column(sa.Column("owner_type", sa.String(32), nullable=True))
        batch.add_column(sa.Column("owner_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("charge_action", sa.String(32), nullable=True))
        batch.alter_column("job_id", existing_type=sa.String(40), nullable=True)
        batch.create_check_constraint(
            "ck_credit_reservations_owner",
            "job_id IS NOT NULL OR (owner_type IS NOT NULL AND owner_id IS NOT NULL"
            " AND charge_action IS NOT NULL)",
        )
    op.create_index(
        "uq_credit_reservations_active_owner",
        "credit_reservations",
        ["owner_type", "owner_id", "charge_action"],
        unique=True,
        postgresql_where=sa.text(ACTIVE_OWNER),
        sqlite_where=sa.text(ACTIVE_OWNER),
    )
    op.create_index(
        "ix_credit_reservations_owner",
        "credit_reservations",
        ["owner_type", "owner_id"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "Keep video credit holds for application rollback; dropping the owner "
        "columns would orphan settled video charges in the ledger."
    )
