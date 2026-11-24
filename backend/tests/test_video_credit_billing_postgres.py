"""Video credit holds under real PostgreSQL row locks and partial indexes."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app import services
from app import video_credit_billing as video_credits
from app.config import Settings
from app.database import Base
from app.errors import ApiError
from app.models import (
    CreditLedgerEntryRecord,
    CreditReservationRecord,
    UserRecord,
    WorkspaceCreditAccountRecord,
    WorkspaceRecord,
)

WORKSPACE = "ws_video_pg"


@pytest.fixture
def postgres_video_credits():
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
    schema = "video_credit_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    options = f"-csearch_path={schema} -clock_timeout=10000"
    engine = create_engine(url.update_query_dict({"options": options}), pool_size=12)
    factory = sessionmaker(engine, expire_on_commit=False)
    services.set_quota_enabled(True)
    services.set_credit_enforcement_enabled(True)
    try:
        Base.metadata.create_all(engine)
        with factory() as session:
            session.add(
                UserRecord(id="usr_video_pg", auth_provider="test", auth_subject="pg")
            )
            session.flush()
            session.add(
                WorkspaceRecord(
                    id=WORKSPACE, name="Synthetic", created_by_user_id="usr_video_pg"
                )
            )
            session.flush()
            session.add(
                WorkspaceCreditAccountRecord(
                    workspace_id=WORKSPACE, balance_credits=50, reserved_credits=0
                )
            )
            session.commit()
        settings = Settings(
            _env_file=None,
            environment="test",
            video_credit_prices={"lipsync": 30, "editing_render": 30},
        )
        yield factory, settings
    finally:
        services.set_quota_enabled(True)
        services.set_credit_enforcement_enabled(False)
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def account(factory):
    with factory() as session:
        row = session.get(WorkspaceCreditAccountRecord, WORKSPACE)
        return row.balance_credits, row.reserved_credits


def test_postgres_concurrent_submits_hold_one_task_once(postgres_video_credits):
    factory, settings = postgres_video_credits
    owner = str(uuid4())
    barrier = Barrier(8)

    def submit(_):
        with factory() as session:
            barrier.wait()
            row = video_credits.hold(
                session, settings, WORKSPACE, "lipsync", "video_generation", owner
            )
            session.commit()
            return row.id

    with ThreadPoolExecutor(8) as pool:
        ids = set(pool.map(submit, range(8)))
    assert len(ids) == 1
    assert account(factory) == (50, 30)


def test_postgres_balance_admits_only_what_it_can_pay(postgres_video_credits):
    factory, settings = postgres_video_credits
    barrier = Barrier(2)

    def submit(_):
        with factory() as session:
            barrier.wait()
            try:
                video_credits.hold(
                    session,
                    settings,
                    WORKSPACE,
                    "lipsync",
                    "video_generation",
                    str(uuid4()),
                )
                session.commit()
                return "held"
            except ApiError as error:
                assert error.status_code == 402
                return error.code

    with ThreadPoolExecutor(2) as pool:
        outcomes = sorted(pool.map(submit, range(2)))
    assert outcomes == ["BUDGET_LIMIT_EXCEEDED", "held"]
    assert account(factory) == (50, 30)


def test_postgres_settle_and_release_race_resolves_once(postgres_video_credits):
    factory, settings = postgres_video_credits
    owner = str(uuid4())
    with factory() as session:
        video_credits.hold(
            session, settings, WORKSPACE, "editing_render", "video_editing", owner
        )
        session.commit()
    barrier = Barrier(6)

    def finish(index):
        with factory() as session:
            hold = session.scalars(
                select(CreditReservationRecord).where(
                    CreditReservationRecord.owner_id == owner
                )
            ).one()
            barrier.wait()
            (video_credits.settle if index % 2 else video_credits.release)(
                session, hold
            )
            session.commit()

    with ThreadPoolExecutor(6) as pool:
        list(pool.map(finish, range(6)))
    with factory() as session:
        terminal = session.scalar(
            select(func.count())
            .select_from(CreditLedgerEntryRecord)
            .where(CreditLedgerEntryRecord.entry_type.in_(["settle", "release"]))
        )
        status = session.scalars(
            select(CreditReservationRecord.status).where(
                CreditReservationRecord.owner_id == owner
            )
        ).one()
    assert terminal == 1
    assert account(factory) == ((20, 0) if status == "settled" else (50, 0))


def test_postgres_index_forbids_two_active_holds_and_orphans(postgres_video_credits):
    factory, _ = postgres_video_credits
    owner = str(uuid4())

    def row(**fields):
        return CreditReservationRecord(
            id="hold_" + uuid4().hex,
            workspace_id=WORKSPACE,
            reserved_credits=1,
            status="active",
            **fields,
        )

    with factory() as session:
        session.add(
            row(owner_type="video_voice", owner_id=owner, charge_action="voice_clone")
        )
        session.commit()
        session.add(
            row(owner_type="video_voice", owner_id=owner, charge_action="voice_clone")
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.add(row())
        with pytest.raises(IntegrityError):
            session.commit()


def test_postgres_migration_matches_the_reservation_model():
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import inspect

    from tests.test_schema_hardening_postgres import (
        _migrate,
        _new_schema,
        _postgres_url,
    )

    with _new_schema(_postgres_url(), "video_credit_migration") as schema:
        _migrate(schema.url, "20261116_0052")
        _migrate(schema.url, "head")
        with schema.engine.connect() as connection:
            table = inspect(connection)
            columns = {c["name"]: c for c in table.get_columns("credit_reservations")}
            assert columns["job_id"]["nullable"] is True
            assert {"owner_type", "owner_id", "charge_action"} <= set(columns)
            assert "ck_credit_reservations_owner" in {
                c["name"] for c in table.get_check_constraints("credit_reservations")
            }
            indexes = {i["name"]: i for i in table.get_indexes("credit_reservations")}
            assert indexes["uq_credit_reservations_active_owner"]["unique"]
            diffs = compare_metadata(
                MigrationContext.configure(connection), Base.metadata
            )
        assert [diff for diff in diffs if "credit_reservations" in repr(diff)] == []
