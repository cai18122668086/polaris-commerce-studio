"""Refunds contend with generation against the same PostgreSQL wallet lock."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import services
from app.config import Settings
from app.credit_payment_routes import settle_paid_purchase
from app.errors import ApiError
from app.main import create_app
from app.models import CreditGrantRecord, UserRecord, WorkspaceCreditAccountRecord
from tests.test_credit_payments import paid_fields
from tests.test_credit_payments_postgres import _order, _settings
from tests.test_credit_payments_postgres import (
    postgres_credits as postgres_credits,  # noqa: F401
)
from tests.test_customer_credit_billing import seed_job


@pytest.fixture
def pg_admin(postgres_credits, tmp_path):
    factory, engine = postgres_credits
    with factory() as session:
        session.get(UserRecord, "usr_test").email_normalized = "admin@example.com"
        session.get(WorkspaceCreditAccountRecord, "ws_test").balance_credits = 0
        session.commit()
    order = _order(factory)
    with factory() as session:
        settle_paid_purchase(session, _settings(), paid_fields(order))
    settings = Settings(
        _env_file=None,
        environment="test",
        auth_mode="development",
        database_url=engine.url.render_as_string(hide_password=False),
        auto_create_schema=False,
        development_user_id="usr_test",
        development_workspace_id="ws_test",
        announcement_admin_emails=["admin@example.com"],
        storage_backend="local",
        storage_dir=tmp_path / "storage",
        aurora_work_root=tmp_path / "aurora",
        task_dispatcher="inline",
        auto_process_jobs=False,
        provider_quota_enabled=False,
        workspace_credit_enforcement_enabled=True,
        access_url_secret="test-only-admin-commerce-secret",
    )
    with TestClient(create_app(settings)) as client:
        yield client, factory, order


def refund(client, order, key=None):
    return client.post(
        "/api/v1/admin/commerce/orders/" + order["id"] + "/refunds",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={"amount_fen": 9900, "credits": 1500, "reason": "人工全额退款核验"},
    )


def test_postgres_two_refund_requests_only_freeze_once(pg_admin):
    client, factory, order = pg_admin
    barrier = Barrier(2)

    def call():
        barrier.wait(timeout=10)
        return refund(client, order)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result(timeout=25) for f in [pool.submit(call), pool.submit(call)]]
    assert sorted(r.status_code for r in results) == [201, 409]
    with factory() as session:
        account = session.get(WorkspaceCreditAccountRecord, "ws_test")
        assert account.balance_credits == account.reserved_credits == 1500
        assert (
            sum(lot.held for lot in session.scalars(select(CreditGrantRecord))) == 1500
        )


def test_postgres_refund_and_generation_cannot_spend_same_credits(pg_admin):
    client, factory, order = pg_admin
    with factory() as session:
        job, _ = seed_job(session, kind="local_edit", count=1)
        identifier = job.id
        session.commit()
    barrier = Barrier(2)

    def hold_refund():
        barrier.wait(timeout=10)
        return refund(client, order).status_code

    def hold_generation():
        barrier.wait(timeout=10)
        with factory() as session:
            try:
                from app.models import JobRecord

                services.reserve_image_credits(
                    session, "ws_test", session.get(JobRecord, identifier)
                )
                session.commit()
                return True
            except ApiError as error:
                session.rollback()
                assert error.status_code == 402
                return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(hold_refund)
        b = pool.submit(hold_generation)
        refund_status, generation_held = a.result(timeout=25), b.result(timeout=25)
    assert (refund_status, generation_held) in [(201, False), (422, True)]
    with factory() as session:
        account = session.get(WorkspaceCreditAccountRecord, "ws_test")
        assert account.balance_credits == 1500
        assert account.reserved_credits in (5, 1500)
        assert (
            sum(lot.held for lot in session.scalars(select(CreditGrantRecord)))
            == account.reserved_credits
        )
