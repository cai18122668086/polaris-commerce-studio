import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import (
    Principal,
    WorkspaceDependency,
    WorkspaceWriteDependency,
    get_principal,
)
from .database import get_session
from .domain import (
    TERMINAL_JOB_STATUSES,
    AssetLifecycleStatus,
    AssetMediaKind,
    AssetOriginKind,
    JobAssetDirection,
    JobItemStatus,
    JobStatus,
    JobType,
    MembershipStatus,
    PlanValidationStatus,
    RetryScope,
)
from .errors import ApiError, UploadValidationError
from .models import (
    AssetRecord,
    JobAssetRecord,
    JobItemRecord,
    JobPlanRecord,
    JobRecord,
    WorkspaceMemberRecord,
    WorkspaceRecord,
    utc_now,
)
from .schemas_v1 import (
    AccessUrlRequest,
    AccessUrlResponse,
    AssetListResponse,
    AssetResponse,
    CancelRequest,
    CurrentUserResponse,
    DetailPackJobCreate,
    DraftJobUpdate,
    JobCreate,
    JobDetailResponse,
    JobListResponse,
    LocalEditJobCreate,
    PlanConfirmRequest,
    PlanResponse,
    PlanUpdateRequest,
    RetryRequest,
    WorkspaceResponse,
)
from .services import (
    add_outbox_event,
    asset_response,
    canonical_hash,
    claim_idempotency,
    complete_idempotency,
    decode_cursor,
    encode_cursor,
    enforce_active_job_limit,
    estimate_job,
    get_ready_assets,
    get_workspace_asset,
    get_workspace_job,
    job_detail_response,
    job_list_response,
    lock_workspace_limits,
    new_id,
    require_idempotency_key,
    reserve_credits,
    retry_item_ids,
    settle_credits,
    transition_job,
)

router = APIRouter(prefix="/api/v1")
SessionDependency = Annotated[Session, Depends(get_session)]
PrincipalDependency = Annotated[Principal, Depends(get_principal)]


def _schedule_outbox(request: Request, background_tasks: BackgroundTasks) -> None:
    if not request.app.state.settings.auto_process_jobs:
        return
    from .outbox import publish_pending_events

    background_tasks.add_task(
        publish_pending_events,
        request.app.state.settings,
        request.app.state.session_factory,
        request.app.state.task_runner,
    )


@router.get("/me", response_model=CurrentUserResponse, tags=["identity"])
def current_user(principal: PrincipalDependency) -> CurrentUserResponse:
    return CurrentUserResponse(id=principal.user_id)


@router.get("/workspaces", response_model=list[WorkspaceResponse], tags=["identity"])
def list_workspaces(
    principal: PrincipalDependency,
    session: SessionDependency,
) -> list[WorkspaceResponse]:
    rows = session.execute(
        select(WorkspaceRecord, WorkspaceMemberRecord)
        .join(
            WorkspaceMemberRecord,
            WorkspaceMemberRecord.workspace_id == WorkspaceRecord.id,
        )
        .where(
            WorkspaceMemberRecord.user_id == principal.user_id,
            WorkspaceMemberRecord.status == MembershipStatus.ACTIVE.value,
        )
        .order_by(WorkspaceRecord.created_at)
    ).all()
    return [
        WorkspaceResponse(
            id=workspace.id,
            name=workspace.name,
            role=membership.role,
        )
        for workspace, membership in rows
    ]


@router.get(
    "/workspaces/{workspace_id}",
    response_model=WorkspaceResponse,
    tags=["identity"],
)
def get_workspace(
    workspace: WorkspaceDependency,
    session: SessionDependency,
) -> WorkspaceResponse:
    record = cast(
        WorkspaceRecord,
        session.get(WorkspaceRecord, workspace.workspace_id),
    )
    return WorkspaceResponse(
        id=record.id,
        name=record.name,
        role=workspace.role,
    )


