import base64
import hashlib
import json
from datetime import timedelta
from typing import Any
from uuid import uuid4

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .domain import (
    TERMINAL_JOB_STATUSES,
    AssetLifecycleStatus,
    AssetMediaKind,
    AssetOriginKind,
    CreditReservationStatus,
    IdempotencyStatus,
    JobItemStatus,
    JobStatus,
    JobType,
    OutboxStatus,
    RetryScope,
    UsageCompleteness,
    can_transition,
)
from .errors import ApiError
from .models import (
    AssetRecord,
    CreditLedgerEntryRecord,
    CreditReservationRecord,
    IdempotencyRequestRecord,
    JobAssetRecord,
    JobItemRecord,
    JobPlanRecord,
    JobRecord,
    OutboxEventRecord,
    WorkspaceCreditAccountRecord,
    WorkspaceLimitRecord,
    utc_now,
)
from .schemas_v1 import (
    AssetResponse,
    CostSummary,
    JobAssetResponse,
    JobDetailResponse,
    JobItemResponse,
    JobListItemResponse,
    MoneyAmount,
    PlanResponse,
)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


_quota_enabled: bool = True


def set_quota_enabled(enabled: bool) -> None:
    global _quota_enabled
    _quota_enabled = enabled


def quota_enabled() -> bool:
    return _quota_enabled


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def require_idempotency_key(value: str | None) -> str:
    if value is None or not value.strip():
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "IDEMPOTENCY_KEY_REQUIRED",
            "该操作必须提供 Idempotency-Key。",
        )
    key = value.strip()
    if len(key) > 128:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_ERROR",
            "Idempotency-Key 不能超过 128 个字符。",
        )
    return key


def claim_idempotency(
    session: Session,
    *,
    workspace_id: str,
    actor_user_id: str,
    method: str,
    route_template: str,
    idempotency_key: str,
    request_hash: str,
) -> tuple[IdempotencyRequestRecord, bool]:
    existing = session.scalar(
        select(IdempotencyRequestRecord).where(
            IdempotencyRequestRecord.workspace_id == workspace_id,
            IdempotencyRequestRecord.method == method,
            IdempotencyRequestRecord.route_template == route_template,
            IdempotencyRequestRecord.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ApiError(
                status.HTTP_409_CONFLICT,
                "IDEMPOTENCY_KEY_REUSED",
                "该幂等键已用于不同请求。",
            )
        if existing.status == IdempotencyStatus.COMPLETED.value:
            return existing, True
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "IDEMPOTENCY_IN_PROGRESS",
            "相同请求正在处理中，请稍后查询结果。",
        )

    record = IdempotencyRequestRecord(
        id=new_id("idem"),
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        method=method,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        status=IdempotencyStatus.IN_PROGRESS.value,
        expires_at=utc_now() + timedelta(days=7),
    )
    session.add(record)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        concurrent = session.scalar(
            select(IdempotencyRequestRecord).where(
                IdempotencyRequestRecord.workspace_id == workspace_id,
                IdempotencyRequestRecord.method == method,
                IdempotencyRequestRecord.route_template == route_template,
                IdempotencyRequestRecord.idempotency_key == idempotency_key,
            )
        )
        if concurrent is None:
            raise
        if concurrent.request_hash != request_hash:
            raise ApiError(
                status.HTTP_409_CONFLICT,
                "IDEMPOTENCY_KEY_REUSED",
                "该幂等键已用于不同请求。",
            ) from None
        if concurrent.status == IdempotencyStatus.COMPLETED.value:
            return concurrent, True
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "IDEMPOTENCY_IN_PROGRESS",
            "相同请求正在处理中，请稍后查询结果。",
        ) from None
    return record, False


def complete_idempotency(
    record: IdempotencyRequestRecord,
    *,
    resource_type: str,
    resource_id: str,
    response_status: int,
) -> None:
    record.status = IdempotencyStatus.COMPLETED.value
    record.resource_type = resource_type
    record.resource_id = resource_id
    record.response_status = response_status
    record.response_body = {"resource_id": resource_id}


def asset_response(asset: AssetRecord) -> AssetResponse:
    return AssetResponse(
        id=asset.id,
        workspace_id=asset.workspace_id,
        media_kind=AssetMediaKind(asset.media_kind),
        origin_kind=AssetOriginKind(asset.origin_kind),
        lifecycle_status=AssetLifecycleStatus(asset.lifecycle_status),
        original_filename=asset.original_filename,
        content_type=asset.content_type,
        byte_size=asset.byte_size,
        width=asset.width,
        height=asset.height,
        sha256=asset.sha256,
        created_at=asset.created_at,
    )


