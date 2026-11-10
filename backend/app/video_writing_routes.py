"""Owned immutable writing documents; explicit draft adoption uses existing history."""

import copy
import subprocess
from datetime import UTC
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import APIRouter, BackgroundTasks, Request
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import SessionDependency, WorkspaceContext, require_workspace_write
from .config import Settings
from .errors import ApiError
from .models import utc_now
from .motion_library import WRITING_SHA256
from .video_assistance import (
    AssistanceResponse,
    BenchmarkExtractionSource,
    process,
    provider,
)
from .video_assistance import (
    response as task_response,
)
from .video_assistance_models import VideoAssistanceRecord
from .video_editing_task_routes import own_project
from .video_studio_models import VideoProjectRecord, VideoScriptVersionRecord
from .video_studio_routes import (
    VideoWorkspace,
    append_version,
    digest,
    project_response,
    remember,
    replay,
    version_response,
)
from .video_studio_schemas import VideoWriteResponse, VideoWritingOrigin
from .video_writing_contracts import (
    ApplyWritingDraft,
    FactReplacement,
    ReviseWritingDraft,
    SaveWritingFacts,
    SaveWritingReference,
    SaveWritingResult,
    WritingAnalysis,
    WritingDraft,
    WritingFacts,
    WritingReference,
    WritingStructureDraft,
    WritingTaskRequest,
    WritingVersionSources,
)
from .video_writing_models import VideoWritingAdoption, VideoWritingDocument
from .video_writing_provenance import matching_writing_origin, script_digest
from .video_writing_provider import (
    revised_draft,
    shape_check,
    structure_check,
    validate_analysis,
    validate_draft,
)
from .video_writing_rules import reference_from_project, verify_writing_package

router = APIRouter(
    prefix="/api/v1/video-studio/workspaces/{workspace_id}",
    tags=["video-writing-workflow"],
)


def enabled(request: Request) -> Settings:
    settings = request.app.state.settings
    if not settings.video_writing_workflow_enabled:
        raise ApiError(503, "VIDEO_WRITING_DISABLED", "拆解写稿流程尚未开放。")
    try:
        verify_writing_package(settings.video_writing_library_dir)
    except (ValueError, OSError):
        raise ApiError(
            503, "VIDEO_WRITING_METHODS_MISSING", "原写稿方法包尚未就绪。"
        ) from None
    return settings


def document_response(row: VideoWritingDocument) -> dict[str, Any]:
    created = row.created_at
    return {
        "id": row.id,
        "project_id": row.project_id,
        "kind": row.kind,
        "body": row.body,
        "body_sha256": row.body_sha256,
        "rules_release": row.rules_release,
        "reference_document_id": row.reference_document_id,
        "analysis_document_id": row.analysis_document_id,
        "facts_document_id": row.facts_document_id,
        "assistance_task_id": row.assistance_task_id,
        "created_at": created if created.tzinfo else created.replace(tzinfo=UTC),
        "review": "unreviewed",
    }


def own_document(
    session: Session,
    workspace: WorkspaceContext,
    document_id: str,
    kind: str | None = None,
) -> VideoWritingDocument:
    row = session.get(VideoWritingDocument, document_id)
    if (
        not row
        or row.workspace_id != workspace.workspace_id
        or row.owner_user_id != workspace.principal.user_id
        or (kind and row.kind != kind)
    ):
        raise ApiError(404, "VIDEO_WRITING_DOCUMENT_NOT_FOUND", "未找到这份文稿资料。")
    return row