@router.post(
    "/workspaces/{workspace_id}/assets",
    response_model=AssetResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["assets"],
)
async def upload_asset(
    request: Request,
    workspace: WorkspaceWriteDependency,
    session: SessionDependency,
    file: Annotated[UploadFile, File()],
    origin_kind: Annotated[AssetOriginKind, Form()] = AssetOriginKind.UPLOAD,
    media_kind: Annotated[AssetMediaKind, Form()] = AssetMediaKind.IMAGE,
    idempotency_header: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AssetResponse:
    idempotency_key = require_idempotency_key(idempotency_header)
    try:
        validated = await request.app.state.image_validator.validate(
            file, workspace.workspace_id
        )
    except UploadValidationError as exc:
        raise ApiError(status.HTTP_400_BAD_REQUEST, exc.code, exc.message) from exc

    request_hash = canonical_hash(
        {
            "sha256": validated.sha256,
            "origin_kind": origin_kind.value,
            "media_kind": media_kind.value,
        }
    )
    idem, replay = claim_idempotency(
        session,
        workspace_id=workspace.workspace_id,
        actor_user_id=workspace.principal.user_id,
        method="POST",
        route_template="/api/v1/workspaces/{workspace_id}/assets",
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if replay:
        return asset_response(
            get_workspace_asset(
                session, workspace.workspace_id, cast(str, idem.resource_id)
            )
        )

    limits = lock_workspace_limits(session, workspace.workspace_id)
    used_bytes = session.scalar(
        select(func.coalesce(func.sum(AssetRecord.byte_size), 0)).where(
            AssetRecord.workspace_id == workspace.workspace_id,
            AssetRecord.lifecycle_status == AssetLifecycleStatus.READY.value,
            AssetRecord.deleted_at.is_(None),
        )
    )
    if int(used_bytes or 0) + len(validated.payload) > limits.storage_quota_bytes:
        raise ApiError(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "STORAGE_QUOTA_EXCEEDED",
            "当前工作区存储空间不足。",
        )

    stored = await request.app.state.storage.save_validated(validated)
    asset = AssetRecord(
        id=new_id("asset"),
        workspace_id=workspace.workspace_id,
        media_kind=media_kind.value,
        origin_kind=origin_kind.value,
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
        asset_metadata={},
    )
    session.add(asset)
    complete_idempotency(
        idem,
        resource_type="asset",
        resource_id=asset.id,
        response_status=status.HTTP_201_CREATED,
    )
    session.commit()
    session.refresh(asset)
    return asset_response(asset)


@router.get(
    "/workspaces/{workspace_id}/assets",
    response_model=AssetListResponse,
    tags=["assets"],
)
def list_assets(
    workspace: WorkspaceDependency,
    session: SessionDependency,
    origin_kind: AssetOriginKind | None = None,
    media_kind: AssetMediaKind | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
    cursor: str | None = None,
    include_total: bool = False,
) -> AssetListResponse:
    scope = canonical_hash(
        {
            "workspace_id": workspace.workspace_id,
            "origin_kind": origin_kind,
            "media_kind": media_kind,
        }
    )
    filters: list[Any] = [
        AssetRecord.workspace_id == workspace.workspace_id,
        AssetRecord.deleted_at.is_(None),
    ]
    if origin_kind is not None:
        filters.append(AssetRecord.origin_kind == origin_kind.value)
    if media_kind is not None:
        filters.append(AssetRecord.media_kind == media_kind.value)
    if cursor:
        created_raw, asset_id = decode_cursor(cursor, scope)
        created_at = datetime.fromisoformat(created_raw)
        filters.append(
            or_(
                AssetRecord.created_at < created_at,
                and_(
                    AssetRecord.created_at == created_at,
                    AssetRecord.id < asset_id,
                ),
            )
        )
    rows = session.scalars(
        select(AssetRecord)
        .where(*filters)
        .order_by(AssetRecord.created_at.desc(), AssetRecord.id.desc())
        .limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = (
        encode_cursor(items[-1].created_at, items[-1].id, scope)
        if has_more and items
        else None
    )
    total = None
    if include_total:
        total_filters = filters[:-1] if cursor else filters
        total = session.scalar(
            select(func.count()).select_from(AssetRecord).where(*total_filters)
        )
    return AssetListResponse(
        items=[asset_response(item) for item in items],
        next_cursor=next_cursor,
        has_more=has_more,
        total=total,
    )


@router.get(
    "/workspaces/{workspace_id}/assets/{asset_id}",
    response_model=AssetResponse,
    tags=["assets"],
)
def get_asset(
    asset_id: str,
    workspace: WorkspaceDependency,
    session: SessionDependency,
) -> AssetResponse:
    return asset_response(
        get_workspace_asset(session, workspace.workspace_id, asset_id)
    )


@router.post(
    "/workspaces/{workspace_id}/assets/{asset_id}/access-url",
    response_model=AccessUrlResponse,
    tags=["assets"],
)
async def create_asset_access_url(
    asset_id: str,
    payload: AccessUrlRequest,
    request: Request,
    workspace: WorkspaceDependency,
    session: SessionDependency,
) -> AccessUrlResponse:
    asset = get_workspace_asset(session, workspace.workspace_id, asset_id)
    if asset.lifecycle_status != AssetLifecycleStatus.READY.value:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "ASSET_NOT_READY",
            "素材尚未就绪。",
        )
    expires_at = datetime.now(UTC) + timedelta(minutes=10)
    url = await request.app.state.storage.create_access_url(
        asset.object_key,
        asset.original_filename,
        payload.disposition,
        600,
    )
    if url is None:
        expires = int(expires_at.timestamp())
        signature = _content_signature(
            request.app.state.settings.access_url_secret,
            workspace.workspace_id,
            asset.id,
            expires,
            payload.disposition,
        )
        url = str(
            request.url_for(
                "get_signed_asset_content",
                workspace_id=workspace.workspace_id,
                asset_id=asset.id,
            ).include_query_params(
                expires=expires,
                disposition=payload.disposition,
                signature=signature,
            )
        )
    return AccessUrlResponse(
        url=url,
        expires_at=expires_at,
        disposition=payload.disposition,
    )


@router.get(
    "/workspaces/{workspace_id}/assets/{asset_id}/content",
    name="get_signed_asset_content",
    include_in_schema=False,
)
async def get_signed_asset_content(
    workspace_id: str,
    asset_id: str,
    request: Request,
    session: SessionDependency,
    expires: int,
    disposition: str,
    signature: str,
) -> Response:
    if disposition not in {"inline", "attachment"}:
        raise ApiError(
            status.HTTP_403_FORBIDDEN, "ACCESS_URL_INVALID", "访问地址无效。"
        )
    expected = _content_signature(
        request.app.state.settings.access_url_secret,
        workspace_id,
        asset_id,
        expires,
        disposition,
    )
    if expires < int(datetime.now(UTC).timestamp()) or not hmac.compare_digest(
        signature, expected
    ):
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "ACCESS_URL_EXPIRED",
            "访问地址无效或已过期。",
        )
    asset = get_workspace_asset(session, workspace_id, asset_id)
    body = await request.app.state.storage.read_bytes(asset.object_key)
    safe_name = asset.original_filename.replace('"', "_")
    return Response(
        body,
        media_type=asset.content_type,
        headers={"Content-Disposition": f'{disposition}; filename="{safe_name}"'},
    )


@router.post(
    "/workspaces/{workspace_id}/jobs",
    response_model=JobDetailResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["jobs"],
)
def create_job(
    payload: JobCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    workspace: WorkspaceWriteDependency,
    session: SessionDependency,
    idempotency_header: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JobDetailResponse:
    key = require_idempotency_key(idempotency_header)
    payload_data = payload.model_dump(mode="json")
    request_hash = canonical_hash(payload_data)
    idem, replay = claim_idempotency(
        session,
        workspace_id=workspace.workspace_id,
        actor_user_id=workspace.principal.user_id,
        method="POST",
        route_template="/api/v1/workspaces/{workspace_id}/jobs",
        idempotency_key=key,
        request_hash=request_hash,
    )
    if replay:
        return job_detail_response(
            session,
            get_workspace_job(
                session, workspace.workspace_id, cast(str, idem.resource_id)
            ),
        )
    if payload.intent == "submit":
        enforce_active_job_limit(session, workspace.workspace_id)

    job, asset_roles = _new_job_from_payload(workspace.workspace_id, payload)
    asset_ids = [item[0] for item in asset_roles]
    get_ready_assets(session, workspace.workspace_id, asset_ids)
    session.add(job)
    session.flush()
    _add_items_and_inputs(session, job, asset_roles)
    if payload.intent == "submit":
        reserve_credits(
            session, workspace.workspace_id, job, cast(int, job.estimated_credits)
        )
        add_outbox_event(
            session,
            workspace_id=workspace.workspace_id,
            job_id=job.id,
            event_type="job.dispatch_requested",
            suffix="initial",
        )
    complete_idempotency(
        idem,
        resource_type="job",
        resource_id=job.id,
        response_status=status.HTTP_202_ACCEPTED,
    )
    session.commit()
    _schedule_outbox(request, background_tasks)
    return job_detail_response(session, job)


@router.get(
    "/workspaces/{workspace_id}/jobs",
    response_model=JobListResponse,
    tags=["jobs"],
)
def list_jobs(
    workspace: WorkspaceDependency,
    session: SessionDependency,
    job_type: Annotated[JobType | None, Query(alias="type")] = None,
    statuses: Annotated[list[JobStatus] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
    include_total: bool = False,
) -> JobListResponse:
    status_values = sorted(item.value for item in statuses or [])
    scope = canonical_hash(
        {
            "workspace_id": workspace.workspace_id,
            "type": job_type,
            "statuses": status_values,
        }
    )
    base_filters: list[Any] = [JobRecord.workspace_id == workspace.workspace_id]
    if job_type is not None:
        base_filters.append(JobRecord.type == job_type.value)
    if status_values:
        base_filters.append(JobRecord.status.in_(status_values))
    filters = list(base_filters)
    if cursor:
        created_raw, job_id = decode_cursor(cursor, scope)
        created_at = datetime.fromisoformat(created_raw)
        filters.append(
            or_(
                JobRecord.created_at < created_at,
                and_(JobRecord.created_at == created_at, JobRecord.id < job_id),
            )
        )
    rows = session.scalars(
        select(JobRecord)
        .where(*filters)
        .order_by(JobRecord.created_at.desc(), JobRecord.id.desc())
        .limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    items = rows[:limit]
    total = (
        session.scalar(select(func.count()).select_from(JobRecord).where(*base_filters))
        if include_total
        else None
    )
    return JobListResponse(
        items=[job_list_response(item) for item in items],
        next_cursor=(
            encode_cursor(items[-1].created_at, items[-1].id, scope)
            if has_more and items
            else None
        ),
        has_more=has_more,
        total=total,
    )


@router.get(
    "/workspaces/{workspace_id}/jobs/{job_id}",
    response_model=JobDetailResponse,
    tags=["jobs"],
)
def get_job(
    job_id: str,
    workspace: WorkspaceDependency,
    session: SessionDependency,
) -> JobDetailResponse:
    return job_detail_response(
        session, get_workspace_job(session, workspace.workspace_id, job_id)
    )


@router.patch(
    "/workspaces/{workspace_id}/jobs/{job_id}",
    response_model=JobDetailResponse,
    tags=["jobs"],
)
def update_draft_job(
    job_id: str,
    payload: DraftJobUpdate,
    workspace: WorkspaceWriteDependency,
    session: SessionDependency,
) -> JobDetailResponse:
    job = get_workspace_job(
        session, workspace.workspace_id, job_id, for_update=True
    )
    if JobStatus(job.status) != JobStatus.DRAFT:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "JOB_NOT_EDITABLE",
            "只有草稿任务可以修改。",
        )
    if payload.display_name is not None:
        job.display_name = payload.display_name
    if payload.configuration is not None:
        job.configuration = payload.configuration
    job.state_version += 1
    session.commit()
    return job_detail_response(session, job)


@router.post(
    "/workspaces/{workspace_id}/jobs/{job_id}/submit",
    response_model=JobDetailResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["jobs"],
)
def submit_job(
    job_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    workspace: WorkspaceWriteDependency,
    session: SessionDependency,
    idempotency_header: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JobDetailResponse:
    key = require_idempotency_key(idempotency_header)
    job = get_workspace_job(
        session, workspace.workspace_id, job_id, for_update=True
    )
    idem, replay = claim_idempotency(
        session,
        workspace_id=workspace.workspace_id,
        actor_user_id=workspace.principal.user_id,
        method="POST",
        route_template="/api/v1/workspaces/{workspace_id}/jobs/{job_id}/submit",
        idempotency_key=key,
        request_hash=canonical_hash({"job_id": job_id}),
    )
    if replay:
        return job_detail_response(session, job)
    if JobStatus(job.status) != JobStatus.DRAFT:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "JOB_NOT_SUBMITTABLE",
            "当前任务状态不能提交。",
            {"status": job.status},
        )
    enforce_active_job_limit(session, workspace.workspace_id)
    transition_job(job, JobStatus.QUEUED, progress=0)
    reserve_credits(
        session, workspace.workspace_id, job, cast(int, job.estimated_credits)
    )
    add_outbox_event(
        session,
        workspace_id=workspace.workspace_id,
        job_id=job.id,
        event_type="job.dispatch_requested",
        suffix="submit",
    )
    complete_idempotency(
        idem, resource_type="job", resource_id=job.id, response_status=202
    )
    session.commit()
    _schedule_outbox(request, background_tasks)
    return job_detail_response(session, job)


@router.post(
    "/workspaces/{workspace_id}/jobs/{job_id}/cancel",
    response_model=JobDetailResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["jobs"],
)
def cancel_job(
    job_id: str,
    payload: CancelRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    workspace: WorkspaceWriteDependency,
    session: SessionDependency,
    idempotency_header: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JobDetailResponse:
    key = require_idempotency_key(idempotency_header)
    job = get_workspace_job(
        session, workspace.workspace_id, job_id, for_update=True
    )
    idem, replay = claim_idempotency(
        session,
        workspace_id=workspace.workspace_id,
        actor_user_id=workspace.principal.user_id,
        method="POST",
        route_template="/api/v1/workspaces/{workspace_id}/jobs/{job_id}/cancel",
        idempotency_key=key,
        request_hash=canonical_hash({"job_id": job_id, **payload.model_dump()}),
    )
    if replay or JobStatus(job.status) == JobStatus.CANCELLED:
        return job_detail_response(session, job)
    current = JobStatus(job.status)
    if current in {JobStatus.PARTIAL, JobStatus.COMPLETED, JobStatus.FAILED}:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "JOB_NOT_CANCELLABLE",
            "当前任务状态不能取消。",
            {"status": current.value},
        )
    job.cancel_requested_at = utc_now()
    job.cancel_reason = payload.reason
    if current in {
        JobStatus.DRAFT,
        JobStatus.QUEUED,
        JobStatus.AWAITING_CONFIRMATION,
    }:
        cancellable_items = session.scalars(
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
        for item in cancellable_items:
            item.status = JobItemStatus.CANCELLED.value
            item.finished_at = utc_now()
            item.state_version += 1
        transition_job(job, JobStatus.CANCELLED, progress=job.progress)
        settle_credits(session, job, 0)
    else:
        transition_job(job, JobStatus.CANCELLING, progress=job.progress)
        add_outbox_event(
            session,
            workspace_id=workspace.workspace_id,
            job_id=job.id,
            event_type="job.cancel_requested",
            suffix=str(job.state_version),
        )
    complete_idempotency(
        idem, resource_type="job", resource_id=job.id, response_status=202
    )
    session.commit()
    _schedule_outbox(request, background_tasks)
    return job_detail_response(session, job)


@router.post(
    "/workspaces/{workspace_id}/jobs/{job_id}/retry",
    response_model=JobDetailResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["jobs"],
)
def retry_job(
    job_id: str,
    payload: RetryRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    workspace: WorkspaceWriteDependency,
    session: SessionDependency,
    idempotency_header: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JobDetailResponse:
    key = require_idempotency_key(idempotency_header)
    source = get_workspace_job(
        session, workspace.workspace_id, job_id, for_update=True
    )
    if JobStatus(source.status) not in {
        JobStatus.PARTIAL,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    }:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "JOB_NOT_RETRYABLE",
            "只有部分成功、失败或已取消任务可以重试。",
        )
    idem, replay = claim_idempotency(
        session,
        workspace_id=workspace.workspace_id,
        actor_user_id=workspace.principal.user_id,
        method="POST",
        route_template="/api/v1/workspaces/{workspace_id}/jobs/{job_id}/retry",
        idempotency_key=key,
        request_hash=canonical_hash(
            {"job_id": job_id, **payload.model_dump(mode="json")}
        ),
    )
    if replay:
        return job_detail_response(
            session,
            get_workspace_job(
                session, workspace.workspace_id, cast(str, idem.resource_id)
            ),
        )
    enforce_active_job_limit(session, workspace.workspace_id)
    selected = retry_item_ids(session, source, payload.scope, payload.item_ids)
    if not selected:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "JOB_NOT_RETRYABLE",
            "当前重试范围内没有可重试条目。",
        )
    retried = _copy_job_for_retry(session, source, payload.scope, selected)
    session.add(retried)
    session.flush()
    _copy_job_relations_for_retry(session, source, retried, selected)
    reserve_credits(
        session,
        workspace.workspace_id,
        retried,
        cast(int, retried.estimated_credits),
    )
    add_outbox_event(
        session,
        workspace_id=workspace.workspace_id,
        job_id=retried.id,
        event_type="job.dispatch_requested",
        suffix="retry",
    )
    complete_idempotency(
        idem, resource_type="job", resource_id=retried.id, response_status=201
    )
    session.commit()
    _schedule_outbox(request, background_tasks)
    return job_detail_response(session, retried)


@router.post(
    "/workspaces/{workspace_id}/jobs/{job_id}/clone",
    response_model=JobDetailResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["jobs"],
)
def clone_job(
    job_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    workspace: WorkspaceWriteDependency,
    session: SessionDependency,
    idempotency_header: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JobDetailResponse:
    source = get_workspace_job(
        session, workspace.workspace_id, job_id, for_update=True
    )
    if JobStatus(source.status) not in TERMINAL_JOB_STATUSES:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "JOB_NOT_CLONEABLE",
            "只有终态任务可以复制。",
        )
    key = require_idempotency_key(idempotency_header)
    idem, replay = claim_idempotency(
        session,
        workspace_id=workspace.workspace_id,
        actor_user_id=workspace.principal.user_id,
        method="POST",
        route_template="/api/v1/workspaces/{workspace_id}/jobs/{job_id}/clone",
        idempotency_key=key,
        request_hash=canonical_hash({"job_id": job_id}),
    )
    if replay:
        return job_detail_response(
            session,
            get_workspace_job(
                session, workspace.workspace_id, cast(str, idem.resource_id)
            ),
        )
    enforce_active_job_limit(session, workspace.workspace_id)
    source_items = session.scalars(
        select(JobItemRecord).where(JobItemRecord.job_id == source.id)
    ).all()
    selected = [item.id for item in source_items]
    cloned = _copy_job_for_retry(session, source, RetryScope.FULL, selected)
    cloned.root_job_id = None
    cloned.retry_of_job_id = None
    cloned.retry_scope = None
    session.add(cloned)
    session.flush()
    _copy_job_relations_for_retry(session, source, cloned, selected)
    reserve_credits(
        session,
        workspace.workspace_id,
        cloned,
        cast(int, cloned.estimated_credits),
    )
    add_outbox_event(
        session,
        workspace_id=workspace.workspace_id,
        job_id=cloned.id,
        event_type="job.dispatch_requested",
        suffix="clone",
    )
    complete_idempotency(
        idem, resource_type="job", resource_id=cloned.id, response_status=201
    )
    session.commit()
    _schedule_outbox(request, background_tasks)
    return job_detail_response(session, cloned)


@router.put(
    "/workspaces/{workspace_id}/jobs/{job_id}/plan",
    response_model=PlanResponse,
    tags=["jobs"],
)
def update_plan(
    job_id: str,
    payload: PlanUpdateRequest,
    workspace: WorkspaceWriteDependency,
    session: SessionDependency,
) -> PlanResponse:
    job = get_workspace_job(
        session, workspace.workspace_id, job_id, for_update=True
    )
    if JobStatus(job.status) != JobStatus.AWAITING_CONFIRMATION:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "JOB_NOT_EDITABLE",
            "当前任务不允许修改计划。",
        )
    current = session.scalar(
        select(JobPlanRecord)
        .where(JobPlanRecord.job_id == job.id)
        .order_by(JobPlanRecord.revision.desc())
        .limit(1)
    )
    if current is None or current.revision != payload.expected_revision:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "PLAN_REVISION_CONFLICT",
            "计划已更新，请刷新后重试。",
        )
    validation_errors = _validate_plan_payload(job, payload.payload)
    plan = JobPlanRecord(
        id=new_id("plan"),
        workspace_id=workspace.workspace_id,
        job_id=job.id,
        revision=current.revision + 1,
        schema_version="v1",
        payload=payload.payload,
        payload_hash=canonical_hash(payload.payload),
        validation_status=(
            PlanValidationStatus.INVALID.value
            if validation_errors
            else PlanValidationStatus.VALID.value
        ),
        validation_errors=validation_errors,
        validated_at=utc_now(),
    )
    session.add(plan)
    job.state_version += 1
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "PLAN_REVISION_CONFLICT",
            "计划已更新，请刷新后重试。",
        ) from exc
    return PlanResponse(
        id=plan.id,
        revision=plan.revision,
        schema_version=plan.schema_version,
        payload=plan.payload,
        validation_status=plan.validation_status,
        validation_errors=plan.validation_errors,
        confirmed_at=plan.confirmed_at,
    )


