"""Real concurrent redo confirmations on an isolated PostgreSQL schema.

Two requests, each on its own database connection, confirm the same missing
pages of the same original job at the same time. The source row lock must let
exactly one redo job through; the customer ledger records each page once.
Mock upstream only. Set POLARIS_TEST_DATABASE_URL to a throwaway database.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url

from app import aurora_main_image_missing_pages as missing_module
from app.aurora_main_image_fast_provider import RECEIPTS_KEY
from app.main import create_app
from app.models import CreditLedgerEntryRecord, CreditReservationRecord, JobRecord

from .test_aurora_main_image_missing_pages import (
    LOST,
    _credits,
    _deliverables,
    _first_round,
    _redo,
)


@pytest.fixture
def pg_client(settings, tmp_path):
    raw_url = os.environ.get("POLARIS_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("set POLARIS_TEST_DATABASE_URL for PostgreSQL concurrency tests")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql":
        raise pytest.UsageError("POLARIS_TEST_DATABASE_URL must use PostgreSQL")
    schema = f"redo_concurrency_{uuid4().hex}"
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    options = (
        f"{url.query.get('options', '')} -csearch_path={schema} -clock_timeout=15000"
    ).strip()
    scoped = url.update_query_dict({"options": options})
    pg_settings = settings.model_copy(
        update={"database_url": scoped.render_as_string(hide_password=False)}
    )
    try:
        with TestClient(create_app(pg_settings)) as client:
            yield client
    finally:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _hold_the_lock_long_enough(monkeypatch):
    """Keep the first confirmation inside its transaction for a moment."""

    original = missing_module.confirm_and_release
    backends: list[int] = []
    lock = threading.Lock()

    def slow(session, job, confirmed_pages, stage_root):
        with lock:
            backends.append(session.execute(text("select pg_backend_pid()")).scalar())
        result = original(session, job, confirmed_pages, stage_root)
        time.sleep(1.0)
        return result

    monkeypatch.setattr(missing_module, "confirm_and_release", slow)
    return backends


def test_two_connections_confirming_at_once_create_one_redo_and_bill_once(
    pg_client, tmp_path, monkeypatch
):
    job_id, gateway = _first_round(pg_client, tmp_path)
    backends = _hold_the_lock_long_enough(monkeypatch)
    start = threading.Barrier(2)

    def confirm(key):
        start.wait()
        return _redo(pg_client, job_id, sorted(LOST), key=key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(confirm, ["tab-a", "tab-b"]))

    codes = sorted(response.status_code for response in responses)
    assert codes == [201, 409], [r.text for r in responses]
    rejected = next(r for r in responses if r.status_code == 409)
    assert rejected.json()["error"]["code"] == "MISSING_PAGES_REDO_EXISTS"
    # Both requests reached the confirmation, each on its own database
    # connection; the second only after the first had committed its redo.
    assert len(backends) == 2 and len(set(backends)) == 2, backends
    redo_id = next(r for r in responses if r.status_code == 201).json()["id"]
    session_factory = pg_client.app.state.session_factory
    with session_factory() as db:
        children = db.scalar(
            select(func.count())
            .select_from(JobRecord)
            .where(JobRecord.retry_of_job_id == job_id)
        )
    assert children == 1

    from .test_api import dispatch_pending

    dispatch_pending(pg_client)
    assert _deliverables(pg_client, redo_id) == set(range(6))
    reservations, ledger, supplier_requests = _credits(pg_client, [job_id, redo_id])
    assert reservations == {job_id: ("settled", 16), redo_id: ("settled", 32)}
    assert ledger[job_id] == ledger[redo_id] == ["reserve", "settle"]
    assert supplier_requests == 10
    with session_factory() as db:
        settled = db.scalar(
            select(func.sum(CreditReservationRecord.settled_credits)).where(
                CreditReservationRecord.job_id.in_([job_id, redo_id])
            )
        )
        ledger_rows = db.scalar(
            select(func.count())
            .select_from(CreditLedgerEntryRecord)
            .where(CreditLedgerEntryRecord.job_id.in_([job_id, redo_id]))
        )
    assert settled == 48 and ledger_rows == 4  # six pages × 8, once each


def test_postgres_late_receipt_after_redo_neither_delivers_nor_bills(
    pg_client, tmp_path
):
    job_id, _ = _first_round(pg_client, tmp_path)
    redo_id = _redo(pg_client, job_id, sorted(LOST)).json()["id"]
    from .test_api import dispatch_pending

    dispatch_pending(pg_client)
    before = _credits(pg_client, [job_id, redo_id])
    delivered = (_deliverables(pg_client, job_id), _deliverables(pg_client, redo_id))
    with pg_client.app.state.session_factory() as db:
        job = db.get(JobRecord, job_id)
        receipts = dict(job.configuration[RECEIPTS_KEY])
        receipts["0"] = {
            **receipts["0"],
            "state": "returned",
            "object_key": "late/object.png",
            "sha256": "0" * 64,
        }
        job.configuration = {**job.configuration, RECEIPTS_KEY: receipts}
        db.commit()
    for target in (job_id, redo_id):
        asyncio.run(pg_client.app.state.task_runner.run(target))
    assert (
        _deliverables(pg_client, job_id),
        _deliverables(pg_client, redo_id),
    ) == delivered
    assert _credits(pg_client, [job_id, redo_id]) == before
