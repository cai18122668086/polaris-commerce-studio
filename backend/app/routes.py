from typing import Annotated
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .database import get_session
from .errors import ApiError, UploadValidationError
from .models import AssetRecord, JobRecord, utc_now
from .schemas import (
    TERMINAL_JOB_STATUSES,
    WORKSPACE_ID_PATTERN,
    AssetListResponse,
    AssetOrigin,
    AssetResponse,
    HealthResponse,
    JobCreate,
    JobListResponse,
    JobResponse,
    JobStatus,
    JobType,
)

router = APIRouter()
SessionDependency = Annotated[Session, Depends(get_session)]


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        task_runner="mock",
    )


@router.post(
    "/api/assets",
    response_model=AssetResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["assets"],
)
async def upload_asset(
    request: Request,
    session: SessionDependency,
    workspace_id: Annotated[
        str,
        Form(
            min_length=1,
            max_length=64,
            pattern=WORKSPACE_ID_PATTERN,
        ),
    ],
    file: Annotated[UploadFile, File()],
    origin: Annotated[AssetOrigin, Form()] = AssetOrigin.UPLOAD,
) -> AssetRecord:
    try:
        stored = await request.app.state.storage.save_image(file, workspace_id)
    except UploadValidationError as exc:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            exc.code,
            exc.message,
        ) from exc

    asset = AssetRecord(
        id=f"asset_{uuid4().hex}",
        workspace_id=workspace_id,
        filename=stored.filename,
        content_type=stored.content_type,
        byte_size=stored.byte_size,
        width=stored.width,
        height=stored.height,
        storage_key=stored.storage_key,
        origin=origin.value,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@router.get(
    "/api/assets",
    response_model=AssetListResponse,
    tags=["assets"],
)
def list_assets(
    session: SessionDependency,
    workspace_id: Annotated[
        str,
        Query(
            min_length=1,
            max_length=64,
            pattern=WORKSPACE_ID_PATTERN,
        ),
    ],
    origin: AssetOrigin | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AssetListResponse:
    filters = [AssetRecord.workspace_id == workspace_id]
    if origin is not None:
        filters.append(AssetRecord.origin == origin.value)
    items = session.scalars(
        select(AssetRecord)
        .where(*filters)
        .order_by(AssetRecord.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    total = session.scalar(
        select(func.count()).select_from(AssetRecord).where(*filters)
    )
    return AssetListResponse(
        items=[AssetResponse.model_validate(item) for item in items],
        total=total or 0,
    )


@router.get(
    "/api/assets/{asset_id}",
    response_model=AssetResponse,
    tags=["assets"],
)
def get_asset(asset_id: str, session: SessionDependency) -> AssetRecord:
    asset = session.get(AssetRecord, asset_id)
    if not asset:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "ASSET_NOT_FOUND",
            "未找到指定素材。",
        )
    return asset


@router.post(
    "/api/jobs",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["jobs"],
)
def create_job(
    payload: JobCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
) -> JobRecord:
    _ensure_assets_exist(session, payload.workspace_id, payload.input_asset_ids)
    job = JobRecord(
        id=f"job_{uuid4().hex}",
        workspace_id=payload.workspace_id,
        type=payload.type.value,
        status=JobStatus.QUEUED.value,
        progress=0,
        input_asset_ids=payload.input_asset_ids,
        configuration=payload.configuration,
        prompt_version=payload.prompt_version,
        strategy_version=payload.strategy_version,
        estimated_cost=payload.estimated_cost,
        usage={"reported": False, "reason": "not_started"},
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    queue_task_id = _dispatch_job(
        request,
        background_tasks,
        session,
        job,
    )
    if queue_task_id:
        job.queue_task_id = queue_task_id
        session.commit()
        session.refresh(job)
    return job


@router.get(
    "/api/jobs",
    response_model=JobListResponse,
    tags=["jobs"],
)
def list_jobs(
    session: SessionDependency,
    workspace_id: Annotated[
        str,
        Query(
            min_length=1,
            max_length=64,
            pattern=WORKSPACE_ID_PATTERN,
        ),
    ],
    job_type: Annotated[JobType | None, Query(alias="type")] = None,
    job_status: Annotated[JobStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JobListResponse:
    filters = [JobRecord.workspace_id == workspace_id]
    if job_type is not None:
        filters.append(JobRecord.type == job_type.value)
    if job_status is not None:
        filters.append(JobRecord.status == job_status.value)
    items = session.scalars(
        select(JobRecord)
        .where(*filters)
        .order_by(JobRecord.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    total = session.scalar(select(func.count()).select_from(JobRecord).where(*filters))
    return JobListResponse(
        items=[JobResponse.model_validate(item) for item in items],
        total=total or 0,
    )


@router.get(
    "/api/jobs/{job_id}",
    response_model=JobResponse,
    tags=["jobs"],
)
def get_job(job_id: str, session: SessionDependency) -> JobRecord:
    return _get_job_or_error(session, job_id)


@router.post(
    "/api/jobs/{job_id}/cancel",
    response_model=JobResponse,
    tags=["jobs"],
)
def cancel_job(job_id: str, session: SessionDependency) -> JobRecord:
    job = _get_job_or_error(session, job_id)
    if JobStatus(job.status) in TERMINAL_JOB_STATUSES:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "JOB_NOT_CANCELLABLE",
            "当前任务状态不能取消。",
            {"status": job.status},
        )
    job.status = JobStatus.CANCELLED.value
    job.finished_at = utc_now()
    job.error_code = "USER_CANCELLED"
    job.error_message = "任务已由用户取消。"
    session.commit()
    session.refresh(job)
    return job


@router.post(
    "/api/jobs/{job_id}/retry",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["jobs"],
)
def retry_job(
    job_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    session: SessionDependency,
) -> JobRecord:
    source = _get_job_or_error(session, job_id)
    retryable_statuses = {
        JobStatus.FAILED,
        JobStatus.PARTIAL,
        JobStatus.CANCELLED,
    }
    if JobStatus(source.status) not in retryable_statuses:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "JOB_NOT_RETRYABLE",
            "只有失败、部分成功或已取消的任务可以重试。",
            {"status": source.status},
        )

    retried = JobRecord(
        id=f"job_{uuid4().hex}",
        workspace_id=source.workspace_id,
        type=source.type,
        status=JobStatus.QUEUED.value,
        progress=0,
        input_asset_ids=source.input_asset_ids,
        configuration=source.configuration,
        prompt_version=source.prompt_version,
        strategy_version=source.strategy_version,
        estimated_cost=source.estimated_cost,
        retry_of_job_id=source.id,
        parent_job_id=source.parent_job_id or source.id,
        usage={"reported": False, "reason": "not_started"},
    )
    session.add(retried)
    session.commit()
    session.refresh(retried)

    queue_task_id = _dispatch_job(
        request,
        background_tasks,
        session,
        retried,
    )
    if queue_task_id:
        retried.queue_task_id = queue_task_id
        session.commit()
        session.refresh(retried)
    return retried


def _get_job_or_error(session: Session, job_id: str) -> JobRecord:
    job = session.get(JobRecord, job_id)
    if not job:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "JOB_NOT_FOUND",
            "未找到指定任务。",
        )
    return job


def _ensure_assets_exist(
    session: Session,
    workspace_id: str,
    asset_ids: list[str],
) -> None:
    existing_ids = set(
        session.scalars(
            select(AssetRecord.id).where(
                AssetRecord.workspace_id == workspace_id,
                AssetRecord.id.in_(asset_ids),
            )
        ).all()
    )
    missing_ids = [asset_id for asset_id in asset_ids if asset_id not in existing_ids]
    if missing_ids:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "INPUT_ASSET_NOT_FOUND",
            "部分输入素材不存在或不属于当前工作区。",
            {"asset_ids": missing_ids},
        )


def _dispatch_job(
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session,
    job: JobRecord,
) -> str | None:
    settings = request.app.state.settings
    if not settings.auto_process_jobs:
        return None
    if settings.task_dispatcher == "inline":
        background_tasks.add_task(request.app.state.task_runner.run, job.id)
        return None

    try:
        from .tasks import process_job

        result = process_job.delay(job.id)
    except Exception as exc:
        job.status = JobStatus.FAILED.value
        job.error_code = "TASK_QUEUE_UNAVAILABLE"
        job.error_message = "任务队列暂时不可用，请稍后重试。"
        job.finished_at = utc_now()
        session.commit()
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "TASK_QUEUE_UNAVAILABLE",
            "任务队列暂时不可用，请稍后重试。",
            {"job_id": job.id},
        ) from exc
    return result.id
