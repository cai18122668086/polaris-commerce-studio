"""Owner-scoped editing API. All decoding, ASR and rendering run in a worker."""

import hashlib
from collections import defaultdict
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import SessionDependency, WorkspaceContext, require_workspace_write
from .config import Settings
from .errors import ApiError
from .motion_browser_originals import original_startup_assets
from .motion_library import MOTION_SHA256, read_json, sha256
from .motion_library_validation import group_status, motion_evidence_directory
from .motion_local_dependencies import local_dependencies
from .motion_parameter_contracts import input_contract
from .video_editing_catalog import (
    asset_metadata,
    audio_asset,
    catalog_summary,
    original_input_variants,
    template_dependencies,
)
from .video_editing_contracts import (
    EditingCarriedRevision,
    EditingExportConfirmation,
    EditingFilmReviewWrite,
    EditingSourceUploadResponse,
    EditingTaskCreate,
    EditingTaskResponse,
    EditingTemplateSample,
    EditingWorksResponse,
)
from .video_editing_delivery_checkpoint import verified_delivery_file
from .video_editing_native_plans import admit_render_plan
from .video_editing_overlay_templates import MIN_OVERLAY_TYPES, overlay_templates
from .video_editing_preview_base import preview_base_attempt
from .video_editing_source_lineage import (
    freeze_generation_source,
    source_origin,
    uploaded_script_reference,
)
from .video_editing_task_models import (
    EditingArtifactRecord,
    EditingNativePlanRecord,
    EditingPlanningTaskRecord,
    EditingSourceRecord,
    EditingTaskRecord,
    EditingTranscriptRevisionRecord,
)
from .video_editing_transcript_store import recorded_source_frame
from .video_generation import own_job
from .video_studio_models import VideoProjectRecord, VideoScriptVersionRecord
from .video_studio_routes import VideoWorkspace, digest

router = APIRouter(
    prefix="/api/v1/video-studio/workspaces/{workspace_id}",
    tags=["video-editing-tasks"],
)


def enabled(request: Request) -> Settings:
    settings = request.app.state.settings
    if not settings.video_editing_enabled:
        raise ApiError(503, "EDITING_DISABLED", "剪辑服务尚未开放。")
    package = settings.video_editing_library_dir
    if not (package / "adapter.py").is_file():
        raise ApiError(503, "EDITING_LIBRARY_MISSING", "剪辑原库尚未安装。")
    return settings


def own_project(
    session: Session, workspace: WorkspaceContext, project_id: str
) -> VideoProjectRecord:
    project = session.get(VideoProjectRecord, project_id)
    if (
        not project
        or project.workspace_id != workspace.workspace_id
        or project.owner_user_id != workspace.principal.user_id
    ):
        raise ApiError(404, "VIDEO_PROJECT_NOT_FOUND", "未找到项目。")
    return project


def own_task(
    session: Session, workspace: WorkspaceContext, task_id: str
) -> EditingTaskRecord:
    row = session.get(EditingTaskRecord, task_id)
    if (
        not row
        or row.workspace_id != workspace.workspace_id
        or row.owner_user_id != workspace.principal.user_id
    ):
        raise ApiError(404, "EDITING_NOT_FOUND", "未找到剪辑任务。")
    return row


def artifact_visible(row: EditingTaskRecord, record: EditingArtifactRecord) -> bool:
    if (
        row.status not in {"completed", "awaiting_review"}
        or record.role == "staged_final"
    ):
        return False
    if record.role != "final":
        return True
    if row.status != "completed":
        return False
    if row.options.get("delivery") != "preview_first":
        return True
    confirmed = row.checkpoint.get("export_confirmation", {})
    return (
        confirmed.get("final_id") == record.id
        and confirmed.get("final_sha256") == record.sha256
    )


def artifact_response(
    row: EditingTaskRecord, record: EditingArtifactRecord
) -> dict[str, Any]:
    base = f"/api/v1/video-studio/workspaces/{row.workspace_id}/editing-tasks/{row.id}"
    return {
        "id": record.id,
        "role": record.role,
        "mime": record.mime,
        "sha256": record.sha256,
        "bytes": record.bytes,
        "duration_ms": record.duration_ms,
        "url": base + "/artifacts/" + record.id,
    }


