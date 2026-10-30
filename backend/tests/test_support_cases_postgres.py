"""Customer support migration and retry contention on isolated PostgreSQL schemas."""

import importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text

from app.admin_commerce_models import SupportCaseRecord
from tests.test_admin_commerce_postgres import pg_admin as pg_admin  # noqa: F401
from tests.test_credit_payments_postgres import (
    postgres_credits as postgres_credits,  # noqa: F401
)


def test_existing_staff_cases_survive_additive_migration(postgres_credits):
    factory, engine = postgres_credits
    with factory() as session:
        session.add(
            SupportCaseRecord(
                id="case_history",
                workspace_id="ws_test",
                actor_user_id="usr_test",
                issue="历史内部核对",
                resolution="原有处理记录",
                status="resolved",
            )
        )
        session.commit()
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE customer_support_cases DROP COLUMN created_by CASCADE")
        )
        connection.execute(
            text("ALTER TABLE customer_support_cases DROP COLUMN request_key CASCADE")
        )
        path = (
            Path(__file__).resolve().parents[1]
            / "migrations/versions/20261030_0033_customer_support_requests.py"
        )
        spec = importlib.util.spec_from_file_location("support_migration", path)
        assert spec and spec.loader
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    with factory() as session:
        row = session.get(SupportCaseRecord, "case_history")
        assert (row.issue, row.resolution, row.status, row.actor_user_id) == (
            "历史内部核对",
            "原有处理记录",
            "resolved",
            "usr_test",
        )
        assert row.created_by is None and row.request_key is None


def test_customer_retries_under_contention_create_one_case(pg_admin):
    client, factory, _ = pg_admin
    gate = Barrier(4)
    key = str(uuid4())
    url = "/api/v1/workspaces/ws_test/support-cases"

    def submit():
        gate.wait(timeout=10)
        return client.post(
            url,
            headers={"Idempotency-Key": key},
            json={"issue": "并发重试核对同一个问题"},
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = [
            f.result(timeout=30) for f in [pool.submit(submit) for _ in range(4)]
        ]
    assert all(r.status_code == 201 for r in responses)
    assert len({r.json()["id"] for r in responses}) == 1
    with factory() as session:
        assert len(list(session.scalars(select(SupportCaseRecord)))) == 1
