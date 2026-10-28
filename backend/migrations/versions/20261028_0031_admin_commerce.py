"""Customer support, audited grants and source-bound manual refunds."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261028_0031"
down_revision = "20261027_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    identity = sa.BigInteger().with_variant(sa.Integer(), "sqlite")

    def fk(name: str, target: str, nullable: bool = False, **kwargs):
        return sa.Column(
            name,
            sa.String(40),
            sa.ForeignKey(target, ondelete="RESTRICT"),
            nullable=nullable,
            **kwargs,
        )

    def stamps():
        return [
            sa.Column(
                n,
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
            for n in ["created_at", "updated_at"]
        ]

    def ledger(name: str, nullable: bool = False):
        return sa.Column(
            name,
            identity,
            sa.ForeignKey("credit_ledger_entries.id", ondelete="RESTRICT"),
            nullable=nullable,
            unique=True,
        )

    op.add_column(
        "credit_memberships",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "customer_support_profiles",
        fk("workspace_id", "workspaces.id", primary_key=True),
        sa.Column("note", sa.Text(), nullable=False),
        fk("updated_by_user_id", "users.id"),
        *stamps(),
    )
    op.create_table(
        "admin_credit_adjustments",
        sa.Column("id", sa.String(40), primary_key=True),
        fk("workspace_id", "workspaces.id"),
        fk("actor_user_id", "users.id"),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("credits", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        fk("job_id", "jobs.id", nullable=True),
        ledger("ledger_entry_id"),
        *stamps(),
        sa.UniqueConstraint(
            "workspace_id",
            "actor_user_id",
            "request_key",
            name="uq_admin_credit_adjustment_request",
        ),
        sa.CheckConstraint(
            "credits > 0 AND kind IN ('gift','compensation')",
            name="ck_admin_credit_adjustment_terms",
        ),
    )
    op.create_table(
        "customer_support_cases",
        sa.Column("id", sa.String(40), primary_key=True),
        fk("workspace_id", "workspaces.id"),
        fk("job_id", "jobs.id", nullable=True),
        sa.Column("issue", sa.Text(), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        fk("actor_user_id", "users.id"),
        *stamps(),
        sa.CheckConstraint(
            "status IN ('open','in_progress','resolved')", name="ck_support_case_status"
        ),
    )
    op.create_table(
        "manual_credit_refunds",
        sa.Column("id", sa.String(40), primary_key=True),
        fk("purchase_id", "credit_purchases.id"),
        fk("workspace_id", "workspaces.id"),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("amount_fen", sa.BigInteger(), nullable=False),
        sa.Column("credits", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("allocations", json_type, nullable=False),
        sa.Column("receipt_reference", sa.String(500)),
        sa.Column("result_note", sa.String(500)),
        fk("actor_user_id", "users.id"),
        fk("confirmed_by_user_id", "users.id", nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        ledger("hold_ledger_entry_id"),
        ledger("result_ledger_entry_id", nullable=True),
        *stamps(),
        sa.UniqueConstraint(
            "purchase_id", "request_key", name="uq_manual_refund_request"
        ),
        sa.CheckConstraint(
            "amount_fen > 0 AND credits >= 0 "
            "AND status IN ('processing','completed','rejected')",
            name="ck_manual_refund_terms",
        ),
    )
    for table, columns in [
        ("admin_credit_adjustments", ["workspace_id"]),
        ("customer_support_cases", ["workspace_id", "job_id"]),
        ("manual_credit_refunds", ["purchase_id", "workspace_id"]),
    ]:
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    raise RuntimeError(
        "Financial support records are forward-only; "
        "disable write permissions to roll back safely."
    )
