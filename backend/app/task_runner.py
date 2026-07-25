import asyncio
import socket
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .domain import (
    TERMINAL_JOB_STATUSES,
    AttemptStatus,
    JobItemStatus,
    JobStatus,
    JobType,
    PlanValidationStatus,
)
from .models import (
    JobAttemptRecord,
    JobItemRecord,
    JobPlanRecord,
    JobRecord,
    UsageEventRecord,
    utc_now,
)
from .services import canonical_hash, new_id, settle_credits, transition_job


class MockTaskRunner:
    """Production-shaped executor that never invokes an external image service."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        delay_seconds: float,
    ) -> None:
        self.session_factory = session_factory
        self.delay_seconds = delay_seconds
        self.worker_id = f"mock-{socket.gethostname()}"

    async def run(self, job_id: str) -> JobStatus | None:
        status = self._prepare(job_id)
        if status is None or status in TERMINAL_JOB_STATUSES:
            return status
        if status == JobStatus.CANCELLING:
            return await self.cancel(job_id)
        if status == JobStatus.PLANNING:
            await asyncio.sleep(self.delay_seconds)
            return self._finish_mock_plan(job_id)
        if status == JobStatus.AWAITING_CONFIRMATION:
            return status

        while True:
            claim = self._claim_next_item(job_id)
            if claim is None:
                break
            item_id, attempt_id = claim
            await asyncio.sleep(self.delay_seconds)
            self._finish_attempt(job_id, item_id, attempt_id)
        result = self._finish_job(job_id)
        if result == JobStatus.CANCELLING:
            return await self.cancel(job_id)
        return result

    async def cancel(self, job_id: str) -> JobStatus | None:
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id)
            if job is None:
                return None
            current = JobStatus(job.status)
            if current == JobStatus.CANCELLED:
                return current
            if current in TERMINAL_JOB_STATUSES:
                return current
            if current != JobStatus.CANCELLING:
                transition_job(job, JobStatus.CANCELLING, progress=job.progress)
            items = session.scalars(
                select(JobItemRecord).where(
                    JobItemRecord.job_id == job.id,
                    JobItemRecord.status.in_(
                        [
                            JobItemStatus.PENDING.value,
                            JobItemStatus.QUEUED.value,
                            JobItemStatus.RUNNING.value,
                        ]
                    ),
                )
            ).all()
            for item in items:
                item.status = JobItemStatus.CANCELLED.value
                item.finished_at = utc_now()
                item.state_version += 1
            attempts = session.scalars(
                select(JobAttemptRecord).where(
                    JobAttemptRecord.job_id == job.id,
                    JobAttemptRecord.status.in_(
                        [AttemptStatus.CLAIMED.value, AttemptStatus.RUNNING.value]
                    ),
                )
            ).all()
            for attempt in attempts:
                attempt.status = AttemptStatus.CANCELLED.value
                attempt.finished_at = utc_now()
            transition_job(job, JobStatus.CANCELLED, progress=job.progress)
            settle_credits(session, job, 0)
            session.commit()
            return JobStatus.CANCELLED

    def _prepare(self, job_id: str) -> JobStatus | None:
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id, with_for_update=True)
            if job is None:
                return None
            current = JobStatus(job.status)
            if current in TERMINAL_JOB_STATUSES or current in {
                JobStatus.CANCELLING,
                JobStatus.AWAITING_CONFIRMATION,
            }:
                return current
            if current == JobStatus.QUEUED and job.type == JobType.DETAIL_PACK.value:
                transition_job(job, JobStatus.PLANNING, stage="planning", progress=10)
                session.commit()
                return JobStatus.PLANNING
            if current == JobStatus.QUEUED:
                transition_job(
                    job, JobStatus.PROCESSING, stage="processing", progress=20
                )
            session.commit()
            return JobStatus(job.status)

    def _finish_mock_plan(self, job_id: str) -> JobStatus | None:
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id, with_for_update=True)
            if job is None:
                return None
            if JobStatus(job.status) != JobStatus.PLANNING:
                return JobStatus(job.status)
            existing = session.scalar(
                select(JobPlanRecord).where(JobPlanRecord.job_id == job.id).limit(1)
            )
            if existing is None:
                payload = {
                    "pages": [
                        {
                            "item_key": f"page-{index + 1:03d}",
                            "title": f"详情页 {index + 1}",
                            "quality": "medium",
                        }
                        for index in range(job.expected_item_count)
                    ],
                    "mock": True,
                }
                session.add(
                    JobPlanRecord(
                        id=new_id("plan"),
                        workspace_id=job.workspace_id,
                        job_id=job.id,
                        revision=1,
                        schema_version="v1",
                        payload=payload,
                        payload_hash=canonical_hash(payload),
                        validation_status=PlanValidationStatus.VALID.value,
                        validation_errors=[],
                        validator_version="phase1.1-mock",
                        validated_at=utc_now(),
                    )
                )
            transition_job(
                job,
                JobStatus.AWAITING_CONFIRMATION,
                stage="awaiting_confirmation",
                progress=15,
            )
            session.commit()
            return JobStatus.AWAITING_CONFIRMATION

    def _claim_next_item(self, job_id: str) -> tuple[str, str] | None:
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id, with_for_update=True)
            if job is None or JobStatus(job.status) in TERMINAL_JOB_STATUSES:
                return None
            if JobStatus(job.status) == JobStatus.CANCELLING:
                return None
            item = session.scalar(
                select(JobItemRecord)
                .where(
                    JobItemRecord.job_id == job.id,
                    JobItemRecord.status == JobItemStatus.PENDING.value,
                )
                .order_by(JobItemRecord.ordinal)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if item is None:
                return None
            existing_success = session.scalar(
                select(JobAttemptRecord).where(
                    JobAttemptRecord.job_item_id == item.id,
                    JobAttemptRecord.status == AttemptStatus.SUCCEEDED.value,
                )
            )
            if existing_success is not None:
                item.status = JobItemStatus.SUCCEEDED.value
                session.commit()
                return None
            attempt_no = item.attempt_count + 1
            attempt = JobAttemptRecord(
                id=new_id("attempt"),
                workspace_id=job.workspace_id,
                job_id=job.id,
                job_item_id=item.id,
                attempt_no=attempt_no,
                status=AttemptStatus.RUNNING.value,
                lease_token=uuid4().hex,
                leased_by=self.worker_id,
                lease_expires_at=utc_now() + timedelta(minutes=5),
                provider="mock",
                operation=job.type,
                provider_idempotency_key=f"{job.id}:{item.id}:{attempt_no}",
                started_at=utc_now(),
            )
            item.status = JobItemStatus.RUNNING.value
            item.started_at = item.started_at or utc_now()
            item.attempt_count = attempt_no
            item.state_version += 1
            session.add(attempt)
            session.commit()
            return item.id, attempt.id

    def _finish_attempt(self, job_id: str, item_id: str, attempt_id: str) -> None:
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id, with_for_update=True)
            item = session.get(JobItemRecord, item_id, with_for_update=True)
            attempt = session.get(JobAttemptRecord, attempt_id, with_for_update=True)
            if job is None or item is None or attempt is None:
                return
            if JobStatus(job.status) == JobStatus.CANCELLING:
                attempt.status = AttemptStatus.CANCELLED.value
                item.status = JobItemStatus.CANCELLED.value
                attempt.finished_at = utc_now()
                item.finished_at = utc_now()
                session.commit()
                return
            if attempt.status == AttemptStatus.SUCCEEDED.value:
                return
            attempt.status = AttemptStatus.SUCCEEDED.value
            attempt.finished_at = utc_now()
            item.status = JobItemStatus.SUCCEEDED.value
            item.result_source = "generated"
            item.finished_at = utc_now()
            item.state_version += 1
            session.add(
                UsageEventRecord(
                    workspace_id=job.workspace_id,
                    job_id=job.id,
                    job_item_id=item.id,
                    attempt_id=attempt.id,
                    provider="mock",
                    model="none",
                    operation=job.type,
                    provider_request_id=None,
                    input_image_count=0,
                    output_image_count=0,
                    usage_reported=False,
                    raw_usage={"reason": "phase1.1_mock_runner"},
                    pricing_version="phase1.1-mock",
                    currency=job.currency or "USD",
                    estimated_cost_micros=0,
                    actual_cost_micros=0,
                )
            )
            session.commit()

    def _finish_job(self, job_id: str) -> JobStatus | None:
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id, with_for_update=True)
            if job is None:
                return None
            current = JobStatus(job.status)
            if current == JobStatus.CANCELLING:
                return current
            if current in TERMINAL_JOB_STATUSES:
                return current
            succeeded = (
                session.scalar(
                    select(func.count())
                    .select_from(JobItemRecord)
                    .where(
                        JobItemRecord.job_id == job.id,
                        JobItemRecord.status.in_(
                            [
                                JobItemStatus.SUCCEEDED.value,
                                JobItemStatus.REUSED.value,
                            ]
                        ),
                    )
                )
                or 0
            )
            failed = (
                session.scalar(
                    select(func.count())
                    .select_from(JobItemRecord)
                    .where(
                        JobItemRecord.job_id == job.id,
                        JobItemRecord.status == JobItemStatus.FAILED.value,
                    )
                )
                or 0
            )
            job.succeeded_item_count = succeeded
            job.failed_item_count = failed
            job.actual_cost_micros = 0
            job.actual_credits = 0
            job.api_request_count = 0
            job.usage_completeness = "none"
            if succeeded == job.expected_item_count:
                target = JobStatus.COMPLETED
            elif succeeded > 0:
                target = JobStatus.PARTIAL
            else:
                target = JobStatus.FAILED
            transition_job(job, target, stage=target.value, progress=100)
            settle_credits(session, job, 0)
            session.commit()
            return target
