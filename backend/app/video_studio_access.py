"""Single server-side gate for video access and all future video business APIs."""

from typing import Annotated

from fastapi import Depends

from .auth import Principal, get_principal
from .domain import UserStatus
from .errors import ApiError

_PREVIEW_EMAIL = "1474953130@qq.com"


def require_video_studio_access(
    principal: Annotated[Principal, Depends(get_principal)],
) -> Principal:
    # Only the authenticated principal is authoritative. Never read browser
    # email/capability headers, query parameters or a development-mode override.
    if (
        principal.status != UserStatus.ACTIVE
        or principal.email_verified is not True
        or (principal.email or "").strip().casefold() != _PREVIEW_EMAIL
    ):
        raise ApiError(404, "NOT_FOUND", "页面暂不可用。")
    return principal


VideoStudioDependency = Annotated[Principal, Depends(require_video_studio_access)]
