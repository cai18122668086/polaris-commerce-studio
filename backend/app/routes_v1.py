import asyncio
import hashlib
import hmac
import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Annotated, Any, Literal, cast
from zipfile import ZIP_STORED, ZipFile

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
from sqlalchemy.orm import Session, sessionmaker

from .amazon_visual_suite_provider import AMAZON_EXPECTED_ITEM_COUNT
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
from .masked_repair import (
    MaskedRepairError,
    validate_local_edit_asset_records,
)
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
from .provider_quota import reserve_provider_job_quota
from .schemas_v1 import (
    AccessUrlRequest,
    AccessUrlResponse,
    AmazonVisualSuiteJobCreate,
    AssetListResponse,
    AssetResponse,
    CancelRequest,
    CapabilityStatus,
    CreativeImageJobCreate,
    CurrentUserResponse,
    DetailPackJobCreate,
    DraftJobUpdate,
    ErrorResponse,
    JobCreate,
    JobDetailResponse,
    JobListResponse,
    LocalEditJobCreate,
    PlanConfirmRequest,
    PlanResponse,
    PlanUpdateRequest,
    ProductImageJobCreate,
    ReferenceRemixJobCreate,
    RetryRequest,
    RuntimeCapabilities,
    RuntimeStatusResponse,
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
    release_credits,
    require_idempotency_key,
    reserve_credits,
    retry_item_ids,
    settle_credits,
    transition_job,
)
from .storage import ImageStorage, StoredImage, build_content_disposition

router = APIRouter(prefix="/api/v1")
SessionDependency = Annotated[Session, Depends(get_session)]
PrincipalDependency = Annotated[Principal, Depends(get_principal)]
logger = logging.getLogger(__name__)


class _UploadCommitOutcomeUnknown(RuntimeError):
    def __init__(self, asset_id: str, object_key: str) -> None:
        super().__init__(
            f"Unable to determine upload commit outcome for asset {asset_id}"
        )
        self.asset_id = asset_id
        self.object_key = object_key


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


async def _cleanup_upload_object(
    storage: ImageStorage,
    *,
    object_key: str,
    object_version: str = "",
    reason: str,
) -> None:
    try:
        await storage.delete_object(object_key, object_version)
    except Exception:
        logger.exception(
            "upload_object_cleanup_failed",
            extra={
                "object_key": object_key,
                "object_version": object_version,
                "cleanup_reason": reason,
            },
        )


async def _finish_cleanup_before_cancellation(
    storage: ImageStorage,
    *,
    object_key: str,
    reason: str,
) -> None:
    cleanup_task = asyncio.create_task(
        _cleanup_upload_object(
            storage,
            object_key=object_key,
            reason=reason,
        )
    )
    while not cleanup_task.done():
        try:
            await asyncio.shield(cleanup_task)
        except asyncio.CancelledError:
            continue
    cleanup_task.result()


