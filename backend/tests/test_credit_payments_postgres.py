"""Financial concurrency and additive migrations on an isolated PostgreSQL schema."""

import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import SecretStr
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app import services
from app.admin_commerce_models import (
    CreditAdjustmentRecord,
    CustomerSupportRecord,
    ManualRefundRecord,
    SupportCaseRecord,
)
from app.config import Settings
from app.credit_payment_routes import _settle_verified_purchase, settle_paid_purchase
from app.database import Base
from app.errors import ApiError
from app.models import (
    AssetRecord,
    CreditGrantRecord,
    CreditLedgerEntryRecord,
    CreditMembershipRecord,
    CreditPurchaseRecord,
    CreditReservationRecord,
    JobAssetRecord,
    JobRecord,
    UserRecord,
    WorkspaceCreditAccountRecord,
    WorkspaceRecord,
    utc_now,
)
from tests.test_credit_payments import SECRET, paid_fields
from tests.test_customer_credit_billing import seed_job


@pytest.fixture
def postgres_credits():
    raw = os.environ.get("POLARIS_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("set POLARIS_TEST_DATABASE_URL for isolated credit tests")
    url = make_url(raw)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or not url.database
        or not any(token in url.database.lower() for token in ("test", "ci"))
    ):
        raise pytest.UsageError("Credit tests require a local test/CI database")
    schema = "credit_check_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    options = f"-csearch_path={schema} -clock_timeout=10000"
    engine = create_engine(url.update_query_dict({"options": options}))
    factory = sessionmaker(engine, expire_on_commit=False)
    services.set_quota_enabled(False)
    services.set_credit_enforcement_enabled(False)
    services.set_credit_pilot_workspaces(["ws_test"])
    try:
        Base.metadata.create_all(engine)
        with factory() as session:
            session.add(
                UserRecord(id="usr_test", auth_provider="test", auth_subject="pg")
            )
            session.flush()
            session.add(
                WorkspaceRecord(
                    id="ws_test", name="Synthetic", created_by_user_id="usr_test"
                )
            )
            session.flush()
            session.add(
                WorkspaceCreditAccountRecord(
                    workspace_id="ws_test", balance_credits=20, reserved_credits=0
                )
            )
            session.commit()
        yield factory, engine
    finally:
        services.set_quota_enabled(True)
        services.set_credit_enforcement_enabled(False)
        services.set_credit_pilot_workspaces([])
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _order(factory):
    order_id = "pay_" + uuid4().hex
    with factory() as session:
        session.add(
            CreditPurchaseRecord(
                id=order_id,
                workspace_id="ws_test",
                created_by_user_id="usr_test",
                idempotency_key=uuid4().hex,
                package_id="credits_1500",
                package_name="创作积分包 · 1,500 积分",
                amount_fen=9900,
                credits=1500,
                merchant_pid="1001",
                signing_key_id="v1",
                checkout_url="https://example.test/unused",
                status="pending",
            )
        )
        session.commit()
    return {"id": order_id, "package_name": "创作积分包 · 1,500 积分"}


def _settings():
    return Settings(
        _env_file=None, environment="test", credit_epay_keys={"v1": SecretStr(SECRET)}
    )


@pytest.mark.parametrize("mix_reconciliation", [False, True])
def test_postgres_duplicate_notifications_credit_once(
    postgres_credits, mix_reconciliation
):
    factory, _ = postgres_credits
    fields = paid_fields(_order(factory))
    barrier = Barrier(8)

    def notify(index):
        barrier.wait(timeout=10)
        with factory() as session:
            if mix_reconciliation and index % 2:
                _settle_verified_purchase(session, fields)
            else:
                settle_paid_purchase(session, _settings(), fields)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(notify, index) for index in range(8)]
        for future in futures:
            future.result(timeout=20)
    with factory() as session:
        assert (
            session.get(WorkspaceCreditAccountRecord, "ws_test").balance_credits == 1520
        )
        assert (
            session.scalar(select(func.count()).select_from(CreditLedgerEntryRecord))
            == 1
        )
        order = session.get(CreditPurchaseRecord, fields["out_trade_no"])
        assert order.status == "paid" and order.ledger_entry_id is not None