def response(
    row: EditingTaskRecord,
    session: Session,
    source: EditingSourceRecord | None = None,
    *,
    artifacts: Sequence[EditingArtifactRecord] | None = None,
) -> dict[str, Any]:
    if source is None:
        source = session.get(EditingSourceRecord, row.source_id)
    if artifacts is None:
        artifacts = session.scalars(
            select(EditingArtifactRecord).where(EditingArtifactRecord.task_id == row.id)
        ).all()
    counts = next(
        (
            item.validation.get("motion_counts")
            for item in artifacts
            if (row.status, item.role)
            in {("awaiting_review", "staged_final"), ("completed", "final")}
        ),
        None,
    )
    transcript = next((item for item in artifacts if item.role == "transcript"), None)
    visible = [item for item in artifacts if artifact_visible(row, item)]
    saved_review = row.checkpoint.get("manual_review")
    manual_review = (
        saved_review
        if saved_review
        and any(
            (item.role, item.id, item.sha256)
            == (
                "final",
                saved_review["final_artifact_id"],
                saved_review["final_sha256"],
            )
            and item.validation.get("decoded") is True
            for item in visible
        )
        else None
    )
    return {
        "id": row.id,
        "project_id": row.project_id,
        "source_id": row.source_id,
        **({"source_origin": source_origin(source)} if source else {}),
        "source_frame": recorded_source_frame(transcript) if transcript else None,
        "status": row.status,
        "stage": row.stage,
        "revision": row.revision,
        "attempts": row.attempts,
        "error_code": row.error_code,
        "cancel_requested": row.cancel_requested,
        "created_at": row.created_at.replace(tzinfo=UTC)
        if row.created_at.tzinfo is None
        else row.created_at,
        "library_release": row.library_release,
        "options": row.options,
        "carried_revision": row.checkpoint.get("carried_revision"),
        "motion_counts": counts,
        "layout_findings": row.checkpoint.get("layout_findings")
        if row.status == "failed"
        else None,
        "manual_review": manual_review,
        "review": {
            "semantic": "unreviewed",
            "visual": "unreviewed",
            "timing": "unreviewed",
            **(
                {
                    key: manual_review["assessment"][key]
                    for key in ("semantic", "visual", "timing", "listening")
                }
                if manual_review
                else {}
            ),
            **(
                {
                    "delivery": "confirmed"
                    if row.checkpoint.get("export_confirmation")
                    else "unconfirmed"
                }
                if row.options.get("delivery") == "preview_first"
                else {}
            ),
        },
        "artifacts": [artifact_response(row, item) for item in visible],
    }


def dispatch(request: Request, task_id: str) -> None:
    """Production delivery belongs to maintenance, never the request thread.

    The committed task is the durable outbox. A broker outage must not make a
    successful create request hang and tempt users to submit a duplicate job.
    """
    callback = getattr(request.app.state, "editing_dispatcher", None)
    if callback:
        callback(task_id)


@router.get("/editing-library")
def library(
    request: Request,
    workspace: VideoWorkspace,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=132),
) -> dict[str, Any]:
    settings = enabled(request)
    package = settings.video_editing_library_dir
    evidence = motion_evidence_directory(settings)
    catalog = read_json(package / "catalog/groups.json")
    return {
        "release": MOTION_SHA256,
        "total": len(catalog["groups"]),
        "bundled_assets": len(read_json(package / "asset-manifest.json")["assets"]),
        "external_references": len(
            read_json(package / "catalog/external-resources.json")["resources"]
        ),
        "groups": [
            {**g, **group_status(evidence, g["id"])}
            for g in catalog["groups"][offset : offset + limit]
        ],
        "next_offset": offset + limit
        if offset + limit < len(catalog["groups"])
        else None,
        "summary": catalog_summary(package, evidence),
    }


@router.post("/editing-sources", response_model=EditingSourceUploadResponse)
async def upload_source(
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
    project_id: Annotated[UUID, Form()],
    file: Annotated[UploadFile, File()],
    confirmed_version_id: Annotated[UUID | None, Form()] = None,
    request_id: Annotated[UUID | None, Form()] = None,
) -> dict[str, Any]:
    require_workspace_write(workspace)
    settings = enabled(request)
    own_project(session, workspace, str(project_id))
    reference = None
    if confirmed_version_id:
        version = session.get(VideoScriptVersionRecord, str(confirmed_version_id))
        if (
            not version
            or version.project_id != str(project_id)
            or version.kind != "confirmed"
        ):
            raise ApiError(422, "EDITING_SCRIPT_INVALID", "请选择本项目的确认稿版本。")
        reference = uploaded_script_reference(version)
        if reference is None:
            raise ApiError(
                409, "EDITING_UPLOAD_SCRIPT_CHANGED", "这份确认稿的写稿来源无法核对。"
            )
    if file.content_type not in {"video/mp4", "video/quicktime", "video/webm"}:
        raise ApiError(422, "EDITING_SOURCE_TYPE", "请上传 MP4、MOV 或 WebM 视频。")
    candidate = uuid4()
    sid = str(
        uuid5(
            NAMESPACE_URL,
            "polaris:editing-source-upload:"
            + digest(
                {
                    "workspace_id": workspace.workspace_id,
                    "owner_user_id": workspace.principal.user_id,
                    "request_id": str(request_id),
                }
            ),
        )
        if request_id
        else candidate
    )
    # Concurrent uploads write separate candidates. Only the winning row owns a file.
    target = (
        settings.video_editing_tasks_dir / "sources" / str(candidate) / "source.media"
    )
    length = 0
    hasher = hashlib.sha256()
    created_dir = False
    keep_file = False
    try:
        target.parent.mkdir(parents=True)
        created_dir = True
        with target.open("xb") as out:
            while block := await file.read(1024 * 1024):
                length += len(block)
                if length > 500 * 1024 * 1024:
                    raise ApiError(
                        413, "EDITING_SOURCE_TOO_LARGE", "视频不能超过 500 MB。"
                    )
                out.write(block)
                hasher.update(block)
        if length == 0:
            raise ApiError(422, "EDITING_SOURCE_EMPTY", "视频文件为空。")
        row = EditingSourceRecord(
            id=sid,
            workspace_id=workspace.workspace_id,
            owner_user_id=workspace.principal.user_id,
            project_id=str(project_id),
            confirmed_version_id=str(confirmed_version_id)
            if confirmed_version_id
            else None,
            kind="upload_asset",
            media_path=str(target.resolve()),
            media_sha256=hasher.hexdigest(),
            details={
                "mime": file.content_type,
                "bytes": length,
                **({"confirmed_script_reference": reference} if reference else {}),
            },
        )
        existing = session.get(EditingSourceRecord, sid) if request_id else None
        if existing is None:
            session.add(row)
            # A lost commit acknowledgement may still leave a row owning this file.
            keep_file = True
            try:
                session.commit()
            except IntegrityError:
                keep_file = False
                session.rollback()
                existing = session.get(EditingSourceRecord, sid)
                if existing is None:
                    raise
        if existing is not None:
            if (
                existing.kind != row.kind
                or existing.workspace_id != row.workspace_id
                or existing.owner_user_id != row.owner_user_id
                or existing.project_id != row.project_id
                or existing.confirmed_version_id != row.confirmed_version_id
                or existing.media_sha256 != row.media_sha256
                or existing.details.get("mime") != file.content_type
                or existing.details.get("bytes") != length
            ):
                raise ApiError(
                    409,
                    "EDITING_SOURCE_REQUEST_REUSED",
                    "上传编号已用于另一份原片或项目。",
                )
            if (
                "confirmed_script_reference" in existing.details
                and existing.details["confirmed_script_reference"] != reference
            ):
                raise ApiError(
                    409, "EDITING_UPLOAD_SCRIPT_CHANGED", "原片绑定的参考确认稿已变化。"
                )
            try:
                path = Path(existing.media_path)
                valid = (
                    path.stat().st_size == length
                    and sha256(path) == existing.media_sha256
                )
            except OSError:
                valid = False
            if not valid:
                raise ApiError(
                    409,
                    "EDITING_SOURCE_CHANGED",
                    "已保存的原片不可用，请重新选择文件。",
                )
            row = existing
    finally:
        if created_dir and not keep_file:
            with suppress(OSError):
                target.unlink(missing_ok=True)
                target.parent.rmdir()
        await file.close()
    return {
        "id": row.id,
        "project_id": row.project_id,
        "sha256": row.media_sha256,
        "bytes": length,
    }