def _commit_staged_asset(
    session_factory: sessionmaker[Session],
    *,
    workspace_id: str,
    actor_user_id: str,
    idempotency_key: str,
    request_hash: str,
    origin_kind: AssetOriginKind,
    media_kind: AssetMediaKind,
    stored: StoredImage,
) -> tuple[AssetResponse, bool]:
    """Run the complete quota critical section in a worker-thread transaction."""

    with session_factory() as session:
        idem, replay = claim_idempotency(
            session,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            method="POST",
            route_template="/api/v1/workspaces/{workspace_id}/assets",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if replay:
            return (
                asset_response(
                    get_workspace_asset(
                        session,
                        workspace_id,
                        cast(str, idem.resource_id),
                    )
                ),
                False,
            )

        limits = lock_workspace_limits(session, workspace_id)
        used_bytes = session.scalar(
            select(func.coalesce(func.sum(AssetRecord.byte_size), 0)).where(
                AssetRecord.workspace_id == workspace_id,
                AssetRecord.lifecycle_status == AssetLifecycleStatus.READY.value,
                AssetRecord.deleted_at.is_(None),
            )
        )
        if int(used_bytes or 0) + stored.byte_size > limits.storage_quota_bytes:
            raise ApiError(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                "STORAGE_QUOTA_EXCEEDED",
                "当前工作区存储空间不足。",
            )

        asset_id = new_id("asset")
        asset = AssetRecord(
            id=asset_id,
            workspace_id=workspace_id,
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
        session.flush()
        response = asset_response(asset)
        try:
            session.commit()
        except Exception as commit_error:
            session.rollback()
            try:
                with session_factory() as verification_session:
                    committed = verification_session.get(AssetRecord, asset_id)
                    if (
                        committed is not None
                        and committed.object_key == stored.object_key
                    ):
                        return asset_response(committed), True
            except Exception:
                raise _UploadCommitOutcomeUnknown(
                    asset_id,
                    stored.object_key,
                ) from commit_error
            raise
        return response, True


@router.get("/me", response_model=CurrentUserResponse, tags=["identity"])
def current_user(principal: PrincipalDependency) -> CurrentUserResponse:
    return CurrentUserResponse(id=principal.user_id)


def runtime_status_response(
    *,
    environment: Literal["development", "test", "production"],
    authentication_mode: Literal["development", "external"],
    task_runner: Literal["mock", "tengli"],
    product_image_provider_enabled: bool = False,
    reference_remix_provider_enabled: bool = False,
    creative_image_provider_enabled: bool = False,
    amazon_visual_suite_provider_enabled: bool = False,
    crossborder_detail_provider_enabled: bool = False,
) -> RuntimeStatusResponse:
    local_edit = (
        CapabilityStatus(
            availability="available",
            execution="mock",
            reason_code="TASK_RUNNER_MOCK",
        )
        if task_runner == "mock"
        else CapabilityStatus(
            availability="available",
            execution="provider",
            reason_code=None,
        )
    )
    detail_pack = (
        CapabilityStatus(
            availability="available",
            execution="mock",
            reason_code="TASK_RUNNER_MOCK",
        )
        if task_runner == "mock"
        else CapabilityStatus(
            availability="available",
            execution="provider",
            reason_code=None,
        )
    )
    mock_feature_status = CapabilityStatus(
        availability="available",
        execution="mock",
        reason_code="TASK_RUNNER_MOCK",
    )
    unregistered_provider_status = CapabilityStatus(
        availability="unavailable",
        execution="none",
        reason_code="REAL_PROVIDER_NOT_REGISTERED",
    )
    registered_provider_status = CapabilityStatus(
        availability="available",
        execution="provider",
        reason_code=None,
    )

    def feature_status(enabled: bool) -> CapabilityStatus:
        if task_runner == "mock":
            return mock_feature_status
        return registered_provider_status if enabled else unregistered_provider_status

    features = {
        "local_edit": local_edit,
        "product_image": feature_status(product_image_provider_enabled),
        "reference_remix": feature_status(reference_remix_provider_enabled),
        "creative_image": feature_status(creative_image_provider_enabled),
        "detail_pack": detail_pack,
        "amazon_visual_suite": feature_status(
            amazon_visual_suite_provider_enabled
        ),
    }
    if task_runner == "tengli":
        features["crossborder_detail"] = feature_status(
            crossborder_detail_provider_enabled
        )

    return RuntimeStatusResponse(
        environment=environment,
        authentication_mode=authentication_mode,
        task_runner=task_runner,
        capabilities=RuntimeCapabilities(
            features=features,
            asset_management=CapabilityStatus(
                availability="available",
                execution="local",
                reason_code=None,
            ),
            local_edit=local_edit,
            detail_pack=detail_pack,
            external_authentication=CapabilityStatus(
                availability="unavailable",
                execution="none",
                reason_code="EXTERNAL_AUTHENTICATION_NOT_IMPLEMENTED",
            ),
        ),
    )


@router.get(
    "/runtime",
    response_model=RuntimeStatusResponse,
    responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}},
    tags=["system"],
    description=(
        "Reports internal-test workflow availability and execution mode. "
        "availability=available only means the workflow/API can be exercised; "
        "clients must read execution before describing real generation support."
    ),
)
def get_runtime_status(
    request: Request,
    _principal: PrincipalDependency,
) -> RuntimeStatusResponse:
    settings = request.app.state.settings
    return runtime_status_response(
        environment=settings.environment,
        authentication_mode=settings.auth_mode,
        task_runner=settings.task_runner,
        product_image_provider_enabled=settings.product_image_provider_enabled,
        reference_remix_provider_enabled=settings.reference_remix_provider_enabled,
        creative_image_provider_enabled=settings.creative_image_provider_enabled,
        amazon_visual_suite_provider_enabled=(
            settings.amazon_visual_suite_provider_enabled
        ),
        crossborder_detail_provider_enabled=(
            settings.crossborder_detail_provider_enabled
        ),
    )


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
    storage: ImageStorage = request.app.state.storage
    try:
        stored = await storage.save_validated(validated)
    except asyncio.CancelledError:
        await _finish_cleanup_before_cancellation(
            storage,
            object_key=validated.object_key,
            reason="storage_save_cancelled",
        )
        raise
    except Exception:
        await _cleanup_upload_object(
            storage,
            object_key=validated.object_key,
            reason="storage_save_failed",
        )
        raise

    try:
        response, retained = await asyncio.to_thread(
            _commit_staged_asset,
            request.app.state.session_factory,
            workspace_id=workspace.workspace_id,
            actor_user_id=workspace.principal.user_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            origin_kind=origin_kind,
            media_kind=media_kind,
            stored=stored,
        )
    except _UploadCommitOutcomeUnknown as exc:
        logger.critical(
            "upload_commit_outcome_unknown",
            extra={
                "asset_id": exc.asset_id,
                "object_key": exc.object_key,
                "workspace_id": workspace.workspace_id,
            },
            exc_info=True,
        )
        raise
    except Exception:
        await _cleanup_upload_object(
            storage,
            object_key=stored.object_key,
            object_version=stored.object_version,
            reason="database_write_failed",
        )
        raise

    if not retained:
        await _cleanup_upload_object(
            storage,
            object_key=stored.object_key,
            object_version=stored.object_version,
            reason="idempotency_replay",
        )
    return response


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
    url = None
    if request.app.state.settings.asset_access_url_mode == "auto":
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
    content_disposition = build_content_disposition(
        disposition, asset.original_filename
    )
    body = await request.app.state.storage.read_bytes(asset.object_key)
    return Response(
        body,
        media_type=asset.content_type,
        headers={"Content-Disposition": content_disposition},
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

    job, asset_roles = _new_job_from_payload(
        workspace.workspace_id,
        payload,
        detail_medium_price_micros=(
            request.app.state.settings.xinghe_medium_price_micros
        ),
        detail_high_price_micros=(request.app.state.settings.xinghe_high_price_micros),
    )
    asset_ids = [item[0] for item in asset_roles]
    assets = get_ready_assets(session, workspace.workspace_id, asset_ids)
    if isinstance(payload, LocalEditJobCreate):
        try:
            validate_local_edit_asset_records(
                assets[payload.input.source_asset_id],
                assets[payload.input.selection_mask_asset_id],
            )
        except MaskedRepairError as exc:
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                exc.code,
                str(exc),
                {"needs_reselection": exc.needs_reselection},
            ) from exc
    session.add(job)
    session.flush()
    _add_items_and_inputs(session, job, asset_roles)
    if payload.intent == "submit":
        _reserve_real_provider_job_if_enabled(
            session,
            request,
            job,
            workspace.principal.user_id,
        )
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


