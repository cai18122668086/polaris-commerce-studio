"""Database-backed job execution, leases, heartbeats, and fencing."""

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .domain import (
    TERMINAL_JOB_STATUSES,
    AttemptStatus,
    JobItemStatus,
    JobStatus,
    JobType,
    PlanValidationStatus,
    UsageCompleteness,
)
from .models import (
    AuditEventRecord,
    JobAttemptRecord,
    JobItemRecord,
    JobPlanRecord,
    JobRecord,
    UsageEventRecord,
    utc_now,
)
from .provider import (
    Provider,
    ProviderOutcome,
    ProviderRequest,
    ProviderResult,
)
from .services import canonical_hash, new_id, settle_credits, transition_job
from .skill_runtime import build_fake_skill_runtime_provider

ACTIVE_ATTEMPT_STATUSES = {
    AttemptStatus.CLAIMED.value,
    AttemptStatus.RUNNING.value,
}
TERMINAL_ITEM_STATUSES = {
    JobItemStatus.SUCCEEDED.value,
    JobItemStatus.FAILED.value,
    JobItemStatus.CANCELLED.value,
    JobItemStatus.SKIPPED.value,
    JobItemStatus.REUSED.value,
}
SUCCESS_ITEM_STATUSES = {
    JobItemStatus.SUCCEEDED.value,
    JobItemStatus.REUSED.value,
}


@dataclass(frozen=True)
class AttemptLease:
    workspace_id: str
    job_id: str
    item_id: str
    attempt_id: str
    lease_token: str
    provider_idempotency_key: str
    operation: str
    configuration: dict[str, object]


class UsageEventWriter(Protocol):
    def add(self, session: Session, event: UsageEventRecord) -> None: ...


class DatabaseUsageEventWriter:
    def add(self, session: Session, event: UsageEventRecord) -> None:
        session.add(event)


