"""Use one durable preview submission for manual and automatic planning results."""

from typing import cast
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import and_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from .auth import (
    Principal,
    WorkspaceContext,
    require_workspace,
    require_workspace_write,
)
from .config import Settings
from .domain import UserStatus
from .errors import ApiError
from .models import UserRecord
from .video_editing_apple_pipeline import suite_engine, verified_suite
from .video_editing_contracts import EditingTaskCreate
from .video_editing_native_plans import register_gateway_plan
from .video_editing_overlay_recipes import PROFILE_ID
from .video_editing_planning_store import require_active_planning_template
from .video_editing_task_models import (
    EditingNativePlanRecord,
    EditingPlanningTaskRecord,
    EditingTaskRecord,
)
from .video_editing_task_routes import own_project, own_task, persist_editing_task
from .video_studio_access import require_video_studio_access


def gateway_candidate(
    session: Session,
    settings: Settings,
    workspace: WorkspaceContext,
    row: EditingPlanningTaskRecord,
    *,
    revalidate: bool = False,
) -> EditingNativePlanRecord:
    require_active_planning_template(row.snapshot.get("overlay_template", {}).get("id"))
    if not settings.video_editing_native_plan_enabled:
        raise ApiError(503, "EDITING_NATIVE_PLAN_DISABLED", "原生编排服务尚未开放。")
    return register_gateway_plan(
        session,
        settings,
        workspace.workspace_id,
        workspace.principal.user_id,
        row.id,
        str(uuid5(NAMESPACE_URL, f"tengli:{PROFILE_ID}:{row.id}")),
        revalidate=revalidate,
    )


def persist_planning_preview(
    row: EditingPlanningTaskRecord,
    workspace: WorkspaceContext,
    session: Session,
    settings: Settings,
) -> tuple[EditingTaskRecord, bool]:
    require_workspace_write(workspace)
    request_id = uuid5(NAMESPACE_URL, f"tengli:planning-preview-v1:{row.id}")
    if saved := row.result.get("preview_task_id"):
        previous = own_task(session, workspace, saved)
        if (previous.request_id, previous.project_id, previous.source_id) != (
            str(request_id),
            row.project_id,
            row.source_id,
        ):
            raise ApiError(
                409, "EDITING_PREVIEW_LINK_CHANGED", "预览与已保存的规划不匹配。"
            )
        return previous, False
    if suite_engine(row.snapshot):
        from .video_editing_task_models import EditingSourceRecord

        source = session.get(EditingSourceRecord, row.source_id)
        if source is None:
            raise ApiError(404, "EDITING_SOURCE_NOT_FOUND", "未找到原片。")
        verified_suite(session, settings, row.id, source)
        payload = EditingTaskCreate.model_validate(
            {
                "request_id": request_id,
                "source_id": source.id,
                "options": {
                    "mode": "suite_plan",
                    "suite_plan_id": row.id,
                    "source_subtitles": row.snapshot["source_subtitles"],
                    "delivery": "preview_first",
                },
            }
        )
        return persist_editing_task(
            payload, settings, workspace, session, preview_for=row
        )
    candidate = gateway_candidate(session, settings, workspace, row)
    payload = EditingTaskCreate.model_validate(
        {
            "request_id": request_id,
            "source_id": candidate.source_id,
            "options": {
                "mode": "native_plan",
                "native_plan_id": candidate.id,
                "source_subtitles": candidate.details["source_subtitles"],
                "caption_font_id": candidate.recipes["design"]["caption_font_id"],
                "delivery": "preview_first",
                **(
                    {"native_edits": {"music": row.snapshot["music"]}}
                    if row.snapshot.get("music") in {"lower", "off"}
                    and (candidate.recipes.get("sound") or {}).get("music")
                    else {}
                ),
            },
        }
    )
    return persist_editing_task(payload, settings, workspace, session, preview_for=row)


def pending_auto_preview() -> ColumnElement[bool]:
    row = EditingPlanningTaskRecord
    return and_(
        row.status == "completed",
        row.mode == "generate",
        row.cancel_requested.is_(False),
        row.checkpoint["auto_preview"].as_boolean().is_(True),
        row.result["preview_task_id"].as_string().is_(None),
        row.result["auto_preview_error_code"].as_string().is_(None),
    )


def resume_auto_preview(
    task_id: str, settings: Settings, factory: sessionmaker[Session]
) -> None:
    with factory() as session:
        row = session.scalar(
            select(EditingPlanningTaskRecord).where(
                EditingPlanningTaskRecord.id == task_id, pending_auto_preview()
            )
        )
        if row is None:
            return
        try:
            if not settings.video_editing_enabled:
                raise ApiError(503, "EDITING_DISABLED", "剪辑服务尚未开放。")
            user = session.get(UserRecord, row.owner_user_id)
            if not user or user.status != UserStatus.ACTIVE.value:
                raise ApiError(403, "WORKSPACE_ACCESS_DENIED", "当前账户无法生成代理。")
            principal = require_video_studio_access(
                Principal(user_id=user.id, email=user.email_normalized)
            )
            workspace = require_workspace(row.workspace_id, principal, session)
            own_project(session, workspace, row.project_id)
            persist_planning_preview(row, workspace, session, settings)
            return
        except ApiError as error:
            code = error.code
        except (ValueError, KeyError, IndexError, TypeError, OSError):
            code = "EDITING_AUTO_PREVIEW_INPUT_INVALID"
        session.rollback()
        current = session.get(EditingPlanningTaskRecord, task_id)
        if current is None:
            return
        saved = session.execute(
            update(EditingPlanningTaskRecord)
            .where(
                EditingPlanningTaskRecord.id == task_id,
                EditingPlanningTaskRecord.revision == current.revision,
                pending_auto_preview(),
            )
            .values(
                result={**current.result, "auto_preview_error_code": code},
                revision=EditingPlanningTaskRecord.revision + 1,
            )
        )
        if cast(CursorResult, saved).rowcount:
            session.commit()