@router.post(
    "/workspaces/{workspace_id}/jobs/{job_id}/plan/confirm",
    response_model=JobDetailResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["jobs"],
)
def confirm_plan(
    job_id: str,
    payload: PlanConfirmRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    workspace: WorkspaceWriteDependency,
    session: SessionDependency,
    idempotency_header: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JobDetailResponse:
    key = require_idempotency_key(idempotency_header)
    job = get_workspace_job(
        session, workspace.workspace_id, job_id, for_update=True
    )
    plan = session.scalar(
        select(JobPlanRecord)
        .where(JobPlanRecord.job_id == job.id)
        .order_by(JobPlanRecord.revision.desc())
        .limit(1)
    )
    if plan is None or plan.revision != payload.expected_revision:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "PLAN_REVISION_CONFLICT",
            "计划版本不一致。",
        )
    if plan.validation_status != PlanValidationStatus.VALID.value:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "PLAN_INVALID",
            "计划未通过校验，不能开始生成。",
        )
    idem, replay = claim_idempotency(
        session,
        workspace_id=workspace.workspace_id,
        actor_user_id=workspace.principal.user_id,
        method="POST",
        route_template="/api/v1/workspaces/{workspace_id}/jobs/{job_id}/plan/confirm",
        idempotency_key=key,
        request_hash=canonical_hash(
            {"job_id": job.id, "expected_revision": payload.expected_revision}
        ),
    )
    if replay:
        return job_detail_response(session, job)
    plan.confirmed_at = utc_now()
    transition_job(job, JobStatus.PROCESSING, stage="generating", progress=20)
    add_outbox_event(
        session,
        workspace_id=workspace.workspace_id,
        job_id=job.id,
        event_type="job.dispatch_requested",
        suffix=f"plan-{plan.revision}",
    )
    complete_idempotency(
        idem, resource_type="job", resource_id=job.id, response_status=202
    )
    session.commit()
    _schedule_outbox(request, background_tasks)
    return job_detail_response(session, job)


