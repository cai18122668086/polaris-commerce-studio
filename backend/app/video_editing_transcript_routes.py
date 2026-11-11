"""Immutable, owner-scoped correction revisions; saving never changes a film."""

import difflib
import hashlib
from datetime import UTC
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .auth import SessionDependency, require_workspace_write
from .errors import ApiError
from .video_editing_contracts import (
    EditingTranscriptRevisionCreate,
    EditingTranscriptRevisionResponse,
)
from .video_editing_task_models import (
    EditingArtifactRecord,
    EditingTranscriptRevisionRecord,
)
from .video_editing_task_routes import enabled, own_task
from .video_editing_transcript_store import read_transcript_artifact as read_transcript
from .video_studio_routes import VideoWorkspace, digest

router = APIRouter(
    prefix="/api/v1/video-studio/workspaces/{workspace_id}",
    tags=["video-editing-transcripts"],
)


def revision_response(row: EditingTranscriptRevisionRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "source_id": row.source_id,
        "base_task_id": row.base_task_id,
        "base_transcript_artifact_id": row.base_transcript_artifact_id,
        "base_transcript_sha256": row.base_transcript_sha256,
        "parent_revision_id": row.parent_revision_id,
        "corrected_text": row.corrected_text,
        "text_sha256": row.text_sha256,
        "text_status": row.text_status,
        "timing_review": "unreviewed",
        "changes": row.details.get("changes", []),
        "created_at": row.created_at.replace(tzinfo=UTC)
        if row.created_at.tzinfo is None
        else row.created_at,
    }


