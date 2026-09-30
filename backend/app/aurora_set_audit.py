"""Durable, single-dispatch set review; generation rows are never review state."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain import TERMINAL_JOB_STATUSES, JobStatus
from .models import AuditEventRecord, JobPlanRecord, JobRecord, utc_now
from .services import canonical_hash

AUDIT_KEY = "_set_audit_execution"
AUDIT_TIMEOUT_SECONDS = 900


@dataclass(frozen=True)
class SetAuditResult:
    passed: bool
    observation: dict[str, Any]


def latest_plan(session: Session, job_id: str) -> JobPlanRecord | None:
    # All callers hold the job lock before taking a plan lock.
    return session.scalar(
        select(JobPlanRecord)
        .where(JobPlanRecord.job_id == job_id)
        .order_by(JobPlanRecord.revision.desc())
        .limit(1)
        .with_for_update()
    )


def audit_state(plan: JobPlanRecord | None) -> dict[str, Any]:
    value = plan.payload.get(AUDIT_KEY) if plan is not None else None
    return dict(value) if isinstance(value, Mapping) else {}


def needs_audit(plan: JobPlanRecord | None) -> bool:
    policy = plan.payload.get("execution_policy") if plan is not None else None
    return (
        isinstance(policy, Mapping) and policy.get("execution_mode") == "parallel_v20"
    )


def store_state(plan: JobPlanRecord, state: dict[str, Any]) -> None:
    plan.payload = {**plan.payload, AUDIT_KEY: state}
    plan.payload_hash = canonical_hash(plan.payload)


def set_failure(job: JobRecord, *, technical: bool, details: dict[str, Any]) -> None:
    job.error_code = (
        "AURORA_SET_AUDIT_ERROR" if technical else "AURORA_SET_AUDIT_FAILED"
    )
    job.error_message = (
        "图片已生成，整组审核发生技术错误，审核结论尚未确认。"
        if technical
        else "图片已生成，整组审核未通过，请检查审核结果。"
    )
    job.error_details = {"scope": "set_audit", "retryable": False, **details}
    job.stage = "set_audit_error" if technical else "set_audit_failed"


def claim(session: Session, job: JobRecord, plan: JobPlanRecord) -> str | None:
    if JobStatus(job.status) in TERMINAL_JOB_STATUSES or job.status == "cancelling":
        return None
    state = audit_state(plan)
    if state:
        # No automatic takeover: the upstream outcome may already be billable.
        # A crashed worker becomes a technical review error, never new image work.
        if (
            state.get("status") == "running"
            and state.get("expires_at", 0) <= utc_now().timestamp()
        ):
            state.update(status="error", finished_at=utc_now().isoformat())
            store_state(plan, state)
            set_failure(
                job, technical=True, details={"reason": "AUDIT_OUTCOME_UNKNOWN"}
            )
        return None
    token = uuid4().hex
    store_state(
        plan,
        {
            "status": "running",
            "token": token,
            "started_at": utc_now().isoformat(),
            "expires_at": (
                utc_now() + timedelta(seconds=AUDIT_TIMEOUT_SECONDS)
            ).timestamp(),
        },
    )
    job.stage = "set_auditing"
    job.state_version += 1
    return token


def commit_result(
    session: Session,
    job_id: str,
    token: str,
    result: bool | SetAuditResult | None,
    error: Exception | None,
) -> bool:
    job = session.get(JobRecord, job_id, with_for_update=True)
    if (
        job is None
        or JobStatus(job.status) in TERMINAL_JOB_STATUSES
        or job.status == "cancelling"
    ):
        return False
    plan = latest_plan(session, job_id)
    state = audit_state(plan)
    if plan is None or state.get("token") != token or state.get("status") != "running":
        return False
    if state.get("expires_at", 0) <= utc_now().timestamp():
        error = TimeoutError()
    passed = result.passed if isinstance(result, SetAuditResult) else result is True
    state.update(
        status="error" if error is not None else "passed" if passed else "failed",
        finished_at=utc_now().isoformat(),
    )
    if error is not None or not passed:
        # Never persist arbitrary exception text (which may contain provider bodies).
        set_failure(
            job,
            technical=error is not None,
            details={
                "reason": type(error).__name__
                if error is not None
                else "QUALITY_VERDICT",
                "http_status": getattr(error, "http_status", None),
                "aurora_gateway_diagnostics": getattr(
                    error, "aurora_gateway_diagnostics", None
                ),
            },
        )
    if isinstance(result, SetAuditResult) and error is None:
        plan.payload = {
            **plan.payload,
            "_parallel_v20_set_session": result.observation,
            "set_audit_passed": passed,
            "harness_state": result.observation.get("state"),
        }
    store_state(plan, state)
    job.state_version += 1
    session.add(
        AuditEventRecord(
            workspace_id=job.workspace_id,
            action="aurora.parallel_v20_set_audited",
            resource_type="job",
            resource_id=job.id,
            request_id=token,
            details={"status": state["status"], "passed": passed and error is None},
        )
    )
    session.commit()
    return True