def test_postgres_different_orders_serialize_wallet_and_ledger(postgres_credits):
    factory, _ = postgres_credits
    fields = [paid_fields(_order(factory), trade=f"PGTRADE{n}") for n in range(2)]
    barrier = Barrier(2)

    def notify(parameters):
        barrier.wait(timeout=10)
        with factory() as session:
            settle_paid_purchase(session, _settings(), parameters)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(notify, parameters) for parameters in fields]
        for future in futures:
            future.result(timeout=20)
    with factory() as session:
        assert (
            session.get(WorkspaceCreditAccountRecord, "ws_test").balance_credits == 3020
        )
        balances = list(
            session.scalars(select(CreditLedgerEntryRecord.balance_after_credits))
        )
        assert sorted(balances) == [1520, 3020]


def test_postgres_concurrent_generation_cannot_overreserve(postgres_credits):
    factory, _ = postgres_credits
    with factory() as session:
        ids = [seed_job(session, kind="local_edit", count=1)[0].id for _ in range(8)]
        session.commit()
    barrier = Barrier(8)

    def reserve(job_id):
        barrier.wait(timeout=10)
        with factory() as session:
            try:
                services.reserve_image_credits(
                    session, "ws_test", session.get(JobRecord, job_id)
                )
                session.commit()
                return True
            except ApiError as error:
                session.rollback()
                assert error.code == "BUDGET_LIMIT_EXCEEDED"
                return False

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(reserve, job_id) for job_id in ids]
        results = [future.result(timeout=20) for future in futures]
    assert results.count(True) == 4
    with factory() as session:
        account = session.get(WorkspaceCreditAccountRecord, "ws_test")
        assert account.reserved_credits == account.balance_credits == 20
        for job_id in ids:
            services.release_credits(session, session.get(JobRecord, job_id))
        session.commit()
        session.refresh(account)
        assert account.balance_credits == 20 and account.reserved_credits == 0


def test_postgres_credit_migrations_preserve_legacy_reservation(postgres_credits):
    factory, engine = postgres_credits
    with factory() as session:
        job, _ = seed_job(session, kind="local_edit", count=1)
        job_id = job.id
        session.add(
            CreditReservationRecord(
                id="hold_legacy",
                workspace_id="ws_test",
                job_id=job_id,
                reserved_credits=2,
                settled_credits=0,
                status="active",
            )
        )
        session.flush()
        session.add(
            CreditLedgerEntryRecord(
                workspace_id="ws_test",
                reservation_id="hold_legacy",
                job_id=job_id,
                entry_type="reserve",
                delta_balance_credits=0,
                delta_reserved_credits=0,
                balance_after_credits=20,
                reserved_after_credits=0,
            )
        )
        session.commit()
    with engine.begin() as connection:
        for record in [
            ManualRefundRecord,
            CreditAdjustmentRecord,
            SupportCaseRecord,
            CustomerSupportRecord,
        ]:
            record.__table__.drop(connection)
        CreditGrantRecord.__table__.drop(connection)
        CreditMembershipRecord.__table__.drop(connection)
        connection.execute(
            text("ALTER TABLE workspace_credit_accounts DROP COLUMN lots_initialized")
        )
        connection.execute(
            text("ALTER TABLE credit_reservations DROP COLUMN credit_allocations")
        )
        connection.execute(
            text("ALTER TABLE credit_ledger_entries DROP COLUMN description")
        )
        CreditPurchaseRecord.__table__.drop(connection)
        connection.execute(
            text("ALTER TABLE credit_reservations DROP COLUMN pricing_snapshot")
        )
        for name in [
            "20261027_0028_credit_pricing_snapshot.py",
            "20261027_0029_credit_purchases.py",
            "20261027_0030_credit_memberships.py",
            "20261028_0031_admin_commerce.py",
        ]:
            path = Path(__file__).resolve().parents[1] / "migrations/versions" / name
            spec = importlib.util.spec_from_file_location("credit_migration", path)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with Operations.context(MigrationContext.configure(connection)):
                module.upgrade()
    with factory() as session:
        hold = session.get(CreditReservationRecord, "hold_legacy")
        assert hold.pricing_snapshot is None and hold.reserved_credits == 2
        services.settle_credits(session, session.get(JobRecord, job_id), 2)
        session.commit()
        assert (
            session.get(WorkspaceCreditAccountRecord, "ws_test").balance_credits == 20
        )
        assert session.get(CreditReservationRecord, "hold_legacy").status == "settled"
    _order(factory)


