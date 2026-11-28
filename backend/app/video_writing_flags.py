"""第三轮爆款文案的功能开关（``POLARIS_VIDEO_WRITING_BRIEF_V2`` + 灰度名单）.

Off (the default) means exactly the b2199c02 behaviour, including putting every
checked draft into the script library at once. On, only the users listed in
``POLARIS_VIDEO_WRITING_BRIEF_V2_USERS`` get the new flow; an empty list with
the switch on means nobody.
"""

from __future__ import annotations

from typing import Any


def brief_v2_users(settings: Any) -> set[str]:
    raw = str(getattr(settings, "video_writing_brief_v2_users", "") or "")
    return {piece.strip() for piece in raw.split(",") if piece.strip()}


def brief_v2_enabled(settings: Any, user_id: str | None) -> bool:
    if not bool(getattr(settings, "video_writing_brief_v2", False)):
        return False
    return bool(user_id) and user_id in brief_v2_users(settings)