@router.get("/editing-tasks/{task_id}/transcript")
def get_transcript(
    task_id: UUID,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict[str, Any]:
    settings = enabled(request)
    task = own_task(session, workspace, str(task_id))
    record = session.scalar(
        select(EditingArtifactRecord).where(
            EditingArtifactRecord.task_id == task.id,
            EditingArtifactRecord.role == "transcript",
        )
    )
    transcript = read_transcript(record, task, settings.video_editing_tasks_dir)
    assert record is not None
    return {
        "artifact_id": record.id,
        "artifact_sha256": record.sha256,
        "source_id": task.source_id,
        "language": transcript.language,
        "text": "".join(t.text for t in transcript.tokens),
        "text_revision_id": transcript.text_revision_id,
        "text_status": transcript.text_status,
        "timing_review": transcript.timing_review,
        "warnings": transcript.warnings,
        "tokens": [t.model_dump() for t in transcript.tokens],
        "utterances": [u.model_dump() for u in transcript.utterances],
        "alignment_available": settings.video_editing_alignment_enabled,
        **(
            {"analysis_audio_offset_ms": record.validation["analysis_audio_offset_ms"]}
            if "analysis_audio_offset_ms" in record.validation
            else {}
        ),
    }


@router.post(
    "/editing-tasks/{task_id}/transcript-revisions",
    response_model=EditingTranscriptRevisionResponse,
)
def save_revision(
    task_id: UUID,
    body: EditingTranscriptRevisionCreate,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict[str, Any]:
    require_workspace_write(workspace)
    settings = enabled(request)
    task = own_task(session, workspace, str(task_id))
    payload = body.model_dump(mode="json")
    if payload["parent_revision_id"] is None:
        payload.pop("parent_revision_id")
    fingerprint = digest({"task_id": task.id, **payload})
    previous = session.scalar(
        select(EditingTranscriptRevisionRecord).where(
            EditingTranscriptRevisionRecord.workspace_id == workspace.workspace_id,
            EditingTranscriptRevisionRecord.owner_user_id
            == workspace.principal.user_id,
            EditingTranscriptRevisionRecord.request_id == str(body.request_id),
        )
    )
    if previous:
        if previous.request_hash != fingerprint:
            raise ApiError(
                409, "EDITING_TRANSCRIPT_REQUEST_REUSED", "请求编号已用于另一版本文字。"
            )
        return revision_response(previous)
    artifact = session.get(EditingArtifactRecord, str(body.base_transcript_artifact_id))
    parent = read_transcript(artifact, task, settings.video_editing_tasks_dir)
    assert artifact is not None
    if parent.language != "zh":
        raise ApiError(
            422, "EDITING_ALIGNMENT_LANGUAGE_UNSUPPORTED", "目前校对对齐支持中文口播。"
        )
    parent_revision_id = (
        str(body.parent_revision_id)
        if body.parent_revision_id
        else parent.text_revision_id
    )
    comparison_text = "".join(t.text for t in parent.tokens)
    if parent_revision_id:
        ancestor = session.get(EditingTranscriptRevisionRecord, parent_revision_id)
        if (
            not ancestor
            or ancestor.source_id != task.source_id
            or ancestor.workspace_id != task.workspace_id
            or ancestor.owner_user_id != task.owner_user_id
        ):
            raise ApiError(
                409, "EDITING_TRANSCRIPT_LINEAGE_INVALID", "校对记录来源不一致。"
            )
        comparison_text = ancestor.corrected_text
    original = comparison_text
    changes = [
        {
            "operation": op,
            "before": original[a:b],
            "after": body.corrected_text[c:d],
            "before_char_range": [a, b],
            "after_char_range": [c, d],
        }
        for op, a, b, c, d in difflib.SequenceMatcher(
            None,
            original,
            body.corrected_text,
            autojunk=max(len(original), len(body.corrected_text)) > 2000,
        ).get_opcodes()
        if op != "equal"
    ]
    row = EditingTranscriptRevisionRecord(
        id=str(uuid4()),
        workspace_id=workspace.workspace_id,
        owner_user_id=workspace.principal.user_id,
        project_id=task.project_id,
        source_id=task.source_id,
        base_task_id=task.id,
        base_transcript_artifact_id=artifact.id,
        base_transcript_sha256=artifact.sha256,
        parent_revision_id=parent_revision_id,
        request_id=str(body.request_id),
        request_hash=fingerprint,
        corrected_text=body.corrected_text,
        text_sha256=hashlib.sha256(body.corrected_text.encode()).hexdigest(),
        text_status=body.text_status,
        details={
            "changes": changes,
            "comparison_text_sha256": hashlib.sha256(
                comparison_text.encode()
            ).hexdigest(),
            "attests_spoken_text": body.attests_spoken_text,
            "source_sha256": parent.source_sha256,
            "audio_sha256": parent.audio_sha256,
            "duration_ms": parent.duration_ms,
        },
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        concurrent = session.scalar(
            select(EditingTranscriptRevisionRecord).where(
                EditingTranscriptRevisionRecord.workspace_id == workspace.workspace_id,
                EditingTranscriptRevisionRecord.owner_user_id
                == workspace.principal.user_id,
                EditingTranscriptRevisionRecord.request_id == str(body.request_id),
            )
        )
        if concurrent and concurrent.request_hash == fingerprint:
            return revision_response(concurrent)
        raise ApiError(
            409, "EDITING_TRANSCRIPT_CONFLICT", "文字版本保存冲突，请刷新后重试。"
        ) from None
    return revision_response(row)


@router.get(
    "/editing-tasks/{task_id}/transcript-revisions",
    response_model=list[EditingTranscriptRevisionResponse],
)
def list_revisions(
    task_id: UUID,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> list[dict[str, Any]]:
    task = own_task(session, workspace, str(task_id))
    return [
        revision_response(r)
        for r in session.scalars(
            select(EditingTranscriptRevisionRecord)
            .where(
                EditingTranscriptRevisionRecord.source_id == task.source_id,
                EditingTranscriptRevisionRecord.workspace_id == workspace.workspace_id,
                EditingTranscriptRevisionRecord.owner_user_id
                == workspace.principal.user_id,
            )
            .order_by(EditingTranscriptRevisionRecord.created_at.desc())
            .limit(100)
        )
    ]