@router.get("/editing-library/groups/{group_id}")
def describe_group(
    group_id: str, request: Request, workspace: VideoWorkspace
) -> dict[str, Any]:
    settings = enabled(request)
    package = settings.video_editing_library_dir
    catalog = read_json(package / "catalog/groups.json")
    canonical = catalog.get("aliases", {}).get(group_id, group_id)
    group = next((g for g in catalog["groups"] if g["id"] == canonical), None)
    if not group:
        raise ApiError(404, "EDITING_GROUP_NOT_FOUND", "未找到原库动效。")
    bindings = local_dependencies(settings.video_editing_native_bindings_file)
    runtime = group_status(motion_evidence_directory(settings), group["id"])
    return {
        "release": MOTION_SHA256,
        "group": group,
        "input_schema": read_json(package / group["input_schema"]),
        "parameter_contract": input_contract(package, group),
        "template_dependencies": template_dependencies(
            package,
            group,
            bindings,
            manifest=settings.video_editing_native_bindings_file,
        ),
        "original_input_variants": original_input_variants(
            package, group, bindings, runtime["runtime_evidence"]
        ),
        "original_startup_assets": original_startup_assets(
            package, group, settings.video_editing_native_bindings_file
        ),
        "dependency_scope": (
            "template inputs, indexed browser fonts and audited native engine "
            "references; "
            "native preflight may require implicit engine dependencies"
        ),
        "contract": read_json(package / group["contract"])
        if group.get("contract")
        else None,
        "contract_status": "declared"
        if group.get("contract")
        else "inspect_native_schema_and_entry",
        **runtime,
        "historical_input_not_used_as_new_defaults": True,
    }


@router.get("/editing-library/resources")
def library_resources(
    request: Request,
    workspace: VideoWorkspace,
    source: str = Query(default="bundled", pattern="^(bundled|external)$"),
    kind: str | None = None,
    search: str = Query(default="", max_length=100),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    settings = enabled(request)
    package = settings.video_editing_library_dir
    rows = (
        read_json(package / "asset-manifest.json")["assets"]
        if source == "bundled"
        else read_json(package / "catalog/external-resources.json")["resources"]
    )
    if kind:
        rows = [r for r in rows if r.get("kind") == kind]
    if search.strip():
        query = search.strip().casefold()
        rows = [
            r
            for r in rows
            if query
            in (
                asset_metadata(r, bundled=source == "bundled")["display_name"]
                + " "
                + r["id"]
            ).casefold()
        ]
    bindings = (
        local_dependencies(settings.video_editing_native_bindings_file)
        if source == "external"
        else None
    )
    resources = [
        asset_metadata(
            row,
            bundled=source == "bundled",
            bindings=bindings,
            manifest=settings.video_editing_native_bindings_file,
        )
        for row in rows[offset : offset + limit]
    ]
    return {
        "release": MOTION_SHA256,
        "source": source,
        "total": len(rows),
        "resources": resources,
        "next_offset": offset + limit if offset + limit < len(rows) else None,
        "external_files_available": (
            any(row.get("local_dependency_state") == "verified" for row in resources)
            if source == "external"
            else None
        ),
        "website_runtime_validation": "unverified",
    }


@router.get("/editing-library/assets/{asset_id}/audio")
def preview_audio(
    asset_id: str,
    request: Request,
    workspace: VideoWorkspace,
) -> FileResponse:
    package = enabled(request).video_editing_library_dir
    try:
        asset, path = audio_asset(package, asset_id)
    except LookupError:
        raise ApiError(404, "EDITING_AUDIO_NOT_FOUND", "未找到原包音频。") from None
    except ValueError:
        raise ApiError(
            409, "EDITING_AUDIO_CHANGED", "原包音频摘要不符，请恢复原始资源。"
        ) from None
    media_type = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
    }[path.suffix.lower()]
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Cache-Control": "private, no-store",
            "ETag": '"' + asset["sha256"] + '"',
        },
    )