def cost_summary(job: JobRecord) -> CostSummary:
    def money(value: int | None) -> MoneyAmount | None:
        if value is None or job.currency is None:
            return None
        return MoneyAmount(micros=str(value), currency=job.currency)

    return CostSummary(
        estimated_min=money(job.estimated_cost_min_micros),
        estimated_max=money(job.estimated_cost_max_micros),
        actual=money(job.actual_cost_micros),
        estimated_credits=job.estimated_credits,
        actual_credits=job.actual_credits,
        usage_completeness=UsageCompleteness(job.usage_completeness),
    )


def allowed_actions(job: JobRecord) -> list[str]:
    current = JobStatus(job.status)
    actions: list[str] = []
    if current == JobStatus.DRAFT:
        actions.extend(["edit", "submit", "cancel"])
    elif current in {
        JobStatus.QUEUED,
        JobStatus.PLANNING,
        JobStatus.AWAITING_CONFIRMATION,
        JobStatus.PROCESSING,
    }:
        actions.append("cancel")
    if current == JobStatus.AWAITING_CONFIRMATION:
        actions.extend(["edit_plan", "confirm_plan"])
    if current in {
        JobStatus.PARTIAL,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    }:
        actions.append("retry")
    if current in TERMINAL_JOB_STATUSES:
        actions.append("clone")
    return actions


def job_list_response(job: JobRecord) -> JobListItemResponse:
    return JobListItemResponse(
        id=job.id,
        workspace_id=job.workspace_id,
        type=JobType(job.type),
        status=JobStatus(job.status),
        stage=job.stage,
        display_name=job.display_name,
        progress=job.progress,
        expected_item_count=job.expected_item_count,
        succeeded_item_count=job.succeeded_item_count,
        failed_item_count=job.failed_item_count,
        allowed_actions=allowed_actions(job),
        cost=cost_summary(job),
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def job_detail_response(session: Session, job: JobRecord) -> JobDetailResponse:
    base = job_list_response(job).model_dump()
    items = session.scalars(
        select(JobItemRecord)
        .where(
            JobItemRecord.workspace_id == job.workspace_id,
            JobItemRecord.job_id == job.id,
        )
        .order_by(JobItemRecord.ordinal)
    ).all()
    assets = session.scalars(
        select(JobAssetRecord)
        .where(
            JobAssetRecord.workspace_id == job.workspace_id,
            JobAssetRecord.job_id == job.id,
        )
        .order_by(JobAssetRecord.ordinal)
    ).all()
    plan = session.scalar(
        select(JobPlanRecord)
        .where(
            JobPlanRecord.workspace_id == job.workspace_id,
            JobPlanRecord.job_id == job.id,
        )
        .order_by(JobPlanRecord.revision.desc())
        .limit(1)
    )
    return JobDetailResponse(
        **base,
        configuration=job.configuration,
        configuration_schema=job.configuration_schema,
        prompt_version=job.prompt_version,
        strategy_version=job.strategy_version,
        release_version=job.release_version,
        root_job_id=job.root_job_id,
        retry_of_job_id=job.retry_of_job_id,
        retry_scope=job.retry_scope,
        state_version=job.state_version,
        error_code=job.error_code,
        error_message=job.error_message,
        error_details=job.error_details,
        api_request_count=job.api_request_count,
        cancel_requested_at=job.cancel_requested_at,
        queued_at=job.queued_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        items=[
            JobItemResponse(
                id=item.id,
                item_key=item.item_key,
                ordinal=item.ordinal,
                status=JobItemStatus(item.status),
                stage=item.stage,
                quality=item.quality,
                result_source=item.result_source,
                error_code=item.error_code,
                error_message=item.error_message,
                error_details=item.error_details,
                started_at=item.started_at,
                finished_at=item.finished_at,
            )
            for item in items
        ],
        assets=[
            JobAssetResponse(
                asset_id=relation.asset_id,
                job_item_id=relation.job_item_id,
                direction=relation.direction,
                role=relation.role,
                ordinal=relation.ordinal,
                is_deliverable=relation.is_deliverable,
                validation=relation.validation,
            )
            for relation in assets
        ],
        plan=(
            PlanResponse(
                id=plan.id,
                revision=plan.revision,
                schema_version=plan.schema_version,
                payload=plan.payload,
                validation_status=plan.validation_status,
                validation_errors=plan.validation_errors,
                confirmed_at=plan.confirmed_at,
            )
            if plan is not None
            else None
        ),
    )


def get_workspace_asset(
    session: Session, workspace_id: str, asset_id: str
) -> AssetRecord:
    asset = session.scalar(
        select(AssetRecord).where(
            AssetRecord.workspace_id == workspace_id,
            AssetRecord.id == asset_id,
            AssetRecord.deleted_at.is_(None),
        )
    )
    if asset is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "ASSET_NOT_FOUND",
            "未找到指定素材。",
        )
    return asset