def _is_preserved_amazon_review_infrastructure_failure(
    item: JobItemRecord,
) -> bool:
    details = item.error_details
    return (
        item.status == JobItemStatus.FAILED.value
        and isinstance(details, dict)
        and details.get("failure_kind") == "review_infrastructure_failure"
        and details.get("image_quality_failed") is False
        and details.get("generated_asset_preserved") is True
    )


def _allows_preserved_amazon_partial_archive(
    job: JobRecord,
    items: Sequence[JobItemRecord],
) -> bool:
    if (
        job.type != JobType.AMAZON_VISUAL_SUITE.value
        or JobStatus(job.status) != JobStatus.PARTIAL
        or job.expected_item_count != AMAZON_EXPECTED_ITEM_COUNT
        or len(items) != job.expected_item_count
        or job.succeeded_item_count + job.failed_item_count
        != job.expected_item_count
    ):
        return False

    preserved_failures = [
        item
        for item in items
        if _is_preserved_amazon_review_infrastructure_failure(item)
    ]
    return (
        bool(preserved_failures)
        and len(preserved_failures) == job.failed_item_count
        and all(
            item.status
            in {
                JobItemStatus.SUCCEEDED.value,
                JobItemStatus.REUSED.value,
            }
            or _is_preserved_amazon_review_infrastructure_failure(item)
            for item in items
        )
    )


