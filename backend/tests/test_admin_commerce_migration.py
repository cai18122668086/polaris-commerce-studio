"""The additive migration preserves purchases and agrees with ORM metadata."""

import importlib.util
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.admin_commerce_models import (
    CreditAdjustmentRecord,
    CustomerSupportRecord,
    ManualRefundRecord,
    SupportCaseRecord,
)
from app.database import Base
from app.models import (
    CreditPurchaseRecord,
    UserRecord,
    WorkspaceCreditAccountRecord,
    WorkspaceRecord,
)


def test_admin_commerce_additive_migration_preserves_financial_rows():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        for model in [
            ManualRefundRecord,
            CreditAdjustmentRecord,
            SupportCaseRecord,
            CustomerSupportRecord,
        ]:
            model.__table__.drop(connection)
        connection.execute(
            text("ALTER TABLE credit_memberships DROP COLUMN cancelled_at")
        )
    with Session(engine) as session:
        session.add(
            UserRecord(id="usr_legacy", auth_provider="test", auth_subject="legacy")
        )
        session.flush()
        session.add(
            WorkspaceRecord(
                id="ws_legacy",
                name="Existing customer",
                created_by_user_id="usr_legacy",
            )
        )
        session.flush()
        session.add(
            WorkspaceCreditAccountRecord(
                workspace_id="ws_legacy", balance_credits=42, reserved_credits=0
            )
        )
        session.add(
            CreditPurchaseRecord(
                id="pay_legacy",
                workspace_id="ws_legacy",
                created_by_user_id="usr_legacy",
                idempotency_key="legacy-original-request",
                package_id="pack_small",
                package_name="Original frozen purchase terms",
                amount_fen=2990,
                credits=300,
                merchant_pid="1001",
                signing_key_id="test-only",
                checkout_url="https://preview.invalid",
                status="pending",
            )
        )
        session.commit()
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/20261028_0031_admin_commerce.py"
    )
    spec = importlib.util.spec_from_file_location("admin_commerce_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        changed_tables = {
            "customer_support_profiles",
            "admin_credit_adjustments",
            "customer_support_cases",
            "manual_credit_refunds",
            "credit_memberships",
        }
        # SQLite cannot round-trip the legacy expression indexes. Compare the
        # complete schemas of all tables touched by this additive migration.
        context = MigrationContext.configure(
            connection,
            opts={
                "include_object": lambda obj, name, kind, reflected, compare_to: (
                    kind != "table" or name in changed_tables
                ),
            },
        )
        assert compare_metadata(context, Base.metadata) == []
    with Session(engine) as session:
        assert (
            session.get(WorkspaceCreditAccountRecord, "ws_legacy").balance_credits == 42
        )
        order = session.get(CreditPurchaseRecord, "pay_legacy")
        assert (order.status, order.amount_fen, order.credits, order.package_name) == (
            "pending",
            2990,
            300,
            "Original frozen purchase terms",
        )
    engine.dispose()