def get_ready_assets(
    session: Session, workspace_id: str, asset_ids: list[str]
) -> dict[str, AssetRecord]:
    assets = {
        item.id: item
        for item in session.scalars(
            select(AssetRecord).where(
                AssetRecord.workspace_id == workspace_id,
                AssetRecord.id.in_(asset_ids),
                AssetRecord.lifecycle_status == AssetLifecycleStatus.READY.value,
                AssetRecord.deleted_at.is_(None),
            )
        ).all()
    }
    missing = [asset_id for asset_id in asset_ids if asset_id not in assets]
    if missing:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "INPUT_ASSET_NOT_FOUND",
            "部分输入素材不存在、不属于当前工作区或尚未就绪。",
            {"asset_ids": missing},
        )
    return assets


def get_workspace_job(
    session: Session,
    workspace_id: str,
    job_id: str,
    *,
    for_update: bool = False,
) -> JobRecord:
    statement = select(JobRecord).where(
            JobRecord.workspace_id == workspace_id,
            JobRecord.id == job_id,
        )
    if for_update:
        statement = statement.with_for_update()
    job = session.scalar(statement)
    if job is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "JOB_NOT_FOUND",
            "未找到指定任务。",
        )
    return job


def transition_job(
    job: JobRecord,
    target: JobStatus,
    *,
    stage: str | None = None,
    progress: int | None = None,
) -> None:
    current = JobStatus(job.status)
    if current == target:
        return
    if not can_transition(current, target):
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "INVALID_STATE_TRANSITION",
            "任务状态不能执行该转换。",
            {"from": current.value, "to": target.value},
        )
    job.status = target.value
    job.stage = stage
    if progress is not None:
        job.progress = progress
    job.state_version += 1
    now = utc_now()
    if target == JobStatus.QUEUED:
        job.queued_at = now
    if target in {JobStatus.PLANNING, JobStatus.PROCESSING} and job.started_at is None:
        job.started_at = now
    if target in TERMINAL_JOB_STATUSES:
        job.finished_at = now


def estimate_job(job_type: JobType, item_count: int) -> tuple[int, int, int]:
    if job_type == JobType.LOCAL_EDIT:
        return 40_000, 80_000, 2
    return item_count * 45_000, item_count * 90_000, item_count * 2


def lock_workspace_limits(
    session: Session,
    workspace_id: str,
) -> WorkspaceLimitRecord:
    """Acquire the workspace-wide transaction lock used by quota gates."""

    limits = session.get(
        WorkspaceLimitRecord,
        workspace_id,
        with_for_update=True,
    )
    if limits is None:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "WORKSPACE_LIMITS_NOT_CONFIGURED",
            "工作区限制尚未配置。",
        )
    return limits


def enforce_active_job_limit(session: Session, workspace_id: str) -> None:
    limits = lock_workspace_limits(session, workspace_id)
    active = session.scalar(
        select(func.count())
        .select_from(JobRecord)
        .where(
            JobRecord.workspace_id == workspace_id,
            JobRecord.status.not_in([item.value for item in TERMINAL_JOB_STATUSES]),
        )
    )
    if (active or 0) >= limits.max_active_jobs:
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "ACTIVE_JOB_LIMIT_REACHED",
            "当前工作区活动任务数量已达到上限。",
        )


def reserve_credits(
    session: Session, workspace_id: str, job: JobRecord, credits: int
) -> CreditReservationRecord | None:
    if not _quota_enabled:
        return None

    existing = session.scalar(
        select(CreditReservationRecord).where(
            CreditReservationRecord.job_id == job.id
        )
    )
    if existing is not None:
        if existing.status == CreditReservationStatus.ACTIVE.value:
            return existing
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "CREDIT_RESERVATION_EXISTS",
            "该任务已有结算或释放的配额预留，无法再次预留。",
        )

    account = session.get(
        WorkspaceCreditAccountRecord, workspace_id, with_for_update=True
    )
    if account is None:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "CREDIT_ACCOUNT_NOT_CONFIGURED",
            "工作区额度账户尚未配置。",
        )
    available = account.balance_credits - account.reserved_credits
    if available < credits:
        raise ApiError(
            status.HTTP_402_PAYMENT_REQUIRED,
            "BUDGET_LIMIT_EXCEEDED",
            "当前工作区可用额度不足。",
            {"required_credits": credits, "available_credits": available},
        )
    reservation = CreditReservationRecord(
        id=new_id("hold"),
        workspace_id=workspace_id,
        job_id=job.id,
        reserved_credits=credits,
        settled_credits=0,
        status=CreditReservationStatus.ACTIVE.value,
    )
    account.reserved_credits += credits
    account.version += 1
    session.add(reservation)
    session.flush()
    session.add(
        CreditLedgerEntryRecord(
            workspace_id=workspace_id,
            reservation_id=reservation.id,
            job_id=job.id,
            entry_type="reserve",
            delta_balance_credits=0,
            delta_reserved_credits=credits,
            balance_after_credits=account.balance_credits,
            reserved_after_credits=account.reserved_credits,
        )
    )
    return reservation