@router.get(
    "/workspaces/{workspace_id}/jobs/{job_id}/deliverables.zip",
    response_class=Response,
    responses={
        status.HTTP_200_OK: {
            "content": {
                "application/zip": {
                    "schema": {"type": "string", "format": "binary"}
                }
            },
            "description": "Complete canonical deliverables archive.",
        }
    },
    tags=["jobs"],
)
async def download_job_deliverables(
    job_id: str,
    request: Request,
    workspace: WorkspaceDependency,
    session: SessionDependency,
) -> Response:
    job = get_workspace_job(session, workspace.workspace_id, job_id)
    if job.type not in {
        JobType.DETAIL_PACK.value,
        JobType.AMAZON_VISUAL_SUITE.value,
    }:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "DELIVERABLE_ARCHIVE_UNSUPPORTED",
            "该任务类型暂不支持整套下载。",
        )
    partial_items: Sequence[JobItemRecord] = ()
    if (
        job.type == JobType.AMAZON_VISUAL_SUITE.value
        and JobStatus(job.status) == JobStatus.PARTIAL
    ):
        partial_items = session.scalars(
            select(JobItemRecord)
            .where(
                JobItemRecord.workspace_id == workspace.workspace_id,
                JobItemRecord.job_id == job.id,
            )
            .order_by(JobItemRecord.ordinal)
        ).all()
    preserved_partial_archive = _allows_preserved_amazon_partial_archive(
        job, partial_items
    )
    if (
        JobStatus(job.status) != JobStatus.COMPLETED
        and not preserved_partial_archive
    ):
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "DELIVERABLE_ARCHIVE_NOT_READY",
            "套图尚未完整生成，请在全部图片完成后下载。",
        )

    deliverables = session.execute(
        select(JobAssetRecord, JobItemRecord, AssetRecord)
        .join(JobItemRecord, JobItemRecord.id == JobAssetRecord.job_item_id)
        .join(AssetRecord, AssetRecord.id == JobAssetRecord.asset_id)
        .where(
            JobAssetRecord.workspace_id == workspace.workspace_id,
            JobAssetRecord.job_id == job.id,
            JobAssetRecord.direction == JobAssetDirection.OUTPUT.value,
            JobAssetRecord.is_deliverable.is_(True),
        )
        .order_by(JobAssetRecord.ordinal)
    ).all()
    if len(deliverables) != job.expected_item_count:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "DELIVERABLE_ARCHIVE_INCOMPLETE",
            "套图文件数量与任务合同不一致，暂不能打包下载。",
            {
                "expected_item_count": job.expected_item_count,
                "deliverable_count": len(deliverables),
            },
        )
    if preserved_partial_archive and {
        item.id for _, item, _ in deliverables
    } != {item.id for item in partial_items}:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "DELIVERABLE_ARCHIVE_INCOMPLETE",
            "套图文件与 Amazon 21 张正式交付集不一致，暂不能打包下载。",
            {
                "expected_item_count": job.expected_item_count,
                "deliverable_count": len(deliverables),
            },
        )

    archive = BytesIO()
    member_names: set[str] = set()
    with ZipFile(archive, mode="w", compression=ZIP_STORED) as bundle:
        for _, item, asset in deliverables:
            extension = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/webp": ".webp",
            }.get(asset.content_type.lower())
            member_name = f"{item.item_key}{extension or ''}"
            if (
                extension is None
                or member_name in member_names
                or asset.lifecycle_status != AssetLifecycleStatus.READY.value
                or (
                    item.status
                    not in {
                        JobItemStatus.SUCCEEDED.value,
                        JobItemStatus.REUSED.value,
                    }
                    and not (
                        preserved_partial_archive
                        and _is_preserved_amazon_review_infrastructure_failure(item)
                    )
                )
            ):
                raise ApiError(
                    status.HTTP_409_CONFLICT,
                    "DELIVERABLE_ARCHIVE_INVALID",
                    "套图中存在不可交付或命名冲突的文件，暂不能打包下载。",
                )
            payload = await request.app.state.storage.read_bytes(asset.object_key)
            if (
                len(payload) != asset.byte_size
                or hashlib.sha256(payload).hexdigest() != asset.sha256
            ):
                raise ApiError(
                    status.HTTP_409_CONFLICT,
                    "DELIVERABLE_INTEGRITY_FAILED",
                    "套图文件完整性校验失败，请联系管理员处理。",
                )
            member_names.add(member_name)
            bundle.writestr(member_name, payload)

    archive_name = f"{job.type.replace('_', '-')}-{job.id}.zip"
    return Response(
        archive.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": build_content_disposition(
                "attachment", archive_name
            )
        },
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
    job = get_workspace_job(session, workspace.workspace_id, job_id, for_update=True)
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
    job = get_workspace_job(session, workspace.workspace_id, job_id, for_update=True)
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
    _reserve_real_provider_job_if_enabled(
        session,
        request,
        job,
        workspace.principal.user_id,
    )
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
    job = get_workspace_job(session, workspace.workspace_id, job_id, for_update=True)
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
    source = get_workspace_job(session, workspace.workspace_id, job_id, for_update=True)
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
    release_credits(session, source)
    _reserve_real_provider_job_if_enabled(
        session,
        request,
        retried,
        workspace.principal.user_id,
        runnable_item_count=len(selected),
    )
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
    source = get_workspace_job(session, workspace.workspace_id, job_id, for_update=True)
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
    release_credits(session, source)
    _reserve_real_provider_job_if_enabled(
        session,
        request,
        cloned,
        workspace.principal.user_id,
        runnable_item_count=len(selected),
    )
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
    job = get_workspace_job(session, workspace.workspace_id, job_id, for_update=True)
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
    job = get_workspace_job(session, workspace.workspace_id, job_id, for_update=True)
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
    current_status = JobStatus(job.status)
    if (
        current_status == JobStatus.PROCESSING
        and plan.confirmed_at is not None
    ):
        return job_detail_response(session, job)
    if current_status != JobStatus.AWAITING_CONFIRMATION:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "JOB_NOT_AWAITING_CONFIRMATION",
            "任务当前状态不允许确认计划。",
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
    if job.type == JobType.DETAIL_PACK.value:
        from .xinghe_agent import (
            XingheAgentError,
            synchronize_confirmed_plan,
        )

        try:
            synchronize_confirmed_plan(session, job, plan)
        except XingheAgentError as exc:
            raise ApiError(
                status.HTTP_409_CONFLICT,
                "PLAN_INVALID",
                "The plan is invalid and cannot be confirmed.",
                {"reason": exc.code},
            ) from exc
    elif job.type == JobType.AMAZON_VISUAL_SUITE.value:
        from .amazon_visual_suite_provider import (
            AdapterValidationError,
            synchronize_confirmed_amazon_plan,
        )
        from .xinghe_agent import XingheAgentError

        try:
            synchronize_confirmed_amazon_plan(session, job, plan)
        except (AdapterValidationError, XingheAgentError) as exc:
            raise ApiError(
                status.HTTP_409_CONFLICT,
                "PLAN_INVALID",
                "The Amazon plan is invalid and cannot be confirmed.",
                {"reason": exc.code},
            ) from exc
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
    payload: (
        LocalEditJobCreate
        | ProductImageJobCreate
        | ReferenceRemixJobCreate
        | CreativeImageJobCreate
        | DetailPackJobCreate
        | AmazonVisualSuiteJobCreate
    ),
    *,
    detail_medium_price_micros: int = 45_000,
    detail_high_price_micros: int = 90_000,
) -> tuple[JobRecord, list[tuple[str, str, int]]]:
    if isinstance(payload, LocalEditJobCreate):
        item_count = 1
        asset_roles = [
            (payload.input.source_asset_id, "source", 0),
            (payload.input.selection_mask_asset_id, "selection_mask", 0),
        ]
    elif isinstance(payload, (ProductImageJobCreate, ReferenceRemixJobCreate)):
        item_count = payload.configuration.image_count
        asset_roles = [
            *[
                (asset_id, "product_reference", ordinal)
                for ordinal, asset_id in enumerate(payload.input.product_asset_ids)
            ],
            *[
                (asset_id, "style_reference", ordinal)
                for ordinal, asset_id in enumerate(payload.input.reference_asset_ids)
            ],
        ]
    elif isinstance(payload, CreativeImageJobCreate):
        item_count = payload.configuration.image_count
        asset_roles = [
            *[
                (asset_id, "product_reference", ordinal)
                for ordinal, asset_id in enumerate(payload.input.product_asset_ids)
            ],
            *[
                (asset_id, "competitor_reference", ordinal)
                for ordinal, asset_id in enumerate(payload.input.competitor_asset_ids)
            ],
        ]
    elif isinstance(payload, DetailPackJobCreate):
        item_count = payload.configuration.page_count * len(
            payload.input.product_groups
        )
        asset_roles = [
            *[
                (asset_id, "product_reference", ordinal)
                for group in payload.input.product_groups
                for ordinal, asset_id in enumerate(group.asset_ids)
            ],
            *[
                (asset_id, "style_reference", ordinal)
                for ordinal, asset_id in enumerate(payload.input.reference_asset_ids)
            ],
        ]
    else:
        item_count = 21
        asset_roles = []
        for role, asset_ids in (
            (
                "white_background_product",
                payload.input.white_background_product_asset_ids,
            ),
            ("product_detail", payload.input.detail_asset_ids),
            ("package_reference", payload.input.package_asset_ids),
            ("scene_reference", payload.input.scene_asset_ids),
            ("brand_reference", payload.input.brand_asset_ids),
            ("style_reference", payload.input.reference_asset_ids),
            (
                "competitor_reference",
                payload.input.competitor_reference_asset_ids,
            ),
        ):
            asset_roles.extend(
                (asset_id, role, ordinal) for ordinal, asset_id in enumerate(asset_ids)
            )
    if isinstance(payload, DetailPackJobCreate):
        minimum = item_count * detail_high_price_micros
        maximum = item_count * detail_high_price_micros
    else:
        minimum = item_count * min(detail_medium_price_micros, detail_high_price_micros)
        maximum = item_count * max(detail_medium_price_micros, detail_high_price_micros)
    _, _, credits = estimate_job(JobType(payload.type), item_count)
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