@router.post("/editing-tasks", response_model=EditingTaskResponse)
def create_task(
    body: EditingTaskCreate,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict[str, Any]:
    return submit_editing_task(body, request, workspace, session)


def submit_editing_task(
    body: EditingTaskCreate,
    request: Request,
    workspace: WorkspaceContext,
    session: Session,
) -> dict[str, Any]:
    require_workspace_write(workspace)
    row, created = persist_editing_task(body, enabled(request), workspace, session)
    if created:
        dispatch(request, row.id)
    return response(row, session)


def persist_editing_task(
    body: EditingTaskCreate,
    settings: Settings,
    workspace: WorkspaceContext,
    session: Session,
    *,
    preview_for: EditingPlanningTaskRecord | None = None,
    carried_revision: EditingCarriedRevision | None = None,
) -> tuple[EditingTaskRecord, bool]:
    require_workspace_write(workspace)

    def lock_planning_row() -> EditingPlanningTaskRecord | None:
        if preview_for is None:
            return None
        planning = session.scalar(
            select(EditingPlanningTaskRecord)
            .where(
                EditingPlanningTaskRecord.id == preview_for.id,
                EditingPlanningTaskRecord.workspace_id == workspace.workspace_id,
                EditingPlanningTaskRecord.owner_user_id == workspace.principal.user_id,
                EditingPlanningTaskRecord.status == "completed",
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if planning is None:
            raise ApiError(
                409, "EDITING_PREVIEW_LINK_CHANGED", "已保存的规划暂不可用。"
            )
        return planning

    planning = lock_planning_row()

    def link_preview(task: EditingTaskRecord) -> bool:
        if planning is None:
            return False
        previous_result = planning.result
        if previous_result.get("preview_task_id") == task.id:
            return False
        if previous_result.get("preview_task_id"):
            raise ApiError(
                409, "EDITING_PREVIEW_LINK_CHANGED", "预览与已保存的规划不匹配。"
            )
        planning.result = {
            **previous_result,
            "preview_task_id": task.id,
        }
        planning.revision += 1
        return True

    payload = body.model_dump(mode="json")
    if payload["options"]["transcript_revision_id"] is None:
        # Preserve replay identity of tasks submitted before correction support.
        payload["options"].pop("transcript_revision_id")
    if payload["options"]["native_plan_id"] is None:
        payload["options"].pop("native_plan_id")
    carried = (
        {"carried_revision": carried_revision.model_dump(mode="json")}
        if carried_revision
        else {}
    )
    fingerprint = digest({**payload, **carried, "library_release": MOTION_SHA256})
    previous = session.scalar(
        select(EditingTaskRecord).where(
            EditingTaskRecord.workspace_id == workspace.workspace_id,
            EditingTaskRecord.owner_user_id == workspace.principal.user_id,
            EditingTaskRecord.request_id == str(body.request_id),
        )
    )
    if previous:
        if previous.request_hash != fingerprint:
            raise ApiError(
                409, "EDITING_REQUEST_REUSED", "此请求编号已用于不同的剪辑内容。"
            )
        if link_preview(previous):
            session.commit()
        return previous, False
    source: EditingSourceRecord | None
    if body.options.native_plan_id and body.generation_task_id:
        raise ApiError(
            422, "EDITING_NATIVE_SOURCE_REQUIRED", "请选择编排对应的原视频源。"
        )
    if body.options.transcript_revision_id and body.generation_task_id:
        raise ApiError(
            422, "EDITING_CORRECTION_SOURCE_REQUIRED", "请选择校对版本对应的原视频源。"
        )
    if body.generation_task_id:
        job = own_job(session, workspace, body.generation_task_id)
        if job.kind != "lipsync" or job.status != "completed" or not job.project_id:
            raise ApiError(409, "EDITING_SOURCE_NOT_READY", "请选择已完成的口播视频。")
        own_project(session, workspace, job.project_id)
        path = Path(job.details.get("result_path", ""))
        if not path.is_file():
            raise ApiError(
                409, "EDITING_SOURCE_MISSING", "原片暂不可用，请恢复原任务。"
            )
        version = (
            session.get(VideoScriptVersionRecord, job.confirmed_version_id)
            if job.confirmed_version_id
            else None
        )
        lineage = freeze_generation_source(job, version)
        source = EditingSourceRecord(
            id=str(uuid4()),
            workspace_id=workspace.workspace_id,
            owner_user_id=workspace.principal.user_id,
            project_id=job.project_id,
            confirmed_version_id=job.confirmed_version_id,
            generation_task_id=job.id,
            kind="generation_task",
            media_path=str(path.resolve()),
            media_sha256=sha256(path),
            details={
                "audio_policy": "source_video_audio",
                "generation_task_id": job.id,
                "generation_lineage": lineage,
            },
        )
        session.add(source)
    else:
        source = session.get(EditingSourceRecord, str(body.source_id))
        if (
            not source
            or source.workspace_id != workspace.workspace_id
            or source.owner_user_id != workspace.principal.user_id
        ):
            raise ApiError(404, "EDITING_SOURCE_NOT_FOUND", "未找到视频源。")
        own_project(session, workspace, source.project_id)
    if body.options.native_plan_id:
        admit_render_plan(
            session,
            settings,
            session.get(EditingNativePlanRecord, str(body.options.native_plan_id)),
            source,
            body.options,
        )
    if (
        body.options.preview_base
        and preview_base_attempt(session, settings, source, payload["options"]) is None
    ):
        raise ApiError(
            409,
            "EDITING_PREVIEW_BASE_INVALID",
            "上版预览与本次原片或编排不一致，或文件已变化，请重新读取预览。",
        )
    if body.options.transcript_revision_id:
        if not settings.video_editing_alignment_enabled:
            raise ApiError(503, "EDITING_ALIGNMENT_DISABLED", "本机校对对齐尚未启用。")
        revision = session.get(
            EditingTranscriptRevisionRecord, str(body.options.transcript_revision_id)
        )
        if (
            not revision
            or revision.source_id != source.id
            or revision.project_id != source.project_id
            or revision.workspace_id != workspace.workspace_id
            or revision.owner_user_id != workspace.principal.user_id
        ):
            raise ApiError(
                404, "EDITING_TRANSCRIPT_REVISION_NOT_FOUND", "未找到此视频的校对版本。"
            )
        if body.options.language != "zh":
            raise ApiError(
                422,
                "EDITING_ALIGNMENT_LANGUAGE_UNSUPPORTED",
                "目前校对对齐支持中文口播。",
            )
    row = EditingTaskRecord(
        id=str(uuid4()),
        workspace_id=workspace.workspace_id,
        owner_user_id=workspace.principal.user_id,
        project_id=source.project_id,
        source_id=source.id,
        request_id=str(body.request_id),
        request_hash=fingerprint,
        library_release=MOTION_SHA256,
        options=body.options.model_dump(mode="json"),
        checkpoint=carried,
    )
    session.add(row)
    link_preview(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        planning = lock_planning_row()
        concurrent = session.scalar(
            select(EditingTaskRecord).where(
                EditingTaskRecord.workspace_id == workspace.workspace_id,
                EditingTaskRecord.owner_user_id == workspace.principal.user_id,
                EditingTaskRecord.request_id == str(body.request_id),
            )
        )
        if concurrent and concurrent.request_hash == fingerprint:
            if link_preview(concurrent):
                session.commit()
            return concurrent, False
        raise ApiError(
            409, "EDITING_TASK_CONFLICT", "剪辑请求发生冲突，请刷新任务后重试。"
        ) from None
    return row, True


@router.get("/editing-tasks", response_model=list[EditingTaskResponse])
def list_tasks(
    workspace: VideoWorkspace,
    session: SessionDependency,
    project_id: UUID | None = None,
) -> list[dict[str, Any]]:
    query = (
        select(EditingTaskRecord, EditingSourceRecord)
        .join(
            EditingSourceRecord, EditingSourceRecord.id == EditingTaskRecord.source_id
        )
        .where(
            EditingTaskRecord.workspace_id == workspace.workspace_id,
            EditingTaskRecord.owner_user_id == workspace.principal.user_id,
        )
    )
    if project_id:
        query = query.where(EditingTaskRecord.project_id == str(project_id))
    rows = session.execute(
        query.order_by(
            EditingTaskRecord.created_at.desc(), EditingTaskRecord.id.desc()
        ).limit(100)
    ).all()
    if not rows:
        return []
    artifacts: dict[str, list[EditingArtifactRecord]] = defaultdict(list)
    for record in session.scalars(
        select(EditingArtifactRecord).where(
            EditingArtifactRecord.task_id.in_([row.id for row, _ in rows])
        )
    ):
        artifacts[record.task_id].append(record)
    return [
        response(row, session, source, artifacts=artifacts[row.id])
        for row, source in rows
    ]


@router.get("/editing-tasks/{task_id}", response_model=EditingTaskResponse)
def get_task(
    task_id: UUID,
    workspace: VideoWorkspace,
    session: SessionDependency,
    project_id: UUID | None = None,
) -> dict[str, Any]:
    row = own_task(session, workspace, str(task_id))
    if project_id is not None and row.project_id != str(project_id):
        raise ApiError(404, "EDITING_NOT_FOUND", "未找到剪辑任务。")
    return response(row, session)


@router.get("/editing-works", response_model=EditingWorksResponse)
def list_editing_works(
    workspace: VideoWorkspace,
    session: SessionDependency,
    keyword: Annotated[str, Query(max_length=120)] = "",
    before: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 24,
) -> dict[str, Any]:
    title = func.coalesce(
        func.nullif(
            func.trim(VideoProjectRecord.content["draft"]["name"].as_string()), ""
        ),
        "未命名项目",
    )
    query = (
        select(EditingTaskRecord, title, EditingArtifactRecord)
        .join(VideoProjectRecord, VideoProjectRecord.id == EditingTaskRecord.project_id)
        .join(
            EditingArtifactRecord, EditingArtifactRecord.task_id == EditingTaskRecord.id
        )
        .where(
            EditingTaskRecord.workspace_id == workspace.workspace_id,
            EditingTaskRecord.owner_user_id == workspace.principal.user_id,
            VideoProjectRecord.workspace_id == workspace.workspace_id,
            VideoProjectRecord.owner_user_id == workspace.principal.user_id,
            EditingTaskRecord.status == "completed",
            EditingArtifactRecord.role == "final",
        )
    )
    if term := keyword.strip():
        query = query.where(title.icontains(term, autoescape=True))
    if before:
        cursor = own_task(session, workspace, str(before))
        query = query.where(
            or_(
                EditingTaskRecord.created_at < cursor.created_at,
                and_(
                    EditingTaskRecord.created_at == cursor.created_at,
                    EditingTaskRecord.id < cursor.id,
                ),
            )
        )
    items: list[dict[str, Any]] = []
    results = session.execute(
        query.order_by(
            EditingTaskRecord.created_at.desc(), EditingTaskRecord.id.desc()
        ).execution_options(yield_per=32)
    )
    with results:
        for result in results:
            row, project_title, final = cast(
                tuple[EditingTaskRecord, str, EditingArtifactRecord], result
            )
            if not artifact_visible(row, final):
                continue
            if len(items) == limit:
                return {"items": items, "next_before": items[-1]["task_id"]}
            items.append(
                {
                    "task_id": row.id,
                    "project_id": row.project_id,
                    "project_title": project_title,
                    "created_at": row.created_at
                    if row.created_at.tzinfo
                    else row.created_at.replace(tzinfo=UTC),
                    "mode": row.options.get("mode", "subtitles"),
                    "final": artifact_response(row, final),
                }
            )
    return {"items": items, "next_before": None}


@router.get(
    "/projects/{project_id}/editing-template-samples",
    response_model=list[EditingTemplateSample],
)
def list_template_samples(
    project_id: UUID,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> list[dict[str, Any]]:
    settings = enabled(request)
    own_project(session, workspace, str(project_id))
    active_templates = {template["id"] for template in overlay_templates()}
    template_id = EditingNativePlanRecord.recipes["overlay_template_id"].as_string()
    query = (
        select(EditingTaskRecord, EditingArtifactRecord, template_id)
        .select_from(EditingTaskRecord)
        .join(
            EditingNativePlanRecord,
            and_(
                EditingNativePlanRecord.id
                == EditingTaskRecord.options["native_plan_id"].as_string(),
                EditingNativePlanRecord.project_id == EditingTaskRecord.project_id,
                EditingNativePlanRecord.workspace_id == EditingTaskRecord.workspace_id,
                EditingNativePlanRecord.owner_user_id
                == EditingTaskRecord.owner_user_id,
                EditingNativePlanRecord.source_id == EditingTaskRecord.source_id,
                EditingNativePlanRecord.library_release == MOTION_SHA256,
            ),
        )
        .join(
            EditingArtifactRecord, EditingArtifactRecord.task_id == EditingTaskRecord.id
        )
        .where(
            EditingTaskRecord.project_id == str(project_id),
            EditingTaskRecord.workspace_id == workspace.workspace_id,
            EditingTaskRecord.owner_user_id == workspace.principal.user_id,
            EditingTaskRecord.library_release == MOTION_SHA256,
            EditingTaskRecord.status == "completed",
            EditingTaskRecord.options["mode"].as_string() == "native_plan",
            EditingTaskRecord.options["delivery"].as_string() == "preview_first",
            EditingArtifactRecord.role == "final",
            EditingArtifactRecord.mime == "video/mp4",
            EditingArtifactRecord.validation["decoded"].as_boolean().is_(True),
            template_id.in_(active_templates),
        )
        .order_by(EditingTaskRecord.created_at.desc(), EditingTaskRecord.id.desc())
    )
    samples: dict[str, dict[str, Any]] = {}
    with session.execute(query, execution_options={"yield_per": 32}) as results:
        for row, final, chosen_template in results.tuples():
            if chosen_template in samples or not artifact_visible(row, final):
                continue
            counts = final.validation.get("motion_counts")
            if (
                not isinstance(counts, dict)
                or type(counts.get("distinct_groups")) is not int
                or type(counts.get("occurrences")) is not int
                or not counts["occurrences"]
                >= counts["distinct_groups"]
                >= MIN_OVERLAY_TYPES
                or not verified_delivery_file(
                    final, (settings.video_editing_tasks_dir / row.id).resolve()
                )
            ):
                continue
            samples[chosen_template] = {
                "template_id": chosen_template,
                "task_id": row.id,
                "motion_counts": counts,
                "final": artifact_response(row, final),
            }
            if len(samples) == len(active_templates):
                break
    return list(samples.values())


@router.post("/editing-tasks/{task_id}/cancel", response_model=EditingTaskResponse)
def cancel_task(
    task_id: UUID, workspace: VideoWorkspace, session: SessionDependency
) -> dict[str, Any]:
    require_workspace_write(workspace)
    row = own_task(session, workspace, str(task_id))
    session.execute(
        update(EditingTaskRecord)
        .execution_options(synchronize_session=False)
        .where(
            EditingTaskRecord.id == row.id,
            EditingTaskRecord.status.in_(["queued", "running"]),
        )
        .values(
            cancel_requested=True,
            revision=EditingTaskRecord.revision + 1,
            status=case(
                (EditingTaskRecord.status == "queued", "cancelled"),
                else_=EditingTaskRecord.status,
            ),
            stage=case(
                (EditingTaskRecord.status == "queued", "cancelled"),
                else_=EditingTaskRecord.stage,
            ),
        )
    )
    session.commit()
    session.refresh(row)
    return response(row, session)


@router.post("/editing-tasks/{task_id}/retry", response_model=EditingTaskResponse)
def retry_task(
    task_id: UUID,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict[str, Any]:
    require_workspace_write(workspace)
    enabled(request)
    row = own_task(session, workspace, str(task_id))
    checkpoint = {**row.checkpoint, "dispatch_not_before": 0}
    checkpoint.pop("layout_findings", None)
    result = session.execute(
        update(EditingTaskRecord)
        .where(
            EditingTaskRecord.id == row.id,
            EditingTaskRecord.status.in_(["failed", "cancelled"]),
        )
        .values(
            status="queued",
            stage="queued",
            cancel_requested=False,
            error_code=None,
            owner_token=None,
            lease_until=None,
            checkpoint=checkpoint,
            revision=EditingTaskRecord.revision + 1,
        )
    )
    if not cast(CursorResult, result).rowcount:
        session.rollback()
        raise ApiError(409, "EDITING_RETRY_STATE", "只有失败或已取消的任务可以重试。")
    session.commit()
    session.refresh(row)
    dispatch(request, row.id)
    return response(row, session)


@router.get("/editing-tasks/{task_id}/artifacts/{artifact_id}")
def artifact(
    task_id: UUID,
    artifact_id: UUID,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> FileResponse:
    row = own_task(session, workspace, str(task_id))
    record = session.get(EditingArtifactRecord, str(artifact_id))
    if not record or record.task_id != row.id or not artifact_visible(row, record):
        raise ApiError(404, "EDITING_ARTIFACT_NOT_FOUND", "未找到已校验的剪辑产物。")
    task_root = (request.app.state.settings.video_editing_tasks_dir / row.id).resolve()
    if not verified_delivery_file(record, task_root):
        raise ApiError(409, "EDITING_ARTIFACT_MISSING", "剪辑产物暂不可用。")
    path = Path(record.path).resolve()
    return FileResponse(
        path,
        media_type=record.mime,
        filename=f"{row.id}-{record.role}{path.suffix}",
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store"},
    )


@router.post(
    "/editing-tasks/{task_id}/repair-preview", response_model=EditingTaskResponse
)
def repair_preview(
    task_id: UUID,
    body: EditingExportConfirmation,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict[str, Any]:
    require_workspace_write(workspace)
    settings = enabled(request)
    row = own_task(session, workspace, str(task_id))
    own_project(session, workspace, row.project_id)
    preview_id, preview_sha = str(body.preview_artifact_id), body.preview_sha256

    def same_repair(current: EditingTaskRecord) -> bool:
        if current.status in {"queued", "running"}:
            repair = current.checkpoint.get("preview_repair", {})
        elif current.status in {"awaiting_review", "completed"}:
            repair = current.checkpoint.get("recovered_preview", {})
        else:
            return False
        return (repair.get("preview_id"), repair.get("preview_sha256")) == (
            preview_id,
            preview_sha,
        )

    if same_repair(row):
        return response(row, session)
    if (
        row.options.get("delivery") != "preview_first"
        or row.status != "awaiting_review"
    ):
        raise ApiError(409, "EDITING_EXPORT_REVIEW_STATE", "当前任务未等待高清确认。")
    preview = session.get(EditingArtifactRecord, preview_id)
    if not preview or (preview.task_id, preview.role, preview.sha256) != (
        row.id,
        "preview",
        preview_sha,
    ):
        raise ApiError(409, "EDITING_PREVIEW_CHANGED", "预览版本已更新，请刷新后查看。")
    task_root = (settings.video_editing_tasks_dir / row.id).resolve()
    master = session.scalar(
        select(EditingArtifactRecord).where(
            EditingArtifactRecord.task_id == row.id,
            EditingArtifactRecord.role == "staged_final",
        )
    )
    if (
        not master
        or preview.validation.get("decoded") is not True
        or preview.validation.get("native_render_sha256") != master.sha256
        or master.validation.get("sha256") != master.sha256
        or master.validation.get("decoded") is not True
        or not verified_delivery_file(master, task_root)
    ):
        raise ApiError(
            409, "EDITING_EXPORT_CHANGED", "高清母版无法核验，请从原编排重新生成预览。"
        )
    if verified_delivery_file(preview, task_root):
        raise ApiError(
            409, "EDITING_PREVIEW_INTACT", "当前代理文件可用，请重新打开播放器。"
        )
    updated = session.execute(
        update(EditingTaskRecord)
        .where(
            EditingTaskRecord.id == row.id,
            EditingTaskRecord.status == "awaiting_review",
            EditingTaskRecord.revision == row.revision,
            EditingTaskRecord.cancel_requested.is_(False),
        )
        .values(
            status="queued",
            stage="queued",
            revision=EditingTaskRecord.revision + 1,
            checkpoint={
                **row.checkpoint,
                "dispatch_not_before": 0,
                "preview_repair": {
                    "preview_id": preview_id,
                    "preview_sha256": preview_sha,
                    "master_id": master.id,
                    "master_sha256": master.sha256,
                },
            },
        )
    )
    if not cast(CursorResult, updated).rowcount:
        session.rollback()
        current = own_task(session, workspace, str(task_id))
        if same_repair(current):
            return response(current, session)
        raise ApiError(409, "EDITING_PREVIEW_CHANGED", "预览状态已更新，请刷新后查看。")
    session.commit()
    session.refresh(row)
    dispatch(request, row.id)
    return response(row, session)


@router.post(
    "/editing-tasks/{task_id}/confirm-export", response_model=EditingTaskResponse
)
def confirm_export(
    task_id: UUID,
    body: EditingExportConfirmation,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict[str, Any]:
    require_workspace_write(workspace)
    settings = enabled(request)
    row = own_task(session, workspace, str(task_id))
    own_project(session, workspace, row.project_id)
    confirmation = {
        "preview_id": str(body.preview_artifact_id),
        "preview_sha256": body.preview_sha256,
    }

    def confirmed(current: EditingTaskRecord) -> bool:
        saved = current.checkpoint.get("export_confirmation", {})
        return current.status == "completed" and all(
            saved.get(key) == value for key, value in confirmation.items()
        )

    if row.options.get("delivery") != "preview_first":
        raise ApiError(
            409, "EDITING_EXPORT_REVIEW_STATE", "请选择需要预览确认的剪辑任务。"
        )
    if confirmed(row):
        return response(row, session)
    if row.status != "awaiting_review" or row.cancel_requested:
        raise ApiError(409, "EDITING_EXPORT_REVIEW_STATE", "当前任务未等待高清确认。")
    preview = session.get(EditingArtifactRecord, confirmation["preview_id"])
    if not preview or (preview.task_id, preview.role, preview.sha256) != (
        row.id,
        "preview",
        body.preview_sha256,
    ):
        raise ApiError(
            409, "EDITING_PREVIEW_CHANGED", "预览版本不一致，请重新读取并查看。"
        )
    master = session.scalar(
        select(EditingArtifactRecord).where(
            EditingArtifactRecord.task_id == row.id,
            EditingArtifactRecord.role == "staged_final",
        )
    )
    if not master:
        session.refresh(row)
        if confirmed(row):
            return response(row, session)
    root = (settings.video_editing_tasks_dir / row.id).resolve()
    if (
        not master
        or preview.validation.get("native_render_sha256") != master.sha256
        or not preview.validation.get("decoded")
        or not master.validation.get("decoded")
    ):
        raise ApiError(
            409, "EDITING_EXPORT_CHANGED", "待交付的高清文件与预览校验不一致。"
        )
    if not all(verified_delivery_file(record, root) for record in (preview, master)):
        raise ApiError(
            409, "EDITING_EXPORT_CHANGED", "预览或待交付文件已变化，请重新生成预览。"
        )
    result = session.execute(
        update(EditingTaskRecord)
        .where(
            EditingTaskRecord.id == row.id,
            EditingTaskRecord.status == "awaiting_review",
            EditingTaskRecord.revision == row.revision,
            EditingTaskRecord.cancel_requested.is_(False),
        )
        .values(
            status="completed",
            stage="completed",
            revision=EditingTaskRecord.revision + 1,
            checkpoint={
                **row.checkpoint,
                "export_confirmation": {
                    **confirmation,
                    "final_id": master.id,
                    "final_sha256": master.sha256,
                    "confirmed_at": datetime.now(UTC).isoformat(),
                    "confirmed_by": workspace.principal.user_id,
                },
            },
        )
    )
    if not cast(CursorResult, result).rowcount:
        session.rollback()
        current = own_task(session, workspace, str(task_id))
        if confirmed(current):
            return response(current, session)
        raise ApiError(
            409, "EDITING_EXPORT_REVIEW_STATE", "任务状态已变化，请刷新后核对。"
        )
    master.role = "final"
    session.commit()
    session.refresh(row)
    return response(row, session)


@router.put("/editing-tasks/{task_id}/review", response_model=EditingTaskResponse)
def review_film(
    task_id: UUID,
    body: EditingFilmReviewWrite,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict[str, Any]:
    require_workspace_write(workspace)
    settings = enabled(request)
    row = own_task(session, workspace, str(task_id))
    own_project(session, workspace, row.project_id)
    final = session.get(EditingArtifactRecord, str(body.final_artifact_id))
    if (
        not final
        or (final.task_id, final.role, final.sha256)
        != (row.id, "final", body.final_sha256)
        or not artifact_visible(row, final)
        or final.validation.get("decoded") is not True
        or not verified_delivery_file(
            final, (settings.video_editing_tasks_dir / row.id).resolve()
        )
    ):
        raise ApiError(
            409, "EDITING_REVIEW_ARTIFACT_CHANGED", "请重新读取可下载的成片后验收。"
        )
    assessment = body.model_dump(mode="json", exclude={"expected_revision"})

    def same_review(task: EditingTaskRecord) -> bool:
        saved = task.checkpoint.get("manual_review", {})
        return all(saved.get(key) == value for key, value in assessment.items())

    if same_review(row):
        return response(row, session)
    if row.revision != body.expected_revision:
        raise ApiError(
            409, "EDITING_REVIEW_CHANGED", "验收记录已更新，请载入最新版本再保存。"
        )
    updated = session.execute(
        update(EditingTaskRecord)
        .where(
            EditingTaskRecord.id == row.id,
            EditingTaskRecord.status == "completed",
            EditingTaskRecord.revision == body.expected_revision,
        )
        .values(
            checkpoint={
                **row.checkpoint,
                "manual_review": {
                    **assessment,
                    "recorded_at": datetime.now(UTC).isoformat(),
                },
            },
            revision=EditingTaskRecord.revision + 1,
        )
    )
    if not cast(CursorResult, updated).rowcount:
        session.rollback()
        current = own_task(session, workspace, str(task_id))
        if same_review(current):
            return response(current, session)
        raise ApiError(
            409, "EDITING_REVIEW_CHANGED", "验收记录已更新，请载入最新版本再保存。"
        )
    session.commit()
    session.refresh(row)
    return response(row, session)
