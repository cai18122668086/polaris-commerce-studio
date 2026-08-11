from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import (
    Principal,
    WorkspaceDependency,
    WorkspaceWriteDependency,
    get_principal,
)
from .database import get_session
from .domain import AssetLifecycleStatus
from .domestic_main_image_models import (
    DomesticMainImageSourceRecord,
    DomesticMainImageTaskRecord,
)
from .domestic_main_image_runtime import (
    DomesticMainImageRuntimeError,
    canonical_json_sha256,
)
from .domestic_main_image_schemas import (
    DomesticMainImageAuthorizeRequest,
    DomesticMainImageCapabilityResponse,
    DomesticMainImageIdentityRequest,
    DomesticMainImagePlanRow,
    DomesticMainImageSourceResponse,
    DomesticMainImageTaskCreate,
    DomesticMainImageTaskResponse,
)
from .domestic_main_image_service import (
    DomesticMainImageOrchestrator,
    materialize_asset,
)
from .errors import ApiError
from .models import AssetRecord
from .services import new_id

router = APIRouter(prefix="/api/v1")
SessionDependency = Annotated[Session, Depends(get_session)]
PrincipalDependency = Annotated[Principal, Depends(get_principal)]


def _orchestrator(request: Request) -> DomesticMainImageOrchestrator:
    return cast(
        DomesticMainImageOrchestrator,
        request.app.state.domestic_main_image_orchestrator,
    )


def _task(
    session: Session, workspace_id: str, task_id: str
) -> DomesticMainImageTaskRecord:
    record = session.scalar(
        select(DomesticMainImageTaskRecord).where(
            DomesticMainImageTaskRecord.id == task_id,
            DomesticMainImageTaskRecord.workspace_id == workspace_id,
        )
    )
    if record is None:
        raise ApiError(
            404, "DOMESTIC_MAIN_IMAGE_TASK_NOT_FOUND", "未找到国内主图任务。"
        )
    return record


def _text(value: object, fallback: str = "") -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return " → ".join(str(item) for item in value)
    if isinstance(value, dict):
        return "；".join(f"{key}: {item}" for key, item in value.items())
    return fallback


def _plan_rows(task: DomesticMainImageTaskRecord) -> list[DomesticMainImagePlanRow]:
    plan = task.plan_payload or task.session_payload.get("plan")
    if not isinstance(plan, dict):
        return []
    commercial = plan.get("commercial_orchestration")
    tasks = (
        commercial.get("page_task_table", []) if isinstance(commercial, dict) else []
    )
    pages = plan.get("pages", [])
    rows: list[DomesticMainImagePlanRow] = []
    for index in range(min(6, len(tasks), len(pages))):
        page = pages[index]
        page_task = tasks[index]
        execution = page.get("approved_page_execution_contract", {})
        performance = page.get("visual_performance_contract", {})
        rows.append(
            DomesticMainImagePlanRow(
                page_index=index,
                page_role=_text(page.get("page_role"), f"PAGE_{index}"),
                main_selling_point=_text(
                    page_task.get("selling_point_display_label")
                    or page_task.get("primary_selling_point_source_text")
                ),
                supporting_selling_points=[
                    str(item) for item in page_task.get("supporting_selling_points", [])
                ],
                visual_proof=_text(page_task.get("visual_proof_method")),
                composition_and_subject=_text(
                    execution.get("composition_blueprint") or page.get("composition")
                ),
                reading_path_and_type_hierarchy=(
                    _text(page.get("reading_path"))
                    + "；"
                    + _text(page.get("type_hierarchy"))
                ).strip("；"),
                non_repetition_reason=_text(page_task.get("non_repetition_reason")),
                commercial_closure=_text(performance.get("commercial_closure")),
            )
        )
    return rows