def test_postgres_yearly_boundary_grants_once(postgres_credits):
    from datetime import timedelta

    from app.credit_memberships import add_months, refresh
    from app.credit_products import PRODUCTS

    factory, _ = postgres_credits
    order = _order(factory)
    with factory() as session:
        record = session.get(CreditPurchaseRecord, order["id"])
        product = PRODUCTS["pro_annual"]
        record.package_id = product.id
        record.package_name = product.name
        record.amount_fen = product.amount_fen
        record.product_snapshot = product.snapshot()
        session.commit()
    order["package_name"] = product.name
    fields = paid_fields(order, money="948.00")
    with factory() as session:
        settle_paid_purchase(session, _settings(), fields)
        member = session.scalar(select(CreditMembershipRecord))
        boundary = add_months(member.starts_at, 1) + timedelta(seconds=1)
    barrier = Barrier(8)

    def reconcile():
        barrier.wait(timeout=10)
        with factory() as session:
            # Simulate an identity-map cache populated before waiting on the
            # wallet lock: it must refresh after another transaction commits.
            session.get(WorkspaceCreditAccountRecord, "ws_test")
            account = refresh(session, "ws_test", now=boundary)
            session.commit()
            return account.balance_credits

    with ThreadPoolExecutor(max_workers=8) as executor:
        values = list(executor.map(lambda _: reconcile(), range(8)))
    assert values == [1520] * 8
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(CreditGrantRecord)
                .where(CreditGrantRecord.kind == "membership")
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(CreditLedgerEntryRecord)
                .where(CreditLedgerEntryRecord.entry_type == "expire")
            )
            == 1
        )


@pytest.mark.parametrize("terminal", ["cancelled", "failed"])
def test_postgres_streamed_delivery_is_settled_once_after_stop(
    postgres_credits, terminal
):
    factory, _ = postgres_credits
    with factory() as session:
        account = session.get(WorkspaceCreditAccountRecord, "ws_test")
        account.balance_credits = 100
        job, _ = seed_job(
            session,
            kind="reference_remix",
            count=2,
            configuration={"replica_session_id": "replica-proof", "settings": {}},
        )
        services.reserve_image_credits(session, "ws_test", job)
        links = list(
            session.scalars(
                select(JobAssetRecord)
                .where(JobAssetRecord.job_id == job.id)
                .order_by(JobAssetRecord.ordinal)
            )
        )
        for link in links:
            session.get(AssetRecord, link.asset_id).asset_metadata = {
                "replica_incremental": True
            }
        session.get(AssetRecord, links[0].asset_id).deleted_at = utc_now()
        links[1].is_deliverable = False
        job.status = terminal
        job_id = job.id
        session.commit()
    barrier = Barrier(4)

    def settle():
        barrier.wait(timeout=10)
        with factory() as session:
            services.settle_credits(session, session.get(JobRecord, job_id), 0)
            session.commit()

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _: settle(), range(4)))
    with factory() as session:
        account = session.get(WorkspaceCreditAccountRecord, "ws_test")
        assert account.balance_credits == 85 and account.reserved_credits == 0
        assert session.get(JobRecord, job_id).actual_credits == 15
        assert (
            session.scalar(
                select(func.count())
                .select_from(CreditLedgerEntryRecord)
                .where(
                    CreditLedgerEntryRecord.job_id == job_id,
                    CreditLedgerEntryRecord.entry_type == "settle",
                )
            )
            == 1
        )
