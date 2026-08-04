"""Database-backed job execution, leases, heartbeats, and fencing."""

from __future__ import annotations

import asyncio
import hashlib
import re
import socket
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .config import (
    default_masked_skill_root,
    default_skill_root,
    default_xinghe_skill_root,
)
from .domain import (
    TERMINAL_JOB_STATUSES,
    AssetLifecycleStatus,
    AssetMediaKind,
    AssetOriginKind,
    AttemptStatus,
    JobAssetDirection,
    JobItemStatus,
    JobStatus,
    JobType,
    PlanValidationStatus,
    UsageCompleteness,
)
from .models import (
    AssetRecord,
    AuditEventRecord,
    JobAssetRecord,
    JobAttemptRecord,
    JobItemRecord,
    JobPlanRecord,
    JobRecord,
    UsageEventRecord,
    WorkspaceLimitRecord,
    utc_now,
)
from .provider import (
    PersistedProviderArtifact,
    Provider,
    ProviderOutcome,
    ProviderRequest,
    ProviderResult,
)
from .services import new_id, settle_credits, transition_job
from .skill_runtime import build_fake_skill_runtime_provider
from .storage import ImageStorage, ValidatedImage


class DetailPlanner(Protocol):
    async def plan(self, job_id: str) -> JobStatus | None: ...


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


