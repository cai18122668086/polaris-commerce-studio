"""Replay manual adjustments on another frozen plan without guessing segments."""

from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.orm import Session

from .auth import WorkspaceContext
from .config import Settings
from .errors import ApiError
from .video_editing_contracts import (
    EditingCarriedRevision,
    EditingPreviewBase,
    EditingTaskCreate,
    NativeRenderEdits,
)
from .video_editing_native_plans import native_edit_transcript
from .video_editing_planning_preview import gateway_candidate
from .video_editing_preview_base import preview_base_attempt
from .video_editing_render_edits import SOURCE_GROUP
from .video_editing_task_models import (
    EditingNativePlanRecord,
    EditingPlanningTaskRecord,
    EditingSourceRecord,
    EditingTaskRecord,
)
from .video_editing_task_routes import own_task, persist_editing_task


def remap_edits(
    edits: NativeRenderEdits,
    previous: EditingNativePlanRecord,
    candidate: EditingNativePlanRecord,
) -> tuple[NativeRenderEdits, list[str]]:
    by_id = {beat["id"]: beat for beat in previous.semantic["beats"]}
    by_range = {
        (beat["first_token_id"], beat["last_token_id"]): beat
        for beat in candidate.semantic["beats"]
    }
    protected = set()

    def match(beat_id: str, *, source_only: bool = False) -> str:
        old = by_id.get(beat_id)
        if old is None:
            raise ApiError(
                409, "EDITING_REPLAN_BASE_INVALID", "原版已调整片段暂不可用。"
            )
        current = by_range.get((old["first_token_id"], old["last_token_id"]))
        if current is None or current["group_id"] == SOURCE_GROUP:
            raise ApiError(
                409,
                "EDITING_REPLAN_SEGMENT_CHANGED",
                "新规划已拆分、合并或移除此实录段，原版调整仍保留。请选择兼容规划。",
            )
        current_id = current["id"]
        if not source_only and (
            {key: value for key, value in old.items() if key not in {"id", "reason"}}
            != {
                key: value
                for key, value in current.items()
                if key not in {"id", "reason"}
            }
            or previous.recipes["entries"].get(beat_id)
            != candidate.recipes["entries"].get(current_id)
        ):
            raise ApiError(
                409,
                "EDITING_REPLAN_SLOT_CHANGED",
                "新规划改变了已调整片段的动效或原生素材槽，原版调整仍保留。",
            )
        protected.add(current_id)
        return current_id

    if edits.music == "lower" and not edits.music_track_id:
        old_music = (previous.recipes.get("sound") or {}).get("music", [])
        new_music = (candidate.recipes.get("sound") or {}).get("music", [])
        if old_music != new_music:
            raise ApiError(
                409,
                "EDITING_REPLAN_MUSIC_CHANGED",
                "新规划的背景音乐编排已变化，原版音乐设置仍保留。",
            )
    payload = edits.model_dump(mode="json")
    payload["source_only_beat_ids"] = [
        match(beat_id, source_only=True) for beat_id in edits.source_only_beat_ids
    ]
    for field in ("effect_edits", "highlight_edits", "image_edits"):
        for item in payload.get(field, []):
            item["beat_id"] = match(item["beat_id"])
    return NativeRenderEdits.model_validate(payload), sorted(protected)


def persist_revision_preview(
    row: EditingPlanningTaskRecord,
    base: EditingPreviewBase,
    workspace: WorkspaceContext,
    session: Session,
    settings: Settings,
) -> tuple[EditingTaskRecord, bool]:
    parent = own_task(session, workspace, str(base.task_id))
    source = session.get(EditingSourceRecord, parent.source_id)
    previous_id = parent.options.get("native_plan_id")
    edits = parent.options.get("native_edits")
    if (
        source is None
        or not previous_id
        or not edits
        or (parent.project_id, parent.source_id) != (row.project_id, row.source_id)
        or preview_base_attempt(
            session,
            settings,
            source,
            {
                "preview_base": base.model_dump(mode="json"),
                "native_plan_id": previous_id,
            },
        )
        is None
    ):
        raise ApiError(
            409,
            "EDITING_REPLAN_BASE_INVALID",
            "请选择同一原片已有人工调整且已验证的代理预览。",
        )
    previous = session.get(EditingNativePlanRecord, previous_id)
    if previous is None or (
        previous.workspace_id,
        previous.owner_user_id,
        previous.project_id,
        previous.source_id,
    ) != (
        parent.workspace_id,
        parent.owner_user_id,
        parent.project_id,
        parent.source_id,
    ):
        raise ApiError(409, "EDITING_REPLAN_BASE_INVALID", "原版编排暂不可用。")
    if (
        previous.base_transcript_sha256 != row.base_transcript_sha256
        or not previous.recipes.get("overlay_template_id")
        or previous.recipes.get("overlay_template_id")
        != row.snapshot.get("overlay_template", {}).get("id")
    ):
        raise ApiError(
            409,
            "EDITING_REPLAN_SOURCE_CHANGED",
            "继承调整需要同一份实录转录及组合模板，原版仍可查看。",
        )
    native_edit_transcript(session, settings, previous)
    candidate = gateway_candidate(session, settings, workspace, row)
    remapped, protected = remap_edits(
        NativeRenderEdits.model_validate(edits), previous, candidate
    )
    lineage = EditingCarriedRevision(
        planning_task_id=UUID(row.id), preview_base=base, protected_beat_ids=protected
    )
    request_id = uuid5(
        NAMESPACE_URL,
        f"tengli:revision-preview-v1:{row.id}:{parent.id}:{base.preview_sha256}",
    )
    body = EditingTaskCreate.model_validate(
        {
            "request_id": request_id,
            "source_id": candidate.source_id,
            "options": {
                "mode": "native_plan",
                "native_plan_id": candidate.id,
                "source_subtitles": candidate.details["source_subtitles"],
                "caption_font_id": candidate.recipes["design"]["caption_font_id"],
                "delivery": "preview_first",
                "native_edits": remapped,
            },
        }
    )
    return persist_editing_task(
        body, settings, workspace, session, carried_revision=lineage
    )