_REAL_PROVIDER_ENABLE_FLAGS = {
    JobType.PRODUCT_IMAGE.value: "product_image_provider_enabled",
    JobType.REFERENCE_REMIX.value: "reference_remix_provider_enabled",
    JobType.CREATIVE_IMAGE.value: "creative_image_provider_enabled",
    JobType.AMAZON_VISUAL_SUITE.value: "amazon_visual_suite_provider_enabled",
}


_AMAZON_INITIAL_IMAGE_REQUESTS = AMAZON_EXPECTED_ITEM_COUNT
_AMAZON_MAX_REDRAW_REQUESTS = AMAZON_EXPECTED_ITEM_COUNT
_AMAZON_PLANNER_REQUESTS = 1
_AMAZON_MAX_SUITE_REVIEW_REQUESTS = 2
_AMAZON_PROVIDER_REQUEST_ENVELOPE = (
    _AMAZON_INITIAL_IMAGE_REQUESTS
    + _AMAZON_MAX_REDRAW_REQUESTS
    + _AMAZON_PLANNER_REQUESTS
    + _AMAZON_MAX_SUITE_REVIEW_REQUESTS
)


def _reserve_real_provider_job_if_enabled(
    session: Session,
    request: Request,
    job: JobRecord,
    actor_user_id: str,
    *,
    runnable_item_count: int | None = None,
) -> None:
    settings = request.app.state.settings
    if settings.task_runner != "tengli":
        return
    enable_flag = _REAL_PROVIDER_ENABLE_FLAGS.get(job.type)
    if enable_flag is not None and not bool(getattr(settings, enable_flag, False)):
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "REAL_PROVIDER_NOT_REGISTERED",
            "?????????? Provider???????????",
            {"job_type": job.type, "provider_called": False},
        )
    configuration = job.configuration if isinstance(job.configuration, dict) else {}
    input_configuration = configuration.get("input")
    group_count = 0
    if job.type == JobType.DETAIL_PACK.value and isinstance(input_configuration, dict):
        groups = input_configuration.get("product_groups")
        if isinstance(groups, list):
            group_count = len(groups)
    image_cost = int(job.estimated_cost_max_micros or 0)
    if job.type == JobType.AMAZON_VISUAL_SUITE.value:
        job_id = getattr(job, "id", None)
        reusable_plan = (
            session.scalar(
                select(JobPlanRecord.id)
                .where(
                    JobPlanRecord.job_id == job_id,
                    JobPlanRecord.validation_status
                    == PlanValidationStatus.VALID.value,
                    JobPlanRecord.confirmed_at.is_not(None),
                )
                .limit(1)
            )
            if isinstance(job_id, str) and hasattr(session, "scalar")
            else None
        )
        planner_required = reusable_plan is None
        # Reserve the complete fail-closed Amazon automation envelope: 21 initial
        # images, up to 21 automatic redraws, one planner call, and up to two
        # whole-suite reviews. Reused plans release the unused planner allowance
        # during settlement rather than weakening the production reservation.
        estimated_cost = (
            image_cost * 2
            + settings.tengli_planner_reserve_micros
            * (_AMAZON_PLANNER_REQUESTS + _AMAZON_MAX_SUITE_REVIEW_REQUESTS)
        )
        provider_requests = _AMAZON_PROVIDER_REQUEST_ENVELOPE
        group_count = int(planner_required)
    elif enable_flag is not None:
        estimated_cost = image_cost
        provider_requests = (
            runnable_item_count
            if runnable_item_count is not None
            else job.expected_item_count
        )
    elif job.type == JobType.DETAIL_PACK.value:
        estimated_cost = (
            image_cost * 2 + group_count * settings.tengli_planner_reserve_micros
        )
        provider_requests = job.expected_item_count * 2 + group_count
    else:
        estimated_cost = image_cost * 2 + settings.tengli_planner_reserve_micros
        # Masked repair can make up to two edit calls and two visual-review
        # calls. Reserve the full fail-closed request envelope.
        provider_requests = 4
    reserve_provider_job_quota(
        session,
        job=job,
        actor_user_id=actor_user_id,
        estimated_cost_micros=estimated_cost,
        provider_request_count=provider_requests,
        daily_limit_micros=int(settings.tengli_daily_budget_usd * 1_000_000),
        monthly_limit_micros=int(settings.tengli_monthly_budget_usd * 1_000_000),
        daily_request_limit=settings.tengli_daily_request_limit,
        planner_reserve_micros=settings.tengli_planner_reserve_micros,
        image_budget_micros=image_cost,
        group_count=group_count,
    )