def _new_job_from_payload(
    workspace_id: str,
    payload: LocalEditJobCreate | DetailPackJobCreate,
) -> tuple[JobRecord, list[tuple[str, str, int]]]:
    if isinstance(payload, LocalEditJobCreate):
        item_count = 1
        asset_roles = [
            (payload.input.source_asset_id, "source", 0),
            (payload.input.selection_mask_asset_id, "selection_mask", 0),
        ]
    else:
        item_count = payload.configuration.page_count
        asset_roles = [
            (asset_id, "product_reference", ordinal)
            for group in payload.input.product_groups
            for ordinal, asset_id in enumerate(group.asset_ids)
        ]
    minimum, maximum, credits = estimate_job(JobType(payload.type), item_count)
    is_submit = payload.intent == "submit"
    job = JobRecord(
        id=new_id("job"),
        workspace_id=workspace_id,
        type=payload.type,
        status=(JobStatus.QUEUED.value if is_submit else JobStatus.DRAFT.value),
        stage=("queued" if is_submit else "draft"),
        display_name=payload.display_name,
        progress=0,
        configuration={
            "input": payload.input.model_dump(mode="json"),
            "settings": payload.configuration.model_dump(mode="json"),
        },
        expected_item_count=item_count,
        estimated_cost_min_micros=minimum,
        estimated_cost_max_micros=maximum,
        estimated_credits=credits,
        currency="USD",
        queued_at=utc_now() if is_submit else None,
    )
    return job, asset_roles


