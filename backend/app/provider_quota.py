"""Durable, fail-closed quotas for the controlled real-provider beta."""

from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .errors import ApiError
from .models import AuditEventRecord, JobRecord, utc_now
from .services import lock_workspace_limits

PROVIDER_JOB_QUOTA_ACTION = "provider.beta_job_reserved"


def reserve_provider_job_quota(
    session: Session,
    *,
    job: JobRecord,
    actor_user_id: str,
    estimated_cost_micros: int,
    provider_request_count: int,
    daily_limit_micros: int,
    monthly_limit_micros: int,
    daily_request_limit: int,
) -> None:
    """Atomically reserve one real-provider job against durable beta limits."""

    values = (
        estimated_cost_micros,
        provider_request_count,
        daily_limit_micros,
        monthly_limit_micros,
        daily_request_limit,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "PROVIDER_QUOTA_INVALID",
            "Real-provider quota values are invalid.",
        )
    if (
        estimated_cost_micros <= 0
        or provider_request_count <= 0
        or daily_limit_micros <= 0
        or monthly_limit_micros < daily_limit_micros
        or daily_request_limit <= 0
    ):
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "PROVIDER_QUOTA_NOT_CONFIGURED",
            "Real-provider quotas are not configured.",
        )

    limits = lock_workspace_limits(session, job.workspace_id)
    effective_daily_limit = min(
        daily_limit_micros,
        int(limits.daily_provider_cost_limit_micros),
    )
    effective_monthly_limit = min(
        monthly_limit_micros,
        int(limits.monthly_provider_cost_limit_micros),
    )
    now = utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    day_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    reservations = session.scalars(
        select(AuditEventRecord).where(
            AuditEventRecord.workspace_id == job.workspace_id,
            AuditEventRecord.action == PROVIDER_JOB_QUOTA_ACTION,
            AuditEventRecord.occurred_at >= month_start,
        )
    ).all()

    daily_cost = 0
    monthly_cost = 0
    daily_requests = 0
    for reservation in reservations:
        details = reservation.details if isinstance(reservation.details, dict) else {}
        cost = details.get("estimated_cost_micros")
        requests = details.get("provider_request_count")
        if (
            isinstance(cost, bool)
            or not isinstance(cost, int)
            or cost < 0
            or isinstance(requests, bool)
            or not isinstance(requests, int)
            or requests < 0
        ):
            raise ApiError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "PROVIDER_QUOTA_LEDGER_INVALID",
                "Real-provider quota ledger is invalid.",
            )
        monthly_cost += cost
        occurred_at = reservation.occurred_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        if occurred_at >= day_start:
            daily_cost += cost
            daily_requests += requests

    if daily_cost + estimated_cost_micros > effective_daily_limit:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "PROVIDER_DAILY_BUDGET_EXCEEDED",
            "The daily real-provider budget is exhausted.",
        )
    if monthly_cost + estimated_cost_micros > effective_monthly_limit:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "PROVIDER_MONTHLY_BUDGET_EXCEEDED",
            "The monthly real-provider budget is exhausted.",
        )
    if daily_requests + provider_request_count > daily_request_limit:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "PROVIDER_DAILY_REQUEST_LIMIT_EXCEEDED",
            "The daily real-provider request limit is exhausted.",
        )

    session.add(
        AuditEventRecord(
            workspace_id=job.workspace_id,
            actor_user_id=actor_user_id,
            action=PROVIDER_JOB_QUOTA_ACTION,
            resource_type="job",
            resource_id=job.id,
            request_id=job.id,
            details={
                "estimated_cost_micros": estimated_cost_micros,
                "provider_request_count": provider_request_count,
                "daily_limit_micros": effective_daily_limit,
                "monthly_limit_micros": effective_monthly_limit,
                "daily_request_limit": daily_request_limit,
            },
        )
    )


def require_provider_job_quota(session: Session, job: JobRecord) -> None:
    """Fail closed when a real provider job bypassed the submit-time gate."""

    reservation = session.scalar(
        select(AuditEventRecord.id)
        .where(
            AuditEventRecord.workspace_id == job.workspace_id,
            AuditEventRecord.action == PROVIDER_JOB_QUOTA_ACTION,
            AuditEventRecord.resource_id == job.id,
            AuditEventRecord.request_id == job.id,
        )
        .limit(1)
    )
    if reservation is None:
        raise RuntimeError("Real provider job has no durable quota reservation.")
