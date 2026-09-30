"""Exercise real row locks with independent sessions and concurrent executors."""

import asyncio
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app import aurora_set_audit
from app.database import Base
from app.execution import ExecutionCoordinator
from app.models import (
    JobItemRecord,
    JobPlanRecord,
    JobRecord,
    UserRecord,
    WorkspaceRecord,
)
from app.provider import FakeProvider


@pytest.fixture
def review_db():
    raw_url = os.environ.get("POLARIS_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("PostgreSQL required for set-review concurrency")
    url = make_url(raw_url)
    assert url.get_backend_name() == "postgresql"
    schema = f"set_review_{uuid4().hex}"
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url.update_query_dict(
            {"options": f"-csearch_path={schema} -clock_timeout=5000"}
        )
    )
    factory = sessionmaker(engine)
    try:
        Base.metadata.create_all(engine)
        with factory() as session:
            session.add(
                UserRecord(id="usr_review", auth_provider="test", auth_subject="review")
            )
            session.flush()
            session.add(
                WorkspaceRecord(
                    id="ws_review", name="Test", created_by_user_id="usr_review"
                )
            )
            session.flush()
            session.add(
                JobRecord(
                    id="job_review",
                    workspace_id="ws_review",
                    type="domestic_main_image",
                    status="processing",
                    expected_item_count=6,
                )
            )
            session.flush()
            session.add(
                JobPlanRecord(
                    id="plan_review",
                    workspace_id="ws_review",
                    job_id="job_review",
                    revision=1,
                    payload={"execution_policy": {"execution_mode": "parallel_v20"}},
                    payload_hash="fixture",
                )
            )
            for index in range(6):
                session.add(
                    JobItemRecord(
                        id=f"item_{index}",
                        workspace_id="ws_review",
                        job_id="job_review",
                        item_key=f"page-{index}",
                        ordinal=index,
                        status="succeeded",
                    )
                )
            session.commit()
        yield factory
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


class HeldReview(FakeProvider):
    def __init__(self, verdict):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.verdict = verdict

    async def audit_parallel_set(self, job_id):
        self.calls += 1
        self.started.set()
        assert await asyncio.to_thread(self.release.wait, 10)
        if isinstance(self.verdict, Exception):
            raise self.verdict
        return self.verdict


@pytest.mark.parametrize(
    "verdict,expected",
    [
        (True, "completed"),
        (False, "partial"),
        (ValueError("SECRET_PAYLOAD"), "partial"),
    ],
)
def test_two_executors_one_review_and_stable_terminal_state(
    review_db, verdict, expected
):
    provider = HeldReview(verdict)
    first = ExecutionCoordinator(review_db, provider)
    second = ExecutionCoordinator(review_db, provider)
    with ThreadPoolExecutor(2) as executor:
        pending = executor.submit(asyncio.run, first.run("job_review"))
        assert provider.started.wait(5)
        assert asyncio.run(second.run("job_review")) == "processing"
        assert second.finalize_job("job_review") == "processing"
        provider.release.set()
        assert pending.result(timeout=10) == expected
    with review_db() as session:
        job = session.get(JobRecord, "job_review")
        before = (
            job.status,
            job.state_version,
            job.finished_at,
            job.succeeded_item_count,
            job.failed_item_count,
        )
        state = aurora_set_audit.audit_state(
            aurora_set_audit.latest_plan(session, job.id)
        )
        assert before[3:] == (6, 0)
        assert "SECRET_PAYLOAD" not in str(job.error_details)
        assert not aurora_set_audit.commit_result(
            session, job.id, state["token"], True, None
        )
        assert not aurora_set_audit.commit_result(
            session, job.id, state["token"], None, RuntimeError("late")
        )
    assert asyncio.run(second.run("job_review")) == expected
    assert provider.calls == 1
    with review_db() as session:
        job = session.get(JobRecord, "job_review")
        assert before == (
            job.status,
            job.state_version,
            job.finished_at,
            job.succeeded_item_count,
            job.failed_item_count,
        )
        assert session.scalars(select(JobItemRecord.status)).all() == ["succeeded"] * 6


def test_expired_claim_is_not_reissued_and_late_result_is_fenced(review_db):
    with review_db() as session:
        job = session.get(JobRecord, "job_review", with_for_update=True)
        plan = aurora_set_audit.latest_plan(session, job.id)
        token = aurora_set_audit.claim(session, job, plan)
        state = aurora_set_audit.audit_state(plan)
        state["expires_at"] = 0
        aurora_set_audit.store_state(plan, state)
        session.commit()
    provider = HeldReview(True)
    coordinator = ExecutionCoordinator(review_db, provider)
    assert asyncio.run(coordinator.run("job_review")) == "partial"
    assert provider.calls == 0
    with review_db() as session:
        assert not aurora_set_audit.commit_result(
            session, "job_review", token, True, None
        )
        job = session.get(JobRecord, "job_review")
        assert job.error_details["reason"] == "AUDIT_OUTCOME_UNKNOWN"
        assert (job.succeeded_item_count, job.failed_item_count) == (6, 0)


def test_cancel_during_review_preserves_outputs_and_fences_review(review_db):
    provider = HeldReview(True)
    coordinator = ExecutionCoordinator(review_db, provider)
    with ThreadPoolExecutor(1) as executor:
        pending = executor.submit(asyncio.run, coordinator.run("job_review"))
        assert provider.started.wait(5)
        assert coordinator.cancel("job_review") == "cancelled"
        provider.release.set()
        assert pending.result(timeout=10) == "cancelled"
    with review_db() as session:
        assert session.scalars(select(JobItemRecord.status)).all() == ["succeeded"] * 6
        assert (
            aurora_set_audit.audit_state(
                aurora_set_audit.latest_plan(session, "job_review")
            )["status"]
            == "running"
        )