def _response(
    session: Session, task: DomesticMainImageTaskRecord
) -> DomesticMainImageTaskResponse:
    sources = session.scalars(
        select(DomesticMainImageSourceRecord)
        .where(DomesticMainImageSourceRecord.task_id == task.id)
        .order_by(DomesticMainImageSourceRecord.ordinal)
    ).all()
    request = task.generation_request or {}
    references = request.get("reference_allowlist", [])
    edit_target = request.get("edit_target")
    plan = task.plan_payload or task.session_payload.get("plan") or {}
    style = plan.get("campaign_style") if isinstance(plan, dict) else None
    style_summary = None
    if isinstance(style, dict):
        style_summary = "；".join(
            filter(
                None,
                [
                    _text(style.get("campaign_thesis")),
                    _text(style.get("palette_roles")),
                    _text(style.get("photography_finish")),
                ],
            )
        )
    return DomesticMainImageTaskResponse(
        id=task.id,
        workspace_id=task.workspace_id,
        technical_status=task.technical_status,
        skill_state=task.skill_state,
        revision=task.revision,
        allowed_actions=[
            str(item) for item in task.session_payload.get("allowed_actions", [])
        ],
        skill_name=task.skill_name,
        skill_version=task.skill_version,
        skill_digest=task.skill_digest,
        startup_git_commit=task.startup_git_commit,
        provider_capability_status=task.provider_capability_status,
        image_model=task.image_model,
        image_model_version=task.image_model_version,
        campaign_style_summary=style_summary,
        plan=_plan_rows(task),
        generation_request_ready=bool(request),
        generation_prompt_sha256=(
            str(request.get("prompt_sha256")) if request.get("prompt_sha256") else None
        ),
        reference_roles=[
            str(item.get("role")) for item in references if isinstance(item, dict)
        ],
        edit_target_role=(
            str(edit_target.get("role")) if isinstance(edit_target, dict) else None
        ),
        last_error_code=task.last_error_code,
        last_error_message=task.last_error_message,
        sources=[
            DomesticMainImageSourceResponse(
                asset_id=source.asset_id,
                evidence_id=source.evidence_id,
                ordinal=source.ordinal,
                role=cast(Any, source.source_role),
                sha256=source.asset_sha256,
            )
            for source in sources
        ],
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.get(
    "/domestic-main-image/capability",
    response_model=DomesticMainImageCapabilityResponse,
    tags=["domestic-main-image"],
)
def domestic_main_image_capability(
    request: Request,
    _principal: PrincipalDependency,
) -> DomesticMainImageCapabilityResponse:
    ready = bool(request.app.state.domestic_main_image_harness_ready)
    provider_enabled = bool(
        request.app.state.settings.domestic_main_image_provider_enabled
    )
    return DomesticMainImageCapabilityResponse(
        skill_runtime="available" if ready else "unavailable",
        planning="available" if ready else "unavailable",
        image_provider=("unverified" if provider_enabled else "disabled"),
        paid_generation_allowed=False,
        reason_code=(None if ready else "SKILL_PYTHON_RUNTIME_INCOMPATIBLE"),
    )


@router.post(
    "/workspaces/{workspace_id}/domestic-main-image/tasks",
    response_model=DomesticMainImageTaskResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["domestic-main-image"],
)
async def create_domestic_main_image_task(
    payload: DomesticMainImageTaskCreate,
    request: Request,
    workspace: WorkspaceWriteDependency,
    session: SessionDependency,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=255)
    ],
) -> DomesticMainImageTaskResponse:
    request_hash = canonical_json_sha256(payload.model_dump(mode="json"))
    existing = session.scalar(
        select(DomesticMainImageTaskRecord).where(
            DomesticMainImageTaskRecord.workspace_id == workspace.workspace_id,
            DomesticMainImageTaskRecord.created_by_user_id
            == workspace.principal.user_id,
            DomesticMainImageTaskRecord.create_idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.create_request_sha256 != request_hash:
            raise ApiError(
                409, "IDEMPOTENCY_KEY_REUSED", "该幂等键已用于不同的主图任务。"
            )
        return _response(session, existing)
    if not request.app.state.domestic_main_image_harness_ready:
        raise ApiError(
            503,
            "DOMESTIC_MAIN_IMAGE_RUNTIME_UNAVAILABLE",
            "当前 Python 运行时无法加载原版国内主图 Skill。",
        )
    asset_ids = [source.asset_id for source in payload.sources]
    assets = session.scalars(
        select(AssetRecord).where(
            AssetRecord.workspace_id == workspace.workspace_id,
            AssetRecord.id.in_(asset_ids),
            AssetRecord.lifecycle_status == AssetLifecycleStatus.READY.value,
            AssetRecord.deleted_at.is_(None),
        )
    ).all()
    by_id = {asset.id: asset for asset in assets}
    if set(by_id) != set(asset_ids):
        raise ApiError(
            422, "SOURCE_ASSET_INVALID", "部分商品原图不可用或不属于当前工作区。"
        )
    sources: list[dict[str, Any]] = []
    for ordinal, source in enumerate(payload.sources):
        asset = by_id[source.asset_id]
        path = await materialize_asset(
            storage=request.app.state.storage,
            asset=asset,
            cache_root=request.app.state.settings.domestic_main_image_asset_cache_dir,
        )
        sources.append(
            {
                "asset_id": asset.id,
                "evidence_id": f"evidence-{ordinal + 1:02d}",
                "ordinal": ordinal,
                "role": source.role,
                "path": str(path),
                "sha256": asset.sha256,
            }
        )
    request_id = new_id("mainreq")
    raw_input = {
        "request_id": request_id,
        "profile01_semantics_read": False,
        "product": {
            "name": payload.product_name,
            "category": payload.category,
            "product_information": payload.product_information,
            "original_references": [
                {
                    "evidence_id": source["evidence_id"],
                    "path": source["path"],
                    "asset_id": source["asset_id"],
                    "sha256": source["sha256"],
                    "source_role": source["role"],
                    "role": "PRODUCT_IDENTITY_AUTHORITY",
                }
                for source in sources
            ],
            "verified_attributes": payload.verified_attributes,
            "verified_selling_points": payload.verified_selling_points,
            "verified_scenes": payload.verified_scenes,
            "verified_offers": payload.verified_offers,
            "verified_service_or_trust_facts": payload.verified_service_or_trust_facts,
        },
    }
    try:
        task = _orchestrator(request).create_task(
            session,
            workspace_id=workspace.workspace_id,
            user_id=workspace.principal.user_id,
            raw_input=raw_input,
            sources=sources,
            idempotency_key=idempotency_key,
            request_sha256=request_hash,
        )
    except DomesticMainImageRuntimeError as exc:
        raise ApiError(503, exc.code, str(exc)) from exc
    return _response(session, task)


@router.get(
    "/workspaces/{workspace_id}/domestic-main-image/tasks/{task_id}",
    response_model=DomesticMainImageTaskResponse,
    tags=["domestic-main-image"],
)
def get_domestic_main_image_task(
    task_id: str,
    workspace: WorkspaceDependency,
    session: SessionDependency,
) -> DomesticMainImageTaskResponse:
    return _response(session, _task(session, workspace.workspace_id, task_id))


@router.post(
    "/workspaces/{workspace_id}/domestic-main-image/tasks/{task_id}/identity",
    response_model=DomesticMainImageTaskResponse,
    tags=["domestic-main-image"],
)
def lock_domestic_main_image_identity(
    task_id: str,
    payload: DomesticMainImageIdentityRequest,
    request: Request,
    workspace: WorkspaceWriteDependency,
    session: SessionDependency,
) -> DomesticMainImageTaskResponse:
    task = _task(session, workspace.workspace_id, task_id)
    try:
        task = _orchestrator(request).lock_identity_and_compile(
            session,
            task=task,
            expected_revision=payload.expected_revision,
            identity_contract=payload.identity_contract,
        )
    except DomesticMainImageRuntimeError as exc:
        raise ApiError(409, exc.code, str(exc)) from exc
    return _response(session, task)


@router.post(
    "/workspaces/{workspace_id}/domestic-main-image/tasks/{task_id}/authorize",
    response_model=DomesticMainImageTaskResponse,
    tags=["domestic-main-image"],
)
def authorize_domestic_main_image_plan(
    task_id: str,
    payload: DomesticMainImageAuthorizeRequest,
    request: Request,
    workspace: WorkspaceWriteDependency,
    session: SessionDependency,
) -> DomesticMainImageTaskResponse:
    task = _task(session, workspace.workspace_id, task_id)
    try:
        task = _orchestrator(request).authorize_and_prepare_first_generation(
            session,
            task=task,
            expected_revision=payload.expected_revision,
            approval_text=payload.approval_text,
        )
    except DomesticMainImageRuntimeError as exc:
        raise ApiError(409, exc.code, str(exc)) from exc
    return _response(session, task)