def _add_items_and_inputs(
    session: Session,
    job: JobRecord,
    asset_roles: list[tuple[str, str, int]],
) -> None:
    for ordinal in range(job.expected_item_count):
        session.add(
            JobItemRecord(
                id=new_id("item"),
                workspace_id=job.workspace_id,
                job_id=job.id,
                item_key=(
                    "result"
                    if job.type == JobType.LOCAL_EDIT
                    else f"page-{ordinal + 1:03d}"
                ),
                ordinal=ordinal,
                status=JobItemStatus.PENDING.value,
                configuration={},
            )
        )
    for asset_id, role, ordinal in asset_roles:
        session.add(
            JobAssetRecord(
                workspace_id=job.workspace_id,
                job_id=job.id,
                asset_id=asset_id,
                direction=JobAssetDirection.INPUT.value,
                role=role,
                ordinal=ordinal,
                is_deliverable=False,
                validation={},
            )
        )


def _copy_job_for_retry(
    session: Session,
    source: JobRecord,
    scope: RetryScope,
    selected: list[str],
) -> JobRecord:
    del session
    minimum, maximum, credits = estimate_job(JobType(source.type), len(selected))
    return JobRecord(
        id=new_id("job"),
        workspace_id=source.workspace_id,
        type=source.type,
        status=JobStatus.QUEUED.value,
        stage="queued",
        display_name=source.display_name,
        configuration=source.configuration,
        configuration_schema=source.configuration_schema,
        prompt_version=source.prompt_version,
        strategy_version=source.strategy_version,
        release_version=source.release_version,
        root_job_id=source.root_job_id or source.id,
        retry_of_job_id=source.id,
        retry_scope=scope.value,
        expected_item_count=source.expected_item_count,
        estimated_cost_min_micros=minimum,
        estimated_cost_max_micros=maximum,
        estimated_credits=credits,
        currency=source.currency or "USD",
        queued_at=utc_now(),
    )