def settle_credits(session: Session, job: JobRecord, actual_credits: int) -> None:
    if not _quota_enabled:
        return

    reservation = session.scalar(
        select(CreditReservationRecord).where(CreditReservationRecord.job_id == job.id)
    )
    if reservation is None or reservation.status != CreditReservationStatus.ACTIVE:
        return
    account = session.get(
        WorkspaceCreditAccountRecord, job.workspace_id, with_for_update=True
    )
    if account is None:
        return
    charged = min(actual_credits, reservation.reserved_credits)
    account.reserved_credits -= reservation.reserved_credits
    account.balance_credits -= charged
    account.version += 1
    reservation.settled_credits = charged
    reservation.status = CreditReservationStatus.SETTLED.value
    session.add(
        CreditLedgerEntryRecord(
            workspace_id=job.workspace_id,
            reservation_id=reservation.id,
            job_id=job.id,
            entry_type="settle",
            delta_balance_credits=-charged,
            delta_reserved_credits=-reservation.reserved_credits,
            balance_after_credits=account.balance_credits,
            reserved_after_credits=account.reserved_credits,
        )
    )
    job.actual_credits = charged


def release_credits(session: Session, job: JobRecord) -> None:
    """Release an active reservation without deducting workspace balance."""
    if not _quota_enabled:
        return

    reservation = session.scalar(
        select(CreditReservationRecord).where(
            CreditReservationRecord.job_id == job.id
        )
    )
    if (
        reservation is None
        or reservation.status != CreditReservationStatus.ACTIVE.value
    ):
        return

    account = session.get(
        WorkspaceCreditAccountRecord,
        job.workspace_id,
        with_for_update=True,
    )
    if account is None:
        return

    released = reservation.reserved_credits
    account.reserved_credits -= released
    account.version += 1
    reservation.status = CreditReservationStatus.RELEASED.value
    session.add(
        CreditLedgerEntryRecord(
            workspace_id=job.workspace_id,
            reservation_id=reservation.id,
            job_id=job.id,
            entry_type="release",
            delta_balance_credits=0,
            delta_reserved_credits=-released,
            balance_after_credits=account.balance_credits,
            reserved_after_credits=account.reserved_credits,
        )
    )
    session.flush()


def add_outbox_event(
    session: Session,
    *,
    workspace_id: str,
    job_id: str,
    event_type: str,
    suffix: str,
) -> OutboxEventRecord:
    event = OutboxEventRecord(
        id=new_id("evt"),
        workspace_id=workspace_id,
        aggregate_type="job",
        aggregate_id=job_id,
        event_type=event_type,
        dedupe_key=f"{job_id}:{event_type}:{suffix}",
        payload={"job_id": job_id},
        status=OutboxStatus.PENDING.value,
    )
    session.add(event)
    return event


def encode_cursor(created_at: Any, resource_id: str, scope: str) -> str:
    raw = json.dumps(
        {"created_at": created_at.isoformat(), "id": resource_id, "scope": scope},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str, scope: str) -> tuple[str, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        if payload["scope"] != scope:
            raise ValueError
        return str(payload["created_at"]), str(payload["id"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "INVALID_CURSOR",
            "分页游标无效或与当前筛选条件不匹配。",
        ) from exc


def retry_item_ids(
    session: Session,
    source: JobRecord,
    scope: RetryScope,
    selected_item_ids: list[str],
) -> list[str]:
    items = session.scalars(
        select(JobItemRecord).where(JobItemRecord.job_id == source.id)
    ).all()
    if scope == RetryScope.FULL:
        return [item.id for item in items]
    if scope == RetryScope.SELECTED:
        known = {item.id for item in items}
        unknown = [item_id for item_id in selected_item_ids if item_id not in known]
        if unknown:
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "VALIDATION_ERROR",
                "所选任务条目不属于源任务。",
                {"item_ids": unknown},
            )
        return selected_item_ids
    statuses = {JobItemStatus.FAILED.value}
    if scope == RetryScope.MISSING:
        statuses.add(JobItemStatus.CANCELLED.value)
    return [item.id for item in items if item.status in statuses]