def _synchronize_job_item_aggregates(
    session: Session,
    job: JobRecord,
) -> None:
    """Keep user-visible counters current without terminalizing the job early."""

    count_rows = session.execute(
        select(JobItemRecord.status, func.count())
        .where(JobItemRecord.job_id == job.id)
        .group_by(JobItemRecord.status)
    ).all()
    counts = {item_status: int(count) for item_status, count in count_rows}
    succeeded = sum(counts.get(value, 0) for value in SUCCESS_ITEM_STATUSES)
    failed = counts.get(JobItemStatus.FAILED.value, 0)
    terminal = sum(
        count
        for item_status, count in counts.items()
        if item_status in TERMINAL_ITEM_STATUSES
    )
    progress = min(
        99,
        max(job.progress, 20 + (80 * terminal // job.expected_item_count)),
    )
    if (
        job.succeeded_item_count,
        job.failed_item_count,
        job.progress,
    ) != (succeeded, failed, progress):
        job.succeeded_item_count = succeeded
        job.failed_item_count = failed
        job.progress = progress
        job.state_version += 1


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
        detail_planner: DetailPlanner | None = None,
        max_concurrency: int = 1,
        max_detail_retries: int = 0,
        artifact_storage: ImageStorage | None = None,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if heartbeat_seconds <= 0 or heartbeat_seconds >= lease_seconds:
            raise ValueError("heartbeat_seconds must be positive and less than lease")
        if max_concurrency < 1 or max_concurrency > 6:
            raise ValueError("max_concurrency must be from 1 through 6")
        if max_detail_retries < 0 or max_detail_retries > 2:
            raise ValueError("max_detail_retries must be from 0 through 2")
        self.session_factory = session_factory
        self.provider = provider
        self.worker_id = worker_id or f"worker-{socket.gethostname()}-{uuid4().hex}"
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.usage_writer = usage_writer or DatabaseUsageEventWriter()
        self.detail_planner = detail_planner
        self.max_concurrency = max_concurrency
        self.max_detail_retries = max_detail_retries
        self.artifact_storage = artifact_storage

    async def run(self, job_id: str) -> JobStatus | None:
        current = self.prepare(job_id)
        if current is None or current in TERMINAL_JOB_STATUSES:
            return current
        if current == JobStatus.CANCELLING:
            return self.cancel(job_id)
        if current == JobStatus.PLANNING:
            if self.detail_planner is None:
                return self.fail_missing_detail_planner(job_id)
            planned = await self.detail_planner.plan(job_id)
            current = self.auto_confirm_detail_plan(job_id, planned)
            if current != JobStatus.PROCESSING:
                return current
        if current == JobStatus.AWAITING_CONFIRMATION:
            current = self.auto_confirm_detail_plan(job_id, current)
            if current != JobStatus.PROCESSING:
                return current

        while True:
            leases: list[AttemptLease] = []
            for _ in range(self.max_concurrency):
                lease = self.claim_next_item(job_id)
                if lease is None:
                    break
                leases.append(lease)
            if not leases:
                break
            await asyncio.gather(
                *(self.execute_lease(lease) for lease in leases)
            )

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
                confirmed_plan = session.scalar(
                    select(JobPlanRecord.id)
                    .where(
                        JobPlanRecord.job_id == job.id,
                        JobPlanRecord.validation_status
                        == PlanValidationStatus.VALID.value,
                        JobPlanRecord.confirmed_at.is_not(None),
                    )
                    .limit(1)
                )
                if confirmed_plan is not None:
                    transition_job(
                        job,
                        JobStatus.PROCESSING,
                        stage="generating",
                        progress=20,
                    )
                    session.commit()
                    return JobStatus.PROCESSING
                transition_job(job, JobStatus.PLANNING, stage="planning", progress=10)
                session.commit()
                return JobStatus.PLANNING
            if current == JobStatus.QUEUED:
                transition_job(
                    job, JobStatus.PROCESSING, stage="processing", progress=20
                )
            session.commit()
            return JobStatus(job.status)

    def auto_confirm_detail_plan(
        self,
        job_id: str,
        planned_status: JobStatus | None,
    ) -> JobStatus | None:
        """Auto-confirm only the explicitly opted-in domestic detail flow."""

        if planned_status != JobStatus.AWAITING_CONFIRMATION:
            return planned_status
        with self.session_factory() as session:
            job = session.get(JobRecord, job_id, with_for_update=True)
            if job is None:
                return None
            settings = job.configuration.get("settings")
            if not isinstance(settings, dict):
                return JobStatus(job.status)
            if (
                job.type != JobType.DETAIL_PACK.value
                or settings.get("market_region") != "domestic"
                or settings.get("auto_start_after_plan") is not True
                or JobStatus(job.status) != JobStatus.AWAITING_CONFIRMATION
            ):
                return JobStatus(job.status)
            plan = session.scalar(
                select(JobPlanRecord)
                .where(JobPlanRecord.job_id == job.id)
                .order_by(JobPlanRecord.revision.desc())
                .limit(1)
                .with_for_update()
            )
            if (
                plan is None
                or plan.validation_status != PlanValidationStatus.VALID.value
            ):
                return JobStatus(job.status)

            from .xinghe_agent import synchronize_confirmed_plan

            synchronize_confirmed_plan(session, job, plan)
            confirmed_at = plan.confirmed_at or utc_now()
            plan.confirmed_at = confirmed_at
            session.add(
                AuditEventRecord(
                    workspace_id=job.workspace_id,
                    actor_user_id=None,
                    action="detail_plan.auto_confirmed",
                    resource_type="job_plan",
                    resource_id=plan.id,
                    request_id=job.id,
                    details={
                        "job_id": job.id,
                        "plan_revision": plan.revision,
                        "market_region": "domestic",
                        "auto_start_after_plan": True,
                        "confirmed_at": confirmed_at.isoformat(),
                    },
                )
            )
            transition_job(
                job,
                JobStatus.PROCESSING,
                stage="generating",
                progress=20,
            )
            session.commit()
            return JobStatus.PROCESSING

    def fail_missing_detail_planner(self, job_id: str) -> JobStatus | None:
        """Fail closed; static/template planning fallback is forbidden."""

        with self.session_factory() as session:
            job = session.get(JobRecord, job_id, with_for_update=True)
            if job is None:
                return None
            if JobStatus(job.status) != JobStatus.PLANNING:
                return JobStatus(job.status)
            now = utc_now()
            items = session.scalars(
                select(JobItemRecord)
                .where(
                    JobItemRecord.job_id == job.id,
                    JobItemRecord.status.in_(
                        [
                            JobItemStatus.PENDING.value,
                            JobItemStatus.QUEUED.value,
                        ]
                    ),
                )
                .with_for_update()
            ).all()
            for item in items:
                item.status = JobItemStatus.FAILED.value
                item.stage = "planning_failed"
                item.error_code = "DETAIL_PLANNER_UNAVAILABLE"
                item.error_message = "The mandatory detail planner is unavailable."
                item.finished_at = now
                item.state_version += 1
            job.failed_item_count = len(items)
            job.error_code = "DETAIL_PLANNER_UNAVAILABLE"
            job.error_message = "The mandatory detail planner is unavailable."
            transition_job(
                job,
                JobStatus.FAILED,
                stage="planning_failed",
                progress=100,
            )
            settle_credits(session, job, 0)
            session.commit()
            return JobStatus.FAILED

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
                select(func.count())
                .select_from(JobAttemptRecord)
                .where(
                    JobAttemptRecord.job_id == job.id,
                    JobAttemptRecord.status.in_(ACTIVE_ATTEMPT_STATUSES),
                    JobAttemptRecord.lease_expires_at > utc_now(),
                )
            )
            if int(active or 0) >= self.max_concurrency:
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
        effective_provider = self._effective_provider_name(result)
        if effective_provider == "mock":
            if result.persisted_artifact is not None:
                await self._delete_persisted_artifact(result.persisted_artifact)
            result = self._without_mock_artifacts(result)
        elif result.artifact is not None:
            result = await self._persist_provider_artifact(lease, result)
        finished = self.finish_attempt(lease, result)
        if result.persisted_artifact is not None and not self._artifact_linked(
            lease,
            result.persisted_artifact,
        ):
            await self._delete_persisted_artifact(result.persisted_artifact)
        return finished

    def _effective_provider_name(self, result: ProviderResult) -> str:
        return result.provider_name or self.provider.name

    @staticmethod
    def _without_mock_artifacts(result: ProviderResult) -> ProviderResult:
        raw_usage = dict(result.raw_usage)
        raw_usage["output_images"] = 0
        for key in ("raw", "normalized"):
            value = raw_usage.get(key)
            if isinstance(value, dict):
                sanitized = dict(value)
                sanitized["output_images"] = 0
                raw_usage[key] = sanitized
        metrics_value = raw_usage.get("metrics")
        metrics = dict(metrics_value) if isinstance(metrics_value, dict) else {}
        metrics["mock_artifact_discarded"] = bool(
            metrics.get("mock_artifact_discarded")
        ) or (
            result.artifact is not None
            or result.persisted_artifact is not None
        )
        raw_usage["metrics"] = metrics
        return replace(
            result,
            raw_usage=raw_usage,
            artifact=None,
            persisted_artifact=None,
        )

    async def _persist_provider_artifact(
        self,
        lease: AttemptLease,
        result: ProviderResult,
    ) -> ProviderResult:
        artifact = result.artifact
        if artifact is None:
            return result
        if self.artifact_storage is None:
            return replace(
                result,
                outcome=ProviderOutcome.FAILED,
                error_code="OUTPUT_STORAGE_UNAVAILABLE",
                error_message="Generated output storage is unavailable.",
                retryable=False,
                artifact=None,
            )
        suffix = (
            ".png"
            if artifact.content_type == "image/png"
            else Path(artifact.filename).suffix or ".bin"
        )
        object_key = (
            f"{lease.workspace_id}/generated/"
            f"{hashlib.sha256(lease.provider_idempotency_key.encode()).hexdigest()}"
            f"{suffix}"
        )
        try:
            stored = await self.artifact_storage.save_validated(
                ValidatedImage(
                    payload=artifact.payload,
                    filename=artifact.filename,
                    content_type=artifact.content_type,
                    width=artifact.width,
                    height=artifact.height,
                    object_key=object_key,
                    sha256=artifact.sha256,
                )
            )
        except Exception as exc:
            return replace(
                result,
                outcome=ProviderOutcome.FAILED,
                error_code="OUTPUT_STORAGE_FAILED",
                error_message=(
                    "Generated output could not be stored "
                    f"({type(exc).__name__})."
                ),
                retryable=False,
                artifact=None,
            )
        raw_usage = dict(result.raw_usage)
        metrics_value = raw_usage.get("metrics")
        metrics = dict(metrics_value) if isinstance(metrics_value, dict) else {}
        metrics["saved_at"] = utc_now().isoformat()
        metrics["locally_resampled"] = artifact.locally_resampled
        metrics["provider_width"] = artifact.provider_width
        metrics["provider_height"] = artifact.provider_height
        raw_usage["metrics"] = metrics
        return replace(
            result,
            raw_usage=raw_usage,
            persisted_artifact=PersistedProviderArtifact(
                filename=stored.filename,
                content_type=stored.content_type,
                byte_size=stored.byte_size,
                width=stored.width,
                height=stored.height,
                sha256=stored.sha256,
                storage_provider=stored.storage_provider,
                storage_bucket=stored.storage_bucket,
                object_key=stored.object_key,
                object_version=stored.object_version,
                etag=stored.etag,
            ),
            artifact=None,
        )

    def _artifact_linked(
        self,
        lease: AttemptLease,
        artifact: PersistedProviderArtifact,
    ) -> bool:
        with self.session_factory() as session:
            return (
                session.scalar(
                    select(JobAssetRecord.id)
                    .join(AssetRecord, AssetRecord.id == JobAssetRecord.asset_id)
                    .where(
                        JobAssetRecord.workspace_id == lease.workspace_id,
                        JobAssetRecord.job_id == lease.job_id,
                        JobAssetRecord.job_item_id == lease.item_id,
                        AssetRecord.object_key == artifact.object_key,
                    )
                    .limit(1)
                )
                is not None
            )

    async def _delete_persisted_artifact(
        self,
        artifact: PersistedProviderArtifact,
    ) -> None:
        if self.artifact_storage is None:
            return
        try:
            await self.artifact_storage.delete_object(
                artifact.object_key,
                artifact.object_version,
            )
        except Exception:
            return

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
        effective_provider = self._effective_provider_name(result)
        if effective_provider == "mock":
            result = self._without_mock_artifacts(result)
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

            expected_dimensions = _expected_delivery_dimensions(item, result)
            if (
                result.outcome == ProviderOutcome.SUCCEEDED
                and result.persisted_artifact is not None
                and expected_dimensions is not None
                and (
                    result.persisted_artifact.width,
                    result.persisted_artifact.height,
                )
                != expected_dimensions
            ):
                result = replace(
                    result,
                    outcome=ProviderOutcome.FAILED,
                    error_code="OUTPUT_DIMENSIONS_INVALID",
                    error_message=(
                        "Generated output does not match the canonical "
                        "delivery dimensions."
                    ),
                    retryable=False,
                )

            if result.persisted_artifact is not None:
                limits = session.get(
                    WorkspaceLimitRecord,
                    job.workspace_id,
                    with_for_update=True,
                )
                used_bytes = session.scalar(
                    select(func.coalesce(func.sum(AssetRecord.byte_size), 0)).where(
                        AssetRecord.workspace_id == job.workspace_id,
                        AssetRecord.lifecycle_status
                        == AssetLifecycleStatus.READY.value,
                        AssetRecord.deleted_at.is_(None),
                    )
                )
                if (
                    limits is None
                    or int(used_bytes or 0)
                    + result.persisted_artifact.byte_size
                    > limits.storage_quota_bytes
                ):
                    result = replace(
                        result,
                        outcome=ProviderOutcome.FAILED,
                        error_code="STORAGE_QUOTA_EXCEEDED",
                        error_message=(
                            "Generated output exceeds the workspace storage quota."
                        ),
                        retryable=False,
                    )

            attempt.provider_request_id = result.provider_request_id
            if result.provider_name:
                attempt.provider = result.provider_name
            attempt.finished_at = now
            attempt.error_code = result.error_code
            attempt.error_message = result.error_message
            if result.outcome == ProviderOutcome.SUCCEEDED:
                attempt.status = AttemptStatus.SUCCEEDED.value
                item.status = JobItemStatus.SUCCEEDED.value
                item.result_source = (
                    "mock" if effective_provider == "mock" else "generated"
                )
                item.error_code = None
                item.error_message = None
                item.error_details = None
            elif result.outcome == ProviderOutcome.FAILED:
                attempt.status = AttemptStatus.FAILED.value
                should_retry = (
                    job.type == JobType.DETAIL_PACK.value
                    and result.retryable
                    and attempt.attempt_no <= self.max_detail_retries
                )
                item.status = (
                    JobItemStatus.PENDING.value
                    if should_retry
                    else JobItemStatus.FAILED.value
                )
                item.stage = "retrying" if should_retry else "failed"
            else:
                attempt.status = AttemptStatus.OUTCOME_UNKNOWN.value
                item.status = JobItemStatus.FAILED.value
                item.error_code = "PROVIDER_OUTCOME_UNKNOWN"
            if result.outcome != ProviderOutcome.SUCCEEDED:
                item.error_code = item.error_code or result.error_code
                item.error_message = result.error_message
                metrics_value = result.raw_usage.get("metrics")
                failure_metrics = (
                    dict(metrics_value)
                    if isinstance(metrics_value, dict)
                    else {}
                )
                delivery_status = failure_metrics.get("delivery_status")
                item.error_details = {
                    "retryable": bool(result.retryable),
                    "needs_reselection": bool(
                        failure_metrics.get("needs_reselection")
                    )
                    or delivery_status == "needs_reselection_for_strict_lock",
                    "provider_outcome": result.outcome.value,
                }
            item.finished_at = (
                None
                if item.status == JobItemStatus.PENDING.value
                else now
            )
            item.state_version += 1

            if (
                result.outcome == ProviderOutcome.SUCCEEDED
                and result.persisted_artifact is not None
            ):
                stored = result.persisted_artifact
                asset_id = new_id("asset")
                metrics_value = result.raw_usage.get("metrics")
                result_metrics = (
                    dict(metrics_value)
                    if isinstance(metrics_value, dict)
                    else {}
                )
                canonical_dimensions = _expected_delivery_dimensions(item, result)
                session.add(
                    AssetRecord(
                        id=asset_id,
                        workspace_id=job.workspace_id,
                        media_kind=AssetMediaKind.IMAGE.value,
                        origin_kind=AssetOriginKind.GENERATED.value,
                        lifecycle_status=AssetLifecycleStatus.READY.value,
                        original_filename=stored.filename,
                        content_type=stored.content_type,
                        byte_size=stored.byte_size,
                        width=stored.width,
                        height=stored.height,
                        sha256=stored.sha256,
                        storage_provider=stored.storage_provider,
                        storage_bucket=stored.storage_bucket,
                        object_key=stored.object_key,
                        object_version=stored.object_version,
                        etag=stored.etag,
                        asset_metadata={
                            "workflow_version": (
                                item.configuration.get("workflow_version")
                            ),
                            "resume_signature": (
                                item.configuration.get("resume_signature")
                            ),
                            "actual_width": stored.width,
                            "actual_height": stored.height,
                            "provider_metrics": result_metrics,
                        },
                    )
                )
                session.add(
                    JobAssetRecord(
                        workspace_id=job.workspace_id,
                        job_id=job.id,
                        job_item_id=item.id,
                        asset_id=asset_id,
                        direction=JobAssetDirection.OUTPUT.value,
                        role=_output_asset_role(job.type),
                        ordinal=item.ordinal,
                        is_deliverable=True,
                        validation={
                            "sha256": stored.sha256,
                            "actual_width": stored.width,
                            "actual_height": stored.height,
                            "requested_size": item.configuration.get("size"),
                            "canonical_width": (
                                canonical_dimensions[0]
                                if canonical_dimensions is not None
                                else None
                            ),
                            "canonical_height": (
                                canonical_dimensions[1]
                                if canonical_dimensions is not None
                                else None
                            ),
                            "locally_resampled": bool(
                                result_metrics.get("locally_resampled", False)
                            ),
                            "provider_width": result_metrics.get("provider_width"),
                            "provider_height": result_metrics.get("provider_height"),
                            "outside_changed_pixels": result_metrics.get(
                                "outside_changed_pixels"
                            ),
                            "raw_visual_success": result_metrics.get(
                                "raw_visual_success"
                            ),
                            "visual_review_summary": result_metrics.get(
                                "visual_review_summary"
                            ),
                            "visual_review_reason_codes": result_metrics.get(
                                "visual_review_reason_codes"
                            ),
                            "visual_review_version": result_metrics.get(
                                "visual_review_version"
                            ),
                            "delivery_status": result_metrics.get(
                                "delivery_status"
                            ),
                        },
                    )
                )

            usage_provider = effective_provider
            usage_model = result.model_name or self.provider.model
            usage_pricing = result.pricing_version or self.provider.pricing_version
            usage_event = UsageEventRecord(
                workspace_id=job.workspace_id,
                job_id=job.id,
                job_item_id=item.id,
                attempt_id=attempt.id,
                provider=usage_provider,
                model=usage_model,
                operation=job.type,
                provider_request_id=result.provider_request_id,
                input_tokens=_usage_count(result.raw_usage, "input_tokens"),
                output_tokens=_usage_count(result.raw_usage, "output_tokens"),
                cached_tokens=_usage_count(result.raw_usage, "cached_tokens"),
                input_image_count=_usage_count(result.raw_usage, "input_images"),
                output_image_count=_usage_count(result.raw_usage, "output_images"),
                quality=item.quality,
                width=(
                    result.persisted_artifact.width
                    if result.persisted_artifact is not None
                    else None
                ),
                height=(
                    result.persisted_artifact.height
                    if result.persisted_artifact is not None
                    else None
                ),
                usage_reported=result.usage_reported,
                raw_usage=result.raw_usage,
                pricing_version=usage_pricing,
                currency=job.currency or "USD",
                estimated_cost_micros=result.estimated_cost_micros,
                actual_cost_micros=result.actual_cost_micros,
            )
            try:
                self.usage_writer.add(session, usage_event)
                if job.type == JobType.DETAIL_PACK.value:
                    from .xinghe_agent import update_job_metrics

                    update_job_metrics(session, job)
                _synchronize_job_item_aggregates(session, job)
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
            _synchronize_job_item_aggregates(session, job)
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
            usage_cost = int(costs[2] or 0)
            planner_count = 0
            planner_reported = 0
            planner_known_cost = 0
            planner_cost = 0
            planner_real_calls = 0
            if job.type == JobType.DETAIL_PACK.value:
                from .xinghe_agent import planner_accounting

                latest_plan = session.scalar(
                    select(JobPlanRecord)
                    .where(JobPlanRecord.job_id == job.id)
                    .order_by(JobPlanRecord.revision.desc())
                    .limit(1)
                )
                if latest_plan is not None:
                    (
                        planner_count,
                        planner_reported,
                        planner_known_cost,
                        planner_cost,
                        planner_real_calls,
                    ) = planner_accounting(latest_plan.payload)
            total_usage_count = usage_count + planner_count
            total_known_cost = known_cost_count + planner_known_cost
            job.actual_cost_micros = (
                usage_cost + planner_cost
                if total_usage_count
                and total_known_cost == total_usage_count
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
            ) + planner_real_calls
            job.usage_completeness = (
                UsageCompleteness.COMPLETE.value
                if total_usage_count
                and reported_count + planner_reported == total_usage_count
                else (
                    UsageCompleteness.PARTIAL.value
                    if reported_count + planner_reported
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
            if job.type == JobType.DETAIL_PACK.value:
                from .xinghe_agent import update_job_metrics

                update_job_metrics(session, job)
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




def _output_asset_role(job_type: str) -> str:
    return {
        JobType.LOCAL_EDIT.value: "local_edit_result",
        JobType.PRODUCT_IMAGE.value: "product_image_result",
        JobType.REFERENCE_REMIX.value: "reference_remix_result",
        JobType.CREATIVE_IMAGE.value: "creative_image_result",
        JobType.DETAIL_PACK.value: "detail_page",
        JobType.AMAZON_VISUAL_SUITE.value: "amazon_visual",
    }.get(job_type, "generated_image")


def _expected_delivery_dimensions(
    item: JobItemRecord,
    result: ProviderResult,
) -> tuple[int, int] | None:
    """Resolve the immutable per-item output contract at the final DB boundary."""

    configuration = (
        item.configuration if isinstance(item.configuration, dict) else {}
    )
    size = configuration.get("size")
    if isinstance(size, str) and re.fullmatch(r"[1-9]\d*x[1-9]\d*", size):
        width_text, height_text = size.split("x", maxsplit=1)
        return int(width_text), int(height_text)
    width = configuration.get("target_width")
    height = configuration.get("target_height")
    if (
        isinstance(width, int)
        and not isinstance(width, bool)
        and width > 0
        and isinstance(height, int)
        and not isinstance(height, bool)
        and height > 0
    ):
        return width, height
    usage_width = result.raw_usage.get("target_width")
    usage_height = result.raw_usage.get("target_height")
    if (
        isinstance(usage_width, int)
        and not isinstance(usage_width, bool)
        and usage_width > 0
        and isinstance(usage_height, int)
        and not isinstance(usage_height, bool)
        and usage_height > 0
    ):
        return usage_width, usage_height
    return None


def build_fake_coordinator(
    session_factory: sessionmaker[Session],
    delay_seconds: float,
    *,
    storage: ImageStorage | None = None,
    xinghe_gateway: object | None = None,
    xinghe_concurrency: int = 6,
    budget_limit_micros: int = 200_000_000,
    medium_price_micros: int = 45_000,
    high_price_micros: int = 90_000,
    xinghe_skill_root: Path | None = None,
    product_image_provider_enabled: bool = False,
    reference_remix_provider_enabled: bool = False,
    creative_image_provider_enabled: bool = False,
    amazon_visual_suite_provider_enabled: bool = False,
    crossborder_detail_provider_enabled: bool = False,
) -> ExecutionCoordinator:
    from .amazon_visual_suite_provider import (
        AMAZON_VISUAL_SUITE_SKILL_ID,
        AmazonVisualSuiteProvider,
    )
    from .creative_image_provider import CreativeImageProvider
    from .domestic_detail_provider import DomesticDetailProvider
    from .new_detail_skill_provider import BundledSkillManifestValidator
    from .product_image_provider import ProductImageProvider
    from .provider_registry import (
        DetailMarketRoutingPlanner,
        RegisteredOperationRoutingProvider,
        UnavailableProvider,
    )
    from .reference_remix_provider import ReferenceRemixProvider
    from .xinghe_agent import (
        FakeXingheGateway,
        XingheGateway,
        XingheImageProvider,
        XinghePlanningCoordinator,
    )

    gateway: XingheGateway
    if xinghe_gateway is None:
        gateway = FakeXingheGateway(delay_seconds=delay_seconds)
    else:
        gateway = cast("XingheGateway", xinghe_gateway)
    skill_root = xinghe_skill_root or default_xinghe_skill_root()
    base_url_signature = str(getattr(gateway, "base_url", "mock://local"))
    planner = XinghePlanningCoordinator(
        session_factory,
        gateway,
        storage=storage,
        skill_root=skill_root,
        base_url_signature=base_url_signature,
        medium_price_micros=medium_price_micros,
        high_price_micros=high_price_micros,
        budget_limit_micros=budget_limit_micros,
    )
    detail_provider: Provider = XingheImageProvider(
        session_factory,
        gateway,
        storage=storage,
        skill_root=skill_root,
        max_concurrency=xinghe_concurrency,
        budget_limit_micros=budget_limit_micros,
    )
    international_planner = planner
    if xinghe_gateway is not None and crossborder_detail_provider_enabled:
        from .crossborder_detail_provider import (
            CROSSBORDER_DETAIL_SKILL_ID,
            CrossborderDetailProvider,
        )

        crossborder_skill_root = default_skill_root(CROSSBORDER_DETAIL_SKILL_ID)
        international_planner = XinghePlanningCoordinator(
            session_factory,
            gateway,
            storage=storage,
            skill_root=crossborder_skill_root,
            base_url_signature=base_url_signature,
            medium_price_micros=medium_price_micros,
            high_price_micros=high_price_micros,
            budget_limit_micros=budget_limit_micros,
            skill_id=CROSSBORDER_DETAIL_SKILL_ID,
        )
        crossborder_detail_delegate = XingheImageProvider(
            session_factory,
            gateway,
            storage=storage,
            skill_root=crossborder_skill_root,
            max_concurrency=xinghe_concurrency,
            budget_limit_micros=budget_limit_micros,
            skill_id=CROSSBORDER_DETAIL_SKILL_ID,
        )
        detail_provider = CrossborderDetailProvider(crossborder_detail_delegate)
    domestic_skill_id = "xinghe-ecommerce-detail-domestic-3"
    domestic_skill_root = default_skill_root(domestic_skill_id)
    domestic_planner = XinghePlanningCoordinator(
        session_factory,
        gateway,
        storage=storage,
        skill_root=domestic_skill_root,
        base_url_signature=base_url_signature,
        medium_price_micros=medium_price_micros,
        high_price_micros=high_price_micros,
        budget_limit_micros=budget_limit_micros,
        skill_id=domestic_skill_id,
    )
    domestic_detail_delegate = XingheImageProvider(
        session_factory,
        gateway,
        storage=storage,
        skill_root=domestic_skill_root,
        max_concurrency=xinghe_concurrency,
        budget_limit_micros=budget_limit_micros,
        skill_id=domestic_skill_id,
    )
    domestic_detail_provider = DomesticDetailProvider(domestic_detail_delegate)
    routed_planner = DetailMarketRoutingPlanner(
        session_factory,
        international_planner,
        domestic_planner,
    )
    default_provider = build_fake_skill_runtime_provider(
        session_factory,
        delay_seconds,
    )
    local_provider: Provider = default_provider
    if xinghe_gateway is not None:
        if storage is None:
            raise ValueError("Real local-edit provider requires image storage.")
        from .masked_repair import MaskedEditGateway, MaskedRepairProvider

        local_provider = MaskedRepairProvider(
            session_factory,
            cast("MaskedEditGateway", gateway),
            storage,
            budget_limit_micros=budget_limit_micros,
            skill_root=default_masked_skill_root(),
        )
    manifest_validator = BundledSkillManifestValidator()
    if xinghe_gateway is None:
        new_routes: dict[str, Provider] = {
            JobType.PRODUCT_IMAGE.value: default_provider,
            JobType.REFERENCE_REMIX.value: default_provider,
            JobType.CREATIVE_IMAGE.value: default_provider,
            JobType.AMAZON_VISUAL_SUITE.value: AmazonVisualSuiteProvider(
                default_provider,
                manifest_validator=manifest_validator,
            ),
        }
    else:
        def single_image_delegate(
            enabled: bool,
            operation: str,
            skill_id: str,
        ) -> Provider:
            if not enabled:
                return UnavailableProvider()
            if storage is None:
                raise ValueError("Real single-image provider requires image storage.")
            from .xinghe_single_image_provider import XingheSingleImageProvider

            skill_root = default_skill_root(skill_id)
            delegate_manifest_validator = BundledSkillManifestValidator(
                source_roots={skill_id: skill_root}
            )
            return XingheSingleImageProvider(
                session_factory,
                gateway,
                storage=storage,
                operation=operation,
                skill_id=skill_id,
                manifest_validator=delegate_manifest_validator.validate,
                max_concurrency=xinghe_concurrency,
            )

        new_routes = {
            JobType.PRODUCT_IMAGE.value: ProductImageProvider(
                single_image_delegate(
                    product_image_provider_enabled,
                    JobType.PRODUCT_IMAGE.value,
                    ProductImageProvider.skill_id,
                ),
                manifest_validator=manifest_validator.validate,
            ),
            JobType.REFERENCE_REMIX.value: ReferenceRemixProvider(
                single_image_delegate(
                    reference_remix_provider_enabled,
                    JobType.REFERENCE_REMIX.value,
                    ReferenceRemixProvider.skill_id,
                ),
                manifest_validator=manifest_validator.validate,
            ),
            JobType.CREATIVE_IMAGE.value: CreativeImageProvider(
                single_image_delegate(
                    creative_image_provider_enabled,
                    JobType.CREATIVE_IMAGE.value,
                    CreativeImageProvider.skill_id,
                ),
                manifest_validator=manifest_validator.validate,
            ),
            JobType.AMAZON_VISUAL_SUITE.value: AmazonVisualSuiteProvider(
                single_image_delegate(
                    amazon_visual_suite_provider_enabled,
                    JobType.AMAZON_VISUAL_SUITE.value,
                    AMAZON_VISUAL_SUITE_SKILL_ID,
                ),
                manifest_validator=manifest_validator,
            ),
        }
    provider = RegisteredOperationRoutingProvider(
        default_provider,
        detail_provider,
        local_provider,
        new_routes,
        domestic_detail_provider=domestic_detail_provider,
    )
    return ExecutionCoordinator(
        session_factory,
        provider,
        detail_planner=routed_planner,
        max_concurrency=xinghe_concurrency,
        max_detail_retries=2,
        artifact_storage=storage,
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
