"""The shared editing-queue estimate on PostgreSQL (SQLite accepts queries
PostgreSQL rejects, so this runs against a real server)."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import sessionmaker

from app import video_work_editing as editing
from app.database import Base
from app.video_editing_task_models import EditingTaskRecord


@pytest.fixture
def postgres_factory():
    raw = os.environ.get("POLARIS_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("set POLARIS_TEST_DATABASE_URL for isolated PostgreSQL tests")
    url = make_url(raw)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or not url.database
        or not any(token in url.database.lower() for token in ("test", "ci"))
    ):
        raise pytest.UsageError("requires a local test/CI database")
    schema = "editing_queue_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url.update_query_dict({"options": f"-csearch_path={schema}"})
    )
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(engine, expire_on_commit=False)
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _ungrouped_mode_query(session, before=None):
    # The 572ca828 shape: the JSON subscript is bound twice, so PostgreSQL sees
    # two different expressions in SELECT and GROUP BY.
    session.execute(
        select(EditingTaskRecord.options["mode"].as_string(), func.count()).group_by(
            EditingTaskRecord.options["mode"].as_string()
        )
    )
    return 9, 9


def test_queue_estimate_groups_by_json_mode_on_postgres(postgres_factory):
    with postgres_factory() as session:
        with pytest.raises(ProgrammingError, match="GROUP BY"), session.begin_nested():
            _ungrouped_mode_query(session)
        # PostgreSQL rejects the grouping at planning time, empty table or not;
        # the raw query (no fallback) must plan and run.
        assert editing._worker_queue(session, None) == (0, 0)
        assert editing._worker_queue(session, datetime.now(UTC)) == (0, 0)
        assert editing.worker_queue(session) == (0, 0)


def test_failed_estimate_keeps_the_postgres_transaction_usable(
    postgres_factory, monkeypatch, caplog
):
    monkeypatch.setattr(editing, "_worker_queue", _ungrouped_mode_query)
    with postgres_factory() as session:
        assert editing.worker_queue(session) == (0, 0)
        assert "editing worker queue estimate failed" in caplog.text
        # Without the savepoint the batch view's next query would fail with
        # InFailedSqlTransaction.
        assert session.scalar(select(func.count()).select_from(EditingTaskRecord)) == 0