class ExecutionCoordinator:
    """Coordinates execution exclusively through PostgreSQL-visible state."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        provider: Provider,
        *,
        worker_id: str | None = None,
        lease_seconds: float = 30,
        heartbeat_seconds: float = 10,
        usage_writer: UsageEventWriter | None = None,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if heartbeat_seconds <= 0 or heartbeat_seconds >= lease_seconds:
            raise ValueError("heartbeat_seconds must be positive and less than lease")
        self.session_factory = session_factory
        self.provider = provider
        self.worker_id = worker_id or f"worker-{socket.gethostname()}-{uuid4().hex}"
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.usage_writer = usage_writer or DatabaseUsageEventWriter()

    async def run(self, job_id: str) -> JobStatus | None:
        current = self.prepare(job_id)
        if current is None or current in TERMINAL_JOB_STATUSES:
            return current
        if current == JobStatus.CANCELLING:
            return self.cancel(job_id)
        if current == JobStatus.PLANNING:
            return self.finish_fake_plan(job_id)
        if current == JobStatus.AWAITING_CONFIRMATION:
            return current

        while True:
            lease = self.claim_next_item(job_id)
            if lease is None:
                break
            await self.execute_lease(lease)

        return self.finalize_job(job_id)

    def prepare(self, job_id: str) -> JobStatus | None:
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

    def finish_fake_plan(self, job_id: str) -> JobStatus | None:
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id, with_for_update=True)
            if job is None:
                return None
            if JobStatus(job.status) != JobStatus.PLANNING:
                return JobStatus(job.status)
            existing = session.scalar(
                select(JobPlanRecord)
                .where(JobPlanRecord.job_id == job.id)
                .order_by(JobPlanRecord.revision.desc())
                .limit(1)
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
                        validator_version="phase1.2a-fake",
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

    def claim_next_item(self, job_id: str) -> AttemptLease | None:
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id, with_for_update=True)
            if job is None:
                return None
            current = JobStatus(job.status)
            if current in TERMINAL_JOB_STATUSES or current in {
                JobStatus.CANCELLING,
                JobStatus.AWAITING_CONFIRMATION,
            }:
                return None

            recovered, expired_handled = self._recover_expired_attempt(session, job)
            if expired_handled:
                session.commit()
            if recovered is not None:
                return recovered

            active = session.scalar(
                select(JobAttemptRecord.id)
                .where(
                    JobAttemptRecord.job_id == job.id,
                    JobAttemptRecord.status.in_(ACTIVE_ATTEMPT_STATUSES),
                    JobAttemptRecord.lease_expires_at > utc_now(),
                )
                .limit(1)
            )
            if active is not None:
                return None

            item = session.scalar(
                select(JobItemRecord)
                .where(
                    JobItemRecord.job_id == job.id,
                    JobItemRecord.status.in_(
                        [JobItemStatus.PENDING.value, JobItemStatus.QUEUED.value]
                    ),
                )
                .order_by(JobItemRecord.ordinal)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if item is None:
                return None

            previous_version = item.state_version
            claimed_id = session.scalar(
                update(JobItemRecord)
                .where(
                    JobItemRecord.id == item.id,
                    JobItemRecord.job_id == job.id,
                    JobItemRecord.state_version == previous_version,
                    JobItemRecord.status.in_(
                        [JobItemStatus.PENDING.value, JobItemStatus.QUEUED.value]
                    ),
                )
                .values(
                    status=JobItemStatus.RUNNING.value,
                    started_at=func.coalesce(JobItemRecord.started_at, utc_now()),
                    attempt_count=JobItemRecord.attempt_count + 1,
                    state_version=JobItemRecord.state_version + 1,
                )
                .returning(JobItemRecord.id)
            )
            if claimed_id is None:
                session.rollback()
                return None

            session.refresh(item)
            lease = self._new_attempt(job, item)
            session.add(lease)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                return None
            return self._lease_from_records(job, item, lease)

    def _recover_expired_attempt(
        self, session: Session, job: JobRecord
    ) -> tuple[AttemptLease | None, bool]:
        now = utc_now()
        attempt = session.scalar(
            select(JobAttemptRecord)
            .where(
                JobAttemptRecord.job_id == job.id,
                JobAttemptRecord.status.in_(ACTIVE_ATTEMPT_STATUSES),
                JobAttemptRecord.lease_expires_at <= now,
            )
            .order_by(JobAttemptRecord.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if attempt is None:
            return None, False
        item = session.get(JobItemRecord, attempt.job_item_id, with_for_update=True)
        if item is None:
            attempt.status = AttemptStatus.FAILED.value
            attempt.error_code = "JOB_ITEM_MISSING"
            attempt.finished_at = now
            return None, True
        if attempt.status == AttemptStatus.CLAIMED.value:
            attempt.lease_token = uuid4().hex
            attempt.leased_by = self.worker_id
            attempt.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            return self._lease_from_records(job, item, attempt), True

        # RUNNING is the durable provider-call boundary.  Once its lease expires
        # the result is unknown and the request must never be issued blindly.
        attempt.status = AttemptStatus.OUTCOME_UNKNOWN.value
        attempt.error_code = "PROVIDER_OUTCOME_UNKNOWN"
        attempt.error_message = "Worker lease expired after provider invocation."
        attempt.finished_at = now
        item.status = JobItemStatus.FAILED.value
        item.error_code = "PROVIDER_OUTCOME_UNKNOWN"
        item.error_message = (
            "Provider outcome is unknown; manual reconciliation required."
        )
        item.finished_at = now
        item.state_version += 1
        return None, True

    def _new_attempt(
        self, job: JobRecord, item: JobItemRecord
    ) -> JobAttemptRecord:
        attempt_no = item.attempt_count
        return JobAttemptRecord(
            id=new_id("attempt"),
            workspace_id=job.workspace_id,
            job_id=job.id,
            job_item_id=item.id,
            attempt_no=attempt_no,
            status=AttemptStatus.CLAIMED.value,
            lease_token=uuid4().hex,
            leased_by=self.worker_id,
            lease_expires_at=utc_now() + timedelta(seconds=self.lease_seconds),
            provider=self.provider.name,
            operation=job.type,
            provider_idempotency_key=f"{job.id}:{item.id}:{attempt_no}",
        )

    @staticmethod
    def _lease_from_records(
        job: JobRecord,
        item: JobItemRecord,
        attempt: JobAttemptRecord,
    ) -> AttemptLease:
        return AttemptLease(
            workspace_id=job.workspace_id,
            job_id=job.id,
            item_id=item.id,
            attempt_id=attempt.id,
            lease_token=attempt.lease_token,
            provider_idempotency_key=attempt.provider_idempotency_key,
            operation=attempt.operation,
            configuration={
                "job": dict(job.configuration),
                "item": dict(item.configuration),
            },
        )

    async def execute_lease(self, lease: AttemptLease) -> bool:
        if not self.mark_provider_started(lease):
            return False
        request = ProviderRequest(
            workspace_id=lease.workspace_id,
            job_id=lease.job_id,
            job_item_id=lease.item_id,
            attempt_id=lease.attempt_id,
            operation=lease.operation,
            idempotency_key=lease.provider_idempotency_key,
            configuration=lease.configuration,
        )
        provider_task = asyncio.create_task(self.provider.execute(request))
        while not provider_task.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(provider_task),
                    timeout=self.heartbeat_seconds,
                )
            except TimeoutError:
                if not self.renew_lease(lease):
                    provider_task.cancel()
                    return False
        result = await provider_task
        return self.finish_attempt(lease, result)

    def mark_provider_started(self, lease: AttemptLease) -> bool:
        now = utc_now()
        with self.session_factory() as session:
            changed_id = session.scalar(
                update(JobAttemptRecord)
                .where(
                    JobAttemptRecord.id == lease.attempt_id,
                    JobAttemptRecord.job_id == lease.job_id,
                    JobAttemptRecord.job_item_id == lease.item_id,
                    JobAttemptRecord.lease_token == lease.lease_token,
                    JobAttemptRecord.leased_by == self.worker_id,
                    JobAttemptRecord.status == AttemptStatus.CLAIMED.value,
                    JobAttemptRecord.lease_expires_at > now,
                )
                .values(status=AttemptStatus.RUNNING.value, started_at=now)
                .returning(JobAttemptRecord.id)
            )
            session.commit()
            return changed_id is not None

    def renew_lease(self, lease: AttemptLease) -> bool:
        now = utc_now()
        with self.session_factory() as session:
            changed_id = session.scalar(
                update(JobAttemptRecord)
                .where(
                    JobAttemptRecord.id == lease.attempt_id,
                    JobAttemptRecord.lease_token == lease.lease_token,
                    JobAttemptRecord.leased_by == self.worker_id,
                    JobAttemptRecord.status.in_(ACTIVE_ATTEMPT_STATUSES),
                    JobAttemptRecord.lease_expires_at > now,
                )
                .values(
                    lease_expires_at=now + timedelta(seconds=self.lease_seconds)
                )
                .returning(JobAttemptRecord.id)
            )
            session.commit()
            return changed_id is not None

    def finish_attempt(
        self,
        lease: AttemptLease,
        result: ProviderResult,
    ) -> bool:
        now = utc_now()
        with self.session_factory() as session:
            job = session.get(JobRecord, lease.job_id, with_for_update=True)
            item = session.get(JobItemRecord, lease.item_id, with_for_update=True)
            attempt = session.get(
                JobAttemptRecord, lease.attempt_id, with_for_update=True
            )
            if job is None or item is None or attempt is None:
                return False
            if JobStatus(job.status) in TERMINAL_JOB_STATUSES or JobStatus(
                job.status
            ) == JobStatus.CANCELLING:
                return False
            if (
                attempt.lease_token != lease.lease_token
                or attempt.leased_by != self.worker_id
                or attempt.status != AttemptStatus.RUNNING.value
                or _lease_expired(attempt.lease_expires_at, now)
                or item.status != JobItemStatus.RUNNING.value
            ):
                return False

            attempt.provider_request_id = result.provider_request_id
            attempt.finished_at = now
            attempt.error_code = result.error_code
            attempt.error_message = result.error_message
            if result.outcome == ProviderOutcome.SUCCEEDED:
                attempt.status = AttemptStatus.SUCCEEDED.value
                item.status = JobItemStatus.SUCCEEDED.value
                item.result_source = "generated"
            elif result.outcome == ProviderOutcome.FAILED:
                attempt.status = AttemptStatus.FAILED.value
                item.status = JobItemStatus.FAILED.value
            else:
                attempt.status = AttemptStatus.OUTCOME_UNKNOWN.value
                item.status = JobItemStatus.FAILED.value
                item.error_code = "PROVIDER_OUTCOME_UNKNOWN"
            item.error_code = item.error_code or result.error_code
            item.error_message = result.error_message
            item.finished_at = now
            item.state_version += 1

            usage_event = UsageEventRecord(
                workspace_id=job.workspace_id,
                job_id=job.id,
                job_item_id=item.id,
                attempt_id=attempt.id,
                provider=self.provider.name,
                model=self.provider.model,
                operation=job.type,
                provider_request_id=result.provider_request_id,
                input_tokens=_usage_count(result.raw_usage, "input_tokens"),
                output_tokens=_usage_count(result.raw_usage, "output_tokens"),
                cached_tokens=_usage_count(result.raw_usage, "cached_tokens"),
                input_image_count=_usage_count(result.raw_usage, "input_images"),
                output_image_count=_usage_count(result.raw_usage, "output_images"),
                usage_reported=result.usage_reported,
                raw_usage=result.raw_usage,
                pricing_version=self.provider.pricing_version,
                currency=job.currency or "USD",
                estimated_cost_micros=result.estimated_cost_micros,
                actual_cost_micros=result.actual_cost_micros,
            )
            try:
                self.usage_writer.add(session, usage_event)
                session.commit()
                return True
            except Exception as exc:
                session.rollback()
                usage_error_type = type(exc).__name__
        return self._fail_closed_on_usage_error(
            lease,
            result,
            usage_error_type,
        )

    def _fail_closed_on_usage_error(
        self,
        lease: AttemptLease,
        result: ProviderResult,
        usage_error_type: str,
    ) -> bool:
        """Persist a controlled failure when usage cannot be recorded."""

        now = utc_now()
        with self.session_factory() as session:
            job = session.get(JobRecord, lease.job_id, with_for_update=True)
            item = session.get(JobItemRecord, lease.item_id, with_for_update=True)
            attempt = session.get(
                JobAttemptRecord, lease.attempt_id, with_for_update=True
            )
            if job is None or item is None or attempt is None:
                return False
            if (
                job.workspace_id != lease.workspace_id
                or item.workspace_id != lease.workspace_id
                or attempt.workspace_id != lease.workspace_id
                or attempt.lease_token != lease.lease_token
                or attempt.leased_by != self.worker_id
                or attempt.status != AttemptStatus.RUNNING.value
                or item.status != JobItemStatus.RUNNING.value
            ):
                return False
            attempt.status = AttemptStatus.FAILED.value
            attempt.provider_request_id = result.provider_request_id
            attempt.error_code = "USAGE_RECORD_FAILED"
            attempt.error_message = "Usage could not be recorded; execution closed."
            attempt.finished_at = now
            item.status = JobItemStatus.FAILED.value
            item.error_code = "USAGE_RECORD_FAILED"
            item.error_message = "Usage could not be recorded; execution closed."
            item.finished_at = now
            item.state_version += 1
            session.add(
                AuditEventRecord(
                    workspace_id=lease.workspace_id,
                    action="skill_runtime.usage_record_failed",
                    resource_type="job",
                    resource_id=lease.job_id,
                    request_id=lease.attempt_id,
                    details={
                        "attempt_id": lease.attempt_id,
                        "job_item_id": lease.item_id,
                        "provider_type": self.provider.name,
                        "error_code": "USAGE_RECORD_FAILED",
                        "usage_error_type": usage_error_type,
                    },
                )
            )
            session.commit()
            return True

    def finalize_job(self, job_id: str) -> JobStatus | None:
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id, with_for_update=True)
            if job is None:
                return None
            current = JobStatus(job.status)
            if current in TERMINAL_JOB_STATUSES:
                return current

            count_rows = session.execute(
                    select(JobItemRecord.status, func.count())
                    .where(JobItemRecord.job_id == job.id)
                    .group_by(JobItemRecord.status)
                ).all()
            counts: dict[str, int] = {
                item_status: int(count) for item_status, count in count_rows
            }
            nonterminal = sum(
                count
                for item_status, count in counts.items()
                if item_status not in TERMINAL_ITEM_STATUSES
            )
            if nonterminal:
                return current

            succeeded = sum(counts.get(value, 0) for value in SUCCESS_ITEM_STATUSES)
            failed = counts.get(JobItemStatus.FAILED.value, 0)
            cancelled = counts.get(JobItemStatus.CANCELLED.value, 0)
            job.succeeded_item_count = succeeded
            job.failed_item_count = failed

            costs = session.execute(
                select(
                    func.count(UsageEventRecord.id),
                    func.count(UsageEventRecord.actual_cost_micros),
                    func.sum(UsageEventRecord.actual_cost_micros),
                ).where(UsageEventRecord.job_id == job.id)
            ).one()
            reported_count = (
                session.scalar(
                    select(func.count())
                    .select_from(UsageEventRecord)
                    .where(
                        UsageEventRecord.job_id == job.id,
                        UsageEventRecord.usage_reported.is_(True),
                    )
                )
                or 0
            )
            usage_count = int(costs[0] or 0)
            known_cost_count = int(costs[1] or 0)
            job.actual_cost_micros = (
                int(costs[2])
                if usage_count and known_cost_count == usage_count
                else None
            )
            job.actual_credits = 0 if usage_count else None
            job.api_request_count = (
                session.scalar(
                    select(func.count())
                    .select_from(UsageEventRecord)
                    .where(
                        UsageEventRecord.job_id == job.id,
                        UsageEventRecord.provider != "mock",
                    )
                )
                or 0
            )
            job.usage_completeness = (
                UsageCompleteness.COMPLETE.value
                if usage_count and reported_count == usage_count
                else (
                    UsageCompleteness.PARTIAL.value
                    if reported_count
                    else UsageCompleteness.NONE.value
                )
            )

            if current == JobStatus.CANCELLING:
                target = JobStatus.CANCELLED
            elif succeeded == job.expected_item_count:
                target = JobStatus.COMPLETED
            elif succeeded:
                target = JobStatus.PARTIAL
            elif cancelled == job.expected_item_count:
                target = JobStatus.CANCELLED
            else:
                target = JobStatus.FAILED
            transition_job(job, target, stage=target.value, progress=100)
            settle_credits(session, job, job.actual_credits or 0)
            session.commit()
            return target

    def cancel(self, job_id: str) -> JobStatus | None:
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id, with_for_update=True)
            if job is None:
                return None
            current = JobStatus(job.status)
            if current in TERMINAL_JOB_STATUSES:
                return current
            if current != JobStatus.CANCELLING:
                transition_job(job, JobStatus.CANCELLING, progress=job.progress)
            now = utc_now()
            attempts = session.scalars(
                select(JobAttemptRecord)
                .where(
                    JobAttemptRecord.job_id == job.id,
                    JobAttemptRecord.status.in_(ACTIVE_ATTEMPT_STATUSES),
                )
                .with_for_update()
            ).all()
            for attempt in attempts:
                attempt.status = (
                    AttemptStatus.CANCELLED.value
                    if attempt.status == AttemptStatus.CLAIMED.value
                    else AttemptStatus.OUTCOME_UNKNOWN.value
                )
                if attempt.status == AttemptStatus.OUTCOME_UNKNOWN.value:
                    attempt.error_code = "PROVIDER_OUTCOME_UNKNOWN"
                attempt.finished_at = now
            items = session.scalars(
                select(JobItemRecord)
                .where(
                    JobItemRecord.job_id == job.id,
                    JobItemRecord.status.in_(
                        [
                            JobItemStatus.PENDING.value,
                            JobItemStatus.QUEUED.value,
                            JobItemStatus.RUNNING.value,
                        ]
                    ),
                )
                .with_for_update()
            ).all()
            for item in items:
                item.status = JobItemStatus.CANCELLED.value
                item.finished_at = now
                item.state_version += 1
            session.commit()
        return self.finalize_job(job_id)


def build_fake_coordinator(
    session_factory: sessionmaker[Session],
    delay_seconds: float,
) -> ExecutionCoordinator:
    return ExecutionCoordinator(
        session_factory,
        build_fake_skill_runtime_provider(session_factory, delay_seconds),
    )


def _lease_expired(expires_at: datetime, now: datetime) -> bool:
    """Compare PostgreSQL-aware and SQLite-naive timestamps consistently."""

    if expires_at.tzinfo is None and now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    return expires_at <= now


def _usage_count(raw_usage: dict[str, object], key: str) -> int | None:
    value = raw_usage.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value
