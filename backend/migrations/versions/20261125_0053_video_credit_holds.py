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
    # Reversible only while no video task holds credits: those rows have no
    # job and would orphan settled video charges in the ledger.
    if not op.get_context().as_sql:
        video_holds = op.get_bind().scalar(
            sa.text(
                "SELECT COUNT(*) FROM credit_reservations "
                "WHERE job_id IS NULL OR owner_type IS NOT NULL"
            )
        )
        if video_holds:
            raise RuntimeError(
                f"{video_holds} video credit holds exist; keep migration 0053 "
                "for application rollback."
            )
    op.drop_index("ix_credit_reservations_owner", table_name="credit_reservations")
    op.drop_index(
        "uq_credit_reservations_active_owner", table_name="credit_reservations"
    )
    with op.batch_alter_table("credit_reservations") as batch:
        batch.drop_constraint("ck_credit_reservations_owner", type_="check")
        batch.alter_column("job_id", existing_type=sa.String(40), nullable=False)
        batch.drop_column("charge_action")
        batch.drop_column("owner_id")
        batch.drop_column("owner_type")