def create_document(
    session: Session,
    workspace: WorkspaceContext,
    project_id: str,
    request_id: UUID,
    kind: str,
    body: dict,
    **parents: Any,
) -> VideoWritingDocument:
    fingerprint = digest(
        {"project_id": project_id, "kind": kind, "body": body, "parents": parents}
    )
    query = select(VideoWritingDocument).where(
        VideoWritingDocument.workspace_id == workspace.workspace_id,
        VideoWritingDocument.owner_user_id == workspace.principal.user_id,
        VideoWritingDocument.request_id == str(request_id),
    )
    existing = session.scalar(query)
    if existing:
        if existing.request_hash != fingerprint:
            raise ApiError(409, "VIDEO_REQUEST_REUSED", "此请求已用于其他资料。")
        return existing
    row = VideoWritingDocument(
        id=str(uuid4()),
        workspace_id=workspace.workspace_id,
        owner_user_id=workspace.principal.user_id,
        project_id=project_id,
        kind=kind,
        request_id=str(request_id),
        request_hash=fingerprint,
        body=body,
        body_sha256=digest(body),
        rules_release=WRITING_SHA256,
        **parents,
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(query)
        if existing and existing.request_hash == fingerprint:
            return existing
        raise ApiError(
            409, "VIDEO_REQUEST_REUSED", "资料保存发生冲突，请刷新。"
        ) from None
    return row


@router.get("/writing-config")
def config(request: Request, workspace: VideoWorkspace) -> dict:
    settings = request.app.state.settings
    return {
        "enabled": settings.video_writing_workflow_enabled,
        "can_generate": settings.video_writing_workflow_enabled
        and settings.video_script_planning_enabled,
        "rules_release": WRITING_SHA256,
    }


@router.get("/writing-documents")
def documents(
    project_id: UUID, workspace: VideoWorkspace, session: SessionDependency
) -> list[dict]:
    own_project(session, workspace, str(project_id))
    rows = session.scalars(
        select(VideoWritingDocument)
        .where(
            VideoWritingDocument.project_id == str(project_id),
            VideoWritingDocument.workspace_id == workspace.workspace_id,
            VideoWritingDocument.owner_user_id == workspace.principal.user_id,
        )
        .order_by(VideoWritingDocument.created_at.desc())
        .limit(200)
    )
    return [document_response(row) for row in rows]


@router.post("/writing-documents/reference")
def save_reference(
    body: SaveWritingReference,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict:
    require_workspace_write(workspace)
    enabled(request)
    previous = session.scalar(
        select(VideoWritingDocument).where(
            VideoWritingDocument.workspace_id == workspace.workspace_id,
            VideoWritingDocument.owner_user_id == workspace.principal.user_id,
            VideoWritingDocument.request_id == str(body.request_id),
        )
    )
    if previous:
        if (
            previous.kind == "reference"
            and previous.project_id == str(body.project_id)
            and previous.body.get("reference_id") == str(body.reference_id)
            and previous.body.get("source_project_revision") == body.expected_revision
        ):
            return document_response(previous)
        raise ApiError(409, "VIDEO_REQUEST_REUSED", "此请求已用于其他资料。")
    project = own_project(session, workspace, str(body.project_id))
    if project.revision != body.expected_revision:
        raise ApiError(
            409, "VIDEO_REVISION_CONFLICT", "项目已变化，请先保存并重新载入。"
        )
    ref = next(
        (
            r
            for r in project.content.get("references", [])
            if r["id"] == str(body.reference_id)
        ),
        None,
    )
    if not ref:
        raise ApiError(404, "VIDEO_REFERENCE_REQUIRED", "请先保存参考原文。")
    try:
        reference = reference_from_project(ref)
        reference.source_project_revision = project.revision
    except ValueError:
        raise ApiError(
            422, "VIDEO_REFERENCE_REQUIRED", "参考原文尚无可拆解的正文。"
        ) from None
    return document_response(
        create_document(
            session,
            workspace,
            project.id,
            body.request_id,
            "reference",
            reference.model_dump(mode="json"),
        )
    )


@router.post("/writing-documents/reference/from-benchmark/{task_id}")
def save_benchmark_reference(
    task_id: UUID,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict:
    require_workspace_write(workspace)
    enabled(request)
    task = session.get(VideoAssistanceRecord, str(task_id))
    if (
        task is None
        or task.workspace_id != workspace.workspace_id
        or task.owner_user_id != workspace.principal.user_id
        or task.kind != "extract"
        or not task.inputs.get("benchmark_source")
    ):
        raise ApiError(404, "VIDEO_ASSISTANCE_NOT_FOUND", "未找到该对标提取任务。")
    own_project(session, workspace, task.project_id)
    source = BenchmarkExtractionSource.model_validate(task.inputs["benchmark_source"])
    if task.status != "completed" or task.result.get("source_url") != source.source_url:
        raise ApiError(409, "VIDEO_TRANSCRIPT_NOT_READY", "本次提取原文尚未就绪。")
    try:
        reference = reference_from_project(
            {
                "id": task.id,
                "original_text": task.result.get("text", ""),
                "url": source.source_url,
                "note": (
                    f"抖音对标「{source.keyword}」作品 {source.platform_id}。"
                    f"搜索页 {source.search_task_id}，"
                    f"采集于 {source.captured_at.isoformat()}。"
                    "语音转写，正文待核对。"
                ),
            }
        )
        reference.source_project_revision = task.inputs["revision"]
    except ValueError:
        raise ApiError(
            422, "VIDEO_REFERENCE_REQUIRED", "本次提取无可拆解原文。"
        ) from None
    return document_response(
        create_document(
            session,
            workspace,
            task.project_id,
            uuid5(NAMESPACE_URL, f"tengli-benchmark-writing-reference:{task.id}"),
            "reference",
            reference.model_dump(mode="json"),
            assistance_task_id=task.id,
        )
    )


@router.post("/writing-documents/facts")
def save_facts(
    body: SaveWritingFacts,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict:
    require_workspace_write(workspace)
    enabled(request)
    own_project(session, workspace, str(body.project_id))
    return document_response(
        create_document(
            session,
            workspace,
            str(body.project_id),
            body.request_id,
            "facts",
            body.body.model_dump(mode="json"),
        )
    )


@router.post("/writing-tasks", response_model=AssistanceResponse)
def create_task(
    body: WritingTaskRequest,
    request: Request,
    background: BackgroundTasks,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> AssistanceResponse:
    require_workspace_write(workspace)
    settings = enabled(request)
    # Omitted mode preserves the idempotency key for existing shadow requests.
    parameters = body.model_dump(mode="json")
    if body.draft_mode is None:
        parameters.pop("draft_mode")
    fingerprint = digest({"workflow": "writing", **parameters})
    query = select(VideoAssistanceRecord).where(
        VideoAssistanceRecord.workspace_id == workspace.workspace_id,
        VideoAssistanceRecord.owner_user_id == workspace.principal.user_id,
        VideoAssistanceRecord.request_id == str(body.request_id),
    )
    existing = session.scalar(query)
    if existing:
        if existing.request_hash != fingerprint:
            raise ApiError(409, "VIDEO_REQUEST_REUSED", "此请求已提交过其他内容。")
        return task_response(existing)
    if not settings.video_script_planning_enabled:
        raise ApiError(503, "VIDEO_ASSISTANCE_DISABLED", "文稿模型服务尚未配置。")
    project = own_project(session, workspace, str(body.project_id))
    if project.revision != body.expected_revision:
        raise ApiError(409, "VIDEO_REVISION_CONFLICT", "项目已变化，请重新核对资料。")
    ref = own_document(session, workspace, str(body.reference_document_id), "reference")
    parents = [ref]
    inputs: dict[str, Any] = {
        "revision": project.revision,
        "reference_document_id": ref.id,
        "reference": ref.body,
        "target_duration_seconds": body.target_duration_seconds,
        "presentation": body.presentation,
    }
    if body.kind == "fact_draft":
        if not body.facts_document_id or not body.analysis_document_id:
            raise ApiError(
                422, "VIDEO_WRITING_INPUTS_REQUIRED", "请先保存拆解结果与用户事实卡。"
            )
        analysis = own_document(
            session, workspace, str(body.analysis_document_id), "analysis"
        )
        facts = own_document(session, workspace, str(body.facts_document_id), "facts")
        fact_card = WritingFacts.model_validate(facts.body)
        if not any(f.status == "user_declared" for f in fact_card.facts):
            raise ApiError(
                422, "VIDEO_WRITING_FACTS_REQUIRED", "请至少填写一项已知的用户事实。"
            )
        if analysis.reference_document_id != ref.id:
            raise ApiError(
                409,
                "VIDEO_WRITING_REFERENCE_CHANGED",
                "拆解对应另一份原文，请重新选择。",
            )
        parents += [analysis, facts]
        inputs.update(
            analysis_document_id=analysis.id,
            analysis=analysis.body,
            facts_document_id=facts.id,
            facts=facts.body,
            draft_mode=body.draft_mode or "shadow",
        )
    if any(p.project_id != project.id for p in parents):
        raise ApiError(404, "VIDEO_WRITING_DOCUMENT_NOT_FOUND", "资料属于另一项目。")
    task_id = str(uuid4())
    inputs["writing_task_id"] = task_id
    inputs["document_hashes"] = {p.id: p.body_sha256 for p in parents}
    row = VideoAssistanceRecord(
        id=task_id,
        workspace_id=workspace.workspace_id,
        owner_user_id=workspace.principal.user_id,
        project_id=project.id,
        request_id=str(body.request_id),
        request_hash=fingerprint,
        kind=body.kind,
        inputs=inputs,
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(query)
        if existing and existing.request_hash == fingerprint:
            return task_response(existing)
        raise ApiError(409, "VIDEO_REQUEST_REUSED", "文稿请求发生冲突。") from None
    background.add_task(
        process, request.app.state.session_factory, row.id, provider(request)
    )
    return task_response(row)


@router.post("/writing-documents/result")
def save_result(
    body: SaveWritingResult,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict:
    require_workspace_write(workspace)
    enabled(request)
    task = session.get(VideoAssistanceRecord, str(body.task_id))
    if (
        not task
        or task.workspace_id != workspace.workspace_id
        or task.owner_user_id != workspace.principal.user_id
    ):
        raise ApiError(404, "VIDEO_WRITING_TASK_NOT_FOUND", "未找到文稿任务。")
    if (
        task.kind not in {"ref_analysis", "fact_draft"}
        or task.status != "completed"
        or task.result.get("validation_error")
    ):
        raise ApiError(
            409,
            "VIDEO_WRITING_RESULT_UNAVAILABLE",
            "只有通过结构检查的完成结果可以保存。",
        )
    parents = {
        key: task.inputs[key]
        for key in (
            "reference_document_id",
            "analysis_document_id",
            "facts_document_id",
        )
        if key in task.inputs
    }
    for ident in parents.values():
        row = own_document(session, workspace, ident)
        if (
            row.project_id != task.project_id
            or row.body_sha256 != task.inputs["document_hashes"][ident]
        ):
            raise ApiError(409, "VIDEO_WRITING_INPUTS_CHANGED", "输入资料版本不一致。")
    kind = "analysis" if task.kind == "ref_analysis" else "draft"
    if kind == "analysis":
        parsed = WritingAnalysis.model_validate(task.result["analysis"])
        validate_analysis(
            parsed, WritingReference.model_validate(task.inputs["reference"])
        )
        content = parsed.model_dump(mode="json")
    else:
        draft_model = (
            WritingStructureDraft
            if task.inputs.get("draft_mode") == "structure"
            else WritingDraft
        )
        parsed_draft = draft_model.model_validate(task.result["draft"])
        text = validate_draft(
            parsed_draft,
            WritingReference.model_validate(task.inputs["reference"]),
            WritingFacts.model_validate(task.inputs["facts"]),
            WritingAnalysis.model_validate(task.inputs["analysis"]),
        )
        content = {
            "draft": parsed_draft.model_dump(mode="json"),
            "text": text,
            "shape_check": task.result["shape_check"],
        }
    return document_response(
        create_document(
            session,
            workspace,
            task.project_id,
            body.request_id,
            kind,
            content,
            assistance_task_id=task.id,
            **parents,
        )
    )


def revision_basis(
    session: Session, workspace: WorkspaceContext, parent: VideoWritingDocument
) -> tuple[dict, dict[str, VideoWritingDocument]]:
    def changed() -> ApiError:
        return ApiError(
            409, "VIDEO_WRITING_INPUTS_CHANGED", "写稿所用的原资料版本不一致。"
        )

    if (
        parent.rules_release != WRITING_SHA256
        or digest(parent.body) != parent.body_sha256
    ):
        raise changed()
    sources = {}
    for kind, ident in (
        ("reference", parent.reference_document_id),
        ("analysis", parent.analysis_document_id),
        ("facts", parent.facts_document_id),
    ):
        if ident is None:
            raise changed()
        source = own_document(session, workspace, ident, kind)
        if (
            source.project_id != parent.project_id
            or digest(source.body) != source.body_sha256
        ):
            raise changed()
        sources[kind] = source
    if sources["analysis"].reference_document_id != sources["reference"].id:
        raise changed()
    if parent.assistance_task_id:
        task = session.get(VideoAssistanceRecord, parent.assistance_task_id)
        if not task or (
            task.workspace_id,
            task.owner_user_id,
            task.project_id,
            task.kind,
            task.status,
        ) != (
            parent.workspace_id,
            parent.owner_user_id,
            parent.project_id,
            "fact_draft",
            "completed",
        ):
            raise changed()
        basis = task.inputs
    else:
        basis = parent.body.get("revision", {})
    if basis.get("document_hashes") != {
        source.id: source.body_sha256 for source in sources.values()
    }:
        raise changed()
    return basis, sources


@router.get(
    "/projects/{project_id}/versions/{version_id}/writing-sources",
    response_model=WritingVersionSources,
)
def version_sources(
    project_id: UUID,
    version_id: UUID,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> WritingVersionSources:
    project = own_project(session, workspace, str(project_id))
    version = session.get(VideoScriptVersionRecord, str(version_id))
    if (
        not version
        or version.project_id != project.id
        or version.writing_origin is None
    ):
        raise ApiError(404, "VIDEO_WRITING_ORIGIN_NOT_FOUND", "该版文案没有写稿来源。")
    changed = ApiError(
        409, "VIDEO_WRITING_ORIGIN_CHANGED", "该版文案的写稿来源无法核对。"
    )
    origin = matching_writing_origin(version.writing_origin, version.snapshot)
    if origin is None:
        raise changed
    draft = own_document(session, workspace, origin["draft_document_id"], "draft")
    draft_text = draft.body.get("text")
    adoption = session.get(VideoWritingAdoption, origin["adoption_id"])
    adopted = (
        session.get(VideoScriptVersionRecord, adoption.script_version_id)
        if adoption
        else None
    )
    if (
        draft.project_id != project.id
        or not adoption
        or adoption.document_id != draft.id
        or not adopted
        or adopted.project_id != project.id
        or adopted.kind != "draft"
        or matching_writing_origin(adopted.writing_origin, adopted.snapshot) != origin
        or draft.reference_document_id != origin["reference_document_id"]
        or draft.analysis_document_id != origin["analysis_document_id"]
        or draft.facts_document_id != origin["facts_document_id"]
        or draft.body_sha256 != origin["draft_document_sha256"]
        or draft.rules_release != origin["rules_release"]
        or not isinstance(draft_text, str)
        or script_digest(draft_text) != origin["script_sha256"]
    ):
        raise changed
    _, sources = revision_basis(session, workspace, draft)
    try:
        return WritingVersionSources.model_validate(
            {
                "origin": origin,
                "reference": sources["reference"].body,
                "analysis": sources["analysis"].body,
                "facts": sources["facts"].body,
                "draft": draft.body["draft"],
            }
        )
    except (KeyError, ValueError):
        raise changed from None


@router.post("/writing-documents/{document_id}/revise")
def revise_draft(
    document_id: UUID,
    body: ReviseWritingDraft,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict:
    require_workspace_write(workspace)
    settings = enabled(request)
    parent = own_document(session, workspace, str(document_id), "draft")
    own_project(session, workspace, parent.project_id)
    basis, sources = revision_basis(session, workspace, parent)
    try:
        stored = parent.body["draft"]
        model = (
            WritingStructureDraft
            if stored.get("schema_version") == "tengli.structure-draft/1"
            else WritingDraft
        )
        previous = model.model_validate(stored)
        replacements = [
            FactReplacement.model_validate(row)
            for row in basis.get(
                "source_replacements",
                [row.model_dump(mode="json") for row in previous.replacements],
            )
        ]
        reference = WritingReference.model_validate(sources["reference"].body)
        analysis = WritingAnalysis.model_validate(sources["analysis"].body)
        facts = WritingFacts.model_validate(sources["facts"].body)
        draft, text = revised_draft(
            previous, body, replacements, reference, facts, analysis
        )
        budget = {
            "target_duration_seconds": basis.get("target_duration_seconds"),
            "presentation": basis.get("presentation", "unspecified"),
        }
        if isinstance(draft, WritingDraft):
            with TemporaryDirectory(prefix="tengli-writing-review-") as work:
                check = shape_check(
                    settings, Path(work), budget, draft, reference, facts
                )
        else:
            check = structure_check(budget, text)
    except (OSError, subprocess.SubprocessError) as error:
        raise ApiError(
            503, "VIDEO_WRITING_METHODS_MISSING", "原写稿检查暂不可用。"
        ) from error
    except (KeyError, TypeError, ValueError) as error:
        raise ApiError(
            422,
            "VIDEO_WRITING_REVISION_INVALID",
            "修订未通过检查，请核对新增文字、每句的事实勾选和原段落。",
        ) from error
    if check["verdict"] == "FAIL":
        raise ApiError(
            422,
            "VIDEO_WRITING_SHAPE_INVALID",
            "修订未通过原逐句结构检查，请核对句数和对应原句。",
        )
    return document_response(
        create_document(
            session,
            workspace,
            parent.project_id,
            body.request_id,
            "draft",
            {
                "draft": draft.model_dump(mode="json"),
                "text": text,
                "shape_check": check,
                "revision": {
                    "parent_document_id": parent.id,
                    "parent_document_sha256": parent.body_sha256,
                    "document_hashes": basis["document_hashes"],
                    "source_replacements": [
                        row.model_dump(mode="json") for row in replacements
                    ],
                    **budget,
                },
            },
            **{kind + "_document_id": source.id for kind, source in sources.items()},
        )
    )


@router.post(
    "/writing-documents/{document_id}/apply", response_model=VideoWriteResponse
)
def apply_draft(
    document_id: UUID,
    body: ApplyWritingDraft,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> VideoWriteResponse:
    require_workspace_write(workspace)
    enabled(request)
    document = own_document(session, workspace, str(document_id), "draft")
    fingerprint = digest(
        {"writing_document_id": document.id, **body.model_dump(mode="json")}
    )
    previous = replay(session, workspace, body.request_id, fingerprint)
    if previous:
        return previous
    if digest(document.body) != document.body_sha256 or not all(
        (
            document.reference_document_id,
            document.analysis_document_id,
            document.facts_document_id,
        )
    ):
        raise ApiError(409, "VIDEO_WRITING_INPUTS_CHANGED", "输入资料版本不一致。")
    project = own_project(session, workspace, document.project_id)
    stored = document.body["draft"]
    draft_model = (
        WritingStructureDraft
        if stored.get("schema_version") == "tengli.structure-draft/1"
        else WritingDraft
    )
    draft = draft_model.model_validate(stored)
    if draft.missing_facts or document.body["shape_check"]["verdict"] == "FAIL":
        raise ApiError(
            409, "VIDEO_WRITING_REVIEW_REQUIRED", "请先补齐缺失事实并处理结构问题。"
        )
    content = copy.deepcopy(project.content)
    content["draft"].update(name=draft.title, text=document.body["text"], drive="text")
    adoption_id = str(uuid4())
    origin = VideoWritingOrigin.model_validate(
        {
            "adoption_id": adoption_id,
            "draft_document_id": document.id,
            "reference_document_id": document.reference_document_id,
            "analysis_document_id": document.analysis_document_id,
            "facts_document_id": document.facts_document_id,
            "draft_document_sha256": document.body_sha256,
            "rules_release": document.rules_release,
            "script_sha256": script_digest(document.body["text"]),
        }
    ).model_dump(mode="json")
    try:
        changed = session.execute(
            update(VideoProjectRecord)
            .where(
                VideoProjectRecord.id == project.id,
                VideoProjectRecord.revision == body.expected_revision,
            )
            .values(
                content=content,
                writing_origin=origin,
                revision=body.expected_revision + 1,
                updated_at=utc_now(),
            )
            .execution_options(synchronize_session=False)
        )
        if not cast(CursorResult, changed).rowcount:
            session.rollback()
            raise ApiError(
                409, "VIDEO_REVISION_CONFLICT", "当前草稿已变化，本次没有覆盖。"
            )
        session.refresh(project)
        version = append_version(
            session, project.id, content, "draft", writing_origin=origin
        )
        session.add(
            VideoWritingAdoption(
                id=adoption_id,
                document_id=document.id,
                script_version_id=version.id,
                request_id=str(body.request_id),
            )
        )
        result = VideoWriteResponse(
            project=project_response(project), version=version_response(version)
        )
        remember(session, workspace, body.request_id, fingerprint, result)
        session.commit()
        return result
    except IntegrityError:
        session.rollback()
        previous = replay(session, workspace, body.request_id, fingerprint)
        if previous:
            return previous
        raise ApiError(
            409, "VIDEO_REVISION_CONFLICT", "采用文稿发生冲突，请刷新后核对。"
        ) from None
