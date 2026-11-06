"""Keep user-uploaded avatars within their owning workspace and account."""

from sqlalchemy import exists, or_, select
from sqlalchemy.sql.elements import ColumnElement

from .auth import WorkspaceContext
from .video_generation_models import VideoAvatarRecord, VideoGenerationRecord


def avatar_scope(workspace: WorkspaceContext) -> ColumnElement[bool]:
    return or_(
        VideoAvatarRecord.source == "quanyu_public",
        VideoAvatarRecord.id == "self-presenter-female-v1",
        exists(
            select(VideoGenerationRecord.id).where(
                VideoGenerationRecord.avatar_id == VideoAvatarRecord.id,
                VideoGenerationRecord.kind == "h3_template",
                VideoGenerationRecord.workspace_id == workspace.workspace_id,
                VideoGenerationRecord.owner_user_id == workspace.principal.user_id,
            )
        ),
    )