def _copy_job_relations_for_retry(
    session: Session,
    source: JobRecord,
    target: JobRecord,
    selected: list[str],
) -> None:
    source_items = session.scalars(
        select(JobItemRecord)
        .where(JobItemRecord.job_id == source.id)
        .order_by(JobItemRecord.ordinal)
    ).all()
    item_map: dict[str, str] = {}
    for item in source_items:
        new_item_id = new_id("item")
        item_map[item.id] = new_item_id
        retry_this = item.id in selected
        reused = not retry_this and item.status in {
            JobItemStatus.SUCCEEDED.value,
            JobItemStatus.REUSED.value,
        }
        session.add(
            JobItemRecord(
                id=new_item_id,
                workspace_id=target.workspace_id,
                job_id=target.id,
                item_key=item.item_key,
                ordinal=item.ordinal,
                status=(
                    JobItemStatus.PENDING.value
                    if retry_this
                    else (
                        JobItemStatus.REUSED.value
                        if reused
                        else JobItemStatus.SKIPPED.value
                    )
                ),
                stage="retry" if retry_this else "reused",
                quality=item.quality,
                configuration=item.configuration,
                source_job_item_id=item.id,
                result_source="reused" if reused else None,
            )
        )
        if reused:
            target.succeeded_item_count += 1
    relations = session.scalars(
        select(JobAssetRecord).where(JobAssetRecord.job_id == source.id)
    ).all()
    for relation in relations:
        if relation.direction == JobAssetDirection.INPUT.value or (
            relation.job_item_id in item_map
            and relation.is_deliverable
            and relation.job_item_id not in selected
        ):
            session.add(
                JobAssetRecord(
                    workspace_id=target.workspace_id,
                    job_id=target.id,
                    job_item_id=(
                        item_map.get(relation.job_item_id)
                        if relation.job_item_id
                        else None
                    ),
                    asset_id=relation.asset_id,
                    direction=relation.direction,
                    role=relation.role,
                    ordinal=relation.ordinal,
                    is_deliverable=relation.is_deliverable,
                    validation=relation.validation,
                )
            )


def _validate_plan_payload(
    job: JobRecord, payload: dict[str, Any]
) -> list[dict[str, Any]]:
    pages = payload.get("pages")
    if not isinstance(pages, list):
        return [{"field": "pages", "message": "pages 必须是数组。"}]
    if len(pages) != job.expected_item_count:
        return [
            {
                "field": "pages",
                "message": "计划页数必须与任务要求一致。",
                "expected": job.expected_item_count,
                "actual": len(pages),
            }
        ]
    return []


def _content_signature(
    secret: str,
    workspace_id: str,
    asset_id: str,
    expires: int,
    disposition: str,
) -> str:
    message = f"{workspace_id}:{asset_id}:{expires}:{disposition}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