_AMAZON_ITEM_KEYS = (
    "MAIN-01",
    *(f"SECONDARY-{index:02d}" for index in range(1, 7)),
    *(f"A-DESKTOP-{index:02d}" for index in range(1, 8)),
    *(f"A-MOBILE-{index:02d}" for index in range(1, 8)),
)


def _job_item_key(job_type: str, ordinal: int) -> str:
    if job_type == JobType.LOCAL_EDIT.value:
        return "result"
    if job_type == JobType.AMAZON_VISUAL_SUITE.value:
        return _AMAZON_ITEM_KEYS[ordinal]
    if job_type in {
        JobType.PRODUCT_IMAGE.value,
        JobType.REFERENCE_REMIX.value,
        JobType.CREATIVE_IMAGE.value,
    }:
        return f"image-{ordinal + 1:03d}"
    return f"page-{ordinal + 1:03d}"

def _job_item_configuration(job_type: str, ordinal: int) -> dict[str, object]:
    if job_type != JobType.AMAZON_VISUAL_SUITE.value:
        return {}

    from .amazon_visual_suite_provider import AMAZON_ITEM_SPECS

    try:
        spec = AMAZON_ITEM_SPECS[ordinal]
    except IndexError as exc:
        raise ValueError("Amazon visual suite item ordinal is out of range.") from exc
    return {
        "item_key": spec.item_key,
        "group": spec.group,
        "group_ordinal": spec.group_ordinal,
        "target_width": spec.width,
        "target_height": spec.height,
        "target_size": {"width": spec.width, "height": spec.height},
        "contact_sheet": False,
    }


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
                item_key=_job_item_key(job.type, ordinal),
                ordinal=ordinal,
                status=JobItemStatus.PENDING.value,
                configuration=_job_item_configuration(job.type, ordinal),
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
    minimum, maximum, credits = estimate_job(JobType(source.type), len(selected))
    if source.type == JobType.LOCAL_EDIT.value:
        minimum = source.estimated_cost_min_micros or minimum
        maximum = source.estimated_cost_max_micros or maximum
    elif source.type == JobType.DETAIL_PACK.value:
        source_plan = session.scalar(
            select(JobPlanRecord)
            .where(JobPlanRecord.job_id == source.id)
            .order_by(JobPlanRecord.revision.desc())
            .limit(1)
        )
        cost = (
            source_plan.payload.get("cost")
            if source_plan is not None and isinstance(source_plan.payload, dict)
            else None
        )
        if isinstance(cost, dict):
            medium_price = cost.get("medium_unit_micros")
            high_price = cost.get("high_unit_micros")
            if (
                isinstance(medium_price, int)
                and not isinstance(medium_price, bool)
                and medium_price >= 0
                and isinstance(high_price, int)
                and not isinstance(high_price, bool)
                and high_price >= 0
            ):
                minimum = len(selected) * high_price
                maximum = len(selected) * high_price
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
    if source.type in {
        JobType.DETAIL_PACK.value,
        JobType.AMAZON_VISUAL_SUITE.value,
    }:
        source_plan = session.scalar(
            select(JobPlanRecord)
            .where(
                JobPlanRecord.job_id == source.id,
                JobPlanRecord.validation_status == PlanValidationStatus.VALID.value,
            )
            .order_by(JobPlanRecord.revision.desc())
            .limit(1)
        )
        if source_plan is not None and source_plan.confirmed_at is not None:
            copied_payload = dict(source_plan.payload)
            copied_payload["state"] = "confirmed"
            cost_value = copied_payload.get("cost")
            cost = dict(cost_value) if isinstance(cost_value, dict) else {}
            pending_items = [item for item in source_items if item.id in selected]
            pending_high = sum(item.quality == "high" for item in pending_items)
            pending_medium = len(pending_items) - pending_high
            medium_price = int(cost.get("medium_unit_micros", 45_000))
            high_price = int(cost.get("high_unit_micros", 90_000))
            cost.update(
                {
                    "pending_medium_count": pending_medium,
                    "pending_high_count": pending_high,
                    "estimated_pending_micros": (
                        pending_medium * medium_price + pending_high * high_price
                    ),
                }
            )
            copied_payload["cost"] = cost
            copied_payload["usage"] = {
                "planner": [],
                "planner_reused_from_job_id": source.id,
                "image": {
                    "reported_requests": 0,
                    "unreported_requests": 0,
                },
            }
            copied_payload["metrics"] = {
                "planning_time": 0,
                "planning_reused": True,
                "image_wall_time": None,
                "average_api_latency": None,
                "effective_seconds_per_page": None,
                "throughput_pages_per_second": 0.0,
                "job_wall_time": None,
                "success_count": 0,
                "failure_count": 0,
                "rate_limit_429_count": 0,
                "actual_concurrency": 0,
                "usage_missing_count": 0,
            }
            if source.type == JobType.AMAZON_VISUAL_SUITE.value:
                copied_payload["business_quality"] = {
                    "status": "pending_generation",
                    "policy_version": source_plan.validator_version,
                    "technical_delivery_status": "pending",
                    "manual_review_required": True,
                    "automatic_redraw_enabled": False,
                    "deterministic_findings": [],
                    "reused_from_job_id": source.id,
                }
            session.add(
                JobPlanRecord(
                    id=new_id("plan"),
                    workspace_id=target.workspace_id,
                    job_id=target.id,
                    revision=1,
                    schema_version=source_plan.schema_version,
                    payload=copied_payload,
                    payload_hash=canonical_hash(copied_payload),
                    validation_status=PlanValidationStatus.VALID.value,
                    validation_errors=[],
                    validator_version=source_plan.validator_version,
                    validated_at=utc_now(),
                    confirmed_at=utc_now(),
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
    if job.type == JobType.DETAIL_PACK.value:
        from .xinghe_agent import validate_editable_plan_payload

        return validate_editable_plan_payload(payload, job.expected_item_count)
    if job.type == JobType.AMAZON_VISUAL_SUITE.value:
        from .amazon_visual_suite_provider import (
            validate_editable_amazon_plan_payload,
        )

        return validate_editable_amazon_plan_payload(payload)
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
